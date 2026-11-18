import type { Target } from "./types";

export const MAP_WATCH_LIMIT = 500;

export function mapWatchTargets(targets: Target[], ids: number[]): Target[] {
  const active = new Map(targets.filter(target => target.active).map(target => [target.id, target]));
  return [...new Set(ids)].flatMap(id => active.has(id) ? [active.get(id)!] : []);
}

export function addMapWatchTargets(targets: Target[], selected: number[], additions: number[]): number[] {
  return mapWatchTargets(targets, [...selected, ...additions]).slice(0, MAP_WATCH_LIMIT).map(target => target.id);
}

export function toggleMapWatchTarget(targets: Target[], selected: number[], id: number): number[] {
  return selected.includes(id) ? selected.filter(value => value !== id) : addMapWatchTargets(targets, selected, [id]);
}
