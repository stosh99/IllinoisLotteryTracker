import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { loadRankingDataset } from "../services/rankings";
import type { RankingDataset } from "../types/rankings";

interface SiteDataContextValue {
  dataset: RankingDataset | null;
  error: string | null;
  retry: () => void;
}

const SiteDataContext = createContext<SiteDataContextValue | null>(null);

export function SiteDataProvider({
  children,
  datasetOverride,
}: {
  children: ReactNode;
  datasetOverride?: RankingDataset;
}) {
  const [dataset, setDataset] = useState<RankingDataset | null>(datasetOverride ?? null);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    if (datasetOverride) {
      setDataset(datasetOverride);
      setError(null);
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

  const retry = useCallback(() => setRequestVersion((value) => value + 1), []);
  const value = useMemo(() => ({ dataset, error, retry }), [dataset, error, retry]);
  return <SiteDataContext.Provider value={value}>{children}</SiteDataContext.Provider>;
}

export function useSiteData(): SiteDataContextValue {
  const value = useContext(SiteDataContext);
  if (!value) throw new Error("useSiteData must be used inside SiteDataProvider");
  return value;
}
