"""Single transaction seam for present and future user-owned data deletion."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

UserDataDeleter = Callable[[Session, uuid.UUID], None]

# A future personal-ticket migration must add its reviewed deletion function to
# this tuple in the same change. Hooks run inside the account deletion
# transaction before the local user is removed; they must flush, never commit.
USER_DATA_DELETERS: tuple[UserDataDeleter, ...] = ()


def delete_user_owned_data(session: Session, user_id: uuid.UUID) -> None:
    for deleter in USER_DATA_DELETERS:
        deleter(session, user_id)
