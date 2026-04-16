import { t } from "./i18n";

export class ApiError extends Error {
  readonly endpoint: string;
  readonly status?: number;
  readonly payload?: unknown;

  constructor(message: string, endpoint: string, status?: number, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.endpoint = endpoint;
    this.status = status;
    this.payload = payload;
  }
}

const apiBase = import.meta.env.VITE_API_BASE?.trim() || "/api";

function joinSegments(...segments: string[]) {
  return segments
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map((segment, index) => (index === 0 ? segment.replace(/\/+$/, "") : segment.replace(/^\/+|\/+$/g, "")))
    .join("/");
}

export function buildApiUrl(path: string) {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  if (path.startsWith("/")) {
    return `${apiBase.replace(/\/+$/, "")}${path}`;
  }

  return joinSegments(apiBase, path);
}

async function readResponsePayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  const text = await response.text();
  return text.length > 0 ? text : null;
}

function extractMessage(payload: unknown, fallback: string) {
  if (typeof payload === "string" && payload.trim()) {
    return payload;
  }
  if (payload && typeof payload === "object") {
    const candidate = payload as Record<string, unknown>;
    if (typeof candidate.message === "string") {
      return candidate.message;
    }
    if (typeof candidate.detail === "string") {
      return candidate.detail;
    }
    if (typeof candidate.error === "string") {
      return candidate.error;
    }
  }
  return fallback;
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });

  const payload = await readResponsePayload(response);

  if (!response.ok) {
    throw new ApiError(
      extractMessage(payload, response.statusText || t("Request failed")),
      path,
      response.status,
      payload,
    );
  }

  return payload as T;
}

export async function postJson<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  return fetchJson<T>(path, {
    ...init,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    body: JSON.stringify(body),
  });
}
