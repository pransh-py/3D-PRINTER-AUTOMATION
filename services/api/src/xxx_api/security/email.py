"""Email normalization shared by registration and lookup."""

from email_validator import EmailNotValidError, validate_email


def normalize_email(value: str) -> str:
    """Normalize an address without performing network deliverability checks."""
    try:
        normalized = validate_email(value.strip(), check_deliverability=False).normalized
    except EmailNotValidError as error:
        raise ValueError("invalid email address") from error
    return normalized.casefold()
