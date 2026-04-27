import { useEffect, useMemo, useState } from "react";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { SectionEmptyState } from "../../components/ui/section-empty";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { usePageData } from "../../lib/use-page-data";
import { t, useI18nLocale } from "../../lib/i18n";

type StrategyConfigPageProps = {
  client?: ApiClient;
};

type StrategyProfile = {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  isDefault: boolean;
  config?: Record<string, unknown>;
};

type ActionState = null | "save" | "clone" | "create";

type LocaleText = {
  zh: string;
  en: string;
};

type ParamExplain = {
  meaning: LocaleText;
  effect: LocaleText;
};

type DualTrackField = {
  key: string;
  label: string;
  type: "number" | "select";
  options?: string[];
  path: string[];
};

const BUILTIN_PROFILE_IDS = ["aggressive", "stable", "conservative"] as const;

const TECHNICAL_GROUP_DIMENSIONS: Record<string, readonly string[]> = {
  trend: ["trend_direction", "ma_alignment", "ma_slope", "price_vs_ma20"],
  momentum: ["macd_level", "macd_hist_slope", "rsi_zone", "kdj_cross"],
  volume_confirmation: ["volume_ratio", "obv_trend"],
  volatility_risk: ["atr_risk", "boll_position"],
};

const CONTEXT_GROUP_DIMENSIONS: Record<string, readonly string[]> = {
  market_structure: ["trend_regime", "price_structure", "momentum"],
  risk_account: ["risk_balance", "account_posture"],
  tradability_timing: ["liquidity", "session"],
  source_execution: ["source_prior", "execution_feedback"],
};

const TECHNICAL_GROUPS = Object.keys(TECHNICAL_GROUP_DIMENSIONS);
const CONTEXT_GROUPS = Object.keys(CONTEXT_GROUP_DIMENSIONS);
const TECHNICAL_DIMENSIONS = TECHNICAL_GROUPS.flatMap((key) => TECHNICAL_GROUP_DIMENSIONS[key]);
const CONTEXT_DIMENSIONS = CONTEXT_GROUPS.flatMap((key) => CONTEXT_GROUP_DIMENSIONS[key]);

const DIMENSION_LABEL_KEYS: Record<string, string> = {
  trend: "Group:trend",
  momentum: "Group:momentum",
  volume_confirmation: "Group:volume_confirmation",
  volatility_risk: "Group:volatility_risk",
  market_structure: "Group:market_structure",
  risk_account: "Group:risk_account",
  tradability_timing: "Group:tradability_timing",
  source_execution: "Group:source_execution",
  trend_direction: "Dimension:trend_direction",
  ma_alignment: "Dimension:ma_alignment",
  ma_slope: "Dimension:ma_slope",
  price_vs_ma20: "Dimension:price_vs_ma20",
  macd_level: "Dimension:macd_level",
  macd_hist_slope: "Dimension:macd_hist_slope",
  rsi_zone: "Dimension:rsi_zone",
  kdj_cross: "Dimension:kdj_cross",
  volume_ratio: "Dimension:volume_ratio",
  obv_trend: "Dimension:obv_trend",
  atr_risk: "Dimension:atr_risk",
  boll_position: "Dimension:boll_position",
  trend_regime: "Dimension:trend_regime",
  price_structure: "Dimension:price_structure",
  risk_balance: "Dimension:risk_balance",
  account_posture: "Dimension:account_posture",
  liquidity: "Dimension:liquidity",
  session: "Dimension:session",
  source_prior: "Dimension:source_prior",
  execution_feedback: "Dimension:execution_feedback",
};

const GROUP_TITLES: Record<string, LocaleText> = {
  trend: { zh: "趋势结构 (Trend)", en: "Trend Structure" },
  momentum: { zh: "动量 (Momentum)", en: "Momentum" },
  volume_confirmation: { zh: "量能确认 (Volume Confirmation)", en: "Volume Confirmation" },
  volatility_risk: { zh: "波动风险 (Volatility Risk)", en: "Volatility Risk" },
  market_structure: { zh: "市场结构 (Market Structure)", en: "Market Structure" },
  risk_account: { zh: "风险账户 (Risk Account)", en: "Risk Account" },
  tradability_timing: { zh: "交易时段 (Tradability Timing)", en: "Tradability Timing" },
  source_execution: { zh: "来源反馈 (Source Execution)", en: "Source Execution" },
};

const GROUP_EXPLAINS: Record<string, ParamExplain> = {
  trend: {
    meaning: { zh: "趋势结构维度，衡量方向和均线关系。", en: "Trend dimensions for direction and MA structure." },
    effect: { zh: "分类权重越高，策略越偏向顺趋势。", en: "Higher category weight makes decisions more trend-following." },
  },
  momentum: {
    meaning: { zh: "动量维度，反映加速/减速变化。", en: "Momentum dimensions for acceleration/deceleration." },
    effect: { zh: "分类权重越高，短中期拐点影响更大。", en: "Higher category weight increases turning-point impact." },
  },
  volume_confirmation: {
    meaning: { zh: "量能确认维度，判断资金是否配合方向。", en: "Volume confirmation dimensions for participation support." },
    effect: { zh: "分类权重越高，放量/缩量影响越大。", en: "Higher category weight amplifies volume expansion/shrink effects." },
  },
  volatility_risk: {
    meaning: { zh: "波动风险维度，评估追高和回撤风险。", en: "Volatility-risk dimensions for chase/drawdown risk." },
    effect: { zh: "分类权重越高，风控更保守。", en: "Higher category weight makes risk control more conservative." },
  },
  market_structure: {
    meaning: { zh: "市场结构维度，描述市场大环境。", en: "Market-structure dimensions for macro regime." },
    effect: { zh: "分类权重越高，环境判断更主导动作。", en: "Higher category weight gives more influence to context view." },
  },
  risk_account: {
    meaning: { zh: "风险账户维度，关注风险暴露和账户状态。", en: "Risk/account dimensions for exposure and posture." },
    effect: { zh: "分类权重越高，更容易收缩仓位。", en: "Higher category weight tends to reduce exposure." },
  },
  tradability_timing: {
    meaning: { zh: "交易时段维度，关注流动性和时段。", en: "Tradability/timing dimensions for liquidity and session." },
    effect: { zh: "分类权重越高，低流动时更抑制动作。", en: "Higher category weight suppresses action in poor liquidity/session." },
  },
  source_execution: {
    meaning: { zh: "来源反馈维度，关注来源先验和执行反馈。", en: "Source/execution dimensions for prior and feedback." },
    effect: { zh: "分类权重越高，历史执行结果更影响决策。", en: "Higher category weight makes execution feedback stronger." },
  },
};

const DIMENSION_EXPLAINS: Record<string, ParamExplain> = {
  trend_direction: {
    meaning: { zh: "基于收盘价与 MA20/MA60 的相对位置判断主趋势方向（如 close>MA20>MA60）。", en: "Determines trend direction from close vs MA20/MA60 (e.g. close>MA20>MA60)." },
    effect: { zh: "结构越多头（价格在关键均线上方且均线顺序健康）得分越高，结构越空头得分越低；权重越高，对最终方向影响越大。", en: "More bullish structure scores higher; more bearish structure scores lower. Higher weight means stronger directional impact." },
  },
  ma_alignment: {
    meaning: { zh: "比较短中长期均线排列（多头排列/空头排列/缠绕）。", en: "Evaluates short-mid-long MA ordering (bullish/bearish/tangled)." },
    effect: { zh: "多头排列通常加分，空头排列通常减分，缠绕接近中性；权重越高，趋势一致性影响越强。", en: "Bullish alignment usually adds score, bearish alignment subtracts, tangled is near neutral. Higher weight amplifies trend-consistency effect." },
  },
  ma_slope: {
    meaning: { zh: "衡量关键均线斜率（上行/走平/下行）反映趋势加速或减速。", en: "Measures MA slope (up/flat/down) to reflect trend acceleration/deceleration." },
    effect: { zh: "斜率上行越明显通常越加分，斜率下行越明显通常越减分；权重越高，趋势强弱变化越敏感。", en: "Stronger upward slope generally scores higher, stronger downward slope scores lower. Higher weight increases sensitivity to trend-strength changes." },
  },
  price_vs_ma20: {
    meaning: { zh: "衡量价格相对 MA20 的偏离程度，用于判断延续与回归风险。", en: "Measures distance from MA20 to evaluate continuation vs mean-reversion risk." },
    effect: { zh: "适度站上 MA20 通常偏多；远离过大可能转为追高风险；跌破 MA20 通常偏空。", en: "Moderately above MA20 is usually bullish; excessive deviation may imply chase risk; below MA20 is usually bearish." },
  },
  macd_level: {
    meaning: { zh: "同时看 DIF 与 DEA 的相对位置及其是否位于 0 轴上方（强势）或下方（弱势）。", en: "Uses DIF vs DEA and zero-axis location (above=strong, below=weak)." },
    effect: { zh: "DIF>DEA 且在 0 轴上方通常显著加分；DIF<DEA 且在 0 轴下方通常显著减分；权重越高，动量方向影响越大。", en: "DIF>DEA above zero usually adds strong positive score; DIF<DEA below zero usually subtracts strongly. Higher weight amplifies momentum-direction effect." },
  },
  macd_hist_slope: {
    meaning: { zh: "看 MACD 柱体变化速度（扩张/收敛）评估动量是否在增强。", en: "Tracks MACD histogram expansion/contraction to assess momentum strengthening." },
    effect: { zh: "红柱持续放大通常加分，绿柱持续放大通常减分；权重越高，对拐点前后的响应更快。", en: "Expanding positive bars usually add score; expanding negative bars usually subtract. Higher weight gives faster turning-point response." },
  },
  rsi_zone: {
    meaning: { zh: "根据 RSI 区间（超卖/中性/超买）判断价格强弱与过热程度。", en: "Uses RSI zones (oversold/neutral/overbought) to judge strength and overheating." },
    effect: { zh: "中高位但不过热通常偏多；过高（如 >75）偏风险；过低（如 <25）可能超卖修复；权重越高，震荡信号影响越大。", en: "Moderately high but not overheated is usually bullish; very high (e.g. >75) indicates risk; very low (e.g. <25) may indicate rebound potential. Higher weight increases oscillator impact." },
  },
  kdj_cross: {
    meaning: { zh: "使用 K 与 D 的金叉/死叉及高低位区间判断短周期拐点。", en: "Uses K/D cross and high-low zones to detect short-cycle turning points." },
    effect: { zh: "低位金叉通常加分，高位死叉通常减分；权重越高，短线拐点对动作影响越大。", en: "Golden cross in low zone usually adds score; death cross in high zone usually subtracts. Higher weight increases short-term turning impact." },
  },
  volume_ratio: {
    meaning: { zh: "比较当前量能与历史均量（量比）判断行情是否有成交支持。", en: "Compares current volume to historical baseline (volume ratio) for participation support." },
    effect: { zh: "放量上行通常加分，缩量上行或放量下跌通常减分；权重越高，量能确认作用越强。", en: "Volume-supported rise usually adds score; low-volume rise or heavy-volume drop usually subtracts. Higher weight strengthens volume confirmation." },
  },
  obv_trend: {
    meaning: { zh: "通过 OBV 趋势观察资金累计方向是否与价格方向一致。", en: "Uses OBV trend to verify whether accumulation direction agrees with price trend." },
    effect: { zh: "OBV 上行且与价格同向通常加分，出现背离通常减分；权重越高，资金行为影响越大。", en: "Rising OBV aligned with price usually adds score; divergence usually subtracts. Higher weight increases capital-flow influence." },
  },
  atr_risk: {
    meaning: { zh: "用 ATR/价格评估单位价格波动风险与止损压力。", en: "Uses ATR/price to estimate volatility risk and stop-loss pressure." },
    effect: { zh: "ATR 占比越高通常风险越大（偏减分），占比越低通常更稳定（偏加分）；权重越高，风控约束越强。", en: "Higher ATR ratio usually means higher risk (negative), lower ratio means more stability (positive). Higher weight strengthens risk control." },
  },
  boll_position: {
    meaning: { zh: "观察价格在布林上中下轨的位置，识别突破、回归或失速。", en: "Uses Bollinger band position (upper/mid/lower) to identify breakout, mean reversion, or breakdown." },
    effect: { zh: "沿上轨稳步上行可偏多，贴上轨过热或跌破中下轨偏空；权重越高，对波动区间变化越敏感。", en: "Stable walk-up near upper band can be bullish; overheated upper-band touch or break below mid/lower bands is bearish. Higher weight increases sensitivity to volatility-range changes." },
  },
  trend_regime: {
    meaning: { zh: "识别市场所处阶段（上行、震荡、下行）作为环境底色。", en: "Identifies market regime (uptrend, sideways, downtrend) as context backdrop." },
    effect: { zh: "上行环境通常给多头信号加分，下行环境通常减分；权重越高，环境方向对动作影响越大。", en: "Bullish regimes usually boost long signals, bearish regimes reduce them. Higher weight gives stronger context-direction impact." },
  },
  price_structure: {
    meaning: { zh: "从高低点结构（抬高/下移）判断市场结构是否改善。", en: "Evaluates higher-high/higher-low vs lower-high/lower-low market structure." },
    effect: { zh: "结构改善（高低点抬升）通常加分，结构走弱（高低点下移）通常减分；权重越高，结构变化影响越大。", en: "Improving structure usually adds score; weakening structure usually subtracts. Higher weight amplifies structural impact." },
  },
  momentum: {
    meaning: { zh: "评估市场/板块级动量强弱，而非单票局部波动。", en: "Measures market/sector-level momentum, not only single-symbol local moves." },
    effect: { zh: "背景动量与技术轨同向时通常加分，反向时通常减分；权重越高，环境共振影响越强。", en: "When background momentum aligns with technical track it usually adds score; conflict usually subtracts. Higher weight strengthens resonance effect." },
  },
  risk_balance: {
    meaning: { zh: "衡量风险偏好与防御需求的平衡（risk-on / risk-off）。", en: "Balances risk-on vs risk-off conditions." },
    effect: { zh: "风险偏好上升通常加分，风险收缩通常减分；权重越高，风险状态切换对最终动作影响越大。", en: "Rising risk appetite usually adds score, risk-off usually subtracts. Higher weight gives stronger impact from risk-state shifts." },
  },
  account_posture: {
    meaning: { zh: "根据可用资金、已用仓位和集中度评估账户承压能力。", en: "Uses cash, utilization, and concentration to evaluate account pressure." },
    effect: { zh: "可用资金充足通常偏加分；仓位过满/集中度过高通常减分；权重越高，对仓位建议约束越强。", en: "Ample cash usually adds score; overfilled or over-concentrated positions usually subtract. Higher weight tightens position-sizing constraints." },
  },
  liquidity: {
    meaning: { zh: "衡量成交深度与滑点风险，判断信号是否可执行。", en: "Measures depth and slippage risk to judge executability." },
    effect: { zh: "流动性好通常加分，流动性差通常减分；权重越高，低流动时更容易降级为 HOLD。", en: "Good liquidity usually adds score, poor liquidity subtracts. Higher weight increases HOLD downgrade in thin markets." },
  },
  session: {
    meaning: { zh: "根据交易时段（开盘冲击、午间低流动、尾盘波动）修正执行质量。", en: "Adjusts execution quality by session (open shock, midday thinness, close volatility)." },
    effect: { zh: "执行友好时段通常轻微加分，噪声/冲击时段通常轻微减分；权重越高，时段过滤越明显。", en: "Execution-friendly sessions mildly add score; noisy/shock sessions mildly subtract. Higher weight makes timing filter stronger." },
  },
  source_prior: {
    meaning: { zh: "根据信号来源历史稳定性与胜率给出先验可靠性评分。", en: "Assigns prior reliability by source stability and historical hit rate." },
    effect: { zh: "高质量来源通常加分，低质量来源通常减分；权重越高，来源质量影响越大。", en: "High-quality sources usually add score; low-quality sources usually subtract. Higher weight increases source-quality influence." },
  },
  execution_feedback: {
    meaning: { zh: "结合近期执行成功率、滑点与偏差，衡量策略执行闭环质量。", en: "Uses recent fill success, slippage, and deviation to evaluate execution-loop quality." },
    effect: { zh: "执行反馈好通常加分，连续失败或高滑点通常减分；权重越高，执行质量对后续决策影响越强。", en: "Good execution feedback usually adds score; repeated failures or high slippage subtract. Higher weight makes execution quality more influential." },
  },
};

const DUAL_PARAM_EXPLAINS: Record<string, ParamExplain> = {
  "track_weights.tech": {
    meaning: { zh: "技术轨在融合中的权重。", en: "Technical track weight in fusion." },
    effect: { zh: "数值越大，融合分越依赖技术轨。", en: "Larger value makes fusion rely more on technical track." },
  },
  "track_weights.context": {
    meaning: { zh: "环境轨在融合中的权重。", en: "Context track weight in fusion." },
    effect: { zh: "数值越大，融合分越依赖环境轨。", en: "Larger value makes fusion rely more on context track." },
  },
  fusion_buy_threshold: {
    meaning: { zh: "融合分触发买入阈值。", en: "Fusion score threshold for BUY." },
    effect: { zh: "越高越保守，BUY 更难触发。", en: "Higher value is more conservative for BUY." },
  },
  fusion_sell_threshold: {
    meaning: { zh: "融合分触发卖出阈值。", en: "Fusion score threshold for SELL." },
    effect: { zh: "越低越保守，SELL 更难触发。", en: "Lower value is more conservative for SELL." },
  },
  sell_precedence_gate: {
    meaning: { zh: "SELL 覆盖优先闸值。", en: "SELL precedence override gate." },
    effect: { zh: "仅当分值足够弱时才允许 SELL 强覆盖。", en: "SELL overrides only when score is weak enough." },
  },
  min_fusion_confidence: {
    meaning: { zh: "融合最小置信度门槛。", en: "Minimum fusion confidence gate." },
    effect: { zh: "低于阈值时动作会降级到 HOLD。", en: "Below threshold, action degrades to HOLD." },
  },
  min_tech_score_for_buy: {
    meaning: { zh: "BUY 的技术轨最小分。", en: "Minimum technical score for BUY." },
    effect: { zh: "技术分不足时不允许 BUY。", en: "BUY blocked if technical score is insufficient." },
  },
  min_context_score_for_buy: {
    meaning: { zh: "BUY 的环境轨最小分。", en: "Minimum context score for BUY." },
    effect: { zh: "环境分不足时不允许 BUY。", en: "BUY blocked if context score is insufficient." },
  },
  min_tech_confidence_for_buy: {
    meaning: { zh: "BUY 的技术轨最小置信度。", en: "Minimum technical confidence for BUY." },
    effect: { zh: "技术覆盖不足时不允许 BUY。", en: "BUY blocked if technical confidence is low." },
  },
  min_context_confidence_for_buy: {
    meaning: { zh: "BUY 的环境轨最小置信度。", en: "Minimum context confidence for BUY." },
    effect: { zh: "环境覆盖不足时不允许 BUY。", en: "BUY blocked if context confidence is low." },
  },
  lambda_divergence: {
    meaning: { zh: "双轨背离惩罚系数。", en: "Divergence penalty coefficient." },
    effect: { zh: "背离越大，FusionConfidence 惩罚越强。", en: "Larger divergence gives stronger confidence penalty." },
  },
  lambda_sign_conflict: {
    meaning: { zh: "符号冲突惩罚系数。", en: "Sign-conflict penalty coefficient." },
    effect: { zh: "方向相反时进一步降低置信度。", en: "Opposite directions further reduce confidence." },
  },
  sign_conflict_min_abs_score: {
    meaning: { zh: "符号冲突触发最小绝对分。", en: "Minimum abs score to trigger sign conflict." },
    effect: { zh: "过滤微小噪声，避免误惩罚。", en: "Filters tiny noise to avoid false penalty." },
  },
  buy_vol_k: {
    meaning: { zh: "BUY 阈值波动调整系数。", en: "Volatility adjustment coefficient for BUY threshold." },
    effect: { zh: "波动模式下动态改变 BUY 阈值。", en: "Dynamically adjusts BUY threshold in volatility mode." },
  },
  sell_vol_k: {
    meaning: { zh: "SELL 阈值波动调整系数。", en: "Volatility adjustment coefficient for SELL threshold." },
    effect: { zh: "波动模式下动态改变 SELL 阈值。", en: "Dynamically adjusts SELL threshold in volatility mode." },
  },
  mode: {
    meaning: { zh: "决策模式：rule_only / weighted_only / hybrid。", en: "Decision mode: rule_only / weighted_only / hybrid." },
    effect: { zh: "决定最终动作路径。", en: "Determines final action path." },
  },
  threshold_mode: {
    meaning: { zh: "阈值模式：static / volatility_adjusted。", en: "Threshold mode: static / volatility_adjusted." },
    effect: { zh: "决定阈值是否随波动动态调整。", en: "Controls dynamic threshold adjustment by volatility." },
  },
  threshold_volatility_missing_policy: {
    meaning: { zh: "波动缺失处理策略。", en: "Policy when volatility input is missing." },
    effect: { zh: "控制缺失波动时按中性或拒绝处理。", en: "Controls neutral fallback or reject on missing volatility." },
  },
};

const isObject = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const deepClone = <T,>(value: T): T => JSON.parse(JSON.stringify(value ?? {})) as T;
const pickText = (text: LocaleText, locale: string) => (locale === "zh-CN" ? text.zh : text.en);
const labelOf = (key: string) => t(DIMENSION_LABEL_KEYS[key] ?? key);
const groupTitleOf = (groupId: string, locale: string) => {
  const title = GROUP_TITLES[groupId];
  if (!title) return labelOf(groupId);
  return locale === "zh-CN" ? title.zh : title.en;
};

const ensureObjectPath = (root: Record<string, unknown>, path: string[]): Record<string, unknown> => {
  let cursor: Record<string, unknown> = root;
  for (const segment of path) {
    const current = cursor[segment];
    if (!isObject(current)) {
      const replacement: Record<string, unknown> = {};
      cursor[segment] = replacement;
      cursor = replacement;
      continue;
    }
    cursor = current;
  }
  return cursor;
};

const getNumberAt = (root: Record<string, unknown>, path: string[], fallback: number): number => {
  let cursor: unknown = root;
  for (const segment of path) {
    if (!isObject(cursor)) return fallback;
    cursor = cursor[segment];
  }
  const parsed = Number(cursor);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const getStringAt = (root: Record<string, unknown>, path: string[], fallback: string): string => {
  let cursor: unknown = root;
  for (const segment of path) {
    if (!isObject(cursor)) return fallback;
    cursor = cursor[segment];
  }
  const text = `${cursor ?? ""}`.trim();
  return text || fallback;
};

const ensureWeightMap = (root: Record<string, unknown>, path: string[], keys: readonly string[], fallback: number) => {
  const container = ensureObjectPath(root, path);
  keys.forEach((key) => {
    const parsed = Number(container[key]);
    container[key] = Number.isFinite(parsed) ? parsed : fallback;
  });
};

const ensureDualTrackDefaults = (root: Record<string, unknown>, path: string[]) => {
  const container = ensureObjectPath(root, path);
  const defaults: Record<string, number | string> = {
    fusion_buy_threshold: 0.76,
    fusion_sell_threshold: -0.17,
    sell_precedence_gate: -0.5,
    min_fusion_confidence: 0.5,
    min_tech_score_for_buy: 0,
    min_context_score_for_buy: 0,
    min_tech_confidence_for_buy: 0.5,
    min_context_confidence_for_buy: 0.5,
    lambda_divergence: 0.6,
    lambda_sign_conflict: 0.4,
    sign_conflict_min_abs_score: 0.1,
    buy_vol_k: 0.2,
    sell_vol_k: 0.2,
    mode: "rule_only",
    threshold_mode: "static",
    threshold_volatility_missing_policy: "neutral_zero",
  };
  Object.entries(defaults).forEach(([key, value]) => {
    if (!(key in container)) container[key] = value;
  });
  const trackWeights = ensureObjectPath(root, [...path, "track_weights"]);
  if (!Number.isFinite(Number(trackWeights.tech))) trackWeights.tech = 1;
  if (!Number.isFinite(Number(trackWeights.context))) trackWeights.context = 1;
};

const normalizeStrategyConfig = (raw: Record<string, unknown> | undefined): Record<string, unknown> => {
  const next = deepClone(raw ?? {});
  ensureWeightMap(next, ["base", "technical", "group_weights"], TECHNICAL_GROUPS, 1);
  ensureWeightMap(next, ["base", "technical", "dimension_weights"], TECHNICAL_DIMENSIONS, 1);
  ensureWeightMap(next, ["base", "context", "group_weights"], CONTEXT_GROUPS, 1);
  ensureWeightMap(next, ["base", "context", "dimension_weights"], CONTEXT_DIMENSIONS, 1);
  const dimensionGroups = ensureObjectPath(next, ["base", "context", "dimension_groups"]);
  dimensionGroups.market_structure = [...CONTEXT_GROUP_DIMENSIONS.market_structure];
  dimensionGroups.risk_account = [...CONTEXT_GROUP_DIMENSIONS.risk_account];
  dimensionGroups.tradability_timing = [...CONTEXT_GROUP_DIMENSIONS.tradability_timing];
  dimensionGroups.source_execution = [...CONTEXT_GROUP_DIMENSIONS.source_execution];
  ensureDualTrackDefaults(next, ["base", "dual_track"]);

  ensureWeightMap(next, ["profiles", "candidate", "technical", "group_weights"], TECHNICAL_GROUPS, 1);
  ensureWeightMap(next, ["profiles", "candidate", "technical", "dimension_weights"], TECHNICAL_DIMENSIONS, 1);
  ensureWeightMap(next, ["profiles", "candidate", "context", "group_weights"], CONTEXT_GROUPS, 1);
  ensureWeightMap(next, ["profiles", "candidate", "context", "dimension_weights"], CONTEXT_DIMENSIONS, 1);
  ensureDualTrackDefaults(next, ["profiles", "candidate", "dual_track"]);

  ensureWeightMap(next, ["profiles", "position", "technical", "group_weights"], TECHNICAL_GROUPS, 1);
  ensureWeightMap(next, ["profiles", "position", "technical", "dimension_weights"], TECHNICAL_DIMENSIONS, 1);
  ensureWeightMap(next, ["profiles", "position", "context", "group_weights"], CONTEXT_GROUPS, 1);
  ensureWeightMap(next, ["profiles", "position", "context", "dimension_weights"], CONTEXT_DIMENSIONS, 1);
  ensureDualTrackDefaults(next, ["profiles", "position", "dual_track"]);
  return next;
};

const buildUnifiedEditableConfig = (raw: Record<string, unknown> | undefined): Record<string, unknown> => {
  const next = normalizeStrategyConfig(raw);
  const candidateRoot = ensureObjectPath(next, ["profiles", "candidate"]);
  const baseRoot = ensureObjectPath(next, ["base"]);
  const positionRoot = ensureObjectPath(next, ["profiles", "position"]);

  baseRoot.technical = deepClone(candidateRoot.technical ?? baseRoot.technical ?? {});
  baseRoot.context = deepClone(candidateRoot.context ?? baseRoot.context ?? {});
  baseRoot.dual_track = deepClone(candidateRoot.dual_track ?? baseRoot.dual_track ?? {});

  positionRoot.technical = deepClone(baseRoot.technical);
  positionRoot.context = deepClone(baseRoot.context);
  positionRoot.dual_track = deepClone(baseRoot.dual_track);
  candidateRoot.technical = deepClone(baseRoot.technical);
  candidateRoot.context = deepClone(baseRoot.context);
  candidateRoot.dual_track = deepClone(baseRoot.dual_track);
  return next;
};

const buildUnifiedSaveConfig = (raw: Record<string, unknown>): Record<string, unknown> => {
  const next = normalizeStrategyConfig(raw);
  const baseRoot = ensureObjectPath(next, ["base"]);
  const candidateRoot = ensureObjectPath(next, ["profiles", "candidate"]);
  const positionRoot = ensureObjectPath(next, ["profiles", "position"]);

  candidateRoot.technical = deepClone(baseRoot.technical ?? {});
  candidateRoot.context = deepClone(baseRoot.context ?? {});
  candidateRoot.dual_track = deepClone(baseRoot.dual_track ?? {});
  positionRoot.technical = deepClone(baseRoot.technical ?? {});
  positionRoot.context = deepClone(baseRoot.context ?? {});
  positionRoot.dual_track = deepClone(baseRoot.dual_track ?? {});
  return next;
};

const dualTrackFields: DualTrackField[] = [
  { key: "mode", label: "Dual-track mode", type: "select", options: ["rule_only", "weighted_only", "hybrid"], path: ["mode"] },
  { key: "threshold_mode", label: "Threshold mode", type: "select", options: ["static", "volatility_adjusted"], path: ["threshold_mode"] },
  { key: "threshold_volatility_missing_policy", label: "Volatility missing policy", type: "select", options: ["neutral_zero", "reject"], path: ["threshold_volatility_missing_policy"] },
  { key: "track_weights.tech", label: "Track weight · Technical", type: "number", path: ["track_weights", "tech"] },
  { key: "track_weights.context", label: "Track weight · Context", type: "number", path: ["track_weights", "context"] },
  { key: "fusion_buy_threshold", label: "Fusion buy threshold", type: "number", path: ["fusion_buy_threshold"] },
  { key: "fusion_sell_threshold", label: "Fusion sell threshold", type: "number", path: ["fusion_sell_threshold"] },
  { key: "sell_precedence_gate", label: "Sell precedence gate", type: "number", path: ["sell_precedence_gate"] },
  { key: "min_fusion_confidence", label: "Min fusion confidence", type: "number", path: ["min_fusion_confidence"] },
  { key: "min_tech_score_for_buy", label: "Min technical score for BUY", type: "number", path: ["min_tech_score_for_buy"] },
  { key: "min_context_score_for_buy", label: "Min context score for BUY", type: "number", path: ["min_context_score_for_buy"] },
  { key: "min_tech_confidence_for_buy", label: "Min technical confidence for BUY", type: "number", path: ["min_tech_confidence_for_buy"] },
  { key: "min_context_confidence_for_buy", label: "Min context confidence for BUY", type: "number", path: ["min_context_confidence_for_buy"] },
  { key: "lambda_divergence", label: "Divergence penalty λ", type: "number", path: ["lambda_divergence"] },
  { key: "lambda_sign_conflict", label: "Sign-conflict penalty λ", type: "number", path: ["lambda_sign_conflict"] },
  { key: "sign_conflict_min_abs_score", label: "Sign-conflict minimum abs score", type: "number", path: ["sign_conflict_min_abs_score"] },
  { key: "buy_vol_k", label: "BUY volatility k", type: "number", path: ["buy_vol_k"] },
  { key: "sell_vol_k", label: "SELL volatility k", type: "number", path: ["sell_vol_k"] },
];

const AI_DYNAMIC_STRATEGY_OPTIONS = [
  { value: "off", label: { zh: "关闭", en: "Off" } },
  { value: "hybrid", label: { zh: "开启", en: "On" } },
];

function normalizeAiDynamicStrategy(value: string) {
  const normalized = String(value).trim().toLowerCase();
  if (!normalized || normalized === "off" || normalized.includes("关")) return "off";
  if (normalized === "template" || normalized === "weights" || normalized === "hybrid" || normalized.includes("开")) return "hybrid";
  return "off";
}

function parseDynamicStrength(value: string | undefined, fallback: number) {
  const match = String(value ?? "").match(/-?\d+(\.\d+)?/);
  if (!match) return fallback;
  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed)) return fallback;
  if (parsed > 1) return Math.max(0, Math.min(1, parsed / 100));
  return Math.max(0, Math.min(1, parsed));
}

function parseDynamicLookback(value: string | undefined, fallback: number) {
  const match = String(value ?? "").match(/\d+/);
  if (!match) return fallback;
  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(6, Math.min(336, Math.round(parsed)));
}

export function StrategyConfigPage({ client }: StrategyConfigPageProps) {
  const effectiveClient = client ?? apiClient;
  const resource = usePageData("settings", effectiveClient);
  const liveSimResource = usePageData("live-sim", effectiveClient);
  const locale = useI18nLocale();
  const strategyProfiles = useMemo(() => (resource.data?.strategyProfiles ?? []) as StrategyProfile[], [resource.data?.strategyProfiles]);
  const orderedProfiles = useMemo(() => {
    const list = [...strategyProfiles];
    const order = new Map<string, number>(BUILTIN_PROFILE_IDS.map((id, index) => [id, index]));
    return list.sort((a, b) => {
      const ai = order.get(a.id);
      const bi = order.get(b.id);
      if (ai !== undefined && bi !== undefined) return ai - bi;
      if (ai !== undefined) return -1;
      if (bi !== undefined) return 1;
      return a.name.localeCompare(b.name, "zh-CN");
    });
  }, [strategyProfiles]);

  const [selectedStrategyProfileId, setSelectedStrategyProfileId] = useState("");
  const [strategyEnabled, setStrategyEnabled] = useState(true);
  const [strategyActionPending, setStrategyActionPending] = useState<ActionState>(null);
  const [strategyActionMessage, setStrategyActionMessage] = useState("");
  const [editableConfig, setEditableConfig] = useState<Record<string, unknown>>({});
  const [activeTechnicalGroup, setActiveTechnicalGroup] = useState<string>("trend");
  const [activeContextGroup, setActiveContextGroup] = useState<string>("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [highlightFormula, setHighlightFormula] = useState(false);
  const [focusedFormulaSection, setFocusedFormulaSection] = useState<1 | 2 | 3 | 4>(1);
  const [focusedParam, setFocusedParam] = useState("");
  const [aiDynamicStrategy, setAiDynamicStrategy] = useState("off");
  const [aiDynamicStrength, setAiDynamicStrength] = useState(0.5);
  const [aiDynamicLookback, setAiDynamicLookback] = useState(48);
  const [aiConfigPending, setAiConfigPending] = useState(false);
  const [aiConfigMessage, setAiConfigMessage] = useState("");

  const selectedProfile = useMemo(
    () => orderedProfiles.find((profile) => profile.id === selectedStrategyProfileId) ?? orderedProfiles[0],
    [selectedStrategyProfileId, orderedProfiles],
  );

  useEffect(() => {
    const firstId =
      resource.data?.selectedStrategyProfileId ||
      orderedProfiles.find((item) => item.id === "aggressive")?.id ||
      orderedProfiles[0]?.id ||
      "";
    setSelectedStrategyProfileId((prev) => (prev && orderedProfiles.some((item) => item.id === prev) ? prev : firstId));
  }, [resource.data?.selectedStrategyProfileId, orderedProfiles]);

  useEffect(() => {
    if (!selectedProfile) {
      setStrategyEnabled(true);
      setEditableConfig(buildUnifiedEditableConfig({}));
      return;
    }
    setStrategyEnabled(Boolean(selectedProfile.enabled));
    setEditableConfig(buildUnifiedEditableConfig(isObject(selectedProfile.config) ? selectedProfile.config : {}));
  }, [selectedProfile?.id]);

  useEffect(() => {
    const cfg = liveSimResource.data?.config;
    if (!cfg) return;
    setAiDynamicStrategy(normalizeAiDynamicStrategy(cfg.aiDynamicStrategy ?? "off"));
    setAiDynamicStrength(parseDynamicStrength(cfg.aiDynamicStrength, 0.5));
    setAiDynamicLookback(parseDynamicLookback(cfg.aiDynamicLookback, 48));
  }, [liveSimResource.data?.updatedAt]);

  const updateNumberPath = (path: string[], value: string, section?: 1 | 2 | 3 | 4, param?: string) => {
    const parsed = Number.parseFloat(value);
    const nextValue = Number.isFinite(parsed) ? parsed : 0;
    setEditableConfig((prev) => {
      const next = deepClone(prev);
      const target = ensureObjectPath(next, path.slice(0, -1));
      target[path[path.length - 1]] = nextValue;
      return next;
    });
    if (section) setFocusedFormulaSection(section);
    if (param) setFocusedParam(param);
  };

  const updateStringPath = (path: string[], value: string, section?: 1 | 2 | 3 | 4, param?: string) => {
    setEditableConfig((prev) => {
      const next = deepClone(prev);
      const target = ensureObjectPath(next, path.slice(0, -1));
      target[path[path.length - 1]] = value;
      return next;
    });
    if (section) setFocusedFormulaSection(section);
    if (param) setFocusedParam(param);
  };

  const buildCloneName = () => {
    const now = new Date();
    const stamp = `${now.getHours().toString().padStart(2, "0")}${now.getMinutes().toString().padStart(2, "0")}${now
      .getSeconds()
      .toString()
      .padStart(2, "0")}`;
    const baseName = selectedProfile?.name || selectedProfileId || "profile";
    return `${baseName}-${locale === "zh-CN" ? "克隆" : "clone"}-${stamp}`;
  };

  const buildCreateName = () => {
    const now = new Date();
    const stamp = `${now.getHours().toString().padStart(2, "0")}${now.getMinutes().toString().padStart(2, "0")}${now
      .getSeconds()
      .toString()
      .padStart(2, "0")}`;
    return `${locale === "zh-CN" ? "自定义策略" : "Custom strategy"}-${stamp}`;
  };

  const renderConfigLabel = (key: string) => {
    const alias = labelOf(key);
    if (locale === "zh-CN") {
      return `${alias}(${key})`;
    }
    const cleaned = alias.replace(/[（(].*?[）)]/g, "").trim();
    const hasCjk = /[\u3400-\u9fff]/.test(cleaned);
    return cleaned && !hasCjk ? cleaned : key;
  };

  const trackGroupWeightSum = (trackPath: string[], groups: readonly string[]) =>
    groups.reduce((acc, groupId) => acc + getNumberAt(editableConfig, [...trackPath, "group_weights", groupId], 0), 0);

  const renderTrackSection = (
    title: string,
    subtitle: string,
    groups: Record<string, readonly string[]>,
    trackPath: string[],
    activeGroup: string,
    onToggleGroup: (groupId: string) => void,
  ) => (
    <WorkbenchCard className="strategy-config-card">
      <div className="strategy-config-card__header">
        <div>
          <h2 className="strategy-config-card__title">{title}</h2>
          <div className="strategy-config-card__subtitle">{subtitle}</div>
        </div>
        <div className="strategy-config-card__meta">
          {locale === "zh-CN"
            ? `组权重总和：${trackGroupWeightSum(trackPath, Object.keys(groups)).toFixed(4)}（已归一化）`
            : `Category weight sum: ${trackGroupWeightSum(trackPath, Object.keys(groups)).toFixed(4)} (normalized)`}
        </div>
      </div>
      <div className="strategy-config-track">
        {Object.entries(groups).map(([groupId, dimensions]) => {
          const isActive = activeGroup === groupId;
          const explain = GROUP_EXPLAINS[groupId];
          return (
            <div key={`${trackPath.join(".")}-${groupId}`} className={`strategy-config-track-item${isActive ? " is-active" : ""}`}>
              <button
                type="button"
                className="strategy-config-track-item__header"
                onClick={() => onToggleGroup(isActive ? "" : groupId)}
              >
                <span className="strategy-config-track-item__caret">{isActive ? "▾" : "▸"}</span>
                <span className="strategy-config-track-item__name">{groupTitleOf(groupId, locale)}</span>
                <span className="strategy-config-track-item__weight-label">{locale === "zh-CN" ? "组权重" : "Weight"}</span>
                <span className="strategy-config-track-item__weight-box" onClick={(event) => event.stopPropagation()}>
                  <input
                    className="input strategy-config-group-weight-input"
                    type="number"
                    step="0.01"
                    value={getNumberAt(editableConfig, [...trackPath, "group_weights", groupId], 1)}
                    onFocus={() => {
                      setFocusedFormulaSection(2);
                      setFocusedParam(groupId);
                    }}
                    onChange={(event) => updateNumberPath([...trackPath, "group_weights", groupId], event.target.value, 2, groupId)}
                  />
                </span>
                <span className="strategy-config-track-item__desc">{pickText(explain.meaning, locale)}</span>
                <span className="strategy-config-track-item__tail">{isActive ? "⌃" : "⌄"}</span>
              </button>
              {isActive ? (
                <div className="strategy-config-track-item__body">
                  <table className="strategy-config-table">
                    <thead>
                      <tr>
                        <th>{locale === "zh-CN" ? "维度（指标）" : "Dimension"}</th>
                        <th>{locale === "zh-CN" ? "权重" : "Weight"}</th>
                        <th>{locale === "zh-CN" ? "含义（说明）" : "Meaning"}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dimensions.map((dimension) => {
                        const dimensionExplain = DIMENSION_EXPLAINS[dimension];
                        return (
                          <tr key={`${groupId}-${dimension}`}>
                            <td>{renderConfigLabel(dimension)}</td>
                            <td>
                              <input
                                className="input"
                                type="number"
                                step="0.01"
                                value={getNumberAt(editableConfig, [...trackPath, "dimension_weights", dimension], 1)}
                                onFocus={() => {
                                  setFocusedFormulaSection(1);
                                  setFocusedParam(dimension);
                                }}
                                onChange={(event) => updateNumberPath([...trackPath, "dimension_weights", dimension], event.target.value, 1, dimension)}
                              />
                            </td>
                            <td>
                              <div className="strategy-config-meaning">
                                <span>{pickText(dimensionExplain.meaning, locale)}</span>
                                <span className="strategy-config-info" title={pickText(dimensionExplain.effect, locale)}>ⓘ</span>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </WorkbenchCard>
  );

  const dualTrackPanelFields = dualTrackFields.filter((field) =>
    [
      "track_weights.tech",
      "track_weights.context",
      "fusion_buy_threshold",
      "fusion_sell_threshold",
      "min_fusion_confidence",
      "min_tech_confidence_for_buy",
      "min_context_confidence_for_buy",
      "sell_precedence_gate",
      "lambda_divergence",
      "lambda_sign_conflict",
      "sign_conflict_min_abs_score",
      "threshold_mode",
    ].includes(field.key),
  );

  const formulaSectionByDualField = (key: string): 3 | 4 =>
    ["track_weights.tech", "track_weights.context", "lambda_divergence", "lambda_sign_conflict", "sign_conflict_min_abs_score"].includes(key)
      ? 3
      : 4;

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title={t("Strategy configuration loading...")} description={t("Loading strategy profile and weight parameters.")} />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title={t("Strategy configuration failed to load")}
        description={resource.error ?? t("Unable to load strategy configuration. Please retry later.")}
        actionLabel={t("Reload")}
        onAction={resource.refresh}
      />
    );
  }

  if (!resource.data) {
    return <PageEmptyState title={t("Strategy configuration has no data")} description={t("Backend has not returned strategy profile data yet.")} actionLabel={t("Refresh")} onAction={resource.refresh} />;
  }

  if (orderedProfiles.length === 0) {
    return <SectionEmptyState title={t("No strategy profiles")} description={t("Backend has not initialized strategy profile data yet.")} />;
  }

  const selectedProfileId = selectedProfile?.id ?? "";
  const formulaCardClass = (section: 1 | 2 | 3 | 4) =>
    `strategy-config-formula__item${highlightFormula && focusedFormulaSection === section ? " is-highlight" : ""}`;

  return (
    <div className="strategy-config">
      <WorkbenchCard className="strategy-config-top">
        <div className="strategy-config-top__title">
          <h1>{locale === "zh-CN" ? "策略配置" : "Strategy configuration"}</h1>
          <span className="strategy-config-info">ⓘ</span>
          <span>{locale === "zh-CN" ? "配置量化评分的权重、阈值与算法参数" : "Configure quant weights, thresholds and algorithm parameters."}</span>
        </div>
        <div className="strategy-config-top__controls">
          <label className="strategy-config-field">
            <span>{locale === "zh-CN" ? "当前策略" : "Current strategy"}</span>
            <select className="input" value={selectedProfileId} onChange={(event) => setSelectedStrategyProfileId(event.target.value)}>
              {orderedProfiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name}
                </option>
              ))}
            </select>
          </label>
          <div className="strategy-config-toggle">
            <span>{locale === "zh-CN" ? "状态" : "Status"}</span>
            <label className="strategy-config-switch" aria-label={locale === "zh-CN" ? "启用策略" : "Enable strategy"}>
              <input type="checkbox" checked={strategyEnabled} onChange={(event) => setStrategyEnabled(event.target.checked)} />
              <span className="strategy-config-switch__track">
                <span className="strategy-config-switch__thumb" />
              </span>
            </label>
            <span>{locale === "zh-CN" ? "启用" : "Enabled"}</span>
          </div>
          <button
            className="button button--secondary"
            type="button"
            disabled={strategyActionPending !== null || !selectedProfileId}
            onClick={async () => {
              setStrategyActionMessage("");
              setStrategyActionPending("save");
              try {
                await effectiveClient.validateStrategyProfile(selectedProfileId, {
                  config: buildUnifiedSaveConfig(editableConfig),
                });
                setStrategyActionMessage(locale === "zh-CN" ? "校验通过" : "Validation passed");
              } catch (error) {
                setStrategyActionMessage(error instanceof Error ? error.message : locale === "zh-CN" ? "校验失败" : "Validation failed");
              } finally {
                setStrategyActionPending(null);
              }
            }}
          >
            {locale === "zh-CN" ? "校验" : "Validate"}
          </button>
          <button
            className="button button--secondary"
            type="button"
            disabled={strategyActionPending !== null}
            onClick={async () => {
              const defaultName = buildCreateName();
              const typedName = typeof window !== "undefined" ? window.prompt(locale === "zh-CN" ? "请输入新策略名称" : "Enter new strategy name", defaultName) : defaultName;
              const name = `${typedName ?? ""}`.trim();
              if (!name) return;
              setStrategyActionMessage("");
              setStrategyActionPending("create");
              try {
                const created = await effectiveClient.createStrategyProfile<{
                  profile?: { id?: string };
                }>({
                  name,
                  description: locale === "zh-CN" ? "自定义策略（由页面新建）" : "Custom strategy (created from UI)",
                  enabled: true,
                  config: buildUnifiedSaveConfig(editableConfig),
                  note: "ui_created_profile",
                });
                await resource.refresh();
                const nextId = `${created?.profile?.id ?? ""}`.trim();
                if (nextId) setSelectedStrategyProfileId(nextId);
                setStrategyActionMessage(locale === "zh-CN" ? "新建成功" : "Created");
              } catch (error) {
                setStrategyActionMessage(error instanceof Error ? error.message : locale === "zh-CN" ? "新建失败" : "Create failed");
              } finally {
                setStrategyActionPending(null);
              }
            }}
          >
            {strategyActionPending === "create" ? (locale === "zh-CN" ? "新建中..." : "Creating...") : locale === "zh-CN" ? "新建策略" : "New strategy"}
          </button>
          <button
            className="button button--primary"
            type="button"
            disabled={strategyActionPending !== null || !selectedProfileId}
            onClick={async () => {
              setStrategyActionMessage("");
              setStrategyActionPending("save");
              try {
                await effectiveClient.updateStrategyProfile(selectedProfileId, {
                  name: selectedProfile?.name ?? selectedProfileId,
                  description: selectedProfile?.description ?? "",
                  enabled: strategyEnabled,
                  config: buildUnifiedSaveConfig(editableConfig),
                  note: "ui_weight_editor_update_layout",
                });
                await resource.refresh();
                setStrategyActionMessage(locale === "zh-CN" ? "保存成功" : "Saved");
              } catch (error) {
                setStrategyActionMessage(error instanceof Error ? error.message : locale === "zh-CN" ? "保存失败" : "Save failed");
              } finally {
                setStrategyActionPending(null);
              }
            }}
          >
            {strategyActionPending === "save" ? (locale === "zh-CN" ? "保存中..." : "Saving...") : locale === "zh-CN" ? "保存" : "Save"}
          </button>
          <button
            className="button button--secondary"
            type="button"
            disabled={strategyActionPending !== null || !selectedProfileId}
            onClick={() => {
              setStrategyActionMessage("");
              setEditableConfig(buildUnifiedEditableConfig(isObject(selectedProfile?.config) ? selectedProfile.config : {}));
            }}
          >
            {locale === "zh-CN" ? "重置" : "Reset"}
          </button>
        </div>
      </WorkbenchCard>

      {strategyActionMessage ? <div className="strategy-config-message">{strategyActionMessage}</div> : null}

      <div className="strategy-config-layout">
        <div className="strategy-config-left">
          {renderTrackSection(
            locale === "zh-CN" ? "技术轨" : "Technical track",
            locale === "zh-CN" ? "衡量个股技术面信号强度，共 12 个维度" : "Measures technical signal strength with 12 dimensions.",
            TECHNICAL_GROUP_DIMENSIONS,
            ["base", "technical"],
            activeTechnicalGroup,
            setActiveTechnicalGroup,
          )}
          {renderTrackSection(
            locale === "zh-CN" ? "环境轨" : "Context track",
            locale === "zh-CN" ? "衡量市场/账户/执行等环境因素的支持度，共 9 个维度" : "Measures market/account/execution context support with 9 dimensions.",
            CONTEXT_GROUP_DIMENSIONS,
            ["base", "context"],
            activeContextGroup,
            setActiveContextGroup,
          )}

          <WorkbenchCard className="strategy-config-card">
            <div className="strategy-config-card__header">
              <div>
                <h2 className="strategy-config-card__title">{locale === "zh-CN" ? "融合参数（决策门控）" : "Fusion parameters (decision gates)"}</h2>
                <div className="strategy-config-card__subtitle">
                  {locale === "zh-CN"
                    ? "用于控制技术轨 + 环境轨如何融合，以及 BUY/SELL/HOLD 的阈值与置信度门槛"
                    : "Controls how technical/context tracks are fused and how BUY/SELL/HOLD thresholds and confidence gates are applied."}
                </div>
              </div>
            </div>
            <div className="strategy-config-dual-grid">
              {dualTrackPanelFields.map((field) => {
                const explain = DUAL_PARAM_EXPLAINS[field.key];
                const fullPath = ["base", "dual_track", ...field.path];
                const section = formulaSectionByDualField(field.key);
                return (
                  <div key={`dual-${field.key}`} className="strategy-config-dual-item">
                    <label>
                      <span>{t(field.label)}</span>
                      <span className="strategy-config-info" title={pickText(explain.effect, locale)}>ⓘ</span>
                    </label>
                    {field.type === "select" ? (
                      <select
                        className="input"
                        value={getStringAt(editableConfig, fullPath, field.options?.[0] ?? "")}
                        onFocus={() => {
                          setFocusedFormulaSection(section);
                          setFocusedParam(field.key);
                        }}
                        onChange={(event) => updateStringPath(fullPath, event.target.value, section, field.key)}
                      >
                        {(field.options ?? []).map((option) => (
                          <option key={option} value={option}>
                            {t(option)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="input"
                        type="number"
                        step="0.01"
                        value={getNumberAt(editableConfig, fullPath, 0)}
                        onFocus={() => {
                          setFocusedFormulaSection(section);
                          setFocusedParam(field.key);
                        }}
                        onChange={(event) => updateNumberPath(fullPath, event.target.value, section, field.key)}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </WorkbenchCard>

          <WorkbenchCard className="strategy-config-card strategy-config-card--compact">
            <div className="strategy-config-advanced">
              <div>
                <h2 className="strategy-config-card__title">{locale === "zh-CN" ? "高级模式（Base / Candidate / Position）" : "Advanced mode (Base / Candidate / Position)"}</h2>
                <div className="strategy-config-card__subtitle">
                  {locale === "zh-CN" ? "配置基础层与场景层覆盖参数（默认关闭）" : "Configure base and profile override params (collapsed by default)."}
                </div>
              </div>
              <button className="button button--secondary" type="button" onClick={() => setAdvancedOpen((prev) => !prev)}>
                {advancedOpen ? (locale === "zh-CN" ? "收起" : "Collapse") : locale === "zh-CN" ? "展开" : "Expand"}
              </button>
            </div>
            {advancedOpen ? (
              <div className="strategy-config-advanced__body">
                <div>{locale === "zh-CN" ? "当前页面对外展示单策略编辑，保存后会同步 Candidate 与 Position。" : "Single-view editing is shown. Save syncs Candidate and Position."}</div>
                <button
                  className="button button--secondary"
                  type="button"
                  disabled={strategyActionPending !== null || !selectedProfileId}
                  onClick={async () => {
                    setStrategyActionMessage("");
                    setStrategyActionPending("clone");
                    try {
                      const cloned = await effectiveClient.cloneStrategyProfile(selectedProfileId, { name: buildCloneName() });
                      await resource.refresh();
                      const nextId = `${(cloned as { profile?: { id?: string } })?.profile?.id ?? ""}`.trim();
                      if (nextId) setSelectedStrategyProfileId(nextId);
                      setStrategyActionMessage(locale === "zh-CN" ? "克隆成功" : "Cloned");
                    } catch (error) {
                      setStrategyActionMessage(error instanceof Error ? error.message : locale === "zh-CN" ? "克隆失败" : "Clone failed");
                    } finally {
                      setStrategyActionPending(null);
                    }
                  }}
                >
                  {strategyActionPending === "clone" ? (locale === "zh-CN" ? "克隆中..." : "Cloning...") : locale === "zh-CN" ? "克隆当前策略" : "Clone current strategy"}
                </button>
              </div>
            ) : null}
          </WorkbenchCard>

          <WorkbenchCard className="strategy-config-card strategy-config-card--compact">
            <div className="strategy-config-card__header">
              <div>
                <h2 className="strategy-config-card__title">{locale === "zh-CN" ? "AI动态策略参数" : "AI dynamic strategy parameters"}</h2>
                <div className="strategy-config-card__subtitle">
                  {locale === "zh-CN"
                    ? "控制 AI 对当前策略模板的动态调整幅度与观察窗口。"
                    : "Controls AI dynamic adjustment strength and lookback window on top of the selected strategy profile."}
                </div>
              </div>
            </div>
            <div className="strategy-config-dual-grid">
              <div className="strategy-config-dual-item">
                <label>
                  <span>{locale === "zh-CN" ? "AI动态策略" : "AI dynamic strategy"}</span>
                </label>
                <select className="input" value={aiDynamicStrategy} onChange={(event) => setAiDynamicStrategy(event.target.value)}>
                  {AI_DYNAMIC_STRATEGY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {pickText(option.label, locale)}
                    </option>
                  ))}
                </select>
              </div>
              {aiDynamicStrategy !== "off" ? (
                <>
                  <div className="strategy-config-dual-item">
                    <label>
                      <span>{locale === "zh-CN" ? "AI动态强度(0-1)" : "AI dynamic strength (0-1)"}</span>
                    </label>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={aiDynamicStrength}
                      onChange={(event) => setAiDynamicStrength(Math.max(0, Math.min(1, Number(event.target.value) || 0)))}
                    />
                  </div>
                  <div className="strategy-config-dual-item">
                    <label>
                      <span>{locale === "zh-CN" ? "AI回看窗口(小时)" : "AI lookback window (hours)"}</span>
                    </label>
                    <input
                      className="input"
                      type="number"
                      min={6}
                      max={336}
                      step={6}
                      value={aiDynamicLookback}
                      onChange={(event) => setAiDynamicLookback(Math.max(6, Math.min(336, Number(event.target.value) || 48)))}
                    />
                  </div>
                </>
              ) : null}
            </div>
            <div className="toolbar toolbar--compact">
              <button
                className="button button--secondary"
                type="button"
                disabled={aiConfigPending}
                onClick={async () => {
                  setAiConfigMessage("");
                  setAiConfigPending(true);
                  try {
                    await effectiveClient.runPageAction("live-sim", "save", {
                      strategyMode: "auto",
                      aiDynamicStrategy,
                      aiDynamicStrength,
                      aiDynamicLookback,
                    });
                    await liveSimResource.refresh();
                    setAiConfigMessage(locale === "zh-CN" ? "AI参数已保存" : "AI parameters saved");
                  } catch (error) {
                    setAiConfigMessage(error instanceof Error ? error.message : locale === "zh-CN" ? "AI参数保存失败" : "Failed to save AI parameters");
                  } finally {
                    setAiConfigPending(false);
                  }
                }}
              >
                {aiConfigPending ? (locale === "zh-CN" ? "保存中..." : "Saving...") : locale === "zh-CN" ? "保存AI参数" : "Save AI parameters"}
              </button>
              {aiConfigMessage ? <span className="summary-item__body">{aiConfigMessage}</span> : null}
            </div>
          </WorkbenchCard>
        </div>

        <div className="strategy-config-right">
          <WorkbenchCard className="strategy-config-formula">
            <h2 className="strategy-config-card__title">{locale === "zh-CN" ? "公式与影响预览" : "Formula and impact preview"}</h2>
            <div className="strategy-config-card__subtitle">
              {locale === "zh-CN" ? "点击左侧参数可高亮公式中的对应项" : "Click parameters on the left to highlight related formula section."}
            </div>

            <div className={formulaCardClass(1)}>
              <div className="strategy-config-formula__title">1. {locale === "zh-CN" ? "组内归一化（Group 内）" : "In-group normalization"}</div>
              <pre>{`w_i,norm = (w_i × a_i) / Σ_j∈Dg(w_j × a_j)
c_i = w_i,norm × s_i
S_g = clamp(Σ_i∈Dg(c_i), -1, 1)`}</pre>
            </div>

            <div className={formulaCardClass(2)}>
              <div className="strategy-config-formula__title">2. {locale === "zh-CN" ? "轨道汇总（Track 内）" : "Track aggregation"}</div>
              <pre>{`W_g,norm = (W_g × A_g) / Σ_k(W_k × A_k)
C_g = W_g,norm × S_g
TrackScore = clamp(Σ_g(C_g), -1, 1)
TrackConfidence = Σ_g(W_g × Coverage_g) / Σ_g(W_g)`}</pre>
            </div>

            <div className={formulaCardClass(3)}>
              <div className="strategy-config-formula__title">3. {locale === "zh-CN" ? "双轨融合（Fusion）" : "Fusion"}</div>
              <pre>{`α_tech,norm = α_tech / (α_tech + α_ctx)
α_ctx,norm = α_ctx / (α_tech + α_ctx)
FusionScore = α_tech,norm × TechScore + α_ctx,norm × CtxScore
FusionConfidence = FusionConfidence_base × (1 - Penalty)`}</pre>
            </div>

            <div className={formulaCardClass(4)}>
              <div className="strategy-config-formula__title">4. {locale === "zh-CN" ? "动作门控（BUY / SELL / HOLD）" : "Action gates"}</div>
              <pre>{`先应用 Hard Veto（最高优先级）
FusionConfidence < 最小置信度 ⇒ HOLD
BUY: FusionScore ≥ BUY_threshold 且各轨道 BUY 门控通过
SELL: FusionScore ≤ SELL_threshold
否则 ⇒ HOLD`}</pre>
            </div>

            <label className="strategy-config-formula__highlight-toggle">
              <input type="checkbox" checked={highlightFormula} onChange={(event) => setHighlightFormula(event.target.checked)} />
              <span>
                {locale === "zh-CN" ? "高亮：对应左侧选中参数" : "Highlight selected parameter"}
                {focusedParam ? ` · ${focusedParam}` : ""}
              </span>
            </label>
          </WorkbenchCard>
        </div>
      </div>
    </div>
  );
}
