import Holidays from "date-holidays";
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const packagePath = require.resolve("date-holidays/package.json");
const { version } = JSON.parse(readFileSync(packagePath, "utf8"));
// Cedar's public reservation form excludes these observances from its US calendar.
const excluded = ["Valentine's Day", "St. Patrick's Day", "Tax Day", "Administrative Professionals Day", "Father's Day"];
const calendar = new Holidays("US");
const years = {};
for (let year = 2026; year <= 2035; year++) {
  years[year] = [...new Set(calendar.getHolidays(year)
    .filter((holiday) => !excluded.includes(holiday.name))
    .map((holiday) => holiday.date.slice(0, 10)))].sort();
}
const output = { source: `date-holidays ${version}`, excluded, years };
writeFileSync(new URL("../../backend/app/cedar_holidays.json", import.meta.url), JSON.stringify(output, null, 2) + "\n");
