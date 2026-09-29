from __future__ import annotations


def mask_secret(secret: str | None) -> str:
    """Show the first two and last two characters, asterisk out the middle.

    The number of asterisks equals the number of hidden characters, so the
    displayed length still tells you whether you pasted the right key. Secrets
    of four characters or fewer are masked entirely, because keeping two on
    each end would reveal the whole thing.
    """
    if not secret:
        return ""
    if len(secret) <= 4:
        return "*" * len(secret)
    return f"{secret[:2]}{'*' * (len(secret) - 4)}{secret[-2:]}"
