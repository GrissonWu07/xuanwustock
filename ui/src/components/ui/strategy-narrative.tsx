import { WorkbenchCard } from "./workbench-card";
import { t } from "../../lib/i18n";

type StrategyEvidence = {
  label: string;
  value: string;
};

type StrategyNarrativeProps = {
  title: string;
  summary: string;
  recommendation: string;
  reasons: string[];
  evidence: StrategyEvidence[];
};

export function StrategyNarrativeCard({ title, summary, recommendation, reasons, evidence }: StrategyNarrativeProps) {
  return (
    <WorkbenchCard>
      <h2 className="section-card__title">{title}</h2>
      <p className="section-card__description">{summary}</p>

      <div className="section-grid">
        <div className="summary-item">
          <div className="summary-item__title">{t("当前建议")}</div>
          <div className="summary-item__body">{recommendation}</div>
        </div>
        <div className="summary-item">
          <div className="summary-item__title">{t("核心原因")}</div>
          <ul className="insight-list" style={{ marginBottom: 0, marginTop: 0 }}>
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="card-divider" />

      <div className="summary-item summary-item--accent">
        <div className="summary-item__title">{t("量化证据")}</div>
        <div className="chip-row">
          {evidence.map((item) => (
            <span className="badge badge--neutral" key={item.label}>
              {item.label}：{item.value}
            </span>
          ))}
        </div>
      </div>
    </WorkbenchCard>
  );
}
