import type { RankingReasonCode } from "../types/rankings";

const messages: Record<RankingReasonCode, { title: string; detail: string }> = {
  AVAILABLE: {
    title: "No complete rows match these filters",
    detail: "Clear the ticket search or reset the ticket-price filter to widen the comparison.",
  },
  ANALYTICS_MODEL_UNAVAILABLE: {
    title: "We cannot calculate a trustworthy comparison right now",
    detail: "The current estimate settings could not be verified. No rankings are shown until that check succeeds.",
  },
  SOURCE_UNAVAILABLE: {
    title: "The official prize report is unavailable",
    detail: "A complete Illinois Lottery prize-count report is required before current games can be compared.",
  },
  CATALOG_UNAVAILABLE: {
    title: "The current games-for-sale list is unavailable",
    detail: "The site needs both official prize counts and a complete list of games currently offered for sale.",
  },
  SOURCE_STALE: {
    title: "The official prize counts are out of date",
    detail: "Older counts are not presented as a current ranking. No demonstration games are substituted.",
  },
  CATALOG_STALE: {
    title: "The games-for-sale list is out of date",
    detail: "The site cannot safely say which games are currently available, so the comparison is paused.",
  },
  ANALYTICS_UNAVAILABLE: {
    title: "The newest data is still being processed",
    detail: "Current rankings will return after the latest official data has been calculated and checked.",
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
