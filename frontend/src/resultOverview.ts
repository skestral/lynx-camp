import type { ResultFilters, ResultGrouping, ResultOverviewGroup } from "./types";

export function groupScope(filters: ResultFilters, group: ResultOverviewGroup, boundary: number): ResultFilters {
  return {
    ...filters,
    ...(group.park_name !== undefined ? { park_name: group.park_name } : {}),
    ...(group.campground_id !== undefined ? { campground_id: group.campground_id } : {}),
    ...(group.arrival_date !== undefined ? { exact_arrival: group.arrival_date, exact_departure: group.departure_date } : {}),
    max_result_id: boundary
  };
}

export function childGrouping(current: ResultGrouping, scope: ResultFilters): ResultGrouping {
  if (scope.campground_id && scope.exact_arrival) return "items";
  return current === "campground" ? "stay" : "campground";
}

export function groupKey(group: ResultOverviewGroup): string {
  return JSON.stringify([group.park_name, group.campground_id, group.arrival_date, group.departure_date]);
}
