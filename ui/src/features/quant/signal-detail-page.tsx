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
};

type StrategyProfileSnapshot = {
  explainability?: ExplainabilityPayload;
};

type SignalDetailPayload = {
  updatedAt: string;
  analysis: string;
  reasoning: string;
  explanation?: {
    summary?: string;
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
    aiProfileSwitched: "否",
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
  "当前价",
  "涨跌幅",
  "开盘价",
  "最高价",
  "最低价",
  "成交量(手)",
  "成交额(万)",
  "换手率",
  "量比",
  "趋势",
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
  if (text === "当前价" || text === "现价" || text === "最新价" || text === "收盘价" || lower === "current_price" || lower === "last_price" || lower === "close") {
    return "当前价";
  }
  if (text === "涨跌幅" || text === "涨跌幅(%)" || lower === "change_pct") {
    return "涨跌幅";
  }
  if (text === "开盘价" || lower === "open") {
    return "开盘价";
  }
  if (text === "最高价" || lower === "high") {
    return "最高价";
  }
  if (text === "最低价" || lower === "low") {
    return "最低价";
  }
  if (text === "成交量" || text === "成交量(手)" || lower === "volume") {
    return "成交量(手)";
  }
  if (text === "成交额" || text === "成交额(万)" || lower === "amount") {
    return "成交额(万)";
  }
  if (text === "换手率" || lower === "turnover_rate") {
    return "换手率";
  }
  if (text === "量比" || lower === "volume_ratio") {
    return "量比";
  }
  if (text === "趋势" || lower === "trend") {
    return "趋势";
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
  if (text === "K值" || text === "KDJ-K" || lower === "kdj_k") {
    return "KDJ-K";
  }
  if (text === "D值" || text === "KDJ-D" || lower === "kdj_d") {
    return "KDJ-D";
  }
  if (text === "J值" || text === "KDJ-J" || lower === "kdj_j") {
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
  execution_feedback: "执行反馈",
  account_posture: "账户态势",
};

const THRESHOLD_KEY_MAP: Record<string, string> = {
  buy_threshold: "Threshold:buy_threshold",
  sell_threshold: "Threshold:sell_threshold",
  max_position_ratio: "Threshold:max_position_ratio",
  allow_pyramiding: "Threshold:allow_pyramiding",
  confirmation: "Threshold:confirmation",
  min_fusion_confidence: "BUY最小融合置信度",
  min_tech_score_for_buy: "BUY技术轨最小分值",
  min_context_score_for_buy: "BUY环境轨最小分值",
  min_tech_confidence_for_buy: "BUY技术轨最小置信度",
  min_context_confidence_for_buy: "BUY环境轨最小置信度",
  dynamic_stop_loss_pct: "动态止损(%)",
  dynamic_take_profit_pct: "动态止盈(%)",
  execution_feedback_delta: "执行反馈修正分",
  account_posture_delta: "账户态势修正分",
  available_cash_ratio: "可用资金占比",
  position_sizing_multiplier: "仓位缩放系数",
  suggested_position_pct: "建议仓位(%)",
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
  const pureKey = text.startsWith("阈值.") ? text.slice(3) : text;
  const mapped = THRESHOLD_KEY_MAP[pureKey];
  const localized = mapped ? (mapped.includes(":") ? t(mapped) : mapped) : pureKey;
  return text.startsWith("阈值.") ? `${t("Threshold prefix")}${localized}` : localized;
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
    return "偏多";
  }
  if (value === "SELL") {
    return "偏空";
  }
  if (value === "HOLD") {
    return "中性";
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
  if (source.includes("scheduler") || source.includes("sim_runs") || source.includes("调度配置/回放任务")) {
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

function _gateStatusLabel(status: boolean | null): string {
  if (status === true) {
    return "通过";
  }
  if (status === false) {
    return "未通过";
  }
  return "未提供";
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
  return track === "context" ? "环境" : "技术";
}

function _formatContributionLabel(track: "technical" | "context", rawLabel: string): string {
  return track === "context" ? _localizeEnvComponentName(rawLabel) : _localizeDynamicText(rawLabel);
}

const TRACK_GROUP_LABEL_MAP: Record<string, string> = {
  trend: "趋势组",
  momentum: "动量组",
  volume_confirmation: "量能确认组",
  volatility_risk: "波动风险组",
  market_structure: "市场结构组",
  risk_account: "风险账户组",
  tradability_timing: "流动时段组",
  source_execution: "来源执行组",
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
  fusion_confidence_below_min: "融合置信度低于最小门限",
  tech_score_below_min_for_buy: "技术轨 BUY 门未过",
  context_score_below_min_for_buy: "环境轨 BUY 门未过",
  tech_confidence_below_min_for_buy: "技术轨置信度门未过",
  context_confidence_below_min_for_buy: "环境轨置信度门未过",
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

  if (normalized.includes("兼容") || normalized.includes("派生") || normalized.includes("legacy")) {
    return { key: "legacy", label: "兼容派生字段", note: "兼容旧语义或派生说明，仅作辅助阅读。" };
  }
  if (source.includes("technical_breakdown") || normalized.includes("技术轨")) {
    return { key: "technical", label: "技术轨", note: "来自技术轨结构化 breakdown 的方向、分值或置信度。" };
  }
  if (source.includes("context_breakdown") || normalized.includes("环境轨")) {
    return { key: "context", label: "环境轨", note: "来自环境轨结构化 breakdown 的方向、分值或置信度。" };
  }
  if (
    source.includes("fusion_breakdown")
    || source.includes("decision_path")
    || source.includes("veto")
    || normalized.includes("融合")
    || normalized.includes("核心规则")
    || normalized.includes("最终动作")
    || normalized.includes("加权")
  ) {
    return { key: "fusion", label: "融合决策层", note: "描述规则层、加权层和最终动作如何汇合。" };
  }
  return { key: "runtime", label: "策略与运行态", note: "描述动态策略模式、模板绑定和运行上下文。" };
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
          <div className="signal-detail-collapsible__eyebrow">按需展开</div>
          <div className="signal-detail-collapsible__title-row">
            <h2 className="section-card__title" style={{ marginBottom: 0 }}>
              {title}
            </h2>
            <span className={`signal-detail-chip ${expanded ? "signal-detail-chip--neutral" : "signal-detail-chip--pass"}`}>
              {expanded ? "已展开" : "默认折叠"}
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
      setError("缺少 signal id");
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
    return <PageLoadingState title="信号详情加载中" description="正在读取投票明细、决策依据和技术指标快照。" />;
  }

  if (status === "error") {
    return (
      <PageErrorState
        title="信号详情加载失败"
        description={error ?? "无法加载信号详情，请稍后重试。"}
        actionLabel="返回"
        onAction={() => navigate(-1)}
      />
    );
  }

  if (!detail?.decision?.id) {
    return <PageEmptyState title="信号详情为空" description="当前信号没有可展示内容。" actionLabel="返回" onAction={() => navigate(-1)} />;
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
    if (name.startsWith("指标.")) {
      technicalParameterRows.push(item);
      continue;
    }
    if (name.startsWith("阈值.")) {
      thresholdRows.push(item);
      continue;
    }
    if (name.includes("环境") || name.includes("市场")) {
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
    const orderedKeys = ["fusion", "technical", "context", "runtime", "legacy"];
    return orderedKeys
      .map((key) => groupMap.get(key))
      .filter((item): item is DecisionMetricGroup => Boolean(item && item.rows.length > 0));
  })();
  const originalAnalysis = explanation.original?.analysis || detail.analysis || "暂无分析数据";
  const originalReasoning = explanation.original?.reasoning || detail.reasoning || "暂无决策理由";
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
      source: _safeValue(marketItem ? "行情快照" : ""),
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
    decisionParameterRows.find((item) => String(item.name || "").trim() === "市场")?.value
    || (decision as unknown as { market?: string }).market
    || "--";
  const basisList = explanation.basis ?? [];
  const voteActorLines = voteRows.map((item) => {
    const trackLabel = item.track === "context" ? "环境" : "技术";
    const voterLabel = item.track === "context" ? _localizeEnvComponentName(item.voter) : _localizeDynamicText(item.voter);
    return `${trackLabel}｜${voterLabel}：投票 ${localizeDecisionCode(item.signal)}，权重 ${item.weight}，贡献 ${item.contribution}，依据 ${_localizeDynamicText(item.reason || "--")}`;
  });
  const positionMetricLabel =
    String(decision.action || "").toUpperCase() === "BUY"
      ? "目标买入仓位(%)"
      : String(decision.action || "").toUpperCase() === "SELL"
      ? "建议卖出比例(%)"
      : "仓位建议";
  const positionMetricValue = String(decision.action || "").toUpperCase() === "HOLD" ? "不变" : decision.positionSizePct;
  const strategyExplainability = detail.strategyProfile?.explainability ?? {};
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
      return "暂无关键因子。";
    }
    return `关键因子：${driver.label} ${_formatSigned(driver.contribution)}`;
  };
  const techGateReasons = weightedGateFailReasons.filter((item) => item.startsWith("tech_"));
  const contextGateReasons = weightedGateFailReasons.filter((item) => item.startsWith("context_"));
  const fusionConfidenceGateReasons = weightedGateFailReasons.filter((item) => item.includes("fusion_confidence"));
  const gateRows: GateChecklistRow[] = [
    {
      key: "veto",
      label: "Veto 否决",
      current: vetoes.length > 0 ? _localizeDynamicText(String(vetoes[0]?.action || "--")) : "未命中",
      threshold: "不命中",
      status: vetoes.length === 0,
      note:
        vetoes.length === 0
          ? "未命中 veto，继续进入规则与加权门控链路。"
          : vetoes
              .map((item) => `${String(item.id || "--")} · ${_localizeDynamicText(String(item.reason || "--"))}`)
              .join("；"),
    },
    {
      key: "buy-threshold",
      label: "买入阈值门",
      current: fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4),
      threshold: buyThresholdValue === null ? "--" : buyThresholdValue.toFixed(4),
      status:
        fusionScoreValue !== null && buyThresholdValue !== null ? fusionScoreValue >= buyThresholdValue : null,
      note: "fusion_score >= buy_threshold 才能形成 BUY。"
    },
    {
      key: "sell-threshold",
      label: "卖出阈值门",
      current: fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4),
      threshold: sellThresholdValue === null ? "--" : sellThresholdValue.toFixed(4),
      status:
        fusionScoreValue !== null && sellThresholdValue !== null ? fusionScoreValue <= sellThresholdValue : null,
      note: "fusion_score <= sell_threshold 才能形成 SELL。"
    },
    {
      key: "fusion-confidence",
      label: "融合置信度门",
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
          ? "当前快照未提供最小融合置信度阈值。"
          : "BUY 需要先通过融合置信度门。"
    },
    {
      key: "tech-buy-gate",
      label: "技术轨 BUY 条件",
      current: techTrackScoreValue === null ? _localizeDynamicText(decision.techSignal) : _formatSigned(techTrackScoreValue),
      threshold: techTrackEnabled ? "> 0" : "关闭",
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
          ? "技术轨 BUY 门已关闭。"
          : techGateReasons.length > 0
          ? techGateReasons.map(_humanizeGateReason).join("；")
          : `当前技术轨方向 ${_localizeTrackBias(decision.techSignal)}。`
    },
    {
      key: "context-buy-gate",
      label: "环境轨 BUY 条件",
      current: contextTrackScoreValue === null ? _localizeDynamicText(decision.contextSignal) : _formatSigned(contextTrackScoreValue),
      threshold: contextTrackEnabled ? "> 0" : "关闭",
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
          ? "环境轨 BUY 门已关闭。"
          : contextGateReasons.length > 0
          ? contextGateReasons.map(_humanizeGateReason).join("；")
          : `当前环境轨方向 ${_localizeTrackBias(decision.contextSignal)}。`
    },
  ];
  const decisionSummaryLine =
    fusionScoreValue !== null && buyThresholdValue !== null && sellThresholdValue !== null
      ? fusionScoreValue < buyThresholdValue
        ? `未买入：融合分 ${fusionScoreValue.toFixed(4)} < 买入阈值 ${buyThresholdValue.toFixed(4)}`
        : fusionScoreValue <= sellThresholdValue
        ? `已触发卖出：融合分 ${fusionScoreValue.toFixed(4)} <= 卖出阈值 ${sellThresholdValue.toFixed(4)}`
        : `保持观望：融合分 ${fusionScoreValue.toFixed(4)} 位于阈值区间内`
      : "当前快照缺少融合阈值，无法生成一句话门控结论";
  const buyGapValue =
    fusionScoreValue !== null && buyThresholdValue !== null ? buyThresholdValue - fusionScoreValue : null;
  const sellGapValue =
    fusionScoreValue !== null && sellThresholdValue !== null ? fusionScoreValue - sellThresholdValue : null;
  const gateDeltaLine =
    fusionScoreValue !== null && buyThresholdValue !== null && fusionScoreValue < buyThresholdValue
      ? `离买入线还差 ${buyGapValue?.toFixed(4)}`
      : fusionScoreValue !== null && sellThresholdValue !== null && fusionScoreValue <= sellThresholdValue
      ? `已低于卖出线 ${Math.abs(sellGapValue ?? 0).toFixed(4)}`
      : fusionScoreValue !== null && buyThresholdValue !== null && sellThresholdValue !== null
      ? `当前位于买卖阈值之间，距买入线 ${buyGapValue?.toFixed(4)}`
      : "当前快照缺少完整阈值，暂时无法计算距离。";
  const chainBlockingStage =
    vetoes.length > 0
      ? "Veto 否决层"
      : finalActionForChain === "BUY"
      ? "全部门控通过"
      : weightedThresholdAction === "SELL" && finalActionForChain !== "SELL"
      ? "SELL 优先门"
      : weightedGateAction !== weightedThresholdAction
      ? "加权门控层"
      : weightedThresholdAction === "HOLD"
      ? "融合阈值层"
      : "规则融合层";
  const driverSummaryLine =
    fusionScoreValue !== null && buyThresholdValue !== null && sellThresholdValue !== null
      ? fusionScoreValue < buyThresholdValue && fusionScoreValue > sellThresholdValue
        ? `本次不是被单一维度直接否决，而是技术轨与环境轨先完成组聚合，再形成融合分 ${fusionScoreValue.toFixed(4)}。该分值仍落在买卖阈值之间，最终停在 ${chainBlockingStage}，所以动作仍是 ${localizeDecisionCode(finalActionForChain)}。`
        : fusionScoreValue >= buyThresholdValue
        ? `融合分 ${fusionScoreValue.toFixed(4)} 已达到买入阈值 ${buyThresholdValue.toFixed(4)}，当前链路没有在阈值层阻断。`
        : `融合分 ${fusionScoreValue.toFixed(4)} 已低于卖出阈值 ${sellThresholdValue.toFixed(4)}，当前需要重点查看 ${chainBlockingStage} 是否继续放行 ${localizeDecisionCode(finalActionForChain)}。`
      : "当前快照缺少完整阈值，暂时无法明确定位阻断阶段。";
  const fusionExplainerLine =
    fusionScoreValue !== null
      ? `双轨融合按 技术轨 ${_formatSigned(techTrackScoreValue)} × ${(Number(fusionBreakdown.tech_weight_norm ?? 0) * 100).toFixed(1)}% 与 环境轨 ${_formatSigned(contextTrackScoreValue)} × ${(Number(fusionBreakdown.context_weight_norm ?? 0) * 100).toFixed(1)}% 计算，得到融合分 ${fusionScoreValue.toFixed(4)}。`
      : "当前快照缺少融合分，无法展开双轨合成说明。";
  const finalDecisionChainLine = `动作链路：Veto ${vetoes.length > 0 ? "命中" : "未命中"} -> 核心规则 ${localizeDecisionCode(coreRuleAction)} -> 加权阈值 ${localizeDecisionCode(weightedThresholdAction)} -> 加权门控 ${localizeDecisionCode(weightedGateAction)} -> 最终 ${localizeDecisionCode(finalActionForChain)}。`;
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
    buyGapValue === null ? "--" : buyGapValue <= 0 ? "已达线" : buyGapValue.toFixed(4);
  const sellGapDisplay =
    sellGapValue === null ? "--" : sellGapValue <= 0 ? "已破线" : sellGapValue.toFixed(4);
  const dominantContributionTrack =
    Math.abs(technicalContribution) === Math.abs(contextContribution)
      ? "均衡"
      : Math.abs(technicalContribution) > Math.abs(contextContribution)
      ? "技术轨"
      : "环境轨";

  return (
    <div>
      <PageHeader
        eyebrow="信号"
        title={`信号详情 #${decision.id}`}
        description={`${decision.stockCode} ${decision.stockName || ""} · ${localizeDecisionCode(decision.action)} · ${_localizeStatus(decision.status)}`}
        actions={
          <div className="chip-row">
            <button className="button button--secondary" type="button" onClick={() => navigate(-1)}>
              返回
            </button>
            <button
              className="button button--secondary"
              type="button"
              disabled={marketRefreshPending}
              onClick={() => {
                setMarketRefreshPending(true);
                setMarketRefreshSeq((current) => current + 1);
              }}
            >
              {marketRefreshPending ? "刷新中..." : "刷新行情"}
            </button>
            <button
              className="button button--secondary"
              type="button"
              onClick={() => navigate(decision.source === "replay" ? "/his-replay" : "/live-sim")}
            >
              {decision.source === "replay" ? "历史回放" : "实时模拟"}
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
                      <div className="signal-detail-focus-panel__eyebrow">决策结论</div>
                      <h2 className="section-card__title" style={{ marginBottom: 0 }}>
                        {`${decision.stockCode} ${decision.stockName || ""}`.trim()}
                      </h2>
                    </div>
                    <span className={_gateStatusClass(decision.finalAction === "BUY" ? true : decision.finalAction === "SELL" ? false : null)}>
                      {localizeDecisionCode(decision.finalAction)}
                    </span>
                  </div>
                  <div className="signal-detail-focus-panel__headline">{decisionSummaryLine}</div>
                  <div className="signal-detail-focus-panel__supporting">
                    <div>{`决策点 ${decision.checkpointAt} · ${localizeDecisionCode(decision.status)} · ${localizeStrategyMode(decision.strategyMode)}`}</div>
                    <div>{`规则层：技术轨${_localizeTrackBias(decision.techSignal)} + 环境轨${_localizeTrackBias(decision.contextSignal)}。`}</div>
                    <div>
                      {`动作链路：核心规则 ${localizeDecisionCode(coreRuleAction)} -> 加权阈值 ${localizeDecisionCode(weightedThresholdAction)} -> 加权门控 ${localizeDecisionCode(weightedGateAction)} -> 最终 ${localizeDecisionCode(finalActionForChain)}。`}
                    </div>
                    <div>
                      {`模板：配置 ${_localizeDynamicText(decision.configuredProfile)}，实际 ${_localizeDynamicText(decision.appliedProfile)}。`}
                      {decision.aiProfileSwitched === "是" ? " 已触发模板切换。" : " 未触发模板切换。"}
                    </div>
                    <div className="markdown-body" style={{ whiteSpace: "pre-wrap" }}>
                      {_localizeDynamicText(explanation.summary || "暂无结构化结论")}
                    </div>
                  </div>
                </div>
                  <div className="signal-detail-summary-grid" data-testid="decision-summary-grid">
                  <div className="signal-detail-summary-stat signal-detail-summary-stat--emphasis">
                    <span className="signal-detail-summary-stat__label">动作</span>
                    <strong className="signal-detail-summary-stat__value">{localizeDecisionCode(decision.action)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat signal-detail-summary-stat--emphasis">
                    <span className="signal-detail-summary-stat__label">核心规则</span>
                    <strong className="signal-detail-summary-stat__value">{localizeDecisionCode(coreRuleAction)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">融合分</span>
                    <strong className="signal-detail-summary-stat__value">{fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">融合置信度</span>
                    <strong className="signal-detail-summary-stat__value">{fusionConfidenceValue === null ? "--" : fusionConfidenceValue.toFixed(4)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">技术分</span>
                    <strong className="signal-detail-summary-stat__value">{decision.techScore}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">环境分</span>
                    <strong className="signal-detail-summary-stat__value">{decision.contextScore}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">策略模式</span>
                    <strong className="signal-detail-summary-stat__value">{localizeStrategyMode(decision.strategyMode)}</strong>
                  </div>
                  <div className="signal-detail-summary-stat">
                    <span className="signal-detail-summary-stat__label">{positionMetricLabel}</span>
                    <strong className="signal-detail-summary-stat__value">{positionMetricValue}</strong>
                  </div>
                </div>
              </div>
            </section>

            <section>
              <div className="signal-detail-split-layout signal-detail-split-layout--gates" data-testid="gate-split-layout">
                <div className="signal-detail-focus-panel" data-testid="gate-focus-panel">
                  <div className="signal-detail-focus-panel__eyebrow-row">
                    <div>
                      <div className="signal-detail-focus-panel__eyebrow">门控检查</div>
                      <h2 className="section-card__title" style={{ marginBottom: 0 }}>为什么停在这里</h2>
                    </div>
                    <span className={_gateStatusClass(gateRows.every((item) => item.status !== false) ? true : false)}>
                      {localizeDecisionCode(decision.ruleHit)}
                    </span>
                  </div>
                  <div className="signal-detail-focus-panel__headline">{decisionSummaryLine}</div>
                  <div className="signal-detail-focus-panel__supporting">
                    <div>{gateDeltaLine}</div>
                    <div>{`当前落点：加权阈值 ${localizeDecisionCode(weightedThresholdAction)} · 加权门控 ${localizeDecisionCode(weightedGateAction)}。`}</div>
                  </div>
                  <div className="signal-detail-focus-panel__metrics">
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">买入线</span>
                      <strong className="signal-detail-inline-metric__value">
                        {buyThresholdValue === null ? "--" : buyThresholdValue.toFixed(4)}
                      </strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">卖出线</span>
                      <strong className="signal-detail-inline-metric__value">
                        {sellThresholdValue === null ? "--" : sellThresholdValue.toFixed(4)}
                      </strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">距买入线</span>
                      <strong className="signal-detail-inline-metric__value">{buyGapDisplay}</strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">距卖出线</span>
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
                          <span className="signal-detail-gate-card__value-label">当前值</span>
                          <strong className="signal-detail-gate-card__value-number">{item.current}</strong>
                        </div>
                        <div className="signal-detail-gate-card__value-block">
                          <span className="signal-detail-gate-card__value-label">阈值</span>
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
                      <div className="signal-detail-focus-panel__eyebrow">阻断链路</div>
                      <h2 className="section-card__title" style={{ marginBottom: 0 }}>真实决策链路</h2>
                    </div>
                    <span className={_gateStatusClass(finalActionForChain === "BUY" ? true : false)}>
                      {chainBlockingStage}
                    </span>
                  </div>
                  <div className="signal-detail-focus-panel__headline">{driverSummaryLine}</div>
                  <div className="signal-detail-focus-panel__metrics">
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">技术票</span>
                      <strong className="signal-detail-inline-metric__value">{`${signalCount.buy}/${signalCount.sell}/${signalCount.hold}`}</strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">技术贡献和</span>
                      <strong className="signal-detail-inline-metric__value">{_formatSigned(technicalContribution)}</strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">环境贡献和</span>
                      <strong className="signal-detail-inline-metric__value">{_formatSigned(contextContribution)}</strong>
                    </div>
                    <div className="signal-detail-inline-metric">
                      <span className="signal-detail-inline-metric__label">主导轨</span>
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
                        <div className="signal-detail-track-panel__title">技术轨聚合</div>
                        <div className="signal-detail-track-panel__meta">
                          {`先按组聚合，再形成技术轨方向 ${_localizeTrackBias(decision.techSignal)} · 分值 ${_formatSigned(techTrackScoreValue)}。`}
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
                            {`组分 ${_formatSigned(item.score)} · 覆盖 ${item.coverage === null ? "--" : `${(item.coverage * 100).toFixed(1)}%`}`}
                          </div>
                          <div className="signal-detail-ranked-list__meta">{groupDominantLine(technicalDimensionRows, item.groupId || "--")}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="signal-detail-track-panel signal-detail-track-panel--context">
                    <div className="signal-detail-track-panel__head">
                      <div>
                        <div className="signal-detail-track-panel__title">环境轨聚合</div>
                        <div className="signal-detail-track-panel__meta">
                          {`先按组聚合，再形成环境轨方向 ${_localizeTrackBias(decision.contextSignal)} · 分值 ${_formatSigned(contextTrackScoreValue)}。`}
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
                            {`组分 ${_formatSigned(item.score)} · 覆盖 ${item.coverage === null ? "--" : `${(item.coverage * 100).toFixed(1)}%`}`}
                          </div>
                          <div className="signal-detail-ranked-list__meta">{groupDominantLine(contextDimensionRows, item.groupId || "--")}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="signal-detail-track-panel">
                    <div className="signal-detail-track-panel__head">
                      <div>
                        <div className="signal-detail-track-panel__title">双轨融合</div>
                        <div className="signal-detail-track-panel__meta">技术轨与环境轨先按权重融合，再进入阈值与门控。</div>
                      </div>
                    </div>
                    <ul className="signal-detail-ranked-list">
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">技术轨输入</span>
                          <strong className="signal-detail-ranked-list__value">{`${_formatSigned(techTrackScoreValue)} × ${(Number(fusionBreakdown.tech_weight_norm ?? 0) * 100).toFixed(1)}%`}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{`原始权重 ${String(fusionBreakdown.tech_weight_raw ?? "--")}，归一化后参与融合。`}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">环境轨输入</span>
                          <strong className="signal-detail-ranked-list__value">{`${_formatSigned(contextTrackScoreValue)} × ${(Number(fusionBreakdown.context_weight_norm ?? 0) * 100).toFixed(1)}%`}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{`原始权重 ${String(fusionBreakdown.context_weight_raw ?? "--")}，归一化后参与融合。`}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">融合分</span>
                          <strong className="signal-detail-ranked-list__value">{fusionScoreValue === null ? "--" : fusionScoreValue.toFixed(4)}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{`置信度 ${fusionConfidenceValue === null ? "--" : fusionConfidenceValue.toFixed(4)}，基础值 ${String(fusionBreakdown.fusion_confidence_base ?? "--")}，分歧惩罚 ${String(fusionBreakdown.divergence_penalty ?? "--")}`}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">融合结论</span>
                          <strong className="signal-detail-ranked-list__value">{`${localizeDecisionCode(weightedThresholdAction)} -> ${localizeDecisionCode(weightedGateAction)}`}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{`方向冲突 ${String(fusionBreakdown.sign_conflict ?? 0)}，技术轨 ${_localizeTrackBias(decision.techSignal)}，环境轨 ${_localizeTrackBias(decision.contextSignal)}。`}</div>
                      </li>
                    </ul>
                  </div>
                  <div className="signal-detail-track-panel">
                    <div className="signal-detail-track-panel__head">
                      <div>
                        <div className="signal-detail-track-panel__title">最终门控</div>
                        <div className="signal-detail-track-panel__meta">真正决定是否买入的，是融合分与门控链，而不是单个维度排行。</div>
                      </div>
                    </div>
                    <ul className="signal-detail-ranked-list">
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">规则层</span>
                          <strong className="signal-detail-ranked-list__value">{`${vetoes.length > 0 ? "Veto 命中" : "Veto 未命中"} -> ${localizeDecisionCode(coreRuleAction)}`}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{vetoes.length > 0 ? vetoes.map((item) => `${String(item.id || "--")} · ${_localizeDynamicText(String(item.reason || "--"))}`).join("；") : `规则命中 ${_localizeDynamicText(decision.ruleHit)}。`}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">阈值层</span>
                          <strong className="signal-detail-ranked-list__value">{localizeDecisionCode(weightedThresholdAction)}</strong>
                        </div>
                        <div className="signal-detail-ranked-list__meta">{decisionSummaryLine}</div>
                      </li>
                      <li className="signal-detail-ranked-list__item">
                        <div className="signal-detail-ranked-list__main">
                          <span className="signal-detail-ranked-list__label">最终动作</span>
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
              title="投票明细"
              summary={`${voteRows.length} 条投票，默认折叠，只在需要排查时展开。`}
              expandLabel="展开投票明细"
              collapseLabel="收起投票明细"
            >
              <div className="signal-detail-filter-row">
                {[
                  { key: "all", label: "全部" },
                  { key: "technical", label: "技术" },
                  { key: "context", label: "环境" },
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
                  { key: "all", label: "全部贡献" },
                  { key: "positive", label: "正贡献" },
                  { key: "negative", label: "负贡献" },
                  { key: "actionable", label: "只看非 HOLD" },
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
                headers={["轨道", "主体", "信号", "权重", "贡献", "依据"]}
                coreIndexes={[0, 1, 2, 4]}
                emptyText="当前筛选下没有投票明细"
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
              title="审计模式"
              summary="结构化依据、参数快照与原始模型文本，默认折叠，仅在复盘或排查时展开。"
              expandLabel="展开审计模式"
              collapseLabel="收起审计模式"
            >
              {basisList.length > 0 ? (
                <div className="summary-item">
                  <div className="summary-item__title">原始依据链路</div>
                  <ul className="insight-list">
                    {basisList.map((item, index) => (
                      <li key={`basis-line-${index}`}>{_localizeDynamicText(item)}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div className="signal-detail-audit-stack">
                <div>
                  <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>决策指标</h3>
                  <div className="signal-detail-audit-groups">
                    {decisionMetricGroups.map((group) => (
                      <div className="signal-detail-audit-group" key={group.key}>
                        <div className="signal-detail-audit-group__header">
                          <div>
                            <div className="signal-detail-audit-group__title">{group.label}</div>
                            <div className="signal-detail-audit-group__note">{group.note}</div>
                          </div>
                          <span className="signal-detail-chip signal-detail-chip--neutral">{`${group.rows.length} 项`}</span>
                        </div>
                        <CompactDataTable
                          isCompactLayout={isCompactLayout}
                          headers={["参数", "值", "来源", "计算方式"]}
                          coreIndexes={[0, 1, 2]}
                          emptyText="暂无决策指标"
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
                    <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>运行参数快照</h3>
                    <div className="signal-detail-audit-groups">
                      {executionThresholdRows.length > 0 ? (
                        <div className="signal-detail-audit-group">
                          <div className="signal-detail-audit-group__header">
                            <div>
                              <div className="signal-detail-audit-group__title">执行阈值</div>
                              <div className="signal-detail-audit-group__note">直接影响买入、卖出与仓位约束的生效阈值。</div>
                            </div>
                            <span className="signal-detail-chip signal-detail-chip--neutral">{`${executionThresholdRows.length} 项`}</span>
                          </div>
                          <CompactDataTable
                            isCompactLayout={isCompactLayout}
                            headers={["执行阈值", "值", "来源", "计算方式"]}
                            coreIndexes={[0, 1, 2]}
                            emptyText="暂无执行阈值"
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
                              <div className="signal-detail-audit-group__title">买入门控阈值</div>
                              <div className="signal-detail-audit-group__note">只有 BUY 候选动作才会继续检查的最小分值与最小置信度门槛。</div>
                            </div>
                            <span className="signal-detail-chip signal-detail-chip--neutral">{`${buyGateThresholdRows.length} 项`}</span>
                          </div>
                          <CompactDataTable
                            isCompactLayout={isCompactLayout}
                            headers={["买入门控阈值", "值", "来源", "计算方式"]}
                            coreIndexes={[0, 1, 2]}
                            emptyText="暂无买入门控阈值"
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
                  <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>技术指标</h3>
                  <CompactDataTable
                    isCompactLayout={isCompactLayout}
                    headers={["指标", "数值", "来源", "说明/计算方式"]}
                    coreIndexes={[0, 1, 2]}
                    emptyText="暂无技术指标"
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
                    <div className="summary-item__title">关键技术证据</div>
                    <ul className="insight-list">
                      {techEvidence.map((item) => (
                        <li key={item}>{_localizeDynamicText(item)}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div>
                  <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>环境指标</h3>
                  <div className="summary-item" style={{ marginBottom: "10px" }}>
                    <div className="summary-item__title">环境分计算</div>
                    <div className="summary-item__body">{_localizeDynamicText(contextScoreExplain.formula || "暂无环境分公式")}</div>
                    <div className="summary-item__body">{_localizeDynamicText(contextScoreExplain.confidenceFormula || "暂无环境置信度公式")}</div>
                    <div className="summary-item__body">
                      {`组件和=${String(contextScoreExplain.componentSum ?? "0")}，最终环境分=${contextScoreExplain.finalScore || decision.contextScore}`}
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
                    headers={["环境因子", "分值", "说明"]}
                    coreIndexes={[0, 1]}
                    emptyText="暂无环境指标"
                    rows={environmentRows.map((item, index) => ({
                      key: `ctx-${index}`,
                      cells: [_localizeEnvComponentName(item.factor), item.score, _localizeDynamicText(item.reason)],
                    }))}
                  />
                </div>

                {dedupedEnvironmentParameterRows.length > 0 ? (
                  <div>
                    <h3 className="section-card__title" style={{ fontSize: "1.05rem" }}>环境参数</h3>
                    <CompactDataTable
                      isCompactLayout={isCompactLayout}
                      headers={["环境参数", "值", "来源", "计算方式"]}
                      coreIndexes={[0, 1, 2]}
                      emptyText="暂无环境参数"
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
                    <div className="summary-item__title">关键环境证据</div>
                    <ul className="insight-list">
                      {contextEvidence.map((item) => (
                        <li key={item}>{_localizeDynamicText(item)}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="summary-item">
                  <div className="summary-item__title">原始模型文本</div>
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
