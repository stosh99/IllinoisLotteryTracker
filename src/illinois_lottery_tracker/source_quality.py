"""Deterministic validation and provenance helpers for observed source data."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .parser import ParseResult

CHICAGO_TIME_ZONE = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class SourceQualityIssue:
    code: str
    message: str
    game_number: str | None = None
    prize_amount: Decimal | None = None


@dataclass(frozen=True)
class SourceQualityReport:
    parsed_game_count: int
    parsed_prize_tier_count: int
    issues: tuple[SourceQualityIssue, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not self.issues


class SourceQualityError(ValueError):
    """Raised when parsed source data cannot be stored as a complete run."""


@dataclass(frozen=True)
class SourceCompletenessDecision:
    is_complete: bool
    reasons: tuple[str, ...]
    parsed_game_count: int
    parsed_prize_tier_count: int
    prior_game_count: int | None
    prior_prize_tier_count: int | None
    manually_approved: bool


def chicago_source_date(observed_at: datetime) -> date:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("source observation timestamp must be timezone-aware")
    return observed_at.astimezone(CHICAGO_TIME_ZONE).date()


def canonical_structure_serialization(
    tiers: Iterable[tuple[Decimal | int, int]],
) -> str:
    normalized: list[tuple[Decimal, int]] = []
    seen: set[Decimal] = set()
    for raw_amount, original_count in tiers:
        amount = Decimal(raw_amount).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValueError("prize amount must be positive")
        if original_count < 0:
            raise ValueError("original count must be nonnegative")
        if amount in seen:
            raise ValueError(f"duplicate prize amount: {amount}")
        seen.add(amount)
        normalized.append((amount, original_count))
    if not normalized:
        raise ValueError("at least one tier is required")
    normalized.sort(key=lambda item: item[0])
    return "|".join(f"{amount:.2f}:{count}" for amount, count in normalized)


def structure_fingerprint(tiers: Iterable[tuple[Decimal | int, int]]) -> str:
    serialization = canonical_structure_serialization(tiers)
    return hashlib.sha256(serialization.encode("utf-8")).hexdigest()


def assess_parse_result(parse_result: ParseResult) -> SourceQualityReport:
    issues: list[SourceQualityIssue] = []
    seen_games: set[str] = set()
    tier_count = 0

    for game in parse_result.games:
        game_number = game.game_number
        if not game_number:
            issues.append(
                SourceQualityIssue("MISSING_GAME_NUMBER", "game number is required")
            )
        elif game_number in seen_games:
            issues.append(
                SourceQualityIssue(
                    "DUPLICATE_GAME_NUMBER",
                    "game number appears more than once in the source",
                    game_number=game_number,
                )
            )
        else:
            seen_games.add(game_number)

        if not game.prize_tiers:
            issues.append(
                SourceQualityIssue(
                    "MISSING_PRIZE_TIERS",
                    "game has no prize tiers",
                    game_number=game_number,
                )
            )
            continue

        seen_amounts: set[Decimal] = set()
        for tier in game.prize_tiers:
            tier_count += 1
            amount = Decimal(tier.prize_amount) if tier.prize_amount is not None else None
            if amount is None or amount <= 0:
                issues.append(
                    SourceQualityIssue(
                        "INVALID_PRIZE_AMOUNT",
                        "prize amount must be present and positive",
                        game_number=game_number,
                        prize_amount=amount,
                    )
                )
            elif amount in seen_amounts:
                issues.append(
                    SourceQualityIssue(
                        "DUPLICATE_PRIZE_AMOUNT",
                        "prize amount appears more than once for the game",
                        game_number=game_number,
                        prize_amount=amount,
                    )
                )
            else:
                seen_amounts.add(amount)

            original = tier.total_prizes
            remaining = tier.unclaimed_prizes
            if original is None or remaining is None:
                issues.append(
                    SourceQualityIssue(
                        "INVALID_TIER_COUNT",
                        "original and remaining counts must be present",
                        game_number=game_number,
                        prize_amount=amount,
                    )
                )
            elif original < 0 or remaining < 0 or remaining > original:
                issues.append(
                    SourceQualityIssue(
                        "INVALID_TIER_COUNT",
                        "counts must be nonnegative and remaining cannot exceed original",
                        game_number=game_number,
                        prize_amount=amount,
                    )
                )

    return SourceQualityReport(
        parsed_game_count=len(seen_games),
        parsed_prize_tier_count=tier_count,
        issues=tuple(issues),
    )


def require_valid_parse_result(parse_result: ParseResult) -> SourceQualityReport:
    report = assess_parse_result(parse_result)
    if not report.is_valid:
        first = report.issues[0]
        raise SourceQualityError(f"{first.code}: {first.message}")
    return report


def evaluate_source_completeness(
    report: SourceQualityReport,
    *,
    prior_game_count: int | None,
    prior_prize_tier_count: int | None,
    minimum_games: int = 40,
    prior_fraction_numerator: int = 80,
    prior_fraction_denominator: int = 100,
    manually_approved: bool = False,
) -> SourceCompletenessDecision:
    if minimum_games < 1:
        raise ValueError("minimum_games must be positive")
    reasons = [issue.code for issue in report.issues]
    if report.parsed_game_count < minimum_games:
        reasons.append("ABSOLUTE_GAME_COUNT")
    if report.parsed_prize_tier_count < report.parsed_game_count:
        reasons.append("MISSING_PRIZE_TIERS")

    relative_reasons: list[str] = []
    if prior_game_count is not None and (
        report.parsed_game_count * prior_fraction_denominator
        < prior_game_count * prior_fraction_numerator
    ):
        relative_reasons.append("RELATIVE_GAME_COUNT")
    if prior_prize_tier_count is not None and (
        report.parsed_prize_tier_count * prior_fraction_denominator
        < prior_prize_tier_count * prior_fraction_numerator
    ):
        relative_reasons.append("RELATIVE_PRIZE_TIER_COUNT")
    if not manually_approved:
        reasons.extend(relative_reasons)

    return SourceCompletenessDecision(
        is_complete=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        parsed_game_count=report.parsed_game_count,
        parsed_prize_tier_count=report.parsed_prize_tier_count,
        prior_game_count=prior_game_count,
        prior_prize_tier_count=prior_prize_tier_count,
        manually_approved=manually_approved,
    )
