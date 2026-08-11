import { useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import type { RankingViewState } from "../types/rankings";
import { parseViewState, serializeViewState } from "../lib/urlState";

export function useRankingViewState(): [
  RankingViewState,
  (patch: Partial<RankingViewState>) => void,
] {
  const location = useLocation();
  const navigate = useNavigate();
  const viewState = useMemo(
    () => parseViewState(location.search),
    [location.search],
  );

  const updateViewState = useCallback((patch: Partial<RankingViewState>) => {
    const next = { ...viewState, ...patch };
    const search = serializeViewState(next);
    void navigate({
      pathname: location.pathname,
      search: search ? `?${search}` : "",
      hash: location.hash,
    });
  }, [location.hash, location.pathname, navigate, viewState]);

  return [viewState, updateViewState];
}
