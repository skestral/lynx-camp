import type {
  AvailabilityWindow,
  StayResults,
  CrawlStatus,
  CartAssistConfigPayload,
  CartAssistStatus,
  CartAttempt,
  CartAttemptStatus,
  CampgroundDetails,
  ConfigBackup,
  ConfigImportResult,
  NotificationEvent,
  NotificationConfig,
  NotificationConfigPayload,
  NotificationStatus,
  NotificationTestResult,
  PresetDiscoveryResult,
  PresetPack,
  PresetSourceImportResult,
  ProviderDiagnostics,
  ReleaseWindowProfileResult,
  Result,
  ResultSummary,
  ResultFilters,
  ResultOverviewQuery,
  ResultOverviewPage,
  RegionScope,
  ScanCancelResult,
  ScanConfig,
  ScanConfigPayload,
  ScanEvent,
  ScanRun,
  SearchSuggestion,
  SourceDefinition,
  SourceDiscoveryResult,
  SourceImportResult,
  Target,
  Watch
} from "./types";

export const RESULTS_LIMIT = 2000;
const PROVIDER_REQUEST_TIMEOUT_MS = 300000;

async function request<T>(path: string, options?: RequestInit, timeoutMs?: number): Promise<T> {
  let response: Response;
  const timeout = AbortSignal.timeout(timeoutMs ?? (options?.method ? 300000 : 15000));
  const signal = options?.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  try {
    response = await fetch(path, {
      ...options,
      signal,
      headers: { "Content-Type": "application/json", ...(options?.headers || {}) }
    });
  } catch {
    if (signal.aborted) throw new Error(`${path}: ${timeout.aborted ? "request timed out" : "request cancelled"}.`);
    throw new Error(`${path}: server unreachable. Check the connection and server logs.`);
  }
  if (!response.ok) {
    const body = await response.text();
    let detail = response.statusText || "Request failed";
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch { /* Proxy error pages are not useful dashboard messages. */ }
    throw new Error(`${path}: HTTP ${response.status} - ${detail}`);
  }
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error(`${path}: expected JSON but received a web page. Check proxy routing and server version.`);
  }
  try {
    return await response.json() as T;
  } catch {
    if (timeout.aborted) throw new Error(`${path}: response timed out.`);
    throw new Error(`${path}: invalid or interrupted JSON response.`);
  }
}

export const api = {
  targets: () => request<Target[]>("/api/targets"),
  presets: () => request<PresetPack[]>("/api/presets"),
  sources: () => request<SourceDefinition[]>("/api/sources"),
  sourceDiagnostics: (sourceId = "washington-state-parks") => request<ProviderDiagnostics>(`/api/sources/${encodeURIComponent(sourceId)}/diagnostics`),
  watches: () => request<Watch[]>("/api/watches"),
  createWatchGroup: (target_ids: number[], watch: Record<string, unknown>, region_scope: RegionScope | null = null) =>
    request<Watch[]>("/api/watch-groups", { method: "POST", body: JSON.stringify({ target_ids, watch, region_scope }) }),
  updateWatchGroup: (id: string, payload: Record<string, unknown>) =>
    request<Watch[]>(`/api/watch-groups/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  bulkWatches: (watch_ids: number[], action: "pause" | "resume" | "delete") =>
    request<{ updated_count: number }>("/api/watches/bulk", {
      method: "POST", body: JSON.stringify({ watch_ids, action })
    }),
  results: (limit = RESULTS_LIMIT) => request<Result[]>(`/api/results?limit=${limit}`),
  availability: () => request<AvailabilityWindow[]>("/api/results/availability"),
  resultsForStay: (arrival: string, departure: string, campgroundId?: string, parkName?: string, signal?: AbortSignal) => {
    const query = new URLSearchParams({ arrival, departure });
    if (campgroundId) query.set("campground_id", campgroundId);
    if (parkName) query.set("park_name", parkName);
    return request<StayResults>(`/api/results/for-stay?${query}`, { signal });
  },
  dismissResultGroup: (result_ids: number[]) => request<{ dismissed_count: number }>("/api/results/dismiss-group", {
    method: "POST", body: JSON.stringify({ result_ids })
  }),
  resultSummary: () => request<ResultSummary>("/api/results/summary"),
  resultOverview: (options: ResultOverviewQuery, signal?: AbortSignal) => {
    const query = new URLSearchParams();
    Object.entries(options).forEach(([key, value]) => { if (value !== undefined) query.set(key, String(value)); });
    return request<ResultOverviewPage>(`/api/results/overview?${query}`, { signal });
  },
  dismissResultScope: (filters: ResultFilters) => request<{ dismissed_count: number }>("/api/results/dismiss-scope", {
    method: "POST", body: JSON.stringify({ filters })
  }),
  scanRuns: () => request<ScanRun[]>("/api/scans"),
  scanEvents: () => request<ScanEvent[]>("/api/scans/events"),
  cancelScans: () => request<ScanCancelResult>("/api/scans/cancel", { method: "POST" }),
  scanConfig: () => request<ScanConfig>("/api/scan-config"),
  updateScanConfig: (payload: ScanConfigPayload) =>
    request<ScanConfig>("/api/scan-config", { method: "PATCH", body: JSON.stringify(payload) }),
  resetScanConfig: () => request<ScanConfig>("/api/scan-config/reset", { method: "POST" }),
  notifications: () => request<NotificationEvent[]>("/api/notifications"),
  notificationConfig: () => request<NotificationConfig>("/api/notifications/config"),
  updateNotificationConfig: (payload: NotificationConfigPayload) =>
    request<NotificationConfig>("/api/notifications/config", { method: "PATCH", body: JSON.stringify(payload) }),
  clearHomeAssistantWebhook: () =>
    request<NotificationConfig>("/api/notifications/home-assistant/clear", { method: "POST" }),
  clearNotificationSecrets: () =>
    request<NotificationConfig>("/api/notifications/secrets/clear", { method: "POST" }),
  cartAssistStatus: () => request<CartAssistStatus>("/api/cart-assist/status"),
  cartAttempts: () => request<CartAttempt[]>("/api/cart-assist/attempts"),
  updateCartAssistConfig: (payload: CartAssistConfigPayload) =>
    request<CartAssistStatus>("/api/cart-assist/config", { method: "PATCH", body: JSON.stringify(payload) }),
  clearCartAssistCredentials: () =>
    request<CartAssistStatus>("/api/cart-assist/credentials/clear", { method: "POST" }),
  updateCartAttemptStatus: (attemptId: number, status: CartAttemptStatus) =>
    request<CartAttempt>(`/api/cart-assist/attempts/${attemptId}`, {
      method: "PATCH",
      body: JSON.stringify({ status })
    }),
  notificationStatus: () => request<NotificationStatus>("/api/notifications/status"),
  testNotifications: () =>
    request<NotificationTestResult>("/api/notifications/test", { method: "POST" }),
  exportConfig: (includeSecrets = false) => request<ConfigBackup>(`/api/config/export?include_secrets=${includeSecrets}`),
  importConfig: (payload: ConfigBackup) =>
    request<ConfigImportResult>("/api/config/import", { method: "POST", body: JSON.stringify(payload) }),
  search: (query: string) => request<SearchSuggestion[]>(`/api/search?q=${encodeURIComponent(query)}`, undefined, PROVIDER_REQUEST_TIMEOUT_MS),
  campgroundDetails: (campgroundId: string) =>
    request<CampgroundDetails>(`/api/campgrounds/${encodeURIComponent(campgroundId)}/details`, undefined, PROVIDER_REQUEST_TIMEOUT_MS),
  createTarget: (payload: Record<string, unknown>) =>
    request<Target>("/api/targets", { method: "POST", body: JSON.stringify(payload) }),
  updateTarget: (targetId: number, payload: Record<string, unknown>) =>
    request<Target>(`/api/targets/${targetId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  detectTargetReleaseWindow: (targetId: number) =>
    request<{
      target: Target;
      detected: {
        release_window_value: number;
        release_window_unit: Target["release_window_unit"];
        sampled_month: string;
        source_campsite_count: number;
        total_campsite_count: number;
      };
    }>(`/api/targets/${targetId}/detect-release-window`, { method: "POST" }),
  releaseWindowProfiles: (targetId: number) =>
    request<ReleaseWindowProfileResult>(`/api/targets/${targetId}/release-window-profiles`, undefined, PROVIDER_REQUEST_TIMEOUT_MS),
  deleteTarget: (targetId: number) => request<{ deleted: boolean }>(`/api/targets/${targetId}`, { method: "DELETE" }),
  importPreset: (packId: string) =>
    request<{ pack_id: string; imported_count: number; updated_count: number; target_count: number }>(
      `/api/presets/${packId}/import`,
      { method: "POST" }
    ),
  discoverPreset: (packId: string) =>
    request<PresetDiscoveryResult>(`/api/presets/${packId}/discover`, { method: "POST" }),
  importDiscoveredPreset: (packId: string) =>
    request<PresetSourceImportResult>(`/api/presets/${packId}/import-discovered`, { method: "POST" }),
  discoverSource: (sourceId: string) =>
    request<SourceDiscoveryResult>(`/api/sources/${sourceId}/discover`, { method: "POST" }),
  resetSourceAccess: (sourceId: string) =>
    request<{ reset: boolean }>(`/api/sources/${sourceId}/reset-access`, { method: "POST" }),
  importSource: (sourceId: string) =>
    request<SourceImportResult>(`/api/sources/${sourceId}/import`, { method: "POST" }),
  createWatch: (payload: Record<string, unknown>) =>
    request<Watch>("/api/watches", { method: "POST", body: JSON.stringify(payload) }),
  updateWatch: (watchId: number, payload: Record<string, unknown>) =>
    request<Watch>(`/api/watches/${watchId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteWatch: (watchId: number) => request<{ deleted: boolean }>(`/api/watches/${watchId}`, { method: "DELETE" }),
  runScan: (watchId: number) =>
    request<{ status: string; message: string; candidate_count: number; available_count: number; missing_count?: number }>(
      `/api/watches/${watchId}/scan`,
      { method: "POST" }
    ),
  crawlStatus: () => request<CrawlStatus>("/api/scans/status"),
  runAllScans: () => request<CrawlStatus>("/api/scans/run-all", { method: "POST" }),
  clearResults: () => request<{ cleared_count: number }>("/api/results/clear", { method: "POST" }),
  updateResultStatus: (resultId: number, status: Result["status"]) =>
    request<Result>(`/api/results/${resultId}`, { method: "PATCH", body: JSON.stringify({ status }) })
};
