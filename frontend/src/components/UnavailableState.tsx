import type { RankingReasonCode } from "../types/rankings";

const messages: Record<RankingReasonCode, { title: string; detail: string }> = {
  AVAILABLE: {
    title: "No complete rows match these filters",
    detail: "Reset the ticket-price filter to widen the comparison.",
  },
  ANALYTICS_MODEL_UNAVAILABLE: {
    title: "The analytics definition is unavailable",
    detail: "The site cannot find the current versioned analytics definition.",
  },
  SOURCE_UNAVAILABLE: {
    title: "Prize-source data is unavailable",
    detail: "A complete official unpaid-prizes capture is required before comparison.",
  },
  CATALOG_UNAVAILABLE: {
    title: "Retail catalog data is unavailable",
    detail: "Rankings require a fresh mapped catalog as well as the prize source.",
  },
  SOURCE_STALE: {
    title: "The prize source is stale",
    detail: "Last-known data is not presented as a current ranking.",
  },
  CATALOG_STALE: {
    title: "The retail catalog is stale",
    detail: "The site cannot safely say which games are still offered for sale.",
  },
  ANALYTICS_UNAVAILABLE: {
    title: "Current analytics are unavailable",
    detail: "The analytical stage for the newest source cutoff is pending or failed.",
  },
};

interface UnavailableStateProps {
  reasonCode: RankingReasonCode;
  onReset?: () => void;
}

export function UnavailableState({ reasonCode, onReset }: UnavailableStateProps) {
  const message = messages[reasonCode];
  return (
    <div className="unavailable-state" role="status">
      <span className="unavailable-state__mark" aria-hidden="true">!</span>
      <p className="eyebrow">COMPARISON PAUSED</p>
      <h3>{message.title}</h3>
      <p>{message.detail}</p>
      {onReset ? (
        <button className="button button--outline" onClick={onReset} type="button">
          Reset filters
        </button>
      ) : null}
    </div>
  );
}
