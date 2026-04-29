import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { APP_ROUTE_LABELS } from "../../routes/manifest";
import { setI18nLocale, t, useI18nLocale } from "../../lib/i18n";

type VersionInfo = {
  version?: string;
  display?: string;
  tag?: string;
  revision?: string;
  describe?: string;
  dirty?: boolean;
};

export function AppHeader() {
  const location = useLocation();
  const locale = useI18nLocale();
  const [versionInfo, setVersionInfo] = useState<VersionInfo | null>(null);
  const titleKey = location.pathname.startsWith("/signal-detail/")
    ? "Signal detail"
    : location.pathname.startsWith("/portfolio/position/")
      ? "Portfolio"
      : APP_ROUTE_LABELS[location.pathname] ?? "Workbench";
  const title = t(titleKey);
  const versionLabel = versionInfo?.display || versionInfo?.version || versionInfo?.describe || "";
  const versionTitle = versionInfo
    ? `tag ${versionInfo.tag || "--"} · revision ${versionInfo.revision || "--"}${versionInfo.dirty ? " · dirty" : ""}`
    : "";

  useEffect(() => {
    let cancelled = false;

    async function loadVersion() {
      try {
        const response = await fetch("/api/v1/version", { headers: { Accept: "application/json" } });
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as VersionInfo;
        if (!cancelled) {
          setVersionInfo(payload);
        }
      } catch {
        // Version display is informational only.
      }
    }

    void loadVersion();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="app-header">
      <div>
        <div className="app-header__title">{title}</div>
        <div className="app-header__subtitle">{t("AI Stock Analyst Team · Single-page Workbench")}</div>
      </div>
      <div className="app-header__actions">
        {versionLabel ? (
          <span className={`app-version-pill${versionInfo?.dirty ? " app-version-pill--dirty" : ""}`} title={versionTitle}>
            <span>{t("Version")}</span>
            <strong>{versionLabel}</strong>
          </span>
        ) : null}
        <div className="locale-switch" role="group" aria-label={t("Language")}>
          <button
            type="button"
            className={`locale-switch__option${locale === "zh-CN" ? " locale-switch__option--active" : ""}`}
            onClick={() => setI18nLocale("zh-CN")}
          >
            {t("Chinese")}
          </button>
          <button
            type="button"
            className={`locale-switch__option${locale === "en-US" ? " locale-switch__option--active" : ""}`}
            onClick={() => setI18nLocale("en-US")}
          >
            {t("English")}
          </button>
        </div>
      </div>
    </header>
  );
}
