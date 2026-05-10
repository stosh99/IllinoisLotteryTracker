You are working on the IllinoisLotteryTracker project.

Project goal:
IllinoisLotteryTracker is a Python-first, data-first pipeline for tracking Illinois Lottery instant ticket prize availability over time. The public UI is intentionally deferred until the data pipeline is reliable.

Important project principles:
- Preserve raw source files.
- Do not overwrite historical snapshots.
- Keep parsers testable with local fixtures.
- Do not make live network calls in tests.
- Keep parsing separate from database writes.
- Treat expected value and ticket-count calculations as estimates.
- Do not build UI in this task.

Current project context:
The project already has a working foundation for the unpaid instant prizes page:

- scripts/check_db.py verifies database connectivity.
- scripts/collect_raw_snapshot.py collects the unpaid instant prizes page, saves raw HTML, and records ScrapeRun / RawSourceSnapshot.
- scripts/discover_source.py was a one-shot Playwright discovery diagnostic for the unpaid-prizes page.
- scripts/parse_saved_html.py parses a saved unpaid-prizes HTML file and prints a summary.
- illinois_lottery_tracker.parser currently parses the unpaid-prizes table.
- Existing parser tests cover game name, display name, ticket price, data-price, game number, weeks in market, prize tiers, total prizes, and unclaimed prizes.
- Existing parser tests intentionally include hidden table rows, because the unpaid-prizes page embeds rows that may be hidden by CSS pagination/filtering.

Important clarification:
The unpaid-prizes page is good for prize availability data:
- game name
- ticket price
- game number
- weeks in market
- prize values
- total prize counts
- unclaimed prize counts

But the unpaid-prizes page does not appear to provide the richer per-ticket metadata we need:
- overall odds
- launch/start date
- end date / expiration date
- claim deadline
- ticket image
- play style
- category
- rules/details
- individual game detail URL

The next phase is to discover and parse individual instant-ticket detail pages.

Starting page:
https://www.illinoislottery.com/games-hub/instant-tickets

Current observation:
The instant-tickets hub appears to list ticket cards with “Find out more” links. It is paginated, currently showing a page range such as “1 - 20 of 58”, so do not assume the first hub page includes all tickets unless the raw HTML proves that all cards are embedded. Individual ticket detail pages appear to contain metadata such as:
- Price Point
- Overall Odds
- Category
- Play Style
- Launch Date
- Game Number
- ticket title/name
- ticket image
- play instructions
- consolidated odds section

Example detail page pattern:
https://www.illinoislottery.com/games-hub/instant-tickets/loteria-2026

Task goal:
Implement individual instant-ticket source discovery and detail-page parsing.

This task should add a new pipeline stage that:
1. Discovers individual instant-ticket detail URLs from the instant-tickets hub.
2. Handles hub pagination or proves that all ticket links are embedded in one HTML response.
3. Saves raw HTML for the hub page(s) and each individual ticket detail page.
4. Parses each individual ticket detail page into structured metadata.
5. Provides tests and fixture-backed parsing.
6. Provides CLI diagnostics.
7. Does not write parsed detail data into production tables yet unless explicitly scoped as a separate import step.

Do not replace the existing unpaid-prizes parser.
Do not break existing tests.
Do not build UI.

Recommended implementation shape:

1. Add a new module for instant-ticket hub discovery.

Possible module:
src/illinois_lottery_tracker/instant_ticket_discovery.py

Responsibilities:
- Parse saved instant-tickets hub HTML.
- Extract individual ticket detail URLs from “Find out more” links.
- Normalize relative URLs to absolute URLs.
- Detect pagination links if present.
- Return a structured discovery result.
- Record parser/discovery warnings instead of failing on minor page-shape differences.

Suggested dataclasses:

@dataclass(frozen=True)
class DiscoveredInstantTicket:
    detail_url: str
    slug: str | None = None
    display_name: str | None = None
    ticket_price: int | None = None
    top_prize_text: str | None = None
    raw_card_text: str | None = None

@dataclass(frozen=True)
class InstantTicketHubDiscoveryResult:
    source_url: str | None
    tickets: list[DiscoveredInstantTicket]
    pagination_urls: list[str]
    current_page_label: str | None
    total_count: int | None
    warnings: list[str]

Functions:
- parse_instant_ticket_hub_html(source: str | Path, *, source_url: str | None = None) -> InstantTicketHubDiscoveryResult
- normalize_illinois_lottery_url(href: str, *, base_url: str = "https://www.illinoislottery.com") -> str
- extract_page_number_or_range(text: str) -> something simple if useful

Discovery behavior:
- Find links whose href looks like /games-hub/instant-tickets/<slug>.
- Prefer links associated with card actions such as “Find out more”.
- Exclude generic hub links, footer links, menu links, external promo links, unclaimed prizes page, and non-ticket pages.
- Deduplicate by normalized detail URL.
- Preserve order as displayed.
- Detect whether pagination uses query params such as ?page=1.
- Return pagination URLs to be collected by a separate collector or CLI.

2. Add collection support for instant-ticket hub/detail pages.

Do not over-engineer. Reuse the project’s existing raw collection patterns where possible.

Possible approaches:
- Reuse collect_raw_snapshot(url=..., settings=...) for arbitrary URLs if it already supports that cleanly.
- If collect_raw_snapshot currently names every file as unpaid-instant-games-prizes, either:
  a) extend it to support a caller-provided filename prefix safely, or
  b) add a small new collector function for arbitrary Illinois Lottery pages.

Requirements:
- Save hub pages under dated raw directories.
- Save detail pages under dated raw directories.
- Use safe filenames based on the URL slug.
- Preserve content type, sha256, captured_at, source_url.
- Do not overwrite raw files.
- Do not require database writes from the collector unless existing collector design makes this unavoidable.

Possible filename examples:
data/raw/YYYY-MM-DD/instant-ticket-hub-page-001-<timestamp>.html
data/raw/YYYY-MM-DD/instant-ticket-detail-loteria-2026-<timestamp>.html

3. Add a detail-page parser.

Possible module:
src/illinois_lottery_tracker/instant_ticket_detail_parser.py

Responsibilities:
- Parse one saved individual instant-ticket detail HTML page.
- Extract stable game metadata.
- Return structured result plus warnings.
- Do not write to the database.
- Do not fetch the network.

Suggested dataclasses:

@dataclass(frozen=True)
class ParsedInstantTicketDetail:
    source_url: str | None
    detail_slug: str | None
    game_name: str | None
    display_name: str | None
    game_number: str | None
    ticket_price: int | None
    overall_odds: Decimal | None
    overall_odds_text: str | None
    category: str | None
    play_style: str | None
    launch_date: date | None
    top_prize_text: str | None
    image_url: str | None
    play_instructions: str | None
    consolidated_odds_present: bool
    raw_fields: dict[str, str]
    warnings: list[str]

Functions:
- parse_instant_ticket_detail_html(source: str | Path, *, source_url: str | None = None) -> ParsedInstantTicketDetail
- parse_odds_text(text: str) -> Decimal | None
- parse_price_point(text: str) -> int | None
- parse_launch_date(text: str) -> date | None

Parsing targets:
- h1/title ticket name
- Game Number
- Price Point
- Overall Odds
- Category
- Play Style
- Launch Date
- Top Prize / Win up to text
- ticket image URL, if available
- play instructions, if available
- whether a Consolidated Odds section exists

Parsing details:
- Overall odds like “1 in 3.85” should be stored as Decimal("3.85") and preserve the original text as overall_odds_text.
- Price Point like “$3” should become integer 3.
- Launch Date like “May 5, 2026” should become ISO date 2026-05-05.
- Game Number should remain string, not int.
- If a field is missing, return None and add a warning only if the field is important.
- Preserve raw extracted label/value pairs in raw_fields for debugging.

4. Add CLI diagnostics.

Add one or both of these scripts:

scripts/discover_instant_ticket_pages.py

Purpose:
- Fetch or parse the instant-tickets hub page(s).
- Print discovered detail URLs.
- Print count and pagination info.
- Optionally save a JSON report under data/raw/discovery or data/raw/YYYY-MM-DD.
- This can use live network because it is a diagnostic script, but tests must not.

Possible usage:
python scripts/discover_instant_ticket_pages.py
python scripts/discover_instant_ticket_pages.py --from-file path/to/hub.html

scripts/parse_instant_ticket_detail.py

Purpose:
- Parse one saved individual ticket detail HTML file.
- Print parsed metadata.
- Do not fetch network.
- Do not write database.

Possible usage:
python scripts/parse_instant_ticket_detail.py path/to/loteria-2026.html

Output example:
Parsed file: path/to/loteria-2026.html
Name: Loteria™
Slug: loteria-2026
Game Number: 7651
Price Point: 3
Overall Odds: 3.85
Launch Date: 2026-05-05
Category: LP
Play Style: Loteria
Top Prize: $80,000
Image URL: /...
Consolidated Odds Present: yes
Warnings: 0

5. Add tests and fixtures.

Add fixture files under tests/fixtures, for example:
- tests/fixtures/instant_tickets_hub_page_1.html
- tests/fixtures/instant_ticket_detail_loteria_2026.html

Tests for hub discovery:
- Parses at least one detail URL.
- Normalizes relative URLs.
- Deduplicates duplicate card links.
- Ignores footer/menu/promo links.
- Detects pagination text or pagination links if present.
- Preserves ticket card order.
- Extracts ticket_price when visible in the card.
- Does not require live network.

Tests for detail parser:
- Parses game name.
- Parses game number as string.
- Parses price point as int.
- Parses overall odds “1 in 3.85” as Decimal("3.85").
- Preserves odds text.
- Parses launch date.
- Parses category.
- Parses play style.
- Finds ticket image URL if present.
- Detects consolidated odds section.
- Returns warnings rather than crashing when optional fields are missing.
- Accepts both raw HTML string and Path input.

6. Keep database import separate.

Do not add production database writes in this task unless there is already an established import layer and this is trivial. The current task is discovery + raw collection + parsing.

However, design the parsed result so a later import step can upsert into the games table.

Relevant database-oriented mapping for later:
- game_number -> games.game_number
- game_name/display_name -> games fields
- ticket_price -> games.ticket_price
- overall_odds -> games.overall_odds or similar
- launch_date -> games.start_date or launch_date, depending on current schema
- end_date -> not expected from detail page unless present
- estimated_ticket_count -> later computed from overall_odds * sum(total_prizes) from unpaid-prizes parser
- detail_url -> games.source_url/detail_url
- image_url -> optional future UI field

7. Be careful with estimated_ticket_count.

The user recently added:
- games.estimated_ticket_count
- games.end_date

Do not force estimated_ticket_count calculation inside the detail parser. The detail parser only knows odds and game metadata. The unpaid-prizes parser knows total prize counts. A later import/metrics step can combine:

estimated_ticket_count = overall_odds * sum(total_prizes across all prize tiers)

Treat it as an estimate because published odds may be rounded.

8. Relationship to existing unpaid-prizes parser.

Keep these separate:

Unpaid prizes page:
- prize tier availability snapshot
- total prizes
- unclaimed prizes
- weeks in market

Instant ticket detail page:
- stable metadata
- odds
- launch date
- game number
- image
- play style/category

Do not combine these into one parser.

9. Deliverables expected from this task.

Please produce:
- New module(s) for hub discovery and detail parsing.
- CLI diagnostic script(s).
- Fixture-backed tests.
- Any small reusable URL/path helper needed.
- Clear warnings for missing fields.
- No live network in unit tests.
- Existing tests still passing.
- Short notes in docs or comments explaining the new source relationship:
  unpaid-prizes page = prize availability snapshots
  instant-tickets hub/detail pages = stable game metadata

10. Suggested implementation order.

A. Inspect the current repo structure and existing parser/raw_collector conventions.
B. Add fixture for one saved instant-ticket hub page.
C. Implement hub URL discovery parser.
D. Add tests for hub discovery.
E. Add fixture for one saved individual ticket detail page.
F. Implement detail-page parser.
G. Add tests for detail-page parser.
H. Add CLI diagnostics.
I. Run the full test suite.
J. Summarize exactly what was added and any unresolved source-discovery issues.

Be conservative. Prefer small, testable pieces over a large end-to-end scraper.


Success criteria:

The task is successful when all of the following are true:

1. Existing behavior is preserved
- All existing tests pass.
- The existing unpaid-prizes parser still works.
- Existing raw snapshot collection for the unpaid-prizes page is not broken.
- No UI work is introduced.

2. Hub discovery works from a fixture
- A saved `/games-hub/instant-tickets` HTML fixture can be parsed without network access.
- The parser discovers individual ticket detail URLs such as `/games-hub/instant-tickets/<slug>`.
- Relative URLs are normalized to absolute Illinois Lottery URLs.
- Duplicate ticket URLs are removed.
- Non-ticket links from headers, footers, promos, app links, store locator links, and menu navigation are ignored.
- The discovery result includes useful warnings instead of crashing if expected elements are missing.

3. Hub pagination is addressed
- The code either:
  a) discovers pagination URLs / controls needed to collect all ticket cards, or
  b) proves through parsed HTML that all ticket cards are embedded in the initial hub response.
- The implementation does not silently assume the first 20 visible cards are all games.
- The diagnostic output clearly reports the number of ticket detail URLs discovered and any detected total count, such as “1 - 20 of 58.”

4. Detail-page parser works from a fixture
- A saved individual instant-ticket detail HTML fixture can be parsed without network access.
- The parser extracts, when present:
  - game name / display name
  - game number
  - ticket price / price point
  - overall odds
  - original odds text
  - launch date
  - category
  - play style
  - top prize text
  - ticket image URL
  - whether a consolidated odds section exists
- Missing optional fields return `None` and warnings, not exceptions.

5. Type handling is correct
- `game_number` remains a string.
- ticket price is parsed as an integer number of dollars.
- odds text like `1 in 3.85` is parsed into `Decimal("3.85")`.
- launch date text like `May 5, 2026` is parsed into a `date`.
- URLs are normalized consistently.

6. Raw source preservation remains central
- Hub HTML can be saved as a raw source file.
- Detail page HTML can be saved as raw source files.
- Files are written under dated raw directories or an existing project-approved raw-data convention.
- Raw files are not overwritten.
- Tests do not depend on live network access.

7. Parser/database separation is preserved
- New parser functions do not write to the database.
- CLI parse diagnostics do not write to the database.
- Parsed objects are shaped so a later import step can upsert into the `games` table.
- The implementation does not prematurely compute `estimated_ticket_count` inside the detail parser.

8. CLI diagnostics are usable
- There is a command to parse or discover ticket detail URLs from a saved hub HTML file.
- There is a command to parse a saved individual ticket detail HTML file.
- Diagnostic output clearly shows what was found, including counts, key fields, and warnings.

9. Tests are meaningful
- New unit tests cover hub discovery.
- New unit tests cover detail-page parsing.
- New tests use fixtures and/or small inline HTML snippets.
- No test launches Playwright or hits the live Illinois Lottery site.
- Tests include at least one negative/missing-field case.

10. Documentation / notes are clear
- The code or docs explain the source split:
  - unpaid-prizes page = prize-tier availability snapshots
  - instant-tickets hub/detail pages = stable game metadata
- Any unresolved issue is explicitly documented, especially if pagination or detail URL discovery is not fully solved.