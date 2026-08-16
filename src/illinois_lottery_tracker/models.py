"""SQLAlchemy ORM models for the Illinois Lottery tracker."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


BIGINT_PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


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
    workflow: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unpaid_prizes", server_default="unpaid_prizes"
    )
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_date: Mapped[date | None] = mapped_column(Date)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    is_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    parsed_game_count: Mapped[int | None] = mapped_column(Integer)
    parsed_prize_tier_count: Mapped[int | None] = mapped_column(Integer)
    pipeline_version: Mapped[str | None] = mapped_column(String(64))
    manually_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_approval_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    raw_snapshots: Mapped[list[RawSourceSnapshot]] = relationship(
        back_populates="scrape_run", cascade="all, delete-orphan"
    )
    game_snapshots: Mapped[list[GameSnapshot]] = relationship(
        back_populates="scrape_run", cascade="all, delete-orphan"
    )
    catalog_snapshots: Mapped[list[GameCatalogSnapshot]] = relationship(
        back_populates="scrape_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_scrape_runs_started_at", "started_at"),
        Index("ix_scrape_runs_status", "status"),
        Index(
            "ix_scrape_runs_workflow_complete_observed",
            "workflow",
            "is_complete",
            source_observed_at.desc(),
        ),
        Index("ix_scrape_runs_source_date", "source_date"),
        Index(
            "uq_scrape_runs_complete_unpaid_sha256",
            "workflow",
            "source_sha256",
            unique=True,
            postgresql_where=(
                (workflow == "unpaid_prizes") & (status == "success") & is_complete
            ),
            sqlite_where=(
                (workflow == "unpaid_prizes") & (status == "success") & is_complete
            ),
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'quarantined')",
            name="ck_scrape_runs_status",
        ),
        CheckConstraint(
            "workflow IN ('unpaid_prizes', 'instant_ticket_catalog')",
            name="ck_scrape_runs_workflow",
        ),
        CheckConstraint(
            "parsed_game_count IS NULL OR parsed_game_count >= 0",
            name="ck_scrape_runs_parsed_game_count_nonnegative",
        ),
        CheckConstraint(
            "parsed_prize_tier_count IS NULL OR parsed_prize_tier_count >= 0",
            name="ck_scrape_runs_parsed_tier_count_nonnegative",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_scrape_runs_finished_after_started",
        ),
        CheckConstraint(
            "NOT (workflow = 'unpaid_prizes' AND status = 'success' AND is_complete) OR "
            "(source_observed_at IS NOT NULL AND source_date IS NOT NULL "
            "AND source_sha256 IS NOT NULL AND parsed_game_count > 0 "
            "AND parsed_prize_tier_count > 0)",
            name="ck_scrape_runs_complete_provenance",
        ),
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
        Index("ix_raw_source_snapshots_scrape_run_id", "scrape_run_id"),
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
    end_date: Mapped[date | None] = mapped_column(Date)
    overall_odds_one_in: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    est_total_tickets: Mapped[int | None] = mapped_column(BigInteger)
    top_prize_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    category: Mapped[str | None] = mapped_column(String(128))
    play_style: Mapped[str | None] = mapped_column(String(128))
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
        CheckConstraint(
            "ticket_price IS NULL OR ticket_price > 0", name="ck_games_ticket_price_positive"
        ),
        CheckConstraint(
            "overall_odds_one_in IS NULL OR overall_odds_one_in > 1",
            name="ck_games_overall_odds_greater_than_one",
        ),
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
    structure_fingerprint: Mapped[str | None] = mapped_column(String(64))

    total_original_prize_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_remaining_prize_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_original_winning_tickets: Mapped[int | None] = mapped_column(BigInteger)
    total_remaining_winning_tickets: Mapped[int | None] = mapped_column(BigInteger)
    top_prizes_original: Mapped[int | None] = mapped_column(Integer)
    top_prizes_remaining: Mapped[int | None] = mapped_column(Integer)
    weeks_in_market: Mapped[int | None] = mapped_column(Integer)
    estimated_tickets_remaining: Mapped[int | None] = mapped_column(BigInteger)
    estimated_ev: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    estimated_ev_excluding_top_prize: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))

    # Phase 1 normalized metrics — odds-dependent
    estimated_payout_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    estimated_house_edge: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    estimated_payout_ratio_excluding_top_prize: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6)
    )
    launch_ev: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    launch_payout_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    ev_vs_launch_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # Phase 1 normalized metrics — always computed from raw totals (no odds needed).
    # *_pct fields are stored as decimal fractions: 0.749 means 74.9 %.
    remaining_prize_value_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    remaining_winning_tickets_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    top_prize_remaining_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    top_prize_depleted: Mapped[bool | None] = mapped_column(Boolean)

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
        Index("ix_game_snapshots_scrape_run_id", "scrape_run_id"),
        Index(
            "ix_game_snapshots_game_id_structure_fingerprint",
            "game_id",
            "structure_fingerprint",
        ),
        CheckConstraint(
            "total_original_prize_value IS NULL OR total_original_prize_value >= 0",
            name="ck_game_snapshots_original_value_nonnegative",
        ),
        CheckConstraint(
            "total_remaining_prize_value IS NULL OR total_remaining_prize_value >= 0",
            name="ck_game_snapshots_remaining_value_nonnegative",
        ),
        CheckConstraint(
            "total_original_winning_tickets IS NULL OR total_original_winning_tickets >= 0",
            name="ck_game_snapshots_original_count_nonnegative",
        ),
        CheckConstraint(
            "total_remaining_winning_tickets IS NULL OR total_remaining_winning_tickets >= 0",
            name="ck_game_snapshots_remaining_count_nonnegative",
        ),
        CheckConstraint(
            "total_original_winning_tickets IS NULL OR "
            "total_remaining_winning_tickets IS NULL OR "
            "total_remaining_winning_tickets <= total_original_winning_tickets",
            name="ck_game_snapshots_remaining_not_above_original",
        ),
        CheckConstraint(
            "top_prizes_original IS NULL OR top_prizes_original >= 0",
            name="ck_game_snapshots_top_original_nonnegative",
        ),
        CheckConstraint(
            "top_prizes_remaining IS NULL OR top_prizes_remaining >= 0",
            name="ck_game_snapshots_top_remaining_nonnegative",
        ),
        CheckConstraint(
            "top_prizes_original IS NULL OR top_prizes_remaining IS NULL OR "
            "top_prizes_remaining <= top_prizes_original",
            name="ck_game_snapshots_top_remaining_not_above_original",
        ),
        CheckConstraint(
            "weeks_in_market IS NULL OR weeks_in_market >= 0",
            name="ck_game_snapshots_weeks_nonnegative",
        ),
    )


class PrizeTierSnapshot(Base):
    __tablename__ = "prize_tier_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("game_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    prize_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    original_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    claimed_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
        CheckConstraint("prize_amount > 0", name="ck_prize_tiers_amount_positive"),
        CheckConstraint("original_count >= 0", name="ck_prize_tiers_original_nonnegative"),
        CheckConstraint("remaining_count >= 0", name="ck_prize_tiers_remaining_nonnegative"),
        CheckConstraint("claimed_count >= 0", name="ck_prize_tiers_claimed_nonnegative"),
        CheckConstraint(
            "remaining_count <= original_count",
            name="ck_prize_tiers_remaining_not_above_original",
        ),
        CheckConstraint(
            "claimed_count = original_count - remaining_count",
            name="ck_prize_tiers_claimed_identity",
        ),
    )


class GameCatalogSnapshot(Base):
    __tablename__ = "game_catalog_snapshots"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL")
    )
    detail_url: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    top_prize_text: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    card_position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scrape_run: Mapped[ScrapeRun] = relationship(back_populates="catalog_snapshots")

    __table_args__ = (
        UniqueConstraint(
            "scrape_run_id", "detail_url", name="uq_catalog_snapshots_run_url"
        ),
        Index("ix_catalog_snapshots_game_run", "game_id", "scrape_run_id"),
        Index("ix_catalog_snapshots_detail_url", "detail_url"),
        CheckConstraint("ticket_price > 0", name="ck_catalog_ticket_price_positive"),
        CheckConstraint("page_number > 0", name="ck_catalog_page_number_positive"),
        CheckConstraint("card_position >= 0", name="ck_catalog_card_position_nonnegative"),
    )


class CatalogQualityIssue(Base):
    __tablename__ = "catalog_quality_issues"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False
    )
    catalog_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("game_catalog_snapshots.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    detail_url: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_catalog_quality_issues_run_code", "scrape_run_id", "code"),
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_catalog_quality_issues_severity",
        ),
    )


class MetadataAttempt(Base):
    __tablename__ = "metadata_attempts"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), nullable=False
    )
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candidate_url: Mapped[str | None] = mapped_column(Text)
    outcome_code: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_metadata_attempts_game_attempted", "game_id", attempted_at.desc()),
        Index("ix_metadata_attempts_next_retry", "next_retry_at"),
        CheckConstraint("attempt_number > 0", name="ck_metadata_attempt_number_positive"),
        CheckConstraint(
            "outcome_code IN ('success', 'no_candidate', 'ambiguous', "
            "'fetch_failed', 'parse_failed', 'not_due')",
            name="ck_metadata_attempt_outcome",
        ),
    )


class UserTicketEntry(Base):
    """One user-owned record of tickets played together for the same game."""

    __tablename__ = "user_ticket_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), nullable=False
    )
    game_number: Mapped[str] = mapped_column(String(32), nullable=False)
    game_name: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    played_on: Mapped[date] = mapped_column(Date, nullable=False)
    ticket_count: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_won: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("ticket_price > 0", name="ck_user_ticket_entries_price_positive"),
        CheckConstraint(
            "ticket_count > 0 AND ticket_count <= 1000",
            name="ck_user_ticket_entries_count_range",
        ),
        CheckConstraint(
            "amount_won >= 0 AND amount_won <= 1000000000",
            name="ck_user_ticket_entries_winnings_range",
        ),
        CheckConstraint("updated_at >= created_at", name="ck_user_ticket_entries_updated_at"),
        Index("ix_user_ticket_entries_user_played", "user_id", "played_on", "created_at"),
        Index("ix_user_ticket_entries_game", "game_id"),
    )
