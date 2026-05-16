"""Read-only claim-activity analytics from stored unpaid-prizes snapshots.

Activity rows compare consecutive public remaining-prize snapshots. A positive
``implied_claimed_count`` means the public remaining count decreased since the
prior snapshot. This is an implied movement from public unclaimed-prize data,
not proof of when a ticket was sold or physically in circulation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import Game, GameSnapshot, RawSourceSnapshot, ScrapeRun


class ActivityReportSection(StrEnum):
    ALL = "all"
    LATEST = "latest"
    ROLLING = "rolling"
    TIERS = "tiers"


@dataclass(frozen=True)
class SnapshotPoint:
    snapshot: GameSnapshot
    observed_at: datetime


@dataclass(frozen=True)
class TierActivityRow:
    game_number: str
    game_name: str
    ticket_price: Decimal | None
    prize_amount: Decimal
    previous_observed_at: datetime
    observed_at: datetime
    previous_remaining_count: int | None
    remaining_count: int | None
    implied_claimed_count: int | None
    implied_claimed_value: Decimal | None


@dataclass(frozen=True)
class GameActivityRow:
    game_number: str
    game_name: str
    ticket_price: Decimal | None
    previous_observed_at: datetime
    observed_at: datetime
    implied_claimed_count: int
    implied_claimed_value: Decimal
    tier_rows: list[TierActivityRow] = field(default_factory=list)


@dataclass(frozen=True)
class RollingActivityRow:
    game_number: str
    game_name: str
    ticket_price: Decimal | None
    window_days: int
    interval_count: int
    implied_claimed_count: int
    implied_claimed_value: Decimal


@dataclass(frozen=True)
class ActivityReport:
    latest_observed_at: datetime | None
    game_rows: list[GameActivityRow]


def build_activity_report(session: Session) -> ActivityReport:
    """Build read-only activity analytics for all games with 2+ snapshots."""
    run_times = _run_source_times(session)
    snapshots = list(
        session.scalars(
            select(GameSnapshot)
            .join(Game)
            .options(selectinload(GameSnapshot.game), selectinload(GameSnapshot.prize_tiers))
        )
    )

    by_game: dict[int, list[SnapshotPoint]] = defaultdict(list)
    for snapshot in snapshots:
        observed_at = _observed_at(snapshot, run_times)
        by_game[snapshot.game_id].append(SnapshotPoint(snapshot=snapshot, observed_at=observed_at))

    game_rows: list[GameActivityRow] = []
    for points in by_game.values():
        points.sort(key=lambda point: (point.observed_at, point.snapshot.id))
        for previous, current in zip(points, points[1:], strict=False):
            game_rows.append(_compare_game_snapshots(previous, current))

    game_rows.sort(key=lambda row: (row.observed_at, row.game_number))
    latest = max((row.observed_at for row in game_rows), default=None)
    return ActivityReport(latest_observed_at=latest, game_rows=game_rows)


def latest_activity_rows(report: ActivityReport, *, limit: int) -> list[GameActivityRow]:
    if report.latest_observed_at is None:
        return []
    rows = [
        row for row in report.game_rows if row.observed_at == report.latest_observed_at
    ]
    rows.sort(
        key=lambda row: (
            row.implied_claimed_value,
            row.implied_claimed_count,
            row.game_number,
        ),
        reverse=True,
    )
    return rows[:limit]


def rolling_activity_rows(
    report: ActivityReport,
    *,
    window_days: int,
    limit: int,
) -> list[RollingActivityRow]:
    if report.latest_observed_at is None:
        return []
    cutoff = report.latest_observed_at - timedelta(days=window_days)
    grouped: dict[str, list[GameActivityRow]] = defaultdict(list)
    for row in report.game_rows:
        if row.observed_at > cutoff:
            grouped[row.game_number].append(row)

    rows: list[RollingActivityRow] = []
    for game_rows in grouped.values():
        first = game_rows[0]
        rows.append(
            RollingActivityRow(
                game_number=first.game_number,
                game_name=first.game_name,
                ticket_price=first.ticket_price,
                window_days=window_days,
                interval_count=len(game_rows),
                implied_claimed_count=sum(r.implied_claimed_count for r in game_rows),
                implied_claimed_value=sum(
                    (r.implied_claimed_value for r in game_rows), Decimal("0")
                ),
            )
        )
    rows.sort(
        key=lambda row: (
            row.implied_claimed_value,
            row.implied_claimed_count,
            row.game_number,
        ),
        reverse=True,
    )
    return rows[:limit]


def tier_activity_rows_for_game(
    report: ActivityReport,
    *,
    game_number: str,
) -> list[TierActivityRow]:
    rows: list[TierActivityRow] = []
    for game_row in report.game_rows:
        if game_row.game_number == game_number:
            rows.extend(game_row.tier_rows)
    rows.sort(key=lambda row: (row.prize_amount, row.observed_at), reverse=True)
    return rows


def render_text_report(
    report: ActivityReport,
    *,
    section: ActivityReportSection = ActivityReportSection.ALL,
    limit: int = 10,
    rolling_windows: tuple[int, ...] = (7, 14, 30),
    game_number: str | None = None,
) -> str:
    lines: list[str] = []
    _render_header(lines, report)

    sections = (
        [section]
        if section is not ActivityReportSection.ALL
        else [ActivityReportSection.LATEST, ActivityReportSection.ROLLING]
    )
    for selected in sections:
        lines.append("")
        if selected is ActivityReportSection.LATEST:
            _render_latest(lines, latest_activity_rows(report, limit=limit))
        elif selected is ActivityReportSection.ROLLING:
            for window in rolling_windows:
                lines.append("")
                _render_rolling(
                    lines,
                    rolling_activity_rows(report, window_days=window, limit=limit),
                    window_days=window,
                )
        elif selected is ActivityReportSection.TIERS:
            _render_tiers(lines, report, game_number=game_number)

    return "\n".join(lines).rstrip() + "\n"


def _compare_game_snapshots(
    previous: SnapshotPoint,
    current: SnapshotPoint,
) -> GameActivityRow:
    game = current.snapshot.game
    previous_tiers = {
        tier.prize_amount: tier.remaining_count for tier in previous.snapshot.prize_tiers
    }
    current_tiers = {
        tier.prize_amount: tier.remaining_count for tier in current.snapshot.prize_tiers
    }

    tier_rows: list[TierActivityRow] = []
    for prize_amount in sorted(set(previous_tiers) | set(current_tiers), reverse=True):
        previous_remaining = previous_tiers.get(prize_amount)
        remaining = current_tiers.get(prize_amount)
        implied_count = _implied_claimed_count(previous_remaining, remaining)
        implied_value = (
            prize_amount * Decimal(implied_count) if implied_count is not None else None
        )
        tier_rows.append(
            TierActivityRow(
                game_number=game.game_number,
                game_name=game.name,
                ticket_price=game.ticket_price,
                prize_amount=prize_amount,
                previous_observed_at=previous.observed_at,
                observed_at=current.observed_at,
                previous_remaining_count=previous_remaining,
                remaining_count=remaining,
                implied_claimed_count=implied_count,
                implied_claimed_value=implied_value,
            )
        )

    return GameActivityRow(
        game_number=game.game_number,
        game_name=game.name,
        ticket_price=game.ticket_price,
        previous_observed_at=previous.observed_at,
        observed_at=current.observed_at,
        implied_claimed_count=sum(
            row.implied_claimed_count or 0 for row in tier_rows
        ),
        implied_claimed_value=sum(
            (row.implied_claimed_value or Decimal("0") for row in tier_rows),
            Decimal("0"),
        ),
        tier_rows=tier_rows,
    )


def _implied_claimed_count(
    previous_remaining: int | None, remaining: int | None
) -> int | None:
    if previous_remaining is None or remaining is None:
        return None
    return previous_remaining - remaining


def _run_source_times(session: Session) -> dict[int, datetime]:
    rows = session.execute(
        select(
            ScrapeRun.id,
            func.coalesce(
                func.min(RawSourceSnapshot.captured_at),
                ScrapeRun.started_at,
            ).label("observed_at"),
        )
        .outerjoin(RawSourceSnapshot, RawSourceSnapshot.scrape_run_id == ScrapeRun.id)
        .group_by(ScrapeRun.id, ScrapeRun.started_at)
    ).all()
    return {row[0]: _ensure_utc(row[1]) for row in rows if row[1] is not None}


def _observed_at(
    snapshot: GameSnapshot,
    run_times: dict[int, datetime],
) -> datetime:
    return run_times.get(snapshot.scrape_run_id) or _ensure_utc(snapshot.captured_at)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _render_header(lines: list[str], report: ActivityReport) -> None:
    lines.extend(
        [
            "Prize Activity Report",
            "=====================",
            "Read-only movement report based on public unclaimed-prize counts.",
            "Implied counts are decreases in remaining-prize counts "
            "since the prior stored snapshot.",
            f"Latest observed at: {_fmt_dt(report.latest_observed_at)}",
            f"Compared intervals: {len(report.game_rows):,}",
        ]
    )


def _render_latest(lines: list[str], rows: list[GameActivityRow]) -> None:
    lines.append("Latest Implied Prize Activity")
    lines.append("-----------------------------")
    if not rows:
        lines.append("  (none)")
        return
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index:>2}. [{row.game_number}] {row.game_name} "
            f"price={_fmt_money(row.ticket_price)} "
            f"period={_fmt_date(row.previous_observed_at)}->{_fmt_date(row.observed_at)} "
            f"implied_claimed={row.implied_claimed_count:,} "
            f"implied_value={_fmt_money(row.implied_claimed_value)}"
        )


def _render_rolling(
    lines: list[str],
    rows: list[RollingActivityRow],
    *,
    window_days: int,
) -> None:
    lines.append(f"Rolling {window_days}-Day Implied Prize Activity")
    lines.append("-----------------------------------------")
    if not rows:
        lines.append("  (none)")
        return
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index:>2}. [{row.game_number}] {row.game_name} "
            f"price={_fmt_money(row.ticket_price)} "
            f"intervals={row.interval_count} "
            f"implied_claimed={row.implied_claimed_count:,} "
            f"implied_value={_fmt_money(row.implied_claimed_value)}"
        )


def _render_tiers(
    lines: list[str],
    report: ActivityReport,
    *,
    game_number: str | None,
) -> None:
    lines.append("Prize-Tier Implied Activity")
    lines.append("---------------------------")
    if not game_number:
        lines.append("  Provide --game-number to render prize-tier activity.")
        return
    rows = tier_activity_rows_for_game(report, game_number=game_number)
    if not rows:
        lines.append(f"  No tier activity found for game_number={game_number}.")
        return

    dates = _calendar_dates(
        min(row.observed_at.date() for row in rows),
        max(row.observed_at.date() for row in rows),
    )
    prizes = sorted({row.prize_amount for row in rows}, reverse=True)
    by_key = {(row.prize_amount, row.observed_at.date()): row for row in rows}

    lines.append(f"Game {game_number}: {rows[0].game_name}")
    header = ["Prize"] + [date.strftime("%-m/%-d") for date in dates]
    lines.append("  ".join(f"{col:>10}" for col in header))
    for prize in prizes:
        cells = [_fmt_money(prize)]
        for observed_date in dates:
            row = by_key.get((prize, observed_date))
            if row is None or row.implied_claimed_count is None:
                cells.append("N/A")
            else:
                cells.append(f"{row.implied_claimed_count:,}")
        lines.append("  ".join(f"{cell:>10}" for cell in cells))


def _fmt_money(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_date(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d")


def _calendar_dates(start: date, end: date) -> list[date]:
    dates: list[date] = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates
