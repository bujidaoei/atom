def mask_secret(value: str) -> str:
    """Show the first two and last two characters. Everything between is a star."""
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"
