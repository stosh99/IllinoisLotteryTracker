import type { CSSProperties } from "react";

import { buildOutcomeRows, formatOutcomeProbability } from "../lib/outcomeLadder";
import { formatMoney, formatOneIn } from "../lib/strategies";
import type { GameDetail, OutcomeMetricStatus } from "../types/gameDetails";
import { EvidenceTag } from "./EvidenceGuide";
import { formatRemainingCount } from "./LeaderCards";

export function OutcomeLadder({ detail }: { detail: GameDetail }) {
  const rows = buildOutcomeRows(detail.outcomes);
  const breakEven = rows.find(({ lane }) => lane === "break-even")!;
  const ordinary = rows.filter(({ lane }) => lane === "ordinary");
  const jackpot = rows.find(({ lane }) => lane === "jackpot")!;

  return (
    <section className="outcome-ladder" aria-labelledby="outcome-ladder-title">
      <div className="outcome-ladder__heading">
        <div>
          <p className="eyebrow">OUTCOME LADDER</p>
          <h2 id="outcome-ladder-title">What could one ticket return?</h2>
        </div>
        <p>Estimated current chances · values stay visible without hover</p>
      </div>

      <div className="outcome-ladder__layout">
        <div className="outcome-ladder__main">
          <OutcomeCard row={breakEven} />

          <div className="outcome-ladder__ordinary" aria-labelledby="ordinary-outcomes-title">
            <div className="outcome-ladder__lane-heading">
              <div>
                <h3 id="ordinary-outcomes-title">Ordinary profit</h3>
                <p>These thresholds exclude the top-prize tier.</p>
              </div>
              <EvidenceTag kind="estimated" />
            </div>
            <ol aria-label="Nested ordinary-profit outcomes">
              {ordinary.map((row) => (
                <li key={row.key} style={{ "--outcome-depth": row.depth } as CSSProperties}>
                  <OutcomeValues row={row} />
                  <div className="outcome-ladder__track" aria-hidden="true">
                    <span style={{ width: `${row.relativeWidth}%` }} />
                  </div>
                </li>
              ))}
            </ol>
            <p className="outcome-ladder__relationship-note">
              <strong>Read these as nested chances.</strong> A 10× prize also counts
              as 5× and as a profit, so do not add these three percentages together.
            </p>
          </div>
        </div>

        <aside className="outcome-ladder__jackpot" aria-labelledby="jackpot-outcome-title">
          <p className="eyebrow">SEPARATE JACKPOT LANE</p>
          <h3 id="jackpot-outcome-title">{jackpot.label}</h3>
          <p>{jackpot.definition}</p>
          <OutcomeExactValues row={jackpot} />
          <dl>
            <div>
              <dt>Top prize amount</dt>
              <dd>{formatMoney(detail.topPrizeAmount, true)}</dd>
            </div>
            <div>
              <dt>Official inventory</dt>
              <dd>
                {formatRemainingCount(
                  detail.topPrizesRemaining,
                  detail.topPrizesOriginal,
                )}
              </dd>
            </div>
          </dl>
          <EvidenceTag kind="estimated" />
        </aside>
      </div>

      <p className="outcome-ladder__caveat">
        These chances use estimated tickets remaining and describe the game—not
        what the next ticket will do. “Exactly money back” is break-even, not profit.
      </p>
    </section>
  );
}

interface OutcomeRowView {
  label: string;
  definition: string;
  available: boolean;
  probability: number | null;
  oneIn: number | null;
  metricStatus: OutcomeMetricStatus;
}

function OutcomeCard({ row }: { row: OutcomeRowView }) {
  return (
    <div className="outcome-ladder__break-even">
      <div>
        <p className="eyebrow">BREAK EVEN</p>
        <h3>{row.label}</h3>
        <p>{row.definition}</p>
      </div>
      <OutcomeExactValues row={row} />
      <EvidenceTag kind="estimated" />
    </div>
  );
}

function OutcomeValues({ row }: { row: OutcomeRowView }) {
  return (
    <div className="outcome-ladder__row-values">
      <div>
        <strong>{row.label}</strong>
        <small>{row.definition}</small>
      </div>
      <OutcomeExactValues row={row} />
    </div>
  );
}

function OutcomeExactValues({ row }: { row: OutcomeRowView }) {
  if (!row.available) {
    return (
      <div className="outcome-ladder__exact outcome-ladder__exact--unavailable">
        <strong>Unavailable</strong>
        <small>{unavailableReason(row.metricStatus)}</small>
      </div>
    );
  }
  return (
    <div className="outcome-ladder__exact">
      <strong>{formatOneIn(row.oneIn)}</strong>
      <small>{formatOutcomeProbability(row.probability)} estimated chance</small>
    </div>
  );
}

function unavailableReason(status: OutcomeMetricStatus): string {
  if (status === "not_applicable") return "No matching prize tier in this game";
  if (status === "partial") return "Current estimate is incomplete";
  return "Current estimate is unavailable";
}
