"""Validate live Illinois Lottery collection through a dedicated Chrome profile.

This is an operator diagnostic. It saves immutable raw files, parses enough of
each source to prove that real content arrived, and never writes to the database.
By default Chrome is visible so an operator can complete a Cloudflare prompt if
one appears; this script does not attempt to solve or bypass such a prompt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from illinois_lottery_tracker.catalog import HUB_URL, HUB_WAIT_SELECTOR
from illinois_lottery_tracker.instant_ticket_discovery import (
    parse_instant_ticket_hub_html,
)
from illinois_lottery_tracker.parser import parse_html
from illinois_lottery_tracker.pipeline import validate_unpaid_prizes_html
from illinois_lottery_tracker.raw_collector import (
    DEFAULT_CHROME_EXECUTABLE,
    UNPAID_PRIZES_URL,
    UNPAID_PRIZES_WAIT_SELECTOR,
    PersistentChromeOptions,
    RawCollectionResult,
    cloudflare_challenge_marker,
    collect_raw_snapshot,
)

DEFAULT_PROFILE_DIR = Path("data/browser-profile/collector")


def _collect(
    *,
    url: str,
    filename_prefix: str,
    wait_selector: str,
    chrome_options: PersistentChromeOptions,
    timeout_seconds: int,
) -> RawCollectionResult:
    return collect_raw_snapshot(
        url=url,
        filename_prefix=filename_prefix,
        wait_selector=wait_selector,
        chrome_options=chrome_options,
        playwright_timeout_ms=timeout_seconds * 1_000,
        requests_first=False,
    )


def _reject_challenge(result: RawCollectionResult) -> bytes:
    content = Path(result.file_path).read_bytes()
    marker = cloudflare_challenge_marker(content)
    if marker is not None:
        raise RuntimeError(
            f"Cloudflare challenge remained after the browser wait (marker={marker!r}); "
            f"saved diagnostic HTML at {result.file_path}"
        )
    return content


def _check_unpaid(
    chrome_options: PersistentChromeOptions, timeout_seconds: int
) -> None:
    result = _collect(
        url=UNPAID_PRIZES_URL,
        filename_prefix="chrome-check-unpaid-prizes",
        wait_selector=UNPAID_PRIZES_WAIT_SELECTOR,
        chrome_options=chrome_options,
        timeout_seconds=timeout_seconds,
    )
    content = _reject_challenge(result)
    validate_unpaid_prizes_html(content)
    parsed = parse_html(Path(result.file_path))
    if not parsed.games:
        raise RuntimeError("the unpaid-prizes page contained no parseable games")
    print(
        f"PASS unpaid prizes: {len(parsed.games)} games, {result.bytes_written:,} bytes, "
        f"method={result.fetch_method}, file={result.file_path}"
    )


def _check_catalog(
    chrome_options: PersistentChromeOptions, timeout_seconds: int
) -> None:
    result = _collect(
        url=HUB_URL,
        filename_prefix="chrome-check-instant-ticket-hub-page-001",
        wait_selector=HUB_WAIT_SELECTOR,
        chrome_options=chrome_options,
        timeout_seconds=timeout_seconds,
    )
    _reject_challenge(result)
    discovery = parse_instant_ticket_hub_html(
        Path(result.file_path), source_url=HUB_URL
    )
    if not discovery.tickets:
        raise RuntimeError("the instant-ticket hub contained no parseable game cards")
    print(
        f"PASS instant-ticket hub: {len(discovery.tickets)} cards on page 1, "
        f"source total={discovery.total_count}, {result.bytes_written:,} bytes, "
        f"method={result.fetch_method}, file={result.file_path}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture and validate Illinois Lottery source pages with installed Chrome; "
            "no database writes are performed."
        )
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help=f"Dedicated collector profile (default: {DEFAULT_PROFILE_DIR}).",
    )
    parser.add_argument(
        "--chrome-executable",
        default=DEFAULT_CHROME_EXECUTABLE,
        help=f"Installed Chrome executable (default: {DEFAULT_CHROME_EXECUTABLE}).",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome without a visible window.",
    )
    parser.add_argument(
        "--force-x11",
        action="store_true",
        help="Force Chrome onto the X11 display supplied by Xvfb.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        metavar="N",
        help="Maximum wait per target page (default: 120).",
    )
    parser.add_argument(
        "--target",
        choices=("both", "unpaid", "catalog"),
        default="both",
        help="Source page to check (default: both).",
    )
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    chrome_options = PersistentChromeOptions(
        profile_dir=args.profile_dir,
        executable_path=args.chrome_executable,
        headless=args.headless,
        force_x11=args.force_x11,
    )
    mode = "headless" if args.headless else "visible"
    print(
        f"Using {mode} Chrome with dedicated profile {args.profile_dir}. "
        "No database rows will be written."
    )

    checks = []
    if args.target in {"both", "unpaid"}:
        checks.append(("unpaid prizes", _check_unpaid))
    if args.target in {"both", "catalog"}:
        checks.append(("instant-ticket hub", _check_catalog))

    failed = False
    for label, check in checks:
        try:
            check(chrome_options, args.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 -- operator diagnostic boundary
            failed = True
            print(f"FAIL {label}: {exc}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
