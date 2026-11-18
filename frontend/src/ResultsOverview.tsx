import { useEffect, useState, type ReactNode } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, LoaderCircle, RefreshCw, X } from "lucide-react";
import { api } from "./api";
import { childGrouping, groupKey, groupScope } from "./resultOverview";
import type { Result, ResultFilters, ResultGrouping, ResultOverviewGroup, ResultOverviewPage, ResultOverviewQuery } from "./types";

const PAGE_SIZE = 25;
const count = (value: number) => value.toLocaleString();
const date = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
const label = (group: ResultOverviewGroup) => group.campground_name || group.park_name || `${date(group.arrival_date!)} - ${date(group.departure_date!)}`;

type Props = {
  filters: ResultFilters;
  sort: ResultOverviewQuery["sort"];
  revision: number;
  disabled: boolean;
  renderResult: (result: Result) => ReactNode;
  onChanged: () => Promise<unknown>;
};

export function ResultsOverview(props: Props) {
  const [grouping, setGrouping] = useState<ResultGrouping>("park");
  const [filterKey, setFilterKey] = useState(JSON.stringify(props.filters));
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const incomingKey = JSON.stringify(props.filters);
  useEffect(() => {
    const timer = window.setTimeout(() => { setFilterKey(incomingKey); setNotice(""); setError(""); }, 250);
    return () => window.clearTimeout(timer);
  }, [incomingKey]);

  async function dismiss(filters: ResultFilters, name: string, activeCount: number) {
    if (busy || props.disabled || !activeCount || !window.confirm(
      `Dismiss ${count(activeCount)} active matches in ${name} across all pages of this filtered group? Watches and booked results are unchanged. New results discovered after this view loaded are excluded.`
    )) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api.dismissResultScope(filters);
      setNotice(`Dismissed ${count(result.dismissed_count)} matches in ${name}.`);
      await props.onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Group could not be dismissed.");
    } finally { setBusy(false); }
  }

  return <div className="results-overview">
    <label className="overview-grouping">Group by
      <select aria-label="Overview grouping" value={grouping} onChange={event => setGrouping(event.target.value as ResultGrouping)}>
        <option value="park">Park / region</option><option value="campground">Campground</option><option value="stay">Dates</option>
      </select>
    </label>
    {notice && <p role="status" className="notice">{notice}</p>}
    {error && <p role="alert" className="notice danger">{error}</p>}
    {filterKey !== incomingKey ? <p role="status">Updating overview...</p> :
      <OverviewPage key={`${filterKey}:${grouping}:${props.sort}`} filters={props.filters} level={grouping}
        sort={props.sort} revision={props.revision} disabled={props.disabled || busy}
        renderResult={props.renderResult} dismiss={dismiss} root />}
  </div>;
}

type PageProps = Omit<Props, "onChanged"> & {
  level: ResultGrouping;
  root?: boolean;
  dismiss: (scope: ResultFilters, label: string, count: number) => Promise<void>;
};

function OverviewPage({ filters, level, sort, revision, disabled, renderResult, dismiss, root = false }: PageProps) {
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [response, setResponse] = useState<{ key: string; data: ResultOverviewPage } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const queryKey = JSON.stringify({ ...filters, group_by: level, sort, limit: PAGE_SIZE, offset });
  const data = response?.key === queryKey ? response.data : null;

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setLoading(true); setError("");
    api.resultOverview(JSON.parse(queryKey), controller.signal).then(data => {
      if (!current) return;
      const lastOffset = Math.max(0, Math.floor((data.total_groups - 1) / PAGE_SIZE) * PAGE_SIZE);
      if (offset > lastOffset) { setOffset(lastOffset); return; }
      setResponse({ key: queryKey, data });
    }).catch(reason => {
      if (current) setError(reason instanceof Error ? reason.message : "Overview could not be loaded.");
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; controller.abort(); };
  }, [queryKey, revision, retry]);

  const noun = level === "items" ? "matches" : level === "stay" ? "stays" : level === "park" ? "parks / regions" : "campgrounds";
  return <div className={`overview-page ${root ? "root" : "branch"}`} aria-busy={loading}>
    {root && data && <div className="overview-totals" aria-label="Complete result totals">
      <strong>{count(data.summary.match_count)} matching results</strong>
      <span>{count(data.summary.park_count)} parks / regions</span>
      <span>{count(data.summary.campground_count)} campgrounds</span>
      <span>{count(data.summary.site_count)} distinct sites</span>
      <span>{count(data.summary.stay_count)} stays</span>
    </div>}
    {loading && <p className="overview-loading" role="status"><LoaderCircle size={16} />{data ? "Refreshing overview..." : "Loading overview..."}</p>}
    {error && <div className="notice danger" role="alert">
      <span>{error}{data ? " Previously loaded groups may be stale." : ""}</span>
      <button className="icon-button" title="Retry overview" aria-label="Retry overview" onClick={() => setRetry(value => value + 1)}><RefreshCw size={16} /></button>
    </div>}
    {data && <>
      {!data.total_groups && <p className="empty">No saved results match these filters.</p>}
      {data.groups.map(group => {
        const key = groupKey(group), expanded = Boolean(open[key]), name = label(group);
        const scope = groupScope(filters, group, data.snapshot_max_id);
        return <section className="overview-group" key={key}>
          <div className="overview-row">
            <button className="overview-expand" aria-expanded={expanded}
              onClick={() => setOpen(value => ({ ...value, [key]: !value[key] }))}>
              {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
              <span><strong>{name}</strong>
                <small>{group.campground_name && group.park_name ? `${group.park_name} · ` : ""}
                  {count(group.match_count)} matches · {count(group.site_count)} sites · {count(group.stay_count)} stays
                  {level === "park" ? ` · ${count(group.campground_count)} campgrounds` : ""}</small>
                {level !== "stay" && group.first_arrival && group.last_departure &&
                  <small>{date(group.first_arrival)} - {date(group.last_departure)}</small>}
              </span>
            </button>
            <button className="icon-only" title={`Dismiss ${count(group.active_count)} active matches in ${name}`}
              aria-label={`Dismiss group ${name}`} disabled={disabled || loading || Boolean(error) || !group.active_count}
              onClick={() => void dismiss(scope, name, group.active_count)}><X size={16} /></button>
          </div>
          {expanded && <OverviewPage filters={scope} level={childGrouping(level, scope)} sort={sort} revision={revision}
            disabled={disabled || loading || Boolean(error)} renderResult={renderResult} dismiss={dismiss} />}
        </section>;
      })}
      {level === "items" && <div className="overview-sites">{data.results.map(renderResult)}</div>}
      {data.total_groups > PAGE_SIZE && <div className="overview-pagination">
        <span>{count(offset + 1)}-{count(Math.min(offset + PAGE_SIZE, data.total_groups))} of {count(data.total_groups)} {noun}</span>
        <button className="icon-only" aria-label={`Previous ${noun}`} title={`Previous ${noun}`} disabled={loading || !offset}
          onClick={() => { setOffset(value => value - PAGE_SIZE); setOpen({}); }}><ChevronLeft size={18} /></button>
        <button className="icon-only" aria-label={`Next ${noun}`} title={`Next ${noun}`} disabled={loading || !data.has_more}
          onClick={() => { setOffset(value => value + PAGE_SIZE); setOpen({}); }}><ChevronRight size={18} /></button>
      </div>}
    </>}
  </div>;
}
