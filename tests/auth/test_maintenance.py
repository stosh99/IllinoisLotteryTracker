from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from illinois_lottery_tracker.auth.maintenance import AuthenticationMaintenance
from illinois_lottery_tracker.auth.user_management import (
    UserAccountManager,
    UserOperationError,
)
from illinois_lottery_tracker.auth_models import (
    AppUser,
    AuthEvent,
    OidcLoginAttempt,
    UserSession,
)
from illinois_lottery_tracker.models import Base

NOW = datetime(2026, 8, 10, 16, 0, tzinfo=UTC)


@pytest.fixture()
def database():
    engine = create_engine("sqlite://", future=True)

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, future=True)

    @contextmanager
    def sessions():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    yield sessions, factory
    engine.dispose()


def _attempt(status: str, *, created_at: datetime, completed_at=None) -> OidcLoginAttempt:
    claimed = created_at + timedelta(minutes=1) if status in {"exchanging", "succeeded"} else None
    return OidcLoginAttempt(
        id=uuid.uuid4(),
        provider="google",
        state_digest=uuid.uuid4().bytes + uuid.uuid4().bytes,
        browser_binding_digest=uuid.uuid4().bytes + uuid.uuid4().bytes,
        nonce_digest=uuid.uuid4().bytes + uuid.uuid4().bytes,
        pkce_verifier_ciphertext="v1." + "A" * 152,
        return_path="/",
        intent="login",
        status=status,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=10),
        claimed_at=claimed,
        completed_at=completed_at,
    )


def test_maintenance_dry_run_and_apply_enforce_original_retention_times(database) -> None:
    sessions, factory = database
    user_id = uuid.uuid4()
    expired_session_id = uuid.uuid4()
    old_attempt_id = uuid.uuid4()
    with sessions() as session:
        session.add(
            AppUser(
                id=user_id,
                status="active",
                created_at=NOW - timedelta(days=100),
                updated_at=NOW - timedelta(days=100),
            )
        )
        session.flush()
        session.add(
            UserSession(
                id=expired_session_id,
                user_id=user_id,
                token_digest=b"s" * 32,
                created_at=NOW - timedelta(days=40),
                last_seen_at=NOW - timedelta(days=39),
                idle_expires_at=NOW - timedelta(days=35),
                absolute_expires_at=NOW - timedelta(days=33),
            )
        )
        pending = _attempt("pending", created_at=NOW - timedelta(minutes=20))
        exchanging = _attempt("exchanging", created_at=NOW - timedelta(minutes=20))
        terminal = _attempt(
            "succeeded",
            created_at=NOW - timedelta(days=2),
            completed_at=NOW - timedelta(hours=25),
        )
        terminal.id = old_attempt_id
        session.add_all([pending, exchanging, terminal])
        session.add(
            AuthEvent(
                occurred_at=NOW - timedelta(days=91),
                event_type="login_started",
                outcome="info",
                details={},
            )
        )

    maintenance = AuthenticationMaintenance(sessions, clock=lambda: NOW)
    planned = maintenance.run()
    assert planned.document(mode="dry-run") == {
        "mode": "dry-run",
        "attempts_expired": 1,
        "exchanges_abandoned": 1,
        "attempts_deleted": 1,
        "sessions_expired": 1,
        "sessions_deleted": 1,
        "events_deleted": 1,
    }
    with factory() as session:
        assert session.get(OidcLoginAttempt, old_attempt_id) is not None

    applied = maintenance.run(apply=True)
    assert applied == planned
    with factory() as session:
        attempts = list(session.scalars(select(OidcLoginAttempt)))
        assert {row.status for row in attempts} == {"expired", "failed"}
        assert {row.failure_code for row in attempts} == {
            "attempt_expired",
            "exchange_abandoned",
        }
        assert session.get(UserSession, expired_session_id) is None
        assert session.get(OidcLoginAttempt, old_attempt_id) is None
        assert session.scalar(
            select(AuthEvent).where(AuthEvent.occurred_at < NOW - timedelta(days=90))
        ) is None

    second = maintenance.run(apply=True)
    assert second.document(mode="apply") == {
        "mode": "apply",
        "attempts_expired": 0,
        "exchanges_abandoned": 0,
        "attempts_deleted": 0,
        "sessions_expired": 0,
        "sessions_deleted": 0,
        "events_deleted": 0,
    }


def test_user_manager_suspends_reactivates_revokes_and_deletes_without_pii(database) -> None:
    sessions, factory = database
    user_id = uuid.uuid4()
    with sessions() as session:
        session.add(
            AppUser(id=user_id, status="active", created_at=NOW, updated_at=NOW)
        )
        session.flush()
        session.add(
            UserSession(
                id=uuid.uuid4(),
                user_id=user_id,
                token_digest=b"t" * 32,
                created_at=NOW,
                last_seen_at=NOW,
                idle_expires_at=NOW + timedelta(days=1),
                absolute_expires_at=NOW + timedelta(days=7),
            )
        )

    manager = UserAccountManager(sessions, clock=lambda: NOW + timedelta(minutes=1))
    planned = manager.mutate("suspend", user_id, "abuse", apply=False)
    assert planned.mode == "dry-run" and planned.resulting_status == "suspended"
    with factory() as session:
        assert session.get(AppUser, user_id).status == "active"

    suspended = manager.mutate("suspend", user_id, "abuse", apply=True)
    assert suspended.sessions_affected == 1
    with factory() as session:
        user = session.get(AppUser, user_id)
        assert user.status == "suspended"
        stored = session.scalar(select(UserSession).where(UserSession.user_id == user_id))
        assert stored.revocation_reason == "account_suspended"

    reactivated = manager.mutate(
        "reactivate", user_id, "review_cleared", apply=True
    )
    assert reactivated.resulting_status == "active"
    with pytest.raises(UserOperationError, match="no active sessions"):
        manager.mutate("revoke_sessions", user_id, "operator_correction", apply=True)

    deleted = manager.mutate("delete", user_id, "user_request", apply=True)
    assert deleted.resulting_status == "deleted"
    assert "@" not in str(deleted.document())
    with factory() as session:
        assert session.get(AppUser, user_id) is None
        event_row = session.scalar(
            select(AuthEvent)
            .where(AuthEvent.event_type == "account_deleted")
            .order_by(AuthEvent.id.desc())
        )
        assert event_row is not None and event_row.user_id is None


def test_user_manager_refuses_invalid_transitions_and_reason_codes(database) -> None:
    sessions, _factory = database
    user_id = uuid.uuid4()
    with sessions() as session:
        session.add(AppUser(id=user_id, status="active", created_at=NOW, updated_at=NOW))
    manager = UserAccountManager(sessions, clock=lambda: NOW)
    with pytest.raises(UserOperationError, match="reason code"):
        manager.mutate("suspend", user_id, "review_cleared", apply=True)
    with pytest.raises(UserOperationError, match="not suspended"):
        manager.mutate("reactivate", user_id, "review_cleared", apply=True)
