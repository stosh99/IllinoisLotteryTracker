from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

AUTH_TABLES = {
    "app_users",
    "user_identities",
    "user_sessions",
    "oidc_login_attempts",
    "auth_events",
}


@pytest.fixture(scope="module")
def auth_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    engine = create_engine(url, future=True)
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required")
    yield engine
    engine.dispose()


def test_auth_tables_constraints_and_no_unique_email(auth_engine) -> None:
    inspector = inspect(auth_engine)
    assert AUTH_TABLES <= set(inspector.get_table_names())
    identity_uniques = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("user_identities")
    }
    assert ("issuer", "subject") in identity_uniques
    assert ("user_id", "provider") in identity_uniques
    assert all("email" not in columns for columns in identity_uniques)
    session_checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("user_sessions")
    }
    assert session_checks >= {
        "ck_user_sessions_digest",
        "ck_user_sessions_revocation_shape",
        "ck_user_sessions_timestamps",
    }
    event_foreign_keys = {
        item["name"]: item for item in inspector.get_foreign_keys("auth_events")
    }
    assert all(
        event_foreign_keys[name]["options"].get("deferrable") is True
        and event_foreign_keys[name]["options"].get("initially") == "DEFERRED"
        for name in (
            "auth_events_user_id_fkey",
            "auth_events_session_id_fkey",
            "auth_events_attempt_id_fkey",
        )
    )


def test_duplicate_email_allowed_but_subject_is_unique(auth_engine) -> None:
    now = datetime.now(UTC)
    with auth_engine.connect() as connection:
        transaction = connection.begin()
        user_one, user_two = uuid4(), uuid4()
        connection.execute(
            text(
                "INSERT INTO app_users (id,status,created_at,updated_at) "
                "VALUES (:one,'active',:now,:now),(:two,'active',:now,:now)"
            ),
            {"one": user_one, "two": user_two, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO user_identities "
                "(id,user_id,provider,issuer,subject,email,email_verified,"
                "last_authenticated_at,created_at) VALUES "
                "(:id1,:user1,'google','https://accounts.google.com','sub-1',"
                "'same@example.test',true,:now,:now),"
                "(:id2,:user2,'google','https://accounts.google.com','sub-2',"
                "'same@example.test',true,:now,:now)"
            ),
            {
                "id1": uuid4(),
                "id2": uuid4(),
                "user1": user_one,
                "user2": user_two,
                "now": now,
            },
        )
        nested = connection.begin_nested()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO user_identities "
                    "(id,user_id,provider,issuer,subject,email,email_verified,"
                    "last_authenticated_at,created_at) VALUES "
                    "(:id,:user,'google','https://accounts.google.com','sub-1',"
                    "'other@example.test',true,:now,:now)"
                ),
                {"id": uuid4(), "user": user_two, "now": now},
            )
        nested.rollback()
        transaction.rollback()


def test_session_digest_and_revocation_shape_are_enforced(auth_engine) -> None:
    now = datetime.now(UTC)
    with auth_engine.connect() as connection:
        transaction = connection.begin()
        user_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO app_users (id,status,created_at,updated_at) "
                "VALUES (:id,'active',:now,:now)"
            ),
            {"id": user_id, "now": now},
        )
        nested = connection.begin_nested()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO user_sessions "
                    "(id,user_id,token_digest,created_at,last_seen_at,idle_expires_at,"
                    "absolute_expires_at,revoked_at,revocation_reason) VALUES "
                    "(:id,:user,:digest,:now,:now,:idle,:absolute,:now,NULL)"
                ),
                {
                    "id": uuid4(),
                    "user": user_id,
                    "digest": b"short",
                    "now": now,
                    "idle": now + timedelta(hours=1),
                    "absolute": now + timedelta(days=1),
                },
            )
        nested.rollback()
        transaction.rollback()


def test_user_delete_cascades_credentials_and_anonymizes_events(auth_engine) -> None:
    now = datetime.now(UTC)
    user_id, identity_id, session_id, attempt_id = uuid4(), uuid4(), uuid4(), uuid4()
    with auth_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app_users (id,status,created_at,updated_at) "
                "VALUES (:user,'active',:now,:now)"
            ),
            {"user": user_id, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO user_identities "
                "(id,user_id,provider,issuer,subject,email,email_verified,"
                "last_authenticated_at,created_at) VALUES "
                "(:id,:user,'google','https://accounts.google.com',:subject,"
                "'delete@example.test',true,:now,:now)"
            ),
            {
                "id": identity_id,
                "user": user_id,
                "subject": f"delete-{user_id}",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO user_sessions "
                "(id,user_id,token_digest,created_at,last_seen_at,idle_expires_at,"
                "absolute_expires_at) VALUES (:id,:user,:digest,:now,:now,:idle,:absolute)"
            ),
            {
                "id": session_id,
                "user": user_id,
                "digest": uuid4().bytes + uuid4().bytes,
                "now": now,
                "idle": now + timedelta(hours=1),
                "absolute": now + timedelta(days=1),
            },
        )
        connection.execute(
            text(
                "INSERT INTO oidc_login_attempts "
                "(id,provider,state_digest,browser_binding_digest,nonce_digest,"
                "pkce_verifier_ciphertext,return_path,intent,expected_user_id,"
                "expected_session_id,status,created_at,expires_at) VALUES "
                "(:id,'google',:state,:binding,:nonce,:pkce,'/account','reauth_delete',"
                ":user,:session,'pending',:now,:expires)"
            ),
            {
                "id": attempt_id,
                "state": uuid4().bytes + uuid4().bytes,
                "binding": uuid4().bytes + uuid4().bytes,
                "nonce": uuid4().bytes + uuid4().bytes,
                "pkce": "v1." + "A" * 152,
                "user": user_id,
                "session": session_id,
                "now": now,
                "expires": now + timedelta(minutes=10),
            },
        )
        event_id = connection.scalar(
            text(
                "INSERT INTO auth_events "
                "(occurred_at,event_type,outcome,user_id,session_id,attempt_id,details) "
                "VALUES (:now,'reauth_started','info',:user,:session,:attempt,'{}') "
                "RETURNING id"
            ),
            {
                "now": now,
                "user": user_id,
                "session": session_id,
                "attempt": attempt_id,
            },
        )
        connection.execute(text("DELETE FROM app_users WHERE id = :user"), {"user": user_id})
        assert connection.scalar(
            text("SELECT count(*) FROM user_identities WHERE user_id = :user"),
            {"user": user_id},
        ) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM user_sessions WHERE user_id = :user"),
            {"user": user_id},
        ) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM oidc_login_attempts WHERE id = :attempt"),
            {"attempt": attempt_id},
        ) == 0
        links = connection.execute(
            text(
                "SELECT user_id,session_id,attempt_id FROM auth_events WHERE id = :event"
            ),
            {"event": event_id},
        ).one()
        assert tuple(links) == (None, None, None)
