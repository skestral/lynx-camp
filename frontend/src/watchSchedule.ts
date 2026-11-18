export const weekdayOptions = [
  { value: 0, label: "Mon", name: "Monday" },
  { value: 1, label: "Tue", name: "Tuesday" },
  { value: 2, label: "Wed", name: "Wednesday" },
  { value: 3, label: "Thu", name: "Thursday" },
  { value: 4, label: "Fri", name: "Friday" },
  { value: 5, label: "Sat", name: "Saturday" },
  { value: 6, label: "Sun", name: "Sunday" }
];

export function watchArrivalDays(watch: { arrival_weekdays?: number[] | null; pattern: string }) {
  if (watch.arrival_weekdays?.length) return watch.arrival_weekdays;
  const legacyDays: Record<string, number> = {
    "thu-sat": 3, "thu-sun": 3,
    "fri-sun": 4, "fri-sat-sun": 4, "fri-mon": 4,
    "sat-sun": 5, "sat-mon": 5, "sat-sun-mon": 5, "sun-mon": 6
  };
  return [legacyDays[watch.pattern] ?? 4];
}

export function recurringStayPreview(days: readonly number[], nights: number) {
  if (!Number.isInteger(nights) || nights < 1 || nights > 14
      || days.some(day => !Number.isInteger(day) || day < 0 || day > 6)) return [];
  return [...new Set(days)].sort((a, b) => a - b).map(day => ({
    day,
    checkIn: weekdayOptions[day].name,
    checkOut: weekdayOptions[(day + nights) % 7].name,
    weeksLater: Math.floor(nights / 7)
  }));
}
