import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { t, useI18nLocale } from "../../lib/i18n";

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
  { key: "pending_eligible", labelKey: "Pending quant entry", target: "/discover?eligible=1" },
  { key: "trial", labelKey: "Quant", target: "/live-sim?quant_status=trial" },
  { key: "active", labelKey: "Quant running", target: "/live-sim?quant_status=active" },
  { key: "exit_only", labelKey: "Exit-only management", target: "/live-sim?quant_status=exit_only" },
  { key: "cooling", labelKey: "Cooling", target: "/live-sim?quant_status=cooling" },
  { key: "manual_paused", labelKey: "Manual paused", target: "/live-sim?quant_status=manual_paused" },
  { key: "retired", labelKey: "Retired pending review", target: "/live-sim?quant_status=retired" },
] as const;

const normalizeCards = (payload: QuantOverviewPayload | null) =>
  CARD_ORDER.map((definition) => {
    const card = payload?.cards?.[definition.key] ?? {};
    return {
      ...definition,
      label: card.label || t(definition.labelKey),
      count: Number(card.count ?? 0),
      topItems: (card.top_items ?? []).slice(0, 3),
      latestReason: card.latest_reason || "",
    };
  });

export function QuantOverviewCards({ baseUrl = "" }: { baseUrl?: string }) {
  const navigate = useNavigate();
  const locale = useI18nLocale();
  const [payload, setPayload] = useState<QuantOverviewPayload | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const cards = useMemo(() => normalizeCards(payload), [payload, locale]);

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
    <section className="quant-command-strip" aria-label={t("Quant universe overview")}>
      <div className="quant-command-strip__header">
        <div>
          <h3 className="section-card__title" style={{ margin: 0 }}>
            {t("Quant status")}
          </h3>
          <p className="section-card__description" style={{ marginBottom: 0 }}>
            {status === "error" ? t("Quant status failed to load.") : t("Selected stocks can enter quant or be forced out from here.")}
          </p>
        </div>
      </div>
      <div className="quant-command-strip__chips">
        {cards.map((card) => (
          <button className="quant-command-chip" type="button" onClick={() => navigate(card.target)} key={card.key}>
            <span className="quant-command-chip__label">{card.label}</span>
            <span className="quant-command-chip__count">{status === "loading" ? "--" : card.count}</span>
            {card.latestReason ? <span className="quant-command-chip__reason">{card.latestReason}</span> : null}
          </button>
        ))}
      </div>
    </section>
  );
}

