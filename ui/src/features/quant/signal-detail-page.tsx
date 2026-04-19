import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { t } from "../../lib/i18n";
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
  };
  techVotes: VoteRow[];
  contextVotes: VoteRow[];
  technicalIndicators: IndicatorRow[];
  effectiveThresholds: ThresholdRow[];
  voteOverview?: VoteOverview;
  parameterDetails?: ParameterDetailRow[];
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

function _safeValue(...values: Array<string | undefined | null>): string {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) {
      return text;
    }
  }
  return "--";
}

const ENV_COMPONENT_KEY_MAP: Record<string, string> = {
  source_prior: "Env component:source_prior",
  trend_regime: "Env component:trend_regime",
  price_structure: "Env component:price_structure",
  momentum: "Env component:momentum",
  risk_balance: "Env component:risk_balance",
  liquidity: "Env component:liquidity",
  session: "Env component:session",
};

const THRESHOLD_KEY_MAP: Record<string, string> = {
  buy_threshold: "Threshold:buy_threshold",
  sell_threshold: "Threshold:sell_threshold",
  max_position_ratio: "Threshold:max_position_ratio",
  allow_pyramiding: "Threshold:allow_pyramiding",
  confirmation: "Threshold:confirmation",
};

function _localizeEnvComponentName(name: string): string {
  const normalized = String(name || "").trim().toLowerCase();
  const key = ENV_COMPONENT_KEY_MAP[normalized];
  return key ? t(key) : name;
}

function _localizeThresholdName(rawName: string): string {
  const text = String(rawName || "").trim();
  if (!text) {
    return text;
  }
  const pureKey = text.startsWith("阈值.") ? text.slice(3) : text;
  const localized = THRESHOLD_KEY_MAP[pureKey] ? t(THRESHOLD_KEY_MAP[pureKey]) : pureKey;
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

export function SignalDetailPage() {
  const navigate = useNavigate();
  const { signalId } = useParams();
  const [searchParams] = useSearchParams();
  const source = useMemo(() => (searchParams.get("source") || "auto").toLowerCase(), [searchParams]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<SignalDetailPayload>(emptyDetail);

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
      try {
        const response = await fetch(`/api/v1/quant/signals/${encodeURIComponent(id)}?source=${encodeURIComponent(source)}`, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `Request failed: ${response.status}`);
        }
        const payload = (await response.json()) as SignalDetailPayload;
        if (mounted) {
          setDetail(payload);
          setStatus("ready");
        }
      } catch (err) {
        if (mounted) {
          setStatus("error");
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    void load();
    return () => {
      mounted = false;
    };
  }, [signalId, source]);

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
  const basisList = explanation.basis ?? [];
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
  const originalAnalysis = explanation.original?.analysis || detail.analysis || "暂无分析数据";
  const originalReasoning = explanation.original?.reasoning || detail.reasoning || "暂无决策理由";
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
  const keepPositionPct = (() => {
    const actionUpper = String(decision.action || "").trim().toUpperCase();
    const raw = Number(String(decision.positionSizePct ?? "").replace("%", "").trim());
    if (actionUpper === "HOLD") {
      return "维持当前仓位（不变）";
    }
    if (!Number.isFinite(raw)) {
      return "--";
    }
    const ratio = Math.max(0, Math.min(100, raw));
    if (actionUpper === "SELL") {
      const keep = Math.max(0, 100 - ratio);
      return String(Number(keep.toFixed(2)));
    }
    if (actionUpper === "BUY") {
      return String(Number(ratio.toFixed(2)));
    }
    return "--";
  })();
  const positionMetricLabel =
    String(decision.action || "").toUpperCase() === "BUY"
      ? "目标买入仓位(%)"
      : String(decision.action || "").toUpperCase() === "SELL"
      ? "建议卖出比例(%)"
      : "仓位建议(%)";

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
              onClick={() => navigate(decision.source === "replay" ? "/his-replay" : "/live-sim")}
            >
              {decision.source === "replay" ? "历史回放" : "量化模拟"}
            </button>
          </div>
        }
      />

      <div className="stack">
        <WorkbenchCard>
          <h2 className="section-card__title">决策概览</h2>

          <div className="summary-item summary-item--accent">
            <div className="summary-item__title">结论</div>
            <div className="summary-item__body">
              {`${localizeDecisionCode(decision.finalAction)} · ${localizeDecisionCode(decision.decisionType)} · 代码 ${decision.stockCode} · 决策点 ${decision.checkpointAt}`}
            </div>
            <div className="summary-item__body markdown-body" style={{ whiteSpace: "pre-wrap" }}>
              {_localizeDynamicText(explanation.summary || "暂无结构化结论")}
            </div>
          </div>

          <div className="mini-metric-grid" style={{ marginTop: "14px" }}>
            <div className="mini-metric"><div className="mini-metric__label">动作</div><div className="mini-metric__value">{localizeDecisionCode(decision.action)}</div></div>
            <div className="mini-metric"><div className="mini-metric__label">决策类型</div><div className="mini-metric__value">{localizeDecisionCode(decision.decisionType)}</div></div>
            <div className="mini-metric"><div className="mini-metric__label">策略模式</div><div className="mini-metric__value">{localizeStrategyMode(decision.strategyMode)}</div></div>
            <div className="mini-metric"><div className="mini-metric__label">置信度</div><div className="mini-metric__value">{decision.confidence}</div></div>
            <div className="mini-metric"><div className="mini-metric__label">{positionMetricLabel}</div><div className="mini-metric__value">{decision.positionSizePct}</div></div>
            <div className="mini-metric"><div className="mini-metric__label">建议保持仓位</div><div className="mini-metric__value">{keepPositionPct}</div></div>
            <div className="mini-metric"><div className="mini-metric__label">技术分</div><div className="mini-metric__value">{decision.techScore}</div></div>
            <div className="mini-metric"><div className="mini-metric__label">环境分</div><div className="mini-metric__value">{decision.contextScore}</div></div>
            <div className="mini-metric"><div className="mini-metric__label">规则命中</div><div className="mini-metric__value">{localizeDecisionCode(decision.ruleHit)}</div></div>
          </div>

          {basisList.length > 0 ? (
            <>
              <div className="card-divider" />
              <div className="summary-item">
                <div className="summary-item__title">依据链路</div>
                <ul className="insight-list">
                  {basisList.map((item) => (
                    <li key={item}>{_localizeDynamicText(item)}</li>
                  ))}
                </ul>
              </div>
            </>
          ) : null}

          <div className="card-divider" />
          <h3 className="section-card__title" style={{ fontSize: "1.1rem" }}>投票明细</h3>
          <div className="table-shell">
            <table className="table table--auto">
              <thead>
                <tr>
                  <th>维度</th>
                  <th>投票主体</th>
                  <th>投票</th>
                  <th>信号分</th>
                  <th>权重</th>
                  <th>贡献分</th>
                  <th>依据</th>
                  <th>计算</th>
                </tr>
              </thead>
              <tbody>
                {voteRows.length === 0
                  ? tableRowEmpty(8, "暂无投票明细")
                  : voteRows.map((item, index) => (
                      <tr key={`vote-${index}`}>
                        <td>{item.track === "technical" ? "技术" : "环境"}</td>
                        <td>{item.track === "context" ? _localizeEnvComponentName(item.voter) : _localizeDynamicText(item.voter)}</td>
                        <td>{localizeDecisionCode(item.signal)}</td>
                        <td>{item.score}</td>
                        <td>{item.weight}</td>
                        <td>{item.contribution}</td>
                        <td>{_localizeDynamicText(item.reason)}</td>
                        <td>{`单票贡献 = 信号分(${item.score}) × 权重(${item.weight}) = ${item.contribution}`}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>

          <div className="card-divider" />
          <h3 className="section-card__title" style={{ fontSize: "1.1rem" }}>决策指标</h3>
          <div className="table-shell">
            <table className="table table--auto">
              <thead>
                <tr><th>参数</th><th>值</th><th>来源</th><th>计算方式</th></tr>
              </thead>
              <tbody>
                {decisionParameterRows.length === 0
                  ? tableRowEmpty(4, "暂无决策指标")
                  : decisionParameterRows.map((item, index) => (
                      <tr key={`decision-${index}`}>
                        <td>{_localizeDynamicText(item.name)}</td>
                        <td>{_localizeValue(item.value)}</td>
                        <td>{_localizeSourceLabel(item.source)}</td>
                        <td>{_localizeDynamicText(item.derivation)}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
          {thresholdRows.length > 0 ? (
            <div className="table-shell" style={{ marginTop: "10px" }}>
              <table className="table table--auto">
                <thead>
                  <tr><th>阈值参数</th><th>值</th><th>来源</th><th>计算方式</th></tr>
                </thead>
                <tbody>
                  {thresholdRows.map((item, index) => (
                    <tr key={`threshold-${index}`}>
                      <td>{_localizeThresholdName(item.name)}</td>
                      <td>{_localizeValue(item.value)}</td>
                      <td>{_localizeSourceLabel(item.source)}</td>
                      <td>{_localizeDynamicText(item.derivation)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <div className="card-divider" />
          <h3 className="section-card__title" style={{ fontSize: "1.1rem" }}>技术指标</h3>
          <div className="table-shell">
            <table className="table table--auto">
              <thead>
                <tr><th>指标</th><th>数值</th><th>来源</th><th>说明/计算方式</th></tr>
              </thead>
              <tbody>
                {mergedTechnicalRows.length === 0
                  ? tableRowEmpty(4, "暂无技术指标")
                  : mergedTechnicalRows.map((item, index) => (
                      <tr key={`tech-${index}`}>
                        <td>{_localizeDynamicText(item.name)}</td>
                        <td>{_localizeValue(item.value)}</td>
                        <td>{_localizeSourceLabel(item.source)}</td>
                        <td>{_localizeDynamicText(item.detail || "--")}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
          {techEvidence.length > 0 ? (
            <div className="summary-item" style={{ marginTop: "10px" }}>
              <div className="summary-item__title">关键技术证据</div>
              <ul className="insight-list">
                {techEvidence.map((item) => (
                  <li key={item}>{_localizeDynamicText(item)}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="card-divider" />
          <h3 className="section-card__title" style={{ fontSize: "1.1rem" }}>环境指标</h3>
          <div className="summary-item">
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
          <div className="table-shell">
            <table className="table table--auto">
              <thead>
                <tr><th>环境因子</th><th>分值</th><th>说明</th></tr>
              </thead>
              <tbody>
                {environmentRows.length === 0
                  ? tableRowEmpty(3, "暂无环境指标")
                  : environmentRows.map((item, index) => (
                      <tr key={`ctx-${index}`}>
                        <td>{_localizeEnvComponentName(item.factor)}</td>
                        <td>{item.score}</td>
                        <td>{_localizeDynamicText(item.reason)}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
          {environmentParameterRows.length > 0 ? (
            <div className="table-shell" style={{ marginTop: "10px" }}>
              <table className="table table--auto">
                <thead>
                  <tr><th>环境参数</th><th>值</th><th>来源</th><th>计算方式</th></tr>
                </thead>
                <tbody>
                  {environmentParameterRows.map((item, index) => (
                    <tr key={`env-param-${index}`}>
                      <td>{_localizeDynamicText(item.name)}</td>
                      <td>{_localizeValue(item.value)}</td>
                      <td>{_localizeSourceLabel(item.source)}</td>
                      <td>{_localizeDynamicText(item.derivation)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {contextEvidence.length > 0 ? (
            <div className="summary-item" style={{ marginTop: "10px" }}>
              <div className="summary-item__title">关键环境证据</div>
              <ul className="insight-list">
                {contextEvidence.map((item) => (
                  <li key={item}>{_localizeDynamicText(item)}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="card-divider" />
          <div className="summary-item">
            <div className="summary-item__title">原始模型文本</div>
            <div className="summary-item__body markdown-body" style={{ whiteSpace: "pre-wrap" }}>{_localizeDynamicText(originalAnalysis)}</div>
            <div className="summary-item__body markdown-body" style={{ whiteSpace: "pre-wrap" }}>{_localizeDynamicText(originalReasoning)}</div>
          </div>
        </WorkbenchCard>
      </div>
    </div>
  );
}
