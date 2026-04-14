import type {
  AiMonitorSnapshot,
  DiscoverSnapshot,
  HistorySnapshot,
  LiveSimSnapshot,
  PageKey,
  PageSnapshotMap,
  PortfolioSnapshot,
  RealMonitorSnapshot,
  ReplaySnapshot,
  ResearchSnapshot,
  SettingsSnapshot,
  TableRow,
  TableSection,
  WorkbenchSnapshot,
} from "./page-models";

type MutableSnapshotMap = {
  [K in PageKey]: PageSnapshotMap[K];
};

const clone = <T,>(value: T): T => {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
};

const makeWatchlistRow = (
  code: string,
  name: string,
  price: string,
  source: string,
  status: string,
  quant: string,
): TableRow => ({
  id: code,
  cells: [code, name, price, source, status, quant],
  actions: [
    { label: "分析", icon: "🔎", tone: "accent" as const },
    { label: "入量化", icon: "🧪", tone: "neutral" as const },
    { label: "删除", icon: "🗑", tone: "danger" as const },
  ],
  code,
  name,
  source,
  latestPrice: price,
});

const makeCandidateRow = (
  code: string,
  name: string,
  industry: string,
  source: string,
  price: string,
  total: string,
  pe: string,
  pb: string,
  reason: string,
): TableRow => ({
  id: code,
  cells: [code, name, industry, source, price, total, pe, pb],
  badges: source === "主力选股" ? ["推荐"] : [],
  actions: [{ label: "加入我的关注", icon: "⭐", tone: "accent" as const }],
  code,
  name,
  industry,
  source,
  latestPrice: price,
  reason,
});

const makeTable = (columns: string[], rows: TableRow[], emptyLabel?: string): TableSection => ({ columns, rows, emptyLabel });

const normalizeCode = (value: unknown) => {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return String(value);
  return "";
};

const extractCodes = (payload: unknown): string[] => {
  if (Array.isArray(payload)) {
    return payload.map((value) => normalizeCode(value)).filter(Boolean);
  }
  if (typeof payload === "string" || typeof payload === "number") {
    const code = normalizeCode(payload);
    return code ? [code] : [];
  }
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const codes = record.codes ?? record.stockCodes ?? record.ids ?? record.rows;
    if (Array.isArray(codes)) {
      return codes.map((value) => normalizeCode(value)).filter(Boolean);
    }
    const code = normalizeCode(record.code ?? record.stockCode ?? record.id);
    return code ? [code] : [];
  }
  return [];
};

const ensureWatchlistMetrics = () => {
  const quantCount = initialState.workbench.watchlist.rows.filter((row) => row.cells[5]?.includes("入量化")).length;
  initialState.workbench.metrics = initialState.workbench.metrics.map((metric) => {
    if (metric.label === "我的关注") {
      return { ...metric, value: String(initialState.workbench.watchlist.rows.length) };
    }
    if (metric.label === "量化候选") {
      return { ...metric, value: String(quantCount) };
    }
    return metric;
  });
  initialState.workbench.watchlistMeta.quantCount = quantCount;
};

const findDiscoveryCandidate = (code: string) =>
  initialState.discover.candidateTable.rows.find((row) => row.id === code);

const findResearchOutput = (code: string) =>
  initialState.research.outputTable.rows.find((row) => row.id === code);

const upsertWatchlistRow = (code: string, options: { status?: string; quantStatus?: string } = {}) => {
  const normalized = normalizeCode(code);
  if (!normalized) return;

  const current = initialState.workbench.watchlist.rows.find((row) => row.id === normalized);
  if (current) {
    current.cells = [...current.cells];
    if (options.status) current.cells[4] = options.status;
    if (options.quantStatus) current.cells[5] = options.quantStatus;
    return;
  }

  const discoveryRow = findDiscoveryCandidate(normalized);
  const researchRow = findResearchOutput(normalized);
  const name = discoveryRow?.cells[1] ?? researchRow?.cells[1] ?? normalized;
  const price = discoveryRow?.cells[4] ?? researchRow?.cells[3] ?? "0.00";
  const source = discoveryRow?.cells[3] ?? researchRow?.cells[2] ?? "manual";

  initialState.workbench.watchlist.rows = [
    ...initialState.workbench.watchlist.rows,
    makeWatchlistRow(
      normalized,
      name,
      price,
      source,
      options.status ?? "待分析",
      options.quantStatus ?? "未加入",
    ),
  ];
  ensureWatchlistMetrics();
};

const setAnalysisSnapshot = (input: {
  symbol: string;
  analysts?: string[];
  mode?: string;
  cycle?: string;
  headline?: string;
  decision?: string;
  summaryBody?: string;
}) => {
  const symbol = normalizeCode(input.symbol);
  const candidate = symbol ? findDiscoveryCandidate(symbol) ?? findResearchOutput(symbol) : undefined;
  const name = candidate?.cells[1] ?? symbol;
  const mode = input.mode ?? initialState.workbench.analysis.mode;
  const cycle = input.cycle ?? initialState.workbench.analysis.cycle;
  const analysts = input.analysts && input.analysts.length ? input.analysts : initialState.workbench.analysis.analysts.filter((item) => item.selected).map((item) => item.value);

  initialState.workbench.analysis = {
    ...initialState.workbench.analysis,
    symbol,
    mode,
    cycle,
    summaryTitle: input.headline ?? (symbol ? `当前结论：${name} 适合继续观察` : "当前结论：先选择一只股票再开始分析"),
    summaryBody:
      input.summaryBody ?? (symbol
        ? `围绕 ${name} 的分析已经完成，当前更适合把它放在我的关注里持续跟踪，等待更明确的趋势确认。`
        : "请输入股票代码后，系统会生成完整的分析结果。"),
    decision:
      input.decision ?? (symbol
        ? `建议：${name} 先保持观察，若价格重新站稳中期均线再考虑推进到量化候选池。`
        : "请输入股票代码后再查看分析结果。"),
    analysts: initialState.workbench.analysis.analysts.map((item) => ({
      ...item,
      selected: analysts.includes(item.value),
    })),
  };
};

const watchlistColumns = ["代码", "名称", "现价", "来源", "状态", "量化状态"];
const candidateColumns = ["代码", "名称", "所属行业", "来源策略", "最新价", "总市值(亿)", "市盈率", "市净率"];
const holdingsColumns = ["代码", "名称", "仓位", "浮盈亏", "建议动作"];
const summaryColumns = ["时间", "股票", "模式", "结论"];
const replayTradesColumns = ["时间", "代码", "动作", "数量", "价格", "备注"];
const signalColumns = ["时间", "代码", "动作", "策略", "执行结果"];
const queueColumns = ["代码", "名称", "策略风格", "最近动作"];
const ruleColumns = ["规则", "说明", "状态"];

const initialState: MutableSnapshotMap = {
  workbench: {
    updatedAt: "2026-04-13 10:35",
    metrics: [
      { label: "我的关注", value: "3" },
      { label: "我的持仓", value: "2" },
      { label: "量化候选", value: "3" },
      { label: "量化任务", value: "2" },
    ],
    watchlist: makeTable(watchlistColumns, [
      makeWatchlistRow("301291", "明阳电气", "52.87", "主力选股", "待分析", "已入量化"),
      makeWatchlistRow("002824", "和胜股份", "22.97", "主力选股", "已分析", "观察中"),
      makeWatchlistRow("600519", "贵州茅台", "1453.96", "手工添加", "长期跟踪", "未加入"),
    ]),
    watchlistMeta: {
      selectedCount: 0,
      quantCount: 3,
      refreshHint: "报价支持手动刷新，量化调度运行时也会把最新价格和信号回写到这里。",
    },
    analysis: {
      symbol: "301291",
      analysts: [
        { label: "技术分析师", value: "technical", selected: true },
        { label: "基本面分析师", value: "fundamental", selected: true },
        { label: "资金面分析师", value: "fund_flow", selected: true },
        { label: "市场情绪分析师", value: "sentiment", selected: true },
        { label: "风险管理师", value: "risk", selected: true },
        { label: "新闻分析师", value: "news", selected: false },
      ],
      mode: "单个分析",
      cycle: "1y",
      inputHint: "例如 600519 / 300390 / AAPL",
      summaryTitle: "最近分析摘要",
      summaryBody: "价格偏弱，趋势处于震荡，适合轻仓观察。图表、团队观点和结论会统一收进同一个结果区域。",
      indicators: [
        { label: "RSI", value: "53.79", tone: "neutral" },
        { label: "MA20", value: "1441.86", tone: "neutral" },
        { label: "量比", value: "1.13", tone: "neutral" },
        { label: "MACD", value: "6.2792", tone: "positive" },
      ],
      decision: "当前建议为轻仓观察，等待趋势和资金配合后再推进量化候选池。",
      insights: [
        { title: "当前风格", body: "单股分析会把团队观点、指标和最终决策聚合到一个结果面板里。", tone: "accent" },
        { title: "重点关注", body: "若价格重新站稳 MA20 且量能放大，可再考虑进入量化候选池。", tone: "warning" },
      ],
      curve: [
        { label: "周一", value: 4 },
        { label: "周二", value: 6 },
        { label: "周三", value: 5 },
        { label: "周四", value: 8 },
        { label: "周五", value: 9 },
      ],
    },
    nextSteps: [
      { label: "持仓分析", hint: "查看当前持仓、收益归因和仓位动作", href: "/portfolio" },
      { label: "实时监控", hint: "看价格规则、触发记录和通知状态", href: "/real-monitor" },
      { label: "AI盯盘", hint: "连续盯盘、生成信号并回看事件时间线", href: "/ai-monitor" },
      { label: "发现股票", hint: "进入选股聚合页，挑出新的关注对象", href: "/discover" },
      { label: "研究情报", hint: "聚合板块、龙虎榜、新闻和宏观判断", href: "/research" },
      { label: "量化模拟", hint: "围绕量化候选池做实时模拟", href: "/live-sim" },
      { label: "历史回放", hint: "用同一候选池回看历史表现", href: "/his-replay" },
    ],
    activity: [
      { time: "10:18", title: "关注池更新", body: "300390 被加入我的关注，最新价格已刷新。" },
      { time: "10:24", title: "股票分析", body: "301291 已完成单股分析，结论为轻仓观察。" },
      { time: "10:31", title: "量化候选", body: "002824 已进入量化候选池，等待模拟任务处理。" },
    ],
  },
  discover: {
    updatedAt: "2026-04-13 10:35",
    metrics: [
      { label: "发现策略", value: "5" },
      { label: "最近候选股票", value: "32" },
      { label: "加入我的关注", value: "14" },
      { label: "最近一次运行", value: "19:26" },
    ],
    strategies: [
      { name: "主力选股", note: "主资金流 + 财务过滤 + AI精选", status: "最近推荐 5 只", highlight: "可勾选后加入我的关注" },
      { name: "低价擒牛", note: "低价高弹性标的挖掘", status: "待运行" },
      { name: "小市值", note: "小而活跃的成长标的", status: "最近推荐 12 只" },
      { name: "净利增长", note: "盈利增长趋势筛选", status: "最近推荐 9 只" },
      { name: "低估值", note: "估值修复方向", status: "最近推荐 6 只" },
    ],
    summary: {
      title: "发现策略说明",
      body: "先运行选股策略，再把真正需要跟踪的股票加入我的关注；结果区会同时保留候选、推荐和历史信息。",
    },
    candidateTable: makeTable(candidateColumns, [
      makeCandidateRow("301291", "明阳电气", "电气设备", "主力选股", "52.87", "128.6", "31.2", "4.1", "资金流向和趋势确认都较强，适合继续关注。"),
      makeCandidateRow("002824", "和胜股份", "工业金属", "主力选股", "22.97", "78.6", "58.8", "3.5", "震荡环境下估值和弹性兼顾，适合候选跟踪。"),
      makeCandidateRow("300857", "协创数据", "消费电子", "低价擒牛", "208.25", "624.6", "24.5", "5.9", "低价高弹性方向，适合进入关注池观察。"),
      makeCandidateRow("002463", "沪电股份", "电子元件", "研究情报", "90.40", "142.3", "28.4", "3.8", "研究情报已经给出明确股票输出，可纳入关注池。"),
    ]),
    recommendation: {
      title: "精选推荐",
      body: "这部分保留模型综合筛选后的优先关注名单，支持单只或批量加入我的关注。",
      chips: ["⭐ 加入所选关注池", "⭐ 加入单只关注池"],
    },
  },
  research: {
    updatedAt: "2026-04-13 10:35",
    modules: [
      { name: "智策板块", note: "热点方向和板块轮动判断", output: "股票输出 6 只" },
      { name: "智瞰龙虎", note: "龙虎榜席位行为和异常波动", output: "股票输出 4 只" },
      { name: "新闻流量", note: "新闻热度和情绪脉冲", output: "情报结论" },
      { name: "宏观分析", note: "总量、流动性和风险偏好", output: "市场判断" },
      { name: "宏观周期", note: "周期阶段与资产偏好", output: "市场判断" },
    ],
    marketView: [
      { title: "市场判断", body: "大盘情绪偏震荡，风险偏好没有恢复到趋势市状态。", tone: "warning" },
      { title: "风格轮动", body: "消费和高股息偏防御，科技高弹性需要更强资金确认。", tone: "neutral" },
      { title: "回写用途", body: "研究模块会把这些背景结论回写到股票分析和量化解释中。", tone: "accent" },
    ],
    outputTable: makeTable(["代码", "名称", "来源模块", "后续动作"], [
      { id: "002463", cells: ["002463", "沪电股份", "智瞰龙虎", "席位集中度提升，可加入我的关注"], actions: [{ label: "加入关注", icon: "⭐", tone: "accent" }] },
      { id: "600519", cells: ["600519", "贵州茅台", "宏观分析", "消费防御属性增强，适合持续跟踪"], actions: [{ label: "加入关注", icon: "⭐", tone: "accent" }] },
    ]),
    summary: {
      title: "研究情报",
      body: "研究情报默认先给出市场判断；只有模块产出明确股票时，才出现“加入我的关注”的后续动作。",
    },
  },
  portfolio: {
    updatedAt: "2026-04-13 10:35",
    metrics: [
      { label: "当前持仓", value: "3" },
      { label: "组合收益", value: "9.7%" },
      { label: "最大回撤", value: "-4.1%" },
      { label: "风险暴露", value: "中性" },
    ],
    holdings: makeTable(["代码", "名称", "仓位", "浮盈亏", "建议动作"], [
      { id: "002463", cells: ["002463", "沪电股份", "34%", "+12.4%", "继续持有"], actions: [{ label: "分析", icon: "🔎", tone: "accent" }] },
      { id: "600519", cells: ["600519", "贵州茅台", "22%", "+5.8%", "观察回撤"], actions: [{ label: "分析", icon: "🔎", tone: "accent" }] },
      { id: "301291", cells: ["301291", "明阳电气", "18%", "-2.5%", "轻仓跟踪"], actions: [{ label: "分析", icon: "🔎", tone: "accent" }] },
    ]),
    attribution: [
      { title: "盈利来源", body: "主要盈利来自 PCB 和电气设备方向的趋势持仓。", tone: "success" },
      { title: "回撤来源", body: "回撤主要来自震荡市下的仓位切换不够快。", tone: "warning" },
      { title: "风险协同", body: "高位股需要配合 AI 盯盘和实时监控一起收口风险。", tone: "accent" },
    ],
    curve: [
      { label: "开盘", value: 8 },
      { label: "上午", value: 9 },
      { label: "午后", value: 11 },
      { label: "尾盘", value: 10 },
      { label: "收盘", value: 12 },
    ],
    actions: ["调整仓位", "查看明细", "导出风险"],
  },
  "live-sim": {
    updatedAt: "2026-04-13 10:35",
    config: {
      interval: "15 分钟",
      timeframe: "30m",
      strategyMode: "自动",
      autoExecute: "开启",
      market: "CN",
      initialCapital: "100000",
    },
    status: {
      running: "运行中",
      lastRun: "10:35",
      nextRun: "10:50",
      candidateCount: "7",
    },
    metrics: [
      { label: "账户结果", value: "117932" },
      { label: "当前持仓", value: "3" },
      { label: "总收益率", value: "17.93%" },
      { label: "可用现金", value: "68499" },
    ],
    candidatePool: makeTable(["代码", "名称", "最新价"], [
      { id: "301307", cells: ["301307", "美利信", "40.31"], actions: [{ label: "分析", icon: "🔎", action: "analyze-candidate" }, { label: "删除", icon: "🗑", tone: "danger", action: "delete-candidate" }] },
      { id: "300390", cells: ["300390", "天华新能", "61.99"], actions: [{ label: "分析", icon: "🔎", action: "analyze-candidate" }, { label: "删除", icon: "🗑", tone: "danger", action: "delete-candidate" }] },
      { id: "002824", cells: ["002824", "和胜股份", "22.97"], actions: [{ label: "分析", icon: "🔎", action: "analyze-candidate" }, { label: "删除", icon: "🗑", tone: "danger", action: "delete-candidate" }] },
    ]),
    pendingSignals: [
      { title: "自动执行说明", body: "建议仓位不足买入一手时，会明确提示并跳过，不再黑盒沉默。", tone: "warning" },
      { title: "执行节奏", body: "当前候选池里 BUY/SELL 信号会优先进入执行中心，HOLD 只做观察记录。", tone: "accent" },
    ],
    executionCenter: {
      title: "执行中心",
      body: "待执行信号会放在最上方，重点解释为什么成交、为什么跳过。",
      chips: ["待执行", "信号列表", "详情"],
    },
    holdings: makeTable(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [
      { id: "002463", cells: ["002463", "沪电股份", "100", "88.50", "90.40", "+1.9%"] },
      { id: "600519", cells: ["600519", "贵州茅台", "10", "1421.00", "1453.96", "+2.3%"] },
      { id: "301291", cells: ["301291", "明阳电气", "200", "49.80", "52.87", "+6.2%"] },
    ]),
    trades: makeTable(["时间", "代码", "动作", "数量", "价格", "备注"], [
      { id: "t1", cells: ["10:16", "002463", "BUY", "100", "90.40", "自动执行"] },
      { id: "t2", cells: ["10:24", "301291", "SELL", "100", "52.87", "手工确认"] },
      { id: "t3", cells: ["10:31", "600519", "BUY", "10", "1453.96", "手工确认"] },
    ]),
    curve: [
      { label: "09:30", value: 100000 },
      { label: "10:00", value: 101200 },
      { label: "10:30", value: 102500 },
      { label: "11:00", value: 103400 },
      { label: "11:30", value: 104200 },
      { label: "14:30", value: 107300 },
    ],
  },
  "his-replay": {
    updatedAt: "2026-04-13 10:35",
    config: {
      mode: "历史区间",
      range: "2026-03-11 -> 2026-04-10",
      timeframe: "30m",
      market: "CN",
      strategyMode: "自动",
    },
    metrics: [
      { label: "回放结果", value: "17.93%" },
      { label: "最终总权益", value: "117932" },
      { label: "交易笔数", value: "43" },
      { label: "胜率", value: "45%" },
    ],
    candidatePool: makeTable(["代码", "名称", "最新价"], [
      { id: "301307", cells: ["301307", "美利信", "40.31"] },
      { id: "300390", cells: ["300390", "天华新能", "61.99"] },
      { id: "000552", cells: ["000552", "甘肃能化", "0.00"] },
    ]),
    tasks: [
      { id: "#9", status: "completed", range: "2026-03-11 -> 2026-04-10", note: "456 个检查点，133 笔成交" },
      { id: "#10", status: "running", range: "2026-04-01 -> now", note: "后台 worker 运行中" },
    ],
    tradingAnalysis: {
      title: "交易分析",
      body: "回放页会把交易分析拆成“人话结论 + 策略解释 + 量化证据”三层，不再堆太大的数字卡。",
      chips: ["已实现盈亏 22420", "平均单笔 1121", "盈亏笔数 9 / 11"],
    },
    holdings: makeTable(["代码", "名称", "数量", "成本", "现价", "浮盈亏"], [
      { id: "002463", cells: ["002463", "沪电股份", "100", "88.50", "90.40", "+1.9%"] },
      { id: "600519", cells: ["600519", "贵州茅台", "10", "1421.00", "1453.96", "+2.3%"] },
    ]),
    trades: makeTable(["时间", "代码", "动作", "数量", "价格", "备注"], [
      { id: "r1", cells: ["2026-04-10 10:30", "002463", "BUY", "100", "90.40", "自动执行"] },
      { id: "r2", cells: ["2026-04-10 11:00", "301291", "SELL", "200", "52.87", "自动执行"] },
    ]),
    signals: makeTable(["时间", "代码", "动作", "策略", "执行结果"], [
      { id: "s1", cells: ["2026-04-10 10:30", "002463", "BUY", "自动", "已执行"], actions: [{ label: "详情", icon: "🔎" }] },
      { id: "s2", cells: ["2026-04-10 11:00", "301291", "SELL", "自动", "已执行"], actions: [{ label: "详情", icon: "🔎" }] },
      { id: "s3", cells: ["2026-04-10 11:30", "600519", "HOLD", "自动", "观察"], actions: [{ label: "详情", icon: "🔎" }] },
    ]),
    curve: [
      { label: "3/11", value: 100000 },
      { label: "3/20", value: 102000 },
      { label: "3/30", value: 104500 },
      { label: "4/5", value: 109000 },
      { label: "4/10", value: 117932 },
    ],
  },
  "ai-monitor": {
    updatedAt: "2026-04-13 10:35",
    metrics: [
      { label: "盯盘队列", value: "2" },
      { label: "最新信号", value: "4" },
      { label: "观察中", value: "1" },
      { label: "通知状态", value: "在线" },
    ],
    queue: makeTable(["代码", "名称", "策略风格", "最近动作"], [
      { id: "301291", cells: ["301291", "明阳电气", "保守", "观察"] },
      { id: "002463", cells: ["002463", "沪电股份", "中性", "跟踪持仓"] },
    ]),
    signals: [
      { title: "301291 进入观察", body: "技术面偏弱，继续观察。", tags: ["观察", "技术偏弱"] },
      { title: "002463 保持中性", body: "未触发新的减仓条件。", tags: ["跟踪持仓", "中性"] },
      { title: "600519 维持防御", body: "消费防御属性增强。", tags: ["防御", "持有"] },
    ],
    timeline: [
      { time: "10:35", title: "301291 更新", body: "301291 更新为持仓跟踪，技术面偏弱，继续观察。" },
      { time: "10:42", title: "002463 跟踪", body: "002463 保持中性风格，未触发新的减仓条件。" },
    ],
    actions: ["启动", "停止", "分析", "删除"],
  },
  "real-monitor": {
    updatedAt: "2026-04-13 10:35",
    metrics: [
      { label: "监控规则", value: "3" },
      { label: "触发记录", value: "2" },
      { label: "通知通道", value: "3" },
      { label: "连接状态", value: "在线" },
    ],
    rules: [
      { title: "价格突破提醒", body: "监控上破 / 下破关键位，并把触发结果推到通知链路。", tone: "accent" },
      { title: "量价异动提醒", body: "监控量比、涨跌幅和短时波动，供实时决策参考。", tone: "warning" },
      { title: "持仓风险提醒", body: "监控持仓回撤、连续弱势和异常放量。", tone: "danger" },
    ],
    triggers: [
      { time: "10:15", title: "301291", body: "触发价格接近支撑位提醒。" },
      { time: "10:32", title: "002463", body: "量比回落，不构成新的监控动作。" },
    ],
    notificationStatus: ["钉钉在线", "邮件未启用", "桌面提醒可用"],
    actions: ["启动", "停止", "刷新", "更新规则", "删除规则"],
  },
  history: {
    updatedAt: "2026-04-13 10:35",
    metrics: [
      { label: "分析记录", value: "259" },
      { label: "最近回放", value: "完成" },
      { label: "操作轨迹", value: "3" },
      { label: "活跃任务", value: "1" },
    ],
    records: makeTable(["时间", "股票", "模式", "结论"], [
      { id: "h1", cells: ["2026-04-13 10:32", "301291 明阳电气", "单股分析", "轻仓观察"] },
      { id: "h2", cells: ["2026-04-13 09:18", "002463 沪电股份", "量化模拟", "自动买入"] },
      { id: "h3", cells: ["2026-04-12 21:42", "600519 贵州茅台", "历史回放", "17.93%"] },
    ]),
    recentReplay: {
      title: "#9 历史区间回放完成",
      body: "执行信号和成交都已落库，回放信号会继续按结果页承接展示。",
      tags: ["456 检查点", "133 笔成交", "1 只结束持仓"],
    },
    curve: [
      { label: "T-2", value: 94 },
      { label: "T-1", value: 105 },
      { label: "Today", value: 117 },
    ],
    timeline: [
      { time: "昨天", title: "发现股票链路", body: "发现股票 -> 加入我的关注 -> 推入量化候选池 -> 启动历史回放。" },
      { time: "今天", title: "工作台跟踪", body: "工作台继续跟踪，准备切换到实时量化模拟。" },
    ],
  },
  settings: {
    updatedAt: "2026-04-13 10:35",
    metrics: [
      { label: "模型配置", value: "1" },
      { label: "数据源", value: "3" },
      { label: "运行参数", value: "3" },
      { label: "通知通道", value: "2" },
    ],
    modelConfig: [
      { title: "默认模型", body: "统一使用后端环境变量中的默认模型配置，前端只承接可视化设置入口。", tone: "accent" },
      { title: "密钥状态", body: "后续会显示 API 连接状态，但不在前端暴露敏感值。", tone: "warning" },
    ],
    dataSources: [
      { title: "行情源", body: "优先展示 pytdx / Tushare / 本地数据的可用状态。", tone: "success" },
      { title: "关注池报价", body: "关注池、量化候选池和历史回放共用同一层报价信息。", tone: "accent" },
    ],
    runtimeParams: [
      { title: "日志目录", body: "所有日志统一落到 logs/。", tone: "neutral" },
      { title: "数据库目录", body: "所有数据库统一落到 data/。", tone: "neutral" },
      { title: "Docker 构建目录", body: "Docker 相关配置统一放在 build/。", tone: "neutral" },
    ],
    paths: ["logs/app.log", "data/watchlist.db", "build/nginx.conf"],
  },
};

const pageActions: Record<PageKey, Record<string, () => void>> = {
  workbench: {},
  discover: {},
  research: {},
  portfolio: {},
  "live-sim": {},
  "his-replay": {},
  "ai-monitor": {},
  "real-monitor": {},
  history: {},
  settings: {},
};

const replaceRow = (row: { id: string; cells: string[]; badges?: string[]; actions?: Array<{ label: string; icon?: string; tone?: "neutral" | "accent" | "danger" }> }) => ({
  ...row,
  actions: row.actions?.map((action) => ({ ...action })),
});

const snapshotClone = <T,>(value: T): T => clone(value);

export function mockPageSnapshot<K extends PageKey>(page: K): PageSnapshotMap[K] {
  return snapshotClone(initialState[page]);
}

export function mockRunPageAction(page: PageKey, action: string, payload?: unknown): PageSnapshotMap[PageKey] {
  switch (page) {
    case "workbench": {
      if (action === "refresh-watchlist") {
        initialState.workbench.updatedAt = "2026-04-13 10:37";
        initialState.workbench.watchlist.rows = initialState.workbench.watchlist.rows.map((row, index) => ({
          ...replaceRow(row),
          cells: [
            row.cells[0],
            row.cells[1] === "N/A" || row.cells[1] === row.id
              ? findDiscoveryCandidate(row.id)?.cells[1] ?? findResearchOutput(row.id)?.cells[1] ?? row.cells[1]
              : row.cells[1],
            (Number(row.cells[2]) + index * 0.12).toFixed(2),
            row.cells[3],
            row.cells[4],
            row.cells[5],
          ],
        }));
        ensureWatchlistMetrics();
      }
      if (action === "add-watchlist") {
        const code = normalizeCode(typeof payload === "object" && payload ? (payload as { code?: unknown }).code : payload) || "000001";
        upsertWatchlistRow(code, { status: "待分析", quantStatus: "未加入" });
        initialState.workbench.updatedAt = "2026-04-13 10:38";
      }
      if (action === "delete-watchlist") {
        const code = normalizeCode(typeof payload === "object" && payload ? (payload as { code?: unknown }).code : payload);
        if (code) {
          initialState.workbench.watchlist.rows = initialState.workbench.watchlist.rows.filter((row) => row.id !== code);
          ensureWatchlistMetrics();
          initialState.workbench.updatedAt = "2026-04-13 10:38";
        }
      }
      if (action === "batch-quant") {
        const codes = extractCodes(payload);
        const targetCodes = codes.length > 0 ? codes : initialState.workbench.watchlist.rows.map((row) => row.id);
        initialState.workbench.watchlist.rows = initialState.workbench.watchlist.rows.map((row) =>
          targetCodes.includes(row.id)
            ? {
                ...replaceRow(row),
                cells: [row.cells[0], row.cells[1], row.cells[2], row.cells[3], row.cells[4], "已入量化"],
              }
            : row,
        );
        ensureWatchlistMetrics();
        initialState.workbench.updatedAt = "2026-04-13 10:38";
      }
      if (action === "clear-selection") {
        initialState.workbench.watchlistMeta = { ...initialState.workbench.watchlistMeta, selectedCount: 0 };
      }
      if (action === "analysis") {
        const record = typeof payload === "object" && payload ? (payload as Record<string, unknown>) : {};
        const code = normalizeCode(record.stockCode ?? record.code ?? record.symbol);
        const selectedAnalysts = Array.isArray(record.analysts)
          ? record.analysts.filter((item): item is string => typeof item === "string")
          : undefined;
        setAnalysisSnapshot({
          symbol: code || initialState.workbench.analysis.symbol,
          analysts: selectedAnalysts,
          mode: typeof record.mode === "string" ? record.mode : undefined,
          cycle: typeof record.cycle === "string" ? record.cycle : undefined,
          headline: code ? `当前结论：${code} 的分析已经完成` : "当前结论：先选择一只股票再开始分析",
          decision: code
            ? `${code} 当前更适合继续观察，优先看价格是否重新站稳中期均线。`
            : "请输入股票代码后再查看分析结果。",
          summaryBody: code
            ? `围绕 ${code} 的团队分析已经生成，综合技术、基本面、资金面和风险视角后，当前更适合保持观察。`
            : "请输入股票代码后，系统会生成完整的分析结果。",
        });
        initialState.workbench.updatedAt = "2026-04-13 10:38";
      }
      if (action === "analysis-batch") {
        const codes = extractCodes(payload);
        const joined = codes.join("、");
        setAnalysisSnapshot({
          symbol: codes[0] ?? initialState.workbench.analysis.symbol,
          mode: "批量分析",
          cycle: initialState.workbench.analysis.cycle,
          headline: codes.length > 0 ? `当前结论：已完成 ${codes.length} 只股票的批量分析` : "当前结论：请选择要批量分析的股票",
          decision:
            codes.length > 0
              ? `批量分析已完成，覆盖 ${joined || "所选股票"}。可以继续筛入我的关注或推进到量化候选池。`
              : "请选择至少一只股票再进行批量分析。",
          summaryBody:
            codes.length > 0
              ? `批量分析已经完成，系统把 ${joined || "所选股票"} 的分析结果统一汇总到了股票分析面板里。`
              : "批量分析需要先选择股票。",
        });
        initialState.workbench.updatedAt = "2026-04-13 10:38";
      }
      return mockPageSnapshot("workbench");
    }
    case "discover": {
      if (action === "run-strategy") {
        initialState.discover.updatedAt = "2026-04-13 10:38";
        initialState.discover.metrics = initialState.discover.metrics.map((metric, index) =>
          index === 1 ? { ...metric, value: "38" } : metric,
        );
        initialState.discover.summary = {
          title: "发现策略已更新",
          body: "主力选股、低价擒牛和成长方向的候选结果已刷新，表格会继续支持勾选后加入我的关注。",
        };
      }
      if (action === "batch-watchlist") {
        const codes = extractCodes(payload);
        const targetCodes = codes.length > 0 ? codes : initialState.discover.candidateTable.rows.map((row) => row.id);
        targetCodes.forEach((code) => upsertWatchlistRow(code, { status: "待分析", quantStatus: "未加入" }));
        ensureWatchlistMetrics();
        initialState.discover.updatedAt = "2026-04-13 10:38";
      }
      if (action === "item-watchlist") {
        const code = normalizeCode(typeof payload === "object" && payload ? (payload as { code?: unknown }).code : payload);
        if (code) {
          upsertWatchlistRow(code, { status: "待分析", quantStatus: "未加入" });
          ensureWatchlistMetrics();
          initialState.discover.updatedAt = "2026-04-13 10:38";
        }
      }
      return mockPageSnapshot("discover");
    }
    case "research": {
      if (action === "run-module") {
        initialState.research.updatedAt = "2026-04-13 10:38";
        initialState.research.summary = {
          title: "研究情报已更新",
          body: "智策板块、龙虎榜、新闻和宏观结论都已刷新，只有明确股票输出时才允许加入我的关注。",
        };
      }
      if (action === "batch-watchlist") {
        const codes = extractCodes(payload);
        const targetCodes = codes.length > 0 ? codes : initialState.research.outputTable.rows.map((row) => row.id);
        targetCodes.forEach((code) => upsertWatchlistRow(code, { status: "待分析", quantStatus: "未加入" }));
        ensureWatchlistMetrics();
        initialState.research.updatedAt = "2026-04-13 10:38";
      }
      if (action === "item-watchlist") {
        const code = normalizeCode(typeof payload === "object" && payload ? (payload as { code?: unknown }).code : payload);
        if (code) {
          upsertWatchlistRow(code, { status: "待分析", quantStatus: "未加入" });
          ensureWatchlistMetrics();
          initialState.research.updatedAt = "2026-04-13 10:38";
        }
      }
      return mockPageSnapshot("research");
    }
    case "portfolio":
      if (action === "refresh-portfolio") {
        initialState.portfolio.updatedAt = "2026-04-13 10:38";
        initialState.portfolio.metrics = initialState.portfolio.metrics.map((metric) =>
          metric.label === "组合收益" ? { ...metric, value: "10.1%" } : metric,
        );
      }
      return mockPageSnapshot("portfolio");
    case "live-sim":
      if (action === "start") {
        initialState["live-sim"].status.running = "运行中";
        initialState["live-sim"].status.lastRun = "10:38";
      }
      if (action === "stop") {
        initialState["live-sim"].status.running = "已停止";
      }
      if (action === "reset") {
        initialState["live-sim"].metrics = initialState["live-sim"].metrics.map((metric) =>
          metric.label === "账户结果" ? { ...metric, value: "100000" } : metric,
        );
      }
      if (action === "delete-candidate") {
        const code = normalizeCode(typeof payload === "object" && payload ? (payload as { code?: unknown }).code : payload);
        if (code) {
          initialState["live-sim"].candidatePool.rows = initialState["live-sim"].candidatePool.rows.filter((row) => row.id !== code);
          initialState["live-sim"].status.candidateCount = `${initialState["live-sim"].candidatePool.rows.length}`;
        }
      }
      return mockPageSnapshot("live-sim");
    case "his-replay":
      if (action === "start" || action === "continue") {
        initialState["his-replay"].tasks = [
          ...initialState["his-replay"].tasks,
          { id: "#11", status: action === "start" ? "running" : "queued", range: "2026-04-01 -> now", note: action === "start" ? "新回放任务已创建" : "接续任务已排队" },
        ];
      }
      if (action === "cancel") {
        initialState["his-replay"].tasks = initialState["his-replay"].tasks.map((task) =>
          task.id === "#10" ? { ...task, status: "cancelled", note: "任务已取消" } : task,
        );
      }
      if (action === "delete") {
        initialState["his-replay"].tasks = initialState["his-replay"].tasks.filter((task) => task.id !== "#10");
      }
      return mockPageSnapshot("his-replay");
    case "ai-monitor":
      if (action === "start") {
        initialState["ai-monitor"].metrics = initialState["ai-monitor"].metrics.map((metric) =>
          metric.label === "通知状态" ? { ...metric, value: "在线" } : metric,
        );
      }
      if (action === "stop") {
        initialState["ai-monitor"].metrics = initialState["ai-monitor"].metrics.map((metric) =>
          metric.label === "通知状态" ? { ...metric, value: "暂停" } : metric,
        );
      }
      if (action === "analyze") {
        initialState["ai-monitor"].timeline = [
          { time: "10:50", title: "盯盘分析", body: "已生成一次新的 AI 盯盘结论。" },
          ...initialState["ai-monitor"].timeline,
        ];
      }
      if (action === "delete") {
        initialState["ai-monitor"].signals = initialState["ai-monitor"].signals.slice(0, 2);
      }
      return mockPageSnapshot("ai-monitor");
    case "real-monitor":
      if (action === "start") {
        initialState["real-monitor"].metrics = initialState["real-monitor"].metrics.map((metric) =>
          metric.label === "连接状态" ? { ...metric, value: "在线" } : metric,
        );
      }
      if (action === "stop") {
        initialState["real-monitor"].metrics = initialState["real-monitor"].metrics.map((metric) =>
          metric.label === "连接状态" ? { ...metric, value: "已停止" } : metric,
        );
      }
      if (action === "refresh") {
        initialState["real-monitor"].updatedAt = "2026-04-13 10:38";
      }
      if (action === "update-rule") {
        initialState["real-monitor"].updatedAt = "2026-04-13 10:38";
        initialState["real-monitor"].triggers = [
          { time: "10:38", title: "规则更新", body: "已同步当前规则配置。" },
          ...initialState["real-monitor"].triggers,
        ];
      }
      if (action === "delete-rule") {
        const title = typeof payload === "object" && payload ? (payload as { title?: unknown }).title : undefined;
        if (typeof title === "string" && title.trim()) {
          initialState["real-monitor"].rules = initialState["real-monitor"].rules.filter((rule) => rule.title !== title);
        } else {
          initialState["real-monitor"].rules = initialState["real-monitor"].rules.slice(0, -1);
        }
      }
      return mockPageSnapshot("real-monitor");
    case "history":
      if (action === "rerun") {
        initialState.history.metrics = initialState.history.metrics.map((metric) =>
          metric.label === "最近回放" ? { ...metric, value: "进行中" } : metric,
        );
      }
      return mockPageSnapshot("history");
    case "settings":
      if (action === "save") {
        initialState.settings.updatedAt = "2026-04-13 10:38";
      }
      return mockPageSnapshot("settings");
    default:
      return mockPageSnapshot(page);
  }
}
