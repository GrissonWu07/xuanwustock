import { NavLink } from "react-router-dom";
import { APP_ROUTE_ITEMS } from "../../routes/manifest";
import { t } from "../../lib/i18n";

export function AppSidebar() {
  const groupKeys = Array.from(new Set(APP_ROUTE_ITEMS.map((item) => item.groupKey)));
  const groups = groupKeys.map((groupKey) => ({
    key: groupKey,
    title: t(groupKey),
    items: APP_ROUTE_ITEMS.filter((item) => item.groupKey === groupKey).map((item) => ({
      to: item.path,
      label: t(item.labelKey),
    })),
  }));

  return (
    <aside className="app-sidebar">
      <div className="app-sidebar__brand">
        <div className="app-sidebar__brand-title">{t("AI Stock Analyst Team")}</div>
        <div className="app-sidebar__brand-note">{t("Workbench entry for discovery, research, watchlist, and quant flow.")}</div>
      </div>
      {groups.map((group) => (
        <section className="app-sidebar__group" key={group.key}>
          <div className="app-sidebar__group-title">{group.title}</div>
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `app-sidebar__item${isActive ? " app-sidebar__item--active" : ""}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </section>
      ))}
    </aside>
  );
}
