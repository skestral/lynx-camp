import {
  Activity,
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Download,
  ExternalLink,
  Filter,
  ListChecks,
  MapPin,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings,
  TentTree,
  Timer,
  Trash2,
  Upload,
  Waves,
  X
} from "lucide-react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { RESULTS_LIMIT, api } from "./api";
import type {
  CartAssistStatus,
  CartAttempt,
  CartAttemptStatus,
  ConfigBackup,
  NotificationEvent,
  NotificationStatus,
  PresetDiscoveryResult,
  PresetPack,
  ReleaseWindowProfileResult,
  Result,
  ResultSummary,
  ScanRun,
  SearchSuggestion,
  Target,
  Watch
} from "./types";

type LoadState = "idle" | "loading" | "error";

type ResultView = "active" | "all" | Result["status"];
type ResultSort = "newest" | "arrival" | "park";
type SetupDrawerMode = "targets" | "watches";
type ScanProgress = {
  title: string;
  detail: string;
};

type ParkSummary = {
  parkName: string;
  stateCodes: string;
  targetCount: number;
  activeTargetCount: number;
  resultCount: number;
  activeResultCount: number;
  latitude: number;
  longitude: number;
  campgrounds: CampgroundMapPoint[];
};

type CampgroundMapPoint = {
  id: string;
  campgroundId: string;
  name: string;
  parkName: string;
  stateCode: string;
  latitude: number;
  longitude: number;
  active: number;
  imported: boolean;
  activeResultCount: number;
};

type ResultStayGroup = {
  id: string;
  label: string;
  count: number;
  activeCount: number;
  results: Result[];
};

type ResultCampgroundGroup = {
  id: string;
  name: string;
  count: number;
  activeCount: number;
  stays: ResultStayGroup[];
};

type ResultParkGroup = {
  id: string;
  name: string;
  count: number;
  activeCount: number;
  campgrounds: ResultCampgroundGroup[];
};

const addDays = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
};

const weekdayOptions = [
  { value: 0, label: "Mon" },
  { value: 1, label: "Tue" },
  { value: 2, label: "Wed" },
  { value: 3, label: "Thu" },
  { value: 4, label: "Fri" },
  { value: 5, label: "Sat" },
  { value: 6, label: "Sun" }
];

const resultViewOptions: Array<{ value: ResultView; label: string }> = [
  { value: "active", label: "Active" },
  { value: "all", label: "All" },
  { value: "available", label: "Available" },
  { value: "opened", label: "Opened" },
  { value: "booked", label: "Booked" },
  { value: "dismissed", label: "Dismissed" }
];

const resultSortOptions: Array<{ value: ResultSort; label: string }> = [
  { value: "newest", label: "Newest" },
  { value: "arrival", label: "Arrival date" },
  { value: "park", label: "Park" }
];

const mapTileUrl = import.meta.env.VITE_CAMPFINDER_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const mapTileAttribution =
  import.meta.env.VITE_CAMPFINDER_TILE_ATTRIBUTION ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function weekdayLabel(days: number[]) {
  return [...days]
    .sort((a, b) => a - b)
    .map((day) => weekdayOptions.find((option) => option.value === day)?.label || "")
    .filter(Boolean)
    .join("/");
}

function patternKey(days: number[], nights: number) {
  return `${[...days].sort((a, b) => a - b).join("-")}-${nights}n`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "Not yet";
  const dateOnly = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const date = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(value);
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function isActiveAvailability(result: Result) {
  return Boolean(result.active) && !["booked", "dismissed"].includes(result.status);
}

function statusTone(status: string) {
  if (status.startsWith("error") || status === "failed") return "danger";
  if (status === "needs_credentials" || status === "cooldown" || status === "manual_required") return "warning";
  if (status === "available" || status === "booked") return "success";
  if (status === "clear" || status === "opened" || status === "running") return "calm";
  return "quiet";
}

function cartAssistCredentialLabel(status: CartAssistStatus | null) {
  if (!status) return "credentials pending";
  if (status.credential_source === "none") return "credentials not configured";
  return `credentials from ${status.credential_source}`;
}

function cartAssistGuardLabel(status: CartAssistStatus | null) {
  if (!status) return "loading";
  if (status.guard_state === "needs_credentials") return "needs credentials";
  if (status.guard_state === "cooldown") return "cooling down";
  return status.guard_state;
}

function cartAssistGuardTone(status: CartAssistStatus | null) {
  if (!status) return "quiet";
  if (status.guard_state === "ready") return "success";
  if (status.guard_state === "needs_credentials" || status.guard_state === "cooldown") return "warning";
  return "quiet";
}

function cartAssistGuardSummary(status: CartAssistStatus | null) {
  if (!status) return "Waiting for server status.";
  const attemptLabel = status.max_attempts_per_scan === 1 ? "attempt" : "attempts";
  const base = `Cooldown ${status.cooldown_minutes} min; ${status.max_attempts_per_scan} ${attemptLabel} per scan; ${cartAssistCredentialLabel(status)}`;
  if (status.guard_state === "cooldown") {
    const activeLabel = status.recent_actionable_attempt_count === 1 ? "active checkout task" : "active checkout tasks";
    const nextWindow =
      status.cooldown_remaining_minutes > 0
        ? `next attempt in about ${status.cooldown_remaining_minutes} min`
        : "next attempt almost ready";
    return `${base}; ${status.recent_actionable_attempt_count} ${activeLabel}; ${nextWindow}.`;
  }
  if (status.guard_state === "ready") return `${base}; guard ready.`;
  if (status.guard_state === "needs_credentials") return `${base}; add credentials before high-priority holds can be prepared.`;
  return `${base}; server guard is off.`;
}

function filterSummary(filters: Watch["site_filters"]) {
  const parts = [
    filters.site_type ? `type ${filters.site_type}` : "",
    filters.loop ? `loop ${filters.loop}` : "",
    filters.site ? `site ${filters.site}` : "",
    filters.min_people ? `${filters.min_people}+ people` : ""
  ].filter(Boolean);
  return parts.length ? `filters: ${parts.join(", ")}` : "no site filters";
}

function bookingBrief(result: Result) {
  return [
    "Camp Finder booking details",
    `Campground: ${result.campground_name}`,
    `Watch: ${result.watch_name}`,
    `Site: ${result.site}`,
    result.loop ? `Loop: ${result.loop}` : "",
    result.campsite_type ? `Type: ${result.campsite_type}` : "",
    `Arrival: ${formatDate(result.arrival_date)}`,
    `Departure: ${formatDate(result.departure_date)}`,
    `Recreation.gov: ${result.booking_url}`,
  ]
    .filter(Boolean)
    .join("\n");
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    };
    return entities[character] || character;
  });
}

async function writeClipboardText(text: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall back for embedded browsers or local contexts that expose the API but deny writes.
    }
  }
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed";
  textArea.style.left = "-9999px";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  const copied = document.execCommand("copy");
  textArea.remove();
  if (!copied) {
    throw new Error("Clipboard copy was not allowed by this browser.");
  }
}

export default function App() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [presets, setPresets] = useState<PresetPack[]>([]);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [results, setResults] = useState<Result[]>([]);
  const [resultSummary, setResultSummary] = useState<ResultSummary>({ total_count: 0, active_count: 0 });
  const [scanRuns, setScanRuns] = useState<ScanRun[]>([]);
  const [notifications, setNotifications] = useState<NotificationEvent[]>([]);
  const [notificationStatus, setNotificationStatus] = useState<NotificationStatus>({ channels: [] });
  const [cartAssistStatus, setCartAssistStatus] = useState<CartAssistStatus | null>(null);
  const [cartAttempts, setCartAttempts] = useState<CartAttempt[]>([]);
  const [cartAssistServerEnabled, setCartAssistServerEnabled] = useState(false);
  const [cartAssistCooldown, setCartAssistCooldown] = useState("30");
  const [cartAssistMaxAttempts, setCartAssistMaxAttempts] = useState("1");
  const [cartAssistUsername, setCartAssistUsername] = useState("");
  const [cartAssistPassword, setCartAssistPassword] = useState("");
  const [cartAssistConfigDirty, setCartAssistConfigDirty] = useState(false);
  const [cartAssistConfigBusy, setCartAssistConfigBusy] = useState<"save" | "clear" | null>(null);
  const [cartAttemptBusyId, setCartAttemptBusyId] = useState<number | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [searching, setSearching] = useState(false);
  const [editingWatchId, setEditingWatchId] = useState<number | null>(null);
  const [watchName, setWatchName] = useState("");
  const [watchMode, setWatchMode] = useState<"weekend" | "specific">("weekend");
  const [watchTarget, setWatchTarget] = useState("");
  const [cartAssistEnabled, setCartAssistEnabled] = useState(false);
  const [selectedWeekdays, setSelectedWeekdays] = useState<number[]>([4]);
  const [watchNights, setWatchNights] = useState(2);
  const [windowStart, setWindowStart] = useState(addDays(1));
  const [windowEnd, setWindowEnd] = useState(addDays(180));
  const [specificArrival, setSpecificArrival] = useState(addDays(30));
  const [specificDeparture, setSpecificDeparture] = useState(addDays(32));
  const [scanBusyId, setScanBusyId] = useState<number | null>(null);
  const [scanAllBusy, setScanAllBusy] = useState(false);
  const [testNotifyBusy, setTestNotifyBusy] = useState(false);
  const [resultBusyId, setResultBusyId] = useState<number | null>(null);
  const [resultGroupOpen, setResultGroupOpen] = useState<Record<string, boolean>>({});
  const [clearResultsBusy, setClearResultsBusy] = useState(false);
  const [resultView, setResultView] = useState<ResultView>("active");
  const [resultSort, setResultSort] = useState<ResultSort>("arrival");
  const [resultQuery, setResultQuery] = useState("");
  const [selectedResultIds, setSelectedResultIds] = useState<number[]>([]);
  const [bulkResultBusy, setBulkResultBusy] = useState<Result["status"] | null>(null);
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
  const [bookingPreview, setBookingPreview] = useState<{ site: string; text: string } | null>(null);
  const [importingPackId, setImportingPackId] = useState<string | null>(null);
  const [discoveringPackId, setDiscoveringPackId] = useState<string | null>(null);
  const [sourceImportingPackId, setSourceImportingPackId] = useState<string | null>(null);
  const [presetDiscovery, setPresetDiscovery] = useState<Record<string, PresetDiscoveryResult>>({});
  const [configBusy, setConfigBusy] = useState<"export" | "import" | null>(null);
  const [backupFile, setBackupFile] = useState<File | null>(null);
  const [targetSettingsId, setTargetSettingsId] = useState("");
  const [targetName, setTargetName] = useState("");
  const [targetParkName, setTargetParkName] = useState("");
  const [targetStateCode, setTargetStateCode] = useState("");
  const [targetBookingUrl, setTargetBookingUrl] = useState("");
  const [targetReleaseWindowValue, setTargetReleaseWindowValue] = useState(6);
  const [targetReleaseWindowUnit, setTargetReleaseWindowUnit] = useState<Target["release_window_unit"]>("Months");
  const [targetReleaseTime, setTargetReleaseTime] = useState("07:00");
  const [targetTimezone, setTargetTimezone] = useState("America/Los_Angeles");
  const [targetPollInterval, setTargetPollInterval] = useState(10);
  const [detectReleaseBusy, setDetectReleaseBusy] = useState(false);
  const [profileBusy, setProfileBusy] = useState(false);
  const [releaseProfiles, setReleaseProfiles] = useState<ReleaseWindowProfileResult | null>(null);
  const [filterSiteType, setFilterSiteType] = useState("");
  const [filterLoop, setFilterLoop] = useState("");
  const [filterSite, setFilterSite] = useState("");
  const [filterMinPeople, setFilterMinPeople] = useState("");
  const [setupDrawerOpen, setSetupDrawerOpen] = useState(false);
  const [setupDrawerMode, setSetupDrawerMode] = useState<SetupDrawerMode>("targets");
  const mapElementRef = useRef<HTMLDivElement | null>(null);
  const leafletMapRef = useRef<L.Map | null>(null);
  const markerLayerRef = useRef<L.LayerGroup | null>(null);

  const activeTargets = targets.filter((target) => target.active);
  const activeWatches = watches.filter((watch) => watch.active && watch.target_active);
  const activeResults = results.filter(isActiveAvailability);
  const loadedResultCount = results.length;
  const totalResultCount = resultSummary.total_count || loadedResultCount;
  const activeResultCount = resultSummary.active_count || activeResults.length;
  const resultListTruncated = totalResultCount > loadedResultCount;
  const selectedResultSet = useMemo(() => new Set(selectedResultIds), [selectedResultIds]);
  const selectedResults = useMemo(
    () => results.filter((result) => selectedResultSet.has(result.id)),
    [results, selectedResultSet]
  );
  const cartAttemptByResultId = useMemo(
    () => new Map(cartAttempts.map((attempt) => [attempt.result_id, attempt])),
    [cartAttempts]
  );
  const filteredResults = useMemo(() => {
    const query = resultQuery.trim().toLowerCase();
    const filtered = results.filter((result) => {
      const matchesView =
        resultView === "all"
          ? true
          : resultView === "active"
            ? isActiveAvailability(result)
            : result.status === resultView;
      if (!matchesView) return false;
      if (!query) return true;
      return [
        result.park_name,
        result.target_name,
        result.campground_name,
        result.site,
        result.loop,
        result.campsite_type,
        result.watch_name,
        result.arrival_date,
        result.departure_date
      ]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(query));
    });

    return [...filtered].sort((a, b) => {
      if (resultSort === "arrival") {
        const arrival = a.arrival_date.localeCompare(b.arrival_date);
        if (arrival !== 0) return arrival;
        return a.site.localeCompare(b.site);
      }
      if (resultSort === "park") {
        const park = (a.park_name || a.target_name).localeCompare(b.park_name || b.target_name);
        if (park !== 0) return park;
        const campground = a.campground_name.localeCompare(b.campground_name);
        if (campground !== 0) return campground;
        return a.arrival_date.localeCompare(b.arrival_date);
      }
      return b.discovered_at.localeCompare(a.discovered_at);
    });
  }, [results, resultQuery, resultSort, resultView]);
  const visibleResultIds = useMemo(() => filteredResults.map((result) => result.id), [filteredResults]);
  const allVisibleResultsSelected =
    visibleResultIds.length > 0 && visibleResultIds.every((id) => selectedResultSet.has(id));
  const runningScan = scanRuns.find((run) => run.status === "running" && !run.finished_at);
  const scanInProgress = scanAllBusy || scanBusyId !== null || Boolean(runningScan);
  const latestScan = scanRuns.find((run) => run.status !== "running") || scanRuns[0];
  const runningScanRuns = scanRuns.filter((run) => run.status === "running" && !run.finished_at);
  const activeScanTitle = runningScan
    ? `Scanning ${runningScan.watch_name}`
    : scanProgress?.title || (latestScan ? `Last scan: ${latestScan.watch_name}` : "No scans yet");
  const activeScanDetail = runningScan ? (
    <>
      {runningScan.target_name} &middot; started {formatDateTime(runningScan.started_at)}
    </>
  ) : scanProgress?.detail ? (
    scanProgress.detail
  ) : latestScan ? (
    <>
      {latestScan.target_name} &middot; {latestScan.candidate_count} stays &middot; {latestScan.available_count} matches &middot;{" "}
      {formatDateTime(latestScan.finished_at || latestScan.started_at)}
    </>
  ) : (
    "Ready when watches are added."
  );
  const watchSummary = `${activeWatches.length} active watch${activeWatches.length === 1 ? "" : "es"}`;
  const latestRelease = useMemo(
    () =>
      activeWatches
        .flatMap((watch) =>
          watch.release_hints.map((hint) => ({
            ...hint,
            watch: watch.name,
            target: watch.target_name
          }))
        )
        .sort((a, b) => {
          if (a.release_status !== b.release_status) {
            return a.release_status === "upcoming" ? -1 : 1;
          }
          return a.release_status === "upcoming"
            ? a.release_at.localeCompare(b.release_at)
            : a.arrival_date.localeCompare(b.arrival_date);
        })
        .slice(0, 4),
    [activeWatches]
  );
  const parkSummaries = useMemo<ParkSummary[]>(() => {
    const summaries = new Map<
      string,
      Omit<ParkSummary, "stateCodes" | "latitude" | "longitude"> & { stateCodeSet: Set<string> }
    >();
    const resultCountsByCampground = new Map<string, { resultCount: number; activeResultCount: number }>();

    for (const result of results) {
      const current = resultCountsByCampground.get(result.campground_id) || {
        resultCount: 0,
        activeResultCount: 0
      };
      current.resultCount += 1;
      if (isActiveAvailability(result)) current.activeResultCount += 1;
      resultCountsByCampground.set(result.campground_id, current);
    }

    const savedTargetsByCampground = new Map(targets.map((target) => [target.campground_id, target]));
    const mapTargets = new Map<string, Target | PresetPack["targets"][number]>();
    for (const pack of presets) {
      for (const target of pack.targets) {
        if (!mapTargets.has(target.campground_id)) {
          mapTargets.set(target.campground_id, target);
        }
      }
    }
    for (const target of targets) {
      mapTargets.set(target.campground_id, target);
    }

    for (const sourceTarget of mapTargets.values()) {
      const savedTarget = savedTargetsByCampground.get(sourceTarget.campground_id);
      const parkName = savedTarget?.park_name || sourceTarget.park_name || "Unassigned park";
      const summary =
        summaries.get(parkName) ||
        {
          parkName,
          stateCodeSet: new Set<string>(),
          targetCount: 0,
          activeTargetCount: 0,
          resultCount: 0,
          activeResultCount: 0,
          campgrounds: []
        };
      summary.targetCount += 1;
      if (savedTarget?.active) summary.activeTargetCount += 1;
      const stateCode = savedTarget?.state_code || sourceTarget.state_code || "";
      if (stateCode) summary.stateCodeSet.add(stateCode);
      const latitude = Number(savedTarget?.latitude ?? sourceTarget.latitude);
      const longitude = Number(savedTarget?.longitude ?? sourceTarget.longitude);
      const resultCounts = resultCountsByCampground.get(sourceTarget.campground_id) || {
        resultCount: 0,
        activeResultCount: 0
      };
      if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
        summary.campgrounds.push({
          id: sourceTarget.campground_id,
          campgroundId: sourceTarget.campground_id,
          name: savedTarget?.name || sourceTarget.name,
          parkName,
          stateCode,
          latitude,
          longitude,
          active: savedTarget?.active || 0,
          imported: Boolean(savedTarget),
          activeResultCount: resultCounts.activeResultCount
        });
      }
      summaries.set(parkName, summary);
    }

    for (const result of results) {
      const parkName = result.park_name || result.target_name || "Unassigned park";
      const summary =
        summaries.get(parkName) ||
        {
          parkName,
          stateCodeSet: new Set<string>(),
          targetCount: 0,
          activeTargetCount: 0,
          resultCount: 0,
          activeResultCount: 0,
          campgrounds: []
        };
      summary.resultCount += 1;
      if (isActiveAvailability(result)) summary.activeResultCount += 1;
      summaries.set(parkName, summary);
    }

    return Array.from(summaries.values())
      .sort((a, b) => {
        const activeSort = b.activeResultCount - a.activeResultCount;
        if (activeSort !== 0) return activeSort;
        return a.parkName.localeCompare(b.parkName);
      })
      .map((summary) => {
        const latitude =
          summary.campgrounds.reduce((total, campground) => total + campground.latitude, 0) /
          Math.max(summary.campgrounds.length, 1);
        const longitude =
          summary.campgrounds.reduce((total, campground) => total + campground.longitude, 0) /
          Math.max(summary.campgrounds.length, 1);
        return {
          parkName: summary.parkName,
          stateCodes: Array.from(summary.stateCodeSet).sort().join("/") || "US",
          targetCount: summary.targetCount,
          activeTargetCount: summary.activeTargetCount,
          resultCount: summary.resultCount,
          activeResultCount: summary.activeResultCount,
          latitude: Number.isFinite(latitude) ? latitude : 44.5,
          longitude: Number.isFinite(longitude) ? longitude : -118,
          campgrounds: summary.campgrounds.sort((a, b) => a.name.localeCompare(b.name))
        };
      });
  }, [presets, results, targets]);
  const resultGroups = useMemo<ResultParkGroup[]>(() => {
    const parkMap = new Map<string, ResultParkGroup>();

    for (const result of filteredResults) {
      const active = isActiveAvailability(result);
      const parkName = result.park_name || result.target_name || "Unknown national park";
      const campgroundName = result.campground_name || "Unknown campground";
      const stayLabel = `${formatDate(result.arrival_date)} - ${formatDate(result.departure_date)}`;
      const parkId = `park:${parkName}`;
      const campgroundId = `campground:${parkName}:${campgroundName}`;
      const stayId = `stay:${parkName}:${campgroundName}:${result.arrival_date}:${result.departure_date}`;

      let park = parkMap.get(parkId);
      if (!park) {
        park = { id: parkId, name: parkName, count: 0, activeCount: 0, campgrounds: [] };
        parkMap.set(parkId, park);
      }
      park.count += 1;
      if (active) park.activeCount += 1;

      let campground = park.campgrounds.find((item) => item.id === campgroundId);
      if (!campground) {
        campground = { id: campgroundId, name: campgroundName, count: 0, activeCount: 0, stays: [] };
        park.campgrounds.push(campground);
      }
      campground.count += 1;
      if (active) campground.activeCount += 1;

      let stay = campground.stays.find((item) => item.id === stayId);
      if (!stay) {
        stay = { id: stayId, label: stayLabel, count: 0, activeCount: 0, results: [] };
        campground.stays.push(stay);
      }
      stay.count += 1;
      if (active) stay.activeCount += 1;
      stay.results.push(result);
    }

    const groups = Array.from(parkMap.values()).sort((a, b) => a.name.localeCompare(b.name));
    for (const park of groups) {
      park.campgrounds.sort((a, b) => a.name.localeCompare(b.name));
      for (const campground of park.campgrounds) {
        campground.stays.sort((a, b) => {
          const firstDate = a.results[0]?.arrival_date || "";
          const secondDate = b.results[0]?.arrival_date || "";
          return firstDate.localeCompare(secondDate);
        });
        for (const stay of campground.stays) {
          stay.results.sort((a, b) => {
            const activeSort = Number(isActiveAvailability(b)) - Number(isActiveAvailability(a));
            if (activeSort !== 0) return activeSort;
            return a.site.localeCompare(b.site);
          });
        }
      }
    }
    return groups;
  }, [filteredResults]);

  useEffect(() => {
    if (!mapElementRef.current || leafletMapRef.current) return;

    const map = L.map(mapElementRef.current, {
      scrollWheelZoom: false,
      zoomControl: true
    }).setView([46.5, -118.5], 5);
    L.tileLayer(mapTileUrl, {
      attribution: mapTileAttribution,
      maxZoom: 18
    }).addTo(map);
    const markerLayer = L.layerGroup().addTo(map);
    leafletMapRef.current = map;
    markerLayerRef.current = markerLayer;

    return () => {
      map.remove();
      leafletMapRef.current = null;
      markerLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = leafletMapRef.current;
    const markerLayer = markerLayerRef.current;
    if (!map || !markerLayer) return;

    markerLayer.clearLayers();
    const bounds = L.latLngBounds([]);

    for (const summary of parkSummaries) {
      const selectedPark = resultQuery === summary.parkName;
      const parkIcon = L.divIcon({
        className: `park-map-marker ${summary.activeResultCount ? "has-results" : ""} ${selectedPark ? "selected" : ""}`,
        html: `<strong>${summary.targetCount}</strong><small>${summary.activeResultCount}</small>`,
        iconSize: [42, 42],
        iconAnchor: [21, 21]
      });
      L.marker([summary.latitude, summary.longitude], { icon: parkIcon, zIndexOffset: -250 })
        .addTo(markerLayer)
        .bindPopup(
          `<strong>${escapeHtml(summary.parkName)}</strong><br>` +
            `${summary.targetCount} campground target${summary.targetCount === 1 ? "" : "s"}<br>` +
            `${summary.activeResultCount} active result${summary.activeResultCount === 1 ? "" : "s"}`
        )
        .on("click", () => {
          setResultQuery(summary.parkName);
          setResultSort("park");
          setResultView(summary.activeResultCount > 0 ? "active" : "all");
          setResultGroupOpen((current) => ({ ...current, [`park:${summary.parkName}`]: true }));
        });
      bounds.extend([summary.latitude, summary.longitude]);

      for (const campground of summary.campgrounds) {
        const selectedCampground = resultQuery === campground.name;
        const campgroundIcon = L.divIcon({
          className: `campground-map-marker ${campground.activeResultCount ? "has-results" : ""} ${
            selectedCampground ? "selected" : ""
          }`,
          html: `<span>${escapeHtml(campground.name)}</span>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11]
        });
        L.marker([campground.latitude, campground.longitude], {
          icon: campgroundIcon,
          zIndexOffset: campground.activeResultCount ? 700 : 500
        })
          .addTo(markerLayer)
          .bindPopup(
            `<strong>${escapeHtml(campground.name)}</strong><br>` +
              `${escapeHtml(campground.parkName)}<br>` +
              `${campground.activeResultCount} active result${campground.activeResultCount === 1 ? "" : "s"}`
          )
          .on("click", () => {
            setResultQuery(campground.name);
            setResultSort("park");
            setResultView(campground.activeResultCount > 0 ? "active" : "all");
            setResultGroupOpen((current) => ({
              ...current,
              [`park:${campground.parkName}`]: true,
              [`campground:${campground.parkName}:${campground.name}`]: true
            }));
          });
        bounds.extend([campground.latitude, campground.longitude]);
      }
    }

    if (bounds.isValid()) {
      map.fitBounds(bounds.pad(0.16), { maxZoom: 8 });
    } else {
      map.setView([46.5, -118.5], 5);
    }
  }, [parkSummaries, resultQuery]);

  async function refresh(options?: { silent?: boolean }) {
    if (!options?.silent) setLoadState("loading");
    try {
      const [
        targetData,
        presetData,
        watchData,
        resultData,
        resultSummaryData,
        scanRunData,
        notificationData,
        notificationStatusData,
        cartAssistStatusData,
        cartAttemptData
      ] = await Promise.all([
        api.targets(),
        api.presets(),
        api.watches(),
        api.results(),
        api.resultSummary(),
        api.scanRuns(),
        api.notifications(),
        api.notificationStatus(),
        api.cartAssistStatus(),
        api.cartAttempts()
      ]);
      setTargets(targetData);
      setPresets(presetData);
      setWatches(watchData);
      setResults(resultData);
      setResultSummary(resultSummaryData);
      setScanRuns(scanRunData);
      setNotifications(notificationData);
      setNotificationStatus(notificationStatusData);
      setCartAssistStatus(cartAssistStatusData);
      setCartAttempts(cartAttemptData);
      setLoadState("idle");
      if (!watchTarget && targetData.length > 0) setWatchTarget(String(targetData[0].id));
      if (!targetSettingsId && targetData.length > 0) {
        loadTargetSettings(targetData[0]);
      }
    } catch (error) {
      setLoadState("error");
      if (!options?.silent) setMessage(error instanceof Error ? error.message : "Unable to load Camp Finder.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    const handle = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh({ silent: true });
    }, 30000);
    return () => window.clearInterval(handle);
  }, [targetSettingsId, watchTarget]);

  useEffect(() => {
    if (!scanInProgress) return;
    const pollLiveScanState = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const [scanRunData, resultData, resultSummaryData, cartAttemptData] = await Promise.all([
          api.scanRuns(),
          api.results(),
          api.resultSummary(),
          api.cartAttempts()
        ]);
        setScanRuns(scanRunData);
        setResults(resultData);
        setResultSummary(resultSummaryData);
        setCartAttempts(cartAttemptData);
      } catch {
        // The normal refresh loop and scan completion handler will surface persistent API failures.
      }
    };
    void pollLiveScanState();
    const handle = window.setInterval(pollLiveScanState, 3000);
    return () => window.clearInterval(handle);
  }, [scanInProgress]);

  useEffect(() => {
    if (!cartAssistStatus || cartAssistConfigDirty || cartAssistConfigBusy) return;
    setCartAssistServerEnabled(cartAssistStatus.enabled);
    setCartAssistCooldown(String(cartAssistStatus.cooldown_minutes));
    setCartAssistMaxAttempts(String(cartAssistStatus.max_attempts_per_scan));
  }, [cartAssistConfigBusy, cartAssistConfigDirty, cartAssistStatus]);

  useEffect(() => {
    const visible = new Set(visibleResultIds);
    setSelectedResultIds((current) => {
      const next = current.filter((id) => visible.has(id));
      return next.length === current.length ? current : next;
    });
  }, [visibleResultIds]);

  useEffect(() => {
    if (query.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    const handle = window.setTimeout(async () => {
      setSearching(true);
      try {
        setSuggestions(await api.search(query.trim()));
      } catch {
        setSuggestions([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => window.clearTimeout(handle);
  }, [query]);

  function loadTargetSettings(target: Target) {
    setTargetSettingsId(String(target.id));
    setTargetName(target.name);
    setTargetParkName(target.park_name);
    setTargetStateCode(target.state_code);
    setTargetBookingUrl(target.booking_url);
    setTargetReleaseWindowValue(target.release_window_value || target.release_months);
    setTargetReleaseWindowUnit(target.release_window_unit || "Months");
    setTargetReleaseTime(target.release_time);
    setTargetTimezone(target.timezone);
    setTargetPollInterval(target.poll_interval_minutes);
    setReleaseProfiles(null);
  }

  function generatedWatchName(isSpecific: boolean) {
    return isSpecific
      ? `Specific ${specificArrival}`
      : `${weekdayLabel(selectedWeekdays)} starts, ${watchNights} night${watchNights === 1 ? "" : "s"}`;
  }

  function resetWatchForm() {
    setEditingWatchId(null);
    setWatchName("");
    setCartAssistEnabled(false);
  }

  function editWatch(watch: Watch) {
    setEditingWatchId(watch.id);
    setWatchName(watch.name);
    setWatchTarget(String(watch.target_id));
    setWatchMode(watch.mode);
    setSelectedWeekdays(watch.arrival_weekdays?.length ? watch.arrival_weekdays : [4]);
    setWatchNights(watch.nights);
    setCartAssistEnabled(Boolean(watch.cart_assist_enabled));
    setWindowStart(watch.window_start);
    setWindowEnd(watch.window_end);
    const firstRange = watch.specific_ranges?.[0];
    setSpecificArrival(firstRange?.arrival_date || watch.window_start);
    setSpecificDeparture(firstRange?.departure_date || watch.window_end);
    setFilterSiteType(watch.site_filters?.site_type || "");
    setFilterLoop(watch.site_filters?.loop || "");
    setFilterSite(watch.site_filters?.site || "");
    setFilterMinPeople(watch.site_filters?.min_people ? String(watch.site_filters.min_people) : "");
    setMessage(`Editing ${watch.name}.`);
  }

  async function addTarget(suggestion: SearchSuggestion) {
    setMessage("");
    await api.createTarget({
      name: suggestion.name,
      campground_id: suggestion.campground_id,
      park_name: suggestion.park_name,
      state_code: suggestion.state_code,
      latitude: suggestion.latitude ? Number(suggestion.latitude) : null,
      longitude: suggestion.longitude ? Number(suggestion.longitude) : null,
      release_months: 6,
      release_window_value: 6,
      release_window_unit: "Months",
      release_time: "07:00",
      timezone: "America/Los_Angeles",
      poll_interval_minutes: 10
    });
    setQuery("");
    setSuggestions([]);
    await refresh();
  }

  async function importPreset(packId: string) {
    setImportingPackId(packId);
    setMessage("");
    try {
      const result = await api.importPreset(packId);
      setMessage(`Imported ${result.imported_count} new target${result.imported_count === 1 ? "" : "s"}; updated ${result.updated_count}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Preset import failed.");
    } finally {
      setImportingPackId(null);
    }
  }

  async function discoverPreset(packId: string) {
    setDiscoveringPackId(packId);
    setMessage("");
    try {
      const result = await api.discoverPreset(packId);
      setPresetDiscovery((current) => ({ ...current, [packId]: result }));
      setMessage(
        `${result.pack_name}: Recreation.gov source returned ${result.discovered_count} campground${result.discovered_count === 1 ? "" : "s"}; ${result.new_count} new, ${result.missing_count} not in source.`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Source check failed.");
    } finally {
      setDiscoveringPackId(null);
    }
  }

  async function importDiscoveredPreset(packId: string) {
    setSourceImportingPackId(packId);
    setMessage("");
    try {
      const result = await api.importDiscoveredPreset(packId);
      setPresetDiscovery((current) => ({ ...current, [packId]: result.discovery }));
      setMessage(
        `Imported ${result.imported_count} source target${result.imported_count === 1 ? "" : "s"}; updated ${result.updated_count}.`
      );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Source import failed.");
    } finally {
      setSourceImportingPackId(null);
    }
  }

  async function downloadConfigBackup() {
    setConfigBusy("export");
    setMessage("");
    try {
      const backup = await api.exportConfig();
      const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `campfinder-backup-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setMessage(`Downloaded backup with ${backup.targets.length} target${backup.targets.length === 1 ? "" : "s"}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Backup download failed.");
    } finally {
      setConfigBusy(null);
    }
  }

  async function restoreConfigBackup() {
    if (!backupFile) {
      setMessage("Choose a JSON backup first.");
      return;
    }
    setConfigBusy("import");
    setMessage("");
    try {
      const parsed = JSON.parse(await backupFile.text()) as ConfigBackup;
      const result = await api.importConfig(parsed);
      setBackupFile(null);
      setMessage(
        `Restored ${result.target_count} target${result.target_count === 1 ? "" : "s"}; ` +
          `${result.created_watches} new watch${result.created_watches === 1 ? "" : "es"}, ` +
          `${result.updated_watches} updated.`
      );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Backup restore failed.");
    } finally {
      setConfigBusy(null);
    }
  }

  async function saveTargetSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!targetSettingsId) {
      setMessage("Choose a target to edit.");
      return;
    }
    if (!targetName.trim()) {
      setMessage("Target name is required.");
      return;
    }
    const updated = await api.updateTarget(Number(targetSettingsId), {
      name: targetName.trim(),
      park_name: targetParkName.trim(),
      state_code: targetStateCode.trim(),
      booking_url: targetBookingUrl.trim(),
      release_months: targetReleaseWindowUnit === "Months" ? targetReleaseWindowValue : undefined,
      release_window_value: targetReleaseWindowValue,
      release_window_unit: targetReleaseWindowUnit,
      release_time: targetReleaseTime,
      timezone: targetTimezone,
      poll_interval_minutes: targetPollInterval
    });
    setMessage(`Updated ${updated.name}.`);
    await refresh();
  }

  async function detectReleaseWindow() {
    if (!targetSettingsId) {
      setMessage("Choose a target first.");
      return;
    }
    setDetectReleaseBusy(true);
    setMessage("");
    try {
      const result = await api.detectTargetReleaseWindow(Number(targetSettingsId));
      loadTargetSettings(result.target);
      setMessage(
        `Detected a ${result.detected.release_window_value} ${result.detected.release_window_unit.toLowerCase()} release window ` +
          `from ${result.detected.source_campsite_count}/${result.detected.total_campsite_count} sampled campsites.`
      );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Release-window detection failed.");
    } finally {
      setDetectReleaseBusy(false);
    }
  }

  async function loadReleaseProfiles() {
    if (!targetSettingsId) {
      setMessage("Choose a target first.");
      return;
    }
    setProfileBusy(true);
    setMessage("");
    try {
      const profiles = await api.releaseWindowProfiles(Number(targetSettingsId));
      setReleaseProfiles(profiles);
      setMessage(
        `Loaded ${profiles.profiles.length} release profile${profiles.profiles.length === 1 ? "" : "s"} from ${profiles.total_campsite_count} sampled campsites.`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Release profiles failed to load.");
    } finally {
      setProfileBusy(false);
    }
  }

  function toggleWeekday(day: number) {
    setSelectedWeekdays((current) =>
      current.includes(day) ? current.filter((item) => item !== day) : [...current, day].sort((a, b) => a - b)
    );
  }

  async function submitWatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!watchTarget) {
      setMessage("Add a campground target first.");
      return;
    }
    const isSpecific = watchMode === "specific";
    if (!isSpecific && selectedWeekdays.length === 0) {
      setMessage("Choose at least one arrival day.");
      return;
    }
    const payload = {
      target_id: Number(watchTarget),
      name: watchName.trim() || generatedWatchName(isSpecific),
      mode: watchMode,
      pattern: isSpecific ? "specific" : patternKey(selectedWeekdays, watchNights),
      arrival_weekdays: isSpecific ? null : selectedWeekdays,
      nights: isSpecific ? 1 : watchNights,
      window_start: isSpecific ? specificArrival : windowStart,
      window_end: isSpecific ? specificDeparture : windowEnd,
      site_filters: {
        site_type: filterSiteType.trim(),
        loop: filterLoop.trim(),
        site: filterSite.trim(),
        min_people: filterMinPeople ? Number(filterMinPeople) : null
      },
      specific_ranges: isSpecific
        ? [{ arrival_date: specificArrival, departure_date: specificDeparture }]
        : [],
      cart_assist_enabled: cartAssistEnabled
    };
    if (editingWatchId) {
      const updated = await api.updateWatch(editingWatchId, payload);
      setMessage(`Updated ${updated.name}.`);
      resetWatchForm();
    } else {
      const created = await api.createWatch(payload);
      setMessage(`Added ${created.name}.`);
      setWatchName("");
      setCartAssistEnabled(false);
    }
    await refresh();
  }

  async function runScan(watchId: number) {
    const watch = watches.find((item) => item.id === watchId);
    setScanBusyId(watchId);
    setScanProgress({
      title: `Scanning ${watch?.name || "watch"}`,
      detail: watch ? `${watch.target_name} is checking candidate stays now.` : "Checking candidate stays now."
    });
    setMessage("");
    try {
      const result = await api.runScan(watchId);
      setMessage(result.message);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Scan failed.");
    } finally {
      setScanBusyId(null);
      setScanProgress(null);
    }
  }

  async function runAllScans() {
    setScanAllBusy(true);
    setScanProgress({
      title: "Scanning all active watches",
      detail: `${activeWatches.length} watch${activeWatches.length === 1 ? "" : "es"} queued for an immediate check.`
    });
    setMessage("");
    try {
      const result = await api.runAllScans();
      setMessage(`Scanned ${result.watch_count} watch${result.watch_count === 1 ? "" : "es"}; found ${result.available_count} available match${result.available_count === 1 ? "" : "es"}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Scan all failed.");
    } finally {
      setScanAllBusy(false);
      setScanProgress(null);
    }
  }

  async function testNotifications() {
    setTestNotifyBusy(true);
    setMessage("");
    try {
      const result = await api.testNotifications();
      setMessage(result.results.map((item) => `${item.channel}: ${item.status}`).join("; "));
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Notification test failed.");
    } finally {
      setTestNotifyBusy(false);
    }
  }

  async function saveCartAssistConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCartAssistConfigBusy("save");
    try {
      const payload = {
        enabled: cartAssistServerEnabled,
        cooldown_minutes: Number(cartAssistCooldown) || 30,
        max_attempts_per_scan: Number(cartAssistMaxAttempts) || 1,
        ...(cartAssistUsername.trim() ? { username: cartAssistUsername.trim() } : {}),
        ...(cartAssistPassword ? { password: cartAssistPassword } : {})
      };
      const status = await api.updateCartAssistConfig(payload);
      setCartAssistStatus(status);
      setCartAssistUsername("");
      setCartAssistPassword("");
      setCartAssistConfigDirty(false);
      setMessage("Saved Cart Assist server settings.");
      await refresh({ silent: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save Cart Assist settings.");
    } finally {
      setCartAssistConfigBusy(null);
    }
  }

  async function clearCartAssistCredentials() {
    const confirmed = window.confirm("Clear stored Recreation.gov credentials from appdata?");
    if (!confirmed) return;
    setCartAssistConfigBusy("clear");
    try {
      const status = await api.clearCartAssistCredentials();
      setCartAssistStatus(status);
      setCartAssistUsername("");
      setCartAssistPassword("");
      setCartAssistConfigDirty(false);
      setMessage(
        status.credential_source === "environment"
          ? "Cleared appdata credentials; environment credentials are still configured."
          : "Cleared stored Recreation.gov credentials."
      );
      await refresh({ silent: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to clear Cart Assist credentials.");
    } finally {
      setCartAssistConfigBusy(null);
    }
  }

  async function updateCartAttemptStatus(attempt: CartAttempt, status: CartAttemptStatus) {
    setCartAttemptBusyId(attempt.id);
    setMessage("");
    try {
      const updated = await api.updateCartAttemptStatus(attempt.id, status);
      setMessage(`Marked Cart Assist for ${updated.site} as ${status.split("_").join(" ")}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to update Cart Assist attempt.");
    } finally {
      setCartAttemptBusyId(null);
    }
  }

  async function deleteTarget(targetId: number) {
    setMessage("");
    await api.deleteTarget(targetId);
    await refresh();
  }

  async function updateTargetActive(target: Target, active: boolean) {
    setMessage("");
    const updated = await api.updateTarget(target.id, { active });
    setMessage(`${active ? "Resumed" : "Paused"} ${updated.name}.`);
    await refresh();
  }

  async function deleteWatch(watchId: number) {
    setMessage("");
    await api.deleteWatch(watchId);
    await refresh();
  }

  async function updateWatchActive(watch: Watch, active: boolean) {
    setMessage("");
    const updated = await api.updateWatch(watch.id, { active });
    setMessage(`${active ? "Resumed" : "Paused"} ${updated.name}.`);
    await refresh();
  }

  function isResultGroupOpen(groupId: string) {
    return resultGroupOpen[groupId] ?? groupId.startsWith("park:");
  }

  function toggleResultGroup(groupId: string) {
    setResultGroupOpen((current) => ({ ...current, [groupId]: !(current[groupId] ?? true) }));
  }

  function toggleResultSelection(resultId: number) {
    setSelectedResultIds((current) =>
      current.includes(resultId) ? current.filter((id) => id !== resultId) : [...current, resultId]
    );
  }

  function toggleVisibleResultSelection() {
    setSelectedResultIds(allVisibleResultsSelected ? [] : visibleResultIds);
  }

  async function updateSelectedResultsStatus(status: Result["status"]) {
    if (selectedResultIds.length === 0) return;
    setBulkResultBusy(status);
    setMessage("");
    try {
      await Promise.all(selectedResultIds.map((resultId) => api.updateResultStatus(resultId, status)));
      setMessage(
        `Updated ${selectedResultIds.length} selected result${selectedResultIds.length === 1 ? "" : "s"} to ${status}.`
      );
      setSelectedResultIds([]);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Bulk result update failed.");
    } finally {
      setBulkResultBusy(null);
    }
  }

  async function updateResultStatus(resultId: number, status: Result["status"]) {
    setResultBusyId(resultId);
    setMessage("");
    try {
      const updated = await api.updateResultStatus(resultId, status);
      setMessage(`Marked ${updated.site} as ${status}.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Result update failed.");
    } finally {
      setResultBusyId(null);
    }
  }

  function openResultBooking(result: Result, attempt?: CartAttempt) {
    if (attempt?.status === "manual_required") {
      void updateCartAttemptStatus(attempt, "opened");
      return;
    }
    if (result.status === "available") {
      void updateResultStatus(result.id, "opened");
    }
  }

  async function clearAllResults() {
    if (activeResultCount === 0) return;
    const confirmed = window.confirm("Dismiss all active availability results?");
    if (!confirmed) return;

    setClearResultsBusy(true);
    setMessage("");
    try {
      const cleared = await api.clearResults();
      setMessage(`Cleared ${cleared.cleared_count} active availability result${cleared.cleared_count === 1 ? "" : "s"}.`);
      setSelectedResultIds([]);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to clear availability results.");
    } finally {
      setClearResultsBusy(false);
    }
  }

  async function copyBookingDetails(result: Result) {
    setMessage("");
    const details = bookingBrief(result);
    try {
      await writeClipboardText(details);
      setBookingPreview(null);
      setMessage(`Copied booking details for ${result.site}.`);
    } catch (error) {
      setBookingPreview({ site: result.site, text: details });
      setMessage(
        error instanceof Error
          ? `${error.message} Booking details are shown below.`
          : "Unable to copy booking details. Booking details are shown below."
      );
    }
  }

  function openSetupDrawer(mode: SetupDrawerMode) {
    setSetupDrawerMode(mode);
    setSetupDrawerOpen(true);
  }

  function focusPark(summary: ParkSummary) {
    setResultQuery(summary.parkName);
    setResultSort("park");
    setResultView(summary.activeResultCount > 0 ? "active" : "all");
    setResultGroupOpen((current) => ({ ...current, [`park:${summary.parkName}`]: true }));
  }

  function resultCard(result: Result) {
    const selected = selectedResultSet.has(result.id);
    const cartAttempt = cartAttemptByResultId.get(result.id);
    return (
      <article className={`result-card ${selected ? "selected" : ""}`} key={result.id}>
        <label className="result-select">
          <input
            checked={selected}
            onChange={() => toggleResultSelection(result.id)}
            type="checkbox"
          />
          <span>
            <strong>{result.site}</strong>
            <small>{[result.loop, result.campsite_type].filter(Boolean).join(" / ") || "Campsite"}</small>
          </span>
        </label>
        <div className="result-card-meta">
          <span className={`status ${statusTone(result.status)}`}>{result.status}</span>
          <span>
            <strong>{result.watch_name}</strong>
            <small>Found {formatDateTime(result.discovered_at)}</small>
          </span>
        </div>
        <div className="result-actions">
          <a
            className="link-button"
            href={result.booking_url}
            target="_blank"
            rel="noreferrer"
            onClick={() => openResultBooking(result, cartAttempt)}
          >
            <ExternalLink size={16} /> Open
          </a>
          <button
            className="icon-button"
            type="button"
            onClick={() => void copyBookingDetails(result)}
            title="Copy campground, site, dates, and booking link"
          >
            <Clipboard size={16} /> Copy
          </button>
          {(result.status === "available" || result.status === "opened") && (
            <button
              className="icon-button"
              type="button"
              disabled={resultBusyId === result.id}
              onClick={() => void updateResultStatus(result.id, "booked")}
              title="Mark this availability as booked"
            >
              <CheckCircle2 size={16} /> Booked
            </button>
          )}
          {(result.status === "available" || result.status === "opened") && (
            <button
              className="icon-button"
              type="button"
              disabled={resultBusyId === result.id}
              onClick={() => void updateResultStatus(result.id, "dismissed")}
              title="Dismiss this availability"
            >
              <Trash2 size={16} /> Dismiss
            </button>
          )}
          {(result.status === "booked" || result.status === "dismissed") && (
            <button
              className="icon-button"
              type="button"
              disabled={resultBusyId === result.id}
              onClick={() => void updateResultStatus(result.id, "available")}
              title="Move this result back to active availability"
            >
              <RefreshCw size={16} /> Reopen
            </button>
          )}
        </div>
        {cartAttempt && (
          <div className="result-cart-assist">
            <span>
              <strong>Cart Assist</strong>
              <small>{cartAttempt.message}</small>
            </span>
            <span>
              <span className={`status ${statusTone(cartAttempt.status)}`}>
                {cartAttempt.status.split("_").join(" ")}
              </span>
              <small>{formatDateTime(cartAttempt.finished_at || cartAttempt.attempted_at)}</small>
            </span>
          </div>
        )}
      </article>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <TentTree size={22} />
          </span>
          <span>Camp Finder</span>
        </div>
        <nav className="nav-list" aria-label="Primary">
          <a className="nav-item active" href="#results">
            <Bell size={18} /> Alerts
          </a>
          <a className="nav-item" href="#activity">
            <Timer size={18} /> Activity
          </a>
          <button
            className={`nav-item ${setupDrawerOpen && setupDrawerMode === "targets" ? "active" : ""}`}
            onClick={() => openSetupDrawer("targets")}
            type="button"
          >
            <MapPin size={18} /> Targets
          </button>
          <button
            className={`nav-item ${setupDrawerOpen && setupDrawerMode === "watches" ? "active" : ""}`}
            onClick={() => openSetupDrawer("watches")}
            type="button"
          >
            <CalendarDays size={18} /> Watches
          </button>
          <a className="nav-item" href="#settings">
            <Settings size={18} /> Settings
          </a>
        </nav>
        <div className="sidebar-note">
          <Timer size={18} />
          <span>Minimum scan interval: 10 min</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>Availability Monitor</h1>
            <p>{activeTargets.length} targets &middot; {watchSummary} &middot; {activeResultCount} active matches</p>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" onClick={() => openSetupDrawer("targets")} type="button" title="Open campground targets">
              <MapPin size={18} />
              <span>Targets</span>
            </button>
            <button className="icon-button" onClick={() => openSetupDrawer("watches")} type="button" title="Open watch rules">
              <CalendarDays size={18} />
              <span>Watches</span>
            </button>
            <button className="icon-button" onClick={runAllScans} disabled={scanAllBusy || activeWatches.length === 0} title="Run every active watch now">
              <Play size={18} />
              <span>{scanAllBusy ? "Scanning" : "Scan All"}</span>
            </button>
            <button className="icon-button primary" onClick={() => void refresh()} disabled={loadState === "loading"} title="Refresh data">
              <RefreshCw size={18} />
              <span>Refresh</span>
            </button>
          </div>
        </header>

        {message && <div className="notice">{message}</div>}
        {loadState === "error" && <div className="notice danger">The API is not reachable yet.</div>}
        <section className={`scan-status-card ${scanInProgress ? "running" : ""}`} aria-live="polite">
          <span className="scan-status-icon">
            {scanInProgress ? <RefreshCw className="spinning" size={20} /> : <Activity size={20} />}
          </span>
          <span>
            <strong>{activeScanTitle}</strong>
            <small>{activeScanDetail}</small>
            {runningScanRuns.length > 0 && (
              <div className="live-scan-list" aria-label="Active scan runs">
                {runningScanRuns.slice(0, 3).map((run) => (
                  <span className="live-scan-pill" key={run.id}>
                    <RefreshCw className="spinning" size={13} />
                    <span>{run.watch_name}</span>
                    <small>{run.target_name}</small>
                  </span>
                ))}
              </div>
            )}
          </span>
        </section>

        <section className="summary-grid" aria-label="Monitor summary">
          <SummaryMetric label="Targets" value={activeTargets.length.toString()} icon={<MapPin size={18} />} />
          <SummaryMetric label="Active watches" value={activeWatches.length.toString()} icon={<CalendarDays size={18} />} />
          <SummaryMetric label="Active matches" value={activeResultCount.toString()} icon={<CheckCircle2 size={18} />} />
          <SummaryMetric label="Notifications" value={notifications.length.toString()} icon={<Bell size={18} />} />
        </section>

        <div className={`drawer-backdrop ${setupDrawerOpen ? "show" : ""}`} onClick={() => setSetupDrawerOpen(false)} />
        <div className={`setup-drawer ${setupDrawerOpen ? "open" : ""}`}>
          <div className="drawer-heading">
            <div>
              <h2>{setupDrawerMode === "targets" ? "Target Setup" : "Watch Builder"}</h2>
              <p>{setupDrawerMode === "targets" ? "Add and maintain campground targets." : "Build date rules and scan filters."}</p>
            </div>
            <div className="drawer-controls">
              <button
                className={`drawer-tab ${setupDrawerMode === "targets" ? "active" : ""}`}
                onClick={() => setSetupDrawerMode("targets")}
                type="button"
              >
                <MapPin size={16} /> Targets
              </button>
              <button
                className={`drawer-tab ${setupDrawerMode === "watches" ? "active" : ""}`}
                onClick={() => setSetupDrawerMode("watches")}
                type="button"
              >
                <CalendarDays size={16} /> Watches
              </button>
              <button className="icon-only" onClick={() => setSetupDrawerOpen(false)} title="Close setup drawer" type="button">
                <X size={17} />
              </button>
            </div>
          </div>
          <section className={`panel ${setupDrawerMode === "targets" ? "" : "drawer-panel-hidden"}`} id="targets">
            <div className="panel-heading">
              <div>
                <h2>Campground Targets</h2>
                <p>Search Recreation.gov and pin the campgrounds you care about.</p>
              </div>
            </div>
            <label className="search-box">
              <Search size={18} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search campground, park, or area"
              />
            </label>
            <div className="suggestions">
              {searching && <span className="muted">Searching...</span>}
              {suggestions.map((suggestion) => (
                <button key={suggestion.campground_id} className="suggestion-row" onClick={() => addTarget(suggestion)}>
                  <span>
                    <strong>{suggestion.name}</strong>
                    <small>{suggestion.park_name || "Recreation.gov"} {suggestion.state_code}</small>
                  </span>
                  <Plus size={18} />
                </button>
              ))}
            </div>
            <div className="preset-packs">
              <div className="subheading">
                <strong>Preset packs</strong>
                <small>Import a starting list, then trim it to your actual targets.</small>
              </div>
              {presets.map((pack) => {
                const discovery = presetDiscovery[pack.id];
                return (
                  <article className="preset-row" key={pack.id}>
                    <span>
                      <strong>{pack.name}</strong>
                      <small>{pack.imported_count}/{pack.target_count} imported &middot; {pack.description}</small>
                      {discovery && (
                        <small className="preset-source-summary">
                          Source {discovery.discovered_count} &middot; {discovery.new_count} new &middot; {discovery.missing_count} static not returned
                        </small>
                      )}
                    </span>
                    <span className="row-actions">
                      <button
                        className="icon-only"
                        onClick={() => discoverPreset(pack.id)}
                        disabled={discoveringPackId === pack.id}
                        title={`Check Recreation.gov source for ${pack.name}`}
                      >
                        <RefreshCw size={17} />
                      </button>
                      <button
                        className="icon-only"
                        onClick={() => importDiscoveredPreset(pack.id)}
                        disabled={sourceImportingPackId === pack.id}
                        title={`Import Recreation.gov source list for ${pack.name}`}
                      >
                        <Search size={17} />
                      </button>
                      <button
                        className="icon-only"
                        onClick={() => importPreset(pack.id)}
                        disabled={importingPackId === pack.id}
                        title={`Import bundled ${pack.name}`}
                      >
                        <Download size={17} />
                      </button>
                    </span>
                  </article>
                );
              })}
            </div>
            <div className="target-list">
              {targets.length === 0 && <p className="empty">No targets yet. Add a campground to start watching dates.</p>}
              {targets.map((target) => (
                <article className={`target-row ${target.active ? "" : "inactive"}`} key={target.id}>
                  <span className="target-icon"><Waves size={18} /></span>
                  <span>
                    <strong>{target.name}</strong>
                    <small>
                      {target.park_name || "Campground"} &middot; {target.campground_id} &middot;{" "}
                      {target.release_window_value || target.release_months} {(target.release_window_unit || "Months").toLowerCase()} @ {target.release_time}
                    </small>
                  </span>
                  <span className="row-actions">
                    <span className={`status ${statusTone(target.active ? target.last_status : "paused")}`}>
                      {target.active ? target.last_status : "paused"}
                    </span>
                    <button
                      className="icon-only"
                      onClick={() => updateTargetActive(target, !target.active)}
                      title={`${target.active ? "Pause" : "Resume"} ${target.name}`}
                    >
                      {target.active ? <Pause size={16} /> : <Play size={16} />}
                    </button>
                    <button className="icon-only quiet" onClick={() => deleteTarget(target.id)} title={`Delete ${target.name}`}>
                      <Trash2 size={16} />
                    </button>
                  </span>
                </article>
              ))}
            </div>
            {targets.length > 0 && (
              <form className="target-settings-form" onSubmit={saveTargetSettings}>
                <div className="subheading">
                  <strong>Target settings</strong>
                  <small>Edit display details and booking window math for each target.</small>
                </div>
                <label>
                  Target
                  <select
                    value={targetSettingsId}
                    onChange={(event) => {
                      const target = targets.find((item) => String(item.id) === event.target.value);
                      if (target) loadTargetSettings(target);
                    }}
                  >
                    {targets.map((target) => (
                      <option key={target.id} value={target.id}>{target.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Display name
                  <input value={targetName} onChange={(event) => setTargetName(event.target.value)} />
                </label>
                <label>
                  Park label
                  <input value={targetParkName} onChange={(event) => setTargetParkName(event.target.value)} />
                </label>
                <label>
                  State
                  <input maxLength={8} value={targetStateCode} onChange={(event) => setTargetStateCode(event.target.value)} />
                </label>
                <label className="wide-field">
                  Booking URL
                  <input value={targetBookingUrl} onChange={(event) => setTargetBookingUrl(event.target.value)} />
                </label>
                <label>
                  Release window
                  <input
                    min="0"
                    max="730"
                    type="number"
                    value={targetReleaseWindowValue}
                    onChange={(event) => setTargetReleaseWindowValue(Number(event.target.value))}
                  />
                </label>
                <label>
                  Window unit
                  <select
                    value={targetReleaseWindowUnit}
                    onChange={(event) => setTargetReleaseWindowUnit(event.target.value as Target["release_window_unit"])}
                  >
                    <option value="Days">Days</option>
                    <option value="Weeks">Weeks</option>
                    <option value="Months">Months</option>
                  </select>
                </label>
                <label>
                  Release time
                  <input type="time" value={targetReleaseTime} onChange={(event) => setTargetReleaseTime(event.target.value)} />
                </label>
                <label>
                  Timezone
                  <input value={targetTimezone} onChange={(event) => setTargetTimezone(event.target.value)} />
                </label>
                <label>
                  Scan interval
                  <input
                    min="10"
                    max="1440"
                    type="number"
                    value={targetPollInterval}
                    onChange={(event) => setTargetPollInterval(Number(event.target.value))}
                  />
                </label>
                <button className="icon-button" type="submit">
                  <Save size={18} />
                  <span>Save Target</span>
                </button>
                <button className="icon-button" type="button" onClick={detectReleaseWindow} disabled={detectReleaseBusy}>
                  <RefreshCw size={18} />
                  <span>Detect Window</span>
                </button>
                <button className="icon-button" type="button" onClick={loadReleaseProfiles} disabled={profileBusy}>
                  <Timer size={18} />
                  <span>View Profiles</span>
                </button>
                {releaseProfiles && (
                  <div className="release-profile-list">
                    <div className="subheading">
                      <strong>Detected release profiles</strong>
                      <small>
                        {formatDate(releaseProfiles.sampled_month)} sample &middot; {releaseProfiles.total_campsite_count} campsites
                      </small>
                    </div>
                    {releaseProfiles.profiles.slice(0, 8).map((profile, index) => (
                      <article className="release-profile-row" key={`${profile.loop}-${profile.campsite_type}-${profile.release_window_value}-${profile.release_window_unit}-${index}`}>
                        <span>
                          <strong>{[profile.loop ? `Loop ${profile.loop}` : "No loop", profile.campsite_type || "Campsite"].join(" / ")}</strong>
                          <small>{profile.campsite_count} sampled site{profile.campsite_count === 1 ? "" : "s"}</small>
                        </span>
                        <span className={`status ${profile.release_window_value ? "calm" : "quiet"}`}>
                          {profile.release_window_value
                            ? `${profile.release_window_value} ${profile.release_window_unit.toLowerCase()}`
                            : "not exposed"}
                        </span>
                      </article>
                    ))}
                  </div>
                )}
              </form>
            )}
          </section>

          <section className={`panel ${setupDrawerMode === "watches" ? "" : "drawer-panel-hidden"}`} id="watches">
            <div className="panel-heading">
              <div>
                <h2>Watch Rules</h2>
                <p>Scan weekend patterns or exact stays for each target.</p>
              </div>
            </div>
            <form className="watch-form" onSubmit={submitWatch}>
              <label>
                Name
                <input value={watchName} onChange={(event) => setWatchName(event.target.value)} placeholder={generatedWatchName(watchMode === "specific")} />
              </label>
              <label>
                Target
                <select value={watchTarget} onChange={(event) => setWatchTarget(event.target.value)}>
                  {targets.map((target) => (
                    <option key={target.id} value={target.id}>{target.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Mode
                <select value={watchMode} onChange={(event) => setWatchMode(event.target.value as "weekend" | "specific")}>
                  <option value="weekend">Weekend pattern</option>
                  <option value="specific">Specific dates</option>
                </select>
              </label>
              {watchMode === "weekend" ? (
                <>
                  <label>
                    Arrival days
                    <span className="weekday-toggle" aria-label="Arrival days">
                      {weekdayOptions.map((day) => (
                        <button
                          className={selectedWeekdays.includes(day.value) ? "selected" : ""}
                          key={day.value}
                          onClick={() => toggleWeekday(day.value)}
                          type="button"
                        >
                          {day.label}
                        </button>
                      ))}
                    </span>
                  </label>
                  <label>
                    Nights
                    <input
                      min="1"
                      max="14"
                      type="number"
                      value={watchNights}
                      onChange={(event) => setWatchNights(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    Window start
                    <input type="date" value={windowStart} onChange={(event) => setWindowStart(event.target.value)} />
                  </label>
                  <label>
                    Window end
                    <input type="date" value={windowEnd} onChange={(event) => setWindowEnd(event.target.value)} />
                  </label>
                </>
              ) : (
                <>
                  <label>
                    Arrival
                    <input type="date" value={specificArrival} onChange={(event) => setSpecificArrival(event.target.value)} />
                  </label>
                  <label>
                    Departure
                    <input type="date" value={specificDeparture} onChange={(event) => setSpecificDeparture(event.target.value)} />
                  </label>
                </>
              )}
              <label>
                Site type
                <input value={filterSiteType} onChange={(event) => setFilterSiteType(event.target.value)} placeholder="Tent, RV, group" />
              </label>
              <label>
                Loop
                <input value={filterLoop} onChange={(event) => setFilterLoop(event.target.value)} placeholder="A, river, meadow" />
              </label>
              <label>
                Site text
                <input value={filterSite} onChange={(event) => setFilterSite(event.target.value)} placeholder="A12, walk-in" />
              </label>
              <label>
                Min people
                <input
                  min="1"
                  max="99"
                  type="number"
                  value={filterMinPeople}
                  onChange={(event) => setFilterMinPeople(event.target.value)}
                  placeholder="4"
                />
              </label>
              <label className="toggle-field wide-field">
                <span>
                  <strong>Cart Assist</strong>
                  <small>High-priority hits create one guarded server-side hold attempt record.</small>
                </span>
                <input
                  checked={cartAssistEnabled}
                  onChange={(event) => setCartAssistEnabled(event.target.checked)}
                  type="checkbox"
                />
              </label>
              <button className="icon-button" type="submit">
                {editingWatchId ? <Save size={18} /> : <Plus size={18} />}
                <span>{editingWatchId ? "Save Watch" : "Add Watch"}</span>
              </button>
              {editingWatchId && (
                <button className="icon-button" type="button" onClick={resetWatchForm}>
                  <X size={18} />
                  <span>Cancel</span>
                </button>
              )}
            </form>
            <div className="watch-list">
              {watches.length === 0 && <p className="empty">No watch rules yet.</p>}
              {watches.map((watch) => {
                const watchPaused = !watch.active || !watch.target_active;
                return (
                <article className={`watch-row ${watchPaused ? "inactive" : ""}`} key={watch.id}>
                  <span>
                    <strong>{watch.name}</strong>
                    <small>
                      {watch.target_name} &middot; {watch.candidate_count} stays &middot; {filterSummary(watch.site_filters)} &middot;{" "}
                      {watchPaused ? "paused" : `next ${formatDateTime(watch.next_scan_at)}`}
                    </small>
                  </span>
                  <span className="row-actions">
                    {Boolean(watch.cart_assist_enabled) && (
                      <span className="status warning" title="Cart Assist is enabled for new hits on this watch">
                        priority
                      </span>
                    )}
                    <span className={`status ${watchPaused ? "quiet" : "success"}`}>{watchPaused ? "paused" : "active"}</span>
                    <button className="icon-only" onClick={() => editWatch(watch)} title={`Edit ${watch.name}`}>
                      <Pencil size={16} />
                    </button>
                    <button className="icon-only" onClick={() => runScan(watch.id)} disabled={scanBusyId === watch.id || watchPaused} title="Run scan now">
                      <RefreshCw size={17} />
                    </button>
                    <button
                      className="icon-only"
                      onClick={() => updateWatchActive(watch, !watch.active)}
                      disabled={!watch.target_active}
                      title={
                        !watch.target_active
                          ? "Resume the target before resuming this watch"
                          : `${watch.active ? "Pause" : "Resume"} ${watch.name}`
                      }
                    >
                      {watch.active ? <Pause size={16} /> : <Play size={16} />}
                    </button>
                    <button className="icon-only quiet" onClick={() => deleteWatch(watch.id)} title={`Delete ${watch.name}`}>
                      <Trash2 size={16} />
                    </button>
                  </span>
                </article>
                );
              })}
            </div>
          </section>
        </div>

        <div className="content-grid lower">
          <section className="map-dashboard" aria-label="Target map">
            <div className="map-panel">
              <div className="map-toolbar">
                <div>
                  <h2>Target Map</h2>
                  <p>Tap a park to filter active availability without leaving the results view.</p>
                </div>
                <div className="map-actions">
                  <button className="icon-button" onClick={() => setResultQuery("")} type="button">
                    <X size={17} />
                    <span>Clear Filter</span>
                  </button>
                  <button className="icon-button primary" onClick={() => openSetupDrawer("targets")} type="button">
                    <Plus size={17} />
                    <span>Add Target</span>
                  </button>
                </div>
              </div>
              <div className="map-canvas proper-map">
                <div className="leaflet-map" ref={mapElementRef} />
                {parkSummaries.length === 0 && (
                  <div className="map-empty">
                    <MapPin size={28} />
                    <strong>No target parks yet</strong>
                    <small>Open Targets to import a preset pack or search Recreation.gov.</small>
                  </div>
                )}
              </div>
            </div>
            <aside className="map-list">
              <div className="subheading">
                <strong>Park Queue</strong>
                <small>{parkSummaries.length} park group{parkSummaries.length === 1 ? "" : "s"} tracked</small>
              </div>
              {parkSummaries.map((summary) => (
                <button
                  className={`park-chip ${resultQuery === summary.parkName ? "selected" : ""}`}
                  key={summary.parkName}
                  onClick={() => focusPark(summary)}
                  type="button"
                >
                  <span>
                    <strong>{summary.parkName}</strong>
                    <small>{summary.activeTargetCount}/{summary.targetCount} targets active</small>
                  </span>
                  <span className={`status ${summary.activeResultCount ? "success" : "quiet"}`}>
                    {summary.activeResultCount || summary.resultCount}
                  </span>
                </button>
              ))}
            </aside>
          </section>

          <section className="panel release-panel">
            <div className="panel-heading">
              <div>
                <h2>Release Planner</h2>
                <p>Calculated from each target's configurable booking window.</p>
              </div>
            </div>
            <div className="release-list">
              {latestRelease.length === 0 && <p className="empty">No future release windows calculated yet.</p>}
              {latestRelease.map((hint) => (
                <article className="release-row" key={`${hint.target}-${hint.arrival_date}-${hint.release_at}`}>
                  <span>
                    <strong>{hint.target}</strong>
                    <small>{hint.watch} &middot; {formatDate(hint.arrival_date)} to {formatDate(hint.departure_date)}</small>
                  </span>
                  <time>
                    {hint.release_status === "upcoming" ? "Opens " : "Open since "}
                    {formatDateTime(hint.release_at)}
                  </time>
                </article>
              ))}
            </div>
          </section>

          <section className="panel scan-panel" id="activity">
            <div className="panel-heading">
              <div>
                <h2>Recent Scan Activity</h2>
                <p>Latest background and manual scan runs.</p>
              </div>
            </div>
            <div className="status-list">
              {scanRuns.length === 0 && <p className="empty">No scans have run yet.</p>}
              {scanRuns.slice(0, 6).map((run) => (
                <article className="status-row scan-row" key={run.id}>
                  <span>
                    <strong>{run.watch_name}</strong>
                    <small>
                      {run.status === "running"
                        ? `${run.target_name} \u00b7 in progress since ${formatDateTime(run.started_at)}`
                        : `${run.target_name} \u00b7 ${run.candidate_count} stays \u00b7 ${run.available_count} matches`}
                    </small>
                    <small>{run.message || (run.status === "running" ? "Checking Recreation.gov availability now." : "")}</small>
                  </span>
                  <span>
                    <span className={`status ${statusTone(run.status === "success" && run.available_count > 0 ? "available" : run.status)}`}>
                      {run.status}
                    </span>
                    <small>{formatDateTime(run.finished_at || run.started_at)}</small>
                  </span>
                </article>
              ))}
            </div>
          </section>

          <section className="panel notification-panel" id="settings">
            <div className="panel-heading">
              <div>
                <h2>Notifications & Server Settings</h2>
                <p>Notification channels use environment variables; Cart Assist can use appdata settings.</p>
              </div>
              <button className="icon-button" onClick={testNotifications} disabled={testNotifyBusy} title="Send a test notification">
                <Bell size={17} />
                <span>Test</span>
              </button>
            </div>
            <div className="status-list">
              {notificationStatus.channels.map((channel) => (
                <article className="status-row" key={channel.channel}>
                  <span>
                    <strong>{channel.channel}</strong>
                    <small>{channel.detail}</small>
                  </span>
                  <span className={`status ${channel.configured ? "success" : "quiet"}`}>
                    {channel.configured ? "configured" : "missing"}
                  </span>
                </article>
              ))}
            </div>
            <div className="cart-assist-log">
              <div className="subheading">
                <strong>Cart Assist</strong>
                <small>
                  {cartAssistStatus?.detail || "Server status has not loaded yet."}
                </small>
              </div>
              <article className="status-row">
                <span>
                  <strong>Remote hold guard</strong>
                  <small>{cartAssistGuardSummary(cartAssistStatus)}</small>
                </span>
                <span className={`status ${cartAssistGuardTone(cartAssistStatus)}`}>
                  {cartAssistGuardLabel(cartAssistStatus)}
                </span>
              </article>
              <form className="cart-assist-form" onSubmit={saveCartAssistConfig}>
                <label className="toggle-field wide-field">
                  <span>
                    <strong>Server Cart Assist</strong>
                    <small>Watches still opt in individually.</small>
                  </span>
                  <input
                    checked={cartAssistServerEnabled}
                    onChange={(event) => {
                      setCartAssistServerEnabled(event.target.checked);
                      setCartAssistConfigDirty(true);
                    }}
                    type="checkbox"
                  />
                </label>
                <label>
                  Cooldown minutes
                  <input
                    min="1"
                    max="1440"
                    type="number"
                    value={cartAssistCooldown}
                    onChange={(event) => {
                      setCartAssistCooldown(event.target.value);
                      setCartAssistConfigDirty(true);
                    }}
                  />
                </label>
                <label>
                  Attempts per scan
                  <input
                    min="1"
                    max="25"
                    type="number"
                    value={cartAssistMaxAttempts}
                    onChange={(event) => {
                      setCartAssistMaxAttempts(event.target.value);
                      setCartAssistConfigDirty(true);
                    }}
                  />
                </label>
                <label>
                  Recreation.gov email
                  <input
                    autoComplete="username"
                    placeholder={cartAssistStatus?.username_configured ? "Configured; leave blank to keep" : "you@example.com"}
                    value={cartAssistUsername}
                    onChange={(event) => {
                      setCartAssistUsername(event.target.value);
                      setCartAssistConfigDirty(true);
                    }}
                  />
                </label>
                <label>
                  Recreation.gov password
                  <input
                    autoComplete="current-password"
                    placeholder={cartAssistStatus?.password_configured ? "Configured; leave blank to keep" : "Password"}
                    type="password"
                    value={cartAssistPassword}
                    onChange={(event) => {
                      setCartAssistPassword(event.target.value);
                      setCartAssistConfigDirty(true);
                    }}
                  />
                </label>
                <div className="cart-assist-actions wide-field">
                  <button className="icon-button" disabled={cartAssistConfigBusy !== null} type="submit">
                    <Save size={17} />
                    <span>{cartAssistConfigBusy === "save" ? "Saving" : "Save"}</span>
                  </button>
                  <button
                    className="icon-button"
                    disabled={cartAssistConfigBusy !== null || cartAssistStatus?.credential_source !== "appdata"}
                    onClick={clearCartAssistCredentials}
                    type="button"
                  >
                    <Trash2 size={17} />
                    <span>{cartAssistConfigBusy === "clear" ? "Clearing" : "Clear Credentials"}</span>
                  </button>
                </div>
              </form>
              {cartAttempts.length === 0 ? (
                <p className="empty compact">No cart assist attempts yet.</p>
              ) : (
                cartAttempts.slice(0, 4).map((attempt) => {
                  const busy = cartAttemptBusyId === attempt.id;
                  const checkoutReady = attempt.status === "manual_required" || attempt.status === "opened";
                  const canMakeReady = ["needs_credentials", "disabled", "failed"].includes(attempt.status);
                  return (
                    <article className="status-row cart-attempt-row" key={attempt.id}>
                      <span>
                        <strong>{attempt.site}</strong>
                        <small>
                          {attempt.target_name} &middot; {formatDate(attempt.arrival_date)} to {formatDate(attempt.departure_date)}
                        </small>
                        <small>{attempt.message}</small>
                        {attempt.finished_at && <small>Resolved {formatDateTime(attempt.finished_at)}</small>}
                      </span>
                      <span>
                        <span className={`status ${statusTone(attempt.status)}`}>{attempt.status.split("_").join(" ")}</span>
                        <small>{formatDateTime(attempt.attempted_at)}</small>
                        <span className="cart-attempt-actions">
                          {checkoutReady && (
                            <a
                              className="link-button compact"
                              href={attempt.booking_url}
                              onClick={() => void updateCartAttemptStatus(attempt, "opened")}
                              rel="noreferrer"
                              target="_blank"
                            >
                              <ExternalLink size={15} /> Open
                            </a>
                          )}
                          {canMakeReady && (
                            <button
                              className="icon-button compact"
                              disabled={busy}
                              onClick={() => void updateCartAttemptStatus(attempt, "manual_required")}
                              type="button"
                            >
                              <RefreshCw size={15} /> Ready
                            </button>
                          )}
                          {checkoutReady && (
                            <>
                              <button
                                className="icon-button compact"
                                disabled={busy}
                                onClick={() => void updateCartAttemptStatus(attempt, "booked")}
                                type="button"
                              >
                                <CheckCircle2 size={15} /> Booked
                              </button>
                              <button
                                className="icon-button compact"
                                disabled={busy}
                                onClick={() => void updateCartAttemptStatus(attempt, "dismissed")}
                                type="button"
                              >
                                <Trash2 size={15} /> Dismiss
                              </button>
                              <button
                                className="icon-button compact"
                                disabled={busy}
                                onClick={() => void updateCartAttemptStatus(attempt, "failed")}
                                type="button"
                              >
                                <X size={15} /> Failed
                              </button>
                            </>
                          )}
                        </span>
                      </span>
                    </article>
                  );
                })
              )}
            </div>
            <div className="backup-tools">
              <div className="subheading">
                <strong>Configuration Backup</strong>
                <small>Targets, release settings, and watch rules.</small>
              </div>
              <div className="backup-actions">
                <button
                  className="icon-button"
                  onClick={downloadConfigBackup}
                  disabled={configBusy !== null}
                  title="Download configuration backup"
                  type="button"
                >
                  <Download size={17} />
                  <span>Download</span>
                </button>
                <label className={`file-picker ${configBusy !== null ? "disabled" : ""}`}>
                  <input
                    accept="application/json,.json"
                    disabled={configBusy !== null}
                    onChange={(event) => setBackupFile(event.target.files?.[0] || null)}
                    type="file"
                  />
                  <Upload size={17} />
                  <span>{backupFile ? backupFile.name : "Choose JSON"}</span>
                </label>
                <button
                  className="icon-button"
                  onClick={restoreConfigBackup}
                  disabled={configBusy !== null || !backupFile}
                  title="Restore configuration backup"
                  type="button"
                >
                  <Upload size={17} />
                  <span>Restore</span>
                </button>
              </div>
            </div>
            <div className="notification-log">
              <div className="subheading">
                <strong>Recent notifications</strong>
                <small>{notifications.length ? "Latest delivery attempts from availability matches." : "No notification attempts yet."}</small>
              </div>
              {notifications.slice(0, 4).map((event) => (
                <article className="status-row" key={event.id}>
                  <span>
                    <strong>{event.channel}</strong>
                    <small>{event.message}</small>
                  </span>
                  <span className={`status ${event.status === "sent" ? "success" : event.status === "error" ? "danger" : "quiet"}`}>
                    {event.status}
                  </span>
                </article>
              ))}
            </div>
          </section>

          <section className="panel results-panel" id="results">
            <div className="panel-heading">
              <div>
                <h2>Availability Results</h2>
                <p>New matches are stored once and linked directly to Recreation.gov.</p>
              </div>
              <button
                className="icon-button"
                disabled={clearResultsBusy || activeResultCount === 0}
                onClick={() => void clearAllResults()}
                title="Dismiss all active availability results"
                type="button"
              >
                <Trash2 size={17} />
                <span>{clearResultsBusy ? "Clearing" : "Clear All"}</span>
              </button>
            </div>
            {bookingPreview && (
              <div className="booking-preview">
                <div className="subheading">
                  <strong>Booking details for {bookingPreview.site}</strong>
                  <small>Select the text below if clipboard access is blocked.</small>
                </div>
                <textarea readOnly value={bookingPreview.text} />
                <button className="icon-button" type="button" onClick={() => setBookingPreview(null)}>
                  <X size={18} />
                  <span>Close</span>
                </button>
              </div>
            )}
            <div className="result-toolbar">
              <label className="toolbar-field">
                <Filter size={16} />
                <select value={resultView} onChange={(event) => setResultView(event.target.value as ResultView)}>
                  {resultViewOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <div className="toolbar-field search-field">
                <Search size={16} />
                <input
                  value={resultQuery}
                  onChange={(event) => setResultQuery(event.target.value)}
                  placeholder="Search park, campground, site"
                />
                {resultQuery && (
                  <button
                    className="inline-clear"
                    onClick={() => setResultQuery("")}
                    title="Clear result search"
                    type="button"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
              <label className="toolbar-field">
                <ListChecks size={16} />
                <select value={resultSort} onChange={(event) => setResultSort(event.target.value as ResultSort)}>
                  {resultSortOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <div className="result-bulk-actions">
                <button
                  className="icon-button"
                  disabled={visibleResultIds.length === 0}
                  onClick={toggleVisibleResultSelection}
                  type="button"
                >
                  <ListChecks size={16} />
                  <span>{allVisibleResultsSelected ? "Deselect" : "Select Visible"}</span>
                </button>
                <button
                  className="icon-button"
                  disabled={selectedResults.length === 0 || bulkResultBusy !== null}
                  onClick={() => void updateSelectedResultsStatus("dismissed")}
                  type="button"
                >
                  <Trash2 size={16} />
                  <span>Dismiss</span>
                </button>
                <button
                  className="icon-button"
                  disabled={selectedResults.length === 0 || bulkResultBusy !== null}
                  onClick={() => void updateSelectedResultsStatus("booked")}
                  type="button"
                >
                  <CheckCircle2 size={16} />
                  <span>Booked</span>
                </button>
                <button
                  className="icon-button"
                  disabled={selectedResults.length === 0 || bulkResultBusy !== null}
                  onClick={() => void updateSelectedResultsStatus("available")}
                  type="button"
                >
                  <RefreshCw size={16} />
                  <span>Reopen</span>
                </button>
              </div>
              <span className="result-count">
                {filteredResults.length} shown &middot; {selectedResults.length} selected &middot; {loadedResultCount} loaded
                {resultListTruncated ? ` of ${totalResultCount}` : ""}
              </span>
            </div>
            {resultListTruncated && (
              <div className="result-limit-note">
                Showing the newest active working set: {loadedResultCount} of {totalResultCount} saved results. This browser view loads up to {RESULTS_LIMIT} rows; search and Select Visible apply to loaded rows.
              </div>
            )}
            <div className="result-groups">
              {resultGroups.length === 0 && (
                <p className="empty">{results.length ? "No results match the current view." : "No availability saved yet."}</p>
              )}
              {resultGroups.map((park) => {
                const parkOpen = isResultGroupOpen(park.id);
                return (
                  <section className="result-group" key={park.id}>
                    <button
                      aria-expanded={parkOpen}
                      className="result-group-header park"
                      onClick={() => toggleResultGroup(park.id)}
                      type="button"
                    >
                      {parkOpen ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                      <span className="result-group-title">
                        <strong>{park.name}</strong>
                        <small>
                          {park.count} result{park.count === 1 ? "" : "s"} &middot; {park.activeCount} active
                        </small>
                      </span>
                    </button>
                    {parkOpen && (
                      <div className="result-group-body">
                        {park.campgrounds.map((campground) => {
                          const campgroundOpen = isResultGroupOpen(campground.id);
                          return (
                            <section className="result-group nested" key={campground.id}>
                              <button
                                aria-expanded={campgroundOpen}
                                className="result-group-header campground"
                                onClick={() => toggleResultGroup(campground.id)}
                                type="button"
                              >
                                {campgroundOpen ? <ChevronDown size={17} /> : <ChevronRight size={17} />}
                                <span className="result-group-title">
                                  <strong>{campground.name}</strong>
                                  <small>
                                    {campground.count} result{campground.count === 1 ? "" : "s"} &middot;{" "}
                                    {campground.activeCount} active
                                  </small>
                                </span>
                              </button>
                              {campgroundOpen && (
                                <div className="result-group-body nested">
                                  {campground.stays.map((stay) => {
                                    const stayOpen = isResultGroupOpen(stay.id);
                                    return (
                                      <section className="result-stay" key={stay.id}>
                                        <button
                                          aria-expanded={stayOpen}
                                          className="result-group-header stay"
                                          onClick={() => toggleResultGroup(stay.id)}
                                          type="button"
                                        >
                                          {stayOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                          <span className="result-group-title">
                                            <strong>{stay.label}</strong>
                                            <small>
                                              {stay.count} site{stay.count === 1 ? "" : "s"} &middot; {stay.activeCount} active
                                            </small>
                                          </span>
                                        </button>
                                        {stayOpen && (
                                          <div className="result-card-list">
                                            {stay.results.map(resultCard)}
                                          </div>
                                        )}
                                      </section>
                                    );
                                  })}
                                </div>
                              )}
                            </section>
                          );
                        })}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}

function SummaryMetric({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <article className="metric">
      <span>{icon}</span>
      <div>
        <strong>{value}</strong>
        <small>{label}</small>
      </div>
    </article>
  );
}
