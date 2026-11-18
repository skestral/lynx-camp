export function coordinatePair(latitude: unknown, longitude: unknown): [number, number] | null {
  const values = [latitude, longitude];
  if (values.some(value => (typeof value !== "number" && typeof value !== "string") || String(value).trim() === "")) return null;
  const lat = Number(latitude), lon = Number(longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180 || (lat === 0 && lon === 0)) return null;
  return [lat, lon];
}
