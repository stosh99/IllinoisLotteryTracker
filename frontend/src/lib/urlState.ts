import {
  STRATEGY_KEYS,
  type RankingViewState,
  type StrategyKey,
  type TicketPriceFilter,
} from "../types/rankings";
import { DEFAULT_STRATEGY, PRIMARY_STRATEGIES } from "./strategies";

const primaryKeys = new Set(PRIMARY_STRATEGIES.map(({ key }) => key));
const allStrategyKeys = new Set<string>(STRATEGY_KEYS);

export const DEFAULT_VIEW_STATE: RankingViewState = {
  strategy: DEFAULT_STRATEGY,
  ticketPrice: "all",
};

function parseStrategy(value: string | null): StrategyKey {
  if (value && allStrategyKeys.has(value) && primaryKeys.has(value as StrategyKey)) {
    return value as StrategyKey;
  }
  return DEFAULT_VIEW_STATE.strategy;
}

function parseTicketPrice(value: string | null): TicketPriceFilter {
  if (!value || value === "all") return "all";
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : "all";
}

export function parseViewState(search: string): RankingViewState {
  const params = new URLSearchParams(search);
  return {
    strategy: parseStrategy(params.get("strategy")),
    ticketPrice: parseTicketPrice(params.get("price")),
  };
}

export function serializeViewState(state: RankingViewState): string {
  const params = new URLSearchParams();
  if (state.strategy !== DEFAULT_VIEW_STATE.strategy) {
    params.set("strategy", state.strategy);
  }
  if (state.ticketPrice !== "all") {
    params.set("price", String(state.ticketPrice));
  }
  return params.toString();
}

export function comparisonHref(
  state: RankingViewState,
  hash = "#rankings",
): string {
  const search = serializeViewState(state);
  return `/${search ? `?${search}` : ""}${normalizeHash(hash)}`;
}

export function gameDetailHref(gameId: number, state: RankingViewState): string {
  if (!Number.isInteger(gameId) || gameId <= 0) {
    throw new Error("Game detail links require a positive integer game id.");
  }
  const search = serializeViewState(state);
  return `/games/${gameId}${search ? `?${search}` : ""}`;
}

export function absolutePublicUrl(href: string, origin: string): string {
  const base = new URL(origin);
  if (!/^https?:$/.test(base.protocol)) {
    throw new Error("Public links require an HTTP origin.");
  }
  return new URL(href, `${base.origin}/`).toString();
}

export function viewStateLabel(state: RankingViewState): string {
  const strategy = PRIMARY_STRATEGIES.find(({ key }) => key === state.strategy);
  const strategyLabel = strategy?.shortLabel ?? PRIMARY_STRATEGIES[0]!.shortLabel;
  const priceLabel =
    state.ticketPrice === "all"
      ? "all ticket prices"
      : `$${state.ticketPrice} tickets`;
  return `${strategyLabel} · ${priceLabel}`;
}

function normalizeHash(hash: string): string {
  if (!hash) return "";
  return hash.startsWith("#") ? hash : `#${hash}`;
}
