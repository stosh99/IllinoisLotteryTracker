import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Outlet, Route, Routes } from "react-router-dom";

import { AuthResultNotice } from "./components/AuthResultNotice";
import { BrandMark } from "./components/BrandMark";
import { DataStatus } from "./components/DataStatus";
import { EvidenceGuide, EvidenceTag } from "./components/EvidenceGuide";
import { LeaderCards } from "./components/LeaderCards";
import { RankingFilters } from "./components/RankingFilters";
import { RankingsTable } from "./components/RankingsTable";
import { SignInControl } from "./components/SignInControl";
import { StrategyPicker } from "./components/StrategyPicker";
import { UnavailableState } from "./components/UnavailableState";
import { AuthSessionProvider } from "./context/AuthSessionProvider";
import { useRankingViewState } from "./hooks/useRankingViewState";
import { getStrategy } from "./lib/strategies";
import { DEFAULT_VIEW_STATE } from "./lib/urlState";
import { AccountPage } from "./pages/AccountPage";
import { GameDetailPage } from "./pages/GameDetailPage";
import { loadRankingDataset } from "./services/rankings";
import type { GameDetail } from "./types/gameDetails";
import type { GameHistory } from "./types/gameHistory";
import type { RankingDataset, RankingRecord } from "./types/rankings";

interface AppProps {
  datasetOverride?: RankingDataset;
  gameDetailOverride?: GameDetail;
  gameHistoryOverride?: GameHistory;
}

const RANKING_PAGE_SIZE = 12;

export default function App({ datasetOverride, gameDetailOverride, gameHistoryOverride }: AppProps) {
  return (
    <BrowserRouter>
      <AuthSessionProvider>
        <Routes>
          <Route element={<SiteLayout />}>
            <Route index element={<RankingPage datasetOverride={datasetOverride} />} />
            <Route
              path="games/:gameId"
              element={
                <GameDetailPage
                  detailOverride={gameDetailOverride}
                  historyOverride={gameHistoryOverride}
                />
              }
            />
            <Route path="account" element={<AccountPage />} />
          </Route>
        </Routes>
      </AuthSessionProvider>
    </BrowserRouter>
  );
}

function SiteLayout() {
  return (
    <div className="site-shell">
      <SiteHeader />
      <AuthResultNotice />
      <Outlet />
      <SiteFooter />
    </div>
  );
}

function RankingPage({ datasetOverride }: AppProps) {
  const [dataset, setDataset] = useState<RankingDataset | null>(datasetOverride ?? null);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    if (datasetOverride) {
      setDataset(datasetOverride);
      return;
    }
    const controller = new AbortController();
    setError(null);
    loadRankingDataset(controller.signal)
      .then(setDataset)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Ranking data failed to load.");
        }
      });
    return () => controller.abort();
  }, [datasetOverride, requestVersion]);

  return (
    <main id="main-content">
      <Hero />
      <CaveatStrip />
      {dataset ? <DataStatus dataset={dataset} /> : null}
      {error ? (
        <section className="load-state" aria-live="polite">
          <p className="eyebrow">DATA CONNECTION</p>
          <h2>We could not load the comparison.</h2>
          <p>{error}</p>
          <button className="button" onClick={() => setRequestVersion((value) => value + 1)}>
            Try again
          </button>
        </section>
      ) : dataset ? (
        <RankingExperience dataset={dataset} />
      ) : (
        <section className="load-state" aria-live="polite">
          <span className="loading-line" />
          <p>Loading the comparison…</p>
        </section>
      )}
      <Methodology />
    </main>
  );
}

function RankingExperience({ dataset }: { dataset: RankingDataset }) {
  const [viewState, updateViewState] = useRankingViewState();
  const [visibleRowCount, setVisibleRowCount] = useState(RANKING_PAGE_SIZE);
  const strategy = getStrategy(viewState.strategy);
  const strategyRows = useMemo(
    () => dataset.rankings.filter((row) => row.strategyKey === viewState.strategy),
    [dataset.rankings, viewState.strategy],
  );
  const prices = useMemo(
    () => [...new Set(strategyRows.map((row) => row.ticketPrice))].sort((a, b) => a - b),
    [strategyRows],
  );
  const filtered = useMemo(
    () =>
      strategyRows
        .filter(
          (row) => viewState.ticketPrice === "all" || row.ticketPrice === viewState.ticketPrice,
        )
        .sort((left, right) => left.rankOverall - right.rankOverall),
    [strategyRows, viewState.ticketPrice],
  );
  const maxMetric = Math.max(...filtered.map((row) => row.metricValue), 0);
  const visibleRows = filtered.slice(0, visibleRowCount);
  const hiddenRowCount = filtered.length - visibleRows.length;

  useEffect(() => {
    setVisibleRowCount(RANKING_PAGE_SIZE);
  }, [viewState.strategy, viewState.ticketPrice]);

  return (
    <>
      <section className="comparison-controls" id="rankings" aria-labelledby="comparison-title">
        <div className="section-heading">
          <p className="eyebrow">CHOOSE YOUR QUESTION</p>
          <h2 id="comparison-title">There is no universal “best” ticket.</h2>
          <p>Start with the outcome you care about, then compare like with like.</p>
        </div>
        <StrategyPicker
          selected={viewState.strategy}
          onSelect={(selected) => updateViewState({ strategy: selected })}
        />
      </section>

      <section className="ranking-section" aria-labelledby="ranking-insight-title">
        <div className="ranking-section__heading">
          <div>
            <p className="eyebrow">CURRENT VIEW</p>
            <h2 id="ranking-insight-title">{strategy.question}</h2>
            <p>{strategy.explanation}</p>
          </div>
        </div>

        <RankingFilters
          prices={prices}
          ticketPrice={viewState.ticketPrice}
          onTicketPriceChange={(ticketPrice) => updateViewState({ ticketPrice })}
        />

        {!dataset.status.available ? (
          <UnavailableState reasonCode={dataset.status.reasonCode} />
        ) : filtered.length === 0 ? (
          <UnavailableState
            reasonCode="AVAILABLE"
            onReset={() => updateViewState(DEFAULT_VIEW_STATE)}
          />
        ) : (
          <>
            <LeaderCards
              rankings={filtered}
              maxMetric={maxMetric}
              filteredByPrice={viewState.ticketPrice !== "all"}
            />
            <div className="all-rankings-heading">
              <div>
                <p className="eyebrow">FULL COMPARISON</p>
                <h3>Complete results in this view</h3>
              </div>
              <p>
                Values stay visible without hover. Rank ties share the same number.
              </p>
            </div>
            <RankingsTable
              rankings={visibleRows}
              maxMetric={maxMetric}
              filteredByPrice={viewState.ticketPrice !== "all"}
            />
            <div className="ranking-progress" aria-live="polite">
              <p>
                Showing {visibleRows.length} of {filtered.length} complete{" "}
                {filtered.length === 1 ? "result" : "results"}.
              </p>
              {hiddenRowCount > 0 ? (
                <button
                  aria-controls="all-rankings-table"
                  className="button button--outline"
                  onClick={() =>
                    setVisibleRowCount((current) =>
                      Math.min(current + RANKING_PAGE_SIZE, filtered.length),
                    )
                  }
                  type="button"
                >
                  Show next {Math.min(RANKING_PAGE_SIZE, hiddenRowCount)}
                </button>
              ) : null}
            </div>
          </>
        )}
      </section>
    </>
  );
}

function SiteHeader() {
  return (
    <header className="site-header">
      <a className="brand" href="/" aria-label="Illinois Lottery Tracker home">
        <BrandMark />
        <span>
          <strong>Illinois</strong>
          <small>Lottery Tracker</small>
        </span>
      </a>
      <nav aria-label="Primary navigation">
        <a href="/#rankings">Compare games</a>
        <a href="/#methodology">Methodology</a>
        <a href="/#data-status">Data status</a>
      </nav>
      <SignInControl />
    </header>
  );
}

function Hero() {
  return (
    <section className="hero" id="top">
      <div className="hero__copy">
        <p className="eyebrow">ILLINOIS INSTANT TICKETS · PUBLIC DATA</p>
        <h1>
          Compare the prize pool.
          <span>Keep the caveats.</span>
        </h1>
        <p className="hero__lede">
          A clearer way to compare current instant-ticket games by estimated value,
          money-back chance, moderate upside, or jackpot odds—without pretending any
          ticket is a sure thing.
        </p>
        <div className="hero__actions">
          <a className="button" href="#rankings">Explore the comparison</a>
          <a className="text-link" href="#methodology">See how the estimates work →</a>
        </div>
      </div>
      <aside className="hero-card" aria-label="What this site promises">
        <p className="hero-card__kicker">THE PRODUCT PROMISE</p>
        <blockquote>
          “Make public lottery data easier to understand—never promise a winning ticket.”
        </blockquote>
        <ul>
          <li><span aria-hidden="true">01</span> One transparent metric per ranking</li>
          <li><span aria-hidden="true">02</span> Source date and estimate type always visible</li>
          <li><span aria-hidden="true">03</span> Partial or stale results never ranked</li>
        </ul>
      </aside>
    </section>
  );
}

function CaveatStrip() {
  return (
    <aside className="caveat-strip" aria-label="Important estimate caveat">
      <strong>Read this first</strong>
      <p>
        Estimates describe game-wide averages—not the next ticket. Official unclaimed
        counts can include sold winners that have not yet been processed as claimed.
      </p>
      <a href="#methodology">How estimates work</a>
    </aside>
  );
}

function Methodology() {
  return (
    <section className="methodology" id="methodology" aria-labelledby="methodology-title">
      <div className="section-heading section-heading--light">
        <p className="eyebrow">HOW TO READ THE ESTIMATES</p>
        <h2 id="methodology-title">Know which numbers are reported—and which are estimated.</h2>
        <p>
          Illinois publishes prize counts and overall game odds, but not the number of
          tickets still for sale. This site keeps those reported facts visible and
          labels every additional calculation.
        </p>
      </div>
      <EvidenceGuide />
      <ol className="methodology__steps">
        <li>
          <span>01</span>
          <h3>Start with the report</h3>
          <p>
            Starting prizes, reported unclaimed prizes, and published overall odds
            come from the Illinois Lottery source.
          </p>
        </li>
        <li>
          <span>02</span>
          <h3>Calculate what is known</h3>
          <p>
            Claimed prizes are starting prizes minus reported unclaimed prizes. That
            subtraction is exact for the published snapshot.
          </p>
        </li>
        <li>
          <span>03</span>
          <h3>Estimate current supply</h3>
          <p>
            Current ticket supply, current chances, and prize return are estimates
            because the lottery does not publish a live count of unsold tickets.
          </p>
        </li>
        <li>
          <span>04</span>
          <h3>Account for claim delay</h3>
          <p>
            A 24-day working assumption applies only to prizes over $600 with at
            least 300 starting prizes. Other tiers keep the official reported count.
          </p>
        </li>
      </ol>
      <article className="worked-example" aria-labelledby="worked-example-title">
        <div>
          <p className="eyebrow">WORKED EXAMPLE</p>
          <h3 id="worked-example-title">What does “$7.42 return” mean on a $10 game?</h3>
        </div>
        <div className="worked-example__math">
          <strong>$7.42 ÷ $10 = about 74¢ per $1</strong>
          <p>
            This is a long-run average across the game-wide prize pool. It does not
            mean one $10 ticket is likely to pay $7.42; that ticket can lose the full
            $10 or win one of the listed prizes.
          </p>
        </div>
        <div className="worked-example__tier">
          <p>
            If a $1,000 tier began with 400 prizes and the official report lists 150
            unclaimed, then <strong>250 claimed</strong> is calculated exactly.
          </p>
          <p>
            Because that tier is over $600 and began with at least 300 prizes, the
            page may also show a <EvidenceTag kind="adjusted" /> such as 143.5. The
            official 150 remains visible beside it.
          </p>
        </div>
      </article>
      <details className="methodology-glossary">
        <summary>Open the plain-language glossary</summary>
        <dl>
          <div>
            <dt>Estimated prize return</dt>
            <dd>Long-run average prize value represented by the current game-wide prize pool. It is not net profit or a prediction for one ticket.</dd>
          </div>
          <div>
            <dt>Estimated chance now</dt>
            <dd>A chance calculated from current prize counts and estimated current ticket supply.</dd>
          </div>
          <div>
            <dt>Reported unclaimed</dt>
            <dd>The official source count. A sold winning ticket can remain in this count until its claim is processed.</dd>
          </div>
          <div>
            <dt>Small prize sample</dt>
            <dd>A tier with too few prizes for stable adjustment. The official count remains visible; the game is not removed.</dd>
          </div>
        </dl>
      </details>
      <div className="methodology__note">
        <strong>Lottery play still has negative expected value.</strong>
        <p>
          This tool compares public data. It does not predict where a winning ticket
          is, guarantee an outcome, or turn lottery play into an investment.
        </p>
      </div>
    </section>
  );
}

function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="brand brand--footer">
        <BrandMark />
        <span>
          <strong>Illinois</strong>
          <small>Lottery Tracker</small>
        </span>
      </div>
      <p>Independent analysis of public Illinois Lottery data.</p>
      <p>Independent tool · not affiliated with the Illinois Lottery.</p>
    </footer>
  );
}

export function visibleGameIds(rows: RankingRecord[]): number[] {
  return rows.map((row) => row.gameId);
}
