"""Demo account seeding.

Exists for one reason: the first thing somebody does with a fresh checkout is open
the web app, and a login wall with no account behind it is where they stop. The
demo user is created idempotently at startup when ``SEED_DEMO_USER`` is on.

The flag is checked by ``Settings.insecure_defaults()`` and refused outside
development, so this cannot quietly ship a known-password administrator to
production. That check is in ``config.py`` rather than here because the guarantee
belongs to configuration, not to the code that would violate it.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .logging import get_logger
from .modules.auth import service as auth_service

log = get_logger(__name__)


async def seed_demo_user(session: AsyncSession, settings: Settings) -> None:
    """Create the demo account if it is missing. Never updates an existing one.

    Deliberately not an upsert. Somebody who has changed the demo password, or
    promoted the account, or accumulated progress on it should not have any of that
    reset by a restart — and a seeder that rewrites a password on every boot is a
    seeder that silently locks people out of their own dev environment.
    """
    existing = await auth_service.get_user_by_email(session, settings.DEMO_USER_EMAIL)
    if existing is not None:
        log.debug("demo_user_present", email=settings.DEMO_USER_EMAIL)
        return

    user, _ = await auth_service.register(
        session,
        email=settings.DEMO_USER_EMAIL,
        password=settings.DEMO_USER_PASSWORD,
        display_name="Demo Learner",
        settings=settings,
        # Admin so the ingestion review queue and the subject reload endpoint are
        # reachable on a fresh checkout. Acceptable only because the surrounding
        # flag is refused outside development.
        is_admin=True,
    )
    log.warning(
        "demo_user_created",
        email=user.email,
        note="known password; SEED_DEMO_USER must be off outside development",
    )
