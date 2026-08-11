from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from illinois_lottery_tracker.auth.repository import AuthRepository
from illinois_lottery_tracker.auth_models import AppUser


def test_add_flushes_but_never_commits() -> None:
    session = MagicMock()
    repository = AuthRepository(session)
    user = AppUser()

    assert repository.add(user) is user
    session.add.assert_called_once_with(user)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_delete_flushes_but_never_commits() -> None:
    session = MagicMock()
    repository = AuthRepository(session)
    user = AppUser()

    repository.delete_user(user)

    session.delete.assert_called_once_with(user)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "details",
    [
        {"email": "forbidden@example.test"},
        {"sessions_revoked": True},
        {"sessions_revoked": 11},
        {"provider": "other"},
        {"duration_bucket_ms": 999},
    ],
)
def test_event_repository_rejects_details_outside_positive_allowlist(details) -> None:
    repository = AuthRepository(MagicMock())
    with pytest.raises(ValueError, match="authentication event"):
        repository.append_event(
            event_type="login_started",
            outcome="info",
            occurred_at=MagicMock(),
            details=details,
        )
