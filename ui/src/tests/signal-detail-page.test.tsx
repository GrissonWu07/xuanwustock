import { fireEvent, render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { SignalDetailPage } from "../features/quant/signal-detail-page";

const mockPayload = {
  updatedAt: "2026-04-23 16:45:00",
  analysis: "analysis",
  reasoning: "reasoning",
  explanation: {
    summary: "结构化结论",
    basis: ["basis-1"],
    techEvidence: ["tech-evidence"],
    contextEvidence: ["context-evidence"],
    thresholdEvidence: [],
    contextScoreExplain: {
      formula: "环境轨分值公式",
      confidenceFormula: "环境轨置信度公式",
      componentBreakdown: [],
      componentSum: 0.033826,
      finalScore: "0.033826",
    },
    original: {
      analysis: "ONLY_IN_AUDIT",
      reasoning: "ONLY_IN_AUDIT_REASONING",
    },
  },
  decision: {
    id: "8535",
    source: "live",
    stockCode: "002463",
    stockName: "沪电股份",
    action: "HOLD",
    status: "observed",
    decisionType: "dual_track_weighted_hold",
    confidence: "0.658724",
    positionSizePct: "0.0",
    techScore: "-0.008843",
    contextScore: "0.033826",
    checkpointAt: "2026-04-23 16:39:45",
    createdAt: "2026-04-23 08:39:45",
    analysisTimeframe: "30m",
    strategyMode: "auto",
    marketRegime: "牛市",
    fundamentalQuality: "中性",
    riskStyle: "稳重",
    autoInferredRiskStyle: "稳重",
    techSignal: "SELL",
    contextSignal: "BUY",
    resonanceType: "neutral",
    ruleHit: "neutral_hold",
    finalAction: "HOLD",
    finalReason: "final reason",
    positionRatio: "0.0",
    configuredProfile: "积极 (aggressive_v23)",
    appliedProfile: "保守 (conservative_v23) v2",
    aiDynamicStrategy: "hybrid",
    aiDynamicStrength: "0.5",
    aiDynamicLookback: "48",
    aiProfileSwitched: "是",
  },
  techVotes: [],
  contextVotes: [
    {
      factor: "source_prior",
      signal: "BUY",
      score: "0.0410",
      reason: "context reason",
    },
  ],
  technicalIndicators: [
    {
      name: "当前价",
      value: "106.62",
      source: "reasoning",
      note: "latest price",
    },
  ],
  effectiveThresholds: [],
  voteOverview: {
    voterCount: 2,
    technicalVoterCount: 1,
    contextVoterCount: 1,
    formula: "",
    technicalAggregation: "",
    contextAggregation: "",
    rows: [
      {
        track: "technical",
        voter: "trend_direction",
        signal: "BUY",
        score: "1.0",
        weight: "0.9620",
        contribution: "0.0884",
        reason: "ONLY_IN_VOTE_TABLE",
        calculation: "calculation",
      },
      {
        track: "context",
        voter: "source_prior",
        signal: "BUY",
        score: "0.28",
        weight: "0.6782",
        contribution: "0.0410",
        reason: "context contribution",
        calculation: "calculation",
      },
    ],
  },
  parameterDetails: [
    {
      name: "技术轨方向",
      value: "偏空",
      source: "technical_breakdown.track.score",
      derivation: "技术轨方向由 track score 的正负号映射得到。",
    },
    {
      name: "环境轨方向",
      value: "偏多",
      source: "context_breakdown.track.score",
      derivation: "环境轨方向由 track score 的正负号映射得到。",
    },
    {
      name: "AI动态调整模式",
      value: "hybrid",
      source: "sim_scheduler_config.ai_dynamic_strategy",
      derivation: "AI 动态调整模式控制模板/权重是否可按市场动态放大。",
    },
    {
      name: "AI动态档位",
      value: "risk_on",
      source: "strategy_profile.dynamic_strategy.overlay_regime",
      derivation: "AI 动态层将市场状态映射到 risk_on / neutral / risk_off。",
    },
    {
      name: "AI动态调整.fusion_buy_threshold",
      value: "0.4300 -> 0.3900 (Δ-0.0400)",
      source: "strategy_profile.dynamic_strategy.adjustments",
      derivation: "risk_on 降低 BUY 触发阈值",
    },
    {
      name: "AI动态调整.sell_precedence_gate",
      value: "-0.3400 -> -0.3800 (Δ-0.0400)",
      source: "strategy_profile.dynamic_strategy.adjustments",
      derivation: "risk_on 提高强卖覆盖门槛",
    },
    {
      name: "双轨融合模式",
      value: "hybrid",
      source: "fusion_breakdown.mode",
      derivation: "双轨融合模式决定规则层与加权层如何合并。",
    },
    {
      name: "市场",
      value: "CN",
      source: "scheduler",
      derivation: "market",
    },
    {
      name: "阈值.buy_threshold",
      value: "0.8773",
      source: "threshold",
      derivation: "buy",
    },
    {
      name: "阈值.sell_threshold",
      value: "-0.1562",
      source: "threshold",
      derivation: "sell",
    },
    {
      name: "阈值.max_position_ratio",
      value: "0.5",
      source: "threshold",
      derivation: "max position",
    },
    {
      name: "阈值.allow_pyramiding",
      value: "False",
      source: "threshold",
      derivation: "allow pyramiding",
    },
    {
      name: "阈值.confirmation",
      value: "30分钟信号确认",
      source: "threshold",
      derivation: "confirmation",
    },
    {
      name: "阈值.min_fusion_confidence",
      value: "0.6200",
      source: "threshold",
      derivation: "minimum fusion confidence for buy",
    },
    {
      name: "阈值.min_tech_score_for_buy",
      value: "0.0800",
      source: "threshold",
      derivation: "minimum tech score for buy",
    },
    {
      name: "阈值.min_context_score_for_buy",
      value: "0.1000",
      source: "threshold",
      derivation: "minimum context score for buy",
    },
    {
      name: "阈值.min_tech_confidence_for_buy",
      value: "0.5800",
      source: "threshold",
      derivation: "minimum tech confidence for buy",
    },
    {
      name: "阈值.min_context_confidence_for_buy",
      value: "0.6200",
      source: "threshold",
      derivation: "minimum context confidence for buy",
    },
    {
      name: "阈值.divergence",
      value: "0.0012",
      source: "threshold",
      derivation: "should not be shown in runtime threshold panel",
    },
  ],
  aiMonitor: {
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
  },
  strategyProfile: {
    explainability: {
      technical_breakdown: {
        groups: [
          { id: "trend", track_contribution: 0.099912, score: 0.410909, coverage: 0.733333 },
          { id: "momentum", track_contribution: 0.061856, score: 0.330864, coverage: 0.841115 },
          { id: "volume_confirmation", track_contribution: 0.042832, score: 0.2, coverage: 0.485719 },
          { id: "volatility_risk", track_contribution: -0.213443, score: -0.6, coverage: 0.471708 },
        ],
        dimensions: [
          { id: "trend_direction", track_contribution: 0.088417, score: 1.0, reason: "trend up" },
          { id: "price_vs_ma20", track_contribution: 0.075155, score: 1.0, reason: "price above ma20" },
          { id: "macd_level", track_contribution: 0.059002, score: 0.95, reason: "macd positive" },
          { id: "boll_position", track_contribution: -0.213443, score: -0.6, reason: "boll high" },
          { id: "ma_alignment", track_contribution: -0.063661, score: -0.8, reason: "ma weak" },
          { id: "rsi_zone", track_contribution: -0.023542, score: -0.4, reason: "rsi hot" },
        ],
        track: { score: -0.008843, confidence: 0.607384, available: true, track_unavailable: false },
      },
      context_breakdown: {
        groups: [
          { id: "market_structure", track_contribution: 0.02004, score: 0.085187, coverage: 1.0 },
          { id: "risk_account", track_contribution: -0.034901, score: -0.08, coverage: 0.5263 },
          { id: "tradability_timing", track_contribution: 0.007728, score: 0.042414, coverage: 1.0 },
          { id: "source_execution", track_contribution: 0.040959, score: 0.28, coverage: 0.407474 },
        ],
        dimensions: [
          { id: "source_prior", track_contribution: 0.040959, score: 0.28, reason: "source prior" },
          { id: "price_structure", track_contribution: 0.012198, score: 0.14, reason: "bull stack" },
          { id: "momentum", track_contribution: 0.007842, score: 0.12, reason: "context momentum" },
          { id: "risk_balance", track_contribution: -0.034901, score: -0.08, reason: "risk high" },
        ],
        track: { score: 0.033826, confidence: 0.706667, available: true, track_unavailable: false },
      },
      fusion_breakdown: {
        mode: "hybrid",
        fusion_score: 0.017825,
        fusion_confidence: 0.658724,
        buy_threshold_eff: 0.8773,
        sell_threshold_eff: -0.1562,
        weighted_threshold_action: "HOLD",
        weighted_action_raw: "HOLD",
        weighted_gate_fail_reasons: [],
        tech_enabled: true,
        context_enabled: true,
        core_rule_action: "HOLD",
        final_action: "HOLD",
      },
      vetoes: [],
      decision_path: [
        { step: "veto_first", matched: "false", detail: "no_veto" },
        { step: "mode", matched: "hybrid", detail: "hybrid_matrix" },
      ],
    },
  },
};

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      media: "(max-width: 1200px)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => mockPayload,
  } as Response);
});

function renderSignalDetailPage() {
  const router = createMemoryRouter(
    [{ path: "/signal-detail/:signalId", element: <SignalDetailPage /> }],
    { initialEntries: ["/signal-detail/8535?source=live"] },
  );

  render(<RouterProvider router={router} />);
}

describe("SignalDetailPage", () => {
  it("renders the decision-first sections for signal detail", async () => {
    renderSignalDetailPage();

    expect(await screen.findByText("门控检查")).toBeInTheDocument();
    expect(screen.getByText("阻断链路")).toBeInTheDocument();
    expect(screen.getByText("投票明细")).toBeInTheDocument();
    expect(screen.getByText("审计模式")).toBeInTheDocument();
    expect(screen.getAllByText(/未买入：融合分/).length).toBeGreaterThan(0);
    expect(screen.getByText("策略：保守 (conservative_v23) v2 · Auto · 模板已切换")).toBeInTheDocument();
    expect(screen.getByText("市场：牛市 · 风格 稳重 · 基本面 中性")).toBeInTheDocument();
    expect(screen.getByText("双轨：技术偏空(-0.0088) · 环境偏多(+0.0338) · 置信度 0.6587")).toBeInTheDocument();
    expect(screen.getByText("链路：核心 Hold -> 加权 Hold -> 门控 Hold -> 最终 Hold")).toBeInTheDocument();
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
    expect(screen.queryByText("建议保持仓位")).not.toBeInTheDocument();
  });

  it("keeps vote details and audit text collapsed until expanded", async () => {
    renderSignalDetailPage();

    await screen.findByText("投票明细");
    expect(screen.queryByText("ONLY_IN_VOTE_TABLE")).not.toBeInTheDocument();
    expect(screen.queryByText("ONLY_IN_AUDIT")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开投票明细" }));
    fireEvent.click(screen.getByRole("button", { name: "展开审计模式" }));

    expect(await screen.findByText("ONLY_IN_VOTE_TABLE")).toBeInTheDocument();
    expect(screen.getByText("ONLY_IN_AUDIT")).toBeInTheDocument();
    expect(screen.getByText("运行参数快照")).toBeInTheDocument();
    expect(screen.getByText("技术轨方向")).toBeInTheDocument();
    expect(screen.getByText("环境轨方向")).toBeInTheDocument();
    expect(screen.getByText("AI动态调整模式")).toBeInTheDocument();
    expect(screen.getByText("AI动态调参")).toBeInTheDocument();
    expect(screen.getByText("AI动态调整.fusion_buy_threshold")).toBeInTheDocument();
    expect(screen.getByText("0.4300 -> 0.3900 (Δ-0.0400)")).toBeInTheDocument();
    expect(screen.getByText("AI动态调整.sell_precedence_gate")).toBeInTheDocument();
    expect(screen.getByText("双轨融合模式")).toBeInTheDocument();
    expect(screen.getAllByText(/技术轨/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/环境轨/).length).toBeGreaterThan(0);
    expect(screen.getByText("策略与运行态")).toBeInTheDocument();
    expect(screen.getAllByText("执行阈值").length).toBeGreaterThan(0);
    expect(screen.getAllByText("买入门控阈值").length).toBeGreaterThan(0);
    expect(screen.getByText(/BUY最小融合置信度/)).toBeInTheDocument();
    expect(screen.queryByText("阈值.divergence")).not.toBeInTheDocument();
    expect(screen.queryByText("阈值参数")).not.toBeInTheDocument();
    expect(screen.queryByText("技术信号")).not.toBeInTheDocument();
    expect(screen.queryByText("环境信号")).not.toBeInTheDocument();
  });

  it("uses split desktop layouts for decision, gate, and contribution sections", async () => {
    renderSignalDetailPage();

    const decisionSplit = await screen.findByTestId("decision-split-layout");
    const gateSplit = await screen.findByTestId("gate-split-layout");
    const contributionSplit = screen.getByTestId("contribution-split-layout");
    const decisionHeroPanel = screen.getByTestId("decision-hero-panel");
    const decisionSummaryGrid = screen.getByTestId("decision-summary-grid");
    const gateFocusPanel = screen.getByTestId("gate-focus-panel");
    const gateCardGrid = screen.getByTestId("gate-card-grid");
    const contributionOverviewPanel = screen.getByTestId("contribution-overview-panel");
    const contributionTrackGrid = screen.getByTestId("contribution-track-grid");

    expect(decisionSplit).toHaveClass("signal-detail-split-layout");
    expect(gateSplit).toHaveClass("signal-detail-split-layout");
    expect(contributionSplit).toHaveClass("signal-detail-split-layout");
    expect(decisionHeroPanel).toHaveClass("signal-detail-focus-panel");
    expect(decisionSummaryGrid).toHaveClass("signal-detail-summary-grid");
    expect(gateFocusPanel).toHaveClass("signal-detail-focus-panel");
    expect(gateCardGrid).toHaveClass("signal-detail-gate-grid");
    expect(contributionOverviewPanel).toHaveClass("signal-detail-focus-panel");
    expect(contributionTrackGrid).toHaveClass("signal-detail-contribution-grid");
    expect(screen.getByText("技术轨聚合")).toBeInTheDocument();
    expect(screen.getByText("环境轨聚合")).toBeInTheDocument();
    expect(screen.getByText("双轨融合")).toBeInTheDocument();
    expect(screen.getByText("最终门控")).toBeInTheDocument();
    expect(screen.queryByText("Top 3 正贡献")).not.toBeInTheDocument();
    expect(screen.queryByText("Top 3 负贡献")).not.toBeInTheDocument();
  });

  it("renders SELL final action with the sell action color instead of gate failure color", async () => {
    const sellPayload = JSON.parse(JSON.stringify(mockPayload));
    sellPayload.decision.action = "SELL";
    sellPayload.decision.finalAction = "SELL";
    sellPayload.strategyProfile.explainability.fusion_breakdown.final_action = "SELL";
    sellPayload.strategyProfile.explainability.fusion_breakdown.core_rule_action = "SELL";
    sellPayload.strategyProfile.explainability.fusion_breakdown.weighted_threshold_action = "SELL";
    sellPayload.strategyProfile.explainability.fusion_breakdown.weighted_action_raw = "SELL";

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => sellPayload,
    } as Response);

    renderSignalDetailPage();

    expect(await screen.findByTestId("final-action-chip")).toHaveClass("signal-detail-chip--action-sell");
    expect(screen.getByTestId("final-action-chip")).not.toHaveClass("signal-detail-chip--fail");
    expect(screen.getByTestId("chain-stage-chip")).toHaveClass("signal-detail-chip--action-sell");
    expect(screen.getAllByText(/卖出：核心规则触发/).length).toBeGreaterThan(0);
    expect(screen.getByText("链路：核心 Sell -> 加权 Sell -> 门控 Sell -> 最终 Sell")).toBeInTheDocument();
    expect(screen.queryByText(/未买入：融合分/)).not.toBeInTheDocument();
  });

  it("labels held-stock BUY intent as position add and shows add gate details", async () => {
    const addPayload = JSON.parse(JSON.stringify(mockPayload));
    addPayload.decision.action = "BUY";
    addPayload.decision.finalAction = "BUY";
    addPayload.decision.executionIntent = "position_add";
    addPayload.decision.positionSizePct = "14.8";
    addPayload.strategyProfile.position_add_gate = {
      intent: "position_add",
      status: "passed",
      current_position_pct: 5.2,
      target_position_pct: 20,
      add_position_delta_pct: 14.8,
      max_position_pct: 30,
      reasons: ["已有浮盈 4.00% >= 2.00%"],
    };
    addPayload.parameterDetails.push(
      {
        name: "执行语义",
        value: "加仓/增持",
        source: "strategy_profile.position_add_gate.intent",
        derivation: "持仓 BUY 显示为加仓/增持。",
      },
      {
        name: "加仓门控",
        value: "通过",
        source: "strategy_profile.position_add_gate.status",
        derivation: "加仓门控通过后才允许持仓 BUY 执行。",
      },
    );

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => addPayload,
    } as Response);

    renderSignalDetailPage();

    expect((await screen.findAllByText("增持")).length).toBeGreaterThan(0);
    expect(screen.getByText("建议加仓比例(%)")).toBeInTheDocument();
    expect(screen.getAllByText("14.8").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "展开审计模式" }));

    expect(await screen.findByText("执行语义")).toBeInTheDocument();
    expect(screen.getByText("加仓门控")).toBeInTheDocument();
    expect(screen.getByText("加仓/增持")).toBeInTheDocument();
  });
});
