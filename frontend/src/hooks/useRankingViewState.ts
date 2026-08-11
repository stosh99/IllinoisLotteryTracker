import { useCallback, useEffect, useState } from "react";

import type { RankingViewState } from "../types/rankings";
import { parseViewState, serializeViewState } from "../lib/urlState";

export function useRankingViewState(): [
  RankingViewState,
  (patch: Partial<RankingViewState>) => void,
] {
  const [viewState, setViewState] = useState<RankingViewState>(() =>
    parseViewState(window.location.search),
  );

  useEffect(() => {
    const onPopState = () => setViewState(parseViewState(window.location.search));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const updateViewState = useCallback((patch: Partial<RankingViewState>) => {
    setViewState((current) => {
      const next = { ...current, ...patch };
      const search = serializeViewState(next);
      const nextUrl = `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`;
      window.history.pushState({}, "", nextUrl);
      return next;
    });
  }, []);

  return [viewState, updateViewState];
}
