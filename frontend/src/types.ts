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

export type NotificationEvent = {
  id: number;
  result_id: number;
  channel: string;
  status: string;
  message: string;
  sent_at: string;
};

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
