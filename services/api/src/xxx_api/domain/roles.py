"""Application roles."""

from enum import StrEnum


class Role(StrEnum):
    """Roles recognized by authorization policies."""

    BUYER = "buyer"
    OWNER = "owner"
