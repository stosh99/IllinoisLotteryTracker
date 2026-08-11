"""Unit tests for JSON-safe nightly operational status values."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from illinois_lottery_tracker.analytics.status import _row_document


def test_row_document_converts_dates_and_decimals_for_json() -> None:
    document = _row_document(
        {
            "source_date": date(2026, 8, 10),
            "median_lag_days": Decimal("4.2500"),
            "count": 57,
        }
    )

    assert document == {
        "source_date": "2026-08-10",
        "median_lag_days": 4.25,
        "count": 57,
    }
    assert json.loads(json.dumps(document)) == document
