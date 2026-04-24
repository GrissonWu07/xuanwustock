export type PageKey =
  | "workbench"
  | "discover"
  | "research"
  | "portfolio"
  | "live-sim"
  | "his-replay"
  | "ai-monitor"
  | "real-monitor"
  | "history"
  | "settings";

export type SummaryMetric = {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "warning" | "danger";
  hint?: string;
};

export type BadgeTone = "neutral" | "success" | "warning" | "danger" | "accent";

export type Insight = {
  title: string;
  body: string;
  tone?: BadgeTone;
};

export type ConfigSettingItem = Insight & {
  key?: string;
  value?: string;
  hint?: string;
  required?: boolean;
  type?: "text" | "password" | "boolean" | "select" | string;
  options?: string[];
};

export type TimelineItem = {
  time: string;
  title: string;
  body: string;
};

export type TableAction = {
  label: string;
  icon?: string;
  tone?: "neutral" | "accent" | "danger";
  action?: string;
};

export type TableRow = {
  id: string;
  cells: string[];
  badges?: string[];
  actions?: TableAction[];
  code?: string;
  name?: string;
  industry?: string;
  source?: string;
  latestPrice?: string;
  reason?: string;
  selectedAt?: string;
};

export type TableSection = {
  columns: string[];
  rows: TableRow[];
  emptyLabel?: string;
  emptyMessage?: string;
  pagination?: {
    page: number;
    pageSize: number;
    totalRows: number;
    totalPages: number;
  };
};

export type SelectableOption = {
  label: string;
  value: string;
  selected?: boolean;
};

export type ChartPoint = {
  label: string;
  value: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
};

export type ActionTile = {
  label: string;
  hint: string;
  href: string;
};

export type TaskStatus = "idle" | "queued" | "running" | "completed" | "failed";

export type TaskJob = {
  id: string;
  status: TaskStatus;
  title: string;
  message: string;
  stage?: string;
  progress?: number;
  symbol?: string;
  stockCodes?: string[];
  completedSymbols?: string[];
  failedSymbols?: string[];
  resultCount?: number;
  startedAt?: string;
  updatedAt?: string;
  logs?: {
    time: string;
    stage: string;
    message: string;
  }[];
};

export type WorkbenchAnalysisResult = {
  symbol: string;
  stockName?: string;
  analysts?: SelectableOption[];
  mode?: string;
  cycle?: string;
  inputHint?: string;
  summaryTitle: string;
  summaryBody: string;
  generatedAt?: string;
  indicators: SummaryMetric[];
  decision: string;
  finalDecisionText?: string;
  insights: Insight[];
  analystViews?: Insight[];
  curve: ChartPoint[];
};

export type WorkbenchSnapshot = {
  taskId?: string;
  updatedAt: string;
  metrics: SummaryMetric[];
  watchlist: TableSection;
  watchlistMeta: {
    selectedCount: number;
    quantCount: number;
    refreshHint: string;
  };
  analysis: {
    symbol: string;
    stockName?: string;
    analysts: SelectableOption[];
    mode: string;
    cycle: string;
    inputHint: string;
    summaryTitle: string;
    summaryBody: string;
    generatedAt?: string;
    indicators: SummaryMetric[];
    decision: string;
    finalDecisionText?: string;
    insights: Insight[];
    analystViews?: Insight[];
    curve: ChartPoint[];
    results?: WorkbenchAnalysisResult[];
  };
  analysisJob?: TaskJob | null;
  nextSteps: ActionTile[];
  activity: TimelineItem[];
};

export type DiscoverSnapshot = {
  taskId?: string;
  updatedAt: string;
  metrics: SummaryMetric[];
  strategies: {
    key: string;
    name: string;
    note: string;
    status: string;
    highlight?: string;
  }[];
  summary: {
    title: string;
    body: string;
  };
  candidateTable: TableSection;
  recommendation: {
    title: string;
    body: string;
    chips: string[];
  };
  taskJob?: TaskJob | null;
};

export type ResearchSnapshot = {
  taskId?: string;
  updatedAt: string;
  modules: {
    name: string;
    note: string;
    output: string;
  }[];
  marketView: Insight[];
  outputTable: TableSection;
  summary: {
    title: string;
    body: string;
  };
  taskJob?: TaskJob | null;
};

export type PortfolioSnapshot = {
  taskId?: string;
  updatedAt: string;
  metrics: SummaryMetric[];
  holdings: TableSection;
  attribution: Insight[];
  curve: ChartPoint[];
  actions: string[];
  selectedSymbol?: string;
  detail?: {
    symbol: string;
    stockName: string;
    sector: string;
    kline: ChartPoint[];
    indicators: SummaryMetric[];
    pendingSignals: TableSection;
    decision: {
      rating: string;
      summary: string;
      updatedAt: string;
    };
    positionForm: {
      quantity: string;
      costPrice: string;
      takeProfit: string;
      stopLoss: string;
      note: string;
    };
  };
  indicatorRefresh?: {
    updatedAt: string;
    scope: string;
    symbols: string[];
  };
  portfolioDecision?: {
    action: string;
    targetExposurePct: string;
    summary: string;
    bullishCount?: number;
    neutralCount?: number;
    bearishCount?: number;
    score?: number;
    reasons?: string[];
  };
  marketNews?: {
    title: string;
    body: string;
    source?: string;
    time?: string;
    url?: string;
  }[];
  portfolioAnalysisJob?: TaskJob | null;
};

export type LiveSimSnapshot = {
  updatedAt: string;
  config: {
    interval: string;
    timeframe: string;
    strategyMode: string;
    strategyProfileId?: string;
    aiDynamicStrategy?: string;
    aiDynamicStrength?: string;
    aiDynamicLookback?: string;
    strategyProfiles?: {
      id: string;
      name: string;
      enabled: boolean;
      isDefault: boolean;
    }[];
    autoExecute: string;
    market: string;
    initialCapital: string;
    commissionRatePct?: string;
    sellTaxRatePct?: string;
  };
  status: {
    running: string;
    lastRun: string;
    nextRun: string;
    candidateCount: string;
  };
  metrics: SummaryMetric[];
  candidatePool: TableSection;
  pendingSignals: Insight[];
  executionCenter: {
    title: string;
    body: string;
    chips: string[];
  };
  holdings: TableSection;
  trades: TableSection;
  curve: ChartPoint[];
};

export type ReplaySnapshot = {
  updatedAt: string;
  config: {
    mode: string;
    range: string;
    timeframe: string;
    market: string;
    strategyMode: string;
    strategyProfileId?: string;
    aiDynamicStrategy?: string;
    aiDynamicStrength?: string;
    aiDynamicLookback?: string;
    strategyProfiles?: {
      id: string;
      name: string;
      enabled: boolean;
      isDefault: boolean;
    }[];
    commissionRatePct?: string;
    sellTaxRatePct?: string;
  };
  metrics: SummaryMetric[];
  candidatePool: TableSection;
  tasks: {
    id: string;
    runId?: string;
    status: string;
    stage?: string;
    progress?: number;
    progressCurrent?: number;
    progressTotal?: number;
    checkpointCount?: number;
    latestCheckpointAt?: string;
    startAt?: string;
    endAt?: string;
    range: string;
    mode?: string;
    timeframe?: string;
    market?: string;
    strategyMode?: string;
    note?: string;
    returnPct?: string;
    finalEquity?: string;
    cashValue?: string;
    marketValue?: string;
    realizedPnl?: string;
    unrealizedPnl?: string;
    tradeCount?: string;
    winRate?: string;
    sellWinRate?: string;
    buyTradeCount?: number;
    sellTradeCount?: number;
    winningSellCount?: number;
    losingSellCount?: number;
    avgWin?: string;
    avgLoss?: string;
    payoffRatio?: string;
    strategyProfileId?: string;
    strategyProfileName?: string;
    strategyProfileVersionId?: string;
    holdings?: TableRow[];
  }[];
  tradingAnalysis: {
    title: string;
    body: string;
    chips: string[];
  };
  holdings: TableSection;
  trades: TableSection;
  signals: TableSection;
  curve: ChartPoint[];
};

export type AiMonitorSnapshot = {
  updatedAt: string;
  metrics: SummaryMetric[];
  queue: TableSection;
  signals: {
    title: string;
    body: string;
    tags: string[];
  }[];
  timeline: TimelineItem[];
  actions?: string[];
};

export type RealMonitorSnapshot = {
  updatedAt: string;
  metrics: SummaryMetric[];
  rules: Insight[];
  triggers: TimelineItem[];
  notificationStatus: string[];
  actions?: string[];
};

export type HistorySnapshot = {
  updatedAt: string;
  metrics: SummaryMetric[];
  records: TableSection;
  recentReplay: {
    title: string;
    body: string;
    tags: string[];
  };
  curve?: ChartPoint[];
  timeline: TimelineItem[];
};

export type SettingsSnapshot = {
  updatedAt?: string;
  metrics?: SummaryMetric[];
  dataSources: ConfigSettingItem[];
  modelConfig: ConfigSettingItem[];
  runtimeParams: ConfigSettingItem[];
  strategyProfiles?: {
    id: string;
    name: string;
    description?: string;
    enabled: boolean;
    isDefault: boolean;
    updatedAt?: string;
    latestVersionId?: string;
    latestVersion?: string;
    config?: Record<string, unknown>;
  }[];
  selectedStrategyProfileId?: string;
};

export type PageSnapshotMap = {
  workbench: WorkbenchSnapshot;
  discover: DiscoverSnapshot;
  research: ResearchSnapshot;
  portfolio: PortfolioSnapshot;
  "live-sim": LiveSimSnapshot;
  "his-replay": ReplaySnapshot;
  "ai-monitor": AiMonitorSnapshot;
  "real-monitor": RealMonitorSnapshot;
  history: HistorySnapshot;
  settings: SettingsSnapshot;
};
