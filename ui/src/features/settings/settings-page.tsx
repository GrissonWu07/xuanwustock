import { useEffect, useMemo, useState, type ReactElement } from "react";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { SectionEmptyState } from "../../components/ui/section-empty";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import type { ConfigSettingItem } from "../../lib/page-models";
import { t } from "../../lib/i18n";
import {
  LifecycleSummaryBadgeGroup,
  ScoreBasedQuantAutomationSwitch,
  isScoreBasedQuantAutomationEnabled,
  normalizeLifecycleSettings,
  withScoreBasedQuantAutomation,
  type QuantLifecycleSettings,
} from "../quant/quant-lifecycle-controls";

type SettingsPageProps = {
  client?: ApiClient;
};

type EditableConfigField = ConfigSettingItem & {
  key: string;
  value: string;
};

const PINNED_RUNTIME_KEYS = ["DISCOVER_TOP_N", "RESEARCH_TOP_N"] as const;

const SETTINGS_KEY_LABELS: Record<string, string> = {
  AI_API_KEY: "AI API key",
  AI_API_BASE_URL: "AI API URL",
  DEFAULT_MODEL_NAME: "Default model",
  DISCOVER_TOP_N: "Discover candidate count",
  RESEARCH_TOP_N: "Research stock output count",
  TUSHARE_TOKEN: "Tushare token",
  MINIQMT_ENABLED: "Enable MiniQMT",
  MINIQMT_ACCOUNT_ID: "MiniQMT account ID",
  MINIQMT_HOST: "MiniQMT host",
  MINIQMT_PORT: "MiniQMT port",
  EMAIL_ENABLED: "Enable email notification",
  SMTP_SERVER: "SMTP server",
  SMTP_PORT: "SMTP port",
  EMAIL_FROM: "Sender email",
  EMAIL_PASSWORD: "Email auth code",
  EMAIL_TO: "Recipient email",
  WEBHOOK_ENABLED: "Enable webhook notification",
  WEBHOOK_TYPE: "Webhook type",
  WEBHOOK_URL: "Webhook URL",
  WEBHOOK_KEYWORD: "Webhook keyword",
};

const resolveFieldLabel = (item: EditableConfigField): string => {
  const mapped = SETTINGS_KEY_LABELS[item.key];
  if (mapped) return t(mapped);
  if (item.title?.trim()) return t(item.title);
  return item.key;
};

const parseValue = (item: ConfigSettingItem): string => {
  if (typeof item.value === "string") {
    return item.value;
  }

  const body = item.body ?? "";
  if (!body.trim()) {
    return "";
  }

  const legacyMarkers = [t("当前值:"), "Current value:", "Value:"];
  for (const marker of legacyMarkers) {
    const markerIndex = body.lastIndexOf(marker);
    if (markerIndex >= 0) {
      return body.slice(markerIndex + marker.length).trim();
    }
  }

  return "";
};

const normalizeField = (item: ConfigSettingItem, index: number): EditableConfigField => ({
  ...item,
  key: item.key?.trim() || `setting-${index}`,
  value: parseValue(item),
});

const toInputType = (field: EditableConfigField): "text" | "password" | "number" => {
  const typeName = `${field.type ?? "text"}`;
  if (typeName === "password") return "password";
  if (typeName === "number") return "number";
  if (typeName === "boolean") return "text";
  return "text";
};

const toBooleanOptions = (value: string) => {
  const normalized = value.toLowerCase();
  if (normalized === "true") return "true";
  if (normalized === "1") return "true";
  return "false";
};

const renderFieldControl = (
  field: EditableConfigField,
  id: string,
  value: string,
  onChange: (next: string) => void,
): ReactElement => {
  const inputType = toInputType(field);
  const isModelField = field.key === "DEFAULT_MODEL_NAME";
  const hasOptions = field.type === "select" || isModelField;
  const selectOptions = hasOptions && Array.isArray(field.options) ? field.options.slice() : [];
  const selectOptionsWithFallback = hasOptions && selectOptions.length > 0 ? selectOptions : [value];

  if (field.type === "boolean") {
    return (
      <select
        className="input"
        id={id}
        value={toBooleanOptions(value)}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="true">{t("Bool:true")}</option>
        <option value="false">{t("Bool:false")}</option>
      </select>
    );
  }

  if (hasOptions) {
    const options = selectOptionsWithFallback;
    return (
      <select
        className="input"
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }

  return <input className="input" id={id} type={inputType} value={value} onChange={(event) => onChange(event.target.value)} />;
};

const renderFields = (
  sectionTitle: string,
  items: EditableConfigField[],
  values: Record<string, string>,
  onChange: (key: string, value: string) => void,
): ReactElement => {
  if (items.length === 0) {
    return <SectionEmptyState title={t("{section} has no data", { section: t(sectionTitle) })} description={t("No settings found for this section.")} />;
  }

  return (
    <div className="settings-fields-grid">
      {items.map((item) => {
        const fieldValue = values[item.key] ?? "";
        const fieldLabel = resolveFieldLabel(item);
        return (
          <div className="settings-field-card" key={item.key}>
            <div className="settings-field-card__header">
              <label className="field__label" htmlFor={`setting-${item.key}`}>
                {fieldLabel}
              </label>
              {item.required ? <span className="badge badge--warning">{t("Required")}</span> : null}
            </div>
            {renderFieldControl(item, `setting-${item.key}`, fieldValue, (next) => onChange(item.key, next))}
          </div>
        );
      })}
    </div>
  );
};

export function SettingsPage({ client }: SettingsPageProps) {
  const effectiveClient = client ?? apiClient;
  const resource = usePageData("settings", effectiveClient);
  const [values, setValues] = useState<Record<string, string>>({});
  const [savedValues, setSavedValues] = useState<Record<string, string>>({});
  const [quantLifecycleSettings, setQuantLifecycleSettings] = useState<QuantLifecycleSettings>(() => normalizeLifecycleSettings(undefined));
  const [savedQuantLifecycleSettings, setSavedQuantLifecycleSettings] = useState<QuantLifecycleSettings>(() => normalizeLifecycleSettings(undefined));

  const dataSources = useMemo(
    () => (resource.data?.dataSources ?? []).map((item, index) => normalizeField(item, index)),
    [resource.data?.dataSources],
  );

  const modelConfig = useMemo(
    () => (resource.data?.modelConfig ?? []).map((item, index) => normalizeField(item, index + (resource.data?.dataSources?.length ?? 0))),
    [resource.data?.dataSources?.length, resource.data?.modelConfig],
  );

  const runtimeParams = useMemo(
    () =>
      (resource.data?.runtimeParams ?? []).map(
        (item, index) => normalizeField(item, index + (resource.data?.dataSources?.length ?? 0) + (resource.data?.modelConfig?.length ?? 0)),
      ),
    [resource.data?.dataSources?.length, resource.data?.modelConfig?.length, resource.data?.runtimeParams],
  );

  const pinnedRuntimeParams = useMemo(
    () => runtimeParams.filter((item) => PINNED_RUNTIME_KEYS.includes(item.key as (typeof PINNED_RUNTIME_KEYS)[number])),
    [runtimeParams],
  );

  const runtimeParamsRemaining = useMemo(
    () => runtimeParams.filter((item) => !PINNED_RUNTIME_KEYS.includes(item.key as (typeof PINNED_RUNTIME_KEYS)[number])),
    [runtimeParams],
  );

  useEffect(() => {
    const nextValues = [...dataSources, ...modelConfig, ...runtimeParams].reduce(
      (acc, item) => ({
        ...acc,
        [item.key]: item.value,
      }),
      {} as Record<string, string>,
    );
    setValues((prev) => {
      const changed = JSON.stringify(prev) !== JSON.stringify(nextValues);
      return changed ? nextValues : prev;
    });
    setSavedValues(nextValues);
  }, [dataSources, modelConfig, runtimeParams]);

  useEffect(() => {
    const nextSettings = normalizeLifecycleSettings(resource.data?.quantLifecycleSettings);
    setQuantLifecycleSettings((prev) => (JSON.stringify(prev) === JSON.stringify(nextSettings) ? prev : nextSettings));
    setSavedQuantLifecycleSettings(nextSettings);
  }, [resource.data?.quantLifecycleSettings]);

  const dirty = useMemo(() => {
    const current = values;
    const saved = savedValues;
    const allKeys = new Set([...Object.keys(current), ...Object.keys(saved)]);

    for (const key of allKeys) {
      if ((current[key] ?? "") !== (saved[key] ?? "")) {
        return true;
      }
    }

    return JSON.stringify(quantLifecycleSettings) !== JSON.stringify(savedQuantLifecycleSettings);
  }, [quantLifecycleSettings, savedQuantLifecycleSettings, savedValues, values]);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title={t("Settings loading...")} description={t("Loading model, data source, and runtime params.")} />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title={t("Settings failed to load")}
        description={resource.error ?? t("Unable to load settings. Please retry later.")}
        actionLabel={t("Reload")}
        onAction={resource.refresh}
      />
    );
  }

  const snapshot = resource.data;
  if (!snapshot) {
    return <PageEmptyState title={t("Settings has no data")} description={t("Backend has not returned a settings snapshot yet.")} actionLabel={t("Refresh")} onAction={resource.refresh} />;
  }

  const submit = () => {
    void resource.runAction(
      "save",
      {
        env: Object.fromEntries([...dataSources, ...modelConfig, ...runtimeParams].map((item) => [item.key, values[item.key] ?? item.value])),
        quantLifecycleSettings,
      },
    );
  };

  const onChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div>
      <PageHeader
        eyebrow={t("Settings")}
        title={t("Environment settings")}
        description={t("Edit and save model, data source, and runtime configuration.")}
      />

      <div className="stack">
        <div className="toolbar settings-toolbar">
          <span className="toolbar__spacer" />
          <button className="button button--secondary settings-toolbar__button" type="button" onClick={resource.refresh}>
            {t("Refresh settings")}
          </button>
          <button
            className="button button--primary settings-toolbar__button"
            type="button"
            disabled={!dirty}
            onClick={submit}
          >
            {t("Save all settings")}
          </button>
        </div>

        <WorkbenchCard className="settings-card settings-card--highlight">
          <h2 className="section-card__title settings-card__title">{t("Output count settings")}</h2>
          {renderFields("Output count settings", pinnedRuntimeParams, values, onChange)}
        </WorkbenchCard>

        <WorkbenchCard className="settings-card settings-card--highlight">
          <div className="toolbar">
            <h2 className="section-card__title settings-card__title" style={{ margin: 0 }}>{t("量化策略自动化")}</h2>
          </div>
          <p className="section-card__description">
            {t("开启后，系统会按候选评分自动纳入量化，并启用生命周期出池；关闭后只记录候选事件，不自动进入实时量化。")}</p>
          <LifecycleSummaryBadgeGroup settings={quantLifecycleSettings} />
          <div className="summary-list">
            <ScoreBasedQuantAutomationSwitch
              checked={isScoreBasedQuantAutomationEnabled(quantLifecycleSettings)}
              onChange={(checked) => setQuantLifecycleSettings(withScoreBasedQuantAutomation(checked))}
            />
          </div>
          <p className="section-card__description">
            {t("这个开关是一个完整自动化口径：入池、出池和生命周期同步开启或关闭。")}</p>
        </WorkbenchCard>

        <div className="settings-layout">
          <WorkbenchCard className="settings-card">
            <h2 className="section-card__title settings-card__title">{t("Model config")}</h2>
            {renderFields("Model config", modelConfig, values, onChange)}
          </WorkbenchCard>

          <WorkbenchCard className="settings-card">
            <h2 className="section-card__title settings-card__title">{t("Data sources")}</h2>
            {renderFields("Data sources", dataSources, values, onChange)}
          </WorkbenchCard>

          <WorkbenchCard className="settings-card settings-card--full">
            <h2 className="section-card__title settings-card__title">{t("Runtime parameters")}</h2>
            {renderFields("Runtime parameters", runtimeParamsRemaining, values, onChange)}
          </WorkbenchCard>
        </div>
      </div>
    </div>
  );
}

