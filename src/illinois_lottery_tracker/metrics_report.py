"""Read-only reporting for stored Phase 1 normalized snapshot metrics.

The report presents cautious estimates based on public unclaimed-prize data.
It does not calculate metrics, fetch source data, or write database rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import Game, GameSnapshot, RawSourceSnapshot, ScrapeRun


class MetricsReportSection(StrEnum):
    ALL = "all"
    GAME = "game"
    PAYOUT = "payout"
    EXCLUDING_TOP = "excluding-top"
    LAUNCH = "launch"
    DEPLETED = "depleted"
    MISSING_ODDS = "missing-odds"
    CAUTION = "caution"


@dataclass(frozen=True)
class MetricsReportRow:
    game_number: str
    game_name: str
    ticket_price: Decimal | None
    snapshot_id: int
    scrape_run_id: int
    source_captured_at: datetime | None
    run_started_at: datetime | None
    estimated_ev: Decimal | None
    estimated_ev_excluding_top_prize: Decimal | None
    estimated_payout_ratio: Decimal | None
    estimated_house_edge: Decimal | None
    estimated_payout_ratio_excluding_top_prize: Decimal | None
    launch_ev: Decimal | None
    launch_payout_ratio: Decimal | None
    ev_vs_launch_ratio: Decimal | None
    remaining_prize_value_pct: Decimal | None
    remaining_winning_tickets_pct: Decimal | None
    top_prize_remaining_pct: Decimal | None
    top_prize_depleted: bool | None
    top_prizes_original: int | None
    top_prizes_remaining: int | None
    overall_odds_one_in: Decimal | None = None
    est_total_tickets: int | None = None
    estimated_tickets_remaining: int | None = None
    total_original_winning_tickets: int | None = None
    total_remaining_winning_tickets: int | None = None
    prize_tiers: tuple["MetricsPrizeTierRow", ...] = ()

    @property
    def has_odds_dependent_metrics(self) -> bool:
        return self.estimated_payout_ratio is not None


@dataclass(frozen=True)
class MetricsPrizeTierRow:
    prize_amount: Decimal
    original_count: int | None
    remaining_count: int | None
    claimed_count: int | None


@dataclass(frozen=True)
class MetricsReport:
    latest_source_captured_at: datetime | None
    latest_run_started_at: datetime | None
    rows: list[MetricsReportRow]

    @property
    def game_count(self) -> int:
        return len(self.rows)

    @property
    def odds_metric_count(self) -> int:
        return sum(1 for row in self.rows if row.has_odds_dependent_metrics)

    @property
    def missing_odds_metric_count(self) -> int:
        return self.game_count - self.odds_metric_count


def build_metrics_report(session: Session) -> MetricsReport:
    """Return latest available active-game metric rows.

    "Latest" is determined by source capture time for the scrape run when a
    RawSourceSnapshot exists, falling back to ScrapeRun.started_at. Selection is
    per game, so an active game missing from the newest snapshot set can still
    appear with its latest available stored snapshot.
    """
    run_times = _run_source_times(session)
    snapshots = list(
        session.scalars(
            select(GameSnapshot)
            .join(Game)
            .where(Game.is_active.is_(True))
            .options(
                selectinload(GameSnapshot.game),
                selectinload(GameSnapshot.scrape_run),
                selectinload(GameSnapshot.prize_tiers),
            )
        )
    )

    latest_by_game: dict[int, GameSnapshot] = {}
    for snap in snapshots:
        current = latest_by_game.get(snap.game_id)
        if current is None or _snapshot_sort_key(snap, run_times) > _snapshot_sort_key(
            current, run_times
        ):
            latest_by_game[snap.game_id] = snap

    rows = [
        _row_from_snapshot(snap, run_times)
        for snap in sorted(
            latest_by_game.values(),
            key=lambda s: (s.game.game_number, s.id),
        )
    ]
    latest_source = max(
        (row.source_captured_at for row in rows if row.source_captured_at is not None),
        default=None,
    )
    latest_started = max(
        (row.run_started_at for row in rows if row.run_started_at is not None),
        default=None,
    )
    return MetricsReport(
        latest_source_captured_at=latest_source,
        latest_run_started_at=latest_started,
        rows=rows,
    )


def top_estimated_payout_rows(
    report: MetricsReport, *, limit: int
) -> list[MetricsReportRow]:
    return _rank_rows(report.rows, "estimated_payout_ratio", limit=limit)


def top_excluding_top_prize_rows(
    report: MetricsReport, *, limit: int
) -> list[MetricsReportRow]:
    return _rank_rows(
        report.rows,
        "estimated_payout_ratio_excluding_top_prize",
        limit=limit,
    )


def top_ev_vs_launch_rows(report: MetricsReport, *, limit: int) -> list[MetricsReportRow]:
    return _rank_rows(report.rows, "ev_vs_launch_ratio", limit=limit)


def depleted_top_prize_rows(
    report: MetricsReport, *, limit: int | None = None
) -> list[MetricsReportRow]:
    rows = [row for row in report.rows if row.top_prize_depleted is True]
    rows.sort(
        key=lambda row: (
            _none_low(row.estimated_payout_ratio),
            row.game_number,
        ),
        reverse=True,
    )
    return rows if limit is None else rows[:limit]


def missing_odds_rows(
    report: MetricsReport, *, limit: int | None = None
) -> list[MetricsReportRow]:
    rows = [row for row in report.rows if not row.has_odds_dependent_metrics]
    rows.sort(key=lambda row: (row.game_number, row.game_name))
    return rows if limit is None else rows[:limit]


def game_detail_row(
    report: MetricsReport,
    *,
    game_number: str,
) -> MetricsReportRow | None:
    for row in report.rows:
        if row.game_number == game_number:
            return row
    return None


def caution_rows(
    report: MetricsReport,
    *,
    limit: int,
    payout_threshold: Decimal = Decimal("0.55"),
    launch_threshold: Decimal = Decimal("0.75"),
) -> list[MetricsReportRow]:
    rows = [
        row
        for row in report.rows
        if row.top_prize_depleted is True
        or (
            row.estimated_payout_ratio is not None
            and row.estimated_payout_ratio < payout_threshold
        )
        or (row.ev_vs_launch_ratio is not None and row.ev_vs_launch_ratio < launch_threshold)
    ]
    rows.sort(
        key=lambda row: (
            row.top_prize_depleted is not True,
            _none_high(row.estimated_payout_ratio),
            _none_high(row.ev_vs_launch_ratio),
            row.game_number,
        )
    )
    return rows[:limit]


def format_money(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def format_percent(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * Decimal('100'):.1f}%"


def format_count_pair(remaining: int | None, original: int | None) -> str:
    if remaining is None or original is None:
        return "N/A"
    return f"{remaining:,}/{original:,}"


def format_odds(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return f"1 in {value:,.0f}"


def format_overall_odds(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    text = f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"1 in {text}"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return _ensure_utc(value).strftime("%Y-%m-%d %H:%M:%S UTC")


def render_text_report(
    report: MetricsReport,
    *,
    limit: int = 10,
    section: MetricsReportSection = MetricsReportSection.ALL,
    game_number: str | None = None,
) -> str:
    lines: list[str] = []
    _render_header(lines, report)

    sections = (
        [section]
        if section is not MetricsReportSection.ALL
        else [
            MetricsReportSection.PAYOUT,
            MetricsReportSection.EXCLUDING_TOP,
            MetricsReportSection.LAUNCH,
            MetricsReportSection.DEPLETED,
            MetricsReportSection.MISSING_ODDS,
            MetricsReportSection.CAUTION,
        ]
    )
    for selected in sections:
        lines.append("")
        if selected is MetricsReportSection.GAME:
            _render_game_detail(lines, report, game_number=game_number)
        elif selected is MetricsReportSection.PAYOUT:
            _render_payout(lines, top_estimated_payout_rows(report, limit=limit))
        elif selected is MetricsReportSection.EXCLUDING_TOP:
            _render_excluding_top(lines, top_excluding_top_prize_rows(report, limit=limit))
        elif selected is MetricsReportSection.LAUNCH:
            _render_launch(lines, top_ev_vs_launch_rows(report, limit=limit))
        elif selected is MetricsReportSection.DEPLETED:
            _render_depleted(lines, depleted_top_prize_rows(report, limit=limit))
        elif selected is MetricsReportSection.MISSING_ODDS:
            _render_missing_odds(lines, missing_odds_rows(report, limit=limit))
        elif selected is MetricsReportSection.CAUTION:
            _render_caution(lines, caution_rows(report, limit=limit))

    return "\n".join(lines).rstrip() + "\n"


def _run_source_times(session: Session) -> dict[int, tuple[datetime | None, datetime | None]]:
    rows = session.execute(
        select(
            ScrapeRun.id,
            func.min(RawSourceSnapshot.captured_at).label("source_captured_at"),
            ScrapeRun.started_at,
        )
        .outerjoin(RawSourceSnapshot, RawSourceSnapshot.scrape_run_id == ScrapeRun.id)
        .group_by(ScrapeRun.id, ScrapeRun.started_at)
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def _snapshot_sort_key(
    snapshot: GameSnapshot,
    run_times: dict[int, tuple[datetime | None, datetime | None]],
) -> tuple[datetime, int, datetime, int]:
    source_captured_at, run_started_at = run_times.get(
        snapshot.scrape_run_id, (None, snapshot.scrape_run.started_at)
    )
    primary = _ensure_utc(
        source_captured_at or run_started_at or datetime.min.replace(tzinfo=UTC)
    )
    captured = _ensure_utc(snapshot.captured_at or datetime.min.replace(tzinfo=UTC))
    return (primary, snapshot.scrape_run_id, captured, snapshot.id)


def _row_from_snapshot(
    snapshot: GameSnapshot,
    run_times: dict[int, tuple[datetime | None, datetime | None]],
) -> MetricsReportRow:
    source_captured_at, run_started_at = run_times.get(
        snapshot.scrape_run_id, (None, snapshot.scrape_run.started_at)
    )
    game = snapshot.game
    return MetricsReportRow(
        game_number=game.game_number,
        game_name=game.name,
        ticket_price=game.ticket_price,
        snapshot_id=snapshot.id,
        scrape_run_id=snapshot.scrape_run_id,
        source_captured_at=_ensure_utc(source_captured_at),
        run_started_at=_ensure_utc(run_started_at),
        estimated_ev=snapshot.estimated_ev,
        estimated_ev_excluding_top_prize=snapshot.estimated_ev_excluding_top_prize,
        estimated_payout_ratio=snapshot.estimated_payout_ratio,
        estimated_house_edge=snapshot.estimated_house_edge,
        estimated_payout_ratio_excluding_top_prize=(
            snapshot.estimated_payout_ratio_excluding_top_prize
        ),
        launch_ev=snapshot.launch_ev,
        launch_payout_ratio=snapshot.launch_payout_ratio,
        ev_vs_launch_ratio=snapshot.ev_vs_launch_ratio,
        remaining_prize_value_pct=snapshot.remaining_prize_value_pct,
        remaining_winning_tickets_pct=snapshot.remaining_winning_tickets_pct,
        top_prize_remaining_pct=snapshot.top_prize_remaining_pct,
        top_prize_depleted=snapshot.top_prize_depleted,
        top_prizes_original=snapshot.top_prizes_original,
        top_prizes_remaining=snapshot.top_prizes_remaining,
        overall_odds_one_in=game.overall_odds_one_in,
        est_total_tickets=game.est_total_tickets,
        estimated_tickets_remaining=snapshot.estimated_tickets_remaining,
        total_original_winning_tickets=snapshot.total_original_winning_tickets,
        total_remaining_winning_tickets=snapshot.total_remaining_winning_tickets,
        prize_tiers=tuple(
            MetricsPrizeTierRow(
                prize_amount=tier.prize_amount,
                original_count=tier.original_count,
                remaining_count=tier.remaining_count,
                claimed_count=tier.claimed_count,
            )
            for tier in sorted(
                snapshot.prize_tiers,
                key=lambda tier: tier.prize_amount,
                reverse=True,
            )
        ),
    )


def _rank_rows(
    rows: list[MetricsReportRow], attr: str, *, limit: int
) -> list[MetricsReportRow]:
    ranked = [row for row in rows if getattr(row, attr) is not None]
    ranked.sort(key=lambda row: (getattr(row, attr), row.game_number), reverse=True)
    return ranked[:limit]


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _none_low(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("-999999999")


def _none_high(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("999999999")


def _render_header(lines: list[str], report: MetricsReport) -> None:
    lines.extend(
        [
            "Estimated Metrics Report",
            "========================",
            "Read-only report of stored Phase 1 normalized snapshot metrics.",
            "Values are estimates based on public unclaimed-prize and remaining-prize data.",
            f"Latest source captured at: {format_datetime(report.latest_source_captured_at)}",
            f"Latest run started at:     {format_datetime(report.latest_run_started_at)}",
            f"Games included:            {report.game_count}",
            f"Games with odds metrics:   {report.odds_metric_count}",
            f"Games missing odds metrics:{report.missing_odds_metric_count:>6}",
        ]
    )


def _render_game_detail(
    lines: list[str],
    report: MetricsReport,
    *,
    game_number: str | None,
) -> None:
    lines.append("Game Detail")
    lines.append("-----------")
    if not game_number:
        lines.append("  Provide --game-number to render game detail.")
        return

    row = game_detail_row(report, game_number=game_number)
    if row is None:
        lines.append(f"  No active game found for game_number={game_number}.")
        return

    original_tickets = _original_ticket_denominator(row)
    lines.extend(
        [
            f"[{row.game_number}] {row.game_name}",
            f"price={format_money(row.ticket_price)} "
            f"overall_odds={format_overall_odds(row.overall_odds_one_in)} "
            f"snapshot={row.snapshot_id}",
            f"estimated_original_tickets={_fmt_int(original_tickets)} "
            f"estimated_tickets_remaining={_fmt_int(row.estimated_tickets_remaining)}",
            f"est_ev={format_money(row.estimated_ev)} "
            f"est_payout={format_percent(row.estimated_payout_ratio)} "
            f"ev_vs_launch={format_percent(row.ev_vs_launch_ratio)}",
            f"remaining_prize_value={format_percent(row.remaining_prize_value_pct)} "
            f"remaining_winning_tickets={format_percent(row.remaining_winning_tickets_pct)} "
            f"top_prizes={format_count_pair(row.top_prizes_remaining, row.top_prizes_original)}",
            "",
            "Prize Tiers",
            "      Prize    Original    Remaining      Claimed    Orig odds    Est odds now",
        ]
    )
    for tier in row.prize_tiers:
        original_odds = _tier_odds(original_tickets, tier.original_count)
        estimated_odds_now = _tier_odds(
            row.estimated_tickets_remaining,
            tier.remaining_count,
        )
        lines.append(
            f"{format_money(tier.prize_amount):>11} "
            f"{_fmt_int(tier.original_count):>11} "
            f"{_fmt_int(tier.remaining_count):>12} "
            f"{_fmt_int(tier.claimed_count):>12} "
            f"{format_odds(original_odds):>12} "
            f"{format_odds(estimated_odds_now):>15}"
        )
    total_claimed = _count_difference(
        row.total_original_winning_tickets,
        row.total_remaining_winning_tickets,
    )
    current_overall_odds = _tier_odds(
        row.estimated_tickets_remaining,
        row.total_remaining_winning_tickets,
    )
    lines.append(
        f"{'Totals':>11} "
        f"{_fmt_int(row.total_original_winning_tickets):>11} "
        f"{_fmt_int(row.total_remaining_winning_tickets):>12} "
        f"{_fmt_int(total_claimed):>12} "
        f"{format_overall_odds(row.overall_odds_one_in):>12} "
        f"{format_overall_odds(current_overall_odds):>15}"
    )


def _render_payout(lines: list[str], rows: list[MetricsReportRow]) -> None:
    lines.append("Top Estimated Payout Ratio")
    lines.append("--------------------------")
    if not rows:
        lines.append("  (none)")
        return
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index:>2}. {_label(row)} price={format_money(row.ticket_price)} "
            f"est_ev={format_money(row.estimated_ev)} "
            f"est_payout={format_percent(row.estimated_payout_ratio)} "
            f"est_house_edge={format_percent(row.estimated_house_edge)} "
            f"ev_vs_launch={format_percent(row.ev_vs_launch_ratio)} "
            f"remaining_prize_value={format_percent(row.remaining_prize_value_pct)} "
            f"top_prizes={format_count_pair(row.top_prizes_remaining, row.top_prizes_original)}"
        )


def _render_excluding_top(lines: list[str], rows: list[MetricsReportRow]) -> None:
    lines.append("Top Estimated Payout Ratio Excluding Top Prize")
    lines.append("----------------------------------------------")
    if not rows:
        lines.append("  (none)")
        return
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index:>2}. {_label(row)} price={format_money(row.ticket_price)} "
            f"est_ev_ex_top={format_money(row.estimated_ev_excluding_top_prize)} "
            f"est_payout_ex_top="
            f"{format_percent(row.estimated_payout_ratio_excluding_top_prize)} "
            f"est_payout={format_percent(row.estimated_payout_ratio)} "
            f"top_prize_depleted={_fmt_bool(row.top_prize_depleted)}"
        )


def _render_launch(lines: list[str], rows: list[MetricsReportRow]) -> None:
    lines.append("Best Current Estimated EV Versus Launch EV")
    lines.append("------------------------------------------")
    if not rows:
        lines.append("  (none)")
        return
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index:>2}. {_label(row)} price={format_money(row.ticket_price)} "
            f"launch_ev={format_money(row.launch_ev)} "
            f"est_ev={format_money(row.estimated_ev)} "
            f"ev_vs_launch={format_percent(row.ev_vs_launch_ratio)} "
            f"launch_payout={format_percent(row.launch_payout_ratio)} "
            f"est_payout={format_percent(row.estimated_payout_ratio)}"
        )


def _render_depleted(lines: list[str], rows: list[MetricsReportRow]) -> None:
    lines.append("Games With Depleted Top Prizes")
    lines.append("------------------------------")
    if not rows:
        lines.append("  (none)")
        return
    for row in rows:
        lines.append(
            f"- {_label(row)} price={format_money(row.ticket_price)} "
            f"top_prizes={format_count_pair(row.top_prizes_remaining, row.top_prizes_original)} "
            f"est_payout={format_percent(row.estimated_payout_ratio)} "
            f"est_payout_ex_top="
            f"{format_percent(row.estimated_payout_ratio_excluding_top_prize)} "
            f"remaining_prize_value={format_percent(row.remaining_prize_value_pct)}"
        )


def _render_missing_odds(lines: list[str], rows: list[MetricsReportRow]) -> None:
    lines.append("Games Missing Odds Metadata")
    lines.append("---------------------------")
    lines.append("EV and odds-dependent metrics cannot be computed without odds metadata.")
    if not rows:
        lines.append("  (none)")
        return
    for row in rows:
        lines.append(
            f"- {_label(row)} price={format_money(row.ticket_price)} "
            f"remaining_prize_value={format_percent(row.remaining_prize_value_pct)} "
            f"remaining_count_pct={format_percent(row.remaining_winning_tickets_pct)} "
            f"top_prize_remaining={format_percent(row.top_prize_remaining_pct)}"
        )


def _render_caution(lines: list[str], rows: list[MetricsReportRow]) -> None:
    lines.append("Games To Review Carefully")
    lines.append("-------------------------")
    if not rows:
        lines.append("  (none)")
        return
    for row in rows:
        reasons = []
        if row.top_prize_depleted is True:
            reasons.append("top prize depleted")
        if row.estimated_payout_ratio is not None and row.estimated_payout_ratio < Decimal(
            "0.55"
        ):
            reasons.append("lower estimated payout ratio")
        if row.ev_vs_launch_ratio is not None and row.ev_vs_launch_ratio < Decimal(
            "0.75"
        ):
            reasons.append("lower current estimate versus launch")
        lines.append(
            f"- {_label(row)} price={format_money(row.ticket_price)} "
            f"est_payout={format_percent(row.estimated_payout_ratio)} "
            f"ev_vs_launch={format_percent(row.ev_vs_launch_ratio)} "
            f"reason={', '.join(reasons) if reasons else 'review'}"
        )


def _label(row: MetricsReportRow) -> str:
    return f"[{row.game_number}] {row.game_name}"


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "N/A"
    return "yes" if value else "no"


def _fmt_int(value: int | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,}"


def _original_ticket_denominator(row: MetricsReportRow) -> int | None:
    if row.est_total_tickets is not None:
        return row.est_total_tickets
    if row.total_original_winning_tickets is None or row.overall_odds_one_in is None:
        return None
    return round(Decimal(row.total_original_winning_tickets) * row.overall_odds_one_in)


def _tier_odds(
    ticket_denominator: int | None,
    prize_count: int | None,
) -> Decimal | None:
    if ticket_denominator is None or not prize_count:
        return None
    return Decimal(ticket_denominator) / Decimal(prize_count)


def _count_difference(original: int | None, remaining: int | None) -> int | None:
    if original is None or remaining is None:
        return None
    return original - remaining
