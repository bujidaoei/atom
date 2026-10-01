"""Strict signed console credentials bound to a persisted session.

Not wired to legacy cookies: rollout requires explicit durable-session cutover.
"""
import re

import jwt

from .access_repository import AccessError, AccessRepository, ConsoleSession

_CLAIMS = {'iss','aud','sub','sid','iat','exp','v'}
_TYPE = 'atom-console+jwt'


class DurableConsoleCredentials:
    def __init__(self, repository: AccessRepository, *, key: str, issuer: str, audience: str):
        if (not isinstance(key,str) or not 32<=len(key.encode('utf-8'))<=4096
                or any(not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',value) is None
                       for value in (issuer,audience))):
            raise ValueError('invalid_durable_credential_configuration')
        self.repository=repository
        self._key=key
        self.issuer,self.audience=issuer,audience

    def sign(self, *, user_id: str, session_id: str) -> str:
        """Sign only a currently valid stored session created after authentication."""
        session=self.repository.console_session(user_id=user_id,session_id=session_id)
        return jwt.encode({'iss':self.issuer,'aud':self.audience,'sub':session.user_id,
            'sid':session.id,'iat':session.created_at,'exp':session.expires_at,'v':1},
            self._key,algorithm='HS256',headers={'typ':_TYPE})

    def authenticate(self, token: str) -> ConsoleSession | None:
        if not isinstance(token,str) or not 1<=len(token)<=4096:
            return None
        try:
            header=jwt.get_unverified_header(token)
            if header!={'alg':'HS256','typ':_TYPE}:
                return None
            claims=jwt.decode(token,self._key,algorithms=['HS256'],issuer=self.issuer,audience=self.audience,
                              options={'require':sorted(_CLAIMS)})
        except (jwt.PyJWTError,ValueError,TypeError,OverflowError):
            return None
        if (set(claims)!=_CLAIMS or claims['iss']!=self.issuer or claims['aud']!=self.audience
                or type(claims['v']) is not int or claims['v']!=1
                or type(claims['iat']) is not int or type(claims['exp']) is not int
                or not isinstance(claims['sub'],str) or not isinstance(claims['sid'],str)):
            return None
        try:
            session=self.repository.console_session(user_id=claims['sub'],session_id=claims['sid'])
        except AccessError as error:
            if str(error)=='session_not_found':
                return None
            # Storage/schema failure is not an authentication denial. The HTTP
            # boundary must report unavailable, rather than deleting credentials.
            raise
        if (session.created_at,session.expires_at)!=(claims['iat'],claims['exp']):
            return None
        return session
