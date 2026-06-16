import type {
  ConfigBackup,
  ConfigImportResult,
  NotificationEvent,
  NotificationStatus,
  NotificationTestResult,
  PresetPack,
  ReleaseWindowProfileResult,
  Result,
  ScanAllResult,
  ScanRun,
  SearchSuggestion,
  Target,
  Watch
} from "./types";

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
  watches: () => request<Watch[]>("/api/watches"),
  results: () => request<Result[]>("/api/results"),
  scanRuns: () => request<ScanRun[]>("/api/scans"),
  notifications: () => request<NotificationEvent[]>("/api/notifications"),
  notificationStatus: () => request<NotificationStatus>("/api/notifications/status"),
  testNotifications: () =>
    request<NotificationTestResult>("/api/notifications/test", { method: "POST" }),
  exportConfig: () => request<ConfigBackup>("/api/config/export"),
  importConfig: (payload: ConfigBackup) =>
    request<ConfigImportResult>("/api/config/import", { method: "POST", body: JSON.stringify(payload) }),
  search: (query: string) => request<SearchSuggestion[]>(`/api/search?q=${encodeURIComponent(query)}`),
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
  createWatch: (payload: Record<string, unknown>) =>
    request<Watch>("/api/watches", { method: "POST", body: JSON.stringify(payload) }),
  updateWatch: (watchId: number, payload: Record<string, unknown>) =>
    request<Watch>(`/api/watches/${watchId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteWatch: (watchId: number) => request<{ deleted: boolean }>(`/api/watches/${watchId}`, { method: "DELETE" }),
  runScan: (watchId: number) =>
    request<{ status: string; message: string; candidate_count: number; available_count: number }>(
      `/api/watches/${watchId}/scan`,
      { method: "POST" }
    ),
  runAllScans: () => request<ScanAllResult>("/api/scans/run-all", { method: "POST" }),
  clearResults: () => request<{ cleared_count: number }>("/api/results/clear", { method: "POST" }),
  updateResultStatus: (resultId: number, status: Result["status"]) =>
    request<Result>(`/api/results/${resultId}`, { method: "PATCH", body: JSON.stringify({ status }) })
};
