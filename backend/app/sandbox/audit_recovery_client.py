"""Bounded trusted recovery transport; no runtime grant-signing key required."""
import json
import re

from .client import AdminTransport, BrokerClientError, _json
from ..audit_archive import ArchiveError, MAX_ARCHIVE_BYTES, decode_archive


class AuditRecoveryClient(AdminTransport):
    def __init__(self, origin, admin_token, *, expected_image, expected_policy_digest, timeout=45):
        if (not isinstance(expected_image,str) or re.fullmatch(r'sha256:[0-9a-f]{64}',expected_image) is None or
                not isinstance(expected_policy_digest,str) or re.fullmatch(r'[0-9a-f]{64}',expected_policy_digest) is None):
            raise BrokerClientError('invalid_recovery_configuration')
        super().__init__(origin,admin_token,timeout=timeout)
        self._image, self._policy = expected_image, expected_policy_digest

    async def recover(self, payload, *, expected_sha256):
        try:
            archive = decode_archive(payload,expected_sha256=expected_sha256)
        except ArchiveError:
            raise BrokerClientError('invalid_recovery_archive') from None
        _, raw = await self._request('/v1/admin/audit/recover',payload,headers={
            'content-type':'application/octet-stream','x-atom-archive-sha256':expected_sha256},limit=MAX_ARCHIVE_BYTES+2048)
        value = _json(raw)
        if (set(value) != {'protocol','image','policy_digest','attempt_id','result'} or
                value['protocol'] != 'audit-recovery-v2' or value['image'] != self._image or value['policy_digest'] != self._policy or
                not isinstance(value['attempt_id'],str) or re.fullmatch(r'[0-9a-f]{32}',value['attempt_id']) is None):
            raise BrokerClientError('invalid_recovery_provenance')
        expected = dict(archive_sha256=expected_sha256,manifest=archive['manifest'],events=archive['events'],
            recovery_target='isolated_memory_database',deletion_authorized=False)
        if json.dumps(value['result'],sort_keys=True,separators=(',',':'),ensure_ascii=True) != json.dumps(expected,sort_keys=True,separators=(',',':'),ensure_ascii=True):
            raise BrokerClientError('recovery_payload_mismatch')
        return value
