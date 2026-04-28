import type { PageKey, PageSnapshotMap } from "./page-models";
import { t } from "./i18n";
export type ApiMode = "live" | "hybrid";

export type ApiClientOptions = {
  baseUrl?: string;
  mode?: ApiMode;
  fetchImpl?: typeof fetch;
};

export const PAGE_ENDPOINTS: Record<PageKey, string> = {
  workbench: "/api/v1/workbench",
  discover: "/api/v1/discover",
  research: "/api/v1/research",
  portfolio: "/api/v1/portfolio_v2",
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
    "batch-portfolio": "/api/v1/workbench/actions/batch-portfolio",
    analysis: "/api/v1/workbench/actions/analysis",
    "analysis-batch": "/api/v1/workbench/actions/analysis-batch",
    "clear-selection": "/api/v1/workbench/actions/clear-selection",
    "delete-watchlist": "/api/v1/workbench/actions/delete-watchlist",
  },
  discover: {
    "run-strategy": "/api/v1/discover/actions/run-strategy",
    "batch-watchlist": "/api/v1/discover/actions/batch-watchlist",
    "item-watchlist": "/api/v1/discover/actions/item-watchlist",
    "reset-list": "/api/v1/discover/actions/reset-list",
  },
  research: {
    "run-module": "/api/v1/research/actions/run-module",
    "batch-watchlist": "/api/v1/research/actions/batch-watchlist",
    "item-watchlist": "/api/v1/research/actions/item-watchlist",
    "reset-list": "/api/v1/research/actions/reset-list",
  },
  portfolio: {
    analyze: "/api/v1/portfolio_v2/actions/analyze",
    "refresh-portfolio": "/api/v1/portfolio_v2/actions/refresh-portfolio",
    "schedule-save": "/api/v1/portfolio_v2/actions/schedule-save",
    "schedule-start": "/api/v1/portfolio_v2/actions/schedule-start",
    "schedule-stop": "/api/v1/portfolio_v2/actions/schedule-stop",
    "refresh-indicators": "/api/v1/portfolio_v2/actions/refresh-indicators",
    "update-position": "/api/v1/portfolio_v2/actions/update-position",
    "delete-position": "/api/v1/portfolio_v2/actions/delete-position",
  },
  "live-sim": {
    save: "/api/v1/quant/live-sim/actions/save",
    start: "/api/v1/quant/live-sim/actions/start",
    stop: "/api/v1/quant/live-sim/actions/stop",
    reset: "/api/v1/quant/live-sim/actions/reset",
    "analyze-candidate": "/api/v1/quant/live-sim/actions/analyze-candidate",
    "delete-candidate": "/api/v1/quant/live-sim/actions/delete-candidate",
    "delete-position": "/api/v1/quant/live-sim/actions/delete-position",
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
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

type QueryValue = string | number | boolean | null | undefined;

const withQuery = (path: string, query?: Record<string, QueryValue>) => {
  if (!query) return path;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.set(key, String(value));
  });
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path;
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

  const requestPage = async <T,>(page: PageKey, query?: Record<string, QueryValue>): Promise<T> => {
    try {
      return await requestLive<T>(withQuery(PAGE_ENDPOINTS[page], query));
    } catch (error) {
      if (mode === "hybrid") {
        throw error;
      }
      throw error;
    }
  };

  const requestAction = async <T,>(page: PageKey, action: string, payload?: unknown): Promise<T> => {
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

  const getReplayProgress = async <T,>(query?: Record<string, QueryValue>): Promise<T> =>
    requestLive<T>(withQuery("/api/v1/quant/his-replay/progress", query));

  const getReplayCapitalPool = async <T,>(query?: Record<string, QueryValue>): Promise<T> =>
    requestLive<T>(withQuery("/api/v1/quant/his-replay/capital-pool", query));

  const requestPortfolioPosition = async <T,>(symbol: string): Promise<T> => {
    if (!symbol.trim()) {
      throw new ApiError(t("Missing stock code"), 400, `/api/v1/portfolio_v2/positions/${symbol}`);
    }
    return await requestLive<T>(`/api/v1/portfolio_v2/positions/${encodeURIComponent(symbol)}`);
  };

  const patchPortfolioPosition = async <T,>(symbol: string, payload: unknown): Promise<T> => {
    if (!symbol.trim()) {
      throw new ApiError(t("Missing stock code"), 400, `/api/v1/portfolio_v2/positions/${symbol}`);
    }
    return await requestLive<T>(`/api/v1/portfolio_v2/positions/${encodeURIComponent(symbol)}`, {
      method: "PATCH",
      body: payload ?? {},
    });
  };

  const listStrategyProfiles = async <T,>(includeDisabled: boolean = true): Promise<T> =>
    requestLive<T>(`/api/v1/strategy-profiles?include_disabled=${includeDisabled ? "true" : "false"}`);

  const getStrategyProfile = async <T,>(profileId: string, versionsLimit: number = 20): Promise<T> => {
    if (!profileId.trim()) {
      throw new ApiError(t("Missing strategy profile id"), 400, "/api/v1/strategy-profiles");
    }
    return requestLive<T>(`/api/v1/strategy-profiles/${encodeURIComponent(profileId)}?versions_limit=${Math.max(1, versionsLimit)}`);
  };

  const createStrategyProfile = async <T,>(payload: unknown): Promise<T> =>
    requestLive<T>("/api/v1/strategy-profiles", { method: "POST", body: payload ?? {} });

  const updateStrategyProfile = async <T,>(profileId: string, payload: unknown): Promise<T> => {
    if (!profileId.trim()) {
      throw new ApiError(t("Missing strategy profile id"), 400, "/api/v1/strategy-profiles");
    }
    return requestLive<T>(`/api/v1/strategy-profiles/${encodeURIComponent(profileId)}`, {
      method: "PUT",
      body: payload ?? {},
    });
  };

  const cloneStrategyProfile = async <T,>(profileId: string, payload: unknown): Promise<T> => {
    if (!profileId.trim()) {
      throw new ApiError(t("Missing strategy profile id"), 400, "/api/v1/strategy-profiles");
    }
    return requestLive<T>(`/api/v1/strategy-profiles/${encodeURIComponent(profileId)}/clone`, {
      method: "POST",
      body: payload ?? {},
    });
  };

  const validateStrategyProfile = async <T,>(profileId: string, payload: unknown): Promise<T> => {
    if (!profileId.trim()) {
      throw new ApiError(t("Missing strategy profile id"), 400, "/api/v1/strategy-profiles");
    }
    return requestLive<T>(`/api/v1/strategy-profiles/${encodeURIComponent(profileId)}/validate`, {
      method: "POST",
      body: payload ?? {},
    });
  };

  const setDefaultStrategyProfile = async <T,>(profileId: string): Promise<T> => {
    if (!profileId.trim()) {
      throw new ApiError(t("Missing strategy profile id"), 400, "/api/v1/strategy-profiles");
    }
    return requestLive<T>(`/api/v1/strategy-profiles/${encodeURIComponent(profileId)}/set-default`, {
      method: "POST",
      body: {},
    });
  };

  const deleteStrategyProfile = async <T,>(profileId: string): Promise<T> => {
    if (!profileId.trim()) {
      throw new ApiError(t("Missing strategy profile id"), 400, "/api/v1/strategy-profiles");
    }
    return requestLive<T>(`/api/v1/strategy-profiles/${encodeURIComponent(profileId)}`, {
      method: "DELETE",
    });
  };

  return {
    baseUrl,
    mode,
    getPageSnapshot: requestPage,
    runPageAction: requestAction,
    getTaskStatus: requestTask,
    getReplayProgress,
    getReplayCapitalPool,
    getPortfolioPosition: requestPortfolioPosition,
    patchPortfolioPosition,
    listStrategyProfiles,
    getStrategyProfile,
    createStrategyProfile,
    updateStrategyProfile,
    cloneStrategyProfile,
    validateStrategyProfile,
    setDefaultStrategyProfile,
    deleteStrategyProfile,
  };
}

export const apiClient = createApiClient();

export type ApiClient = ReturnType<typeof createApiClient>;

export type PageSnapshotFor<K extends PageKey> = PageSnapshotMap[K];

