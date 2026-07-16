"""Persisted users and bearer-token state."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PythonEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from xxx_api.domain.auth import AuditEventType, MfaMethodKind, OneTimeTokenPurpose, UserStatus
from xxx_api.domain.roles import Role
from xxx_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def enum_values[EnumType: PythonEnum](enum_type: type[EnumType]) -> list[str]:
    """Persist stable enum values instead of Python member names."""
    return [member.value for member in enum_type]


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A public buyer or administratively provisioned owner."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(role = 'owner' AND owner_slot = 'primary') OR "
            "(role = 'buyer' AND owner_slot IS NULL)",
            name="ck_users_owner_slot",
        ),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            native_enum=False,
            values_callable=enum_values,
            length=16,
            validate_strings=True,
            create_constraint=True,
            name="ck_users_role",
        ),
        default=Role.BUYER,
        server_default=Role.BUYER.value,
        nullable=False,
    )
    owner_slot: Mapped[str | None] = mapped_column(String(16), unique=True)
    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            native_enum=False,
            values_callable=enum_values,
            length=32,
            validate_strings=True,
            create_constraint=True,
            name="ck_users_status",
        ),
        default=UserStatus.PENDING_VERIFICATION,
        server_default=UserStatus.PENDING_VERIFICATION.value,
        nullable=False,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    refresh_sessions: Mapped[list[RefreshSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    one_time_tokens: Mapped[list[OneTimeToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    mfa_method: Mapped[MfaMethod | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class RefreshSession(UUIDPrimaryKeyMixin, Base):
    """Server-side state for one rotating refresh-token chain."""

    __tablename__ = "refresh_sessions"
    __table_args__ = (
        Index("ix_refresh_sessions_family_active", "family_id", "revoked_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    family_id: Mapped[UUID] = mapped_column(Uuid, default=uuid4, index=True, nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mfa_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("refresh_sessions.id", ondelete="SET NULL")
    )
    user_agent_digest: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="refresh_sessions")


class OneTimeToken(UUIDPrimaryKeyMixin, Base):
    """Hashed email-verification or password-reset token."""

    __tablename__ = "one_time_tokens"
    __table_args__ = (
        Index("ix_one_time_tokens_user_purpose", "user_id", "purpose", "consumed_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[OneTimeTokenPurpose] = mapped_column(
        Enum(
            OneTimeTokenPurpose,
            native_enum=False,
            values_callable=enum_values,
            length=32,
            validate_strings=True,
            create_constraint=True,
            name="ck_one_time_tokens_purpose",
        ),
        nullable=False,
    )
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="one_time_tokens")


class MfaMethod(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Encrypted owner TOTP material and replay state."""

    __tablename__ = "mfa_methods"

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    kind: Mapped[MfaMethodKind] = mapped_column(
        Enum(
            MfaMethodKind,
            native_enum=False,
            values_callable=enum_values,
            length=16,
            validate_strings=True,
            create_constraint=True,
            name="ck_mfa_methods_kind",
        ),
        nullable=False,
    )
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_counter: Mapped[int | None] = mapped_column(BigInteger)

    user: Mapped[User] = relationship(back_populates="mfa_method")
    recovery_codes: Mapped[list[MfaRecoveryCode]] = relationship(
        back_populates="mfa_method", cascade="all, delete-orphan", passive_deletes=True
    )


class MfaRecoveryCode(UUIDPrimaryKeyMixin, Base):
    """One owner recovery code stored only as a keyed digest."""

    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (
        Index("ix_mfa_recovery_codes_method_unused", "mfa_method_id", "used_at"),
    )

    mfa_method_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mfa_methods.id", ondelete="CASCADE"), nullable=False
    )
    code_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    mfa_method: Mapped[MfaMethod] = relationship(back_populates="recovery_codes")


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only, non-secret evidence for security and business transitions."""

    __tablename__ = "audit_events"

    event_type: Mapped[AuditEventType] = mapped_column(
        Enum(
            AuditEventType,
            native_enum=False,
            values_callable=enum_values,
            length=64,
            validate_strings=True,
            create_constraint=True,
            name="ck_audit_events_type",
        ),
        index=True,
        nullable=False,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    target_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)


def _reject_audit_mutation(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("audit events are append-only")


event.listen(AuditEvent, "before_update", _reject_audit_mutation)
event.listen(AuditEvent, "before_delete", _reject_audit_mutation)
