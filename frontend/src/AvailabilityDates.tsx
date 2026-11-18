import { CalendarDays, LocateFixed, X } from "lucide-react";
import { availableStays } from "./availability";
import type { AvailabilityWindow } from "./types";
import { useMemo } from "react";

const stayFormatter = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
const stayLabel = (arrival: string, departure: string) => stayFormatter.formatRange(
  new Date(`${arrival}T12:00:00`), new Date(`${departure}T12:00:00`)
);

export function AvailabilityDates({ windows, arrival, departure, error, onChange, onFit, canFit }: {
  windows: AvailabilityWindow[]; arrival: string; departure: string; error: string;
  onChange: (arrival: string, departure: string) => void; onFit: () => void; canFit: boolean;
}) {
  const stays = useMemo(() => availableStays(windows), [windows]);
  const key = `${arrival}/${departure}`;
  return <div className="availability-dates" aria-label="Map availability dates">
    <label className="available-stays-field">
      <span><CalendarDays size={16} /> Available stays</span>
      <select aria-label="Available stays" value={stays.some(stay => stay.key === key) ? key : ""}
        onChange={event => { if (event.target.value) { const [start, end] = event.target.value.split("/"); onChange(start, end); } }}>
        <option value="">{stays.length ? "Choose a saved stay" : "No saved availability"}</option>
        {stays.map(stay => <option key={stay.key} value={stay.key}>
          {stayLabel(stay.arrival, stay.departure)} ({stay.campgroundCount} {stay.campgroundCount === 1 ? "campground" : "campgrounds"})
        </option>)}
      </select>
    </label>
    <label><span>Arrival / night of</span><input aria-label="Arrival or night of" type="date" value={arrival}
      aria-invalid={Boolean(error)} aria-describedby={error ? "map-date-error" : undefined}
      onChange={event => onChange(event.target.value, departure)} /></label>
    <label><span>Check-out (optional)</span><input aria-label="Map check-out" type="date" value={departure}
      min={arrival || undefined} aria-invalid={Boolean(error)} aria-describedby={error ? "map-date-error" : undefined}
      onChange={event => onChange(arrival, event.target.value)} /></label>
    <div className="availability-date-actions">
      <button className="icon-button" type="button" title="Fit matching campgrounds" aria-label="Fit matching campgrounds"
        disabled={!canFit} onClick={onFit}><LocateFixed size={18} /></button>
      <button className="icon-button" type="button" title="Clear dates" aria-label="Clear dates"
        disabled={!arrival && !departure} onClick={() => onChange("", "")}><X size={18} /></button>
    </div>
    {error && <p id="map-date-error" className="map-date-error" role="alert">{error}</p>}
  </div>;
}
