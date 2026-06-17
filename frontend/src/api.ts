import type {
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
  ReleaseWindowProfileResult,
  Result,
  ResultSummary,
  ScanAllResult,
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

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  targets: () => request<Target[]>("/api/targets"),
  presets: () => request<PresetPack[]>("/api/presets"),
  sources: () => request<SourceDefinition[]>("/api/sources"),
  watches: () => request<Watch[]>("/api/watches"),
  results: (limit = RESULTS_LIMIT) => request<Result[]>(`/api/results?limit=${limit}`),
  resultSummary: () => request<ResultSummary>("/api/results/summary"),
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
  search: (query: string) => request<SearchSuggestion[]>(`/api/search?q=${encodeURIComponent(query)}`),
  campgroundDetails: (campgroundId: string) =>
    request<CampgroundDetails>(`/api/campgrounds/${encodeURIComponent(campgroundId)}/details`),
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
    request<ReleaseWindowProfileResult>(`/api/targets/${targetId}/release-window-profiles`),
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
  runAllScans: () => request<ScanAllResult>("/api/scans/run-all", { method: "POST" }),
  clearResults: () => request<{ cleared_count: number }>("/api/results/clear", { method: "POST" }),
  updateResultStatus: (resultId: number, status: Result["status"]) =>
    request<Result>(`/api/results/${resultId}`, { method: "PATCH", body: JSON.stringify({ status }) })
};
