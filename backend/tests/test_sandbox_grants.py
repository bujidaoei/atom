from dataclasses import replace
import base64
import hashlib
import hmac
import json

import jwt
import pytest

from app.sandbox.grants import Grant, GrantCodec, GrantError


KEY = b"synthetic-grant-test-key-32-bytes-minimum"
NOW = 1000


@pytest.fixture
def grant():
    return Grant(jti="grant-1", org="org-1", project="project-1", run="run-1", attempt="attempt-1",
                 fence=1, base_revision="a" * 64, iat=NOW, exp=NOW + 60)


@pytest.fixture
def codec():
    return GrantCodec(KEY, clock=lambda: NOW)


def signed(claims, **kwargs):
    return jwt.encode(claims, KEY, algorithm="HS256", headers={"typ": "atom-sandbox+jwt", **kwargs})


def test_round_trip_and_scope(codec, grant):
    decoded = codec.verify(codec.issue(grant))
    assert decoded == grant
    assert decoded.fingerprint() == grant.fingerprint()
    decoded.require_scope(org=grant.org, project=grant.project, run=grant.run, attempt=grant.attempt, fence=1)
    for field, value in [("org", "other"), ("project", "other"), ("run", "other"), ("attempt", "other"), ("fence", 2), ("fence", True)]:
        scope = dict(org=grant.org, project=grant.project, run=grant.run, attempt=grant.attempt, fence=1)
        scope[field] = value
        with pytest.raises(GrantError, match="^grant_scope_mismatch$"):
            decoded.require_scope(**scope)


@pytest.mark.parametrize("field,value", [
    ("org", "../host"), ("project", "/host"), ("run", "x" * 65), ("attempt", ""),
    ("jti", "space value"), ("fence", True), ("fence", 0), ("fence", 1.0), ("fence", 2**63),
    ("base_revision", "A" * 64), ("profile", "shell"), ("iat", True), ("iat", NOW + 1),
    ("exp", NOW), ("exp", NOW + 901), ("exp", float(NOW + 60)),
    ("nbf", NOW - 1), ("iss", "other"), ("aud", ["atom-sandbox"]), ("sub", "admin"),
    ("host_path", "/etc"), ("exp", "1060"),
])
def test_signed_invalid_claims_rejected(codec, grant, field, value):
    claims = grant.claims()
    claims[field] = value
    with pytest.raises(GrantError, match="^invalid_grant$"):
        codec.verify(signed(claims))


def test_every_required_claim(codec, grant):
    for field in grant.claims():
        claims = grant.claims()
        del claims[field]
        with pytest.raises(GrantError, match="^invalid_grant$"):
            codec.verify(signed(claims))


def test_signature_purpose_algorithm_and_length(codec, grant):
    claims = grant.claims()
    for token in [jwt.encode(claims, b"different-synthetic-key-32-bytes-minimum", algorithm="HS256", headers={"typ": "atom-sandbox+jwt"}),
                  jwt.encode(claims, "", algorithm="none"),
                  jwt.encode(claims, KEY * 2, algorithm="HS512", headers={"typ": "atom-sandbox+jwt"}), signed(claims, typ="JWT"),
                  signed(claims, kid="external-key"), "x" * 8193, "not.a.token", "", None]:
        with pytest.raises(GrantError, match="^invalid_grant$"):
            codec.verify(token)


def test_duplicate_and_malformed_json_with_valid_signature(codec, grant):
    def token(header, payload):
        def encoded(data):
            return base64.urlsafe_b64encode(data).rstrip(b"=")
        message = encoded(header) + b"." + encoded(payload)
        return (message + b"." + encoded(hmac.digest(KEY, message, hashlib.sha256))).decode("ascii")
    header = b'{"alg":"HS256","typ":"atom-sandbox+jwt"}'
    payload = json.dumps(grant.claims()).encode()
    malformed = [payload[:-1] + b',"fence":1}', b'{"x":NaN}', b'[]', b'\xff', b'[' * 1100]
    for value in malformed:
        with pytest.raises(GrantError, match="^invalid_grant$"):
            codec.verify(token(header, value))
    with pytest.raises(GrantError):
        codec.verify(token(b'{"alg":"HS256","alg":"HS256","typ":"atom-sandbox+jwt"}', payload))


def test_tampering_payload_fails_cryptographic_verification(codec, grant):
    token = codec.issue(grant)
    header, _, signature = token.split(".")
    altered = json.dumps(replace(grant, project="other-project").claims()).encode()
    encoded = base64.urlsafe_b64encode(altered).rstrip(b"=").decode()
    with pytest.raises(GrantError, match="^invalid_grant$"):
        codec.verify(f"{header}.{encoded}.{signature}")


def test_exact_expiry_and_lifetime_boundaries(codec, grant):
    token = codec.issue(replace(grant, exp=NOW + 900))
    assert GrantCodec(KEY, clock=lambda: NOW + 899).verify(token).exp == NOW + 900
    with pytest.raises(GrantError):
        GrantCodec(KEY, clock=lambda: NOW + 900).verify(token)
    with pytest.raises(GrantError):
        GrantCodec(KEY, clock=lambda: NOW - 1).verify(token)
    with pytest.raises(GrantError):
        codec.issue(replace(grant, exp=NOW + 901))


@pytest.mark.parametrize("key", [b"short", b"x" * 129, "x" * 40])
def test_key_config_fails_without_echoing_value(key):
    with pytest.raises(ValueError, match="^invalid_grant_key$"):
        GrantCodec(key)


@pytest.mark.parametrize("limit", [0, -1, True, 1.0, 7201])
def test_lifetime_config(limit):
    with pytest.raises(ValueError, match="^invalid_grant_lifetime$"):
        GrantCodec(KEY, max_lifetime=limit)


def test_execution_and_sandbox_capabilities_are_not_interchangeable(grant):
    from app.sandbox.grants import CompletionGrantCodec
    sandbox=GrantCodec(KEY,clock=lambda:NOW)
    completion=CompletionGrantCodec(KEY,clock=lambda:NOW)
    work_token=sandbox.issue(grant)
    finish_token=completion.issue(grant)
    assert completion.verify(finish_token)==grant
    assert sandbox.verify(work_token)==grant
    for verifier,token in ((sandbox,finish_token),(completion,work_token)):
        with pytest.raises(GrantError): verifier.verify(token)
    claims=jwt.decode(finish_token,options={'verify_signature':False})
    assert claims['aud']=='atom-execution' and jwt.get_unverified_header(finish_token)['typ']=='atom-execution+jwt'
    assert KEY.decode() not in repr(completion)
    with pytest.raises(GrantError): CompletionGrantCodec(KEY,clock=lambda:grant.exp).verify(finish_token)
    with pytest.raises(GrantError): CompletionGrantCodec(b'z'*32,clock=lambda:NOW).verify(finish_token)


@pytest.mark.parametrize('field,value',[('aud','atom-sandbox'),('sub','admin'),('fence',True),('host_path','/tmp'),('exp',1060.0)])
def test_execution_capability_rejects_signed_invalid_claims(grant,field,value):
    from app.sandbox.grants import CompletionGrantCodec
    completion=CompletionGrantCodec(KEY,clock=lambda:NOW)
    claims=jwt.decode(completion.issue(grant),options={'verify_signature':False})
    claims[field]=value
    token=jwt.encode(claims,KEY,algorithm='HS256',headers={'typ':'atom-execution+jwt'})
    with pytest.raises(GrantError): completion.verify(token)
