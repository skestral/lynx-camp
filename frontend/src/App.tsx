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
  MapPinned,
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
  CampgroundDetails,
  ConfigBackup,
  NotificationEvent,
  NotificationConfig,
  NotificationConfigValues,
  NotificationStatus,
  PresetDiscoveryResult,
  PresetPack,
  ReleaseWindowProfileResult,
  Result,
  ResultSummary,
  ScanEvent,
  ScanConfig,
  ScanConfigValues,
  ScanRun,
  SearchSuggestion,
  SourceDefinition,
  SourceDiscoveryResult,
  Target,
  Watch
} from "./types";

type LoadState = "idle" | "loading" | "error";

type ResultView = "active" | "all" | Result["status"];
type ResultSort = "newest" | "arrival" | "park";
type DrawerMode = "alerts" | "activity" | "targets" | "watches" | "settings";
type PageView = "monitor" | "logs";
type UtilityTab = "release" | "activity" | "settings";
type WatchScope = "target" | "park" | "state" | "map";
type MapSelection =
  | { kind: "park"; parkName: string }
  | { kind: "campground"; campgroundId: string };
type ScanProgress = {
  title: string;
  detail: string;
};
type ScanConfigForm = Record<keyof ScanConfigValues, string>;
type NotificationConfigForm = Record<keyof NotificationConfigValues, string>;
type ScanControlField = {
  key: keyof ScanConfigValues;
  label: string;
  min: number;
  max: number;
  step: number;
  help: string;
};
type NotificationField = {
  key: keyof NotificationConfigValues;
  label: string;
  help: string;
  type?: "text" | "url" | "number" | "password";
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  secret?: boolean;
  wide?: boolean;
};

const DEFAULT_SCAN_CONFIG_VALUES: ScanConfigValues = {
  min_poll_interval_minutes: 10,
  release_scan_before_minutes: 15,
  release_scan_after_minutes: 60,
  release_scan_interval_minutes: 10,
  availability_cache_minutes: 5,
  api_request_delay_seconds: 1,
  rate_limit_backoff_minutes: 60
};

const SCAN_CONTROL_FIELDS: ScanControlField[] = [
  {
    key: "min_poll_interval_minutes",
    label: "Minimum scan interval",
    min: 1,
    max: 1440,
    step: 1,
    help: "Lowest interval any target or watch cadence can use."
  },
  {
    key: "release_scan_interval_minutes",
    label: "Release-window interval",
    min: 1,
    max: 1440,
    step: 1,
    help: "Temporary cadence while a watched stay is near its calculated release."
  },
  {
    key: "release_scan_before_minutes",
    label: "Release window starts",
    min: 0,
    max: 1440,
    step: 1,
    help: "Minutes before release time to begin the faster release cadence."
  },
  {
    key: "release_scan_after_minutes",
    label: "Release window ends",
    min: 0,
    max: 1440,
    step: 1,
    help: "Minutes after release time to keep the faster release cadence."
  },
  {
    key: "availability_cache_minutes",
    label: "Availability cache",
    min: 0,
    max: 1440,
    step: 1,
    help: "Minutes to reuse campground/month responses across similar watches."
  },
  {
    key: "api_request_delay_seconds",
    label: "Request delay",
    min: 0,
    max: 60,
    step: 0.25,
    help: "Seconds to wait between uncached Recreation.gov month requests."
  },
  {
    key: "rate_limit_backoff_minutes",
    label: "Rate-limit backoff",
    min: 1,
    max: 1440,
    step: 1,
    help: "Minutes to pause scans after Recreation.gov returns HTTP 429."
  }
];

function scanConfigFormFromValues(values: ScanConfigValues): ScanConfigForm {
  return {
    min_poll_interval_minutes: String(values.min_poll_interval_minutes),
    release_scan_before_minutes: String(values.release_scan_before_minutes),
    release_scan_after_minutes: String(values.release_scan_after_minutes),
    release_scan_interval_minutes: String(values.release_scan_interval_minutes),
    availability_cache_minutes: String(values.availability_cache_minutes),
    api_request_delay_seconds: String(values.api_request_delay_seconds),
    rate_limit_backoff_minutes: String(values.rate_limit_backoff_minutes)
  };
}

const DEFAULT_NOTIFICATION_CONFIG_VALUES: NotificationConfigValues = {
  webhook_url: "",
  home_assistant_webhook_url: "",
  ntfy_server: "https://ntfy.sh",
  ntfy_topic: "",
  ntfy_token: "",
  ntfy_priority: "high",
  smtp_host: "",
  smtp_port: 587,
  smtp_username: "",
  smtp_password: "",
  smtp_from: "",
  smtp_to: "",
  max_notification_results: 5
};

const WEBHOOK_NOTIFICATION_FIELDS: NotificationField[] = [
  {
    key: "webhook_url",
    label: "Discord or generic webhook URL",
    type: "url",
    secret: true,
    wide: true,
    placeholder: "https://discord.com/api/webhooks/...",
    help: "Sends the plain text availability summary to a Discord-compatible webhook."
  },
  {
    key: "home_assistant_webhook_url",
    label: "Home Assistant webhook URL",
    type: "url",
    secret: true,
    wide: true,
    placeholder: "https://homeassistant.local/api/webhook/...",
    help: "Sends structured JSON for Home Assistant automations."
  }
];

const NTFY_NOTIFICATION_FIELDS: NotificationField[] = [
  {
    key: "ntfy_server",
    label: "ntfy server",
    type: "url",
    placeholder: "https://ntfy.sh",
    help: "Server base URL for ntfy push notifications."
  },
  {
    key: "ntfy_topic",
    label: "ntfy topic",
    type: "password",
    secret: true,
    placeholder: "campfinder-alerts",
    help: "Topic to publish to. Leave blank to keep the current saved or environment topic."
  },
  {
    key: "ntfy_token",
    label: "ntfy token",
    type: "password",
    secret: true,
    placeholder: "Optional bearer token",
    help: "Optional access token for private ntfy topics."
  },
  {
    key: "ntfy_priority",
    label: "ntfy priority",
    placeholder: "high",
    help: "Priority header used for ntfy messages."
  }
];

const SMTP_NOTIFICATION_FIELDS: NotificationField[] = [
  {
    key: "smtp_host",
    label: "SMTP host",
    placeholder: "smtp.example.com",
    help: "Mail server hostname."
  },
  {
    key: "smtp_port",
    label: "SMTP port",
    type: "number",
    min: 1,
    max: 65535,
    step: 1,
    help: "TLS port for the SMTP server."
  },
  {
    key: "smtp_username",
    label: "SMTP username",
    type: "password",
    secret: true,
    placeholder: "Account username",
    help: "Leave blank to keep the current saved or environment username."
  },
  {
    key: "smtp_password",
    label: "SMTP password",
    type: "password",
    secret: true,
    placeholder: "App password",
    help: "Leave blank to keep the current saved or environment password."
  },
  {
    key: "smtp_from",
    label: "From address",
    placeholder: "campfinder@example.com",
    help: "Sender shown on email alerts."
  },
  {
    key: "smtp_to",
    label: "To address",
    placeholder: "you@example.com",
    help: "Recipient for email alerts."
  },
  {
    key: "max_notification_results",
    label: "Max results per alert",
    type: "number",
    min: 1,
    max: 100,
    step: 1,
    help: "Caps how many matches are listed in one notification."
  }
];

function notificationConfigFormFromValues(values: NotificationConfigValues): NotificationConfigForm {
  return {
    webhook_url: "",
    home_assistant_webhook_url: "",
    ntfy_server: String(values.ntfy_server || DEFAULT_NOTIFICATION_CONFIG_VALUES.ntfy_server),
    ntfy_topic: "",
    ntfy_token: "",
    ntfy_priority: String(values.ntfy_priority || DEFAULT_NOTIFICATION_CONFIG_VALUES.ntfy_priority),
    smtp_host: String(values.smtp_host || ""),
    smtp_port: String(values.smtp_port || DEFAULT_NOTIFICATION_CONFIG_VALUES.smtp_port),
    smtp_username: "",
    smtp_password: "",
    smtp_from: String(values.smtp_from || ""),
    smtp_to: String(values.smtp_to || ""),
    max_notification_results: String(
      values.max_notification_results || DEFAULT_NOTIFICATION_CONFIG_VALUES.max_notification_results
    )
  };
}

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
  activeResultCount: number;
  resultCount: number;
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
const washingtonMapBounds: L.LatLngBoundsExpression = [
  [45.45, -125.15],
  [49.1, -116.85]
];

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
  if (
    status === "needs_credentials" ||
    status === "cooldown" ||
    status === "manual_required" ||
    status === "cancelled" ||
    status === "interrupted" ||
    status === "rate_limited"
  )
    return "warning";
  if (status === "available" || status === "booked" || status === "ready") return "success";
  if (status === "clear" || status === "opened" || status === "running" || status === "directory" || status === "research") return "calm";
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

function isActiveCartAttempt(attempt: CartAttempt) {
  return ["manual_required", "opened", "hold_queued", "hold_attempted"].includes(attempt.status);
}

function cartAttemptRank(attempt: CartAttempt) {
  if (attempt.status === "manual_required" || attempt.status === "opened") return 0;
  if (attempt.status === "hold_queued" || attempt.status === "hold_attempted") return 1;
  if (["needs_credentials", "disabled", "cooldown", "failed"].includes(attempt.status)) return 2;
  return 3;
}

function cartAssistQueueSummary(status: CartAssistStatus | null) {
  if (!status) return "Waiting for queue status.";
  if (status.active_attempt_count > 0) {
    const readyLabel = status.ready_attempt_count === 1 ? "ready checkout task" : "ready checkout tasks";
    const activeLabel = status.active_attempt_count === 1 ? "active task" : "active tasks";
    return `${status.ready_attempt_count} ${readyLabel}; ${status.active_attempt_count} ${activeLabel} need a final decision.`;
  }
  if (status.blocked_attempt_count > 0) {
    const blockedLabel = status.blocked_attempt_count === 1 ? "blocked attempt" : "blocked attempts";
    return `No active checkout tasks. ${status.blocked_attempt_count} ${blockedLabel} remain in history.`;
  }
  return status.total_attempt_count > 0
    ? "No active checkout tasks. Recent attempts are resolved."
    : "No Cart Assist attempts have been created yet.";
}

function notificationChannelLabel(channel: string) {
  if (channel === "home_assistant") return "Home Assistant";
  if (channel === "ntfy") return "ntfy";
  return channel.replace(/_/g, " ");
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
  const bookingUrl = bookingUrlWithStartDate(result.booking_url, result.arrival_date);
  return [
    "Camp Finder booking details",
    `Campground: ${result.campground_name}`,
    `Watch: ${result.watch_name}`,
    `Site: ${result.site}`,
    result.loop ? `Loop: ${result.loop}` : "",
    result.campsite_type ? `Type: ${result.campsite_type}` : "",
    `Arrival: ${formatDate(result.arrival_date)}`,
    `Departure: ${formatDate(result.departure_date)}`,
    `Recreation.gov: ${bookingUrl}`,
  ]
    .filter(Boolean)
    .join("\n");
}

function bookingUrlWithStartDate(bookingUrl: string, arrivalDate: string) {
  const startDate = arrivalDate.slice(0, 10);
  if (!bookingUrl || !startDate) return bookingUrl;

  try {
    const url = new URL(bookingUrl);
    url.searchParams.set("startDate", startDate);
    return url.toString();
  } catch {
    const existingStartDate = /([?&]startDate=)[^&]*/;
    if (existingStartDate.test(bookingUrl)) {
      return bookingUrl.replace(existingStartDate, `$1${encodeURIComponent(startDate)}`);
    }
    const separator = bookingUrl.includes("?") ? "&" : "?";
    return `${bookingUrl}${separator}startDate=${encodeURIComponent(startDate)}`;
  }
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
  const [sources, setSources] = useState<SourceDefinition[]>([]);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [results, setResults] = useState<Result[]>([]);
  const [resultSummary, setResultSummary] = useState<ResultSummary>({ total_count: 0, active_count: 0 });
  const [scanRuns, setScanRuns] = useState<ScanRun[]>([]);
  const [scanEvents, setScanEvents] = useState<ScanEvent[]>([]);
  const [notifications, setNotifications] = useState<NotificationEvent[]>([]);
  const [notificationStatus, setNotificationStatus] = useState<NotificationStatus>({ channels: [] });
  const [notificationConfig, setNotificationConfig] = useState<NotificationConfig | null>(null);
  const [notificationConfigForm, setNotificationConfigForm] = useState<NotificationConfigForm>(
    notificationConfigFormFromValues(DEFAULT_NOTIFICATION_CONFIG_VALUES)
  );
  const [notificationConfigDirty, setNotificationConfigDirty] = useState(false);
  const [notificationConfigBusy, setNotificationConfigBusy] = useState<"save" | "clear" | null>(null);
  const [cartAssistStatus, setCartAssistStatus] = useState<CartAssistStatus | null>(null);
  const [cartAttempts, setCartAttempts] = useState<CartAttempt[]>([]);
  const [scanConfig, setScanConfig] = useState<ScanConfig | null>(null);
  const [scanConfigForm, setScanConfigForm] = useState<ScanConfigForm>(
    scanConfigFormFromValues(DEFAULT_SCAN_CONFIG_VALUES)
  );
  const [scanConfigDirty, setScanConfigDirty] = useState(false);
  const [scanConfigBusy, setScanConfigBusy] = useState<"save" | "reset" | null>(null);
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
  const [watchScope, setWatchScope] = useState<WatchScope>("target");
  const [watchPark, setWatchPark] = useState("");
  const [watchStateCode, setWatchStateCode] = useState("");
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
  const [scanCancelBusy, setScanCancelBusy] = useState(false);
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
  const [discoveringSourceId, setDiscoveringSourceId] = useState<string | null>(null);
  const [importingSourceId, setImportingSourceId] = useState<string | null>(null);
  const [sourceDiscovery, setSourceDiscovery] = useState<Record<string, SourceDiscoveryResult>>({});
  const [configBusy, setConfigBusy] = useState<"export" | "import" | null>(null);
  const [backupFile, setBackupFile] = useState<File | null>(null);
  const [includeSecretSettings, setIncludeSecretSettings] = useState(false);
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
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>("targets");
  const [pageView, setPageView] = useState<PageView>(() => (window.location.hash === "#logs" ? "logs" : "monitor"));
  const [utilityTab, setUtilityTab] = useState<UtilityTab>("release");
  const [mapSelection, setMapSelection] = useState<MapSelection | null>(null);
  const [campgroundDetails, setCampgroundDetails] = useState<Record<string, CampgroundDetails>>({});
  const [campgroundDetailsBusyId, setCampgroundDetailsBusyId] = useState<string | null>(null);
  const [campgroundDetailsErrors, setCampgroundDetailsErrors] = useState<Record<string, string>>({});
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
  const isLogsPage = pageView === "logs";
  const selectedResultSet = useMemo(() => new Set(selectedResultIds), [selectedResultIds]);
  const selectedResults = useMemo(
    () => results.filter((result) => selectedResultSet.has(result.id)),
    [results, selectedResultSet]
  );
  const cartAttemptByResultId = useMemo(
    () => new Map(cartAttempts.map((attempt) => [attempt.result_id, attempt])),
    [cartAttempts]
  );
  const prioritizedCartAttempts = useMemo(
    () =>
      [...cartAttempts].sort((left, right) => {
        const rankDelta = cartAttemptRank(left) - cartAttemptRank(right);
        if (rankDelta !== 0) return rankDelta;
        return right.attempted_at.localeCompare(left.attempted_at);
      }),
    [cartAttempts]
  );
  const nextCheckoutAttempt = useMemo(
    () => prioritizedCartAttempts.find((attempt) => attempt.status === "manual_required" || attempt.status === "opened") || null,
    [prioritizedCartAttempts]
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
  const latestScanEvent = scanEvents[0];
  const activeScanTitle = runningScan
    ? `Scanning ${runningScan.watch_name}`
    : scanProgress?.title || (latestScan ? `Last scan: ${latestScan.watch_name}` : "No scans yet");
  const activeScanDetail = runningScan ? (
    <>
      <span>{runningScan.target_name}</span>
      <span>started {formatDateTime(runningScan.started_at)}</span>
    </>
  ) : scanProgress?.detail ? (
    scanProgress.detail
  ) : latestScan ? (
    <>
      <span>{latestScan.target_name}</span>
      <span>
        {latestScan.candidate_count} stays &middot; {latestScan.available_count} matches &middot;{" "}
        {formatDateTime(latestScan.finished_at || latestScan.started_at)}
      </span>
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
  const sourceCoverage = useMemo(() => {
    const bundledIds = new Set<string>();
    const importedBundledIds = new Set<string>();
    const parkNames = new Set<string>();
    let checkedPacks = 0;
    let sourceNewCount = 0;
    let sourceMissingCount = 0;
    let checkedSourceDefinitions = 0;
    let sourceDefinitionNewCount = 0;

    for (const pack of presets) {
      const discovery = presetDiscovery[pack.id];
      if (discovery) {
        checkedPacks += 1;
        sourceNewCount += discovery.new_count;
        sourceMissingCount += discovery.missing_count;
      }
      for (const target of pack.targets) {
        bundledIds.add(target.campground_id);
        if (target.imported) importedBundledIds.add(target.campground_id);
        if (target.park_name) parkNames.add(target.park_name);
      }
    }
    for (const source of sources) {
      const discovery = sourceDiscovery[source.id];
      if (discovery) {
        checkedSourceDefinitions += 1;
        sourceDefinitionNewCount += discovery.new_count;
      }
    }

    return {
      packCount: presets.length,
      parkCount: parkNames.size,
      bundledTargetCount: bundledIds.size,
      importedBundledCount: importedBundledIds.size,
      sourceDefinitionCount: sources.length,
      readySourceDefinitionCount: sources.filter((source) => source.discover_supported).length,
      checkedPacks,
      sourceNewCount,
      sourceMissingCount,
      checkedSourceDefinitions,
      sourceDefinitionNewCount
    };
  }, [presetDiscovery, presets, sourceDiscovery, sources]);
  const nextReleaseHint = latestRelease[0] || null;
  const focusSummary = scanInProgress
    ? `${runningScanRuns.length || 1} scan${(runningScanRuns.length || 1) === 1 ? "" : "s"} running now.`
    : activeResultCount > 0
      ? `${activeResultCount} active match${activeResultCount === 1 ? "" : "es"} ready for review.`
      : activeWatches.length > 0
        ? `${activeWatches.length} active watch${activeWatches.length === 1 ? "" : "es"} covering ${activeTargets.length} campground${activeTargets.length === 1 ? "" : "s"}.`
        : targets.length > 0
          ? `${targets.length} campground target${targets.length === 1 ? "" : "s"} saved.`
          : "No campground targets saved yet.";
  const sourceSummary =
    sourceCoverage.checkedSourceDefinitions > 0
      ? `${sourceCoverage.checkedSourceDefinitions} source catalog check${sourceCoverage.checkedSourceDefinitions === 1 ? "" : "s"} run, ${sourceCoverage.sourceDefinitionNewCount} new target${sourceCoverage.sourceDefinitionNewCount === 1 ? "" : "s"} found.`
      : sourceCoverage.checkedPacks > 0
      ? `${sourceCoverage.checkedPacks} live source check${sourceCoverage.checkedPacks === 1 ? "" : "s"} run, ${sourceCoverage.sourceNewCount} new target${sourceCoverage.sourceNewCount === 1 ? "" : "s"} found.`
      : `${sourceCoverage.readySourceDefinitionCount} ready source${sourceCoverage.readySourceDefinitionCount === 1 ? "" : "s"} across ${sourceCoverage.packCount} preset pack${sourceCoverage.packCount === 1 ? "" : "s"}.`;
  const sourceGroups = useMemo(() => {
    const grouped = new Map<string, SourceDefinition[]>();
    for (const source of sources) {
      const category = source.category || "Other sources";
      grouped.set(category, [...(grouped.get(category) || []), source]);
    }
    return Array.from(grouped.entries()).map(([category, items]) => ({
      category,
      items: items.sort((a, b) => a.name.localeCompare(b.name))
    }));
  }, [sources]);
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
          targetId: savedTarget?.id || null,
          campgroundId: sourceTarget.campground_id,
          name: savedTarget?.name || sourceTarget.name,
          parkName,
          stateCode,
          latitude,
          longitude,
          active: savedTarget?.active || 0,
          imported: Boolean(savedTarget),
          bookingUrl: savedTarget?.booking_url || `https://www.recreation.gov/camping/campgrounds/${sourceTarget.campground_id}`,
          activeResultCount: resultCounts.activeResultCount,
          resultCount: resultCounts.resultCount
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
  const targetById = useMemo(() => new Map(targets.map((target) => [target.id, target])), [targets]);
  const watchParkOptions = useMemo(
    () =>
      parkSummaries
        .filter((summary) => summary.campgrounds.some((campground) => campground.imported && campground.active))
        .map((summary) => ({
          value: summary.parkName,
          label: summary.parkName,
          count: summary.campgrounds.filter((campground) => campground.imported && campground.active).length
        })),
    [parkSummaries]
  );
  const watchStateOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const target of activeTargets) {
      const state = target.state_code || "US";
      counts.set(state, (counts.get(state) || 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([value, count]) => ({ value, count }));
  }, [activeTargets]);
  const selectedMapPark = useMemo(
    () =>
      mapSelection?.kind === "park"
        ? parkSummaries.find((summary) => summary.parkName === mapSelection.parkName) || null
        : null,
    [mapSelection, parkSummaries]
  );
  const selectedMapCampground = useMemo(
    () =>
      mapSelection?.kind === "campground"
        ? parkSummaries
            .flatMap((summary) => summary.campgrounds)
            .find((campground) => campground.campgroundId === mapSelection.campgroundId) || null
        : null,
    [mapSelection, parkSummaries]
  );
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
    if (pageView !== "monitor") return;
    if (!mapElementRef.current || leafletMapRef.current) return;

    const map = L.map(mapElementRef.current, {
      scrollWheelZoom: false,
      zoomControl: true
    }).fitBounds(washingtonMapBounds, { padding: [10, 10] });
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
  }, [pageView]);

  useEffect(() => {
    if (pageView !== "monitor") return;
    if (!mapElementRef.current) return;
    const observer = new ResizeObserver(() => {
      leafletMapRef.current?.invalidateSize();
    });
    observer.observe(mapElementRef.current);
    return () => observer.disconnect();
  }, [pageView]);

  useEffect(() => {
    const map = leafletMapRef.current;
    const markerLayer = markerLayerRef.current;
    if (!map || !markerLayer) return;

    markerLayer.clearLayers();
    const selectedBounds = L.latLngBounds([]);
    const query = resultQuery.trim().toLowerCase();

    for (const summary of parkSummaries) {
      const selectedPark =
        resultQuery === summary.parkName || (mapSelection?.kind === "park" && mapSelection.parkName === summary.parkName);
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
          setMapSelection({ kind: "park", parkName: summary.parkName });
          setResultQuery(summary.parkName);
          setResultSort("park");
          setResultView(summary.activeResultCount > 0 ? "active" : "all");
          setResultGroupOpen((current) => ({ ...current, [`park:${summary.parkName}`]: true }));
        });
      if (query && selectedPark) {
        selectedBounds.extend([summary.latitude, summary.longitude]);
      }

      for (const campground of summary.campgrounds) {
        const selectedCampground =
          resultQuery === campground.name ||
          (mapSelection?.kind === "campground" && mapSelection.campgroundId === campground.campgroundId);
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
            setMapSelection({ kind: "campground", campgroundId: campground.campgroundId });
            setResultQuery(campground.name);
            setResultSort("park");
            setResultView(campground.activeResultCount > 0 ? "active" : "all");
            setResultGroupOpen((current) => ({
              ...current,
              [`park:${campground.parkName}`]: true,
              [`campground:${campground.parkName}:${campground.name}`]: true
            }));
          });
        if (query && (selectedPark || selectedCampground)) {
          selectedBounds.extend([campground.latitude, campground.longitude]);
        }
      }
    }

    if (selectedBounds.isValid()) {
      map.fitBounds(selectedBounds.pad(0.2), { maxZoom: 9 });
    } else {
      map.fitBounds(washingtonMapBounds, { padding: [10, 10] });
    }
  }, [mapSelection, parkSummaries, resultQuery]);

  async function refresh(options?: { silent?: boolean }) {
    if (!options?.silent) setLoadState("loading");
    try {
      const [
        targetData,
        presetData,
        sourceData,
        watchData,
        resultData,
        resultSummaryData,
        scanRunData,
        scanEventData,
        scanConfigData,
        notificationData,
        notificationStatusData,
        notificationConfigData,
        cartAssistStatusData,
        cartAttemptData
      ] = await Promise.all([
        api.targets(),
        api.presets(),
        api.sources(),
        api.watches(),
        api.results(),
        api.resultSummary(),
        api.scanRuns(),
        api.scanEvents(),
        api.scanConfig(),
        api.notifications(),
        api.notificationStatus(),
        api.notificationConfig(),
        api.cartAssistStatus(),
        api.cartAttempts()
      ]);
      setTargets(targetData);
      setPresets(presetData);
      setSources(sourceData);
      setWatches(watchData);
      setResults(resultData);
      setResultSummary(resultSummaryData);
      setScanRuns(scanRunData);
      setScanEvents(scanEventData);
      setScanConfig(scanConfigData);
      setNotifications(notificationData);
      setNotificationStatus(notificationStatusData);
      setNotificationConfig(notificationConfigData);
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
    const syncPageFromHash = () => {
      const nextPage = window.location.hash === "#logs" ? "logs" : "monitor";
      setPageView(nextPage);
      if (nextPage === "logs") setDrawerOpen(false);
    };
    syncPageFromHash();
    window.addEventListener("hashchange", syncPageFromHash);
    return () => window.removeEventListener("hashchange", syncPageFromHash);
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
        const [scanRunData, scanEventData, resultData, resultSummaryData, cartAttemptData] = await Promise.all([
          api.scanRuns(),
          api.scanEvents(),
          api.results(),
          api.resultSummary(),
          api.cartAttempts()
        ]);
        setScanRuns(scanRunData);
        setScanEvents(scanEventData);
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
    if (!notificationConfig || notificationConfigDirty || notificationConfigBusy) return;
    setNotificationConfigForm(notificationConfigFormFromValues(notificationConfig.values));
  }, [notificationConfig, notificationConfigBusy, notificationConfigDirty]);

  useEffect(() => {
    if (!scanConfig || scanConfigDirty || scanConfigBusy) return;
    setScanConfigForm(scanConfigFormFromValues(scanConfig.values));
  }, [scanConfig, scanConfigBusy, scanConfigDirty]);

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

  useEffect(() => {
    if (!watchPark && watchParkOptions.length > 0) {
      setWatchPark(watchParkOptions[0].value);
    }
  }, [watchPark, watchParkOptions]);

  useEffect(() => {
    if (!watchStateCode && watchStateOptions.length > 0) {
      setWatchStateCode(watchStateOptions[0].value);
    }
  }, [watchStateCode, watchStateOptions]);

  useEffect(() => {
    if (
      !selectedMapCampground ||
      campgroundDetails[selectedMapCampground.campgroundId] ||
      campgroundDetailsErrors[selectedMapCampground.campgroundId]
    ) {
      return;
    }
    let cancelled = false;
    setCampgroundDetailsBusyId(selectedMapCampground.campgroundId);
    api
      .campgroundDetails(selectedMapCampground.campgroundId)
      .then((details) => {
        if (cancelled) return;
        setCampgroundDetails((current) => ({ ...current, [selectedMapCampground.campgroundId]: details }));
      })
      .catch((error) => {
        if (cancelled) return;
        setCampgroundDetailsErrors((current) => ({
          ...current,
          [selectedMapCampground.campgroundId]:
            error instanceof Error ? error.message : "Campground details are unavailable."
        }));
      })
      .finally(() => {
        if (!cancelled) setCampgroundDetailsBusyId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [campgroundDetails, campgroundDetailsErrors, selectedMapCampground]);

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
    setWatchScope("target");
    setCartAssistEnabled(false);
  }

  function editWatch(watch: Watch) {
    setEditingWatchId(watch.id);
    setWatchName(watch.name);
    setWatchScope("target");
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

  async function discoverSource(sourceId: string) {
    setDiscoveringSourceId(sourceId);
    setMessage("");
    try {
      const result = await api.discoverSource(sourceId);
      setSourceDiscovery((current) => ({ ...current, [sourceId]: result }));
      setMessage(
        `${result.source_name}: source returned ${result.discovered_count} campground${result.discovered_count === 1 ? "" : "s"}; ${result.new_count} not imported yet.`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Source catalog check failed.");
    } finally {
      setDiscoveringSourceId(null);
    }
  }

  async function importSource(sourceId: string) {
    setImportingSourceId(sourceId);
    setMessage("");
    try {
      const result = await api.importSource(sourceId);
      setSourceDiscovery((current) => ({ ...current, [sourceId]: result.discovery }));
      setMessage(
        `Imported ${result.imported_count} source target${result.imported_count === 1 ? "" : "s"} from ${result.source_name}; updated ${result.updated_count}.`
      );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Source catalog import failed.");
    } finally {
      setImportingSourceId(null);
    }
  }

  async function downloadConfigBackup() {
    setConfigBusy("export");
    setMessage("");
    try {
      const backup = await api.exportConfig(includeSecretSettings);
      const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `campfinder-backup-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      const settingCount = Object.keys(backup.settings?.app_settings || {}).length;
      const redactedCount = backup.settings?.redacted_keys?.length || 0;
      setMessage(
        `Downloaded backup with ${backup.targets.length} target${backup.targets.length === 1 ? "" : "s"} ` +
          `and ${settingCount} saved setting${settingCount === 1 ? "" : "s"}` +
          (redactedCount > 0 ? `; ${redactedCount} secret${redactedCount === 1 ? "" : "s"} omitted.` : ".")
      );
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
      const importedSettings = result.imported_settings || 0;
      const skippedSettings = result.skipped_settings || 0;
      setMessage(
        `Restored ${result.target_count} target${result.target_count === 1 ? "" : "s"}; ` +
          `${result.created_watches} new watch${result.created_watches === 1 ? "" : "es"}, ` +
          `${result.updated_watches} updated; ${importedSettings} setting${importedSettings === 1 ? "" : "s"} restored` +
          (skippedSettings > 0 ? `, ${skippedSettings} skipped.` : ".")
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
    const selectedTargets = selectedWatchTargets();
    if (selectedTargets.length === 0) {
      setMessage(
        watchScope === "map"
          ? "Move the map over imported active targets before creating a map-view watch."
          : "Choose at least one imported active target for this watch."
      );
      return;
    }
    const isSpecific = watchMode === "specific";
    if (!isSpecific && selectedWeekdays.length === 0) {
      setMessage("Choose at least one arrival day.");
      return;
    }
    const baseName = watchName.trim() || generatedWatchName(isSpecific);
    const payload = {
      target_id: selectedTargets[0].id,
      name: baseName,
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
      let createdCount = 0;
      let skippedCount = 0;
      const existingSignatures = new Set(
        watches.map((watch) =>
          [
            watch.target_id,
            watch.name,
            watch.mode,
            watch.pattern,
            watch.window_start,
            watch.window_end,
            JSON.stringify(watch.arrival_weekdays || []),
            JSON.stringify(watch.specific_ranges || []),
            JSON.stringify(watch.site_filters || {})
          ].join("|")
        )
      );
      for (const target of selectedTargets) {
        const targetPayload = { ...payload, target_id: target.id };
        const signature = [
          targetPayload.target_id,
          targetPayload.name,
          targetPayload.mode,
          targetPayload.pattern,
          targetPayload.window_start,
          targetPayload.window_end,
          JSON.stringify(targetPayload.arrival_weekdays || []),
          JSON.stringify(targetPayload.specific_ranges || []),
          JSON.stringify(targetPayload.site_filters || {})
        ].join("|");
        if (existingSignatures.has(signature)) {
          skippedCount += 1;
          continue;
        }
        await api.createWatch(targetPayload);
        existingSignatures.add(signature);
        createdCount += 1;
      }
      setMessage(
        selectedTargets.length === 1
          ? createdCount
            ? `Added ${baseName}.`
            : `Skipped ${baseName}; an identical watch already exists.`
          : `Added ${createdCount} region watch rule${createdCount === 1 ? "" : "s"}` +
              (skippedCount ? `; skipped ${skippedCount} duplicate${skippedCount === 1 ? "" : "s"}.` : ".")
      );
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

  async function cancelScans() {
    setScanCancelBusy(true);
    setMessage("");
    try {
      const result = await api.cancelScans();
      setScanAllBusy(false);
      setScanBusyId(null);
      setScanProgress(null);
      const staleMessage =
        result.stale_cancelled_count > 0
          ? ` Marked ${result.stale_cancelled_count} stale run${result.stale_cancelled_count === 1 ? "" : "s"} as cancelled.`
          : "";
      setMessage(
        result.cancel_requested
          ? `Stop requested for the active scan.${staleMessage}`
          : `No active scanner was running.${staleMessage}`
      );
      await refresh({ silent: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to stop scan.");
    } finally {
      setScanCancelBusy(false);
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

  async function saveNotificationConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotificationConfigBusy("save");
    try {
      const payload: Partial<NotificationConfigValues> = {
        ntfy_server: notificationConfigForm.ntfy_server.trim(),
        ntfy_priority: notificationConfigForm.ntfy_priority.trim(),
        smtp_host: notificationConfigForm.smtp_host.trim(),
        smtp_port: Math.round(notificationConfigNumber("smtp_port")),
        smtp_from: notificationConfigForm.smtp_from.trim(),
        smtp_to: notificationConfigForm.smtp_to.trim(),
        max_notification_results: Math.round(notificationConfigNumber("max_notification_results"))
      };
      const secretFields = [
        "webhook_url",
        "home_assistant_webhook_url",
        "ntfy_topic",
        "ntfy_token",
        "smtp_username",
        "smtp_password"
      ] as const;
      const secretPayload: Partial<Record<(typeof secretFields)[number], string>> = {};
      secretFields.forEach((key) => {
        const value = notificationConfigForm[key].trim();
        if (value) secretPayload[key] = value;
      });
      const config = await api.updateNotificationConfig({ ...payload, ...secretPayload });
      setNotificationConfig(config);
      setNotificationConfigForm(notificationConfigFormFromValues(config.values));
      setNotificationConfigDirty(false);
      setMessage("Saved notification settings.");
      await refresh({ silent: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save notification settings.");
    } finally {
      setNotificationConfigBusy(null);
    }
  }

  async function clearNotificationSecrets() {
    const confirmed = window.confirm("Clear stored notification webhooks, topics, tokens, usernames, and passwords from appdata?");
    if (!confirmed) return;
    setNotificationConfigBusy("clear");
    try {
      const config = await api.clearNotificationSecrets();
      setNotificationConfig(config);
      setNotificationConfigForm(notificationConfigFormFromValues(config.values));
      setNotificationConfigDirty(false);
      setMessage("Cleared stored notification secrets.");
      await refresh({ silent: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to clear notification secrets.");
    } finally {
      setNotificationConfigBusy(null);
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

  function updateScanConfigFormValue(key: keyof ScanConfigValues, value: string) {
    setScanConfigForm((current) => ({ ...current, [key]: value }));
    setScanConfigDirty(true);
  }

  function updateNotificationConfigFormValue(key: keyof NotificationConfigValues, value: string) {
    setNotificationConfigForm((current) => ({ ...current, [key]: value }));
    setNotificationConfigDirty(true);
  }

  function notificationConfigNumber(key: keyof NotificationConfigValues): number {
    const value = Number(notificationConfigForm[key]);
    if (Number.isFinite(value)) return value;
    const fallback = notificationConfig?.values[key] ?? DEFAULT_NOTIFICATION_CONFIG_VALUES[key];
    return Number(fallback) || Number(DEFAULT_NOTIFICATION_CONFIG_VALUES[key]);
  }

  function scanConfigNumber(key: keyof ScanConfigValues): number {
    const value = Number(scanConfigForm[key]);
    if (Number.isFinite(value)) return value;
    return scanConfig?.values[key] ?? DEFAULT_SCAN_CONFIG_VALUES[key];
  }

  async function saveScanConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setScanConfigBusy("save");
    try {
      const config = await api.updateScanConfig({
        min_poll_interval_minutes: Math.round(scanConfigNumber("min_poll_interval_minutes")),
        release_scan_before_minutes: Math.round(scanConfigNumber("release_scan_before_minutes")),
        release_scan_after_minutes: Math.round(scanConfigNumber("release_scan_after_minutes")),
        release_scan_interval_minutes: Math.round(scanConfigNumber("release_scan_interval_minutes")),
        availability_cache_minutes: Math.round(scanConfigNumber("availability_cache_minutes")),
        api_request_delay_seconds: scanConfigNumber("api_request_delay_seconds"),
        rate_limit_backoff_minutes: Math.round(scanConfigNumber("rate_limit_backoff_minutes"))
      });
      setScanConfig(config);
      setScanConfigForm(scanConfigFormFromValues(config.values));
      setScanConfigDirty(false);
      setMessage("Saved scan controls. New scans use these settings immediately.");
      await refresh({ silent: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save scan controls.");
    } finally {
      setScanConfigBusy(null);
    }
  }

  async function resetScanConfigToEnvironment() {
    const confirmed = window.confirm("Reset scan controls to the server environment defaults?");
    if (!confirmed) return;
    setScanConfigBusy("reset");
    try {
      const config = await api.resetScanConfig();
      setScanConfig(config);
      setScanConfigForm(scanConfigFormFromValues(config.values));
      setScanConfigDirty(false);
      setMessage("Reset scan controls to environment defaults.");
      await refresh({ silent: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to reset scan controls.");
    } finally {
      setScanConfigBusy(null);
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

  function openCartAttemptBooking(attempt: CartAttempt) {
    if (attempt.status === "manual_required") {
      void updateCartAttemptStatus(attempt, "opened");
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

  function openDrawer(mode: DrawerMode) {
    setDrawerMode(mode);
    setDrawerOpen(true);
  }

  function scrollToResults() {
    setDrawerOpen(false);
    setPageView("monitor");
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#results`);
    window.setTimeout(() => {
      const results = document.getElementById("results");
      if (!results) return;
      const targetTop = results.getBoundingClientRect().top + window.scrollY;
      window.scrollTo({ top: targetTop, behavior: "auto" });
    }, 0);
  }

  function focusPark(summary: ParkSummary) {
    setMapSelection({ kind: "park", parkName: summary.parkName });
    setResultQuery(summary.parkName);
    setResultSort("park");
    setResultView(summary.activeResultCount > 0 ? "active" : "all");
    setResultGroupOpen((current) => ({ ...current, [`park:${summary.parkName}`]: true }));
    scrollToResults();
  }

  function focusCampgroundResults(campground: CampgroundMapPoint) {
    setMapSelection({ kind: "campground", campgroundId: campground.campgroundId });
    setResultQuery(campground.name);
    setResultSort("park");
    setResultView(campground.activeResultCount > 0 ? "active" : "all");
    setResultGroupOpen((current) => ({
      ...current,
      [`park:${campground.parkName}`]: true,
      [`campground:${campground.parkName}:${campground.name}`]: true
    }));
    scrollToResults();
  }

  function activeTargetsInMapView() {
    const map = leafletMapRef.current;
    if (!map) return [];
    const bounds = map.getBounds();
    return activeTargets.filter((target) => {
      const latitude = Number(target.latitude);
      const longitude = Number(target.longitude);
      return Number.isFinite(latitude) && Number.isFinite(longitude) && bounds.contains([latitude, longitude]);
    });
  }

  function selectedWatchTargets() {
    if (editingWatchId || watchScope === "target") {
      const target = targetById.get(Number(watchTarget));
      return target ? [target] : [];
    }
    if (watchScope === "park") {
      return activeTargets.filter((target) => (target.park_name || "Unassigned park") === watchPark);
    }
    if (watchScope === "state") {
      return activeTargets.filter((target) => (target.state_code || "US") === watchStateCode);
    }
    return activeTargetsInMapView();
  }

  function watchScopeSummary() {
    const selected = selectedWatchTargets();
    if (editingWatchId) return "Editing one existing watch.";
    if (watchScope === "target") return "Creates one watch for the selected campground.";
    if (watchScope === "park") return `Creates ${selected.length} watch rule${selected.length === 1 ? "" : "s"} across ${watchPark || "this park"}.`;
    if (watchScope === "state") return `Creates ${selected.length} watch rule${selected.length === 1 ? "" : "s"} across ${watchStateCode || "this state"}.`;
    return `Creates ${selected.length} watch rule${selected.length === 1 ? "" : "s"} inside the current map view.`;
  }

  function openWatchBuilderForPark(parkName: string) {
    setWatchScope("park");
    setWatchPark(parkName);
    setEditingWatchId(null);
    openDrawer("watches");
  }

  function openWatchBuilderForCampground(campground: CampgroundMapPoint) {
    if (!campground.targetId) {
      setMessage("Import this campground as a target before creating a watch.");
      return;
    }
    setWatchScope("target");
    setWatchTarget(String(campground.targetId));
    setEditingWatchId(null);
    openDrawer("watches");
  }

  function openWatchBuilderForMapView() {
    setWatchScope("map");
    setEditingWatchId(null);
    const count = activeTargetsInMapView().length;
    setMessage(
      count > 0
        ? `Map-view watch will use ${count} active imported target${count === 1 ? "" : "s"} in the current map window.`
        : "Move the map over active imported targets before creating a map-view watch."
    );
    openDrawer("watches");
  }

  async function importCampgroundFromMap(campground: CampgroundMapPoint) {
    setMessage("");
    try {
      const target = await api.createTarget({
        name: campground.name,
        campground_id: campground.campgroundId,
        park_name: campground.parkName,
        state_code: campground.stateCode,
        latitude: campground.latitude,
        longitude: campground.longitude,
        booking_url: campground.bookingUrl,
        release_months: 6,
        release_window_value: 6,
        release_window_unit: "Months",
        release_time: "07:00",
        timezone: campground.stateCode === "MT" || campground.stateCode === "WY" ? "America/Denver" : "America/Los_Angeles",
        poll_interval_minutes: scanConfig?.values.min_poll_interval_minutes || 10,
        active: true
      });
      setWatchTarget(String(target.id));
      setWatchScope("target");
      setMessage(`Imported ${target.name}.`);
      await refresh({ silent: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to import campground.");
    }
  }

  function renderMapSelectionPanel() {
    if (selectedMapPark) {
      const activeImportedCount = selectedMapPark.campgrounds.filter((campground) => campground.imported && campground.active).length;
      const previewCampgrounds = selectedMapPark.campgrounds.slice(0, 5);

      return (
        <section className="map-detail" aria-label="Selected park details">
          <div className="map-detail-header">
            <span className="map-detail-icon">
              <MapPinned size={18} />
            </span>
            <span>
              <strong>{selectedMapPark.parkName}</strong>
              <small>
                {selectedMapPark.targetCount} campground{selectedMapPark.targetCount === 1 ? "" : "s"} shown{" "}
                &middot; {activeImportedCount} active target{activeImportedCount === 1 ? "" : "s"}
              </small>
            </span>
          </div>
          <div className="map-detail-facts">
            <span>{selectedMapPark.stateCodes}</span>
            <span>{selectedMapPark.activeResultCount} active matches</span>
            <span>{selectedMapPark.resultCount} loaded results</span>
          </div>
          <div className="map-detail-list">
            {previewCampgrounds.map((campground) => (
              <button key={campground.campgroundId} onClick={() => setMapSelection({ kind: "campground", campgroundId: campground.campgroundId })} type="button">
                <span>{campground.name}</span>
                <small>{campground.imported ? "target" : "preset"}</small>
              </button>
            ))}
          </div>
          <div className="map-detail-actions">
            <button className="icon-button primary" disabled={activeImportedCount === 0} onClick={() => openWatchBuilderForPark(selectedMapPark.parkName)} type="button">
              <CalendarDays size={16} />
              <span>Watch Park</span>
            </button>
            <button className="icon-button" onClick={() => focusPark(selectedMapPark)} type="button">
              <ListChecks size={16} />
              <span>View Results</span>
            </button>
          </div>
        </section>
      );
    }

    if (selectedMapCampground) {
      const details = campgroundDetails[selectedMapCampground.campgroundId];
      const loading = campgroundDetailsBusyId === selectedMapCampground.campgroundId;
      const detailError = campgroundDetailsErrors[selectedMapCampground.campgroundId] || "";
      const description =
        details?.description ||
        (selectedMapCampground.imported
          ? "Saved campground target. Recreation.gov details will appear here when available."
          : "Preset campground option. Import it as a target before adding a recurring watch.");
      const detailUrl = details?.detail_url || selectedMapCampground.bookingUrl;
      const mapTags = Array.from(new Set([...(details?.activities || []), ...(details?.amenities || [])])).slice(0, 8);
      const factRows = [
        selectedMapCampground.parkName,
        selectedMapCampground.stateCode,
        details?.phone,
        details?.address,
        details?.timezone
      ].filter((fact): fact is string => Boolean(fact));

      return (
        <section className="map-detail" aria-label="Selected campground details">
          <div className="map-detail-media">
            {details?.image_url ? (
              <img alt={`${selectedMapCampground.name} campground`} src={details.image_url} />
            ) : (
              <div className="map-detail-placeholder">
                <TentTree size={28} />
                <span>{loading ? "Loading Recreation.gov details" : "No campground image provided"}</span>
              </div>
            )}
          </div>
          <div className="map-detail-header">
            <span className="map-detail-icon">
              <MapPin size={18} />
            </span>
            <span>
              <strong>{selectedMapCampground.name}</strong>
              <small>{selectedMapCampground.imported ? "Imported target" : "Preset target"}</small>
            </span>
          </div>
          <p className="map-detail-copy">{loading ? "Loading the latest campground overview from Recreation.gov." : description}</p>
          {detailError && !loading && <p className="map-detail-error">{detailError}</p>}
          <div className="map-detail-facts">
            {factRows.map((fact) => (
              <span key={fact}>{fact}</span>
            ))}
            <span>{selectedMapCampground.activeResultCount} active matches</span>
          </div>
          {mapTags.length > 0 && (
            <div className="map-detail-tags">
              {mapTags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
          )}
          {details?.notices?.length ? (
            <div className="map-detail-notices">
              {details.notices.map((notice) => (
                <small key={notice}>{notice}</small>
              ))}
            </div>
          ) : null}
          <div className="map-detail-actions">
            {selectedMapCampground.imported ? (
              <button className="icon-button primary" onClick={() => openWatchBuilderForCampground(selectedMapCampground)} type="button">
                <CalendarDays size={16} />
                <span>Watch Campground</span>
              </button>
            ) : (
              <button className="icon-button primary" onClick={() => void importCampgroundFromMap(selectedMapCampground)} type="button">
                <Plus size={16} />
                <span>Import Target</span>
              </button>
            )}
            <button className="icon-button" onClick={() => focusCampgroundResults(selectedMapCampground)} type="button">
              <ListChecks size={16} />
              <span>View Results</span>
            </button>
            <a className="icon-button" href={detailUrl} rel="noreferrer" target="_blank">
              <ExternalLink size={16} />
              <span>Details</span>
            </a>
          </div>
        </section>
      );
    }

    return (
      <section className="map-detail empty-selection" aria-label="Map selection details">
        <div className="map-detail-header">
          <span className="map-detail-icon">
            <MapPin size={18} />
          </span>
          <span>
            <strong>Select a marker</strong>
            <small>Campground details, Recreation.gov links, and watch actions appear here.</small>
          </span>
        </div>
        <button className="icon-button" onClick={openWatchBuilderForMapView} type="button">
          <MapPinned size={16} />
          <span>Watch Current Map View</span>
        </button>
      </section>
    );
  }

  function renderNotificationField(field: NotificationField) {
    const source = notificationConfig?.sources?.[field.key] || "none";
    const configured = Boolean(notificationConfig?.configured?.[field.key]);
    const placeholder =
      field.secret && configured
        ? `Configured from ${source}; paste a new value to replace`
        : field.placeholder || "";

    return (
      <label className={field.wide ? "wide-field" : ""} key={field.key}>
        <span className="scan-field-heading">
          <span>{field.label}</span>
          <small>{configured ? source : "none"}</small>
        </span>
        <input
          autoComplete="off"
          inputMode={field.type === "url" ? "url" : field.type === "number" ? "decimal" : "text"}
          max={field.max}
          min={field.min}
          onChange={(event) => updateNotificationConfigFormValue(field.key, event.target.value)}
          placeholder={placeholder}
          step={field.step}
          type={field.type || "text"}
          value={notificationConfigForm[field.key]}
        />
        <small>{field.help}</small>
      </label>
    );
  }

  function renderNotificationSection(title: string, detail: string, fields: NotificationField[]) {
    return (
      <div className="notification-fieldset">
        <div className="notification-fieldset-heading">
          <strong>{title}</strong>
          <small>{detail}</small>
        </div>
        <div className="notification-config-grid">{fields.map((field) => renderNotificationField(field))}</div>
      </div>
    );
  }

  function renderNotificationControls() {
    const configuredChannelCount = notificationStatus.channels.filter((channel) => channel.configured).length;
    const secretFields = notificationConfig?.secret_fields || [];
    const savedSecretCount = secretFields.filter(
      (key) => notificationConfig?.sources?.[key] === "appdata" && notificationConfig?.configured?.[key]
    ).length;
    const sourceSummary = notificationConfig
      ? `${configuredChannelCount} channel${configuredChannelCount === 1 ? "" : "s"} ready`
      : "Loading notification settings";

    return (
      <div className="notification-config-panel">
        <div className="subheading scan-control-heading">
          <span>
            <strong>Notification Settings</strong>
            <small>Saved values override environment defaults for webhooks, ntfy, email, and alert size.</small>
          </span>
          <span className={`status ${configuredChannelCount > 0 ? "success" : "quiet"}`}>{sourceSummary}</span>
        </div>
        <form className="notification-config-form" onSubmit={saveNotificationConfig}>
          {renderNotificationSection("Webhooks", "Discord-compatible and Home Assistant endpoints.", WEBHOOK_NOTIFICATION_FIELDS)}
          {renderNotificationSection("ntfy", "Push topic, server, priority, and token.", NTFY_NOTIFICATION_FIELDS)}
          {renderNotificationSection("SMTP Email", "Server, mailbox credentials, recipient, and batch size.", SMTP_NOTIFICATION_FIELDS)}
          <div className="notification-config-actions wide-field">
            <button className="icon-button" disabled={notificationConfigBusy !== null} type="submit">
              <Save size={17} />
              <span>{notificationConfigBusy === "save" ? "Saving" : "Save Notifications"}</span>
            </button>
            <button
              className="icon-button"
              disabled={notificationConfigBusy !== null || savedSecretCount === 0}
              onClick={clearNotificationSecrets}
              type="button"
            >
              <Trash2 size={17} />
              <span>{notificationConfigBusy === "clear" ? "Clearing" : "Clear Secrets"}</span>
            </button>
          </div>
        </form>
      </div>
    );
  }

  function renderScanControls() {
    const appdataFieldCount = scanConfig
      ? Object.values(scanConfig.sources).filter((source) => source === "appdata").length
      : 0;
    const sourceSummary = scanConfig
      ? appdataFieldCount > 0
        ? `${appdataFieldCount} saved override${appdataFieldCount === 1 ? "" : "s"} active`
        : "Using environment defaults"
      : "Loading scan controls";

    return (
      <div className="scan-control-panel">
        <div className="subheading scan-control-heading">
          <span>
            <strong>Scan Controls</strong>
            <small>Adjust background cadence, release scanning, caching, and rate-limit recovery.</small>
          </span>
          <span className={`status ${appdataFieldCount > 0 ? "warning" : "quiet"}`}>{sourceSummary}</span>
        </div>
        <form className="scan-control-form" onSubmit={saveScanConfig}>
          {SCAN_CONTROL_FIELDS.map((field) => {
            const source = scanConfig?.sources[field.key] || "environment";
            return (
              <label key={field.key}>
                <span className="scan-field-heading">
                  <span>{field.label}</span>
                  <small>{source}</small>
                </span>
                <input
                  max={field.max}
                  min={field.min}
                  onChange={(event) => updateScanConfigFormValue(field.key, event.target.value)}
                  step={field.step}
                  type="number"
                  value={scanConfigForm[field.key]}
                />
                <small>{field.help}</small>
              </label>
            );
          })}
          <div className="scan-control-actions wide-field">
            <button className="icon-button" disabled={scanConfigBusy !== null} type="submit">
              <Save size={17} />
              <span>{scanConfigBusy === "save" ? "Saving" : "Save Scan Controls"}</span>
            </button>
            <button
              className="icon-button"
              disabled={scanConfigBusy !== null || !scanConfig || appdataFieldCount === 0}
              onClick={resetScanConfigToEnvironment}
              type="button"
            >
              <RefreshCw size={17} />
              <span>{scanConfigBusy === "reset" ? "Resetting" : "Reset to Env"}</span>
            </button>
          </div>
        </form>
      </div>
    );
  }

  function resultCard(result: Result) {
    const selected = selectedResultSet.has(result.id);
    const cartAttempt = cartAttemptByResultId.get(result.id);
    const bookingUrl = bookingUrlWithStartDate(result.booking_url, result.arrival_date);
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
            href={bookingUrl}
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
          <button className={`nav-item ${drawerOpen && drawerMode === "alerts" ? "active" : ""}`} onClick={() => openDrawer("alerts")} type="button">
            <Bell size={18} /> Alerts
          </button>
          <button className={`nav-item ${drawerOpen && drawerMode === "activity" ? "active" : ""}`} onClick={() => openDrawer("activity")} type="button">
            <Timer size={18} /> Activity
          </button>
          <a className={`nav-item ${isLogsPage ? "active" : ""}`} href="#logs" onClick={() => setDrawerOpen(false)}>
            <ListChecks size={18} /> Logs
          </a>
          <button
            className={`nav-item ${drawerOpen && drawerMode === "targets" ? "active" : ""}`}
            onClick={() => openDrawer("targets")}
            type="button"
          >
            <MapPin size={18} /> Targets
          </button>
          <button
            className={`nav-item ${drawerOpen && drawerMode === "watches" ? "active" : ""}`}
            onClick={() => openDrawer("watches")}
            type="button"
          >
            <CalendarDays size={18} /> Watches
          </button>
          <button className={`nav-item ${drawerOpen && drawerMode === "settings" ? "active" : ""}`} onClick={() => openDrawer("settings")} type="button">
            <Settings size={18} /> Settings
          </button>
        </nav>
        <div className="sidebar-note">
          <Timer size={18} />
          <span>Minimum scan interval: 10 min</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{isLogsPage ? "Scan Logs" : "Availability Monitor"}</h1>
            <p>
              {isLogsPage
                ? `${scanRuns.length} recent runs \u00b7 ${scanEvents.length} events \u00b7 ${notifications.length} notifications`
                : `${activeTargets.length} targets \u00b7 ${watchSummary} \u00b7 ${activeResultCount} active matches`}
            </p>
          </div>
          <div className="topbar-actions">
            {isLogsPage && (
              <a className="icon-button" href="#results" onClick={scrollToResults} title="Back to availability monitor">
                <ListChecks size={18} />
                <span>Monitor</span>
              </a>
            )}
            <button className="icon-button" onClick={() => openDrawer("targets")} type="button" title="Open campground targets">
              <MapPin size={18} />
              <span>Targets</span>
            </button>
            <button className="icon-button" onClick={() => openDrawer("watches")} type="button" title="Open watch rules">
              <CalendarDays size={18} />
              <span>Watches</span>
            </button>
            <button className="icon-button" onClick={runAllScans} disabled={scanAllBusy || activeWatches.length === 0} title="Run every active watch now">
              <Play size={18} />
              <span>{scanAllBusy ? "Scanning" : "Scan All"}</span>
            </button>
            {scanInProgress && (
              <button className="icon-button danger" onClick={cancelScans} disabled={scanCancelBusy} title="Stop the active scan">
                <X size={18} />
                <span>{scanCancelBusy ? "Stopping" : "Stop"}</span>
              </button>
            )}
            <button className="icon-button primary" onClick={() => void refresh()} disabled={loadState === "loading"} title="Refresh data">
              <RefreshCw size={18} />
              <span>Refresh</span>
            </button>
          </div>
        </header>

        {message && <div className="notice">{message}</div>}
        {loadState === "error" && <div className="notice danger">The API is not reachable yet.</div>}
        {!isLogsPage && (
          <>
            <section className="home-focus" aria-label="Trip control">
              <div className="home-focus-main">
                <span className="focus-kicker">
                  <TentTree size={16} />
                  Camp Finder
                </span>
                <div>
                  <h2>Trip Control</h2>
                  <p>{focusSummary}</p>
                </div>
                <div className="focus-action-row">
                  <button className="icon-button primary" onClick={() => openDrawer("targets")} type="button">
                    <MapPin size={17} />
                    <span>Sources</span>
                  </button>
                  <button className="icon-button" onClick={() => openDrawer("watches")} type="button">
                    <CalendarDays size={17} />
                    <span>Watches</span>
                  </button>
                  <button className="icon-button" onClick={runAllScans} disabled={scanAllBusy || activeWatches.length === 0} type="button">
                    <Play size={17} />
                    <span>{scanAllBusy ? "Scanning" : "Scan Now"}</span>
                  </button>
                  <button className="icon-button" onClick={() => openDrawer("alerts")} type="button">
                    <Bell size={17} />
                    <span>Alerts</span>
                  </button>
                </div>
              </div>

              <div className="home-focus-side">
                <div className={`scan-status-card focus-scan ${scanInProgress ? "running" : ""}`} aria-live="polite">
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
                </div>
                <div className="focus-signal-grid">
                  <article className="focus-signal">
                    <Timer size={17} />
                    <span>
                      <strong>{nextReleaseHint ? formatDateTime(nextReleaseHint.release_at) : "No release queued"}</strong>
                      <small>{nextReleaseHint ? `${nextReleaseHint.target} \u00b7 ${formatDate(nextReleaseHint.arrival_date)}` : "Release planner will update after watches are added."}</small>
                    </span>
                  </article>
                  <article className="focus-signal source-signal">
                    <Search size={17} />
                    <span>
                      <strong>{sourceCoverage.importedBundledCount}/{sourceCoverage.bundledTargetCount} preset targets saved</strong>
                      <small>{sourceSummary}</small>
                    </span>
                  </article>
                </div>
              </div>
            </section>

            <section className="summary-grid" aria-label="Monitor summary">
              <SummaryMetric label="Targets" value={activeTargets.length.toString()} icon={<MapPin size={18} />} />
              <SummaryMetric label="Active watches" value={activeWatches.length.toString()} icon={<CalendarDays size={18} />} />
              <SummaryMetric label="Active matches" value={activeResultCount.toString()} icon={<CheckCircle2 size={18} />} />
              <SummaryMetric label="Notifications" value={notifications.length.toString()} icon={<Bell size={18} />} />
            </section>
          </>
        )}

        <div className={`drawer-backdrop ${drawerOpen ? "show" : ""}`} onClick={() => setDrawerOpen(false)} />
        <div className={`setup-drawer ${drawerOpen ? "open" : ""}`}>
          <div className="drawer-heading">
            <div>
              <h2>
                {drawerMode === "alerts"
                  ? "Alert Center"
                  : drawerMode === "activity"
                    ? "Activity"
                    : drawerMode === "targets"
                      ? "Target Setup"
                      : drawerMode === "watches"
                        ? "Watch Builder"
                        : "Settings"}
              </h2>
              <p>
                {drawerMode === "alerts"
                  ? "Review active availability and notification delivery."
                  : drawerMode === "activity"
                    ? "Watch live scan state and recent background work."
                    : drawerMode === "targets"
                      ? "Add and maintain campground targets."
                      : drawerMode === "watches"
                        ? "Build date rules and scan filters."
                        : "Manage notifications, Cart Assist, and backups."}
              </p>
            </div>
            <div className="drawer-controls">
              <button
                className={`drawer-tab ${drawerMode === "alerts" ? "active" : ""}`}
                onClick={() => setDrawerMode("alerts")}
                type="button"
              >
                <Bell size={16} /> Alerts
              </button>
              <button
                className={`drawer-tab ${drawerMode === "activity" ? "active" : ""}`}
                onClick={() => setDrawerMode("activity")}
                type="button"
              >
                <Timer size={16} /> Activity
              </button>
              <button
                className={`drawer-tab ${drawerMode === "targets" ? "active" : ""}`}
                onClick={() => setDrawerMode("targets")}
                type="button"
              >
                <MapPin size={16} /> Targets
              </button>
              <button
                className={`drawer-tab ${drawerMode === "watches" ? "active" : ""}`}
                onClick={() => setDrawerMode("watches")}
                type="button"
              >
                <CalendarDays size={16} /> Watches
              </button>
              <button
                className={`drawer-tab ${drawerMode === "settings" ? "active" : ""}`}
                onClick={() => setDrawerMode("settings")}
                type="button"
              >
                <Settings size={16} /> Settings
              </button>
              <button className="icon-only" onClick={() => setDrawerOpen(false)} title="Close drawer" type="button">
                <X size={17} />
              </button>
            </div>
          </div>
          <section className={`panel ${drawerMode === "alerts" ? "" : "drawer-panel-hidden"}`} id="alerts">
            <div className="panel-heading">
              <div>
                <h2>Availability Alerts</h2>
                <p>Fast access to active matches and recent notification delivery.</p>
              </div>
              <div className="panel-action-row inline">
                <a className="icon-button primary" href="#results" onClick={scrollToResults}>
                  <ListChecks size={17} />
                  <span>View Results</span>
                </a>
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
            </div>
            <div className="drawer-metrics">
              <SummaryMetric label="Active matches" value={activeResultCount.toString()} icon={<CheckCircle2 size={18} />} />
              <SummaryMetric label="Loaded results" value={loadedResultCount.toString()} icon={<ListChecks size={18} />} />
              <SummaryMetric label="Notifications" value={notifications.length.toString()} icon={<Bell size={18} />} />
            </div>
            <div className="subheading">
              <strong>Newest active matches</strong>
              <small>{activeResults.length ? "Open, copy, or triage the latest availability." : "No active availability is waiting."}</small>
            </div>
            <div className="drawer-result-list">
              {activeResults.length === 0 && <p className="empty">No active availability alerts right now.</p>}
              {activeResults.slice(0, 6).map(resultCard)}
            </div>
            <div className="notification-log">
              <div className="subheading">
                <strong>Recent notifications</strong>
                <small>{notifications.length ? "Latest delivery attempts from availability matches." : "No notification attempts yet."}</small>
              </div>
              {notifications.slice(0, 5).map((event) => (
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

          <section className={`panel ${drawerMode === "activity" ? "" : "drawer-panel-hidden"}`} id="activity">
            <div className="panel-heading">
              <div>
                <h2>Scan Activity</h2>
                <p>Live scanner state, recent runs, and the manual stop control.</p>
              </div>
              <div className="panel-action-row inline">
                <a className="icon-button" href="#logs" onClick={() => setDrawerOpen(false)} title="Open detailed logs">
                  <ListChecks size={17} />
                  <span>Open Logs</span>
                </a>
                <button className="icon-button" onClick={() => void refresh({ silent: true })} disabled={loadState === "loading"} title="Refresh activity">
                  <RefreshCw size={17} />
                  <span>Refresh</span>
                </button>
                <button className="icon-button danger" onClick={cancelScans} disabled={!scanInProgress || scanCancelBusy} title="Stop the active scan">
                  <X size={17} />
                  <span>{scanCancelBusy ? "Stopping" : "Stop Scan"}</span>
                </button>
              </div>
            </div>
            <div className="diagnostic-grid">
              <article className="diagnostic-card">
                <span className={`status ${scanInProgress ? "calm" : "quiet"}`}>
                  {scanInProgress ? "running" : "idle"}
                </span>
                <strong>{activeScanTitle}</strong>
                <small>{activeScanDetail}</small>
              </article>
              <article className="diagnostic-card">
                <span className={`status ${latestScanEvent?.level === "error" ? "danger" : latestScanEvent?.level === "warning" ? "warning" : "quiet"}`}>
                  {latestScanEvent?.event_type || "no events"}
                </span>
                <strong>{latestScanEvent ? latestScanEvent.watch_name || "Scanner" : "No scan events yet"}</strong>
                <small>{latestScanEvent ? latestScanEvent.message : "The server will log scan checkpoints here once a scan starts."}</small>
              </article>
            </div>
            <div className="subheading">
              <strong>Recent runs</strong>
              <small>Durable run records from the server.</small>
            </div>
            <div className="status-list compact-list">
              {scanRuns.length === 0 && <p className="empty">No scans have run yet.</p>}
              {scanRuns.slice(0, 8).map((run) => (
                <article className="status-row scan-row" key={run.id}>
                  <span>
                    <strong>{run.watch_name}</strong>
                    <small>
                      {run.status === "running"
                        ? `${run.target_name} · in progress since ${formatDateTime(run.started_at)}`
                        : `${run.target_name} · ${run.candidate_count} stays · ${run.available_count} matches`}
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
            <div className="subheading">
              <strong>Recent events</strong>
              <small>Use the Logs page for the full diagnostic view.</small>
            </div>
            <div className="scan-event-list compact-events">
              {scanEvents.length === 0 && <p className="empty">No event log entries yet.</p>}
              {scanEvents.slice(0, 8).map((event) => (
                <article className={`scan-event-row ${event.level}`} key={event.id}>
                  <span>
                    <strong>{event.event_type.split("_").join(" ")}</strong>
                    <small>{event.watch_name || event.target_name || "Scanner"} · {formatDateTime(event.created_at)}</small>
                  </span>
                  <p>{event.message}</p>
                </article>
              ))}
            </div>
          </section>

          <section className={`panel ${drawerMode === "targets" ? "" : "drawer-panel-hidden"}`} id="targets">
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
            <div className="source-catalog">
              <div className="subheading">
                <strong>Source catalog</strong>
                <small>Refreshable v2 sources grouped by park, forest, region, and Washington state research.</small>
              </div>
              {sourceGroups.map((group) => (
                <div className="source-group" key={group.category}>
                  <div className="source-group-heading">
                    <strong>{group.category}</strong>
                    <small>{group.items.length} source{group.items.length === 1 ? "" : "s"}</small>
                  </div>
                  {group.items.map((source) => {
                    const discovery = sourceDiscovery[source.id];
                    return (
                      <article className="source-row" key={source.id}>
                        <span>
                          <span className={`status ${statusTone(source.status)}`}>{source.status}</span>
                          <strong>{source.name}</strong>
                          <small>
                            {source.provider} &middot; {source.region} &middot; {source.query_count || 0} quer{source.query_count === 1 ? "y" : "ies"} &middot; {source.description}
                          </small>
                          {discovery && (
                            <small className="preset-source-summary">
                              Source {discovery.discovered_count} &middot; {discovery.new_count} new &middot; {discovery.imported_count} already saved
                            </small>
                          )}
                        </span>
                        <span className="row-actions">
                          {source.discover_supported && (
                            <button
                              className="icon-only"
                              onClick={() => discoverSource(source.id)}
                              disabled={discoveringSourceId === source.id}
                              title={`Check ${source.name}`}
                              type="button"
                            >
                              <RefreshCw size={17} />
                            </button>
                          )}
                          {source.import_supported && (
                            <button
                              className="icon-only"
                              onClick={() => importSource(source.id)}
                              disabled={importingSourceId === source.id}
                              title={`Import ${source.name}`}
                              type="button"
                            >
                              <Download size={17} />
                            </button>
                          )}
                          <a className="icon-only quiet" href={source.official_url} target="_blank" rel="noreferrer" title={`Open ${source.provider} source`}>
                            <ExternalLink size={16} />
                          </a>
                        </span>
                      </article>
                    );
                  })}
                </div>
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

          <section className={`panel ${drawerMode === "watches" ? "" : "drawer-panel-hidden"}`} id="watches">
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
                Scope
                <select
                  disabled={Boolean(editingWatchId)}
                  value={editingWatchId ? "target" : watchScope}
                  onChange={(event) => setWatchScope(event.target.value as WatchScope)}
                >
                  <option value="target">One campground</option>
                  <option value="park">Park group</option>
                  <option value="state">State</option>
                  <option value="map">Current map view</option>
                </select>
              </label>
              {(editingWatchId || watchScope === "target") && (
                <label>
                  Target
                  <select value={watchTarget} onChange={(event) => setWatchTarget(event.target.value)}>
                    {targets.map((target) => (
                      <option key={target.id} value={target.id}>{target.name}</option>
                    ))}
                  </select>
                </label>
              )}
              {!editingWatchId && watchScope === "park" && (
                <label>
                  Park group
                  <select value={watchPark} onChange={(event) => setWatchPark(event.target.value)}>
                    {watchParkOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label} ({option.count})
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {!editingWatchId && watchScope === "state" && (
                <label>
                  State
                  <select value={watchStateCode} onChange={(event) => setWatchStateCode(event.target.value)}>
                    {watchStateOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.value} ({option.count})
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <div className="watch-scope-note wide-field">
                <MapPinned size={17} />
                <span>{watchScopeSummary()}</span>
              </div>
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

          <section className={`panel ${drawerMode === "settings" ? "" : "drawer-panel-hidden"}`} id="settings">
            <div className="panel-heading">
              <div>
                <h2>Notifications & Server Settings</h2>
                <p>Notifications, scan controls, and Cart Assist can use appdata settings or environment defaults.</p>
              </div>
              <div className="panel-action-row inline">
                <button className="icon-button" onClick={testNotifications} disabled={testNotifyBusy} title="Send a test notification">
                  <Bell size={17} />
                  <span>{testNotifyBusy ? "Testing" : "Test"}</span>
                </button>
              </div>
            </div>
            <div className="status-list">
              {notificationStatus.channels.length === 0 && <p className="empty">Notification channel status has not loaded yet.</p>}
              {notificationStatus.channels.map((channel) => (
                <article className="status-row" key={channel.channel}>
                  <span>
                    <strong>{notificationChannelLabel(channel.channel)}</strong>
                    <small>{channel.detail}</small>
                  </span>
                  <span className={`status ${channel.configured ? "success" : "quiet"}`}>
                    {channel.configured ? "configured" : "missing"}
                  </span>
                </article>
              ))}
            </div>
            {renderNotificationControls()}
            {renderScanControls()}
            <div className="cart-assist-log">
              <div className="subheading">
                <strong>Cart Assist</strong>
                <small>{cartAssistStatus?.detail || "Server status has not loaded yet."}</small>
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
              <article className="status-row">
                <span>
                  <strong>Checkout queue</strong>
                  <small>{cartAssistQueueSummary(cartAssistStatus)}</small>
                </span>
                <span className="cart-queue-actions">
                  <span className={`status ${cartAssistStatus ? (cartAssistStatus.active_attempt_count ? "warning" : "success") : "quiet"}`}>
                    {cartAssistStatus ? `${cartAssistStatus.active_attempt_count} active` : "loading"}
                  </span>
                  {nextCheckoutAttempt && (
                    <a
                      className="link-button compact"
                      href={bookingUrlWithStartDate(nextCheckoutAttempt.booking_url, nextCheckoutAttempt.arrival_date)}
                      onClick={() => openCartAttemptBooking(nextCheckoutAttempt)}
                      rel="noreferrer"
                      target="_blank"
                    >
                      <ExternalLink size={15} /> Open Next
                    </a>
                  )}
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
                prioritizedCartAttempts.slice(0, 4).map((attempt) => {
                  const busy = cartAttemptBusyId === attempt.id;
                  const checkoutReady = attempt.status === "manual_required" || attempt.status === "opened";
                  const canMakeReady = ["needs_credentials", "disabled", "failed"].includes(attempt.status);
                  const activeAttempt = isActiveCartAttempt(attempt);
                  return (
                    <article className={`status-row cart-attempt-row ${activeAttempt ? "active" : ""}`} key={attempt.id}>
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
                              href={bookingUrlWithStartDate(attempt.booking_url, attempt.arrival_date)}
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
                <small>Targets, watches, scan controls, notifications, and Cart Assist settings.</small>
              </div>
              <label className="backup-secret-toggle">
                <input
                  checked={includeSecretSettings}
                  disabled={configBusy !== null}
                  onChange={(event) => setIncludeSecretSettings(event.target.checked)}
                  type="checkbox"
                />
                <span>Include saved secrets</span>
              </label>
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
          </section>
        </div>

        {isLogsPage ? (
          <section className="logs-page" id="logs" aria-label="Detailed scan logs">
            <section className="panel logs-hero">
              <div className="panel-heading">
                <div>
                  <h2>Detailed Logs</h2>
                  <p>Scan events, durable run records, and notification history for diagnosing slow or stuck work.</p>
                </div>
                <div className="panel-action-row inline">
                  <button className="icon-button" onClick={() => void refresh({ silent: true })} disabled={loadState === "loading"} title="Refresh logs">
                    <RefreshCw size={17} />
                    <span>Refresh</span>
                  </button>
                  <button className="icon-button danger" onClick={cancelScans} disabled={!scanInProgress || scanCancelBusy} title="Stop the active scan">
                    <X size={17} />
                    <span>{scanCancelBusy ? "Stopping" : "Stop Scan"}</span>
                  </button>
                </div>
              </div>
              <div className="logs-summary-grid">
                <SummaryMetric label="Recent runs" value={scanRuns.length.toString()} icon={<Timer size={18} />} />
                <SummaryMetric label="Events loaded" value={scanEvents.length.toString()} icon={<ListChecks size={18} />} />
                <SummaryMetric label="Notifications" value={notifications.length.toString()} icon={<Bell size={18} />} />
                <SummaryMetric label="Active matches" value={activeResultCount.toString()} icon={<CheckCircle2 size={18} />} />
              </div>
              <div className={`scan-status-card embedded ${scanInProgress ? "running" : ""}`} aria-live="polite">
                <span className="scan-status-icon">
                  {scanInProgress ? <RefreshCw className="spinning" size={20} /> : <Activity size={20} />}
                </span>
                <span>
                  <strong>{activeScanTitle}</strong>
                  <small>{activeScanDetail}</small>
                </span>
              </div>
            </section>

            <div className="logs-layout">
              <section className="panel log-stream-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Event Log</h2>
                    <p>Checkpoint messages emitted by active and recent scans.</p>
                  </div>
                </div>
                <div className="scan-event-list log-stream">
                  {scanEvents.length === 0 && <p className="empty">No event log entries yet.</p>}
                  {scanEvents.map((event) => (
                    <article className={`scan-event-row ${event.level}`} key={event.id}>
                      <span>
                        <strong>{event.event_type.split("_").join(" ")}</strong>
                        <small>
                          {event.watch_name || event.target_name || "Scanner"} &middot; {formatDateTime(event.created_at)}
                        </small>
                      </span>
                      <p>{event.message}</p>
                    </article>
                  ))}
                </div>
              </section>

              <aside className="logs-side-panels">
                <section className="panel">
                  <div className="panel-heading compact-heading">
                    <div>
                      <h2>Scan Runs</h2>
                      <p>Most recent durable run rows.</p>
                    </div>
                  </div>
                  <div className="status-list compact-list">
                    {scanRuns.length === 0 && <p className="empty">No scans have run yet.</p>}
                    {scanRuns.slice(0, 12).map((run) => (
                      <article className="status-row scan-row" key={run.id}>
                        <span>
                          <strong>{run.watch_name}</strong>
                          <small>
                            {run.status === "running"
                              ? `${run.target_name} · in progress since ${formatDateTime(run.started_at)}`
                              : `${run.target_name} · ${run.candidate_count} stays · ${run.available_count} matches`}
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

                <section className="panel">
                  <div className="panel-heading compact-heading">
                    <div>
                      <h2>Notification Log</h2>
                      <p>Delivery attempts created from new matches.</p>
                    </div>
                  </div>
                  <div className="notification-log flat-log">
                    {notifications.length === 0 && <p className="empty">No notification attempts yet.</p>}
                    {notifications.slice(0, 12).map((event) => (
                      <article className="status-row" key={event.id}>
                        <span>
                          <strong>{event.channel}</strong>
                          <small>{event.message}</small>
                          <small>{formatDateTime(event.sent_at)}</small>
                        </span>
                        <span className={`status ${event.status === "sent" ? "success" : event.status === "error" ? "danger" : "quiet"}`}>
                          {event.status}
                        </span>
                      </article>
                    ))}
                  </div>
                </section>
              </aside>
            </div>
          </section>
        ) : (
        <div className="content-grid lower">
          <section className="map-dashboard" aria-label="Target map">
            <div className="map-panel">
              <div className="map-toolbar">
                <div>
                  <h2>Target Map</h2>
                  <p>Tap a marker for details, campground links, and bulk watch actions.</p>
                </div>
                <div className="map-actions">
                  <a className="icon-button primary" href="#results" onClick={scrollToResults}>
                    <ListChecks size={17} />
                    <span>View Results</span>
                  </a>
                  <button className="icon-button" onClick={openWatchBuilderForMapView} type="button">
                    <MapPinned size={17} />
                    <span>Watch View</span>
                  </button>
                  <button
                    className="icon-button"
                    onClick={() => {
                      setResultQuery("");
                      setMapSelection(null);
                    }}
                    type="button"
                  >
                    <X size={17} />
                    <span>Clear Filter</span>
                  </button>
                  <button className="icon-button" onClick={() => openDrawer("targets")} type="button">
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
              {renderMapSelectionPanel()}
              <div className="subheading">
                <strong>Park Queue</strong>
                <small>{parkSummaries.length} park group{parkSummaries.length === 1 ? "" : "s"} tracked</small>
              </div>
              <div className="park-chip-strip">
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
              </div>
            </aside>
          </section>

          <aside className="utility-rail" aria-label="Planning and server tools">
            <section className="panel utility-dock">
              <div className="utility-dock-heading">
                <div>
                  <h2>Release Planner</h2>
                  <p>Upcoming release windows calculated from active watch rules.</p>
                </div>
              </div>
              <div className="utility-tabs" role="tablist" aria-label="Utility dock views">
                <button
                  aria-controls="release-panel"
                  aria-selected={utilityTab === "release"}
                  className={`utility-tab ${utilityTab === "release" ? "active" : ""}`}
                  id="release-tools"
                  onClick={() => setUtilityTab("release")}
                  role="tab"
                  type="button"
                >
                  <CalendarDays size={15} />
                  <span>Releases</span>
                  <small>{latestRelease.length}</small>
                </button>
                <button
                  aria-controls="activity-panel"
                  aria-selected={utilityTab === "activity"}
                  className={`utility-tab ${utilityTab === "activity" ? "active" : ""}`}
                  id="activity-tools"
                  onClick={() => setUtilityTab("activity")}
                  role="tab"
                  type="button"
                >
                  <Timer size={15} />
                  <span>Activity</span>
                  <small>{scanRuns.length}</small>
                </button>
                <button
                  aria-controls="settings-panel"
                  aria-selected={utilityTab === "settings"}
                  className={`utility-tab ${utilityTab === "settings" ? "active" : ""}`}
                  id="settings"
                  onClick={() => setUtilityTab("settings")}
                  role="tab"
                  type="button"
                >
                  <Settings size={15} />
                  <span>Server</span>
                  <small>{cartAssistStatus?.active_attempt_count || 0}</small>
                </button>
              </div>

              {utilityTab === "release" && (
                <div className="utility-tab-panel release-panel" id="release-panel" role="tabpanel" aria-labelledby="release-tools">
                  <div className="utility-panel-heading">
                    <strong>Release Planner</strong>
                    <small>Calculated from each target's configurable booking window.</small>
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
                </div>
              )}

              {utilityTab === "activity" && (
                <div className="utility-tab-panel scan-panel" id="activity-panel" role="tabpanel" aria-labelledby="activity-tools">
                  <div className="utility-panel-heading">
                    <strong>Recent Scan Activity</strong>
                    <small>Latest background and manual scan runs.</small>
                  </div>
                  <div className="panel-action-row">
                    <a className="link-button compact" href="#logs">
                      <ListChecks size={16} />
                      <span>Open Log</span>
                    </a>
                    <button className="icon-button compact danger" onClick={cancelScans} disabled={!scanInProgress || scanCancelBusy} title="Stop the active scan">
                      <X size={16} />
                      <span>Stop</span>
                    </button>
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
                </div>
              )}

              {utilityTab === "settings" && (
                <div className="utility-tab-panel notification-panel" id="settings-panel" role="tabpanel" aria-labelledby="settings">
                  <div className="utility-panel-heading">
                    <strong>Notifications & Server Settings</strong>
                    <small>Notifications, scan controls, and Cart Assist can use appdata settings or environment defaults.</small>
                  </div>
                  <div className="panel-action-row">
                    <button className="icon-button" onClick={testNotifications} disabled={testNotifyBusy} title="Send a test notification">
                      <Bell size={17} />
                      <span>Test</span>
                    </button>
                  </div>
                  <div className="status-list">
                    {notificationStatus.channels.map((channel) => (
                      <article className="status-row" key={channel.channel}>
                        <span>
                          <strong>{notificationChannelLabel(channel.channel)}</strong>
                          <small>{channel.detail}</small>
                        </span>
                        <span className={`status ${channel.configured ? "success" : "quiet"}`}>
                          {channel.configured ? "configured" : "missing"}
                        </span>
                      </article>
                    ))}
                  </div>
                  {renderNotificationControls()}
                  {renderScanControls()}
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
                    <article className="status-row">
                      <span>
                        <strong>Checkout queue</strong>
                        <small>{cartAssistQueueSummary(cartAssistStatus)}</small>
                      </span>
                      <span className="cart-queue-actions">
                        <span className={`status ${cartAssistStatus ? (cartAssistStatus.active_attempt_count ? "warning" : "success") : "quiet"}`}>
                          {cartAssistStatus ? `${cartAssistStatus.active_attempt_count} active` : "loading"}
                        </span>
                        {nextCheckoutAttempt && (
                          <a
                            className="link-button compact"
                            href={bookingUrlWithStartDate(nextCheckoutAttempt.booking_url, nextCheckoutAttempt.arrival_date)}
                            onClick={() => openCartAttemptBooking(nextCheckoutAttempt)}
                            rel="noreferrer"
                            target="_blank"
                          >
                            <ExternalLink size={15} /> Open Next
                          </a>
                        )}
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
                      prioritizedCartAttempts.slice(0, 4).map((attempt) => {
                        const busy = cartAttemptBusyId === attempt.id;
                        const checkoutReady = attempt.status === "manual_required" || attempt.status === "opened";
                        const canMakeReady = ["needs_credentials", "disabled", "failed"].includes(attempt.status);
                        const activeAttempt = isActiveCartAttempt(attempt);
                        return (
                          <article className={`status-row cart-attempt-row ${activeAttempt ? "active" : ""}`} key={attempt.id}>
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
                                    href={bookingUrlWithStartDate(attempt.booking_url, attempt.arrival_date)}
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
                      <small>Targets, watches, scan controls, notifications, and Cart Assist settings.</small>
                    </div>
                    <label className="backup-secret-toggle">
                      <input
                        checked={includeSecretSettings}
                        disabled={configBusy !== null}
                        onChange={(event) => setIncludeSecretSettings(event.target.checked)}
                        type="checkbox"
                      />
                      <span>Include saved secrets</span>
                    </label>
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
                </div>
              )}
            </section>
          </aside>

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
        )}
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
