
---

# File 2: `docs/next-claude-prompt-parser.md`

Copy everything below into `docs/next-claude-prompt-parser.md`:

```md
# Next Claude Code Prompt — Rendered HTML Parser

Paste the following prompt into Claude Code from inside the `IllinoisLotteryTracker` project folder.

---

You are working in the IllinoisLotteryTracker project.

Project context:
IllinoisLotteryTracker is a Python-first data pipeline project that tracks Illinois Lottery instant ticket prize availability over time. The current priority is reliable raw data collection and parsing. Do not build a UI yet.

Current status:
- PostgreSQL connection is working.
- Initial SQLAlchemy models exist.
- Raw collector exists.
- Raw collector tries requests first and falls back to Playwright on 403.
- Source discovery has been run.
- Discovery saved rendered HTML files and network files.
- Network files appear to contain mostly analytics, tracking, ads, SVG/logo assets, images, CSRF/session files, and the page HTML itself.
- We did not find a clean JSON/API endpoint containing the unclaimed instant-ticket prize data.
- Therefore, proceed with a rendered-HTML parser.

Important source files:
- data/raw/discovery/rendered-initial.html
- data/raw/discovery/rendered-filter-*.html
- data/raw/discovery/network/020-about-the-games_unpaid-instant-games-prizes.html

Important HTML findings:
- The Illinois Lottery unclaimed prizes page appears to include the prize table directly in rendered HTML.
- Rows use selectors/classes like:
  - tr.unclaimed-prizes-table__row
  - td.unclaimed-prizes-table__cell
- Rows include data-price attributes such as:
  - data-price="5"
- Some rows are hidden with:
  - style="display: none;"
- Some rows are visible with:
  - unclaimed-prizes-table__row--filtered
- Do not rely on row visibility.
- Do not rely on active filter state.
- Do not rely on pagination.
- Parse all table rows in the DOM.

Goal:
Create a parser for saved rendered HTML files.

Implement:

## 1. Parser module

Create:

```text
src/illinois_lottery_tracker/parser.py

The parser should:

Accept raw HTML text or a Path to an HTML file.
Use BeautifulSoup/lxml.
Parse all rows matching:
tr.unclaimed-prizes-table__row

For each row, extract:

game_name
Example: MONEY RUSH
display_name
Example: MONEY RUSH ($5)
ticket_price
From the visible price cell and/or data-price
data_price
From row attribute data-price
game_number
weeks_in_market
From the parentheses under/near the game number, if present
prize_tiers, as a list of objects with:
prize_amount
total_prizes
unclaimed_prizes

Prize-tier details:

Prize amounts, total prize counts, and unclaimed prize counts appear as parallel <br>-separated values across cells.
The parser must align those parallel values by index.
Validate that the number of prize amounts, total prize counts, and unclaimed prize counts match for each game.
If they do not match, preserve a parse warning.
Do not silently discard malformed rows.
2. Return types

Create dataclasses or typed structures for:

ParsedPrizeTier
ParsedGame
ParseWarning
ParseResult

Suggested fields:

ParsedPrizeTier
- prize_amount
- total_prizes
- unclaimed_prizes

ParsedGame
- game_name
- display_name
- ticket_price
- data_price
- game_number
- weeks_in_market
- prize_tiers

ParseWarning
- message
- row_index
- game_name optional
- raw_text optional

ParseResult
- games
- warnings

Use Python dataclasses unless there is already a project convention suggesting otherwise.

3. Parsing rules

Implement robust helper functions for:

Cleaning whitespace
Splitting <br>-separated cell values
Parsing currency values:
$5
$10
$1,000
$1,000,000
Parsing integer counts:
1
10
1,000
12,345
Extracting game number and weeks in market from the game-number cell
Extracting ticket price from either:
row data-price
visible price text
display name suffix like ($5)

The parser should preserve warnings rather than silently dropping bad rows.

For money/count storage:

It is acceptable for this milestone to parse dollar amounts as integer dollars.
It is acceptable for counts to be integers.
If a value cannot be parsed, add a warning.
4. Output behavior

For this milestone, the parser should only return structured parsed data.

Do not write parsed data to the database yet.

Do not update existing SQLAlchemy models yet unless absolutely necessary.

Do not calculate EV.

Do not build UI.

Do not scrape the live site as part of tests.

Do not change the raw collector unless necessary.

5. Tests

Add:

tests/test_parser.py

Use small inline HTML fixtures first. Do not rely only on the large saved real HTML file.

Tests should cover:

Parsing one normal game row
Parsing multiple prize tiers from parallel <br>-separated columns
Parsing currency amounts with commas
Parsing counts with commas
Extracting data-price
Extracting ticket price
Extracting game number
Extracting weeks in market
Warning when prize amount / total prize / unclaimed prize list lengths do not match
Ignoring non-game rows
Parsing hidden rows as well as visible rows
Returning a ParseResult with both games and warnings

Tests should not require internet access.

If convenient, add one integration-style test using a tiny saved fixture file under tests/fixtures/, but keep it small.

6. CLI script

Add:

scripts/parse_saved_html.py

The script should:

Accept a file path argument
Parse that saved HTML file
Print:
number of games parsed
number of prize tiers parsed
distinct ticket prices found
first 5 parsed games as a sanity check
warning count
first few warnings, if any

Example usage:

python scripts/parse_saved_html.py data/raw/discovery/rendered-initial.html

Expected output should be human-readable and concise.

Example format:

Parsed file: data/raw/discovery/rendered-initial.html
Games parsed: 58
Prize tiers parsed: 712
Ticket prices found: [1, 2, 3, 5, 10, 20, 30, 50]
Warnings: 0

First 5 games:
- 1234 MONEY RUSH ($5): 10 prize tiers
- ...

Exact counts are not known yet. Do not hardcode the counts.

7. Validation

Run:

pytest
ruff check .

If the real discovery HTML file exists locally, also run:

python scripts/parse_saved_html.py data/raw/discovery/rendered-initial.html

If rendered-initial.html is missing, say so and run only tests/ruff.

8. Report back

When finished, report:

Files created/changed
Commands run
Whether tests passed
Whether ruff passed
Whether the parser worked against rendered-initial.html
Number of games parsed from the real fixture, if available
Number of prize tiers parsed from the real fixture, if available
Distinct ticket prices found
Warning count
Assumptions
Recommended next step

Important:
Keep this as a parser milestone only. Do not build the importer, EV math, scheduler, or UI yet.