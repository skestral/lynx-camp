import type { AvailabilityWindow } from "./types";
import type { Stay } from "./availability";

export type MapAvailabilityPreview = {
  matchCount: number;
  stays: AvailabilityWindow[];
  lastSeenAt: string;
};

export function mapAvailabilityPreviews(windows: AvailabilityWindow[], stay: Stay | null) {
  const previews = new Map<string, MapAvailabilityPreview>();
  for (const window of windows) {
    if (stay && (window.arrival_date > stay.arrival || window.departure_date < stay.departure)) continue;
    const preview = previews.get(window.campground_id) || { matchCount: 0, stays: [], lastSeenAt: "" };
    preview.matchCount += window.match_count;
    preview.stays.push(window);
    if (window.last_seen_at > preview.lastSeenAt) preview.lastSeenAt = window.last_seen_at;
    previews.set(window.campground_id, preview);
  }
  for (const preview of previews.values()) {
    preview.stays.sort((a, b) => a.arrival_date.localeCompare(b.arrival_date) || a.departure_date.localeCompare(b.departure_date));
  }
  return previews;
}

const escape = (value: string) => value.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]!));
const dateLabel = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

export function combineMapPreviews(previews: MapAvailabilityPreview[]): MapAvailabilityPreview | undefined {
  if (!previews.length) return undefined;
  const stays = new Map<string, AvailabilityWindow>();
  for (const preview of previews) for (const stay of preview.stays) {
    const key = `${stay.arrival_date}/${stay.departure_date}`;
    const current = stays.get(key);
    stays.set(key, { ...stay, match_count: stay.match_count + (current?.match_count || 0) });
  }
  return { matchCount: previews.reduce((total, value) => total + value.matchCount, 0),
    lastSeenAt: previews.map(value => value.lastSeenAt).sort().pop() || "",
    stays: [...stays.values()].sort((a, b) => a.arrival_date.localeCompare(b.arrival_date) || a.departure_date.localeCompare(b.departure_date)) };
}

function externalLink(label: string, value: string | undefined) {
  if (!value) return "";
  try {
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return "";
    return `<a href="${escape(url.href)}" target="_blank" rel="noopener noreferrer" title="${escape(label)} (opens in a new tab)">${escape(label)}</a>`;
  } catch {
    return "";
  }
}

export function campgroundPreviewHtml(
  campground: { name: string; parkName: string; stateCode: string; locationPrecision?: "park" | "campground" },
  preview: MapAvailabilityPreview | undefined,
  context: { stay: Stay | null; loaded: boolean; error: boolean; mapsUrl?: string; websiteUrl?: string;
    listings?: { label: string; status: string; url: string }[] }
) {
  const matches = preview?.matchCount || 0;
  const dates = context.stay ? `<div class="map-preview-selection"><span>Check-in <b>${dateLabel(context.stay.arrival)}</b></span><span>Check-out <b>${dateLabel(context.stay.departure)}</b></span></div>` : "";
  const stays = preview?.stays || [];
  const status = !context.loaded ? "Availability not loaded" : matches ? `${matches.toLocaleString()} saved ${matches === 1 ? "match" : "matches"}` : "No saved availability";
  const lastSeen = preview?.lastSeenAt ? new Date(preview.lastSeenAt) : null;
  const listings = context.listings || [];
  const links = externalLink("Google Maps", context.mapsUrl) + (listings.length > 1
    ? listings.map(listing => externalLink(`${listing.label} website`, listing.url)).join("") : externalLink("Website", context.websiteUrl));
  return `<div class="map-preview-heading">${escape(campground.name)}</div>` +
    `<div class="map-preview-meta">${escape([campground.parkName, campground.stateCode].filter(Boolean).join(" / "))}</div>` +
    (campground.locationPrecision === "park" ? `<div class="map-preview-meta">Park reference location</div>` : "") +
    (listings.length ? `<div class="map-preview-meta">${listings.map(listing => `${escape(listing.label)}: ${escape(listing.status)}`).join("<br>")}</div>` : "") +
    (links ? `<div class="map-preview-links">${links}</div>` : "") +
    `<div class="map-preview-count">${status}</div>` +
    (lastSeen && Number.isFinite(lastSeen.getTime()) ? `<div class="map-preview-updated">Last seen ${escape(lastSeen.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))}</div>` : "") +
    dates +
    (stays.length ? `<div class="map-preview-stays"><div class="map-preview-stay-heading"><span>Saved stays</span><span>Matches</span></div>${stays.slice(0, 3).map(stay =>
      `<div><span>${dateLabel(stay.arrival_date)} - ${dateLabel(stay.departure_date)}</span><b>${stay.match_count.toLocaleString()}</b></div>`
    ).join("")}${stays.length > 3 ? `<small>+${stays.length - 3} more date pairs</small>` : ""}</div>` : "") +
    (context.error ? `<div class="map-preview-warning">Last availability refresh failed. Saved counts may be stale.</div>` : "");
}

const MAP_MARGIN = 8;
const ZOOM_CLEARANCE = 88;
const ATTRIBUTION_CLEARANCE = 28;
const MARKER_GAP = 18;

export function previewHeightLimit(point: { y: number }, map: { y: number }) {
  return Math.max(60, point.y - ZOOM_CLEARANCE - MARKER_GAP,
    map.y - Math.max(ZOOM_CLEARANCE, point.y + MARKER_GAP) - ATTRIBUTION_CLEARANCE);
}

export function previewOffset(point: { x: number; y: number }, map: { x: number; y: number }, card: { width: number; height: number }) {
  const clamp = (value: number, half: number, size: number) => Math.max(half + MAP_MARGIN, Math.min(value, size - half - MAP_MARGIN));
  const above = point.y - card.height - MARKER_GAP >= ZOOM_CLEARANCE;
  return {
    x: clamp(point.x, card.width / 2, map.x) - point.x,
    y: above
      ? Math.min(point.y - MARKER_GAP, map.y - ATTRIBUTION_CLEARANCE) - card.height / 2 - point.y
      : Math.max(ZOOM_CLEARANCE, point.y + MARKER_GAP) + card.height / 2 - point.y
  };
}
