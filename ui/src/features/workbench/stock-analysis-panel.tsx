import { useEffect, useMemo, useState } from "react";
import type { WorkbenchSnapshot } from "../../lib/page-models";
import { Sparkline } from "../../components/ui/sparkline";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { t } from "../../lib/i18n";

type AnalyzePayload = {
  symbol: string;
  analysts: string[];
  mode: string;
  cycle: string;
};

type BatchAnalyzePayload = {
  stockCodes: string[];
  analysts: string[];
  mode: string;
  cycle: string;
};

type StockAnalysisPanelProps = {
  analysis: WorkbenchSnapshot["analysis"];
  analysisJob?: WorkbenchSnapshot["analysisJob"];
  inputSeed?: string;
  onAnalyze: (payload: AnalyzePayload) => void;
  onBatchAnalyze: (payload: BatchAnalyzePayload) => void;
  onClearInput: () => void;
  busy?: boolean;
  busyMessage?: string;
  refreshFailure?: {
    title: string;
    body: string;
    generatedAt?: string;
  } | null;
};

const splitSymbols = (input: string) =>
  input
    .split(/[,\s;|\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);

const DECISION_FIELD_LABELS = [
  "Investment rating",
  "Target price",
  "Entry range",
  "Take-profit",
  "Stop-loss",
  "Holding period",
  "Position sizing",
  "Confidence",
] as const;

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const localizeDecisionText = (value: string) => {
  let output = value ?? "";
  for (const label of DECISION_FIELD_LABELS) {
    const pattern = new RegExp(`${escapeRegExp(label)}\\s*[:：]`, "gi");
    output = output.replace(pattern, `${t(label)}：`);
  }
  return output;
};

const localizeSummaryTitle = (value: string) => {
  const text = (value ?? "").trim();
  const match = text.match(/^(.*)\s+analysis summary$/i);
  if (match) {
    const stock = (match[1] ?? "").trim();
    return stock ? `${stock} ${t("Latest analysis summary")}` : t("Latest analysis summary");
  }
  return t(text);
};

const MetricCard = ({ label, value, hint }: { label: string; value: string; hint?: string }) => (
  <div className="mini-metric">
    <div className="mini-metric__label">{t(label)}</div>
    <div className="mini-metric__value">{value}</div>
    {hint ? <div className="mini-metric__hint">{t(hint)}</div> : null}
  </div>
);

const MODE_OPTIONS = [t("Single analysis"), t("Batch analysis")] as const;
const CYCLE_OPTIONS = ["1y", "1d", "30m"] as const;
const DEFAULT_ANALYSTS = ["technical", "fundamental", "fund_flow", "risk"];

type StageState = "waiting" | "running" | "completed";

const STAGE_LABELS = {
  analyst: t("Analyst views"),
  discussion: t("Team discussion"),
  decision: t("Final decision"),
} as const;

const resolveStageState = (
  target: keyof typeof STAGE_LABELS,
  stage: string | undefined,
  busy: boolean,
): StageState => {
  if (!busy) return "completed";
  if (stage === "completed") return "completed";
  const stageOrder = ["queued", "fetch", "enrich", "analyst", "discussion", "decision", "persist", "completed"];
  const currentIndex = stageOrder.indexOf(stage ?? "queued");
  const targetIndex = stageOrder.indexOf(target);
  if (currentIndex === -1 || targetIndex === -1) return "waiting";
  if (currentIndex === targetIndex) return "running";
  if (currentIndex > targetIndex) return "completed";
  return "waiting";
};

const StageBadge = ({ state }: { state: StageState }) => {
  if (state === "completed") {
    return <span className="analysis-stage__badge analysis-stage__badge--completed">{t("Completed")}</span>;
  }
  if (state === "running") {
    return (
      <span className="analysis-stage__badge analysis-stage__badge--running">
        <span className="analysis-stage__spinner" aria-hidden="true" />
        {t("In progress")}
      </span>
    );
  }
  return <span className="analysis-stage__badge analysis-stage__badge--waiting">{t("Waiting previous stage")}</span>;
};

const escapeHtml = (value: string) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

const formatMarkdownInline = (value: string) =>
  value
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");

const markdownToHtml = (markdown: string) => {
  const source = escapeHtml(markdown || "").replaceAll("\r\n", "\n");
  const lines = source.split("\n");
  const html: string[] = [];
  const paragraphBuffer: string[] = [];
  let inUl = false;
  let inOl = false;
  let inCode = false;
  const codeBuffer: string[] = [];

  const flushParagraph = () => {
    if (paragraphBuffer.length === 0) return;
    html.push(`<p>${formatMarkdownInline(paragraphBuffer.join("<br />"))}</p>`);
    paragraphBuffer.length = 0;
  };

  const closeLists = () => {
    if (inUl) {
      html.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      html.push("</ol>");
      inOl = false;
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (inCode) {
      if (trimmed.startsWith("```")) {
        html.push(`<pre><code>${codeBuffer.join("\n")}</code></pre>`);
        inCode = false;
        codeBuffer.length = 0;
      } else {
        codeBuffer.push(line);
      }
      continue;
    }

    if (trimmed.startsWith("```")) {
      flushParagraph();
      closeLists();
      inCode = true;
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      closeLists();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      closeLists();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${formatMarkdownInline(headingMatch[2])}</h${level}>`);
      continue;
    }

    const quoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      closeLists();
      html.push(`<blockquote>${formatMarkdownInline(quoteMatch[1])}</blockquote>`);
      continue;
    }

    const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (ulMatch) {
      flushParagraph();
      if (inOl) {
        html.push("</ol>");
        inOl = false;
      }
      if (!inUl) {
        html.push("<ul>");
        inUl = true;
      }
      html.push(`<li>${formatMarkdownInline(ulMatch[1])}</li>`);
      continue;
    }

    const olMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (olMatch) {
      flushParagraph();
      if (inUl) {
        html.push("</ul>");
        inUl = false;
      }
      if (!inOl) {
        html.push("<ol>");
        inOl = true;
      }
      html.push(`<li>${formatMarkdownInline(olMatch[1])}</li>`);
      continue;
    }

    closeLists();
    paragraphBuffer.push(trimmed);
  }

  flushParagraph();
  closeLists();

  if (inCode) {
    html.push(`<pre><code>${codeBuffer.join("\n")}</code></pre>`);
  }

  return html.join("");
};

const MarkdownBlock = ({ content, className }: { content: string; className?: string }) => {
  const html = useMemo(() => markdownToHtml(content), [content]);
  return <div className={className} dangerouslySetInnerHTML={{ __html: html }} />;
};

const resolveSelectedAnalysts = (analysts: WorkbenchSnapshot["analysis"]["analysts"]) => {
  const selected = analysts.filter((item) => item.selected).map((item) => item.value);
  return selected.length > 0 ? selected : DEFAULT_ANALYSTS;
};

export function StockAnalysisPanel({
  analysis,
  analysisJob = null,
  inputSeed = "",
  onAnalyze,
  onBatchAnalyze,
  onClearInput,
  busy = false,
  busyMessage = t("Analyzing, please wait..."),
  refreshFailure = null,
}: StockAnalysisPanelProps) {
  const [symbol, setSymbol] = useState(analysis.symbol);
  const [mode, setMode] = useState(analysis.mode);
  const [cycle, setCycle] = useState(analysis.cycle);
  const [selectedAnalysts, setSelectedAnalysts] = useState(resolveSelectedAnalysts(analysis.analysts));

  useEffect(() => {
    setSymbol(analysis.symbol);
    setMode(analysis.mode);
    setCycle(analysis.cycle);
    setSelectedAnalysts(resolveSelectedAnalysts(analysis.analysts));
  }, [analysis]);

  const analysisResults = useMemo(() => {
    const rows = Array.isArray(analysis.results) ? analysis.results.filter((item) => Boolean(item && item.symbol)) : [];
    if (rows.length > 0) {
      return rows;
    }
    return [analysis];
  }, [analysis]);
  const [activeResultSymbol, setActiveResultSymbol] = useState<string>("");

  useEffect(() => {
    if (analysisResults.length === 0) {
      setActiveResultSymbol("");
      return;
    }
    const latestSymbol = analysisResults[analysisResults.length - 1]?.symbol ?? "";
    setActiveResultSymbol(latestSymbol);
  }, [analysisResults]);

  const displayAnalysis = analysisResults.find((item) => item.symbol === activeResultSymbol) ?? analysisResults[0] ?? analysis;

  useEffect(() => {
    const codes = splitSymbols(inputSeed);
    if (codes.length === 0) return;
    setSymbol(codes.join(","));
    if (codes.length > 1) {
      setMode(t("Batch analysis"));
    }
  }, [inputSeed]);

  const analystViews = displayAnalysis.analystViews ?? [];
  const decisionInsights = displayAnalysis.insights.filter(
    (item) => !analystViews.some((view) => view.title === item.title),
  );
  const operationInsights = decisionInsights.filter((item) => item.title === t("Action advice"));
  const otherDecisionInsights = decisionInsights.filter((item) => item.title !== t("Action advice"));
  const [activeAnalystTitle, setActiveAnalystTitle] = useState<string>("");

  useEffect(() => {
    if (analystViews.length === 0) {
      setActiveAnalystTitle("");
      return;
    }
    setActiveAnalystTitle((current) =>
      analystViews.some((item) => item.title === current) ? current : analystViews[0].title,
    );
  }, [analystViews]);

  const activeAnalystView = analystViews.find((item) => item.title === activeAnalystTitle) ?? analystViews[0] ?? null;

  const stageKey = analysisJob?.stage ?? (busy ? "queued" : "completed");
  const analystStage = resolveStageState("analyst", stageKey, busy);
  const discussionStage = resolveStageState("discussion", stageKey, busy);
  const decisionStage = resolveStageState("decision", stageKey, busy);
  const hasCachedAnalysis = Boolean(displayAnalysis.generatedAt || displayAnalysis.summaryBody || analystViews.length > 0);

  const handleToggleAnalyst = (value: string) => {
    setSelectedAnalysts((current) =>
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    );
  };

  const handleSmartAnalyze = () => {
    const stockCodes = splitSymbols(symbol);
    if (stockCodes.length === 0 || selectedAnalysts.length === 0) return;
    if (stockCodes.length === 1) {
      onAnalyze({
        symbol: stockCodes[0],
        analysts: selectedAnalysts,
        mode: t("Single analysis"),
        cycle,
      });
      return;
    }
    onBatchAnalyze({
      stockCodes,
      analysts: selectedAnalysts,
      mode: t("Batch analysis"),
      cycle,
    });
  };

  const hasBatchCodes = splitSymbols(symbol).length > 0;
  const canAnalyze = hasBatchCodes && selectedAnalysts.length > 0;
  const operationAdvice = operationInsights.map((item) => item.body).filter(Boolean).join("\n\n");

  return (
    <WorkbenchCard className={busy ? "analysis-panel analysis-panel--busy" : "analysis-panel"}>
      <h2 className="section-card__title">{t("Stock analysis")}</h2>
      <p className="section-card__description">
        {t("Organized by team, config, codes, and results so one full analysis can be completed top-down.")}
      </p>

      {refreshFailure ? (
        <div className="summary-item summary-item--accent analysis-panel__refresh-notice" role="status" aria-live="polite">
          <div className="summary-item__title">{refreshFailure.title}</div>
          <div className="summary-item__body">{t("Current view stays on latest successful analysis until refresh finishes.")}</div>
          {refreshFailure.body ? <div className="summary-item__body" style={{ marginTop: "6px" }}>{refreshFailure.body}</div> : null}
          {refreshFailure.generatedAt ? (
            <div className="summary-item__meta">{t("Generate time: {time}", { time: refreshFailure.generatedAt })}</div>
          ) : null}
        </div>
      ) : null}

      <div className="summary-list">
        <section className="summary-item">
          <div className="summary-item__title">{t("1. Analysis team")}</div>
          <div className="summary-item__body">
            {t("Select perspectives first. Default lineup covers technical/fundamental/fund-flow/risk and optional news.")}
          </div>
          <div className="chip-row" style={{ marginTop: "12px" }}>
            {analysis.analysts.map((team) => (
              <button
                key={team.value}
                className={`chip${selectedAnalysts.includes(team.value) ? " chip--active" : ""}`}
                type="button"
                onClick={() => handleToggleAnalyst(team.value)}
              >
                {t(team.label)}
              </button>
            ))}
          </div>
        </section>

        <section className="summary-item">
          <div className="summary-item__title">{t("2. Analysis config")}</div>
          <div className="summary-item__body">{t("Set mode and cycle, then enter symbols to start.")}</div>
          <div className="section-grid" style={{ marginTop: "12px" }}>
            <label className="field">
              <span className="field__label">{t("Analysis mode")}</span>
              <select className="input" value={mode} onChange={(event) => setMode(event.target.value)}>
                {MODE_OPTIONS.map((option) => (
                  <option value={option} key={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">{t("Data cycle")}</span>
              <select className="input" value={cycle} onChange={(event) => setCycle(event.target.value)}>
                {CYCLE_OPTIONS.map((option) => (
                  <option value={option} key={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <section className="summary-item">
          <div className="summary-item__title">{t("3. Stock codes")}</div>
          <div className="summary-item__body">
            {t("Single code for single analysis; use comma/space/newline to separate multiple symbols.")}
          </div>
          <div className="watchlist-entry" style={{ marginTop: "12px" }}>
            <label className="field">
              <span className="field__label">{t("Code / batch codes")}</span>
              <input className="input" placeholder={analysis.inputHint} value={symbol} onChange={(event) => setSymbol(event.target.value)} />
            </label>
            <div className="watchlist-entry__actions">
              <button className="button button--primary" type="button" onClick={handleSmartAnalyze} disabled={!canAnalyze || busy}>
                {busy ? t("Starting...") : t("Start analysis")}
              </button>
              <button
                className="button button--secondary"
                type="button"
                onClick={() => {
                  setSymbol("");
                  onClearInput();
                }}
                disabled={busy}
              >
                {t("Clear input")}
              </button>
            </div>
          </div>
        </section>

        <section className="summary-item summary-item--accent">
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "12px",
              flexWrap: "wrap",
            }}
          >
            <div className="summary-item__title" style={{ marginBottom: 0 }}>
              {t("4. Analysis result")}
            </div>
            {analysisResults.length > 1 ? (
              <div className="chip-row" style={{ justifyContent: "flex-end" }}>
                {analysisResults.map((item) => (
                  <button
                    key={item.symbol}
                    type="button"
                    className={`chip${item.symbol === displayAnalysis.symbol ? " chip--active" : ""}`}
                    onClick={() => setActiveResultSymbol(item.symbol)}
                  >
                    {item.stockName ? `${item.stockName} (${item.symbol})` : item.symbol}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="summary-item__body">{t("After completion, summary, indicators, decision, and analyst views unfold in order.")}</div>

          {busy ? (
            <div className="analysis-stage-panel" role="status" aria-live="polite">
              <div className="analysis-stage-panel__header">
                <div className="analysis-stage-panel__title">{t("Current analysis progress")}</div>
                <div className="analysis-stage-panel__message">{busyMessage}</div>
              </div>
              <div className="analysis-stage-grid">
                <div className={`analysis-stage analysis-stage--${analystStage}`}>
                  <div className="analysis-stage__title">{STAGE_LABELS.analyst}</div>
                  <div className="analysis-stage__body">
                    {analystStage === "waiting" ? t("Waiting market/fundamental/fund-flow data ready.") : t("Analysts are generating individual views.")}
                  </div>
                  <StageBadge state={analystStage} />
                </div>
                <div className={`analysis-stage analysis-stage--${discussionStage}`}>
                  <div className="analysis-stage__title">{STAGE_LABELS.discussion}</div>
                  <div className="analysis-stage__body">
                    {discussionStage === "waiting" ? t("Waiting analyst outputs before team discussion.") : t("Summarizing analyst views into discussion memo.")}
                  </div>
                  <StageBadge state={discussionStage} />
                </div>
                <div className={`analysis-stage analysis-stage--${decisionStage}`}>
                  <div className="analysis-stage__title">{STAGE_LABELS.decision}</div>
                  <div className="analysis-stage__body">
                    {decisionStage === "waiting" ? t("Waiting team discussion before final decision.") : t("Compiling final conclusion, action advice, and risk notes.")}
                  </div>
                  <StageBadge state={decisionStage} />
                </div>
              </div>
              {hasCachedAnalysis ? (
                <div className="analysis-stage-panel__hint">{t("Showing latest successful analysis until new one completes.")}</div>
              ) : null}
            </div>
          ) : null}

          <div className="summary-list" style={{ marginTop: "12px" }}>
            <div className="summary-item summary-item--accent">
              <div className="summary-item__title">{localizeSummaryTitle(displayAnalysis.summaryTitle)}</div>
              <MarkdownBlock className="summary-item__body markdown-body" content={displayAnalysis.summaryBody} />
              {displayAnalysis.generatedAt ? (
                <div className="summary-item__meta">{t("Generate time: {time}", { time: displayAnalysis.generatedAt })}</div>
              ) : null}
            </div>
          </div>

          <div className="summary-list" style={{ marginTop: "12px" }}>
            <div className="summary-item">
              <div className="summary-item__title">{t("Analyst views")}</div>
            </div>
          </div>

          {analystViews.length > 0 && activeAnalystView ? (
            <div className="analyst-layout" style={{ marginTop: "12px" }}>
              <div className="analyst-layout__nav">
                {analystViews.map((insight, index) => (
                  <button
                    key={`${insight.title}-${index}`}
                    type="button"
                    className={`analyst-tab${insight.title === activeAnalystView.title ? " analyst-tab--active" : ""}`}
                    onClick={() => setActiveAnalystTitle(insight.title)}
                  >
                    {t(insight.title)}
                  </button>
                ))}
              </div>
              <div className="analyst-layout__content">
                <div className="summary-item__title">{t(activeAnalystView.title)}</div>
                <MarkdownBlock className="summary-item__body markdown-body" content={activeAnalystView.body} />
              </div>
            </div>
          ) : null}

          <div className="card-divider" />

          <div className="summary-list" style={{ marginTop: "12px" }}>
            <div className="summary-item">
              <div className="summary-item__title">{t("Quant evidence")}</div>
            </div>
          </div>

          <div className="evidence-grid" style={{ marginTop: "12px" }}>
            <div className="summary-item">
              <div className="summary-item__title">{t("Key indicators")}</div>
              {displayAnalysis.indicators.length > 0 ? (
                <div className="mini-metric-grid" style={{ marginTop: "10px" }}>
                  {displayAnalysis.indicators.map((indicator) => (
                    <MetricCard key={indicator.label} label={indicator.label} value={indicator.value} hint={indicator.hint} />
                  ))}
                </div>
              ) : (
                <div className="summary-item__body">{t("No indicator data")}</div>
              )}
            </div>
            <div className="summary-item">
              <div className="summary-item__title">{t("Trend summary")}</div>
              <Sparkline points={displayAnalysis.curve} />
            </div>
          </div>

          <div className="decision-grid" style={{ marginTop: "12px" }}>
            <div className="summary-item summary-item--accent">
              <div className="summary-item__title">{t("Final investment decision")}</div>
              <MarkdownBlock
                className="summary-item__body markdown-body"
                content={localizeDecisionText(displayAnalysis.finalDecisionText ?? displayAnalysis.decision)}
              />
            </div>
            <div className="summary-item">
              <div className="summary-item__title">{t("Operation advice")}</div>
              <MarkdownBlock
                className="summary-item__body markdown-body"
                content={operationAdvice || t("No standalone action advice. Please follow the final decision on the left.")}
              />
            </div>
          </div>

          {otherDecisionInsights.length > 0 ? (
            <div className="summary-list" style={{ marginTop: "12px" }}>
              {otherDecisionInsights.map((insight, index) => (
                <div className="summary-item" key={`${insight.title}-${index}`}>
                  <div className="summary-item__title">{t(insight.title)}</div>
                  <MarkdownBlock className="summary-item__body markdown-body" content={insight.body} />
                </div>
              ))}
            </div>
          ) : null}
        </section>
      </div>
    </WorkbenchCard>
  );
}
