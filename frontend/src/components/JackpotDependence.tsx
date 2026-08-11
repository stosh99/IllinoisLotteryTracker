import { calculateJackpotDependence, formatCentsPerDollarValue, formatShare } from "../lib/decisionSupport";
import { EvidenceTag } from "./EvidenceGuide";

interface JackpotDependenceSummaryProps {
  ticketPrice: number;
  estimatedEvFull: number | null;
  estimatedEvExTop: number | null;
}

export function JackpotDependenceSummary({
  ticketPrice,
  estimatedEvFull,
  estimatedEvExTop,
}: JackpotDependenceSummaryProps) {
  const dependence = calculateJackpotDependence(
    ticketPrice,
    estimatedEvFull,
    estimatedEvExTop,
  );
  if (!dependence) return null;
  return (
    <p className="jackpot-dependence-summary">
      <EvidenceTag kind="estimated" />
      <span>
        About {formatShare(dependence.topShare)} of its full estimated return comes
        from the top prize.
      </span>
    </p>
  );
}

export function JackpotDependenceDetail({
  ticketPrice,
  estimatedEvFull,
  estimatedEvExTop,
}: JackpotDependenceSummaryProps) {
  const dependence = calculateJackpotDependence(
    ticketPrice,
    estimatedEvFull,
    estimatedEvExTop,
  );
  return (
    <section className="jackpot-dependence" aria-labelledby="jackpot-dependence-title">
      <div className="jackpot-dependence__heading">
        <div>
          <p className="eyebrow">JACKPOT DEPENDENCE</p>
          <h2 id="jackpot-dependence-title">
            How much estimated return depends on the top prize?
          </h2>
        </div>
        <EvidenceTag kind="estimated" />
      </div>
      {!dependence ? (
        <div className="jackpot-dependence__unavailable" role="status">
          <strong>Jackpot dependence is unavailable.</strong>
          <p>The current estimates do not support a reliable decomposition.</p>
        </div>
      ) : (
        <>
          <dl className="jackpot-dependence__facts">
            <div>
              <dt>All prizes</dt>
              <dd>{formatCentsPerDollarValue(dependence.fullReturnPerDollar)}</dd>
              <small>Full estimated long-run return</small>
            </div>
            <div>
              <dt>Without the top prize</dt>
              <dd>{formatCentsPerDollarValue(dependence.nonTopReturnPerDollar)}</dd>
              <small>Estimated return from every other tier</small>
            </div>
            <div>
              <dt>From the top prize</dt>
              <dd>{formatCentsPerDollarValue(dependence.topContributionPerDollar)}</dd>
              <small>{formatShare(dependence.topShare)} of full estimated return</small>
            </div>
          </dl>
          <div
            aria-label={`${formatShare(dependence.nonTopShare)} of estimated return comes from prizes below the top tier; ${formatShare(dependence.topShare)} comes from the top prize.`}
            className="jackpot-dependence__bar"
            role="img"
          >
            <span
              className="jackpot-dependence__bar-non-top"
              style={{ width: `${dependence.nonTopShare * 100}%` }}
            />
            <span
              className="jackpot-dependence__bar-top"
              style={{ width: `${dependence.topShare * 100}%` }}
            />
          </div>
          <div className="jackpot-dependence__key" aria-hidden="true">
            <span><i className="jackpot-dependence__swatch jackpot-dependence__swatch--non-top" />Other prize tiers</span>
            <span><i className="jackpot-dependence__swatch jackpot-dependence__swatch--top" />Top prize</span>
          </div>
          <p className="jackpot-dependence__interpretation">
            Lower dependence means more of the estimate comes from non-jackpot prizes;
            higher dependence places more of it in the rare top tier. Neither is a
            universal recommendation. These are game-wide long-run estimates, not a
            prediction for one ticket.
          </p>
        </>
      )}
    </section>
  );
}
