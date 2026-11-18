import { Download, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ProviderDiagnostics as DiagnosticReport, SourceDefinition } from "./types";

export function ProviderDiagnostics({ sourceId, sources, onSourceChange }: {
  sourceId: string; sources: SourceDefinition[]; onSourceChange: (id: string) => void;
}) {
  const [report, setReport] = useState<DiagnosticReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const mounted = useRef(false);

  const refresh = useCallback(async (download = false) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    try {
      const data = await api.sourceDiagnostics(sourceId);
      if (!mounted.current) return;
      setReport(data);
      setError("");
      if (download) {
        const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `campfinder-${sourceId}-diagnostics.json`;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : "Diagnostics could not be refreshed.");
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }, [sourceId]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 30000);
    return () => { mounted.current = false; window.clearInterval(timer); };
  }, [refresh]);

  return (
    <section className="panel provider-diagnostics" aria-label="Provider diagnostics" aria-busy={busy}>
      <div className="panel-heading">
        <div>
          <h2>Provider Diagnostics</h2>
          <p>{report?.provider || sources.find(source => source.id === sourceId)?.name} &middot; Last {report?.history_limit ?? 30} HTTP requests</p>
        </div>
        <div className="panel-action-row inline">
          <button className="icon-button" onClick={() => void refresh()} disabled={busy} title="Refresh saved diagnostics" aria-label="Refresh saved diagnostics">
            <RefreshCw size={17} className={busy ? "spinning" : ""} />
          </button>
          <button className="icon-button" onClick={() => void refresh(true)} disabled={busy || !report} title="Download redacted diagnostics" aria-label="Download redacted diagnostics">
            <Download size={17} />
          </button>
        </div>
      </div>
      <label>Provider
        <select value={sourceId} onChange={event => onSourceChange(event.target.value)}>
          {sources.filter(source => ["goingtocamp", "usedirect"].includes(source.source_type)).map(source => (
            <option key={source.id} value={source.id}>{source.name}</option>
          ))}
        </select>
      </label>
      {error && <p role="alert" className="diagnostics-error">{error} {report ? "Previously loaded diagnostics may be stale." : ""}</p>}
      {report && <div className="diagnostics-connection">
        <strong>{report.connection.state.split("_").join(" ")}</strong>
        <span>{report.connection.message || (report.connection.checked_at
          ? `Last checked ${new Date(report.connection.checked_at).toLocaleString()}`
          : "No provider access check recorded.")}</span>
        {report.connection.retry_at && <span>Cooldown until {new Date(report.connection.retry_at).toLocaleString()}</span>}
      </div>}
      {!report && !error && <p className="empty" role="status">Loading diagnostics...</p>}
      {report?.records.length === 0 && <p className="empty">No HTTP diagnostics recorded yet.</p>}
      <div className="diagnostics-history">
        {report?.records.map(record => (
          <details className="diagnostics-entry" key={record.id}>
            <summary>
              <span className={`status ${record.outcome === "json_response" ? "success" : "danger"}`}>{record.status ?? "Network error"}</span>
              <strong>{record.method} {record.endpoint}</strong>
              <span>{record.outcome.split("_").join(" ")}</span>
              <time dateTime={record.recorded_at}>{new Date(record.recorded_at).toLocaleString()}</time>
              <span>{record.elapsed_ms} ms</span>
            </summary>
            <dl className="diagnostics-facts">
              <div><dt>Response</dt><dd>{record.content_type} &middot; {record.response_bytes.toLocaleString()} bytes</dd></div>
              <div><dt>Server family</dt><dd>{record.server_family}</dd></div>
              <div><dt>Body classifications</dt><dd>{record.markers.join(", ") || "None detected"}</dd></div>
              <div><dt>Transport</dt><dd>{record.transport_error || "HTTP response received"}</dd></div>
              <div><dt>Environment</dt><dd>Proxy: {record.proxy_configured ? "configured" : "not detected"}; exclusions: {record.no_proxy_configured ? "configured" : "not detected"}; custom CA: {record.custom_ca_configured ? "configured" : "not detected"}</dd></div>
              <div><dt>Headers present</dt><dd>{[record.via_present && "Via", record.cache_header_present && "X-Cache", record.azure_edge_header_present && "X-Azure-Ref", record.set_cookie_present && "Set-Cookie", record.authenticate_header_present && "WWW-Authenticate"].filter(Boolean).join(", ") || "None of the tracked headers"}</dd></div>
              <div><dt>Redirect</dt><dd>{record.redirect}</dd></div>
            </dl>
            <pre aria-label="Request parameters and identifiers">{JSON.stringify({ query: record.query, request_ids: record.request_ids }, null, 2)}</pre>
          </details>
        ))}
      </div>
    </section>
  );
}
