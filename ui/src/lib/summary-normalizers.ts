import type {
  DiscoveryCandidate,
  DiscoveryOverview,
  DiscoveryStrategy,
  ResearchModule,
  ResearchOverview,
  ResearchStockOutput,
  SummaryMetric,
  WatchlistRow,
  WorkbenchAnalysis,
  WorkbenchOverview,
} from "./contracts";
import { t } from "./i18n";

type AnyRecord = Record<string, unknown>;

function asObject(value: unknown): AnyRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as AnyRecord) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  return asArray(value)
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean);
}

function pickText(value: unknown, fallback = "") {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number") {
    return String(value);
  }
  return fallback;
}

function normalizeMetrics(value: unknown): SummaryMetric[] {
  return asArray(value).map((item) => {
    const record = asObject(item);
    return {
      label: asString(record.label ?? record.title ?? record.name, t("Unnamed metric")),
      value: pickText(record.value ?? record.amount ?? record.count ?? record.text, "0"),
      hint: asString(record.hint ?? record.description ?? record.note, undefined as never),
      delta: asString(record.delta, undefined as never),
    };
  });
}

function normalizeWatchlistRows(value: unknown): WatchlistRow[] {
  return asArray(value).map((item) => {
    const record = asObject(item);
    return {
      code: asString(record.code ?? record.symbol, "--"),
      name: asString(record.name ?? record.stock_name, "N/A"),
      price: pickText(record.price ?? record.latest_price ?? record.current_price, "-"),
      source: asString(record.source ?? record.origin, "manual"),
      status: asString(record.status ?? record.state, t("Pending analysis")),
      quantStatus: asString(record.quantStatus ?? record.quant_status ?? record.in_quant_pool, t("Not added")),
    };
  });
}

function normalizeWorkbenchAnalysis(value: unknown): WorkbenchAnalysis {
  const record = asObject(value);
  const evidence = asArray(record.evidence).map((item) => {
    const evidenceRecord = asObject(item);
    return {
      label: asString(evidenceRecord.label ?? evidenceRecord.title, t("Quant evidence")),
      value: asString(evidenceRecord.value ?? evidenceRecord.summary, ""),
      note: asString(evidenceRecord.note, undefined as never),
    };
  });

  return {
    symbol: asString(record.symbol ?? record.code, ""),
    name: asString(record.name ?? record.stock_name, ""),
    mode: asString(record.mode ?? record.analysisMode, t("Single analysis")),
    period: asString(record.period ?? record.timeframe, "1y"),
    analysts: asStringArray(record.analysts ?? record.team ?? record.teamMembers),
    headline: asString(record.headline ?? record.summary ?? record.verdict, t("Waiting for analysis result")),
    verdict: asString(record.verdict ?? record.action ?? record.decision, t("Pending analysis")),
    highlights: asStringArray(record.highlights ?? record.bullets ?? record.key_points),
    evidence,
    action: asString(record.action ?? record.suggestion, undefined as never),
  };
}

function normalizeNextSteps(value: unknown) {
  return asArray(value).map((item) => {
    const record = asObject(item);
    return {
      label: asString(record.label ?? record.name, t("Next step")),
      hint: asString(record.hint ?? record.description, ""),
      to: asString(record.to ?? record.path, "/main"),
      tone: (record.tone as "primary" | "neutral" | "danger" | undefined) ?? "neutral",
    };
  });
}

function normalizeDiscoveryStrategies(value: unknown): DiscoveryStrategy[] {
  return asArray(value).map((item) => {
    const record = asObject(item);
    return {
      key: asString(record.key ?? record.id, "unknown"),
      name: asString(record.name, t("Unnamed strategy")),
      note: asString(record.note ?? record.description, ""),
      status: asString(record.status ?? record.state, t("Pending run")),
      candidateCount: typeof record.candidateCount === "number" ? record.candidateCount : undefined,
    };
  });
}

function normalizeDiscoveryCandidates(value: unknown): DiscoveryCandidate[] {
  return asArray(value).map((item) => {
    const record = asObject(item);
    return {
      code: asString(record.code ?? record.symbol, "--"),
      name: asString(record.name ?? record.stock_name, "N/A"),
      industry: asString(record.industry ?? record.sector, t("Uncategorized")),
      source: asString(record.source ?? record.strategy ?? record.origin, "unknown"),
      latestPrice: pickText(record.latestPrice ?? record.latest_price ?? record.price, "-"),
      reason: asString(record.reason ?? record.note ?? record.action, ""),
    };
  });
}

function normalizeResearchModules(value: unknown): ResearchModule[] {
  return asArray(value).map((item) => {
    const record = asObject(item);
    return {
      key: asString(record.key ?? record.id, "unknown"),
      name: asString(record.name, t("Unnamed module")),
      note: asString(record.note ?? record.description, ""),
      output: asString(record.output ?? record.result, t("Research conclusion")),
    };
  });
}

function normalizeResearchStocks(value: unknown): ResearchStockOutput[] {
  return asArray(value).map((item) => {
    const record = asObject(item);
    return {
      code: asString(record.code ?? record.symbol, "--"),
      name: asString(record.name ?? record.stock_name, "N/A"),
      source: asString(record.source ?? record.module, "unknown"),
      action: asString(record.action ?? record.suggestion, t("Add to watchlist")),
      reason: asString(record.reason ?? record.note ?? record.detail, ""),
    };
  });
}

export function normalizeWorkbenchOverview(value: unknown): WorkbenchOverview {
  const record = asObject(value);
  const watchlist = asObject(record.watchlist);
  return {
    updatedAt: asString(record.updatedAt ?? record.updated_at ?? record.lastUpdated, ""),
    metrics: normalizeMetrics(record.metrics ?? record.summary_cards ?? record.summary),
    watchlist: {
      rows: normalizeWatchlistRows(watchlist.rows ?? record.watchlistRows ?? record.rows),
      emptyMessage: asString(watchlist.emptyMessage ?? record.watchlistEmptyMessage ?? record.emptyMessage, t("No stocks")),
    },
    analysis: normalizeWorkbenchAnalysis(record.analysis ?? record.stockAnalysis ?? record.currentAnalysis),
    nextSteps: normalizeNextSteps(record.nextSteps ?? record.actions ?? record.shortcuts),
  };
}

export function normalizeDiscoveryOverview(value: unknown): DiscoveryOverview {
  const record = asObject(value);
  const candidateTable = asObject(record.candidateTable);
  return {
    updatedAt: asString(record.updatedAt ?? record.updated_at ?? record.lastUpdated, ""),
    metrics: normalizeMetrics(record.metrics ?? record.summary_cards ?? record.summary),
    strategies: normalizeDiscoveryStrategies(record.strategies ?? record.strategyCards ?? record.modules),
    candidateTable: {
      rows: normalizeDiscoveryCandidates(candidateTable.rows ?? record.candidates ?? record.rows),
      summary: asString(candidateTable.summary ?? record.summaryText ?? record.subtitle, ""),
      emptyMessage: asString(candidateTable.emptyMessage ?? record.emptyMessage, t("No candidate stocks")),
    },
    highlights: asStringArray(record.highlights ?? record.notes ?? record.bullets),
  };
}

export function normalizeResearchOverview(value: unknown): ResearchOverview {
  const record = asObject(value);
  const stockOutputs = asObject(record.stockOutputs);
  return {
    updatedAt: asString(record.updatedAt ?? record.updated_at ?? record.lastUpdated, ""),
    metrics: normalizeMetrics(record.metrics ?? record.summary_cards ?? record.summary),
    modules: normalizeResearchModules(record.modules ?? record.researchModules ?? record.cards),
    marketJudgment: asStringArray(record.marketJudgment ?? record.marketView ?? record.market_judgment),
    stockOutputs: {
      rows: normalizeResearchStocks(stockOutputs.rows ?? record.outputs ?? record.rows),
      emptyMessage: asString(stockOutputs.emptyMessage ?? record.emptyMessage, t("No stock output")),
    },
    highlights: asStringArray(record.highlights ?? record.notes ?? record.bullets),
  };
}
