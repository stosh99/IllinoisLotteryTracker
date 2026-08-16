import type { RankingDataset } from "../types/rankings";

export function HeaderDataStamp({ dataset }: { dataset: RankingDataset | null }) {
  const value = dataValidAt(dataset);
  if (!value) return <span className="header-data-stamp">Data time unavailable</span>;
  return (
    <span className="header-data-stamp">
      Data valid as of <time dateTime={value}>{formatDataTimestamp(value)}</time>
    </span>
  );
}

export function dataValidAt(dataset: RankingDataset | null): string | null {
  if (!dataset) return null;
  const values = [dataset.status.sourceObservedAt, dataset.status.catalogObservedAt]
    .filter((value): value is string => value !== null)
    .map((value) => ({ value, time: Date.parse(value) }))
    .filter(({ time }) => !Number.isNaN(time))
    .sort((left, right) => left.time - right.time);
  return values[0]?.value ?? null;
}

function formatDataTimestamp(value: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
    timeZoneName: "short",
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value ?? "";
  return `${part("month")}/${part("day")}/${part("year")} · ${part("hour")}:${part("minute")} ${part("dayPeriod")} ${part("timeZoneName")}`;
}
