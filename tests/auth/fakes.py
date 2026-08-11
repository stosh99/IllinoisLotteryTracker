from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class FakeSession:
    flushed: int = 0

    def flush(self) -> None:
        self.flushed += 1


@contextmanager
def fake_session_context(session: FakeSession):
    yield session


@dataclass
class MemoryStore:
    attempts: list = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
