import type { RankingDataset, RankingReasonCode } from "../types/rankings";

const reasonCopy: Record<Exclude<RankingReasonCode, "AVAILABLE">, string> = {
  ANALYTICS_MODEL_UNAVAILABLE:
    "The current estimate settings could not be verified, so no rankings are shown.",
  SOURCE_UNAVAILABLE:
    "A complete official prize-count report is not available right now.",
  CATALOG_UNAVAILABLE:
    "A complete list of games currently offered for sale is not available right now.",
  SOURCE_STALE:
    "The latest official prize counts are too old to present as a current comparison.",
  CATALOG_STALE:
    "The latest list of games for sale is too old to present as current.",
  ANALYTICS_UNAVAILABLE:
    "The newest official data has not finished processing, so current rankings are paused.",
};

interface DataStatusProps {
  dataset: RankingDataset;
}

export function DataStatus({ dataset }: DataStatusProps) {
  const { rankings, status } = dataset;
  const isAvailable = status.available;
  const title = isAvailable ? "Comparison ready" : "Current comparison paused";
  const detail = isAvailable
    ? "Official prize counts and the retail game list are complete for the dates shown. Every estimate uses that same snapshot."
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
          DATA STATUS
        </p>
        <h2 id="data-status-title">{title}</h2>
        <p>{detail}</p>
      </div>
      <dl className="data-status__facts">
        <div>
          <dt>Games compared</dt>
          <dd>{isAvailable ? new Set(rankings.map((row) => row.gameId)).size : 0}</dd>
        </div>
        <div>
          <dt>Official prize counts</dt>
          <dd>
            <Timestamp value={status.sourceObservedAt} />
          </dd>
        </div>
        <div>
          <dt>Games-for-sale list</dt>
          <dd>
            <Timestamp value={status.catalogObservedAt} />
          </dd>
        </div>
        <div>
          <dt>Page updated</dt>
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
