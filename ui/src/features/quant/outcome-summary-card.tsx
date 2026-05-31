import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { SignalOutcomeSummary } from "../../lib/page-models";
import { t } from "../../lib/i18n";

type OutcomeSummaryCardProps = {
  summary?: SignalOutcomeSummary | null;
};

function formatScore(value: unknown) {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed)) return "--";
  return parsed.toFixed(1);
}

function formatCount(value: unknown) {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed)) return "0";
  return String(Math.trunc(parsed));
}

function hasOutcomeRows(summary?: SignalOutcomeSummary | null) {
  return Number(summary?.total_count ?? 0) > 0 || Number(summary?.mature_count ?? 0) > 0;
}

export function OutcomeSummaryCard({ summary }: OutcomeSummaryCardProps) {
  if (!hasOutcomeRows(summary)) return null;
  const metrics = [
    { label: t("成熟 outcome"), value: formatCount(summary?.mature_count) },
    { label: t("BUY 平均分"), value: formatScore(summary?.buy_avg_score) },
    { label: t("SELL 平均分"), value: formatScore(summary?.sell_avg_score) },
    { label: t("高风险 BUY"), value: formatCount(summary?.bad_buy_count) },
    { label: t("有效 SELL"), value: formatCount(summary?.good_sell_count) },
  ];
  const skippedCount = Number(summary?.skipped_count ?? 0);
  return (
    <WorkbenchCard>
      <h2 className="section-card__title">{t("信号 outcome 复盘")}</h2>
      <p className="section-card__description">{t("按已成熟的 3/5/10 检查点窗口评估 BUY/SELL 后续表现，用于解释信号质量和反馈门控。")}</p>
      <div className="execution-summary execution-summary--finance" aria-label={t("信号 outcome 复盘")}>
        <div className="execution-summary__hero">
          <div className="execution-summary__hero-card execution-summary__hero-card--primary">
            <span>{t("已评分信号")}</span>
            <strong>{formatCount(summary?.total_count)}</strong>
            <em>
              {t("成熟 {v0} · 未成熟/跳过 {v1}", {
                v0: formatCount(summary?.mature_count),
                v1: formatCount(skippedCount),
              })}
            </em>
          </div>
          {metrics.map((metric) => (
            <div className="execution-summary__hero-card" key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </div>
          ))}
        </div>
      </div>
    </WorkbenchCard>
  );
}
