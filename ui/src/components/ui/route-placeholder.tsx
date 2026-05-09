import { PageHeader } from "./page-header";
import { WorkbenchCard } from "./workbench-card";
import { t } from "../../lib/i18n";

type RoutePlaceholderPageProps = {
  title: string;
  description: string;
  note: string;
};

export function RoutePlaceholderPage({ title, description, note }: RoutePlaceholderPageProps) {
  return (
    <div>
      <PageHeader eyebrow="Preview" title={title} description={description} />
      <WorkbenchCard>
        <h2 className="section-card__title">{t("页面入口已保留")}</h2>
        <p className="section-card__description" style={{ marginBottom: 0 }}>
          {note}
        </p>
      </WorkbenchCard>
    </div>
  );
}
