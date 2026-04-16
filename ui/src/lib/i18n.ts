import { useSyncExternalStore } from "react";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";

type Dict = Record<string, string>;
type Vars = Record<string, string | number>;
type Locale = "zh-CN" | "en-US";

const fallbackDict: Dict = enUS as Dict;
const STORAGE_KEY = "xuanwu.ui.locale";

const normalizeLocale = (value: string | undefined | null): Locale => {
  const locale = (value ?? "").toString().trim().toLowerCase();
  return locale.startsWith("zh") ? "zh-CN" : "en-US";
};

const envLocaleRaw = (import.meta.env.VITE_UI_LOCALE ?? "").toString().trim();
const envLocale = envLocaleRaw ? normalizeLocale(envLocaleRaw) : "en-US";

const readBrowserLocale = (): Locale => {
  if (typeof navigator === "undefined") return envLocale;
  const candidates = [...(navigator.languages ?? []), navigator.language, (navigator as { userLanguage?: string }).userLanguage].filter(Boolean);
  if (candidates.length === 0) return envLocale;
  return normalizeLocale(String(candidates[0]));
};

const readStoredLocale = (): Locale => {
  if (typeof window === "undefined") return envLocale;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored ? normalizeLocale(stored) : readBrowserLocale();
  } catch {
    return readBrowserLocale();
  }
};

let currentLocale: Locale = readStoredLocale();
let currentDict: Dict = currentLocale === "zh-CN" ? (zhCN as Dict) : (enUS as Dict);
const listeners = new Set<() => void>();

const notifyLocaleChange = () => {
  for (const listener of listeners) {
    listener();
  }
};

const persistLocale = (locale: Locale) => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Ignore persistence errors.
  }
};

const updateLocaleState = (locale: Locale) => {
  currentLocale = locale;
  currentDict = locale === "zh-CN" ? (zhCN as Dict) : (enUS as Dict);
  persistLocale(locale);
  notifyLocaleChange();
};

export function t(key: string, vars?: Vars): string {
  const template = currentDict[key] ?? fallbackDict[key] ?? key;
  if (!vars) {
    return template;
  }
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (_, name) => {
    if (Object.prototype.hasOwnProperty.call(vars, name)) {
      return String(vars[name]);
    }
    return `{${name}}`;
  });
}

export function setI18nLocale(locale: string) {
  const target = normalizeLocale(locale);
  if (target === currentLocale) return;
  updateLocaleState(target);
}

export function toggleI18nLocale() {
  setI18nLocale(currentLocale === "zh-CN" ? "en-US" : "zh-CN");
}

export function useI18nLocale(): Locale {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => currentLocale,
    () => currentLocale,
  );
}

export function i18nLocale() {
  return currentLocale;
}
