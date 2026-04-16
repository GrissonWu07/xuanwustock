import { Outlet } from "react-router-dom";
import { AppHeader } from "./components/layout/app-header";
import { AppSidebar } from "./components/layout/app-sidebar";
import { useI18nLocale } from "./lib/i18n";

export function AppShell() {
  const locale = useI18nLocale();

  return (
    <div className="app-shell" data-locale={locale}>
      <AppSidebar />
      <div className="app-shell__content">
        <AppHeader />
        <main className="app-shell__main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
