"""SQLAlchemy ORM models for the Illinois Lottery tracker."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_file_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    raw_snapshots: Mapped[list[RawSourceSnapshot]] = relationship(
        back_populates="scrape_run", cascade="all, delete-orphan"
    )
    game_snapshots: Mapped[list[GameSnapshot]] = relationship(
        back_populates="scrape_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_scrape_runs_started_at", "started_at"),
        Index("ix_scrape_runs_status", "status"),
    )


class RawSourceSnapshot(Base):
    __tablename__ = "raw_source_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scrape_run: Mapped[ScrapeRun] = relationship(back_populates="raw_snapshots")

    __table_args__ = (
        Index("ix_raw_source_snapshots_captured_at", "captured_at"),
        Index("ix_raw_source_snapshots_sha256", "sha256"),
    )


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    ticket_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    launch_date: Mapped[date | None] = mapped_column(Date)
    overall_odds: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    top_prize_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=_utcnow,
    )

    snapshots: Mapped[list[GameSnapshot]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_games_is_active", "is_active"),
    )


class GameSnapshot(Base):
    __tablename__ = "game_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), nullable=False
    )
    scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    total_original_prize_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_remaining_prize_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_original_winning_tickets: Mapped[int | None] = mapped_column(BigInteger)
    total_remaining_winning_tickets: Mapped[int | None] = mapped_column(BigInteger)
    top_prizes_original: Mapped[int | None] = mapped_column(Integer)
    top_prizes_remaining: Mapped[int | None] = mapped_column(Integer)
    estimated_tickets_remaining: Mapped[int | None] = mapped_column(BigInteger)
    estimated_ev: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    estimated_ev_excluding_top_prize: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    game: Mapped[Game] = relationship(back_populates="snapshots")
    scrape_run: Mapped[ScrapeRun] = relationship(back_populates="game_snapshots")
    prize_tiers: Mapped[list[PrizeTierSnapshot]] = relationship(
        back_populates="game_snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "game_id", "scrape_run_id", name="uq_game_snapshots_game_scrape_run"
        ),
        Index("ix_game_snapshots_captured_at", "captured_at"),
        Index("ix_game_snapshots_game_id_captured_at", "game_id", "captured_at"),
    )


class PrizeTierSnapshot(Base):
    __tablename__ = "prize_tier_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("game_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    prize_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    original_count: Mapped[int | None] = mapped_column(BigInteger)
    remaining_count: Mapped[int | None] = mapped_column(BigInteger)
    claimed_count: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    game_snapshot: Mapped[GameSnapshot] = relationship(back_populates="prize_tiers")

    __table_args__ = (
        UniqueConstraint(
            "game_snapshot_id",
            "prize_amount",
            name="uq_prize_tier_snapshots_snapshot_amount",
        ),
    )
