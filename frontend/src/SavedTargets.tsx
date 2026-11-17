import { useMemo, useState } from "react";
import { ChevronRight, ExternalLink, Pause, Pencil, Play, Search, Trash2 } from "lucide-react";
import type { Target } from "./types";

type Props = {
  targets: Target[];
  onActive: (target: Target, active: boolean) => void;
  onDelete: (id: number) => void;
  onEdit: (target: Target) => void;
};

export function SavedTargets({ targets, onActive, onDelete, onEdit }: Props) {
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    const grouped = new Map<string, Target[]>();
    for (const target of targets) {
      if (![target.name, target.park_name, target.state_code].join(" ").toLowerCase().includes(query.toLowerCase())) continue;
      const key = target.park_name || "Other campgrounds";
      grouped.set(key, [...(grouped.get(key) || []), target]);
    }
    return [...grouped].sort(([a], [b]) => a.localeCompare(b));
  }, [targets, query]);
  return <div className="saved-targets">
    <label className="search-box">
      <Search size={18} />
      <input aria-label="Filter saved campgrounds" placeholder="Filter saved campgrounds" value={query} onChange={(event) => setQuery(event.target.value)} />
    </label>
    {groups.length === 0 && <p className="empty">{targets.length ? "No matching campgrounds." : "No saved campgrounds."}</p>}
    {groups.map(([name, items]) => <details className="target-group" key={`${name}:${Boolean(query)}`} open={query ? true : undefined}>
      <summary><ChevronRight size={18} /><strong>{name}</strong><small>{items.length} campgrounds</small></summary>
      <div className="target-group-items">
        {items.map((target) => <article className={`saved-target-row ${target.active ? "" : "inactive"}`} key={target.id}>
          <div><strong>{target.name}</strong><small>{target.campground_id.startsWith("activenet:king:") ? "King County Parks" : target.campground_id.startsWith("camava:snoco:") ? "Snohomish County Parks" : "Recreation.gov"} &middot; {target.active ? target.last_status : "Paused"}</small></div>
          <div className="row-actions">
            <a className="icon-only quiet" href={target.booking_url} target="_blank" rel="noreferrer" title={`Open ${target.name}`}><ExternalLink size={16} /></a>
            <button className="icon-only quiet" onClick={() => onEdit(target)} title={`Edit ${target.name}`}><Pencil size={16} /></button>
            <button className="icon-only quiet" onClick={() => onActive(target, !target.active)} title={`${target.active ? "Pause" : "Resume"} ${target.name}`}>{target.active ? <Pause size={16} /> : <Play size={16} />}</button>
            <button className="icon-only quiet" onClick={() => onDelete(target.id)} title={`Delete ${target.name}`}><Trash2 size={16} /></button>
          </div>
        </article>)}
      </div>
    </details>)}
  </div>;
}
