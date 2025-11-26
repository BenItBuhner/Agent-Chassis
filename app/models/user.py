"""
SQLAlchemy model for user accounts.

Supports multiple authentication methods:
- Email + Password (with email verification)
- Google OAuth (passwordless)

Part of OSP-14 implementation.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.conversation import Base


class User(Base):
    """
    User account model for authentication and authorization.

    Attributes:
        id: UUID primary key
        email: Unique email address (indexed)
        email_verified: Whether email has been verified
        password_hash: Hashed password (None for OAuth-only users)
        google_id: Google OAuth subject ID (for Google sign-in)
        display_name: User's display name
        created_at: Account creation timestamp
        updated_at: Last update timestamp
        last_login_at: Last successful login timestamp
        is_active: Whether account is active (can login)
        is_admin: Whether user has admin privileges
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    password_hash: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,  # None for OAuth-only users
    )

    # OAuth fields
    google_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
    )

    # Profile
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    # Account status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert user to dictionary (excludes sensitive fields)."""
        return {
            "id": self.id,
            "email": self.email,
            "email_verified": self.email_verified,
            "google_id": self.google_id is not None,  # Boolean, not the actual ID
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
        }

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, verified={self.email_verified})>"
