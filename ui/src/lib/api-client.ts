import type { PageKey, PageSnapshotMap } from "./page-models";
import { t } from "./i18n";
export type ApiMode = "live" | "hybrid" | "mock";

export type ApiClientOptions = {
  baseUrl?: string;
  mode?: ApiMode;
  fetchImpl?: typeof fetch;
};

export const PAGE_ENDPOINTS: Record<PageKey, string> = {
  workbench: "/api/v1/workbench",
  discover: "/api/v1/discover",
  research: "/api/v1/research",
  portfolio: "/api/v1/portfolio",
  "live-sim": "/api/v1/quant/live-sim",
  "his-replay": "/api/v1/quant/his-replay",
  "ai-monitor": "/api/v1/monitor/ai",
  "real-monitor": "/api/v1/monitor/real",
  history: "/api/v1/history",
  settings: "/api/v1/settings",
};

export const PAGE_ACTION_ENDPOINTS: Record<PageKey, Record<string, string>> = {
  workbench: {
    "add-watchlist": "/api/v1/workbench/actions/add-watchlist",
    "refresh-watchlist": "/api/v1/workbench/actions/refresh-watchlist",
    "batch-quant": "/api/v1/workbench/actions/batch-quant",
    analysis: "/api/v1/workbench/actions/analysis",
    "analysis-batch": "/api/v1/workbench/actions/analysis-batch",
    "clear-selection": "/api/v1/workbench/actions/clear-selection",
    "delete-watchlist": "/api/v1/workbench/actions/delete-watchlist",
  },
  discover: {
    "run-strategy": "/api/v1/discover/actions/run-strategy",
    "batch-watchlist": "/api/v1/discover/actions/batch-watchlist",
    "item-watchlist": "/api/v1/discover/actions/item-watchlist",
  },
  research: {
    "run-module": "/api/v1/research/actions/run-module",
    "batch-watchlist": "/api/v1/research/actions/batch-watchlist",
    "item-watchlist": "/api/v1/research/actions/item-watchlist",
  },
  portfolio: {
    analyze: "/api/v1/portfolio/actions/analyze",
    "refresh-portfolio": "/api/v1/portfolio/actions/refresh-portfolio",
    "schedule-save": "/api/v1/portfolio/actions/schedule-save",
    "schedule-start": "/api/v1/portfolio/actions/schedule-start",
    "schedule-stop": "/api/v1/portfolio/actions/schedule-stop",
  },
  "live-sim": {
    save: "/api/v1/quant/live-sim/actions/save",
    start: "/api/v1/quant/live-sim/actions/start",
    stop: "/api/v1/quant/live-sim/actions/stop",
    reset: "/api/v1/quant/live-sim/actions/reset",
    "analyze-candidate": "/api/v1/quant/live-sim/actions/analyze-candidate",
    "delete-candidate": "/api/v1/quant/live-sim/actions/delete-candidate",
    "bulk-quant": "/api/v1/quant/live-sim/actions/bulk-quant",
  },
  "his-replay": {
    start: "/api/v1/quant/his-replay/actions/start",
    continue: "/api/v1/quant/his-replay/actions/continue",
    cancel: "/api/v1/quant/his-replay/actions/cancel",
    delete: "/api/v1/quant/his-replay/actions/delete",
  },
  "ai-monitor": {
    start: "/api/v1/monitor/ai/actions/start",
    stop: "/api/v1/monitor/ai/actions/stop",
    analyze: "/api/v1/monitor/ai/actions/analyze",
    delete: "/api/v1/monitor/ai/actions/delete",
  },
  "real-monitor": {
    start: "/api/v1/monitor/real/actions/start",
    stop: "/api/v1/monitor/real/actions/stop",
    refresh: "/api/v1/monitor/real/actions/refresh",
    "update-rule": "/api/v1/monitor/real/actions/update-rule",
    "delete-rule": "/api/v1/monitor/real/actions/delete-rule",
  },
  history: {
    rerun: "/api/v1/history/actions/rerun",
  },
  settings: {
    save: "/api/v1/settings/actions/save",
  },
};

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

const DEFAULT_BASE_URL = import.meta.env.VITE_API_BASE ?? "";
const DEFAULT_MODE = (import.meta.env.VITE_UI_API_MODE as ApiMode | undefined) ?? "live";

const safeJson = (value: unknown) => JSON.stringify(value ?? {});

const isNetworkFailure = (error: unknown) =>
  error instanceof TypeError || (error instanceof Error && /fetch|network|Failed to fetch/i.test(error.message));

const parseResponseJson = async <T,>(response: Response, path: string): Promise<T> => {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }

  const text = await response.text();
  if (!text.trim()) {
    throw new ApiError("Empty response body", response.status, path);
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(`Invalid JSON response from ${path}`, response.status, path);
  }
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly url?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;
  const mode = options.mode ?? DEFAULT_MODE;
  const fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);

  const requestLive = async <T,>(path: string, request: RequestOptions = {}): Promise<T> => {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method: request.method ?? "GET",
      headers: {
        "Content-Type": "application/json",
      },
      body: request.body === undefined ? undefined : safeJson(request.body),
      signal: request.signal,
    });

    if (!response.ok) {
      throw new ApiError(`Request failed: ${response.status}`, response.status, path);
    }

    return await parseResponseJson<T>(response, path);
  };

  const requestPage = async <T,>(page: PageKey): Promise<T> => {
    if (mode === "mock") {
      throw new ApiError(t("Mock mode is test-only; use mock backend stubs"), 501, PAGE_ENDPOINTS[page]);
    }
    try {
      return await requestLive<T>(PAGE_ENDPOINTS[page]);
    } catch (error) {
      if (mode === "hybrid") {
        throw error;
      }
      throw error;
    }
  };

  const requestAction = async <T,>(page: PageKey, action: string, payload?: unknown): Promise<T> => {
    if (mode === "mock") {
      throw new ApiError(
        t("Mock mode is test-only; use mock backend stubs"),
        501,
        PAGE_ACTION_ENDPOINTS[page][action] ?? `${PAGE_ENDPOINTS[page]}/actions/${action}`,
      );
    }
    try {
      const endpoint = PAGE_ACTION_ENDPOINTS[page][action] ?? `${PAGE_ENDPOINTS[page]}/actions/${action}`;
      return await requestLive<T>(endpoint, {
        method: "POST",
        body: payload ?? {},
      });
    } catch (error) {
      if (mode === "hybrid") {
        throw error;
      }
      throw error;
    }
  };

  const requestTask = async <T,>(taskId: string): Promise<T> => {
    if (!taskId.trim()) {
      throw new ApiError(t("Missing task id"), 400, `/api/v1/tasks/${taskId}`);
    }
    return await requestLive<T>(`/api/v1/tasks/${taskId}`);
  };

  return {
    baseUrl,
    mode,
    getPageSnapshot: requestPage,
    runPageAction: requestAction,
    getTaskStatus: requestTask,
  };
}

export const apiClient = createApiClient();

export type ApiClient = ReturnType<typeof createApiClient>;

export type PageSnapshotFor<K extends PageKey> = PageSnapshotMap[K];

