import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { t } from "../../lib/i18n";
import { useCompactLayout } from "../../lib/use-compact-layout";
import { localizeDecisionCode, localizeStrategyMode } from "./quant-decision-localizer";

type VoteRow = {
  factor: string;
  signal: string;
  score: string;
  reason: string;
};

type IndicatorRow = {
  name: string;
  value: string;
  source: string;
  note?: string;
};

type ThresholdRow = {
  name: string;
  value: string;
};

type ParameterDetailRow = {
  name: string;
  value: string;
  source: string;
  derivation: string;
};

type VoteDetailRow = {
  track: string;
  voter: string;
  signal: string;
  score: string;
  weight: string;
  contribution: string;
  reason: string;
  calculation: string;
};

type VoteOverview = {
  voterCount: number;
  technicalVoterCount: number;
  contextVoterCount: number;
  formula: string;
  technicalAggregation: string;
  contextAggregation: string;
  rows: VoteDetailRow[];
};

type AiMonitorValueRow = {
  label: string;
  value: string;
  note?: string;
};

type AiMonitorHistoryRow = {
  id: string;
  decisionTime: string;
  action: string;
  confidence: string;
  riskLevel: string;
  positionSizePct: string;
  stopLossPct: string;
  takeProfitPct: string;
  tradingSession: string;
  executed: boolean;
  executionResult: string;
  reasoning: string;
};

type AiMonitorTradeRow = {
  id: string;
  tradeTime: string;
  tradeType: string;
  quantity: string;
  price: string;
  amount: string;
  commission: string;
  tax: string;
  profitLoss: string;
  orderStatus: string;
};

type AiMonitorPayload = {
  available: boolean;
  stockCode: string;
  matchedMode: string;
  message: string;
  decision: {
    id: string;
    decisionTime: string;
    action: string;
    confidence: string;
    riskLevel: string;
    positionSizePct: string;
    stopLossPct: string;
    takeProfitPct: string;
    tradingSession: string;
    executed: boolean;
    executionResult: string;
    reasoning: string;
  };
  keyLevels: AiMonitorValueRow[];
  marketData: AiMonitorValueRow[];
  accountData: AiMonitorValueRow[];
  history: AiMonitorHistoryRow[];
  trades: AiMonitorTradeRow[];
};

type ExplainTrack = {
  score?: number | string;
  confidence?: number | string;
  available?: boolean;
  track_unavailable?: boolean;
};

type ExplainDimension = {
  id?: string;
  group?: string;
  score?: number | string;
  available?: boolean;
  reason?: string;
  track_contribution?: number | string;
};

type ExplainGroup = {
  id?: string;
  score?: number | string;
  coverage?: number | string;
  track_contribution?: number | string;
};

type FusionBreakdown = {
  mode?: string;
  fusion_score?: number | string;
  fusion_confidence?: number | string;
  fusion_confidence_base?: number | string;
  buy_threshold_eff?: number | string;
  sell_threshold_eff?: number | string;
  tech_weight_raw?: number | string;
  tech_weight_norm?: number | string;
  context_weight_raw?: number | string;
  context_weight_norm?: number | string;
  divergence_penalty?: number | string;
  sign_conflict?: number | string;
  weighted_threshold_action?: string;
  weighted_action_raw?: string;
  weighted_gate_fail_reasons?: string[];
  tech_enabled?: boolean;
  context_enabled?: boolean;
  core_rule_action?: string;
  final_action?: string;
};

type ExplainabilityPayload = {
  technical_breakdown?: {
    groups?: ExplainGroup[];
    dimensions?: ExplainDimension[];
    track?: ExplainTrack;
  };
  context_breakdown?: {
    groups?: ExplainGroup[];
    dimensions?: ExplainDimension[];
    track?: ExplainTrack;
  };
  fusion_breakdown?: FusionBreakdown;
  vetoes?: Array<Record<string, unknown>>;
  decision_path?: Array<{ step?: string; matched?: string; detail?: string }>;
  resonance?: {
    rule_hit?: string;
    quality_adjusted_position_ratio?: number | string;
    signal_quality_score?: number | string;
    quality_components?: Record<string, unknown>;
    quality_penalties?: Record<string, unknown>;
  };
};

type StrategyProfileSnapshot = {
  explainability?: ExplainabilityPayload;
  kernel_positioning?: {
    quality_position_pct?: number | string;
    rule_hit?: string;
    signal_quality_score?: number | string;
    quality_penalties?: unknown;
  };
  execution_sizing_plan?: {
    buy_tier?: string;
    kernel_quality_position_pct?: number | string;
    buy_tier_cap_pct?: number | string;
    lifecycle_cap_pct?: number | string;
    risk_budget_pct?: number | string;
    expected_stop_loss_pct?: number | string;
    effective_position_pct?: number | string;
    final_budget?: number | string;
    cap_reasons?: string[];
    skip_reason?: string;
  };
  position_sizing?: {
    slot_plan?: {
      slot_count?: number | string;
      slot_budget?: number | string;
    };
    sizing?: {
      slot_units?: number | string;
      base_slot_units?: number | string;
      reentry_size_multiplier?: number | string;
    };
    buy_budget?: number | string;
    quantity?: number | string;
    skip_reason?: string;
  };
  portfolio_execution_guard?: {
    intent?: string;
    status?: string;
    buy_tier?: string;
    buy_tier_label?: string;
    buy_strength_score?: number | string;
    size_multiplier?: number | string;
    cold_start?: {
      active?: boolean;
      sample_count?: number | string;
      profit_sample_threshold?: number | string;
      recent_realized_pnl?: number | string;
    };
    is_late_rebound?: boolean;
    late_rebound_reasons?: string[];
    reasons?: string[];
    portfolio_guard?: {
      status?: string;
      reasons?: string[];
    };
  };
  position_add_gate?: {
    intent?: string;
    status?: string;
    current_position_pct?: number | string;
    target_position_pct?: number | string;
    add_position_delta_pct?: number | string;
    max_position_pct?: number | string;
    reasons?: string[];
  };
};

type SignalDetailPayload = {
  updatedAt: string;
  analysis: string;
  reasoning: string;
  explanation?: {
    summary?: string;
    auditSummary?: string[];
    basis?: string[];
    techEvidence?: string[];
    contextEvidence?: string[];
    thresholdEvidence?: string[];
    contextScoreExplain?: {
      formula?: string;
      confidenceFormula?: string;
      componentBreakdown?: string[];
      componentSum?: number;
      finalScore?: string;
    };
    original?: {
      analysis?: string;
      reasoning?: string;
    };
  };
  decision: {
    id: string;
    source: string;
    stockCode: string;
    stockName: string;
    action: string;
    status: string;
    decisionType: string;
    executionIntent?: string;
    confidence: string;
    positionSizePct: string;
    techScore: string;
    contextScore: string;
    checkpointAt: string;
    createdAt: string;
    analysisTimeframe: string;
    strategyMode: string;
    marketRegime: string;
    fundamentalQuality: string;
    riskStyle: string;
    autoInferredRiskStyle: string;
    techSignal: string;
    contextSignal: string;
    resonanceType: string;
    ruleHit: string;
    finalAction: string;
    finalReason: string;
    positionRatio: string;
    configuredProfile: string;
    appliedProfile: string;
    aiDynamicStrategy: string;
    aiDynamicStrength: string;
    aiDynamicLookback: string;
    aiProfileSwitched: string;
  };
  techVotes: VoteRow[];
  contextVotes: VoteRow[];
  technicalIndicators: IndicatorRow[];
  effectiveThresholds: ThresholdRow[];
  voteOverview?: VoteOverview;
  parameterDetails?: ParameterDetailRow[];
  aiMonitor?: AiMonitorPayload;
  strategyProfile?: StrategyProfileSnapshot;
};

const emptyAiMonitor: AiMonitorPayload = {
  available: false,
  stockCode: "",
  matchedMode: "none",
  message: "",
  decision: {
    id: "",
    decisionTime: "--",
    action: "HOLD",
    confidence: "--",
    riskLevel: "--",
    positionSizePct: "--",
    stopLossPct: "--",
    takeProfitPct: "--",
    tradingSession: "--",
    executed: false,
    executionResult: "--",
    reasoning: "--",
  },
  keyLevels: [],
  marketData: [],
  accountData: [],
  history: [],
  trades: [],
};

const emptyDetail: SignalDetailPayload = {
  updatedAt: "",
  analysis: "",
  reasoning: "",
  explanation: {
    summary: "",
    basis: [],
    techEvidence: [],
    contextEvidence: [],
    thresholdEvidence: [],
    contextScoreExplain: {
      formula: "",
      confidenceFormula: "",
      componentBreakdown: [],
      componentSum: 0,
      finalScore: "0",
    },
    original: { analysis: "", reasoning: "" },
  },
  decision: {
    id: "",
    source: "auto",
    stockCode: "",
    stockName: "",
    action: "HOLD",
    status: "observed",
    decisionType: "auto",
    executionIntent: "",
    confidence: "0",
    positionSizePct: "0",
    techScore: "0",
    contextScore: "0",
    checkpointAt: "--",
    createdAt: "--",
    analysisTimeframe: "--",
    strategyMode: "--",
    marketRegime: "--",
    fundamentalQuality: "--",
    riskStyle: "--",
    autoInferredRiskStyle: "--",
    techSignal: "--",
    contextSignal: "--",
    resonanceType: "--",
    ruleHit: "--",
    finalAction: "HOLD",
    finalReason: "--",
    positionRatio: "0",
    configuredProfile: "--",
    appliedProfile: "--",
    aiDynamicStrategy: "--",
    aiDynamicStrength: "--",
    aiDynamicLookback: "--",
    aiProfileSwitched: t("否"),
  },
  techVotes: [],
  contextVotes: [],
  technicalIndicators: [],
  effectiveThresholds: [],
  voteOverview: {
    voterCount: 0,
    technicalVoterCount: 0,
    contextVoterCount: 0,
    formula: "",
    technicalAggregation: "",
    contextAggregation: "",
    rows: [],
  },
  parameterDetails: [],
  aiMonitor: emptyAiMonitor,
};

function tableRowEmpty(colSpan: number, text: string) {
  return (
    <tr>
      <td className="table__empty" colSpan={colSpan}>
        {text}
      </td>
    </tr>
  );
}

type CompactDataRow = {
  key: string;
  cells: ReactNode[];
};

type GateChecklistRow = {
  key: string;
  label: string;
  current: string;
  threshold: string;
  status: boolean | null;
  note: string;
};

type DriverSummaryRow = {
  key: string;
  track: "technical" | "context";
  label: string;
  groupId?: string;
  contribution: number | null;
  score: number | null;
  coverage: number | null;
  reason: string;
};

type DecisionMetricGroup = {
  key: string;
  label: string;
  note: string;
  rows: ParameterDetailRow[];
};

function CompactDataTable({
  isCompactLayout,
  headers,
  rows,
  coreIndexes,
  emptyText,
}: {
  isCompactLayout: boolean;
  headers: string[];
  rows: CompactDataRow[];
  coreIndexes: number[];
  emptyText: string;
}) {
  const [expandedRows, setExpandedRows] = useState<string[]>([]);
  const validCoreIndexes = coreIndexes.filter(
    (index, position, all) => Number.isInteger(index) && index >= 0 && index < headers.length && all.indexOf(index) === position,
  );
  const finalCoreIndexes = validCoreIndexes.length > 0 ? validCoreIndexes : [0];
  const detailIndexes = headers.map((_, index) => index).filter((index) => !finalCoreIndexes.includes(index));

  if (!isCompactLayout) {
    return (
      <div className="table-shell">
        <table className="table table--auto">
          <thead>
            <tr>
              {headers.map((header) => (
                <th key={header}>{header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? tableRowEmpty(headers.length, emptyText) : rows.map((row) => <tr key={row.key}>{row.cells.map((cell, idx) => <td key={`${row.key}-${idx}`}>{cell}</td>)}</tr>)}
          </tbody>
        </table>
      </div>
    );
  }

  const toggleExpand = (rowKey: string) => {
    setExpandedRows((current) => (current.includes(rowKey) ? current.filter((item) => item !== rowKey) : [...current, rowKey]));
  };

  return (
    <div className="table-shell table-shell--compact">
      <table className="table table--auto">
        <thead>
          <tr>
            {finalCoreIndexes.map((index) => (
              <th key={headers[index]}>{headers[index]}</th>
            ))}
            {detailIndexes.length > 0 ? <th className="table__actions-head">{t("Detail")}</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            tableRowEmpty(finalCoreIndexes.length + (detailIndexes.length > 0 ? 1 : 0), emptyText)
          ) : (
            rows.flatMap((row) => {
              const expanded = expandedRows.includes(row.key);
              const mainRow = (
                <tr key={`${row.key}-main`} className="table__compact-main-row">
                  {finalCoreIndexes.map((index, idx) => (
                    <td key={`${row.key}-core-${index}`} className={idx === 0 ? "table__cell-strong" : undefined}>
                      {row.cells[index]}
                    </td>
                  ))}
                  {detailIndexes.length > 0 ? (
                    <td className="table__compact-control-cell">
                      <button className="button button--secondary button--small table__expand-button" type="button" aria-expanded={expanded} onClick={() => toggleExpand(row.key)}>
                        {expanded ? t("Collapse") : t("Expand")}
                      </button>
                    </td>
                  ) : null}
                </tr>
              );
              if (!expanded || detailIndexes.length === 0) {
                return [mainRow];
              }
              const detailRow = (
                <tr key={`${row.key}-detail`} className="table__compact-detail-row">
                  <td className="table__compact-detail-cell" colSpan={finalCoreIndexes.length + 1}>
                    <div className="compact-detail-grid">
                      {detailIndexes.map((index) => (
                        <div className="compact-detail-item" key={`${row.key}-detail-${index}`}>
                          <div className="compact-detail-item__label">{headers[index]}</div>
                          <div className="compact-detail-item__value">{row.cells[index]}</div>
                        </div>
                      ))}
                    </div>
                  </td>
                </tr>
              );
              return [mainRow, detailRow];
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

function _safeValue(...values: Array<string | undefined | null>): string {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) {
      return text;
    }
  }
  return "--";
}

const REQUIRED_MARKET_TECHNICAL_INDICATORS = [
  t("当前价"),
  t("涨跌幅"),
  t("开盘价"),
  t("最高价"),
  t("最低价"),
  t("成交量(手)"),
  t("成交额(万)"),
  t("换手率"),
  t("量比"),
  t("趋势"),
  "DIF",
  "DEA",
  "RSI6",
  "RSI12",
  "RSI24",
  "KDJ-K",
  "KDJ-D",
  "KDJ-J",
];

function _normalizeIndicatorName(name: string): string {
  const raw = String(name || "").trim();
  if (!raw) {
    return "";
  }
  const text = raw.replace(/\s+/g, "").replace(/（/g, "(").replace(/）/g, ")");
  const lower = text.toLowerCase();
  if (text === t("当前价") || text === t("现价") || text === t("最新价") || text === t("收盘价") || lower === "current_price" || lower === "last_price" || lower === "close") {
    return t("当前价");
  }
  if (text === t("涨跌幅") || text === t("涨跌幅(%)") || lower === "change_pct") {
    return t("涨跌幅");
  }
  if (text === t("开盘价") || lower === "open") {
    return t("开盘价");
  }
  if (text === t("最高价") || lower === "high") {
    return t("最高价");
  }
  if (text === t("最低价") || lower === "low") {
    return t("最低价");
  }
  if (text === t("成交量") || text === t("成交量(手)") || lower === "volume") {
    return t("成交量(手)");
  }
  if (text === t("成交额") || text === t("成交额(万)") || lower === "amount") {
    return t("成交额(万)");
  }
  if (text === t("换手率") || lower === "turnover_rate") {
    return t("换手率");
  }
  if (text === t("量比") || lower === "volume_ratio") {
    return t("量比");
  }
  if (text === t("趋势") || lower === "trend") {
    return t("趋势");
  }
  if (text === "DIF" || lower === "dif" || lower === "macd_dif") {
    return "DIF";
  }
  if (text === "DEA" || lower === "dea" || lower === "macd_dea") {
    return "DEA";
  }
  if (text === "RSI6" || lower === "rsi6") {
    return "RSI6";
  }
  if (text === "RSI12" || lower === "rsi12") {
    return "RSI12";
  }
  if (text === "RSI24" || lower === "rsi24") {
    return "RSI24";
  }
  if (text === t("K值") || text === "KDJ-K" || lower === "kdj_k") {
    return "KDJ-K";
  }
  if (text === t("D值") || text === "KDJ-D" || lower === "kdj_d") {
    return "KDJ-D";
  }
  if (text === t("J值") || text === "KDJ-J" || lower === "kdj_j") {
    return "KDJ-J";
  }
  return text;
}

const ENV_COMPONENT_KEY_MAP: Record<string, string> = {
  source_prior: "Env component:source_prior",
  trend_regime: "Env component:trend_regime",
  price_structure: "Env component:price_structure",
  momentum: "Env component:momentum",
  risk_balance: "Env component:risk_balance",
  liquidity: "Env component:liquidity",
  session: "Env component:session",
  execution_feedback: t("执行反馈"),
  account_posture: t("账户态势"),
};

const THRESHOLD_KEY_MAP: Record<string, string> = {
  buy_threshold: "Threshold:buy_threshold",
  sell_threshold: "Threshold:sell_threshold",
  max_position_ratio: "Threshold:max_position_ratio",
  allow_pyramiding: "Threshold:allow_pyramiding",
  confirmation: "Threshold:confirmation",
  min_fusion_confidence: t("BUY最小融合置信度"),
  min_tech_score_for_buy: t("BUY技术轨最小分值"),
  min_context_score_for_buy: t("BUY环境轨最小分值"),
  min_tech_confidence_for_buy: t("BUY技术轨最小置信度"),
  min_context_confidence_for_buy: t("BUY环境轨最小置信度"),
  add_min_unrealized_pnl_pct: t("加仓最小浮盈(%)"),
  add_min_tech_score: t("加仓最小技术分"),
  add_min_fusion_confidence: t("加仓最小融合置信度"),
};

function _localizeEnvComponentName(name: string): string {
  const normalized = String(name || "").trim().toLowerCase();
  const key = ENV_COMPONENT_KEY_MAP[normalized];
  if (!key) {
    return name;
  }
  if (key.includes(":")) {
    return t(key);
  }
  return key;
}

function _localizeThresholdName(rawName: string): string {
  const text = String(rawName || "").trim();
  if (!text) {
    return text;
  }
  const pureKey = text.startsWith(t("阈值.")) ? text.slice(3) : text;
  const mapped = THRESHOLD_KEY_MAP[pureKey];
  const localized = mapped ? (mapped.includes(":") ? t(mapped) : mapped) : pureKey;
  return text.startsWith(t("阈值.")) ? `${t("Threshold prefix")}${localized}` : localized;
}

function _localizeComponentBreakdownLine(line: string): string {
  const text = String(line || "").trim();
  const match = /^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([+\-]?\d+(?:\.\d+)?)$/.exec(text);
  if (!match) {
    return _localizeDynamicText(text);
  }
  return `${_localizeEnvComponentName(match[1])}=${match[2]}`;
}

function _localizeTrackBias(rawValue: string): string {
  const value = String(rawValue || "").trim().toUpperCase();
  if (value === "BUY") {
    return t("偏多");
  }
  if (value === "SELL") {
    return t("偏空");
  }
  if (value === "HOLD") {
    return t("中性");
  }
  return _localizeDynamicText(rawValue || "--");
}

const STATUS_KEY_MAP: Record<string, string> = {
  pending: "Status:pending",
  observed: "Status:observed",
  delivered: "Status:delivered",
  executed: "Status:executed",
  failed: "Status:failed",
  cancelled: "Status:cancelled",
  canceled: "Status:canceled",
  skipped: "Status:skipped",
};

const SOURCE_LABEL_MAP: Record<string, string> = {
  tech_vote: "Source:tech_vote",
  tech_vote_reason: "Source:tech_vote_reason",
  reasoning: "Source:reasoning",
};

const TOKEN_KEY_MAP: Record<string, string> = {
  main_force: "Token:main_force",
  sideways: "Token:sideways",
  ContextScore: "Token:ContextScore",
  label: "Token:label",
  reason: "Token:reason",
  score: "Token:score",
  weight: "Token:weight",
  clamp: "Token:clamp",
  abs: "Token:abs",
  base_confidence: "Token:base_confidence",
  tech_score: "Token:tech_score",
  context_score: "Token:context_score",
  effective_thresholds: "Token:effective_thresholds",
  NA: "Token:NA",
  True: "Bool:true",
  False: "Bool:false",
  true: "Bool:true",
  false: "Bool:false",
};

function _escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function _replaceWholeWord(source: string, from: string, to: string): string {
  if (!from || !to) {
    return source;
  }
  return source.replace(new RegExp(`\\b${_escapeRegex(from)}\\b`, "g"), to);
}

function _localizeStatus(rawStatus: string): string {
  const value = String(rawStatus || "").trim();
  if (!value) {
    return "--";
  }
  const key = STATUS_KEY_MAP[value.toLowerCase()];
  return key ? t(key) : value;
}

function _localizeSourceLabel(rawSource: string): string {
  const source = String(rawSource || "").trim();
  if (!source) {
    return "--";
  }
  const direct = SOURCE_LABEL_MAP[source];
  if (direct) {
    return t(direct);
  }
  if (source.includes("DualTrackResolver")) {
    return t("Source:DualTrackResolver");
  }
  if (source.includes("KernelStrategyRuntime")) {
    return t("Source:KernelStrategyRuntime");
  }
  if (source.includes("MarketRegimeContextProvider")) {
    return t("Source:MarketRegimeContextProvider");
  }
  if (source.includes("scheduler") || source.includes("sim_runs") || source.includes(t("调度配置/回放任务"))) {
    return t("Source:SchedulerReplay");
  }
  return _localizeDynamicText(source);
}

function _localizeValue(rawValue: string): string {
  const value = String(rawValue || "").trim();
  if (!value) {
    return "--";
  }
  if (value === "CN") {
    return t("Market:CN");
  }
  const boolKey = TOKEN_KEY_MAP[value];
  if (boolKey) {
    return t(boolKey);
  }
  return _localizeDynamicText(value);
}

function _localizeDynamicText(rawText: string): string {
  let text = String(rawText || "");
  if (!text) {
    return text;
  }

  text = text.replace(/\b(dual_track_[a-z_]+|sell_divergence|buy_divergence|resonance_[a-z_]+|neutral_hold|full|heavy|moderate|light)\b/gi, (matched) =>
    localizeDecisionCode(matched),
  );
  text = text.replace(/\b(BUY|SELL|HOLD|CONTEXT)\b/g, (matched) => localizeDecisionCode(matched));
  text = text.replace(/\b(pending|observed|delivered|executed|failed|cancelled|canceled|skipped)\b/gi, (matched) => _localizeStatus(matched));
  text = text.replace(/\b(source_prior|trend_regime|price_structure|momentum|risk_balance|liquidity|session)\b/g, (matched) => _localizeEnvComponentName(matched));
  text = text.replace(/\b(buy_threshold|sell_threshold|max_position_ratio|allow_pyramiding|confirmation)\b/g, (matched) => _localizeThresholdName(matched));

  for (const [token, key] of Object.entries(TOKEN_KEY_MAP)) {
    text = _replaceWholeWord(text, token, t(key));
  }

  return text;
}

function _parseNumeric(raw: string): number | null {
  const text = String(raw || "").replace(/,/g, "").trim();
  if (!text) {
    return null;
  }
  const match = text.match(/[+\-]?\d+(\.\d+)?/);
  if (!match) {
    return null;
  }
  const value = Number(match[0]);
  return Number.isFinite(value) ? value : null;
}

function _formatSigned(value: number | null, digits = 4): string {
  if (value === null || !Number.isFinite(value)) {
    return "--";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function _parseNumberish(raw: unknown): number | null {
  if (raw === null || raw === undefined) {
    return null;
  }
  if (typeof raw === "number") {
    return Number.isFinite(raw) ? raw : null;
  }
  return _parseNumeric(String(raw));
}

function _formatPlainNumber(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) {
    return "--";
  }
  return value.toFixed(digits);
}

function _formatPercentNumber(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) {
    return "--";
  }
  return `${value.toFixed(digits)}%`;
}

function _formatCurrencyNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function _formatShareQuantity(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value <= 0) {
    return "--";
  }
  return t("{v0}股", { v0: Math.round(value) });
}

function _formatMultiplier(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "--";
  }
  return `${value.toFixed(2)}x`;
}

function _gateStatusLabel(status: boolean | null): string {
  if (status === true) {
    return t("通过");
  }
  if (status === false) {
    return t("未通过");
  }
  return t("未提供");
}

function _gateStatusClass(status: boolean | null): string {
  if (status === true) {
    return "signal-detail-chip signal-detail-chip--pass";
  }
  if (status === false) {
    return "signal-detail-chip signal-detail-chip--fail";
  }
  return "signal-detail-chip signal-detail-chip--neutral";
}

function _actionChipClass(action: string): string {
  const normalized = String(action || "").trim().toUpperCase();
  if (normalized === "BUY") {
    return "signal-detail-chip signal-detail-chip--action-buy";
  }
  if (normalized === "SELL") {
    return "signal-detail-chip signal-detail-chip--action-sell";
  }
  return "signal-detail-chip signal-detail-chip--action-hold";
}

function _isPositionAddIntent(intent?: string): boolean {
  return String(intent || "").trim().toLowerCase() === "position_add";
}

function _displayActionLabel(action: string, executionIntent?: string): string {
  if (String(action || "").trim().toUpperCase() === "BUY" && _isPositionAddIntent(executionIntent)) {
    return t("增持");
  }
  return localizeDecisionCode(action);
}

function _gateStatusTone(status: boolean | null): "pass" | "fail" | "neutral" {
  if (status === true) {
    return "pass";
  }
  if (status === false) {
    return "fail";
  }
  return "neutral";
}

function _trackLabel(track: string): string {
  return track === "context" ? t("环境") : t("技术");
}

function _formatContributionLabel(track: "technical" | "context", rawLabel: string): string {
  return track === "context" ? _localizeEnvComponentName(rawLabel) : _localizeDynamicText(rawLabel);
}

const TRACK_GROUP_LABEL_MAP: Record<string, string> = {
  trend: t("趋势组"),
  momentum: t("动量组"),
  volume_confirmation: t("量能确认组"),
  volatility_risk: t("波动风险组"),
  market_structure: t("市场结构组"),
  risk_account: t("风险账户组"),
  tradability_timing: t("流动时段组"),
  source_execution: t("来源执行组"),
};

function _formatGroupLabel(track: "technical" | "context", rawLabel: string): string {
  const normalized = String(rawLabel || "").trim().toLowerCase();
  const mapped = TRACK_GROUP_LABEL_MAP[normalized];
  if (mapped) {
    return mapped;
  }
  return _formatContributionLabel(track, rawLabel);
}

const GATE_REASON_LABEL_MAP: Record<string, string> = {
  fusion_confidence_below_min: t("融合置信度低于最小门限"),
  tech_score_below_min_for_buy: t("技术轨 BUY 门未过"),
  context_score_below_min_for_buy: t("环境轨 BUY 门未过"),
  tech_confidence_below_min_for_buy: t("技术轨置信度门未过"),
  context_confidence_below_min_for_buy: t("环境轨置信度门未过"),
};

function _humanizeGateReason(reason: string): string {
  const normalized = String(reason || "").trim();
  if (!normalized) {
    return "--";
  }
  return GATE_REASON_LABEL_MAP[normalized] ?? _localizeDynamicText(normalized);
}

function _classifyDecisionMetric(item: ParameterDetailRow): { key: string; label: string; note: string } {
  const name = String(item.name || "").trim();
  const source = String(item.source || "").trim().toLowerCase();
  const normalized = name.toLowerCase();

  if (normalized.includes(t("兼容")) || normalized.includes(t("派生")) || normalized.includes("legacy")) {
    return { key: "legacy", label: t("兼容派生字段"), note: t("兼容旧语义或派生说明，仅作辅助阅读。") };
  }
  if (
    normalized.startsWith(t("ai动态调整."))
    || normalized.includes(t("ai动态档位"))
    || normalized.includes(t("ai动态评分"))
    || source.includes("dynamic_strategy.adjustments")
  ) {
    return { key: "dynamic", label: t("AI动态调参"), note: t("记录 AI 动态层在白名单内实际调整过的参数和值。") };
  }
  if (source.includes("technical_breakdown") || normalized.includes(t("技术轨"))) {
    return { key: "technical", label: t("技术轨"), note: t("来自技术轨结构化 breakdown 的方向、分值或置信度。") };
  }
  if (source.includes("context_breakdown") || normalized.includes(t("环境轨"))) {
    return { key: "context", label: t("环境轨"), note: t("来自环境轨结构化 breakdown 的方向、分值或置信度。") };
  }
  if (
    source.includes("fusion_breakdown")
    || source.includes("decision_path")
    || source.includes("veto")
    || normalized.includes(t("融合"))
    || normalized.includes(t("核心规则"))
    || normalized.includes(t("最终动作"))
    || normalized.includes(t("加权"))
  ) {
    return { key: "fusion", label: t("融合决策层"), note: t("描述规则层、加权层和最终动作如何汇合。") };
  }
  return { key: "runtime", label: t("策略与运行态"), note: t("描述动态策略模式、模板绑定和运行上下文。") };
}

function CollapsibleSection({
  title,
  summary,
  expandLabel,
  collapseLabel,
  children,
}: {
  title: string;
  summary?: ReactNode;
  expandLabel: string;
  collapseLabel: string;
  children: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="signal-detail-collapsible">
      <div className="signal-detail-collapsible__header">
        <div className="signal-detail-collapsible__intro">
          <div className="signal-detail-collapsible__eyebrow">{t("按需展开")}</div>
          <div className="signal-detail-collapsible__title-row">
            <h2 className="section-card__title" style={{ marginBottom: 0 }}>
              {title}
            </h2>
            <span className={`signal-detail-chip ${expanded ? "signal-detail-chip--neutral" : "signal-detail-chip--pass"}`}>
              {expanded ? t("已展开") : t("默认折叠")}
            </span>
          </div>
          {summary ? <div className="signal-detail-collapsible__summary">{summary}</div> : null}
        </div>
        <button
          className="button button--secondary button--small signal-detail-collapsible__trigger"
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? collapseLabel : expandLabel}
        </button>
      </div>
      {expanded ? <div className="signal-detail-collapsible__body">{children}</div> : null}
    </section>
  );
}

export function SignalDetailPage() {
  const isCompactLayout = useCompactLayout();
  const navigate = useNavigate();
  const { signalId } = useParams();
  const [searchParams] = useSearchParams();
  const source = useMemo(() => (searchParams.get("source") || "auto").toLowerCase(), [searchParams]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<SignalDetailPayload>(emptyDetail);
  const [marketRefreshSeq, setMarketRefreshSeq] = useState(0);
  const [marketRefreshPending, setMarketRefreshPending] = useState(false);
  const [voteTrackFilter, setVoteTrackFilter] = useState<"all" | "technical" | "context">("all");
  const [voteContributionFilter, setVoteContributionFilter] = useState<"all" | "positive" | "negative" | "actionable">("all");

  useEffect(() => {
    const id = String(signalId || "").trim();
    if (!id) {
      setStatus("error");
      setError(t("缺少 signal id"));
      return;
    }
    let mounted = true;
    async function load() {
      setStatus("loading");
      setError(null);
      const forceRefreshMarket = marketRefreshSeq > 0;
      try {
        const response = await fetch(
          `/api/v1/quant/signals/${encodeURIComponent(id)}?source=${encodeURIComponent(source)}${
            forceRefreshMarket ? "&refresh_market=1" : ""
          }`,
          {
            headers: { Accept: "application/json" },
          },
        );
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `Request failed: ${response.status}`);
        }
        const payload = (await response.json()) as SignalDetailPayload;
        if (mounted) {
          setDetail(payload);
          setStatus("ready");
          if (forceRefreshMarket) {
            setMarketRefreshPending(false);
          }
        }
      } catch (err) {
        if (mounted) {
          setStatus("error");
          setError(err instanceof Error ? err.message : String(err));
          if (forceRefreshMarket) {
            setMarketRefreshPending(false);
          }
        }
      }
    }
    void load();
    return () => {
      mounted = false;
    };
  }, [signalId, source, marketRefreshSeq]);

  if (status === "loading") {
    return <PageLoadingState title={t("信号详情加载中")} description={t("正在读取投票明细、决策依据和技术指标快照。")} />;
  }

  if (status === "error") {
    return (
      <PageErrorState
        title={t("信号详情加载失败")}
        description={error ?? t("无法加载信号详情，请稍后重试。")}
        actionLabel={t("返回")}
        onAction={() => navigate(-1)}
      />
    );
  }

  if (!detail?.decision?.id) {
    return <PageEmptyState title={t("信号详情为空")} description={t("当前信号没有可展示内容。")} actionLabel={t("返回")} onAction={() => navigate(-1)} />;
  }

  const decision = detail.decision;
  const explanation = detail.explanation ?? {};
  const techEvidence = explanation.techEvidence ?? [];
  const contextEvidence = explanation.contextEvidence ?? [];
  const contextScoreExplain = explanation.contextScoreExplain ?? {
    formula: "",
    confidenceFormula: "",
    componentBreakdown: [],
    componentSum: 0,
    finalScore: decision.contextScore,
  };
  const parameterDetails = detail.parameterDetails ?? [];
  const technicalRows = detail.technicalIndicators;
  const environmentRows = detail.contextVotes;
  const technicalParameterRows: ParameterDetailRow[] = [];
  const environmentParameterRows: ParameterDetailRow[] = [];
  const decisionParameterRows: ParameterDetailRow[] = [];
  const thresholdRows: ParameterDetailRow[] = [];
  for (const item of parameterDetails) {
    const name = String(item.name || "");
    if (name.startsWith(t("指标."))) {
      technicalParameterRows.push(item);
      continue;
    }
    if (name.startsWith(t("阈值."))) {
      thresholdRows.push(item);
      continue;
    }
    if (name.includes(t("环境")) || name.includes(t("市场"))) {
      environmentParameterRows.push(item);
      continue;
    }
    decisionParameterRows.push(item);
  }
  const dedupeParameterRows = (rows: ParameterDetailRow[]) => {
    const seen = new Set<string>();
    return rows.filter((item) => {
      const key = `${String(item.name || "").trim().toLowerCase()}::${String(item.value || "").trim()}::${String(item.source || "").trim().toLowerCase()}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  };
  const dedupedDecisionParameterRows = dedupeParameterRows(decisionParameterRows);
  const dedupedThresholdRows = dedupeParameterRows(thresholdRows);
  const dedupedEnvironmentParameterRows = dedupeParameterRows(environmentParameterRows);
  const normalizeThresholdKey = (name: string) => String(name || "").replace(/^阈值\./, "").trim().toLowerCase();
  const executionThresholdKeys = new Set([
    "buy_threshold",
    "sell_threshold",
    "max_position_ratio",
    "allow_pyramiding",
    "confirmation",
    "add_min_unrealized_pnl_pct",
    "add_min_tech_score",
    "add_min_fusion_confidence",
  ]);
  const buyGateThresholdKeys = new Set([
    "min_fusion_confidence",
    "min_tech_score_for_buy",
    "min_context_score_for_buy",
    "min_tech_confidence_for_buy",
    "min_context_confidence_for_buy",
  ]);
  const executionThresholdRows = dedupedThresholdRows.filter((item) => executionThresholdKeys.has(normalizeThresholdKey(item.name)));
  const buyGateThresholdRows = dedupedThresholdRows.filter((item) => buyGateThresholdKeys.has(normalizeThresholdKey(item.name)));
  const decisionMetricGroups: DecisionMetricGroup[] = (() => {
    const groupMap = new Map<string, DecisionMetricGroup>();
    for (const row of dedupedDecisionParameterRows) {
      const category = _classifyDecisionMetric(row);
      const existing = groupMap.get(category.key);
      if (existing) {
        existing.rows.push(row);
        continue;
      }
      groupMap.set(category.key, { ...category, rows: [row] });
    }
    const orderedKeys = ["fusion", "technical", "context", "dynamic", "runtime", "legacy"];
    return orderedKeys
      .map((key) => groupMap.get(key))
      .filter((item): item is DecisionMetricGroup => Boolean(item && item.rows.length > 0));
  })();
  const originalAnalysis = explanation.original?.analysis || detail.analysis || t("暂无分析数据");
  const originalReasoning = explanation.original?.reasoning || detail.reasoning || t("暂无决策理由");
  const aiMonitor = detail.aiMonitor ?? emptyAiMonitor;
  const marketIndicatorByName = new Map<string, AiMonitorValueRow>();
  for (const item of aiMonitor.marketData ?? []) {
    const key = _normalizeIndicatorName(item.label);
    if (!key || marketIndicatorByName.has(key)) {
      continue;
    }
    marketIndicatorByName.set(key, item);
  }
  const technicalParamByName = new Map<string, ParameterDetailRow>();
  const consumedTechnicalParamNames = new Set<string>();
  for (const item of technicalParameterRows) {
    const key = String(item.name || "").replace(/^指标\./, "");
    if (!key) {
      continue;
    }
    if (!technicalParamByName.has(key)) {
      technicalParamByName.set(key, item);
    }
  }
  const mergedTechnicalRows = technicalRows.map((item) => {
    const key = String(item.name || "");
    const matchedParam = technicalParamByName.get(key);
    if (matchedParam) {
      consumedTechnicalParamNames.add(key);
    }
    return {
      name: key || "--",
      value: _safeValue(item.value, matchedParam?.value),
      source: _safeValue(matchedParam?.source, item.source),
      detail: _safeValue(matchedParam?.derivation, item.note),
    };
  });
  for (const item of technicalParameterRows) {
    const key = String(item.name || "").replace(/^指标\./, "");
    if (!key || consumedTechnicalParamNames.has(key)) {
      continue;
    }
    mergedTechnicalRows.push({
      name: key,
      value: _safeValue(item.value),
      source: _safeValue(item.source),
      detail: _safeValue(item.derivation),
    });
  }
  const mergedTechnicalNormalizedNames = new Set(mergedTechnicalRows.map((item) => _normalizeIndicatorName(item.name)));
  for (const indicatorName of REQUIRED_MARKET_TECHNICAL_INDICATORS) {
    const normalizedName = _normalizeIndicatorName(indicatorName);
    if (mergedTechnicalNormalizedNames.has(normalizedName)) {
      continue;
    }
    const marketItem = marketIndicatorByName.get(normalizedName);
    mergedTechnicalRows.push({
      name: indicatorName,
      value: _safeValue(marketItem?.value),
      source: _safeValue(marketItem ? t("行情快照") : ""),
      detail: _safeValue(marketItem?.note),
    });
    mergedTechnicalNormalizedNames.add(normalizedName);
  }
  const voteOverview = detail.voteOverview ?? {
    voterCount: 0,
    technicalVoterCount: 0,
    contextVoterCount: 0,
    formula: "",
    technicalAggregation: "",
    contextAggregation: "",
    rows: [],
  };
  const voteRows = voteOverview.rows ?? [];
  const technicalVoteRows = voteRows.filter((item) => item.track === "technical");
  const contextVoteRows = voteRows.filter((item) => item.track === "context");
  const totalTechnicalVotes = technicalVoteRows.length;
  const totalContextVotes = contextVoteRows.length;
  const technicalWeightSum = technicalVoteRows.reduce((sum, item) => sum + (_parseNumeric(item.weight) ?? 1), 0);
  const contextWeightSum = contextVoteRows.reduce((sum, item) => sum + (_parseNumeric(item.weight) ?? 1), 0);
  const technicalContribution = technicalVoteRows.reduce((sum, item) => sum + (_parseNumeric(item.contribution) ?? 0), 0);
  const contextContribution = contextVoteRows.reduce((sum, item) => sum + (_parseNumeric(item.contribution) ?? 0), 0);
  const contextComponentSum = _parseNumeric(String(contextScoreExplain.componentSum ?? ""));
  const contextFinalScore = _parseNumeric(String(contextScoreExplain.finalScore ?? decision.contextScore));
  const signalCount = technicalVoteRows.reduce(
    (acc, item) => {
      const signal = String(item.signal || "").toUpperCase();
      if (signal === "BUY") acc.buy += 1;
      else if (signal === "SELL") acc.sell += 1;
      else acc.hold += 1;
      return acc;
    },
    { buy: 0, sell: 0, hold: 0 },
  );
  const topContextDrivers = [...contextVoteRows]
    .map((item) => ({
      factor: item.voter,
      contribution: _parseNumeric(item.contribution) ?? _parseNumeric(item.score) ?? 0,
      reason: item.reason,
    }))
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .slice(0, 3);
  const findThreshold = (name: string) =>
    thresholdRows.find((item) => String(item.name || "").replace(/^阈值\./, "").trim().toLowerCase() === name.toLowerCase())?.value ?? "--";
  const buyThreshold = findThreshold("buy_threshold");
  const sellThreshold = findThreshold("sell_threshold");
  const maxPositionRatio = findThreshold("max_position_ratio");
  const allowPyramiding = findThreshold("allow_pyramiding");
  const confirmation = findThreshold("confirmation");
  const marketValue =
    decisionParameterRows.find((item) => String(item.name || "").trim() === t("市场"))?.value
    || (decision as unknown as { market?: string }).market
    || "--";
  const basisList = explanation.basis ?? [];
  const auditSummaryList = explanation.auditSummary ?? [];
  const voteActorLines = voteRows.map((item) => {
    const trackLabel = item.track === "context" ? t("环境") : t("技术");
    const voterLabel = item.track === "context" ? _localizeEnvComponentName(item.voter) : _localizeDynamicText(item.voter);
    return t("{v0}｜{v1}：投票 {v2}，权重 {v3}，贡献 {v4}，依据 {v5}", { v0: trackLabel, v1: voterLabel, v2: localizeDecisionCode(item.signal), v3: item.weight, v4: item.contribution, v5: _localizeDynamicText(item.reason || "--") });
  });
  const positionMetricLabel =
    String(decision.action || "").toUpperCase() === "BUY"
      ? _isPositionAddIntent(decision.executionIntent) ? t("建议加仓比例(%)") : t("目标买入仓位(%)")
      : String(decision.action || "").toUpperCase() === "SELL"
      ? t("建议卖出比例(%)")
      : t("仓位建议");
  const positionMetricValue = String(decision.action || "").toUpperCase() === "HOLD" ? t("不变") : decision.positionSizePct;
  const strategyExplainability = detail.strategyProfile?.explainability ?? {};
  const kernelPositioning = detail.strategyProfile?.kernel_positioning;
  const resonancePositioning = strategyExplainability.resonance;
  const executionSizingPlan = detail.strategyProfile?.execution_sizing_plan;
  const positionAddGate = detail.strategyProfile?.position_add_gate;
  const positionSizing = detail.strategyProfile?.position_sizing;
  const portfolioExecutionGuard = detail.strategyProfile?.portfolio_execution_guard;
  const technicalBreakdown = strategyExplainability.technical_breakdown ?? {};
  const contextBreakdown = strategyExplainability.context_breakdown ?? {};
  const fusionBreakdown = strategyExplainability.fusion_breakdown ?? {};
  const vetoes = Array.isArray(strategyExplainability.vetoes) ? strategyExplainability.vetoes : [];
  const weightedGateFailReasons = Array.isArray(fusionBreakdown.weighted_gate_fail_reasons)
    ? fusionBreakdown.weighted_gate_fail_reasons
    : [];
  const buyThresholdValue = _parseNumberish(fusionBreakdown.buy_threshold_eff ?? buyThreshold);
  const sellThresholdValue = _parseNumberish(fusionBreakdown.sell_threshold_eff ?? sellThreshold);
  const minFusionConfidenceValue = _parseNumberish(findThreshold("min_fusion_confidence"));
  const fusionScoreValue = _parseNumberish(fusionBreakdown.fusion_score ?? findThreshold("fusion_score"));
  const fusionConfidenceValue = _parseNumberish(fusionBreakdown.fusion_confidence ?? decision.confidence);
  const coreRuleAction = String(fusionBreakdown.core_rule_action ?? decision.ruleHit ?? "--");
  const weightedThresholdAction = String(fusionBreakdown.weighted_threshold_action ?? "--");
  const weightedGateAction = String(fusionBreakdown.weighted_action_raw ?? "--");
  const finalActionForChain = String(fusionBreakdown.final_action ?? decision.finalAction ?? decision.action ?? "--");
  const techTrackScoreValue = _parseNumberish(technicalBreakdown.track?.score ?? decision.techScore);
  const contextTrackScoreValue = _parseNumberish(contextBreakdown.track?.score ?? decision.contextScore);
  const techTrackEnabled = fusionBreakdown.tech_enabled !== false;
  const contextTrackEnabled = fusionBreakdown.context_enabled !== false;
  const technicalGroupRows: DriverSummaryRow[] = (Array.isArray(technicalBreakdown.groups) ? technicalBreakdown.groups : [])
    .map((item, index) => ({
      key: `tech-group-${index}`,
      track: "technical" as const,
      label: _formatGroupLabel("technical", String(item.id || "--")),
      groupId: String(item.id || "--"),
      contribution: _parseNumberish(item.track_contribution),
      score: _parseNumberish(item.score),
      coverage: _parseNumberish(item.coverage),
      reason: "",
    }))
    .sort((left, right) => Math.abs(right.contribution ?? 0) - Math.abs(left.contribution ?? 0));
  const contextGroupRows: DriverSummaryRow[] = (Array.isArray(contextBreakdown.groups) ? contextBreakdown.groups : [])
    .map((item, index) => ({
      key: `context-group-${index}`,
      track: "context" as const,
      label: _formatGroupLabel("context", String(item.id || "--")),
      groupId: String(item.id || "--"),
      contribution: _parseNumberish(item.track_contribution),
      score: _parseNumberish(item.score),
      coverage: _parseNumberish(item.coverage),
      reason: "",
    }))
    .sort((left, right) => Math.abs(right.contribution ?? 0) - Math.abs(left.contribution ?? 0));
  const dimensionRows: DriverSummaryRow[] = [
    ...(Array.isArray(technicalBreakdown.dimensions) ? technicalBreakdown.dimensions : []).map((item, index) => ({
      key: `tech-dim-${index}`,
      track: "technical" as const,
      label: _formatContributionLabel("technical", String(item.id || "--")),
      groupId: String(item.group || "--"),
      contribution: _parseNumberish(item.track_contribution),
      score: _parseNumberish(item.score),
      coverage: null,
      reason: _localizeDynamicText(String(item.reason || "--")),
    })),
    ...(Array.isArray(contextBreakdown.dimensions) ? contextBreakdown.dimensions : []).map((item, index) => ({
      key: `context-dim-${index}`,
      track: "context" as const,
      label: _formatContributionLabel("context", String(item.id || "--")),
      groupId: String(item.group || "--"),
      contribution: _parseNumberish(item.track_contribution),
      score: _parseNumberish(item.score),
      coverage: null,
      reason: _localizeDynamicText(String(item.reason || "--")),
    })),
  ].filter((item) => item.contribution !== null);
  const technicalDimensionRows = dimensionRows.filter((item) => item.track === "technical");
  const contextDimensionRows = dimensionRows.filter((item) => item.track === "context");
  const groupDominantLine = (rows: DriverSummaryRow[], groupId: string) => {
    const candidates = rows
      .filter((item) => item.groupId === groupId)
      .sort((left, right) =>
        Math.abs(right.contribution ?? 0) - Math.abs(left.contribution ?? 0),
      );
    const driver = candidates[0];
    if (!driver) {
      return t("暂无关键因子。");
    }
    return t("关键因子：{v0} {v1}", { v0: driver.label, v1: _formatSigned(driver.contribution) });
  };
  const techGateReasons = weightedGateFailReasons.filter((item) => item.startsWith("tech_"));
  const contextGateReasons = weightedGateFailReasons.filter((item) => item.startsWith("context_"));
  const fusionConfidenceGateReasons = weightedGateFailReasons.filter((item) => item.includes("fusion_confidence"));
  const portfolioGuardScore = _parseNumberish(portfolioExecutionGuard?.buy_strength_score);
  const portfolioGuardMultiplier = _parseNumberish(portfolioExecutionGuard?.size_multiplier);
  const kernelSuggestedPct =
    _parseNumberish(kernelPositioning?.quality_position_pct)
    ?? _parseNumberish(executionSizingPlan?.kernel_quality_position_pct)
    ?? (() => {
      const ratio = _parseNumberish(resonancePositioning?.quality_adjusted_position_ratio);
      return ratio === null ? null : ratio * 100;
    })();
  const executionEffectivePct = _parseNumberish(executionSizingPlan?.effective_position_pct);
  const executionFinalBudget = _parseNumberish(executionSizingPlan?.final_budget);
  const executionRiskBudgetPct = _parseNumberish(executionSizingPlan?.risk_budget_pct);
  const coldStartState = portfolioExecutionGuard?.cold_start;
  const coldStartActive = Boolean(coldStartState?.active);
  const coldStartSampleCount = _parseNumberish(coldStartState?.sample_count);
  const coldStartSampleThreshold = _parseNumberish(coldStartState?.profit_sample_threshold);
  const positionSizingQuantity = _parseNumberish(positionSizing?.quantity);
  const positionSizingBuyBudget = _parseNumberish(positionSizing?.buy_budget);
  const positionSizingSlotUnits = _parseNumberish(positionSizing?.sizing?.slot_units);
  const positionSizingMultiplier =
    _parseNumberish(positionSizing?.sizing?.reentry_size_multiplier)
    ?? portfolioGuardMultiplier;
  const positionSizingSkipReason = String(positionSizing?.skip_reason || "").trim();
  const portfolioGuardReasons = [
    ...(Array.isArray(portfolioExecutionGuard?.reasons) ? portfolioExecutionGuard.reasons : []),
    ...(Array.isArray(portfolioExecutionGuard?.portfolio_guard?.reasons) ? portfolioExecutionGuard.portfolio_guard.reasons : []),
    ...(Array.isArray(portfolioExecutionGuard?.late_rebound_reasons) ? portfolioExecutionGuard.late_rebound_reasons : []),
  ];
  const gateRows: GateChecklistRow[] = [
    {
      key: "veto",
      label: t("Veto 否决"),
      current: vetoes.length > 0 ? _localizeDynamicText(String(vetoes[0]?.action || "--")) : t("未命中"),
      threshold: t("不命中"),
      status: vetoes.length === 0,
      note:
        vetoes.length === 0
          ? t("未命中 veto，继续进入规则与加权门控链路。")
          : vetoes
              .map((item) => `${String(item.id || "--")} · ${_localizeDynamicText(String(item.reason || "--"))}`)
              .join("；"),
    },
    {
      key: "buy-threshold",
      label: t("买入阈值门"),
      current: fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4),
      threshold: buyThresholdValue === null ? "--" : buyThresholdValue.toFixed(4),
      status:
        fusionScoreValue !== null && buyThresholdValue !== null ? fusionScoreValue >= buyThresholdValue : null,
      note: t("fusion_score >= buy_threshold 才能形成 BUY。")
    },
    {
      key: "sell-threshold",
      label: t("卖出阈值门"),
      current: fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4),
      threshold: sellThresholdValue === null ? "--" : sellThresholdValue.toFixed(4),
      status:
        fusionScoreValue !== null && sellThresholdValue !== null ? fusionScoreValue <= sellThresholdValue : null,
      note: t("fusion_score <= sell_threshold 才能形成 SELL。")
    },
    {
      key: "fusion-confidence",
      label: t("融合置信度门"),
      current: fusionConfidenceValue === null ? "--" : fusionConfidenceValue.toFixed(4),
      threshold: minFusionConfidenceValue === null ? "--" : minFusionConfidenceValue.toFixed(4),
      status: fusionConfidenceGateReasons.length > 0
        ? false
        : fusionConfidenceValue !== null && minFusionConfidenceValue !== null
        ? fusionConfidenceValue >= minFusionConfidenceValue
        : null,
      note:
        fusionConfidenceGateReasons.length > 0
          ? fusionConfidenceGateReasons.map(_humanizeGateReason).join("；")
          : minFusionConfidenceValue === null
          ? t("当前快照未提供最小融合置信度阈值。")
          : t("BUY 需要先通过融合置信度门。")
    },
    {
      key: "tech-buy-gate",
      label: t("技术轨 BUY 条件"),
      current: techTrackScoreValue === null ? _localizeDynamicText(decision.techSignal) : _formatSigned(techTrackScoreValue),
      threshold: techTrackEnabled ? "> 0" : t("关闭"),
      status:
        !techTrackEnabled
          ? null
          : techGateReasons.length > 0
          ? false
          : techTrackScoreValue !== null
          ? techTrackScoreValue > 0
          : String(decision.techSignal || "").toUpperCase() === "BUY",
      note:
        !techTrackEnabled
          ? t("技术轨 BUY 门已关闭。")
          : techGateReasons.length > 0
          ? techGateReasons.map(_humanizeGateReason).join("；")
          : t("当前技术轨方向 {v0}。", { v0: _localizeTrackBias(decision.techSignal) })
    },
    {
      key: "context-buy-gate",
      label: t("环境轨 BUY 条件"),
      current: contextTrackScoreValue === null ? _localizeDynamicText(decision.contextSignal) : _formatSigned(contextTrackScoreValue),
      threshold: contextTrackEnabled ? "> 0" : t("关闭"),
      status:
        !contextTrackEnabled
          ? null
          : contextGateReasons.length > 0
          ? false
          : contextTrackScoreValue !== null
          ? contextTrackScoreValue > 0
          : String(decision.contextSignal || "").toUpperCase() === "BUY",
      note:
        !contextTrackEnabled
          ? t("环境轨 BUY 门已关闭。")
          : contextGateReasons.length > 0
          ? contextGateReasons.map(_humanizeGateReason).join("；")
          : t("当前环境轨方向 {v0}。", { v0: _localizeTrackBias(decision.contextSignal) })
    },
    ...(portfolioExecutionGuard ? [{
      key: "portfolio-execution-guard",
      label: t("组合防守 / BUY分层"),
      current: [
        _localizeDynamicText(String(portfolioExecutionGuard.buy_tier_label || portfolioExecutionGuard.buy_tier || "--")),
        portfolioGuardScore === null ? "" : t("分数 {v0}", { v0: portfolioGuardScore.toFixed(2) }),
        portfolioGuardMultiplier === null ? "" : t("倍率 {v0}", { v0: portfolioGuardMultiplier.toFixed(2) }),
      ].filter(Boolean).join(" · "),
      threshold: _localizeDynamicText(String(portfolioExecutionGuard.status || "passed")),
      status: String(portfolioExecutionGuard.status || "").toLowerCase() === "blocked"
        ? false
        : String(portfolioExecutionGuard.status || "").toLowerCase() === "downgraded"
        ? null
        : true,
      note: portfolioGuardReasons.length > 0
        ? portfolioGuardReasons.map((item) => _localizeDynamicText(String(item))).join("；")
        : t("组合防守未触发额外降级。")
    }] : []),
  ];
  const normalizedFinalAction = String(finalActionForChain || decision.finalAction || decision.action || "").toUpperCase();
  const normalizedCoreRuleAction = String(coreRuleAction || "").toUpperCase();
  const normalizedWeightedThresholdAction = String(weightedThresholdAction || "").toUpperCase();
  const normalizedWeightedGateAction = String(weightedGateAction || "").toUpperCase();
  const decisionSummaryLine =
    normalizedFinalAction === "SELL"
      ? fusionScoreValue !== null && sellThresholdValue !== null && fusionScoreValue <= sellThresholdValue
        ? t("卖出：融合分 {v0} <= 卖出阈值 {v1}", { v0: fusionScoreValue.toFixed(4), v1: sellThresholdValue.toFixed(4) })
        : normalizedCoreRuleAction === "SELL"
        ? t("卖出：核心规则触发；融合分 {v0} 未低于卖出阈值{v1}", { v0: fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4), v1: sellThresholdValue === null ? "" : ` ${sellThresholdValue.toFixed(4)}` })
        : t("卖出：最终动作由卖出规则放行")
      : fusionScoreValue !== null && buyThresholdValue !== null && sellThresholdValue !== null
      ? normalizedFinalAction === "BUY"
        ? t("买入：融合分 {v0} >= 买入阈值 {v1}", { v0: fusionScoreValue.toFixed(4), v1: buyThresholdValue.toFixed(4) })
        : fusionScoreValue < buyThresholdValue
        ? t("未买入：融合分 {v0} < 买入阈值 {v1}", { v0: fusionScoreValue.toFixed(4), v1: buyThresholdValue.toFixed(4) })
        : t("保持观望：融合分 {v0} 位于阈值区间内", { v0: fusionScoreValue.toFixed(4) })
      : t("当前快照缺少融合阈值，无法生成一句话门控结论");
  const buyGapValue =
    fusionScoreValue !== null && buyThresholdValue !== null ? buyThresholdValue - fusionScoreValue : null;
  const sellGapValue =
    fusionScoreValue !== null && sellThresholdValue !== null ? fusionScoreValue - sellThresholdValue : null;
  const gateDeltaLine =
    normalizedFinalAction === "SELL" && fusionScoreValue !== null && sellThresholdValue !== null
      ? fusionScoreValue <= sellThresholdValue
        ? t("已低于卖出线 {v0}", { v0: Math.abs(sellGapValue ?? 0).toFixed(4) })
        : t("核心规则卖出；融合分距卖出线 {v0}，加权阈值仍为 {v1}", { v0: sellGapValue?.toFixed(4) ?? "--", v1: localizeDecisionCode(weightedThresholdAction) })
      : fusionScoreValue !== null && buyThresholdValue !== null && fusionScoreValue < buyThresholdValue
      ? t("离买入线还差 {v0}", { v0: buyGapValue?.toFixed(4) ?? "--" })
      : fusionScoreValue !== null && sellThresholdValue !== null && fusionScoreValue <= sellThresholdValue
      ? t("已低于卖出线 {v0}", { v0: Math.abs(sellGapValue ?? 0).toFixed(4) })
      : fusionScoreValue !== null && buyThresholdValue !== null && sellThresholdValue !== null
      ? t("当前位于买卖阈值之间，距买入线 {v0}", { v0: buyGapValue?.toFixed(4) ?? "--" })
      : t("当前快照缺少完整阈值，暂时无法计算距离。");
  const chainBlockingStage =
    vetoes.length > 0
      ? t("Veto 否决层")
      : normalizedFinalAction === "SELL" && normalizedCoreRuleAction === "SELL"
      ? t("核心卖出规则")
      : finalActionForChain === "BUY"
      ? t("全部门控通过")
      : weightedThresholdAction === "SELL" && finalActionForChain !== "SELL"
      ? t("SELL 优先门")
      : weightedGateAction !== weightedThresholdAction
      ? t("加权门控层")
      : weightedThresholdAction === "HOLD"
      ? t("融合阈值层")
      : t("规则融合层");
  const driverSummaryLine =
    normalizedFinalAction === "SELL"
      ? normalizedCoreRuleAction === "SELL"
        ? t("卖出由核心规则触发；加权阈值为 {v0}、加权门控为 {v1}，但 hybrid 模式下核心卖出优先。", { v0: localizeDecisionCode(weightedThresholdAction), v1: localizeDecisionCode(weightedGateAction) })
        : t("卖出由 {v0} 触发，需结合卖出线和持仓风险查看。", { v0: chainBlockingStage })
      : fusionScoreValue !== null && buyThresholdValue !== null && sellThresholdValue !== null
      ? fusionScoreValue < buyThresholdValue && fusionScoreValue > sellThresholdValue
        ? t("本次不是被单一维度直接否决，而是技术轨与环境轨先完成组聚合，再形成融合分 {v0}。该分值仍落在买卖阈值之间，最终停在 {v1}，所以动作仍是 {v2}。", { v0: fusionScoreValue.toFixed(4), v1: chainBlockingStage, v2: localizeDecisionCode(finalActionForChain) })
        : fusionScoreValue >= buyThresholdValue
        ? t("融合分 {v0} 已达到买入阈值 {v1}，当前链路没有在阈值层阻断。", { v0: fusionScoreValue.toFixed(4), v1: buyThresholdValue.toFixed(4) })
        : t("融合分 {v0} 已低于卖出阈值 {v1}，当前需要重点查看 {v2} 是否继续放行 {v3}。", { v0: fusionScoreValue.toFixed(4), v1: sellThresholdValue.toFixed(4), v2: chainBlockingStage, v3: localizeDecisionCode(finalActionForChain) })
      : t("当前快照缺少完整阈值，暂时无法明确定位阻断阶段。");
  const fusionExplainerLine =
    fusionScoreValue !== null
      ? t("双轨融合按 技术轨 {v0} × {v1}% 与 环境轨 {v2} × {v3}% 计算，得到融合分 {v4}。", { v0: _formatSigned(techTrackScoreValue), v1: (Number(fusionBreakdown.tech_weight_norm ?? 0) * 100).toFixed(1), v2: _formatSigned(contextTrackScoreValue), v3: (Number(fusionBreakdown.context_weight_norm ?? 0) * 100).toFixed(1), v4: fusionScoreValue.toFixed(4) })
      : t("当前快照缺少融合分，无法展开双轨合成说明。");
  const finalDecisionChainLine = t("动作链路：Veto {v0} -> 核心规则 {v1} -> 加权阈值 {v2} -> 加权门控 {v3} -> 最终 {v4}。", { v0: vetoes.length > 0 ? t("命中") : t("未命中"), v1: localizeDecisionCode(coreRuleAction), v2: localizeDecisionCode(weightedThresholdAction), v3: localizeDecisionCode(weightedGateAction), v4: localizeDecisionCode(finalActionForChain) });
  const executionPlanLine =
    String(decision.action || "").toUpperCase() !== "BUY"
      ? ""
      : positionSizingQuantity !== null && positionSizingQuantity > 0
      ? [
          t("执行：信号仓位 {v0}%", { v0: decision.positionSizePct }),
          positionSizingMultiplier === null ? "" : t("执行倍率 {v0}", { v0: _formatMultiplier(positionSizingMultiplier) }),
          positionSizingSlotUnits === null ? "" : `slot ${_formatPlainNumber(positionSizingSlotUnits, 2)}`,
          t("预估买入 {v0}", { v0: _formatShareQuantity(positionSizingQuantity) }),
          positionSizingBuyBudget === null ? "" : t("预算 {v0}", { v0: _formatPlainNumber(positionSizingBuyBudget, 2) }),
        ].filter(Boolean).join(" · ")
      : positionSizingSkipReason
      ? [
          t("执行：信号仓位 {v0}%", { v0: decision.positionSizePct }),
          positionSizingMultiplier === null ? "" : t("执行倍率 {v0}", { v0: _formatMultiplier(positionSizingMultiplier) }),
          t("当前无法形成一手：{v0}", { v0: positionSizingSkipReason }),
        ].filter(Boolean).join(" · ")
      : positionSizingMultiplier !== null
      ? t("执行：信号仓位 {v0}% · 执行倍率 {v1}", { v0: decision.positionSizePct, v1: _formatMultiplier(positionSizingMultiplier) })
      : "";
  const coldStartLine =
    !coldStartActive
      ? ""
      : [
          t("冷启动：盈利样本 {v0}/{v1}", { v0: coldStartSampleCount === null ? "--" : String(Math.round(coldStartSampleCount)), v1: coldStartSampleThreshold === null ? "--" : String(Math.round(coldStartSampleThreshold)) }),
          t("当前按冷启动规则限仓"),
          portfolioGuardMultiplier === null ? "" : t("倍率 {v0}", { v0: _formatMultiplier(portfolioGuardMultiplier) }),
        ].filter(Boolean).join(" · ");
  const keyDecisionLines = [
    t("策略：{v0} · {v1} · {v2}", { v0: _localizeDynamicText(decision.appliedProfile), v1: localizeStrategyMode(decision.strategyMode), v2: decision.aiProfileSwitched === t("是") ? t("模板已切换") : t("模板未切换") }),
    t("市场：{v0} · 风格 {v1} · 基本面 {v2}", { v0: _localizeDynamicText(decision.marketRegime), v1: _localizeDynamicText(decision.riskStyle), v2: _localizeDynamicText(decision.fundamentalQuality) }),
    t("双轨：技术{v0}({v1}) · 环境{v2}({v3}) · 置信度 {v4}", { v0: _localizeTrackBias(decision.techSignal), v1: _formatSigned(techTrackScoreValue), v2: _localizeTrackBias(decision.contextSignal), v3: _formatSigned(contextTrackScoreValue), v4: fusionConfidenceValue === null ? "--" : fusionConfidenceValue.toFixed(4) }),
    _isPositionAddIntent(decision.executionIntent) && positionAddGate
      ? t("加仓：当前 {v0}% -> 目标 {v1}%，本次差额 {v2}%", { v0: _safeValue(String(positionAddGate.current_position_pct ?? "")), v1: _safeValue(String(positionAddGate.target_position_pct ?? "")), v2: _safeValue(String(positionAddGate.add_position_delta_pct ?? "")) })
      : "",
    executionPlanLine,
    coldStartLine,
    t("链路：核心 {v0} -> 加权 {v1} -> 门控 {v2} -> 最终 {v3}", { v0: localizeDecisionCode(coreRuleAction), v1: localizeDecisionCode(weightedThresholdAction), v2: localizeDecisionCode(weightedGateAction), v3: localizeDecisionCode(finalActionForChain) }),
  ].filter(Boolean);
  const filteredVoteRows = voteRows.filter((item) => {
    if (voteTrackFilter !== "all" && item.track !== voteTrackFilter) {
      return false;
    }
    const contributionValue = _parseNumeric(item.contribution);
    if (voteContributionFilter === "positive") {
      return contributionValue !== null && contributionValue > 0;
    }
    if (voteContributionFilter === "negative") {
      return contributionValue !== null && contributionValue < 0;
    }
    if (voteContributionFilter === "actionable") {
      return String(item.signal || "").toUpperCase() !== "HOLD";
    }
    return true;
  });
  const buyGapDisplay =
    buyGapValue === null ? "--" : buyGapValue <= 0 ? t("已达线") : buyGapValue.toFixed(4);
  const sellGapDisplay =
    sellGapValue === null ? "--" : sellGapValue <= 0 ? t("已破线") : sellGapValue.toFixed(4);
  const dominantContributionTrack =
    Math.abs(technicalContribution) === Math.abs(contextContribution)
      ? t("均衡")
      : Math.abs(technicalContribution) > Math.abs(contextContribution)
      ? t("技术轨")
      : t("环境轨");

  return (
    <div>
      <PageHeader
        eyebrow={t("信号")}
        title={t("信号详情 #{v0}", { v0: decision.id })}
        description={`${decision.stockCode} ${decision.stockName || ""} · ${_displayActionLabel(decision.action, decision.executionIntent)} · ${_localizeStatus(decision.status)}`}
        actions={
          <div className="chip-row">
            <button className="button button--secondary" type="button" onClick={() => navigate(-1)}>
              {t("返回")}</button>
            <button
              className="button button--secondary"
              type="button"
              disabled={marketRefreshPending}
              onClick={() => {
                setMarketRefreshPending(true);
                setMarketRefreshSeq((current) => current + 1);
              }}
            >
              {marketRefreshPending ? t("刷新中...") : t("刷新行情")}
            </button>
            <button
              className="button button--secondary"
              type="button"
              onClick={() => navigate(decision.source === "replay" ? "/his-replay" : "/live-sim")}
            >
              {decision.source === "replay" ? t("历史回放") : t("实时量化")}
            </button>
          </div>
        }
      />

      <div className="stack">
        <WorkbenchCard>
          <div className="signal-detail-section-stack">
            <section>
              <div className="signal-detail-split-layout signal-detail-split-layout--hero" data-testid="decision-split-layout">
                <div className="signal-detail-focus-panel signal-detail-focus-panel--hero" data-testid="decision-hero-panel">
                  <div className="signal-detail-focus-panel__eyebrow-row">
                    <div>
                      <div className="signal-detail-focus-panel__eyebrow">{t("决策结论")}</div>
                      <h2 className="section-card__title" style={{ marginBottom: 0 }}>
                        {`${decision.stockCode} ${decision.stockName || ""}`.trim()}
                      </h2>
                    </div>
                    <span className={_actionChipClass(decision.finalAction)} data-testid="final-action-chip">
                      {_displayActionLabel(decision.finalAction, decision.executionIntent)}
                    </span>
                  </div>
                  <div className="signal-detail-focus-panel__headline">{decisionSummaryLine}</div>
                  <div className="signal-detail-focus-panel__supporting">
                    <div>{t("决策点 {v0} · {v1} · {v2}", { v0: decision.checkpointAt, v1: localizeDecisionCode(decision.status), v2: localizeStrategyMode(decision.strategyMode) })}</div>
                    {keyDecisionLines.map((line) => (
                      <div key={line}>{line}</div>
                    ))}
                  </div>
                </div>
                  <div className="signal-detail-summary-grid" data-testid="decision-summary-grid">
                  <div className="signal-detail-summary-stat signal-detail-summary-stat--emphasis">
                    <span className="signal-detail-summary-stat__label">{t("动作")}</span>
                    <strong className="signal-detail-summary-stat__value">{_displayActionLabel(decision.action, decision.executionIntent)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat signal-detail-summary-stat--emphasis">
                    <span className="signal-detail-summary-stat__label">{t("核心规则")}</span>
                    <strong className="signal-detail-summary-stat__value">{localizeDecisionCode(coreRuleAction)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{t("融合分")}</span>
                    <strong className="signal-detail-summary-stat__value">{fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{t("融合置信度")}</span>
                    <strong className="signal-detail-summary-stat__value">{fusionConfidenceValue === null ? "--" : fusionConfidenceValue.toFixed(4)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{t("技术分")}</span>
                    <strong className="signal-detail-summary-stat__value">{decision.techScore}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{t("环境分")}</span>
                    <strong className="signal-detail-summary-stat__value">{decision.contextScore}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{t("策略模式")}</span>
                    <strong className="signal-detail-summary-stat__value">{localizeStrategyMode(decision.strategyMode)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{positionMetricLabel}</span>
                    <strong className="signal-detail-summary-stat__value">{positionMetricValue}</strong>
                  </div>
                  {executionSizingPlan || kernelSuggestedPct !== null ? (
                    <div className="signal-detail-summary-stat">
                      <span className="signal-detail-summary-stat__label">{t("Kernel 建议仓位")}</span>
                      <strong className="signal-detail-summary-stat__value">{_formatPercentNumber(kernelSuggestedPct)}</strong>
                    </div>
                  ) : null}
                  {executionSizingPlan ? (
                    <>
                      <div className="signal-detail-summary-stat">
                        <span className="signal-detail-summary-stat__label">{t("最终执行仓位")}</span>
                        <strong className="signal-detail-summary-stat__value">{_formatPercentNumber(executionEffectivePct)}</strong>
                      </div>
                      <div className="signal-detail-summary-stat">
                        <span className="signal-detail-summary-stat__label">{t("最终预算")}</span>
                        <strong className="signal-detail-summary-stat__value">{_formatCurrencyNumber(executionFinalBudget)}</strong>
                      </div>
                      <div className="signal-detail-summary-stat">
                        <span className="signal-detail-summary-stat__label">{t("风险预算")}</span>
                        <strong className="signal-detail-summary-stat__value">{_formatPercentNumber(executionRiskBudgetPct)}</strong>
                      </div>
                    </>
                  ) : null}
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{t("执行倍率")}</span>
                    <strong className="signal-detail-summary-stat__value">{_formatMultiplier(positionSizingMultiplier)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{t("预估数量")}</span>
                    <strong className="signal-detail-summary-stat__value">
                      {positionSizingQuantity !== null && positionSizingQuantity > 0
                        ? _formatShareQuantity(positionSizingQuantity)
                        : positionSizingSkipReason
                        ? t("不足一手")
                        : "--"}
                    </strong>
                  </div>
                </div>
              </div>
            </section>

            <section>
              <div className="signal-detail-split-layout signal-detail-split-layout--gates" data-testid="gate-split-layout">
                <div className="signal-detail-focus-panel" data-testid="gate-focus-panel">
                  <div className="signal-detail-focus-panel__eyebrow-row">
                    <div>
                      <div className="signal-detail-focus-panel__eyebrow">{t("门控检查")}</div>
                      <h2 className="section-card__title" style={{ marginBottom: 0 }}>{t("为什么停在这里")}</h2>
                    </div>
                    <span className={_gateStatusClass(gateRows.every((item) => item.status !== false) ? true : false)}>
                      {localizeDecisionCode(decision.ruleHit)}
                    </span>
                  </div>
                  <div className="signal-detail-focus-panel__headline">{decisionSummaryLine}</div>
                  <div className="signal-detail-focus-panel__supporting">
                    <div>{gateDeltaLine}</div>
                    <div>{t("当前落点：加权阈值 {v0} · 加权门控 {v1}。", { v0: localizeDecisionCode(weightedThresholdAction), v1: localizeDecisionCode(weightedGateAction) })}</div>
                  </div>
                  <div className="signal-detail-focus-panel__metrics">
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">{t("买入线")}</span>
                      <strong className="signal-detail-inline-metric__value">
                        {buyThresholdValue === null ? "--" : buyThresholdValue.toFixed(4)}
                      </strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">{t("卖出线")}</span>
                      <strong className="signal-detail-inline-metric__value">
                        {sellThresholdValue === null ? "--" : sellThresholdValue.toFixed(4)}
                      </strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">{t("距买入线")}</span>
                      <strong className="signal-detail-inline-metric__value">{buyGapDisplay}</strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">{t("距卖出线")}</span>
                      <strong className="signal-detail-inline-metric__value">{sellGapDisplay}</strong>
                    </div>
                  </div>
                </div>
                <div className="signal-detail-gate-grid" data-testid="gate-card-grid">
                  {gateRows.map((item) => (
                    <div
                      className={`signal-detail-gate-card signal-detail-gate-card--${_gateStatusTone(item.status)}`}
                      key={item.key}
                    >
                      <div className="signal-detail-gate-card__head">
                        <div>
                          <div className="signal-detail-gate-card__title">{item.label}</div>
                          <div className="signal-detail-gate-card__note">{item.note}</div>
                        </div>
                        <span className={_gateStatusClass(item.status)}>{_gateStatusLabel(item.status)}</span>
                      </div>
                      <div className="signal-detail-gate-card__values">
                        <div className="signal-detail-gate-card__value-block">
                          <span className="signal-detail-gate-card__value-label">{t("当前值")}</span>
                          <strong className="signal-detail-gate-card__value-number">{item.current}</strong>
                        </div>
                        <div className="signal-detail-gate-card__value-block">
                          <span className="signal-detail-gate-card__value-label">{t("阈值")}</span>
                          <strong className="signal-detail-gate-card__value-number">{item.threshold}</strong>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section>
              <div className="signal-detail-split-layout signal-detail-split-layout--contribution" data-testid="contribution-split-layout">
                <div className="signal-detail-focus-panel signal-detail-focus-panel--contrast" data-testid="contribution-overview-panel">
                  <div className="signal-detail-focus-panel__eyebrow-row">
                    <div>
                      <div className="signal-detail-focus-panel__eyebrow">{t("阻断链路")}</div>
                      <h2 className="section-card__title" style={{ marginBottom: 0 }}>{t("真实决策链路")}</h2>
                    </div>
                    <span className={_actionChipClass(finalActionForChain)} data-testid="chain-stage-chip">
                      {chainBlockingStage}
                    </span>
                  </div>
                  <div className="signal-detail-focus-panel__headline">{driverSummaryLine}</div>
                  <div className="signal-detail-focus-panel__metrics">
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">{t("技术票")}</span>
                      <strong className="signal-detail-inline-metric__value">{`${signalCount.buy}/${signalCount.sell}/${signalCount.hold}`}</strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">{t("技术贡献和")}</span>
                      <strong className="signal-detail-inline-metric__value">{_formatSigned(technicalContribution)}</strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">{t("环境贡献和")}</span>
                      <strong className="signal-detail-inline-metric__value">{_formatSigned(contextContribution)}</strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">{t("主导轨")}</span>
                      <strong className="signal-detail-inline-metric__value">{dominantContributionTrack}</strong>
                    </div>
                  </div>
                  <div className="signal-detail-focus-panel__supporting">
                    <div>{fusionExplainerLine}</div>
                  </div>
                </div>
                <div className="signal-detail-contribution-grid" data-testid="contribution-track-grid">
                  <div className="signal-detail-track-panel signal-detail-track-panel--technical">
                    <div className="signal-detail-track-panel__head">
                      <div>
                        <div className="signal-detail-track-panel__title">{t("技术轨聚合")}</div>
                        <div className="signal-detail-track-panel__meta">
                          {t("先按组聚合，再形成技术轨方向 {v0} · 分值 {v1}。", { v0: _localizeTrackBias(decision.techSignal), v1: _formatSigned(techTrackScoreValue) })}
                        </div>
                      </div>
                      <span className={_gateStatusClass((techTrackScoreValue ?? 0) > 0 ? true : (techTrackScoreValue ?? 0) < 0 ? false : null)}>
                        {_localizeTrackBias(decision.techSignal)}
                      </span>
                    </div>
                    <ul className="signal-detail-ranked-list">
                      {technicalGroupRows.map((item) => (
                        <li className="signal-detail-ranked-list__item" key={item.key}>
                          <div className="signal-detail-ranked-list__main">
                            <span className="signal-detail-ranked-list__label">{item.label}</span>
                            <strong className="signal-detail-ranked-list__value">{_formatSigned(item.contribution)}</strong>
                          </div>
                          <div className="signal-detail-ranked-list__meta">
                            {t("组分 {v0} · 覆盖 {v1}", { v0: _formatSigned(item.score), v1: item.coverage === null ? "--" : `${(item.coverage * 100).toFixed(1)}%` })}
                          </div>
                          <div className="signal-detail-ranked-list__meta">{groupDominantLine(technicalDimensionRows, item.groupId || "--")}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="signal-detail-track-panel signal-detail-track-panel--context">
                    <div className="signal-detail-track-panel__head">
                      <div>
                        <div className="signal-detail-track-panel__title">{t("环境轨聚合")}</div>
                        <div className="signal-detail-track-panel__meta">
                          {t("先按组聚合，再形成环境轨方向 {v0} · 分值 {v1}。", { v0: _localizeTrackBias(decision.contextSignal), v1: _formatSigned(contextTrackScoreValue) })}
                        </div>
                      </div>
                      <span className={_gateStatusClass((contextTrackScoreValue ?? 0) > 0 ? true : (contextTrackScoreValue ?? 0) < 0 ? false : null)}>
                        {_localizeTrackBias(decision.contextSignal)}
                      </span>
                    </div>
                    <ul className="signal-detail-ranked-list">
                      {contextGroupRows.map((item) => (
                        <li className="signal-detail-ranked-list__item" key={item.key}>
                          <div className="signal-detail-ranked-list__main">
                            <span className="signal-detail-ranked-list__label">{item.label}</span>
                            <strong className="signal-detail-ranked-list__value">{_formatSigned(item.contribution)}</strong>
                          </div>
                          <div className="signal-detail-ranked-list__meta">
                            {t("组分 {v0} · 覆盖 {v1}", { v0: _formatSigned(item.score), v1: item.coverage === null ? "--" : `${(item.coverage * 100).toFixed(1)}%` })}
                          </div>
                          <div className="signal-detail-ranked-list__meta">{groupDominantLine(contextDimensionRows, item.groupId || "--")}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="signal-detail-track-panel">
                    <div className="signal-detail-track-panel__head">
                      <div>
                        <div className="signal-detail-track-panel__title">{t("双轨融合")}</div>
                        <div className="signal-detail-track-panel__meta">{t("技术轨与环境轨先按权重融合，再进入阈值与门控。")}</div>
                      </div>
                    </div>
                    <ul className="signal-detail-ranked-list">
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">{t("技术轨输入")}</span>
                          <strong className="signal-detail-ranked-list__value">{`${_formatSigned(techTrackScoreValue)} × ${(Number(fusionBreakdown.tech_weight_norm ?? 0) * 100).toFixed(1)}%`}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{t("原始权重 {v0}，归一化后参与融合。", { v0: String(fusionBreakdown.tech_weight_raw ?? "--") })}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">{t("环境轨输入")}</span>
                          <strong className="signal-detail-ranked-list__value">{`${_formatSigned(contextTrackScoreValue)} × ${(Number(fusionBreakdown.context_weight_norm ?? 0) * 100).toFixed(1)}%`}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{t("原始权重 {v0}，归一化后参与融合。", { v0: String(fusionBreakdown.context_weight_raw ?? "--") })}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">{t("融合分")}</span>
                          <strong className="signal-detail-ranked-list__value">{fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4)}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{t("置信度 {v0}，基础值 {v1}，分歧惩罚 {v2}", { v0: fusionConfidenceValue === null ? "--" : fusionConfidenceValue.toFixed(4), v1: String(fusionBreakdown.fusion_confidence_base ?? "--"), v2: String(fusionBreakdown.divergence_penalty ?? "--") })}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">{t("融合结论")}</span>
                          <strong className="signal-detail-ranked-list__value">{`${localizeDecisionCode(weightedThresholdAction)} -> ${localizeDecisionCode(weightedGateAction)}`}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{t("方向冲突 {v0}，技术轨 {v1}，环境轨 {v2}。", { v0: String(fusionBreakdown.sign_conflict ?? 0), v1: _localizeTrackBias(decision.techSignal), v2: _localizeTrackBias(decision.contextSignal) })}</div>
                      </li>
                    </ul>
                  </div>
                  <div className="signal-detail-track-panel">
                    <div className="signal-detail-track-panel__head">
                      <div>
                        <div className="signal-detail-track-panel__title">{t("最终门控")}</div>
                        <div className="signal-detail-track-panel__meta">{t("真正决定是否买入的，是融合分与门控链，而不是单个维度排行。")}</div>
                      </div>
                    </div>
                    <ul className="signal-detail-ranked-list">
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">{t("规则层")}</span>
                          <strong className="signal-detail-ranked-list__value">{t("{v0} -> {v1}", { v0: vetoes.length > 0 ? t("Veto 命中") : t("Veto 未命中"), v1: localizeDecisionCode(coreRuleAction) })}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{vetoes.length > 0 ? vetoes.map((item) => `${String(item.id || "--")} · ${_localizeDynamicText(String(item.reason || "--"))}`).join("；") : t("规则命中 {v0}。", { v0: _localizeDynamicText(decision.ruleHit) })}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">{t("阈值层")}</span>
                          <strong className="signal-detail-ranked-list__value">{localizeDecisionCode(weightedThresholdAction)}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{decisionSummaryLine}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">{t("最终动作")}</span>
                          <strong className="signal-detail-ranked-list__value">{`${localizeDecisionCode(weightedGateAction)} -> ${localizeDecisionCode(finalActionForChain)}`}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{`${gateDeltaLine}；${finalDecisionChainLine}`}</div>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
            </section>

            <CollapsibleSection
              title={t("投票明细")}
              summary={t("{v0} 条投票，默认折叠，只在需要排查时展开。", { v0: voteRows.length })}
              expandLabel={t("展开投票明细")}
              collapseLabel={t("收起投票明细")}
            >
              <div className="signal-detail-filter-row">
                {[
                  { key: "all", label: t("全部") },
                  { key: "technical", label: t("技术") },
                  { key: "context", label: t("环境") },
                ].map((option) => (
                  <button
                    key={option.key}
                    className={`button button--small ${voteTrackFilter === option.key ? "" : "button--secondary"}`}
                    type="button"
                    onClick={() => setVoteTrackFilter(option.key as "all" | "technical" | "context")}
                  >
                    {option.label}
                  </button>
                ))}
                {[
                  { key: "all", label: t("全部贡献") },
                  { key: "positive", label: t("正贡献") },
                  { key: "negative", label: t("负贡献") },
                  { key: "actionable", label: t("只看非 HOLD") },
                ].map((option) => (
                  <button
                    key={option.key}
                    className={`button button--small ${voteContributionFilter === option.key ? "" : "button--secondary"}`}
                    type="button"
                    onClick={() => setVoteContributionFilter(option.key as "all" | "positive" | "negative" | "actionable")}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <CompactDataTable
                isCompactLayout={isCompactLayout}
                headers={[t("轨道"), t("主体"), t("信号"), t("权重"), t("贡献"), t("依据")]}
                coreIndexes={[0, 1, 2, 4]}
                emptyText={t("当前筛选下没有投票明细")}
                rows={filteredVoteRows.map((item, index) => ({
                  key: `vote-row-${index}`,
                  cells: [
                    _trackLabel(item.track),
                    item.track === "context" ? _localizeEnvComponentName(item.voter) : _localizeDynamicText(item.voter),
                    localizeDecisionCode(item.signal),
                    item.weight,
                    item.contribution,
                    _localizeDynamicText(item.reason || "--"),
                  ],
                }))}
              />
            </CollapsibleSection>

            <CollapsibleSection
              title={t("审计模式")}
              summary={t("结构化依据、参数快照与原始模型文本，默认折叠，仅在复盘或排查时展开。")}
              expandLabel={t("展开审计模式")}
              collapseLabel={t("收起审计模式")}
            >
              {auditSummaryList.length > 0 ? (
                <div className="summary-item">
                  <div className="summary-item__title">{t("审计总结")}</div>
                  <ul className="insight-list">
                    {auditSummaryList.map((item, index) => (
                      <li key={`audit-summary-line-${index}`}>{_localizeDynamicText(item)}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {basisList.length > 0 ? (
                <div className="summary-item">
                  <div className="summary-item__title">{t("原始依据链路")}</div>
                  <ul className="insight-list">
                    {basisList.map((item, index) => (
                      <li key={`basis-line-${index}`}>{_localizeDynamicText(item)}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div className="signal-detail-audit-stack">
                <div>
                  <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>{t("决策指标")}</h3>
                  <div className="signal-detail-audit-groups">
                    {decisionMetricGroups.map((group) => (
                      <div className="signal-detail-audit-group" key={group.key}>
                        <div className="signal-detail-audit-group__header">
                          <div>
                            <div className="signal-detail-audit-group__title">{group.label}</div>
                            <div className="signal-detail-audit-group__note">{group.note}</div>
                          </div>
                          <span className="signal-detail-chip signal-detail-chip--neutral">{t("{v0} 项", { v0: group.rows.length })}</span>
                        </div>
                        <CompactDataTable
                          isCompactLayout={isCompactLayout}
                          headers={[t("参数"), t("值"), t("来源"), t("计算方式")]}
                          coreIndexes={[0, 1, 2]}
                          emptyText={t("暂无决策指标")}
                          rows={group.rows.map((item, index) => ({
                            key: `${group.key}-${index}`,
                            cells: [
                              _localizeDynamicText(item.name),
                              _localizeValue(item.value),
                              _localizeSourceLabel(item.source),
                              _localizeDynamicText(item.derivation),
                            ],
                          }))}
                        />
                      </div>
                    ))}
                  </div>
                </div>

                {(executionThresholdRows.length > 0 || buyGateThresholdRows.length > 0) ? (
                  <div>
                    <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>{t("运行参数快照")}</h3>
                    <div className="signal-detail-audit-groups">
                      {executionThresholdRows.length > 0 ? (
                        <div className="signal-detail-audit-group">
                          <div className="signal-detail-audit-group__header">
                            <div>
                              <div className="signal-detail-audit-group__title">{t("执行阈值")}</div>
                              <div className="signal-detail-audit-group__note">{t("直接影响买入、卖出与仓位约束的生效阈值。")}</div>
                            </div>
                            <span className="signal-detail-chip signal-detail-chip--neutral">{t("{v0} 项", { v0: executionThresholdRows.length })}</span>
                          </div>
                          <CompactDataTable
                            isCompactLayout={isCompactLayout}
                            headers={[t("执行阈值"), t("值"), t("来源"), t("计算方式")]}
                            coreIndexes={[0, 1, 2]}
                            emptyText={t("暂无执行阈值")}
                            rows={executionThresholdRows.map((item, index) => ({
                              key: `execution-threshold-${index}`,
                              cells: [
                                _localizeThresholdName(item.name),
                                _localizeValue(item.value),
                                _localizeSourceLabel(item.source),
                                _localizeDynamicText(item.derivation),
                              ],
                            }))}
                          />
                        </div>
                      ) : null}
                      {buyGateThresholdRows.length > 0 ? (
                        <div className="signal-detail-audit-group">
                          <div className="signal-detail-audit-group__header">
                            <div>
                              <div className="signal-detail-audit-group__title">{t("买入门控阈值")}</div>
                              <div className="signal-detail-audit-group__note">{t("只有 BUY 候选动作才会继续检查的最小分值与最小置信度门槛。")}</div>
                            </div>
                            <span className="signal-detail-chip signal-detail-chip--neutral">{t("{v0} 项", { v0: buyGateThresholdRows.length })}</span>
                          </div>
                          <CompactDataTable
                            isCompactLayout={isCompactLayout}
                            headers={[t("买入门控阈值"), t("值"), t("来源"), t("计算方式")]}
                            coreIndexes={[0, 1, 2]}
                            emptyText={t("暂无买入门控阈值")}
                            rows={buyGateThresholdRows.map((item, index) => ({
                              key: `buy-gate-threshold-${index}`,
                              cells: [
                                _localizeThresholdName(item.name),
                                _localizeValue(item.value),
                                _localizeSourceLabel(item.source),
                                _localizeDynamicText(item.derivation),
                              ],
                            }))}
                          />
                        </div>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                <div>
                  <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>{t("技术指标")}</h3>
                  <CompactDataTable
                    isCompactLayout={isCompactLayout}
                    headers={[t("指标"), t("数值"), t("来源"), t("说明/计算方式")]}
                    coreIndexes={[0, 1, 2]}
                    emptyText={t("暂无技术指标")}
                    rows={mergedTechnicalRows.map((item, index) => ({
                      key: `tech-${index}`,
                      cells: [
                        _localizeDynamicText(item.name),
                        _localizeValue(item.value),
                        _localizeSourceLabel(item.source),
                        _localizeDynamicText(item.detail || "--"),
                      ],
                    }))}
                  />
                </div>

                {techEvidence.length > 0 ? (
                  <div className="summary-item">
                    <div className="summary-item__title">{t("关键技术证据")}</div>
                    <ul className="insight-list">
                      {techEvidence.map((item) => (
                        <li key={item}>{_localizeDynamicText(item)}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div>
                  <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>{t("环境指标")}</h3>
                  <div className="summary-item" style={{ marginBottom: "10px" }}>
                    <div className="summary-item__title">{t("环境分计算")}</div>
                    <div className="summary-item__body">{_localizeDynamicText(contextScoreExplain.formula || t("暂无环境分公式"))}</div>
                    <div className="summary-item__body">{_localizeDynamicText(contextScoreExplain.confidenceFormula || t("暂无环境置信度公式"))}</div>
                    <div className="summary-item__body">
                      {t("组件和={v0}，最终环境分={v1}", { v0: String(contextScoreExplain.componentSum ?? "0"), v1: contextScoreExplain.finalScore || decision.contextScore })}
                    </div>
                    {(contextScoreExplain.componentBreakdown ?? []).length > 0 ? (
                      <ul className="insight-list">
                        {(contextScoreExplain.componentBreakdown ?? []).map((item) => (
                          <li key={item}>{_localizeComponentBreakdownLine(item)}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                  <CompactDataTable
                    isCompactLayout={isCompactLayout}
                    headers={[t("环境因子"), t("分值"), t("说明")]}
                    coreIndexes={[0, 1]}
                    emptyText={t("暂无环境指标")}
                    rows={environmentRows.map((item, index) => ({
                      key: `ctx-${index}`,
                      cells: [_localizeEnvComponentName(item.factor), item.score, _localizeDynamicText(item.reason)],
                    }))}
                  />
                </div>

                {dedupedEnvironmentParameterRows.length > 0 ? (
                  <div>
                    <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>{t("环境参数")}</h3>
                    <CompactDataTable
                      isCompactLayout={isCompactLayout}
                      headers={[t("环境参数"), t("值"), t("来源"), t("计算方式")]}
                      coreIndexes={[0, 1, 2]}
                      emptyText={t("暂无环境参数")}
                      rows={dedupedEnvironmentParameterRows.map((item, index) => ({
                        key: `env-param-${index}`,
                        cells: [
                          _localizeDynamicText(item.name),
                          _localizeValue(item.value),
                          _localizeSourceLabel(item.source),
                          _localizeDynamicText(item.derivation),
                        ],
                      }))}
                    />
                  </div>
                ) : null}

                {contextEvidence.length > 0 ? (
                  <div className="summary-item">
                    <div className="summary-item__title">{t("关键环境证据")}</div>
                    <ul className="insight-list">
                      {contextEvidence.map((item) => (
                        <li key={item}>{_localizeDynamicText(item)}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="summary-item">
                  <div className="summary-item__title">{t("原始模型文本")}</div>
                  <div className="summary-item__body markdown-body" style={{ whiteSpace: "pre-wrap" }}>{_localizeDynamicText(originalAnalysis)}</div>
                  <div className="summary-item__body markdown-body" style={{ whiteSpace: "pre-wrap" }}>{_localizeDynamicText(originalReasoning)}</div>
                </div>
              </div>
            </CollapsibleSection>
          </div>
        </WorkbenchCard>
      </div>
    </div>
  );
}
