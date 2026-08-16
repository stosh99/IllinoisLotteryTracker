import { buildOutcomeRows, formatOutcomeProbability } from "../lib/outcomeLadder";
import { formatMoney, formatOneIn } from "../lib/strategies";
import type { GameDetail, OutcomeMetricStatus } from "../types/gameDetails";
import { EvidenceTag } from "./EvidenceGuide";
import { formatRemainingCount } from "./LeaderCards";

export function OutcomeLadder({ detail }: { detail: GameDetail }) {
  const rows = buildOutcomeRows(detail.outcomes);
  const anyWin = rows.find(({ key }) => key === "any_win")!;
  const profit = rows.find(({ key }) => key === "profit_full")!;
  const tenX = rows.find(({ key }) => key === "moderate_10x_full")!;
  const jackpot = rows.find(({ lane }) => lane === "jackpot")!;

  return (
    <section className="outcome-ladder" aria-labelledby="outcome-ladder-title">
      <div className="outcome-ladder__heading">
        <div>
          <p className="eyebrow">OUTCOME LADDER</p>
          <h2 id="outcome-ladder-title">What are my chances?</h2>
        </div>
        <p>Three different ways to define a winning ticket</p>
      </div>

      <div className="outcome-ladder__layout">
        <div className="outcome-ladder__main">
          <OutcomeCard row={anyWin} eyebrow="ANY PRIZE" />
          <OutcomeCard row={profit} eyebrow="COME OUT AHEAD" />
          <OutcomeCard row={tenX} eyebrow="10× UPSIDE" />
        </div>

        <aside className="outcome-ladder__jackpot" aria-labelledby="jackpot-outcome-title">
          <p className="eyebrow">SEPARATE JACKPOT LANE</p>
          <h3 id="jackpot-outcome-title">{jackpot.label}</h3>
          <p>{jackpot.definition}</p>
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
          <OutcomeExactValues row={jackpot} />
          <EvidenceTag kind="estimated" />
        </aside>
      </div>

      <p className="outcome-ladder__caveat">
        These are nested chances: a 10× prize also counts as a profit and as any
        prize, so do not add the percentages together. Estimates describe the game,
        not what the next ticket will do.
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

function OutcomeCard({
  row,
  eyebrow,
}: {
  row: OutcomeRowView;
  eyebrow: string;
}) {
  return (
    <div className="outcome-ladder__break-even">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h3>{row.label}</h3>
        <p>{row.definition}</p>
      </div>
      <OutcomeExactValues row={row} />
      <EvidenceTag kind="estimated" />
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
