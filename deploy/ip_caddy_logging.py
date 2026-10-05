"""Bounded Caddy runtime-log redaction for the console origin proof."""


class IngressLogPolicyError(RuntimeError):
    """Stable refusal code without config or credential content."""


PROOF_FILTER = "request>headers>X-Atom-Console-Proof delete"
LOGGER_BLOCK = ("  log default {\n"
                "    format filter {\n"
                f"      {PROOF_FILTER}\n"
                "    }\n"
                "  }")


def secure_base(base: bytes) -> bytes:
    """Insert one runtime logger filter into a validated IP Caddy base."""
    if not isinstance(base, bytes) or not 0 < len(base) <= 1024 * 1024:
        raise IngressLogPolicyError("invalid_ingress_log_base")
    try:
        opening, remainder = base.decode("utf-8").split("\n}\n", 1)
    except (UnicodeError, ValueError):
        raise IngressLogPolicyError("invalid_ingress_log_base") from None
    lines = opening.splitlines()
    if (not lines or lines[0] != "{" or not remainder.strip()
            or "  grace_period 5s" not in lines
            or not any(line.startswith("  default_sni ") for line in lines)):
        raise IngressLogPolicyError("invalid_ingress_log_base")
    if PROOF_FILTER in opening:
        if opening.count(PROOF_FILTER) != 1 or LOGGER_BLOCK not in opening:
            raise IngressLogPolicyError("ambiguous_ingress_log_policy")
        return base
    if any(line.strip().startswith("log ") for line in lines):
        raise IngressLogPolicyError("existing_ingress_log_policy")
    updated = opening + "\n" + LOGGER_BLOCK + "\n}\n" + remainder
    payload = updated.encode("utf-8")
    if len(payload) > 1024 * 1024:
        raise IngressLogPolicyError("ingress_log_base_too_large")
    return payload
