"""Browser-bound private capabilities; no HTTP or console credential parsing."""
from dataclasses import dataclass, field
import hashlib
import hmac
import re
import secrets
import time

from .security_audit import record_content_transition
from .access_repository import AccessError, AccessRepository


@dataclass(frozen=True)
class AccessLimits:
    bootstrap_seconds: int = 120
    handoff_seconds: int = 120
    session_seconds: int = 900
    pending_per_binding: int = 32
    sessions_per_viewer_binding: int = 32

    def __post_init__(self):
        for value, maximum in ((self.bootstrap_seconds,120),(self.handoff_seconds,120),
                (self.session_seconds,900),(self.pending_per_binding,128),(self.sessions_per_viewer_binding,128)):
            if type(value) is not int or not 1<=value<=maximum:
                raise AccessError('invalid_access_configuration')


@dataclass(frozen=True)
class AccessCredential:
    secret: str = field(repr=False)
    expires_at: int


@dataclass(frozen=True)
class BrowserBootstrap(AccessCredential):
    challenge: str


@dataclass(frozen=True)
class ContentPrincipal:
    viewer_id: str
    source_session_id: str
    binding_id: str
    publication_generation: int
    expires_at: int


def _hex(value):
    if not isinstance(value,str) or re.fullmatch(r'[0-9a-f]{64}',value) is None:
        raise AccessError('content_access_denied')
    return value


def _hash(purpose, secret):
    return hashlib.sha256((purpose+':'+_hex(secret)).encode('ascii')).hexdigest()


def _active(row, now, terminal):
    if row is None or row[terminal] is not None or not row['created_at']<=now<row['expires_at']:
        raise AccessError('content_access_denied')


class ContentAccessRepository(AccessRepository):
    def __init__(self,path,*,limits: AccessLimits = AccessLimits(),**options):
        super().__init__(path,**options)
        self.limits=limits

    @staticmethod
    def _publication(db,binding_id,viewer=None,generation=None):
        row=db.execute('''SELECT p.generation,p.live,o.user_id FROM content_bindings b
            JOIN release_records r ON r.id=b.release_id AND r.project_id=b.project_id
            JOIN release_publications p ON p.project_id=b.project_id
            JOIN projects o ON o.id=b.project_id WHERE b.id=?''',(binding_id,)).fetchone()
        # A bootstrap is only a browser challenge, never content authority.
        # v16 allows a fresh owner handoff for retained, withdrawn snapshots;
        # generation checks still revoke every previously issued capability.
        retained = db.execute('PRAGMA user_version').fetchone()[0] in (16, 17, 18)
        if (row is None or (not row['live'] and not retained) or (viewer is not None and row['user_id']!=viewer)
                or (generation is not None and row['generation']!=generation)):
            raise AccessError('content_access_denied')
        return row['generation']

    @staticmethod
    def _source(db,viewer,session_id,now):
        row=db.execute('SELECT * FROM console_sessions WHERE id=? AND user_id=?',(session_id,viewer)).fetchone()
        _active(row,now,'revoked_at')
        return row

    def bootstrap(self,*,binding_id: str) -> BrowserBootstrap:
        self._identity(binding_id)
        with self._transaction() as db:
            now=int(time.time())
            self._publication(db,binding_id)
            count=db.execute('''SELECT nonce_hash FROM content_bootstraps
                WHERE binding_id=? AND consumed_at IS NULL AND expires_at>? LIMIT ?''',
                (binding_id,now,self.limits.pending_per_binding)).fetchall()
            if len(count)>=self.limits.pending_per_binding:raise AccessError('content_access_capacity')
            secret=secrets.token_hex(32);challenge=_hash('bootstrap',secret)
            expires=now+self.limits.bootstrap_seconds
            db.execute('INSERT INTO content_bootstraps VALUES (?,?,?,?,NULL)',(challenge,binding_id,now,expires))
            return BrowserBootstrap(secret,expires,challenge)

    def describe_handoff(self,*,viewer_id: str,source_session_id: str,binding_id: str,challenge: str) -> dict:
        """Authorized display metadata only; never allocates or consumes credentials."""
        self._user(viewer_id);self._identity(source_session_id);self._identity(binding_id);_hex(challenge)
        with self._transaction() as db:
            now=int(time.time())
            source=self._source(db,viewer_id,source_session_id,now)
            generation=self._publication(db,binding_id,viewer_id)
            bootstrap=db.execute('SELECT * FROM content_bootstraps WHERE nonce_hash=? AND binding_id=?',
                                 (challenge,binding_id)).fetchone()
            _active(bootstrap,now,'consumed_at')
            if db.execute('SELECT 1 FROM content_handoffs WHERE bootstrap_hash=?',(challenge,)).fetchone():
                raise AccessError('access_conflict')
            row=db.execute('SELECT b.project_id,b.release_id,r.revision_id,r.audience,r.created_at,'
                'o.title,p.release_id AS current_release_id,p.live FROM content_bindings b '
                'JOIN release_records r ON r.id=b.release_id AND r.project_id=b.project_id '
                'JOIN projects o ON o.id=b.project_id JOIN release_publications p ON p.project_id=b.project_id '
                'WHERE b.id=?',(binding_id,)).fetchone()
            return {'binding':binding_id,'projectId':row['project_id'],'projectTitle':row['title'],
                    'releaseId':row['release_id'],'revisionId':row['revision_id'],'audience':row['audience'],
                    'releaseCreatedAt':row['created_at'],'isCurrentRelease':bool(row['live'] and row['release_id']==row['current_release_id']),
                    'publicationGeneration':generation,'expiresAt':min(bootstrap['expires_at'],source['expires_at'])}

    def issue_handoff(self,*,viewer_id: str,source_session_id: str,binding_id: str,challenge: str) -> AccessCredential:
        """Only after authenticated, CSRF-protected console authorization."""
        self._user(viewer_id);self._identity(source_session_id);self._identity(binding_id);_hex(challenge)
        with self._transaction() as db:
            now=int(time.time())
            source=self._source(db,viewer_id,source_session_id,now)
            generation=self._publication(db,binding_id,viewer_id)
            bootstrap=db.execute('SELECT * FROM content_bootstraps WHERE nonce_hash=? AND binding_id=?',(challenge,binding_id)).fetchone()
            _active(bootstrap,now,'consumed_at')
            pending=db.execute('''SELECT token_hash FROM content_handoffs
                WHERE viewer_id=? AND binding_id=? AND consumed_at IS NULL AND expires_at>? LIMIT ?''',
                (viewer_id,binding_id,now,self.limits.pending_per_binding)).fetchall()
            if len(pending)>=self.limits.pending_per_binding:raise AccessError('content_access_capacity')
            expires=min(now+self.limits.handoff_seconds,source['expires_at'],bootstrap['expires_at'])
            secret=secrets.token_hex(32)
            db.execute('INSERT INTO content_handoffs VALUES (?,?,?,?,?,?,?,?,NULL)',
                (_hash('handoff',secret),challenge,binding_id,viewer_id,source_session_id,generation,now,expires))
            if db.execute('PRAGMA user_version').fetchone()[0] in (5,6,7,9,10,13,14,15,16, 17, 18):
                record_content_transition(db,kind='content.handoff.issued',user_id=viewer_id,
                    source_session_id=source_session_id,binding_id=binding_id,generation=generation,occurred_at=now)
            return AccessCredential(secret,expires)

    def exchange(self,*,binding_id: str,handoff: str,browser_nonce: str) -> AccessCredential:
        self._identity(binding_id)
        handoff_hash,bootstrap_hash=_hash('handoff',handoff),_hash('bootstrap',browser_nonce)
        with self._transaction() as db:
            now=int(time.time())
            row=db.execute('SELECT * FROM content_handoffs WHERE token_hash=? AND binding_id=?',(handoff_hash,binding_id)).fetchone()
            _active(row,now,'consumed_at')
            if not hmac.compare_digest(row['bootstrap_hash'],bootstrap_hash):raise AccessError('content_access_denied')
            bootstrap=db.execute('SELECT * FROM content_bootstraps WHERE nonce_hash=? AND binding_id=?',(bootstrap_hash,binding_id)).fetchone()
            _active(bootstrap,now,'consumed_at')
            source=self._source(db,row['viewer_id'],row['source_session_id'],now)
            self._publication(db,binding_id,row['viewer_id'],row['publication_generation'])
            active=db.execute('''SELECT token_hash FROM content_sessions
                WHERE viewer_id=? AND binding_id=? AND revoked_at IS NULL AND expires_at>? LIMIT ?''',
                (row['viewer_id'],binding_id,now,self.limits.sessions_per_viewer_binding)).fetchall()
            if len(active)>=self.limits.sessions_per_viewer_binding:raise AccessError('content_access_capacity')
            secret=secrets.token_hex(32)
            expires=min(now+self.limits.session_seconds,source['expires_at'])
            db.execute('UPDATE content_bootstraps SET consumed_at=? WHERE nonce_hash=?',(now,bootstrap_hash))
            db.execute('UPDATE content_handoffs SET consumed_at=? WHERE token_hash=?',(now,handoff_hash))
            db.execute('INSERT INTO content_sessions VALUES (?,?,?,?,?,?,?,?,NULL)',
                (_hash('session',secret),handoff_hash,binding_id,row['viewer_id'],row['source_session_id'],row['publication_generation'],now,expires))
            if db.execute('PRAGMA user_version').fetchone()[0] in (5,6,7,9,10,13,14,15,16, 17, 18):
                record_content_transition(db,kind='content.session.created',user_id=row['viewer_id'],
                    source_session_id=row['source_session_id'],binding_id=binding_id,
                    generation=row['publication_generation'],occurred_at=now)
            return AccessCredential(secret,expires)

    def authorize(self,*,binding_id: str,session_secret: str) -> ContentPrincipal:
        self._identity(binding_id)
        token_hash=_hash('session',session_secret)
        with self._transaction() as db:
            now=int(time.time())
            row=db.execute('SELECT * FROM content_sessions WHERE token_hash=? AND binding_id=?',(token_hash,binding_id)).fetchone()
            _active(row,now,'revoked_at')
            self._source(db,row['viewer_id'],row['source_session_id'],now)
            self._publication(db,binding_id,row['viewer_id'],row['publication_generation'])
            return ContentPrincipal(row['viewer_id'],row['source_session_id'],binding_id,row['publication_generation'],row['expires_at'])
