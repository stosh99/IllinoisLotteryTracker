"""Single transaction seam for present and future user-owned data deletion."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import UserTicketEntry

UserDataDeleter = Callable[[Session, uuid.UUID], None]


def delete_user_ticket_entries(session: Session, user_id: uuid.UUID) -> None:
    session.execute(delete(UserTicketEntry).where(UserTicketEntry.user_id == user_id))
    session.flush()


# Hooks run inside the account deletion transaction before the local user is
# removed; they must flush, never commit.
USER_DATA_DELETERS: tuple[UserDataDeleter, ...] = (delete_user_ticket_entries,)


def delete_user_owned_data(session: Session, user_id: uuid.UUID) -> None:
    for deleter in USER_DATA_DELETERS:
        deleter(session, user_id)
