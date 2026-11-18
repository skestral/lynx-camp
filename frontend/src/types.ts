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

export type CampgroundDetails = {
  campground_id: string;
  name: string;
  park_name?: string;
  state_code?: string;
  description: string;
  overview: string;
  facilities: string;
  natural_features: string;
  recreation: string;
  directions: string;
  phone: string;
  address: string;
  latitude?: number | string | null;
  longitude?: number | string | null;
  timezone: string;
  amenities: string[];
  activities: string[];
  notices: string[];
  links: Array<{ title: string; url: string }>;
  image_url: string;
  detail_url: string;
  source: string;
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

export type RegionScope =
  | { kind: "state"; state_code: string }
  | { kind: "parks"; park_names: string[] }
  | { kind: "bounds"; south: number; west: number; north: number; east: number };

export type Watch = {
  group_id: string | null;
  region_scope?: RegionScope | null;
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
  alerts_enabled: number;
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
  equipment?: "" | "tent" | "rv" | "trailer" | "vehicle";
  vehicle_length_ft?: number | null;
  campsite_ids?: string[];
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

export type AvailabilityWindow = {
  campground_id: string;
  arrival_date: string;
  departure_date: string;
  match_count: number;
  last_seen_at: string;
};

export type StayResults = { results: Result[]; total_count: number };

export type NotificationEvent = {
  id: number;
  result_id: number | null;
  event_type?: string;
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

export type CrawlStatus = {
  status: "idle" | "queued" | "running" | "waiting" | "completed" | "incomplete" | "cancelled";
  crawl_paused: boolean;
  total_count: number;
  completed_count: number;
  failed_count: number;
  skipped_count: number;
  remaining_count: number;
  current_target: string | null;
  retry_at: string | null;
  cooldown_seconds: number;
  effective_request_delay_seconds: number;
  estimated_remaining_seconds: number | null;
  estimated_requests_remaining: number;
  completed_stay_count: number;
};

export type ScanEvent = {
  id: number;
  run_id: number | null;
  watch_id: number | null;
  target_id: number | null;
  watch_name: string | null;
  target_name: string | null;
  campground_id: string | null;
  level: "info" | "warning" | "error" | string;
  event_type: string;
  message: string;
  created_at: string;
};

export type ScanCancelResult = {
  cancel_requested: boolean;
  active_run_id: number | null;
  stale_cancelled_count: number;
};

export type ScanConfigValues = {
  min_poll_interval_minutes: number;
  release_scan_before_minutes: number;
  release_scan_after_minutes: number;
  release_scan_interval_minutes: number;
  availability_cache_minutes: number;
  api_request_delay_seconds: number;
  rate_limit_backoff_minutes: number;
};

export type ScanConfig = {
  values: ScanConfigValues;
  sources: Record<keyof ScanConfigValues, "appdata" | "environment">;
  environment: ScanConfigValues;
};

export type ScanConfigPayload = Partial<ScanConfigValues>;

export type NotificationChannelStatus = {
  channel: string;
  configured: boolean;
  detail: string;
  missing: string[];
};

export type NotificationStatus = {
  channels: NotificationChannelStatus[];
};

export type NotificationConfig = {
  schedule: { next_digest_at: string | null; timezone_label: string };
  configuration_error: string | null;
  home_assistant_webhook_configured: boolean;
  home_assistant_webhook_source: "appdata" | "environment" | "none";
  home_assistant_detail: string;
  values: NotificationConfigValues;
  sources: Record<keyof NotificationConfigValues, "appdata" | "environment" | "none">;
  configured: Record<keyof NotificationConfigValues, boolean>;
  secret_fields: Array<keyof NotificationConfigValues>;
};

export type NotificationConfigValues = {
  digest_frequency: "daily" | "weekly" | "disabled";
  digest_time: string;
  digest_timezone: "America/Los_Angeles" | "server" | "UTC";
  digest_weekday: number;
  home_assistant_errors_enabled: boolean;
  home_assistant_error_cooldown_minutes: number;
  apprise_urls: string;
  webhook_url: string;
  home_assistant_webhook_url: string;
  ntfy_server: string;
  ntfy_topic: string;
  ntfy_token: string;
  ntfy_priority: string;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;
  smtp_from: string;
  smtp_to: string;
  max_notification_results: number;
};

export type NotificationConfigPayload = Partial<NotificationConfigValues>;

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
  regions?: Array<{ group_id: string; scope: RegionScope; excluded_campgrounds: string[] }>;
  settings?: {
    app_settings: Record<string, string>;
    redacted_keys: string[];
  };
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
      alerts_enabled: boolean;
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
  imported_settings?: number;
  skipped_settings?: number;
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

export type SourceDefinition = {
  areas?: string[];
  counties?: string[];
  id: string;
  name: string;
  provider: string;
  category: string;
  region: string;
  status: "ready" | "research" | "directory" | string;
  source_type: string;
  description: string;
  official_url: string;
  query_count: number;
  discover_supported: boolean;
  import_supported: boolean;
  imported_count: number;
  connection?: {
    state: "unverified" | "catalog_loaded" | "access_denied" | "rate_limited";
    message?: string;
    checked_at?: string;
    retry_at?: string;
  };
};

export type SourceDiscoveryResult = {
  source_id: string;
  source_name: string;
  provider: string;
  category: string;
  region: string;
  status: string;
  source: string;
  checked_at: string;
  source_queries: string[];
  discovered_count: number;
  imported_count: number;
  new_count: number;
  targets: PresetTarget[];
};

export type ProviderDiagnosticRecord = {
  id: string;
  recorded_at: string;
  endpoint: string;
  method: string;
  query: Record<string, string>;
  status: number | null;
  outcome: string;
  elapsed_ms: number;
  response_bytes: number;
  content_type: string;
  server_family: string;
  markers: string[];
  request_ids: Record<string, string>;
  via_present: boolean;
  cache_header_present: boolean;
  azure_edge_header_present: boolean;
  set_cookie_present: boolean;
  authenticate_header_present: boolean;
  redirect: string;
  transport_error: string | null;
  proxy_configured: boolean;
  no_proxy_configured: boolean;
  custom_ca_configured: boolean;
};

export type ProviderDiagnostics = {
  source_id: string;
  provider: string;
  history_limit: number;
  connection: NonNullable<SourceDefinition["connection"]>;
  records: ProviderDiagnosticRecord[];
  client: {
    method: string;
    host: string;
    user_agent: string;
    accept: string;
    browser_required: boolean;
    automatic_redirects: boolean;
  };
};

export type SourceImportResult = {
  source_id: string;
  source_name: string;
  source: string;
  checked_at: string;
  imported_count: number;
  updated_count: number;
  target_count: number;
  new_count: number;
  discovery: SourceDiscoveryResult;
  targets: Target[];
};
