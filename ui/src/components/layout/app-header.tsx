import { useLocation } from "react-router-dom";
import { APP_ROUTE_LABELS } from "../../routes/manifest";
import { setI18nLocale, t, useI18nLocale } from "../../lib/i18n";

export function AppHeader() {
  const location = useLocation();
  const locale = useI18nLocale();
  const title = t(APP_ROUTE_LABELS[location.pathname] ?? "Workbench");

  return (
    <header className="app-header">
      <div>
        <div className="app-header__title">{title}</div>
        <div className="app-header__subtitle">{t("AI Stock Analyst Team · Single-page Workbench")}</div>
      </div>
      <div className="app-header__actions">
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
