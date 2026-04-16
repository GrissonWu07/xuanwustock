import { NavLink } from "react-router-dom";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { ActionTile } from "../../lib/page-models";
import { t } from "../../lib/i18n";

type NextStepsPanelProps = {
  steps: ActionTile[];
};

export function NextStepsPanel({ steps }: NextStepsPanelProps) {
  return (
    <WorkbenchCard>
      <h2 className="section-card__title">{t("Next step")}</h2>
      <p className="section-card__description">
        {t("Continue from watchlist into monitor, discover, research, or quant validation without switching around.")}
      </p>
      <div className="next-steps">
        {steps.map((step) => (
          <NavLink className="next-steps__item" key={step.label} to={step.href}>
            <div className="summary-item__title">{t(step.label)}</div>
            <div className="summary-item__body">{t(step.hint)}</div>
          </NavLink>
        ))}
      </div>
    </WorkbenchCard>
  );
}

