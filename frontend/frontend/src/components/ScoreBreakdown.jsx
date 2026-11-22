import { Gauge } from "lucide-react";

import { formatScore } from "../utils/formatters";

export default function ScoreBreakdown({ breakdown, compact = false }) {
  if (!breakdown) {
    return (
      <div className="score-breakdown">
        <p className="muted">No score breakdown is available.</p>
      </div>
    );
  }
  const contributions = breakdown.contributions || [];
  const priority = breakdown.priority_policy;
  return (
    <section className={`score-breakdown ${compact ? "score-breakdown-compact" : ""}`}>
      <div className="score-breakdown-head">
        <div className="score-total">
          <span className="score-total-icon" aria-hidden="true">
            <Gauge size={18} />
          </span>
          <div>
            <span className="section-kicker">Compatibility score</span>
            <strong>{formatScore(breakdown.score)}</strong>
            <small>/ 100 final ranking value</small>
          </div>
        </div>
      </div>

      <div className="score-summary-line">
        <span>Base weighted score</span>
        <strong>{formatScore(breakdown.base_score)}</strong>
        <span>Senior policy</span>
        <strong>
          +{formatScore(breakdown.priority_adjustment ?? 0)}
        </strong>
      </div>

      {priority?.applied && (
        <div className="priority-breakdown-note">
          <span className="badge badge-priority">
            Senior priority applied
          </span>
          <p>
            A self-declared senior-priority flag is active for one passenger in
            this pair. The adjustment is capped so the final score cannot exceed
            100 and never affects eligibility.
            {breakdown.priority_bonus_capped
              ? " The requested bonus was capped at the available headroom."
              : ""}
          </p>
        </div>
      )}

      <div className="factor-list">
        {contributions.map((factor) => {
          const percent = Math.round((factor.value || 0) * 100);
          return (
            <div
              className={`factor-row ${
                factor.kind === "policy_adjustment" ? "factor-row-policy" : ""
              }`}
              key={factor.feature}
            >
              <div className="factor-row-label">
                <span>{factor.label}</span>
                <span className="factor-points">
                  +{formatScore(factor.contribution)}
                </span>
              </div>
              <div
                className="factor-track"
                role="progressbar"
                aria-label={`${factor.label}: ${percent} percent`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
              >
                <span
                  className="factor-fill"
                  style={{ width: `${percent}%` }}
                />
              </div>
              <div className="factor-meta">
                <span>
                  {factor.kind === "policy_adjustment"
                    ? "Transparent policy adjustment"
                    : `${percent}% normalized value`}
                </span>
                <span>
                  {factor.kind === "policy_adjustment"
                    ? "Not an ML feature"
                    : `Weight ${Math.round(factor.weight * 100)}%`}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <p className="score-note">{breakdown.note}</p>
    </section>
  );
}
