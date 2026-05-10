# IllinoisLotteryTracker — Overall Website Strategy

## Core Product Idea

IllinoisLotteryTracker should help users understand Illinois instant-ticket games using public prize-availability data.

The website should not promise that users can beat the lottery or find guaranteed winners. A better framing is:

> Lottery games are negative expected value overall, but some games may be meaningfully better or worse than others at a given point in time based on remaining prize data.

The core user question is:

> Given the tickets currently available, which games are least bad, most interesting, or best aligned with the kind of player I am?

The site should help users compare games by strategy, not just show one universal “best ticket.”

---

## Important Caveats

These caveats should be visible throughout the site, not hidden only in a footer.

- All values are estimates based on public Illinois Lottery data.
- Unclaimed prizes are not the same as unsold tickets.
- Large prizes may have claim-reporting delays.
- Any prize requiring submission to the lottery board may appear as unclaimed even after a winning ticket has been sold.
- Lottery games remain negative expected value overall.
- The site is for analysis and transparency, not gambling advice or outcome prediction.

Suggested short caveat language:

> Estimated values are based on public unclaimed-prize data. Unclaimed prizes may not equal unsold tickets, and large claims may lag.

---

## Main User Questions

Users may arrive with different versions of the question:

> Which ticket should I buy?

But underneath that, users may really be asking different things.

### 1. Which games have the best estimated value?

This is the pure expected-value question.

These users want to know:

> For every dollar I spend, how much prize value appears to remain?

Useful rankings:

- Best estimated EV
- Best estimated payout ratio
- Lowest estimated house edge
- Best EV by ticket price
- Best EV among $1, $2, $5, $10, $20, $30, and $50 games

This is likely the site’s core analytical ranking.

---

### 2. Which games are best if I ignore the giant prizes?

A game can appear attractive because it still has one very large prize. But that prize may be extremely unlikely, and it may distort the practical value of the ticket.

The site should offer several EV views:

- Full estimated EV
- EV excluding the top prize
- EV excluding the top 3 prizes
- EV excluding prizes above $100,000
- EV excluding prizes above $600

The `$600+` threshold is especially useful because larger prizes may require claim processing and may not be reflected immediately in public unclaimed-prize data.

This supports a practical question:

> How good is this ticket if I mostly care about prizes that are not huge, rare, or subject to claim-delay risk?

---

### 3. Which games are best for getting my money back?

This user is not primarily chasing a jackpot. They want frequent smaller wins or break-even outcomes.

They care about:

- Chance of any win
- Chance of break-even or better
- Chance of 2x ticket price or better
- Chance of 5x ticket price or better
- Small-prize density
- Break-even prize density

Possible website section:

> Best for Getting Your Money Back

This should identify games with strong small-prize or break-even profiles, even if they do not have the best top-prize upside.

---

### 4. Which games are best for moderate upside?

This user wants a meaningful win, but not necessarily the jackpot.

They may care about:

- $50 wins on $5 tickets
- $100 wins on $10 tickets
- $500 wins on $20 tickets
- $1,000 wins on $20 or $30 tickets
- 5x, 10x, or 20x ticket-price outcomes

Useful rankings:

- Best chance at 5x+
- Best chance at 10x+
- Best mid-tier prize value
- Best $100–$1,000 prize density
- Best non-jackpot upside
- Best EV excluding top prizes

This may become one of the most useful site sections because many lottery players want a “nice hit,” not only a jackpot.

---

### 5. Which games are best for chasing the big prize?

This is the jackpot-focused user.

They care about:

- Top prize amount
- Top prizes originally available
- Top prizes remaining
- Percentage of top prizes remaining
- Whether all top prizes are gone
- How old or depleted the game is
- Full estimated EV including top prizes

Possible labels:

- Top Prize Still Available
- Top Prize Depleted
- Only 1 Top Prize Left
- All Top Prizes Remaining
- Jackpot-Heavy Game

For this user, full EV and top-prize availability matter more than practical EV excluding large prizes.

---

### 6. Which games should I avoid?

Some users may not want the mathematically best game. They may simply want to avoid games that look depleted or misleading.

Useful warnings:

- Top prize gone
- Low remaining prize value
- Old game with depleted prize pool
- Estimated EV far below launch EV
- Missing detail metadata
- Large-prize-heavy EV
- Recent unusual prize-structure change

Possible section:

> Games to Be Careful With

This would help casual users avoid obviously weak or uncertain games.

---

## Player Style Framework

The site should not present a single universal “best game.” It should help users find games that match their playing style.

### 1. Money-Back Player

This player wants frequent smaller wins and cares about staying in the game.

Prioritize:

- Chance of any win
- Chance of break-even or better
- Small-prize density
- Lowest volatility
- EV excluding top prizes

Plain-English explanation:

> You care more about staying in the game than chasing a huge prize.

---

### 2. Steady Value Player

This player wants the best overall math.

Prioritize:

- Estimated payout ratio
- Estimated EV per dollar
- Lowest house edge
- EV excluding top prize
- EV excluding top 3 prizes

Plain-English explanation:

> You want the ticket that appears least unfavorable based on remaining prizes.

---

### 3. Moderate Upside Player

This player wants a realistic but meaningful hit.

Prioritize:

- Chance of 5x+
- Chance of 10x+
- Remaining $100–$1,000 prize density
- Mid-tier prize value
- EV excluding top prize

Plain-English explanation:

> You are looking for a realistic but meaningful win, not only a jackpot chase.

---

### 4. Jackpot Hunter

This player is comfortable with long odds if the biggest prizes are still available.

Prioritize:

- Top prize amount
- Top prizes remaining
- Top prize remaining percentage
- Full estimated EV
- Top-heavy score

Plain-English explanation:

> You are comfortable with long odds if the biggest prizes are still alive.

---

### 5. Avoid-Bad-Games Player

This player wants to avoid tickets that look depleted or uncertain.

Prioritize warnings:

- Top prize gone
- Weak EV excluding top prizes
- Low remaining prize value percentage
- Missing metadata
- Recently disappeared from the unpaid-prizes page
- Claim-lag exposure

Plain-English explanation:

> You mainly want to avoid games where the public data suggests the prize pool has become unattractive.

---

## Suggested Website Sections

Eventually, the website could include these main areas:

1. Home
2. Best Games
3. Player Styles
4. All Games
5. Game Detail
6. Daily Changes
7. Methodology
8. Data Quality

---

## Home Page Strategy

The home page should provide quick, opinionated answers.

Suggested sections:

- Best Overall Estimated Value
- Best Value Excluding Top Prizes
- Best Value Excluding Prizes Over $600
- Best for Getting Your Money Back
- Best for Moderate Upside
- Best Jackpot Chases
- Recently Added Games
- Recently Removed or Missing Games
- Games to Be Careful With

The home page should not begin as a giant table. It should guide users toward the most useful views.

---

## Best Games Page

This page should rank games by user objective.

Suggested rankings:

- Best Overall Estimated Value
- Best Estimated Payout Ratio
- Best EV Excluding Top Prize
- Best EV Excluding Top 3 Prizes
- Best EV Excluding Prizes Over $600
- Best Break-Even / Money-Back Games
- Best Moderate Upside Games
- Best Jackpot Chase Games
- Best by Ticket Price

Ticket-price groupings are important because many users shop within a fixed price tier.

Examples:

- Best $1 tickets
- Best $2 tickets
- Best $5 tickets
- Best $10 tickets
- Best $20 tickets
- Best $30 tickets
- Best $50 tickets

---

## All Games Page

This should be the power-user sortable/filterable table.

Suggested columns:

- Game name
- Game number
- Ticket price
- Overall odds
- Top prize
- Top prizes remaining
- Estimated EV
- Estimated payout ratio
- Estimated house edge
- EV excluding top prize
- EV excluding top 3 prizes
- EV excluding prizes over $600
- Estimated remaining tickets
- Remaining prize value percentage
- Remaining winning tickets percentage
- Weeks in market
- Last updated
- Metadata status

Suggested filters:

- Ticket price
- Top prize still available
- Minimum estimated payout ratio
- Exclude games with missing metadata
- Only games with all top prizes remaining
- Only games above launch EV
- Only games with strong mid-tier prizes
- Only games with lower claim-lag exposure

Suggested sorts:

- Best estimated EV
- Best payout ratio
- Best EV excluding top prize
- Best EV excluding prizes over $600
- Best chance of any win
- Best chance of break-even or better
- Best chance of 10x+
- Most depleted
- Newest games
- Top prize remaining percentage

---

## Game Detail Page

The game detail page should explain one ticket deeply and build trust.

Suggested sections:

- Overview
- Prize table
- Remaining prize trends
- EV trend
- Top prize status
- Small/mid/large prize breakdown
- Claim-delay caution
- Raw source history
- Data quality notes

The detail page should show:

- Original prizes
- Remaining prizes
- Claimed prizes
- Remaining percentage
- Estimated remaining tickets
- Estimated EV
- EV excluding top prize
- EV excluding top 3 prizes
- EV excluding prizes over $600
- Top prize remaining percentage
- Prize value remaining percentage

Suggested charts:

- Remaining prize value over time
- Estimated EV over time
- Top prize count over time
- Remaining winning tickets over time
- Prize-tier depletion over time

---

## Player Style Page

This page should help users who do not know how to interpret EV.

Possible questions:

- Are you mostly trying to get your money back?
- Are you chasing a big prize?
- Do you prefer frequent smaller wins?
- Do you care about avoiding games where top prizes are gone?
- What ticket price do you usually buy?
- Are you comfortable with long-shot prizes driving most of the value?

Then classify the user into a style:

- Money-Back Player
- Steady Value Player
- Moderate Upside Player
- Jackpot Hunter
- Avoid-Bad-Games Player

Example result:

> You look like a Moderate Upside Player. Here are the current games that appear best aligned with that style.

This could become one of the site’s most distinctive features.

---

## Daily Changes Page

This page should use the historical snapshot pipeline.

Suggested sections:

- New games
- Games missing from latest snapshot
- Prize structure changes
- Top prize count changes
- Games whose estimated EV improved
- Games whose estimated EV worsened
- Games with suspicious data changes
- Games newly missing detail metadata
- Games still missing detail metadata

Important wording:

- Do not say a game “ended” after one missing snapshot.
- Say “missing from latest unpaid-prizes snapshot” or “removed from latest source capture.”
- Do not say tickets were definitely printed.
- Say “original prize structure changed” or “estimated ticket pool changed.”

This page proves the site is tracking history, not just showing a static scrape.

---

## Methodology Page

This page is crucial for trust.

It should explain:

- Data sources
- Raw HTML preservation
- What unpaid prizes mean
- Why unclaimed prizes are not the same as unsold tickets
- How estimated total tickets are calculated
- How estimated remaining tickets are calculated
- How estimated EV is calculated
- How EV excluding top prizes is calculated
- Why large-prize claim delays matter
- Why missing metadata causes null metrics
- Why estimates should not be treated as guarantees

Suggested tone:

> This site makes public lottery data easier to analyze. It does not predict winning tickets or guarantee outcomes.

---

## Data Quality Page

This page should make the site more credible.

Show:

- Last successful unpaid-prizes capture
- Last successful detail metadata capture
- Number of games with complete metadata
- Number of games missing odds
- Known metadata gaps
- Failed captures
- Cloudflare or validation failures
- Duplicate capture skips
- Source anomalies
- Prize structure changes

Known current example:

- `$250,000 CROSSWORD`, game number `7587`, is active in unpaid-prizes data but has no current detail page found. Odds-dependent metrics remain null intentionally.

This page is not glamorous, but it supports trust.

---

## Claim-Delay Strategy

Prizes over a certain amount may require submission to the lottery board rather than being paid instantly by a local retailer. This creates a possible delay between:

1. A ticket being sold and winning
2. The winner submitting the claim
3. The lottery updating the unclaimed-prize table

This matters because a large prize may still appear unclaimed even after the winning ticket has already been sold.

The site should communicate this clearly.

Possible concept:

> Claim Lag Risk

Suggested labels:

- Lower claim-lag exposure
- Moderate claim-lag exposure
- High claim-lag exposure

Factors that increase claim-lag exposure:

- EV heavily dependent on prizes over $600
- EV heavily dependent on top prizes
- Few large prizes remaining
- Recent game with high-value prizes
- Large difference between full EV and EV excluding large prizes

Practical implication:

- Full estimated EV may be optimistic when large prizes are still listed but not yet processed as claimed.
- EV excluding prizes over $600 may be a useful conservative comparison.
- EV excluding top prizes may be more stable for practical users.

---

## EV Decomposition

Instead of showing only one EV number, the site should eventually show where EV comes from.

Example:

```text
Ticket price: $10
Estimated EV: $7.49

Break-even prizes: $1.20
Small profit prizes: $1.80
Moderate prizes: $2.10
Large prizes: $1.15
Top prize contribution: $1.24