export type CampgroundMapPoint = {
  id: string;
  targetId: number | null;
  campgroundId: string;
  name: string;
  parkName: string;
  stateCode: string;
  latitude: number;
  longitude: number;
  active: number;
  imported: boolean;
  bookingUrl: string;
  locationPrecision?: "park" | "campground";
  locationSourceUrl?: string;
  activeResultCount: number;
  resultCount: number;
};

export type CampgroundLocation = CampgroundMapPoint & { members: CampgroundMapPoint[] };

// Recreation.gov publishes these group areas as separate facilities at the same campground.
const facilityParents: Record<string, string> = { "232510": "232466", "232509": "232465" };
const facilityNames: Record<string, string> = { "232466": "Cougar Rock Campground", "232465": "Ohanapecosh Campground" };

export function locationKey(id: string) {
  const goingToCamp = /^(gtc:[a-z]+:-?\d+):[01]$/.exec(id);
  return goingToCamp?.[1] || facilityParents[id] || id;
}

export function listingLabel(point: CampgroundMapPoint) {
  if (/^gtc:[a-z]+:-?\d+:1$/.test(point.campgroundId)) return "Roofed";
  if (/^gtc:[a-z]+:-?\d+:0$/.test(point.campgroundId)) return "Camping";
  if (facilityParents[point.campgroundId]) return "Group camping";
  return facilityNames[point.campgroundId] ? "Camping" : "Sites";
}

export function listingStatus(point: CampgroundMapPoint) {
  return !point.imported ? "Not imported" : !point.active ? "Paused target" : "Active target";
}

export function groupMapLocations(points: CampgroundMapPoint[]): CampgroundLocation[] {
  const groups = new Map<string, CampgroundMapPoint[]>();
  for (const point of points) {
    const key = `${point.parkName}\u0000${locationKey(point.campgroundId)}`;
    groups.set(key, [...(groups.get(key) || []), point]);
  }
  return [...groups.values()].map(members => {
    members.sort((a, b) => (listingLabel(a) === "Camping" ? 0 : 1) - (listingLabel(b) === "Camping" ? 0 : 1) || a.name.localeCompare(b.name));
    const primary = members[0];
    const key = locationKey(primary.campgroundId);
    const name = facilityNames[key] || (/^gtc:/.test(key) ? primary.name.replace(/\s+-\s+(Camping|Roofed)$/, "").replace(/\s*\(Cabins?\)\s*$/i, "") : primary.name);
    return { ...primary, name, members,
      active: members.some(member => member.active) ? 1 : 0,
      imported: members.every(member => member.imported),
      activeResultCount: members.reduce((total, member) => total + member.activeResultCount, 0),
      resultCount: members.reduce((total, member) => total + member.resultCount, 0) };
  });
}

export function locationWatchIds(location: CampgroundLocation) {
  return location.members.filter(member => member.targetId && member.active).map(member => member.targetId!);
}

export function toggleLocationWatchIds(selected: number[], ids: number[], limit = 500) {
  return ids.length && ids.every(id => selected.includes(id))
    ? selected.filter(id => !ids.includes(id))
    : [...new Set([...selected, ...ids])].slice(0, limit);
}

const parkPalette = ["#0f766e", "#2563a6", "#a83d65", "#84610b", "#6853a2", "#337842", "#b64a22", "#436a7e",
  "#9c3644", "#426131", "#923e96", "#137d9a", "#70533f", "#5265ad", "#777529", "#a8537e"];
export function parkColors(names: string[]) {
  return new Map([...new Set(names)].sort().map((name, index) => [name, parkPalette[index % parkPalette.length]]));
}
