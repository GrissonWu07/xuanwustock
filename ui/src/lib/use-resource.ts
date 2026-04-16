import { useEffect, useReducer, useState } from "react";
import { ApiError, fetchJson } from "./api";
import { t } from "./i18n";

type ResourceStatus = "idle" | "loading" | "success" | "error";

export type ResourceState<T> = {
  status: ResourceStatus;
  data: T | null;
  error: ApiError | null;
  reload: () => void;
};

type Options<T> = {
  enabled?: boolean;
  initialData?: T | null;
  transform?: (value: unknown) => T;
};

export function useResource<T>(path: string | null, options: Options<T> = {}): ResourceState<T> {
  const enabled = options.enabled ?? true;
  const [data, setData] = useState<T | null>(options.initialData ?? null);
  const [error, setError] = useState<ApiError | null>(null);
  const [status, setStatus] = useState<ResourceStatus>(enabled && path ? "loading" : "idle");
  const [version, bumpVersion] = useReducer((value: number) => value + 1, 0);

  useEffect(() => {
    if (!enabled || !path) {
      setStatus("idle");
      return;
    }

    const controller = new AbortController();
    let active = true;

    setStatus("loading");
    setError(null);

    fetchJson<unknown>(path, { signal: controller.signal })
      .then((value) => {
        if (!active) {
          return;
        }
        const nextValue = options.transform ? options.transform(value) : (value as T);
        setData(nextValue);
        setStatus("success");
      })
      .catch((requestError: unknown) => {
        if (!active || controller.signal.aborted) {
          return;
        }
        const apiError =
          requestError instanceof ApiError
            ? requestError
            : new ApiError(requestError instanceof Error ? requestError.message : t("Request failed"), path);
        setError(apiError);
        setStatus("error");
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [enabled, options, path, version]);

  return {
    status,
    data,
    error,
    reload: () => {
      if (enabled && path) {
        bumpVersion();
      }
    },
  };
}
