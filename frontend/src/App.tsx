import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { BrowserRouter, Link, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { AuthResultNotice } from "./components/AuthResultNotice";
import { BrandMark } from "./components/BrandMark";
import { EvidenceGuide, EvidenceTag } from "./components/EvidenceGuide";
import { HeaderDataStamp } from "./components/HeaderDataStamp";
import { LeaderCards } from "./components/LeaderCards";
import {
  hasCurrentSiteNoticeAcknowledgment,
  persistSiteNoticeAcknowledgment,
  SiteNoticeDialog,
  type SiteNoticeMode,
} from "./components/SiteNoticeDialog";
import { RankingFilters } from "./components/RankingFilters";
import { RankingsTable } from "./components/RankingsTable";
import { ShareLinkButton } from "./components/ShareLinkButton";
import { SignInControl } from "./components/SignInControl";
import { StrategyPicker } from "./components/StrategyPicker";
import { TicketFinder } from "./components/TicketFinder";
import { UnavailableState } from "./components/UnavailableState";
import { AuthSessionProvider } from "./context/AuthSessionProvider";
import { SiteDataProvider, useSiteData } from "./context/SiteDataProvider";
import { useAuthSession } from "./hooks/useAuthSession";
import { useRankingViewState } from "./hooks/useRankingViewState";
import { getStrategy } from "./lib/strategies";
import { comparisonHref, DEFAULT_VIEW_STATE, parseViewState } from "./lib/urlState";
import { AccountPage } from "./pages/AccountPage";
import { AllTicketsPage } from "./pages/AllTicketsPage";
import { ContactPage } from "./pages/ContactPage";
import { GameDetailPage } from "./pages/GameDetailPage";
import { PrivacyPage } from "./pages/PrivacyPage";
import { TermsPage } from "./pages/TermsPage";
import type { GameDetail } from "./types/gameDetails";
import type { GameHistory } from "./types/gameHistory";
import type {
  RankingDataset,
  RankingRecord,
  RankingViewState,
} from "./types/rankings";

interface AppProps {
  datasetOverride?: RankingDataset;
  gameDetailOverride?: GameDetail;
  gameHistoryOverride?: GameHistory;
}

const RANKING_PAGE_SIZE = 12;
const PUBLIC_ORIGIN = "https://scratchoffdata.com";

export default function App({ datasetOverride, gameDetailOverride, gameHistoryOverride }: AppProps) {
  return (
    <BrowserRouter>
      <AuthSessionProvider>
        <SiteDataProvider datasetOverride={datasetOverride}>
          <Routes>
            <Route element={<SiteLayout />}>
              <Route index element={<RankingPage />} />
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
              <Route path="tickets" element={<AllTicketsPage />} />
              <Route path="privacy" element={<PrivacyPage />} />
              <Route path="terms" element={<TermsPage />} />
              <Route path="contact" element={<ContactPage />} />
            </Route>
          </Routes>
        </SiteDataProvider>
      </AuthSessionProvider>
    </BrowserRouter>
  );
}

function SiteLayout() {
  const location = useLocation();
  const [noticeMode, setNoticeMode] = useState<SiteNoticeMode | null>(() =>
    hasCurrentSiteNoticeAcknowledgment() ? null : "required",
  );
  const noticeTriggerRef = useRef<HTMLButtonElement>(null);
  const restoreNoticeFocus = useRef(false);
  const closeNotice = useCallback(() => {
    restoreNoticeFocus.current = true;
    setNoticeMode(null);
  }, []);
  const acknowledgeNotice = useCallback(() => {
    persistSiteNoticeAcknowledgment();
    setNoticeMode(null);
  }, []);

  useLayoutEffect(() => {
    const background = document.getElementById("site-background");
    if (!background) return;
    if (noticeMode) {
      background.setAttribute("inert", "");
      background.setAttribute("aria-hidden", "true");
    } else {
      background.removeAttribute("inert");
      background.removeAttribute("aria-hidden");
      if (restoreNoticeFocus.current) {
        restoreNoticeFocus.current = false;
        noticeTriggerRef.current?.focus();
      }
    }
    return () => {
      background.removeAttribute("inert");
      background.removeAttribute("aria-hidden");
    };
  }, [noticeMode]);

  useEffect(() => {
    let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (!canonical) {
      canonical = document.createElement("link");
      canonical.rel = "canonical";
      document.head.append(canonical);
    }
    canonical.href = `${PUBLIC_ORIGIN}${location.pathname}`;
  }, [location.pathname]);

  return (
    <div className="site-shell">
      <div id="site-background">
        <SiteHeader noticeTriggerRef={noticeTriggerRef} onOpenNotice={() => setNoticeMode("voluntary")} />
        <AuthResultNotice />
        <Outlet />
        <SiteFooter />
      </div>
      {noticeMode ? (
        <SiteNoticeDialog
          mode={noticeMode}
          onAcknowledge={acknowledgeNotice}
          onClose={closeNotice}
        />
      ) : null}
    </div>
  );
}

function RankingPage() {
  const { dataset, error, retry } = useSiteData();
  const [viewState, updateViewState] = useRankingViewState();

  return (
    <main id="main-content">
      <Hero
        viewState={viewState}
        onSelectStrategy={(strategy) => {
          updateViewState({ strategy });
          window.requestAnimationFrame(() => {
            const rankings = document.getElementById("rankings");
            if (rankings && typeof rankings.scrollIntoView === "function") {
              rankings.scrollIntoView({ behavior: "smooth" });
            }
          });
        }}
      />
      {error ? (
        <section className="load-state" aria-live="polite">
          <p className="eyebrow">DATA CONNECTION</p>
          <h2>We could not load the comparison.</h2>
          <p>{error}</p>
          <button className="button" onClick={retry}>
            Try again
          </button>
        </section>
      ) : dataset ? (
        <RankingExperience
          dataset={dataset}
          viewState={viewState}
          updateViewState={updateViewState}
        />
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

function RankingExperience({
  dataset,
  viewState,
  updateViewState,
}: {
  dataset: RankingDataset;
  viewState: RankingViewState;
  updateViewState: (patch: Partial<RankingViewState>) => void;
}) {
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
  const visibleRows = filtered.slice(0, visibleRowCount);
  const hiddenRowCount = filtered.length - visibleRows.length;

  useEffect(() => {
    setVisibleRowCount(RANKING_PAGE_SIZE);
  }, [viewState.strategy, viewState.ticketPrice]);

  return (
    <>
      <section className="ranking-section" id="rankings" aria-labelledby="ranking-insight-title">
        <div className="ranking-section__heading">
          <div>
            <p className="eyebrow">CURRENT VIEW</p>
            <h2 id="ranking-insight-title">{strategy.question}</h2>
            <p>{strategy.explanation}</p>
          </div>
          <div className="ranking-strategy-control">
            <span>Change player type</span>
            <StrategyPicker
              variant="tabs"
              selected={viewState.strategy}
              onSelect={(selected) => updateViewState({ strategy: selected })}
            />
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
              filteredByPrice={viewState.ticketPrice !== "all"}
              viewState={viewState}
            />
            <div className="all-rankings-heading" id="all-tickets">
              <div>
                <p className="eyebrow">ALL TICKETS</p>
                <h3>Every ticket for this question</h3>
              </div>
              <p>
                Values stay visible without hover. Rank ties share the same number.
              </p>
              <ShareLinkButton
                href={comparisonHref(viewState)}
                label="Copy this view"
                successMessage="Comparison link copied."
              />
            </div>
            <RankingsTable
              rankings={visibleRows}
              filteredByPrice={viewState.ticketPrice !== "all"}
              viewState={viewState}
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

function SiteHeader({
  noticeTriggerRef,
  onOpenNotice,
}: {
  noticeTriggerRef: React.RefObject<HTMLButtonElement | null>;
  onOpenNotice: () => void;
}) {
  const location = useLocation();
  const viewState = parseViewState(location.search);
  const { dataset } = useSiteData();
  const { state: authState } = useAuthSession();
  return (
    <header className="site-header">
      <div className="site-header__left">
        <div className="site-header__brand-group">
          <Link className="brand" to="/" aria-label="Scratch-Off Data home">
            <BrandMark />
            <span>
              <strong>Scratch-Off Data</strong>
            </span>
          </Link>
          <HeaderDataStamp dataset={dataset} />
        </div>
        <button
          className="read-first__trigger"
          onClick={onOpenNotice}
          ref={noticeTriggerRef}
          type="button"
        >
          Important information
        </button>
      </div>
      <nav aria-label="Primary navigation">
        <Link to={comparisonHref(viewState, "#player-types")}>Player types</Link>
        <Link to="/tickets">All games</Link>
        <Link to={comparisonHref(viewState, "#methodology")}>Methodology</Link>
        {authState.status === "authenticated" ? (
          <Link to="/account#ticket-history">My ticket history</Link>
        ) : null}
      </nav>
      <div className="site-header__account">
        <SignInControl />
      </div>
      <TicketFinder dataset={dataset} />
    </header>
  );
}

function Hero({
  viewState,
  onSelectStrategy,
}: {
  viewState: RankingViewState;
  onSelectStrategy: (strategy: RankingViewState["strategy"]) => void;
}) {
  return (
    <section className="hero" id="top">
      <div className="hero__copy">
        <p className="eyebrow">ILLINOIS INSTANT TICKETS · PUBLIC DATA</p>
        <h1>
          Compare the prize pool.
          <span>Understand the odds.</span>
        </h1>
        <p className="hero__lede">
          Compare current Illinois instant tickets using the outcome that matters most
          to you. Every ranking shows the estimate behind it and what changes when the
          jackpot is removed.
        </p>
      </div>
      <aside className="hero-player-types" id="player-types" aria-labelledby="player-types-title">
        <p className="eyebrow">START HERE</p>
        <h2 id="player-types-title">What type of player are you?</h2>
        <p>Choose the question that sounds most like you.</p>
        <StrategyPicker
          variant="hero"
          selected={viewState.strategy}
          onSelect={onSelectStrategy}
        />
        <Link className="hero-all-tickets" to="/tickets">
          <span>Not sure yet?</span>
          <strong>I can’t decide. Show me every ticket.</strong>
          <small>Browse every current game without choosing a player type.</small>
        </Link>
      </aside>
    </section>
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
          <strong>Scratch-Off Data</strong>
        </span>
      </div>
      <p>Independent analysis of public Illinois Lottery data.</p>
      <p>Independent tool · not affiliated with the Illinois Lottery.</p>
      <nav className="site-footer__links" aria-label="Site information">
        <Link to="/privacy">Privacy</Link>
        <Link to="/terms">Terms</Link>
        <Link to="/contact">Contact</Link>
      </nav>
      <p className="site-footer__play">
        Must be 18 or older to play. Problem-gambling help: 1-800-GAMBLER.
      </p>
    </footer>
  );
}

export function visibleGameIds(rows: RankingRecord[]): number[] {
  return rows.map((row) => row.gameId);
}
