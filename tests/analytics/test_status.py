from illinois_lottery_tracker.analytics.status import freshness


def test_source_freshness_boundaries_are_exact():
    assert freshness(None) == "unavailable"
    assert freshness(36) == "fresh"
    assert freshness(36.0001) == "stale_warning"
    assert freshness(72) == "stale_warning"
    assert freshness(72.0001) == "stale_error"
