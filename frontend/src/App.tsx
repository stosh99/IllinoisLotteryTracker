import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Outlet, Route, Routes } from "react-router-dom";

import { AuthResultNotice } from "./components/AuthResultNotice";
import { BrandMark } from "./components/BrandMark";
import { DataStatus } from "./components/DataStatus";
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

const LEADER_COUNT = 3;
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
  const leaders = filtered.slice(0, LEADER_COUNT);
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
          <div className="result-count" aria-live="polite">
            <strong>{filtered.length}</strong>
            <span>{filtered.length === 1 ? "game" : "games"} in view</span>
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
              rankings={leaders}
              maxMetric={maxMetric}
              filteredByPrice={viewState.ticketPrice !== "all"}
              totalRankings={filtered.length}
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
          <a className="text-link" href="#methodology">See how the model works →</a>
        </div>
      </div>
      <aside className="hero-card" aria-label="What this site promises">
        <p className="hero-card__kicker">THE PRODUCT PROMISE</p>
        <blockquote>
          “Make public lottery data easier to understand—never promise a winning ticket.”
        </blockquote>
        <ul>
          <li><span aria-hidden="true">01</span> One transparent metric per ranking</li>
          <li><span aria-hidden="true">02</span> Source and model cutoff always visible</li>
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
        Estimated values use public unclaimed-prize data. Unclaimed prizes may not
        equal unsold tickets, and large claims may be reported later.
      </p>
      <a href="#methodology">Why that matters</a>
    </aside>
  );
}

function Methodology() {
  return (
    <section className="methodology" id="methodology" aria-labelledby="methodology-title">
      <div className="section-heading section-heading--light">
        <p className="eyebrow">BUILT FOR AUDITABILITY</p>
        <h2 id="methodology-title">An estimate should show its work.</h2>
        <p>
          The frontend is designed around the database’s cutoff-strict publication
          contract, not around a permanently available leaderboard.
        </p>
      </div>
      <ol className="methodology__steps">
        <li>
          <span>01</span>
          <h3>Observe</h3>
          <p>Preserve official source captures and reported prize counts without rewriting history.</p>
        </li>
        <li>
          <span>02</span>
          <h3>Estimate</h3>
          <p>Score each prize tier against an independent progress reference, with explicit uncertainty.</p>
        </li>
        <li>
          <span>03</span>
          <h3>Qualify</h3>
          <p>Publish comparisons only when source, catalog, analytics, coverage, and freshness align.</p>
        </li>
      </ol>
      <div className="methodology__note">
        <strong>Still negative expected value.</strong>
        <p>
          This tool compares public data. It does not predict where a winning ticket is,
          guarantee an outcome, or turn lottery play into an investment.
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
