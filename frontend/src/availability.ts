import type { AvailabilityWindow } from "./types";

export type Stay = { arrival: string; departure: string };

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function selectedStay(arrival: string, departure: string): { stay: Stay | null; error: string } {
  if (!arrival && !departure) return { stay: null, error: "" };
  if (!validDate(arrival)) return { stay: null, error: "Choose a valid arrival date." };
  if (!departure) {
    const next = new Date(`${arrival}T00:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    departure = next.toISOString().slice(0, 10);
  }
  if (!validDate(departure) || departure <= arrival) {
    return { stay: null, error: "Check-out must be after arrival." };
  }
  return { stay: { arrival, departure }, error: "" };
}

export function coversStay(window: Pick<AvailabilityWindow, "arrival_date" | "departure_date">, stay: Stay) {
  return window.arrival_date <= stay.arrival && window.departure_date >= stay.departure;
}

export function availabilityCounts(windows: AvailabilityWindow[], stay: Stay) {
  const counts = new Map<string, number>();
  for (const window of windows) {
    if (coversStay(window, stay)) {
      counts.set(window.campground_id, (counts.get(window.campground_id) || 0) + window.match_count);
    }
  }
  return counts;
}

export function availableStays(windows: AvailabilityWindow[]) {
  const stays = new Map<string, { stay: Stay; campgrounds: Set<string> }>();
  for (const window of windows) {
    const key = `${window.arrival_date}/${window.departure_date}`;
    const entry = stays.get(key) || {
      stay: { arrival: window.arrival_date, departure: window.departure_date }, campgrounds: new Set<string>()
    };
    entry.campgrounds.add(window.campground_id);
    stays.set(key, entry);
  }
  return [...stays.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => ({
    key, ...entry.stay, campgroundCount: entry.campgrounds.size
  }));
}
