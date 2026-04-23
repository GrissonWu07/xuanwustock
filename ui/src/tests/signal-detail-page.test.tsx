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
    expect(screen.getByText("贡献拆解")).toBeInTheDocument();
    expect(screen.getByText("投票明细")).toBeInTheDocument();
    expect(screen.getByText("审计模式")).toBeInTheDocument();
    expect(screen.getAllByText(/未买入：融合分/).length).toBeGreaterThan(0);
    expect(screen.getByText("规则层：技术轨偏空 + 环境轨偏多。")).toBeInTheDocument();
    expect(screen.getAllByText("动作链路：核心规则 Hold -> 加权阈值 Hold -> 加权门控 Hold -> 最终 Hold。").length).toBeGreaterThan(0);
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
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
    expect(screen.getByText("双轨融合模式")).toBeInTheDocument();
    expect(screen.queryByText("阈值参数")).not.toBeInTheDocument();
    expect(screen.queryByText("技术信号")).not.toBeInTheDocument();
    expect(screen.queryByText("环境信号")).not.toBeInTheDocument();
  });

  it("uses split desktop layouts for gate and contribution sections", async () => {
    renderSignalDetailPage();

    const gateSplit = await screen.findByTestId("gate-split-layout");
    const contributionSplit = screen.getByTestId("contribution-split-layout");

    expect(gateSplit).toHaveClass("signal-detail-split-layout");
    expect(contributionSplit).toHaveClass("signal-detail-split-layout");
  });
});
