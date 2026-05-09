import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { t } from "../../lib/i18n";

type QuantOverviewItem = {
  stock_code?: string;
  stock_name?: string;
  latest_reason?: string;
};

type QuantOverviewCard = {
  label?: string;
  count?: number;
  top_items?: QuantOverviewItem[];
  latest_reason?: string;
};

type QuantOverviewPayload = {
  cards?: Record<string, QuantOverviewCard>;
};

const OVERVIEW_ENDPOINT = "/api/v1/quant/universe/overview";

const CARD_ORDER = [
  { key: "pending_eligible", label: t("待纳入量化"), target: "/discover?eligible=1" },
  { key: "trial", label: t("量化观察"), target: "/live-sim?quant_status=trial" },
  { key: "exit_only", label: t("只出场管理"), target: "/live-sim?quant_status=exit_only" },
  { key: "cooling", label: t("冷却中"), target: "/live-sim?quant_status=cooling" },
  { key: "retired", label: t("已退出待重评估"), target: "/live-sim?quant_status=retired" },
] as const;

const normalizeCards = (payload: QuantOverviewPayload | null) =>
  CARD_ORDER.map((definition) => {
    const card = payload?.cards?.[definition.key] ?? {};
    return {
      ...definition,
      label: card.label || definition.label,
      count: Number(card.count ?? 0),
      topItems: (card.top_items ?? []).slice(0, 3),
      latestReason: card.latest_reason || "",
    };
  });

export function QuantOverviewCards({ baseUrl = "" }: { baseUrl?: string }) {
  const navigate = useNavigate();
  const [payload, setPayload] = useState<QuantOverviewPayload | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const cards = useMemo(() => normalizeCards(payload), [payload]);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetch(`${baseUrl}${OVERVIEW_ENDPOINT}`, { method: "GET" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Request failed: ${response.status}`);
        }
        return response.json() as Promise<QuantOverviewPayload>;
      })
      .then((next) => {
        if (!cancelled) {
          setPayload(next);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  return (
    <section className="quant-overview" aria-label={t("Quant universe overview")}>
      <div className="toolbar toolbar--compact">
        <div>
          <h2 className="section-card__title" style={{ margin: 0 }}>
            {t("Quant overview")}
          </h2>
          <p className="section-card__description" style={{ marginBottom: 0 }}>
            {status === "error" ? t("Quant overview failed to load.") : t("Current quant universe lifecycle snapshot.")}
          </p>
        </div>
      </div>
      <div className="metric-grid quant-overview__grid" style={{ marginTop: "10px" }}>
        {cards.map((card) => (
          <WorkbenchCard className="metric-card quant-overview__card" key={card.key}>
            <button
              className="button button--ghost quant-overview__button"
              type="button"
              onClick={() => navigate(card.target)}
              style={{
                width: "100%",
                display: "grid",
                gap: "8px",
                justifyItems: "start",
                textAlign: "left",
                background: "transparent",
                border: 0,
                padding: 0,
                color: "inherit",
              }}
            >
              <span className="metric-card__label">{card.label}</span>
              <span className="metric-card__value">{status === "loading" ? "--" : card.count}</span>
              {card.latestReason ? <span className="summary-item__meta">{card.latestReason}</span> : null}
              {card.topItems.length > 0 ? (
                <span className="summary-list" style={{ gap: "4px", width: "100%" }}>
                  {card.topItems.map((item) => (
                    <span className="summary-item__body" key={`${card.key}-${item.stock_code}`}>
                      {item.stock_code} · {item.stock_name || "--"}
                      {item.latest_reason ? <span className="summary-item__meta"> {item.latest_reason}</span> : null}
                    </span>
                  ))}
                </span>
              ) : null}
            </button>
          </WorkbenchCard>
        ))}
      </div>
    </section>
  );
}

