import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  formatMetric,
  formatMoney,
  formatOneIn,
  formatRelativeToLaunch,
  getSupportingEv,
  getStrategy,
} from "../lib/strategies";
import type { RankingRecord } from "../types/rankings";

interface LeaderCardsProps {
  rankings: RankingRecord[];
  maxMetric: number;
  filteredByPrice: boolean;
  totalRankings: number;
}

export function LeaderCards({
  rankings,
  maxMetric,
  filteredByPrice,
  totalRankings,
}: LeaderCardsProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [visibleCount, setVisibleCount] = useState(1);
  const [canScrollPrevious, setCanScrollPrevious] = useState(false);
  const [canScrollNext, setCanScrollNext] = useState(rankings.length > 1);

  const updateCarouselState = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const measurements = measureCarousel(track);
    if (!measurements) return;

    setActiveIndex(measurements.activeIndex);
    setVisibleCount(measurements.visibleCount);
    setCanScrollPrevious(measurements.canScrollPrevious);
    setCanScrollNext(measurements.canScrollNext);
  }, []);

  const scheduleCarouselStateUpdate = useCallback(() => {
    if (scrollFrameRef.current !== null) return;
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      updateCarouselState();
    });
  }, [updateCarouselState]);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = null;
    }
    track.scrollLeft = 0;
    setActiveIndex(0);
    setCanScrollPrevious(false);
    setCanScrollNext(rankings.length > 1);

    const frame = window.requestAnimationFrame(updateCarouselState);
    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(updateCarouselState);
    resizeObserver?.observe(track);
    track.addEventListener("scrollend", updateCarouselState);
    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      track.removeEventListener("scrollend", updateCarouselState);
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [rankings, updateCarouselState]);

  const scrollCards = (direction: -1 | 1) => {
    const track = trackRef.current;
    if (!track) return;
    const cards = Array.from(track.querySelectorAll<HTMLElement>(".leader-card"));
    const measurements = measureCarousel(track);
    if (!measurements) return;
    const pageStarts = getCarouselPageStarts(cards.length, measurements.visibleCount);
    const targetIndex =
      direction === 1
        ? (pageStarts.find((start) => start > measurements.activeIndex) ??
          pageStarts.at(-1) ??
          0)
        : ([...pageStarts].reverse().find((start) => start < measurements.activeIndex) ??
          pageStarts[0] ??
          0);
    const target = cards[targetIndex];
    if (!target) return;
    track.scrollLeft = target.offsetLeft;
    updateCarouselState();
  };

  const carouselLabel = formatCardRange(activeIndex, visibleCount, rankings.length);

  return (
    <div className="leader-carousel">
      <div className="leader-carousel__toolbar">
        <p>
          Top {rankings.length} {rankings.length === 1 ? "leader" : "leaders"} · {totalRankings}{" "}
          {totalRankings === 1 ? "game" : "games"} in view
        </p>
        <div className="leader-carousel__buttons" aria-label="Browse ranked cards">
          <button
            aria-label="Show previous ranked games"
            disabled={!canScrollPrevious}
            onClick={() => scrollCards(-1)}
            type="button"
          >
            <ArrowIcon direction="previous" />
          </button>
          <button
            aria-label="Show more ranked games"
            disabled={!canScrollNext}
            onClick={() => scrollCards(1)}
            type="button"
          >
            <ArrowIcon direction="next" />
          </button>
        </div>
      </div>
      <div
        aria-label="Ranked game cards"
        className="leader-track"
        onScroll={scheduleCarouselStateUpdate}
        ref={trackRef}
        role="region"
        tabIndex={0}
      >
        {rankings.map((record, index) => {
          const supportingEv = getSupportingEv(record);
          return (
            <article className="leader-card" data-position={index + 1} key={record.gameId}>
              <Link
                aria-label={`View details for ${record.gameName}`}
                className="leader-card__link"
                draggable={false}
                to={`/games/${record.gameId}`}
              >
                <div className="leader-card__topline">
                <span className="rank-badge">
                  #{filteredByPrice ? record.rankWithinTicketPrice : record.rankOverall}
                </span>
                <span className="price-badge">${record.ticketPrice} ticket</span>
                </div>
                <p className="game-number">Game {record.gameNumber}</p>
                <h3>{record.gameName}</h3>
                <div className="leader-card__metric">
                <span>{getStrategy(record.strategyKey).metricLabel}</span>
                <strong>{primaryMetric(record)}</strong>
                <small>{secondaryMetric(record)}</small>
                </div>
                <progress
                aria-label="Relative metric within this comparison"
                className="metric-track"
                max="100"
                value={relativeWidth(record.metricValue, maxMetric)}
                />
                <dl className="leader-card__details">
                <div>
                  <dt>{supportingEv.label}</dt>
                  <dd>{formatMoney(supportingEv.value)}</dd>
                </div>
                <div>
                  <dt>Top prize</dt>
                  <dd>
                    {formatMoney(record.topPrizeAmount, true)} ·{" "}
                    {formatRemainingCount(
                      record.topPrizesRemaining,
                      record.topPrizesOriginal,
                    )}
                  </dd>
                </div>
                </dl>
                <footer>
                  <ConfidenceBadge record={record} />
                  <span>{formatRelativeToLaunch(record.relativeToLaunch)}</span>
                </footer>
                <span className="leader-card__view-link">View prize tiers →</span>
              </Link>
            </article>
          );
        })}
      </div>
      <p className="visually-hidden" aria-live="polite">
        {carouselLabel}.
      </p>
    </div>
  );
}

interface CarouselMeasurements {
  activeIndex: number;
  visibleCount: number;
  canScrollPrevious: boolean;
  canScrollNext: boolean;
}

function measureCarousel(track: HTMLDivElement): CarouselMeasurements | null {
  const cards = Array.from(track.querySelectorAll<HTMLElement>(".leader-card"));
  const firstCard = cards[0];
  if (!firstCard) return null;

  const activeIndex = cards.reduce((closest, card, index) => {
    const closestDistance = Math.abs(cards[closest]!.offsetLeft - track.scrollLeft);
    const distance = Math.abs(card.offsetLeft - track.scrollLeft);
    return distance < closestDistance ? index : closest;
  }, 0);
  const visibleCount = Math.min(
    cards.length,
    Math.max(1, Math.round(track.clientWidth / Math.max(firstCard.offsetWidth, 1))),
  );
  const maximumScroll = Math.max(0, track.scrollWidth - track.clientWidth);

  return {
    activeIndex,
    visibleCount,
    canScrollPrevious: track.scrollLeft > 2,
    canScrollNext: track.scrollLeft < maximumScroll - 2,
  };
}

export function getCarouselPageStarts(cardCount: number, cardsPerPage: number): number[] {
  const safeCardsPerPage = Math.max(1, cardsPerPage);
  const maximumStart = Math.max(0, cardCount - safeCardsPerPage);
  const starts = [0];
  for (let start = safeCardsPerPage; start < maximumStart; start += safeCardsPerPage) {
    starts.push(start);
  }
  if (starts.at(-1) !== maximumStart) {
    starts.push(maximumStart);
  }
  return starts;
}

export function formatCardRange(
  activeIndex: number,
  visibleCount: number,
  totalGames: number,
): string {
  const start = totalGames === 0 ? 0 : Math.min(activeIndex + 1, totalGames);
  const end = Math.min(totalGames, activeIndex + Math.max(1, visibleCount));
  return `Showing cards ${start}–${end} of ${totalGames} ${totalGames === 1 ? "game" : "games"}`;
}

function ArrowIcon({ direction }: { direction: "previous" | "next" }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path
        d={direction === "previous" ? "m12.5 4.5-5.5 5.5 5.5 5.5" : "m7.5 4.5 5.5 5.5-5.5 5.5"}
      />
    </svg>
  );
}

export function ConfidenceBadge({ record }: { record: RankingRecord }) {
  return (
    <span className={`confidence-badge confidence-badge--${record.lowestConfidence}`}>
      {record.lowestConfidence} confidence
      {record.containsLumpyTier ? " · lumpy tier" : ""}
    </span>
  );
}

export function primaryMetric(record: RankingRecord): string {
  if (record.strategyKey === "jackpot_top_odds") {
    return formatOneIn(record.oneInValue);
  }
  return formatMetric(record);
}

export function secondaryMetric(record: RankingRecord): string {
  if (record.strategyKey === "jackpot_top_odds") {
    return `${formatMetric(record)} estimated chance`;
  }
  if (record.oneInValue !== null) {
    return formatOneIn(record.oneInValue);
  }
  return "Estimated return per $1 played";
}

export function relativeWidth(value: number, maximum: number): number {
  if (maximum <= 0) return 0;
  return Math.max(5, Math.min(100, (value / maximum) * 100));
}

export function formatRemainingCount(
  remaining: number | null,
  original: number | null,
): string {
  if (remaining === null) return "count unavailable";
  if (original === null) return `${remaining} left`;
  return `${remaining} out of ${original} left`;
}
