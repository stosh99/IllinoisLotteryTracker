import { useEffect, useId, useRef, useState, type RefObject } from "react";

export interface TimeSeriesChartPoint {
  observedAt: string;
  value: number;
  segment: number;
}

export interface TimeSeriesChartSeries {
  key: string;
  label: string;
  color: string;
  dash?: string;
  points: TimeSeriesChartPoint[];
}

interface TimeSeriesChartProps {
  ariaLabel: string;
  description: string;
  series: TimeSeriesChartSeries[];
  unitLabel: string;
  yDomain: [number, number];
  formatY: (value: number) => string;
}

interface PlotBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

interface SegmentedPath {
  d: string;
  lastX: number;
  lastY: number;
  segment: number;
}

export function TimeSeriesChart({
  ariaLabel,
  description,
  series,
  unitLabel,
  yDomain,
  formatY,
}: TimeSeriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const width = useContainerWidth(containerRef);
  const titleId = `${useId().replaceAll(":", "")}-title`;
  const descriptionId = `${titleId}-description`;
  const height = width < 600 ? 300 : 350;
  const bounds: PlotBounds = {
    left: width < 600 ? 58 : 72,
    right: width - 18,
    top: 30,
    bottom: height - 48,
  };
  const allPoints = series.flatMap((item) => item.points);

  if (allPoints.length === 0) return null;

  const timestamps = allPoints.map((point) => Date.parse(point.observedAt));
  const minimumTime = Math.min(...timestamps);
  const maximumTime = Math.max(...timestamps);
  const safeMaximumTime = minimumTime === maximumTime ? maximumTime + 86_400_000 : maximumTime;
  const xScale = (value: number) =>
    scale(value, minimumTime, safeMaximumTime, bounds.left, bounds.right);
  const yScale = (value: number) =>
    scale(value, yDomain[0], yDomain[1], bounds.bottom, bounds.top);
  const xTicks = linearTicks(minimumTime, safeMaximumTime, width < 600 ? 3 : 5);
  const yTicks = linearTicks(yDomain[0], yDomain[1], 5);
  const segmentStarts = [
    ...new Set(series.flatMap((item) => segmentChangeDates(item.points))),
  ].sort((left, right) => left - right);

  return (
    <div className="time-series-chart" ref={containerRef}>
      <svg
        aria-labelledby={`${titleId} ${descriptionId}`}
        height={height}
        role="img"
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
      >
        <title id={titleId}>{ariaLabel}</title>
        <desc id={descriptionId}>{description}</desc>
        <text className="chart-unit-label" x={bounds.left} y={14}>{unitLabel}</text>
        <g className="chart-grid" aria-hidden="true">
          {yTicks.map((tick) => {
            const y = yScale(tick);
            return (
              <g key={tick}>
                <line x1={bounds.left} x2={bounds.right} y1={y} y2={y} />
                <text x={bounds.left - 9} y={y + 4}>{formatY(tick)}</text>
              </g>
            );
          })}
        </g>
        <g className="chart-structure-markers" aria-hidden="true">
          {segmentStarts.map((timestamp, index) => {
            const x = xScale(timestamp);
            return (
              <g key={timestamp}>
                <line x1={x} x2={x} y1={bounds.top} y2={bounds.bottom} />
                {index === 0 ? <text x={x + 5} y={bounds.top + 12}>Structure changed</text> : null}
              </g>
            );
          })}
        </g>
        <g className="chart-series" aria-hidden="true">
          {series.flatMap((item) =>
            buildSegmentedPaths(item.points, xScale, yScale).map((path) => (
              <g key={`${item.key}-${path.segment}`}>
                <path
                  d={path.d}
                  stroke={item.color}
                  strokeDasharray={item.dash}
                />
                <circle cx={path.lastX} cy={path.lastY} fill={item.color} r="3.5" />
              </g>
            )),
          )}
        </g>
        <g className="chart-x-axis" aria-hidden="true">
          {xTicks.map((tick, index) => {
            const x = xScale(tick);
            const anchor = index === 0 ? "start" : index === xTicks.length - 1 ? "end" : "middle";
            return (
              <g key={tick}>
                <line x1={x} x2={x} y1={bounds.bottom} y2={bounds.bottom + 5} />
                <text textAnchor={anchor} x={x} y={bounds.bottom + 24}>
                  {formatChartDate(tick)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

export function buildSegmentedPaths(
  points: TimeSeriesChartPoint[],
  xScale: (value: number) => number,
  yScale: (value: number) => number,
): SegmentedPath[] {
  const sorted = [...points].sort(
    (left, right) => Date.parse(left.observedAt) - Date.parse(right.observedAt),
  );
  const groups: TimeSeriesChartPoint[][] = [];
  for (const point of sorted) {
    const current = groups.at(-1);
    if (!current || current[0]!.segment !== point.segment) groups.push([point]);
    else current.push(point);
  }
  return groups.map((group) => {
    const coordinates = group.map((point) => ({
      x: xScale(Date.parse(point.observedAt)),
      y: yScale(point.value),
    }));
    const last = coordinates.at(-1)!;
    return {
      d: coordinates
        .map(({ x, y }, index) => `${index === 0 ? "M" : "L"}${round(x)},${round(y)}`)
        .join(" "),
      lastX: last.x,
      lastY: last.y,
      segment: group[0]!.segment,
    };
  });
}

export function linearTicks(start: number, end: number, count: number): number[] {
  if (count <= 1 || start === end) return [start];
  return Array.from({ length: count }, (_, index) =>
    start + ((end - start) * index) / (count - 1),
  );
}

function useContainerWidth(ref: RefObject<HTMLDivElement | null>): number {
  const [width, setWidth] = useState(900);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => {
      const next = Math.floor(element.getBoundingClientRect().width);
      if (next >= 320) setWidth(next);
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

function segmentChangeDates(points: TimeSeriesChartPoint[]): number[] {
  const sorted = [...points].sort(
    (left, right) => Date.parse(left.observedAt) - Date.parse(right.observedAt),
  );
  const starts = new Set<number>();
  for (let index = 1; index < sorted.length; index += 1) {
    if (sorted[index]!.segment > sorted[index - 1]!.segment) {
      starts.add(Date.parse(sorted[index]!.observedAt));
    }
  }
  return [...starts].sort((left, right) => left - right);
}

function scale(
  value: number,
  domainStart: number,
  domainEnd: number,
  rangeStart: number,
  rangeEnd: number,
): number {
  if (domainStart === domainEnd) return (rangeStart + rangeEnd) / 2;
  return rangeStart + ((value - domainStart) / (domainEnd - domainStart)) * (rangeEnd - rangeStart);
}

function formatChartDate(timestamp: number): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "America/Chicago",
  }).format(new Date(timestamp));
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
