import { Pause, Pencil, Play, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import type { Watch } from "./types";

type Props = {
  members: Watch[];
  selectedIds: number[];
  busy: boolean;
  onSelect: (ids: number[], selected: boolean) => void;
  onEdit: (watch: Watch, groupId: string) => void;
  onAction: (action: "pause" | "resume" | "delete", ids: number[]) => void;
  children: ReactNode;
};

export function WatchGroup({ members, selectedIds, busy, onSelect, onEdit, onAction, children }: Props) {
  const first = members[0];
  if (!first.group_id) return <>{children}</>;
  const ids = members.map((watch) => watch.id);
  const active = members.filter((watch) => watch.active && watch.target_active).length;
  const selected = ids.filter((id) => selectedIds.includes(id)).length;
  const anyEnabled = members.some((watch) => watch.active);
  const parks = [...new Set(members.map((watch) => watch.park_name).filter(Boolean))].join(", ");
  return (
    <section className="watch-group" aria-label={`Regional watch ${first.name}`}>
      <div className="watch-row">
        <label className="watch-group-label">
          <input type="checkbox" aria-label={`Select regional watch ${first.name}`} checked={selected === ids.length}
            ref={(input) => { if (input) input.indeterminate = selected > 0 && selected < ids.length; }}
            disabled={busy} onChange={(event) => onSelect(ids, event.target.checked)} />
          <span><strong>{first.name}</strong><small>{members.length} campgrounds &middot; {active} active</small>
            {first.region_scope && <small>Future imports included &middot; {first.region_scope.kind === "state" ? first.region_scope.state_code : first.region_scope.kind === "parks" ? "Selected park groups" : "Saved map area"}</small>}
            <small>{parks}</small></span>
        </label>
        <div className="row-actions">
          <button className="icon-only" disabled={busy} title={`Edit regional watch ${first.name}`} onClick={() => onEdit(first, first.group_id!)}><Pencil size={16} /></button>
          <button className="icon-only" disabled={busy} title={`${anyEnabled ? "Pause" : "Resume"} regional watch ${first.name}`} onClick={() => onAction(anyEnabled ? "pause" : "resume", ids)}>{anyEnabled ? <Pause size={16} /> : <Play size={16} />}</button>
          <button className="icon-only quiet" disabled={busy} title={`Delete regional watch ${first.name}`} onClick={() => onAction("delete", ids)}><Trash2 size={16} /></button>
        </div>
      </div>
      <details className="watch-members"><summary>Campgrounds ({members.length})</summary>{children}</details>
    </section>
  );
}
