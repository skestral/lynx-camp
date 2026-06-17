export type Target = {
  id: number;
  name: string;
  campground_id: string;
  park_name: string;
  state_code: string;
  latitude: number | null;
  longitude: number | null;
  booking_url: string;
  release_months: number;
  release_window_value: number;
  release_window_unit: "Days" | "Weeks" | "Months";
  release_time: string;
  timezone: string;
  poll_interval_minutes: number;
  active: number;
  last_checked_at: string | null;
  last_status: string;
};

export type SearchSuggestion = {
  name: string;
  campground_id: string;
  park_name: string;
  state_code: string;
  latitude?: string;
  longitude?: string;
};

export type ReleaseHint = {
  arrival_date: string;
  departure_date: string;
  release_at: string;
  release_status: "open" | "upcoming";
};

export type DateRange = {
  arrival_date: string;
  departure_date: string;
};

export type Watch = {
  id: number;
  target_id: number;
  target_name: string;
  campground_id: string;
  park_name: string;
  state_code: string;
  target_active: number;
  name: string;
  mode: "weekend" | "specific";
  pattern: string;
  arrival_weekdays: number[] | null;
  nights: number;
  window_start: string;
  window_end: string;
  site_filters: SiteFilters;
  specific_ranges: DateRange[];
  cart_assist_enabled: number;
  active: number;
  next_scan_at: string | null;
  last_checked_at: string | null;
  last_status: string;
  poll_interval_minutes: number;
  release_window_value: number;
  release_window_unit: "Days" | "Weeks" | "Months";
  candidate_count: number;
  release_hints: ReleaseHint[];
};

export type SiteFilters = {
  site_type: string;
  loop: string;
  site: string;
  min_people: number | null;
};

export type Result = {
  id: number;
  watch_id: number;
  target_id: number;
  watch_name: string;
  target_name: string;
  park_name: string;
  state_code: string;
  campground_id: string;
  campground_name: string;
  campsite_id: string;
  site: string;
  loop: string;
  campsite_type: string;
  arrival_date: string;
  departure_date: string;
  booking_url: string;
  status: "available" | "opened" | "booked" | "dismissed";
  active: number;
  opened_at: string | null;
  booked_at: string | null;
  dismissed_at: string | null;
  discovered_at: string;
  last_seen_at: string;
};

export type ResultSummary = {
  total_count: number;
  active_count: number;
};

export type NotificationEvent = {
  id: number;
  result_id: number;
  channel: string;
  status: string;
  message: string;
  sent_at: string;
};

export type CartAssistStatus = {
  enabled: boolean;
  ready: boolean;
  guard_state: "off" | "needs_credentials" | "cooldown" | "ready";
  credentials_configured: boolean;
  username_configured: boolean;
  password_configured: boolean;
  cooldown_minutes: number;
  max_attempts_per_scan: number;
  recent_actionable_attempt_count: number;
  latest_actionable_attempt_at: string | null;
  next_allowed_at: string | null;
  cooldown_remaining_seconds: number;
  cooldown_remaining_minutes: number;
  active_attempt_count: number;
  ready_attempt_count: number;
  blocked_attempt_count: number;
  resolved_attempt_count: number;
  total_attempt_count: number;
  latest_active_attempt_at: string | null;
  attempt_status_counts: Record<string, number>;
  config_source: "appdata" | "environment";
  credential_source: "appdata" | "environment" | "none";
  detail: string;
};

export type CartAssistConfigPayload = {
  enabled?: boolean;
  cooldown_minutes?: number;
  max_attempts_per_scan?: number;
  username?: string;
  password?: string;
};

export type CartAttempt = {
  id: number;
  result_id: number;
  watch_id: number;
  target_id: number;
  watch_name: string;
  target_name: string;
  park_name: string;
  state_code: string;
  campsite_id: string;
  site: string;
  arrival_date: string;
  departure_date: string;
  booking_url: string;
  status: string;
  message: string;
  attempted_at: string;
  finished_at: string | null;
};

export type CartAttemptStatus = "manual_required" | "opened" | "booked" | "dismissed" | "failed";

export type ScanRun = {
  id: number;
  watch_id: number;
  target_id: number;
  watch_name: string;
  target_name: string;
  campground_id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  message: string;
  candidate_count: number;
  available_count: number;
};

export type NotificationChannelStatus = {
  channel: string;
  configured: boolean;
  detail: string;
  missing: string[];
};

export type NotificationStatus = {
  channels: NotificationChannelStatus[];
};

export type NotificationTestResult = {
  results: Array<{
    channel: string;
    status: "sent" | "skipped" | "error";
    message: string;
  }>;
};

export type ScanAllResult = {
  watch_count: number;
  available_count: number;
  missing_count?: number;
  summaries: Array<{
    watch_id: number;
    watch_name: string;
    status: string;
    message: string;
    candidate_count: number;
    available_count: number;
    missing_count?: number;
  }>;
};

export type ConfigBackup = {
  version: number;
  exported_at?: string | null;
  targets: Array<{
    name: string;
    campground_id: string;
    park_name: string;
    state_code: string;
    latitude?: number | null;
    longitude?: number | null;
    booking_url?: string | null;
    release_months: number;
    release_window_value: number;
    release_window_unit: "Days" | "Weeks" | "Months";
    release_time: string;
    timezone: string;
    poll_interval_minutes: number;
    active: boolean;
    watches: Array<{
      name: string;
      mode: "weekend" | "specific";
      pattern: string;
      arrival_weekdays: number[] | null;
      nights: number;
      window_start: string;
      window_end: string;
      site_filters: SiteFilters;
      specific_ranges: DateRange[];
      cart_assist_enabled: boolean;
      active: boolean;
    }>;
  }>;
};

export type ConfigImportResult = {
  target_count: number;
  imported_targets: number;
  updated_targets: number;
  created_watches: number;
  updated_watches: number;
};

export type ReleaseWindowProfile = {
  loop: string;
  campsite_type: string;
  release_window_value: number | null;
  release_window_unit: "Days" | "Weeks" | "Months" | "";
  campsite_count: number;
};

export type ReleaseWindowProfileResult = {
  sampled_month: string;
  total_campsite_count: number;
  profiles: ReleaseWindowProfile[];
};

export type PresetTarget = {
  name: string;
  campground_id: string;
  park_name: string;
  state_code: string;
  latitude?: number | null;
  longitude?: number | null;
  release_months: number;
  release_window_value: number;
  release_window_unit: "Days" | "Weeks" | "Months";
  release_time: string;
  timezone: string;
  poll_interval_minutes: number;
  imported: boolean;
};

export type PresetPack = {
  id: string;
  name: string;
  description: string;
  region: string;
  target_count: number;
  imported_count: number;
  targets: PresetTarget[];
};

export type PresetDiscoveryResult = {
  pack_id: string;
  pack_name: string;
  checked_at: string;
  source: string;
  source_queries: string[];
  static_count: number;
  discovered_count: number;
  imported_count: number;
  new_count: number;
  missing_count: number;
  unchanged_count: number;
  new_targets: PresetTarget[];
  missing_static_targets: PresetTarget[];
  targets: PresetTarget[];
};

export type PresetSourceImportResult = {
  pack_id: string;
  source: string;
  checked_at: string;
  imported_count: number;
  updated_count: number;
  target_count: number;
  new_count: number;
  missing_count: number;
  discovery: PresetDiscoveryResult;
  targets: Target[];
};
