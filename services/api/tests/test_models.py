"""Identity persistence tests against the development-compatible async dialect."""

from asyncio import run

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from xxx_api.domain.auth import UserStatus
from xxx_api.domain.roles import Role
from xxx_api.models import Base, User


def test_user_defaults_persist() -> None:
    async def exercise_database() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            user = User(
                email="buyer@example.com",
                display_name="Buyer",
                password_hash="$argon2id$placeholder",
            )
            session.add(user)
            await session.commit()
            user_id = user.id

        async with sessions() as session:
            persisted = await session.scalar(select(User).where(User.id == user_id))
            assert persisted is not None
            assert persisted.role is Role.BUYER
            assert persisted.status is UserStatus.PENDING_VERIFICATION
            assert persisted.created_at is not None
            assert persisted.password_changed_at is not None

        await engine.dispose()

    run(exercise_database())
