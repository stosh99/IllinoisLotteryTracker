import type { RankingDataset, RankingReasonCode } from "../types/rankings";

const reasonCopy: Record<Exclude<RankingReasonCode, "AVAILABLE">, string> = {
  ANALYTICS_MODEL_UNAVAILABLE:
    "The current versioned analytics definition is unavailable.",
  SOURCE_UNAVAILABLE:
    "A complete unpaid-prizes source capture is not currently available.",
  CATALOG_UNAVAILABLE:
    "A complete retail catalog capture is not currently available.",
  SOURCE_STALE:
    "The latest unpaid-prizes source is too old to support a current comparison.",
  CATALOG_STALE:
    "The latest retail catalog is too old to support a current comparison.",
  ANALYTICS_UNAVAILABLE:
    "Analytics for the newest source cutoff are pending or failed.",
};

interface DataStatusProps {
  dataset: RankingDataset;
}

export function DataStatus({ dataset }: DataStatusProps) {
  const { rankings, status } = dataset;
  const isAvailable = status.available;
  const title = isAvailable ? "Current comparison available" : "Rankings unavailable";
  const detail = isAvailable
    ? "Source, catalog, and analytics cutoffs are aligned."
    : reasonCopy[status.reasonCode as Exclude<RankingReasonCode, "AVAILABLE">];

  return (
    <section
      className={`data-status data-status--${isAvailable ? "ready" : "blocked"}`}
      id="data-status"
      aria-labelledby="data-status-title"
    >
      <div className="data-status__signal" aria-hidden="true">
        <span />
      </div>
      <div className="data-status__copy">
        <p className="data-status__eyebrow">
          {isAvailable ? "PUBLISHED DATA" : status.reasonCode}
        </p>
        <h2 id="data-status-title">{title}</h2>
        <p>{detail}</p>
      </div>
      <dl className="data-status__facts">
        <div>
          <dt>Games available</dt>
          <dd>{isAvailable ? new Set(rankings.map((row) => row.gameId)).size : 0}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>{status.modelVersion ?? "Unavailable"}</dd>
        </div>
        <div>
          <dt>Prize source</dt>
          <dd>
            <Timestamp value={status.sourceObservedAt} />
          </dd>
        </div>
        <div>
          <dt>Retail catalog</dt>
          <dd>
            <Timestamp value={status.catalogObservedAt} />
          </dd>
        </div>
        <div>
          <dt>Page generated</dt>
          <dd>
            <Timestamp value={dataset.generatedAt} />
          </dd>
        </div>
      </dl>
    </section>
  );
}

function Timestamp({ value }: { value: string | null }) {
  const formatted = formatTimestamp(value);
  return value && formatted !== "Unavailable" ? (
    <time dateTime={value}>{formatted}</time>
  ) : (
    <>Unavailable</>
  );
}

function formatTimestamp(value: string | null): string {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
    timeZoneName: "short",
  }).format(date);
}
