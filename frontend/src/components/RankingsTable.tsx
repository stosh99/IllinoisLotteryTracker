import {
  formatLongRunReturn,
  formatMoney,
  getStrategy,
  getSupportingEv,
} from "../lib/strategies";
import type { RankingRecord } from "../types/rankings";
import { explainRank } from "../lib/decisionSupport";
import { Link, useNavigate } from "react-router-dom";
import {
  ConfidenceBadge,
  formatRemainingCount,
  primaryMetric,
  relativeWidth,
  secondaryMetric,
} from "./LeaderCards";

interface RankingsTableProps {
  rankings: RankingRecord[];
  maxMetric: number;
  filteredByPrice: boolean;
}

export function RankingsTable({
  rankings,
  maxMetric,
  filteredByPrice,
}: RankingsTableProps) {
  const navigate = useNavigate();
  const evHeader = rankings[0] ? getSupportingEv(rankings[0]).label : "Estimated return";
  const metricHeader = rankings[0]
    ? getStrategy(rankings[0].strategyKey).metricLabel
    : "Selected estimated measure";
  return (
    <div className="ranking-table-wrap" id="all-rankings-table">
      <table className="ranking-table">
        <caption className="visually-hidden">
          Ranked instant-ticket comparison with estimated metric, ticket price,
          long-run prize return, top prize, and prize-sample context.
        </caption>
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Game</th>
            <th scope="col">Price</th>
            <th scope="col">{metricHeader}</th>
            <th scope="col">{evHeader}</th>
            <th scope="col">Top prize</th>
            <th scope="col">Prize sample</th>
          </tr>
        </thead>
        <tbody>
          {rankings.map((record) => {
            const supportingEv = getSupportingEv(record);
            const rankExplanation = explainRank(record, rankings, filteredByPrice);
            return (
              <tr
                className="ranking-table__clickable-row"
                key={record.gameId}
                onClick={(event) => {
                  if (!(event.target as HTMLElement).closest("a")) {
                    navigate(`/games/${record.gameId}`);
                  }
                }}
              >
                <td data-label="Rank">
                  <span className="table-rank">
                    {filteredByPrice ? record.rankWithinTicketPrice : record.rankOverall}
                  </span>
                </td>
                <th scope="row" data-label="Game">
                  <Link
                    aria-label={`View details for ${record.gameName}`}
                    className="ranking-table__game-link"
                    to={`/games/${record.gameId}`}
                  >
                    <strong>{record.gameName}</strong>
                    <small>Game {record.gameNumber} · View prize tiers →</small>
                  </Link>
                </th>
                <td data-label="Price">
                  <span className="table-price">${record.ticketPrice}</span>
                </td>
                <td data-label={metricHeader} className="table-metric">
                  <div>
                    <strong>{primaryMetric(record)}</strong>
                    <small>{secondaryMetric(record)}</small>
                  </div>
                  <progress
                    aria-label="Relative metric within this comparison"
                    className="metric-track"
                    max="100"
                    value={relativeWidth(record.metricValue, maxMetric)}
                  />
                  <small className="table-rank-explanation">
                    {rankExplanation.comparison}
                  </small>
                </td>
                <td data-label={supportingEv.label}>
                  {formatLongRunReturn(supportingEv.value, record.ticketPrice)}
                </td>
                <td data-label="Top prize">
                  <strong>{formatMoney(record.topPrizeAmount, true)}</strong>
                  <small>
                    {formatRemainingCount(
                      record.topPrizesRemaining,
                      record.topPrizesOriginal,
                    )}
                  </small>
                </td>
                <td data-label="Prize sample">
                  <ConfidenceBadge record={record} />
                  <small>
                    {formatCoverage(record.targetCountCoverage)}
                  </small>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatCoverage(value: number): string {
  const percentage = Math.round(value * 100);
  return percentage >= 100
    ? "All matching prize counts included"
    : `${percentage}% of matching prize counts included`;
}
