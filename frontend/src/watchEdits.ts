import type { Watch } from "./types";

export function watchChanges(members: Watch[], submitted: Record<string, unknown>): Record<string, unknown> {
  const filters = { site_type: "", loop: "", site: "", min_people: null, equipment: "", vehicle_length_ft: null, campsite_ids: [] };
  return Object.fromEntries(Object.entries(submitted).filter(([key, value]) => {
    // These fields are not editable in exact-date mode; preserve legacy values.
    if (["pattern", "nights", "arrival_weekdays"].includes(key) && submitted.mode === "specific" && members.every(watch => watch.mode === "specific")) return false;
    return !members.every(watch => {
      const current = watch[key as keyof Watch];
      if (key === "site_filters") {
        const previous = { ...filters, ...watch.site_filters };
        const next = { ...filters, ...(value as object) };
        return Object.keys(filters).every(field => JSON.stringify(previous[field as keyof typeof filters]) === JSON.stringify(next[field as keyof typeof filters]));
      }
      if (key === "alerts_enabled" || key === "cart_assist_enabled") return Boolean(current) === value;
      return JSON.stringify(current) === JSON.stringify(value);
    });
  }));
}
