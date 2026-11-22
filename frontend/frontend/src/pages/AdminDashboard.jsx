import {
  Activity,
  ArrowLeftRight,
  BrainCircuit,
  CheckCircle2,
  Database,
  FlaskConical,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Ticket,
  TrainFront,
  UsersRound,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { adminApi } from "../api/client";
import ErrorState from "../components/ErrorState";
import ExchangeStatus from "../components/ExchangeStatus";
import LoadingState from "../components/LoadingState";
import StatCard from "../components/StatCard";
import {
  formatDate,
  formatDateTime,
  formatScore,
  statusLabel,
} from "../utils/formatters";

const STATUS_OPTIONS = [
  "PENDING",
  "ACCEPTED_BY_BOTH",
  "AWAITING_EXTERNAL_AUTHORIZATION",
  "COMPLETED",
  "DECLINED",
  "CANCELLED",
  "EXPIRED",
];

const NEXT_ACTIONS = {
  ACCEPTED_BY_BOTH: {
    target: "AWAITING_EXTERNAL_AUTHORIZATION",
    label: "Start simulated authorization",
  },
  AWAITING_EXTERNAL_AUTHORIZATION: {
    target: "COMPLETED",
    label: "Complete simulation",
  },
};

export default function AdminDashboard() {
  const [overview, setOverview] = useState(null);
  const [exchanges, setExchanges] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [flash, setFlash] = useState("");
  const [actionId, setActionId] = useState(null);
  const [alertActionId, setAlertActionId] = useState(null);
  const [statusFilter, setStatusFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [overviewPayload, exchangePayload, alertPayload] = await Promise.all([
        adminApi.overview(),
        adminApi.exchanges({ limit: 100 }),
        adminApi.fraudAlerts({ limit: 100 }),
      ]);
      setOverview(overviewPayload);
      setExchanges(exchangePayload.items || []);
      setAlerts(alertPayload.items || []);
    } catch (err) {
      setError(err.message || "Administrator data could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filteredExchanges = useMemo(
    () =>
      statusFilter
        ? exchanges.filter((exchange) => exchange.status === statusFilter)
        : exchanges,
    [exchanges, statusFilter]
  );

  async function advance(exchange) {
    const action = NEXT_ACTIONS[exchange.status];
    if (!action) return;
    const confirmed = window.confirm(
      `${action.label} for request #${exchange.id}? This is an explicitly simulated workflow action and does not contact any railway system.`
    );
    if (!confirmed) return;
    setActionError("");
    setFlash("");
    setActionId(exchange.id);
    try {
      const payload = await adminApi.advance(exchange.id, action.target);
      setExchanges((current) =>
        current.map((item) =>
          item.id === exchange.id ? payload.exchange : item
        )
      );
      setFlash(
        `Request #${exchange.id} moved to ${statusLabel(payload.exchange.status)}. ${payload.simulation_note}`
      );
      const refreshed = await adminApi.overview();
      setOverview(refreshed);
      window.dispatchEvent(new Event("railswap:notifications-changed"));
    } catch (err) {
      setActionError(err.message || "The administrative action failed.");
    } finally {
      setActionId(null);
    }
  }

  async function resolveAlert(alert, resolution, restrictUser = false) {
    const confirmed = window.confirm(
      restrictUser
        ? `Resolve alert #${alert.id} and restrict this demo account? Existing sessions will stop working and sign-in will be blocked until an administrator reactivates the account.`
        : `Mark alert #${alert.id} as ${resolution.toLowerCase()}? No account restriction will be applied.`
    );
    if (!confirmed) return;
    setActionError("");
    setFlash("");
    setAlertActionId(alert.id);
    try {
      const payload = await adminApi.resolveFraudAlert(alert.id, {
        resolution,
        restrict_user: restrictUser,
        note: restrictUser
          ? "Administrator restricted the account after review."
          : "Administrator reviewed the synthetic demo signal.",
      });
      setAlerts((current) =>
        current.map((item) =>
          item.id === alert.id ? payload.alert : item
        )
      );
      const refreshed = await adminApi.overview();
      setOverview(refreshed);
      setFlash(
        restrictUser
          ? `Alert #${alert.id} resolved and the demo account was restricted.`
          : `Alert #${alert.id} marked ${resolution.toLowerCase()}.`
      );
    } catch (err) {
      setActionError(err.message || "The fraud alert could not be updated.");
    } finally {
      setAlertActionId(null);
    }
  }

  if (loading) return <LoadingState full label="Loading administrator console..." />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const counts = overview?.counts || {};
  const statusCounts = overview?.exchange_status_counts || {};
  const security = overview?.security || {};
  const ml = overview?.ml;
  const openAlerts = alerts.filter((alert) => alert.status === "OPEN");

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <span className="eyebrow">
            <ShieldCheck size={14} aria-hidden="true" />
            Restricted administrator workspace
          </span>
          <h2>Demo operations console</h2>
          <p>
            Aggregate system health and anonymized exchange states. Passenger
            identity and private booking details are intentionally redacted.
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={load}>
          <RefreshCcw size={16} />
          Refresh data
        </button>
      </header>

      {flash && (
        <div className="inline-notice inline-notice-success" role="status">
          <CheckCircle2 size={17} aria-hidden="true" />
          {flash}
        </div>
      )}
      {actionError && (
        <div className="inline-notice inline-notice-danger" role="alert">
          {actionError}
        </div>
      )}

      <section className="stats-grid">
        <StatCard
          icon={UsersRound}
          label="Demo users"
          value={counts.users ?? 0}
          hint={`${counts.admins ?? 0} administrator account(s)`}
        />
        <StatCard
          icon={TrainFront}
          label="Fictional trains"
          value={counts.trains ?? 0}
          hint={`${counts.journeys ?? 0} journeys`}
          tone="teal"
        />
        <StatCard
          icon={Ticket}
          label="Demo bookings"
          value={counts.bookings ?? 0}
          hint="Synthetic inventory"
          tone="violet"
        />
        <StatCard
          icon={Activity}
          label="Active exchanges"
          value={counts.active_exchanges ?? 0}
          hint={`${counts.exchange_requests ?? 0} requests in total`}
          tone="warning"
        />
        <StatCard
          icon={ShieldAlert}
          label="Open fraud alerts"
          value={security.open_fraud_alerts ?? openAlerts.length}
          hint={`${security.failed_logins_24h ?? 0} failed sign-ins in 24h`}
          tone="violet"
        />
        <StatCard
          icon={Sparkles}
          label="Priority requests"
          value={counts.senior_priority_requests ?? 0}
          hint="Self-declared senior policy"
          tone="teal"
        />
      </section>

      <div className="admin-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">
                <ArrowLeftRight size={14} aria-hidden="true" />
                Workflow state
              </span>
              <h2>Exchange distribution</h2>
            </div>
            <span className="badge badge-soft">Anonymized</span>
          </div>
          <div className="status-summary-grid">
            {STATUS_OPTIONS.map((status) => (
              <button
                type="button"
                key={status}
                className={`status-summary-item ${
                  statusFilter === status ? "status-summary-active" : ""
                }`}
                onClick={() =>
                  setStatusFilter((current) =>
                    current === status ? "" : status
                  )
                }
              >
                <span>{statusLabel(status)}</span>
                <strong>{statusCounts[status] ?? 0}</strong>
              </button>
            ))}
          </div>
          {statusFilter && (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => setStatusFilter("")}
            >
              Clear status filter
            </button>
          )}
        </section>

        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">
                <BrainCircuit size={14} aria-hidden="true" />
                Engine health
              </span>
              <h2>Matching model status</h2>
            </div>
            <span className={`badge ${ml?.available ? "badge-violet" : "badge-soft"}`}>
              {ml?.mode || "fallback"}
            </span>
          </div>
          <dl className="summary-list">
            <div>
              <dt>Artifact</dt>
              <dd>{ml?.artifact_present ? "Present" : "Not found"}</dd>
            </div>
            <div>
              <dt>Fallback</dt>
              <dd>{ml?.available ? "Not active" : "Deterministic rule engine"}</dd>
            </div>
            <div>
              <dt>Training metadata</dt>
              <dd>
                {ml?.metadata?.trained_at_utc
                  ? formatDateTime(ml.metadata.trained_at_utc)
                  : "Unavailable"}
              </dd>
            </div>
          </dl>
          {ml?.fallback_reason && (
            <div className="inline-notice inline-notice-info compact-notice">
              {ml.fallback_reason}
            </div>
          )}
          <div className="inline-notice inline-notice-warning compact-notice">
            <FlaskConical size={15} aria-hidden="true" />
            Model metrics are synthetic-label consistency results, not real
            passenger acceptance.
          </div>
        </section>
      </div>

      <section className="panel security-panel">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">
              <ShieldAlert size={14} aria-hidden="true" />
              Misuse protection
            </span>
            <h2>Fraud and abuse alerts</h2>
          </div>
          <span
            className={`badge ${
              openAlerts.length > 0 ? "badge-warning" : "badge-success"
            }`}
          >
            {openAlerts.length} open
          </span>
        </div>

        <div className="security-summary">
          <div>
            <span>Failed sign-ins / 24h</span>
            <strong>{security.failed_logins_24h ?? 0}</strong>
          </div>
          <div>
            <span>Successful sign-ins / 24h</span>
            <strong>{security.successful_logins_24h ?? 0}</strong>
          </div>
          <div>
            <span>Restricted accounts</span>
            <strong>{security.restricted_users ?? 0}</strong>
          </div>
          <div>
            <span>Limiter store</span>
            <strong>
              {security.rate_limit_store === "in_memory_single_process"
                ? "In-memory demo"
                : "Configured"}
            </strong>
          </div>
        </div>

        {alerts.length === 0 ? (
          <div className="empty-state compact-empty">
            <strong>No security alerts yet.</strong>
            <p>
              Repeated failed sign-ins, request floods, and repeat-decline
              retries create reviewable alerts.
            </p>
          </div>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Alert</th>
                  <th>Account</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id}>
                    <td>
                      <strong>{alert.alert_type}</strong>
                      <small>{alert.summary}</small>
                    </td>
                    <td>
                      {alert.user ? (
                        <>
                          <strong>{alert.user.reference}</strong>
                          <small>{alert.user.account_status}</small>
                        </>
                      ) : (
                        <span className="muted small">Unknown account</span>
                      )}
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          alert.severity === "HIGH"
                            ? "badge-danger"
                            : alert.severity === "MEDIUM"
                              ? "badge-warning"
                              : "badge-soft"
                        }`}
                      >
                        {alert.severity}
                      </span>
                    </td>
                    <td>
                      <span className="badge badge-soft">{alert.status}</span>
                    </td>
                    <td>
                      <small>{formatDateTime(alert.created_at)}</small>
                    </td>
                    <td>
                      {alert.status === "OPEN" ? (
                        <div className="alert-actions">
                          <button
                            type="button"
                            className="btn btn-secondary btn-small"
                            onClick={() => resolveAlert(alert, "RESOLVED")}
                            disabled={alertActionId === alert.id}
                          >
                            <CheckCircle2 size={14} />
                            Resolve
                          </button>
                          {alert.user && (
                            <button
                              type="button"
                              className="btn btn-danger-ghost btn-small"
                              onClick={() =>
                                resolveAlert(alert, "RESOLVED", true)
                              }
                              disabled={alertActionId === alert.id}
                            >
                              <ShieldAlert size={14} />
                              Restrict
                            </button>
                          )}
                        </div>
                      ) : (
                        <span className="muted small">Reviewed</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="panel-note">
          {security.note ||
            "Alerts use hashed sign-in identifiers and never expose display names, raw emails, IP addresses, or ticket data."}
        </p>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">
              <Database size={14} aria-hidden="true" />
              Request operations
            </span>
            <h2>Anonymized exchange requests</h2>
          </div>
          <span className="badge badge-soft">
            {filteredExchanges.length} shown
          </span>
        </div>

        <div className="inline-notice inline-notice-info">
          <ShieldCheck size={16} aria-hidden="true" />
          {overview?.privacy_note}
        </div>

        {filteredExchanges.length === 0 ? (
          <div className="empty-state compact-empty">
            <strong>No requests match this filter.</strong>
            <p>Clear the status filter or seed the demo database.</p>
          </div>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Request</th>
                  <th>Journey</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th>Score</th>
                  <th>Updated</th>
                  <th>Simulated action</th>
                </tr>
              </thead>
              <tbody>
                {filteredExchanges.map((exchange) => {
                  const action = NEXT_ACTIONS[exchange.status];
                  return (
                    <tr key={exchange.id}>
                      <td>
                        <strong>#{exchange.id}</strong>
                        <small>Passenger data redacted</small>
                      </td>
                      <td>
                        <strong>{exchange.train_number}</strong>
                        <small>
                          {exchange.source} → {exchange.destination} ·{" "}
                          {formatDate(exchange.journey_date)}
                        </small>
                      </td>
                      <td>
                        <ExchangeStatus status={exchange.status} />
                      </td>
                      <td>
                        {exchange.priority_tier === "SENIOR_PRIORITY" ? (
                          <span className="badge badge-priority">
                            <Sparkles size={12} aria-hidden="true" />
                            Senior
                          </span>
                        ) : (
                          <span className="muted small">Standard</span>
                        )}
                      </td>
                      <td>{formatScore(exchange.compatibility_score)}</td>
                      <td>
                        <small>{formatDateTime(exchange.updated_at)}</small>
                      </td>
                      <td>
                        {action ? (
                          <button
                            type="button"
                            className="btn btn-secondary btn-small"
                            onClick={() => advance(exchange)}
                            disabled={actionId === exchange.id}
                          >
                            {action.target === "COMPLETED" ? (
                              <CheckCircle2 size={14} />
                            ) : (
                              <ShieldCheck size={14} />
                            )}
                            {actionId === exchange.id ? "Working..." : action.label}
                          </button>
                        ) : (
                          <span className="muted small">No admin action</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="panel-note">
          Administrator actions only advance the explicitly simulated external
          authorization gate. They do not represent official railway approval and do
          not modify any real reservation.
        </p>
      </section>
    </div>
  );
}
