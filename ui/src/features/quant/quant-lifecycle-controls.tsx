import type { ReactNode } from "react";
import { t } from "../../lib/i18n";

export type QuantStatus = "trial" | "active" | "exit_only" | "cooling" | "retired" | "manual_paused" | string;

export type QuantLifecycleSettings = {
  quant_universe_lifecycle_enabled: boolean;
  auto_entry_mode: string;
  auto_exit_enabled: boolean;
};

export type QuantLifecyclePayload = {
  quant_status?: QuantStatus;
  health_score?: number;
  latest_reason?: string;
  quant_auto_managed?: boolean;
  quant_manual_override?: string;
};

export const DEFAULT_LIFECYCLE_SETTINGS: QuantLifecycleSettings = {
  quant_universe_lifecycle_enabled: true,
  auto_entry_mode: "confirm_first",
  auto_exit_enabled: true,
};

export const QUANT_STATUS_OPTIONS = ["trial", "active", "exit_only", "cooling", "retired", "manual_paused"];
export const DEFAULT_QUANT_STATUS_FILTERS = ["trial", "active", "exit_only"];

const AUTO_ENTRY_MODE_OPTIONS = [
  { value: "manual_only", label: t("只记录候选") },
  { value: "confirm_first", label: t("确认后纳入") },
  { value: "auto_trial", label: t("自动纳入观察") },
];

const statusLabels: Record<string, string> = {
  trial: t("量化观察"),
  active: t("正常扫描"),
  exit_only: t("只出场"),
  cooling: t("冷却"),
  retired: t("已退出"),
  manual_paused: t("手工暂停"),
};

const statusTone: Record<string, string> = {
  trial: "badge--accent",
  active: "badge--success",
  exit_only: "badge--warning",
  cooling: "badge--warning",
  retired: "badge--neutral",
  manual_paused: "badge--neutral",
};

const clampScore = (value: number | undefined) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 100;
  return Math.max(0, Math.min(100, parsed));
};

export function normalizeLifecycleSettings(value: Partial<QuantLifecycleSettings> | undefined): QuantLifecycleSettings {
  return {
    quant_universe_lifecycle_enabled: Boolean(
      value?.quant_universe_lifecycle_enabled ?? DEFAULT_LIFECYCLE_SETTINGS.quant_universe_lifecycle_enabled,
    ),
    auto_entry_mode: String(value?.auto_entry_mode ?? DEFAULT_LIFECYCLE_SETTINGS.auto_entry_mode),
    auto_exit_enabled: Boolean(value?.auto_exit_enabled ?? DEFAULT_LIFECYCLE_SETTINGS.auto_exit_enabled),
  };
}

export function quantStatusLabel(status: string | undefined) {
  const normalized = String(status || "inactive");
  return statusLabels[normalized] ?? normalized;
}

export function LifecycleMasterSwitch({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="field">
      <span className="field__label">{t("量化生命周期")}</span>
      <input
        aria-label={t("量化生命周期")}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

export function AutoEntryModeSelect({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span className="field__label">{t("自动入池模式")}</span>
      <select
        aria-label={t("自动入池模式")}
        className="input"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {AUTO_ENTRY_MODE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AutoExitSwitch({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="field">
      <span className="field__label">{t("自动出池")}</span>
      <input aria-label={t("自动出池")} type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

export function LifecycleSummaryBadgeGroup({ settings }: { settings: QuantLifecycleSettings }) {
  const entryMode = AUTO_ENTRY_MODE_OPTIONS.find((option) => option.value === settings.auto_entry_mode)?.label ?? settings.auto_entry_mode;
  return (
    <div className="chip-row" aria-label={t("量化生命周期摘要")}>
      <span className={settings.quant_universe_lifecycle_enabled ? "badge badge--success" : "badge badge--neutral"}>
        {settings.quant_universe_lifecycle_enabled ? t("生命周期开启") : t("生命周期关闭")}
      </span>
      <span className="badge badge--accent">{entryMode}</span>
      <span className={settings.auto_exit_enabled ? "badge badge--warning" : "badge badge--neutral"}>
        {settings.auto_exit_enabled ? t("自动出池开启") : t("自动出池关闭")}
      </span>
    </div>
  );
}

export function StatusFilterChips({
  available,
  selected,
  onToggle,
}: {
  available: string[];
  selected: string[];
  onToggle: (status: string) => void;
}) {
  return (
    <div className="chip-row" aria-label={t("生命周期状态筛选")}>
      {available.map((status) => {
        const active = selected.includes(status);
        return (
          <button
            key={status}
            type="button"
            className={active ? "chip chip--active" : "chip"}
            aria-pressed={active}
            onClick={() => onToggle(status)}
          >
            <span>{quantStatusLabel(status)}</span>
          </button>
        );
      })}
    </div>
  );
}

export function QuantStatusBadge({ status }: { status: string | undefined }) {
  const normalized = String(status || "inactive");
  return <span className={`badge ${statusTone[normalized] ?? "badge--neutral"}`}>{quantStatusLabel(normalized)}</span>;
}

export function HealthScoreBar({ value }: { value: number | undefined }) {
  const score = clampScore(value);
  const tone = score >= 65 ? "success" : score >= 35 ? "warning" : "danger";
  return (
    <span className={`health-score health-score--${tone}`} aria-label={t("健康 {v0}", { v0: Math.round(score) })}>
      <span>{t("健康 {score}", { score: Math.round(score) })}</span>
      <span
        aria-hidden="true"
        style={{
          display: "block",
          width: "72px",
          height: "6px",
          borderRadius: "999px",
          background: "rgba(148, 163, 184, 0.24)",
          overflow: "hidden",
          marginTop: "4px",
        }}
      >
        <span
          style={{
            display: "block",
            width: `${score}%`,
            height: "100%",
            background: score >= 65 ? "#16a34a" : score >= 35 ? "#d97706" : "#dc2626",
          }}
        />
      </span>
    </span>
  );
}

export function AutoManageToggle({
  autoManaged,
  stockCode,
  onToggle,
}: {
  autoManaged: boolean;
  stockCode: string;
  onToggle: () => void;
}) {
  return (
    <button className="icon-button icon-button--neutral" type="button" aria-label={t("{v0} {v1}", { v0: autoManaged ? t("暂停自动管理") : t("启用自动管理"), v1: stockCode })} onClick={onToggle}>
      {autoManaged ? "⏸" : "▶"}
    </button>
  );
}

export function RestoreToTrialButton({ stockCode, onRestore }: { stockCode: string; onRestore: () => void }) {
  return (
    <button className="icon-button icon-button--accent" type="button" aria-label={t("恢复到量化观察 {v0}", { v0: stockCode })} onClick={onRestore}>
      ↩
    </button>
  );
}

export function LifecycleReason({ children }: { children: ReactNode }) {
  return <span className="table-cell-muted">{children || "--"}</span>;
}
