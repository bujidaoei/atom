"""Owned SDK worker. Credentials arrive over stdin, never argv or logs."""
import json
import logging
import sys
from urllib.parse import urlsplit

from .artifacts import ArtifactError, _describe
from .snapshots import MAX_ARCHIVE_BYTES


def service_error(error):
    """Translate only known status/code pairs; SDK text may contain secrets."""
    try:
        status, code = error.get_status_code(), error.get_error_code()
    except (KeyError, TypeError, ValueError):
        return ArtifactError('artifact_io_error')
    if status == 403 and code in ('InvalidAccessKeyId', 'InvalidSecurity', 'ExpiredToken', 'InvalidToken'):
        return ArtifactError('artifact_credentials_invalid')
    if status == 403 and code == 'SignatureDoesNotMatch':
        return ArtifactError('artifact_signature_invalid')
    if status == 403 and code in ('AccessDenied', 'AccessForbidden'):
        return ArtifactError('artifact_access_denied')
    if status == 404 and code == 'NoSuchKey':
        return ArtifactError('artifact_not_found')
    return ArtifactError('artifact_io_error')


def _read(client, bucket, key):
    response = client.get_object(Bucket=bucket, Key=key)
    raw = response['Body'].get_raw_stream()
    try:
        length = int(response.get('Content-Length', '-1'))
        if not 14 <= length <= MAX_ARCHIVE_BYTES or response.get('Content-Encoding'):
            raise ArtifactError('invalid_artifact')
        payload = bytearray()
        while chunk := raw.read(min(65536, MAX_ARCHIVE_BYTES + 1 - len(payload))):
            payload.extend(chunk)
            if len(payload) > MAX_ARCHIVE_BYTES:
                raise ArtifactError('invalid_artifact')
        if len(payload) != length:
            raise ArtifactError('invalid_artifact')
        return bytes(payload)
    finally:
        raw.close()


def transfer(control, payload):
    from qcloud_cos import CosConfig, CosS3Client
    from qcloud_cos.cos_exception import CosServiceError
    import requests

    class ImmutableSession(requests.Session):
        def prepare_request(self, request):
            if request.method.upper() == 'PUT':
                request.headers['x-cos-forbid-overwrite'] = 'true'
            return super().prepare_request(request)

    configuration = CosConfig(Region=control['region'], SecretId=control['access_key'],
        SecretKey=control['secret_key'], Endpoint=urlsplit(control['endpoint']).netloc,
        Scheme='https', Timeout=5, AllowRedirects=False, AutoSwitchDomainOnRetry=False,
        VerifySSL=True)
    key = control['prefix'] + '/snapshots/' + control['key'] + '.atomsnap'
    with ImmutableSession() as session:
        session.trust_env = False
        client = CosS3Client(configuration, retry=0, session=session)
        try:
            existing = _read(client, control['bucket'], key)
        except CosServiceError as error:
            if error.get_status_code() != 404 or error.get_error_code() != 'NoSuchKey':
                raise service_error(error) from None
            existing = None
        if existing is not None:
            if _describe(existing).key != control['key']:
                raise ArtifactError('artifact_digest_mismatch')
            if control['operation'] == 'put' and existing != payload:
                raise ArtifactError('artifact_digest_mismatch')
            return existing
        if control['operation'] == 'read':
            raise ArtifactError('artifact_not_found')
        if control['operation'] != 'put' or _describe(payload).key != control['key']:
            raise ArtifactError('invalid_artifact')
        try:
            client.put_object(Bucket=control['bucket'], Key=key, Body=payload,
                ACL='private', ContentType='application/octet-stream', EnableMD5=True)
        except CosServiceError as error:
            if error.get_status_code() != 409 or error.get_error_code() != 'ObjectAlreadyExists':
                raise service_error(error) from None
        # A successful upload alone is not a publication receipt. Verify readback.
        try:
            return _read(client, control['bucket'], key)
        except CosServiceError as error:
            raise service_error(error) from None


def main():
    logging.disable(logging.CRITICAL)
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    try:
        header = sys.stdin.buffer.readline(16385)
        if len(header) > 16384 or not header.endswith(b'\n'):
            raise ArtifactError('invalid_artifact')
        control = json.loads(header)
        payload = sys.stdin.buffer.read(MAX_ARCHIVE_BYTES + 1)
        if len(payload) > MAX_ARCHIVE_BYTES:
            raise ArtifactError('invalid_artifact')
        result = transfer(control, payload)
        if _describe(result).key != control['key']:
            raise ArtifactError('artifact_digest_mismatch')
        sys.stdout.buffer.write(b'OK\n' + result)
    except ArtifactError as error:
        sys.stdout.buffer.write(b'ERROR\n' + error.code.encode('ascii'))
    except Exception:
        # SDK exceptions may include signed URLs or request headers.
        sys.stdout.buffer.write(b'ERROR\nartifact_io_error')


if __name__ == '__main__':
    main()
