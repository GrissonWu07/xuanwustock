import { useEffect, useMemo, useRef, useState } from "react";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { IconButton } from "../../components/ui/icon-button";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import { useSelection } from "../../lib/use-selection";
import type { ResearchSnapshot } from "../../lib/page-models";
import { t } from "../../lib/i18n";

type ResearchPageProps = {
  client?: ApiClient;
};

type ResearchModuleWithInsights = {
  name: string;
  note: string;
  output: string;
  outputDetail: string;
  insights: {
    title: string;
    body: string;
    tone?: "neutral" | "success" | "warning" | "danger" | "accent";
  }[];
  sections: {
    title: string;
    body: string;
  }[];
};

const extractOutputCount = (output: string) => {
  const match = output.match(/(\d+)/);
  return match ? Number.parseInt(match[1], 10) : 0;
};

const RESEARCH_TASK_POLL_MAX_ROUNDS = 1800;

const extractOutputSentiment = (output: string) => {
  const pairMatch = output.match(/(\d+)\s*\/\s*(\d+)/);
  if (pairMatch) {
    const bullish = Number.parseInt(pairMatch[1], 10);
    const bearish = Number.parseInt(pairMatch[2], 10);
    return { bullish, bearish, total: bullish + bearish };
  }
  return null;
};

const getOutputScore = (output: string) => {
  const sentiment = extractOutputSentiment(output);
  if (sentiment && sentiment.total > 0) {
    return sentiment.total;
  }
  return extractOutputCount(output);
};

const getOutputTone = (output: string) => {
  if (output.includes("/")) return "warning";
  if (extractOutputCount(output) > 0) return "accent";
  return "neutral";
};

const normalizeText = (value: string) =>
  value
    .trim()
    .replace(/\s+/g, "")
    .replace(/[#*`]/g, "")
    .toLowerCase();

const isCompositeInsight = (_item: { title: string; body: string }) => false;

const hasStructuredText = (output: string) => {
  const trimmed = output.trim();
  if (!trimmed) return false;
  if (/^\s*\d+\s*\/\s*\d+\s*$/.test(trimmed)) return false;
  if (/^\s*\d+[^\n\r]*$/.test(trimmed)) return false;
  return trimmed.length >= 18 || trimmed.includes("#") || trimmed.includes("**") || trimmed.includes("---") || trimmed.includes(".");
};

const cleanStructuredText = (value: string) =>
  value
    .replace(/^\s*>\s?/gm, "")
    .replace(/^[\-*]\s+/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`/g, "")
    .trim();

const extractStructuredSections = (note: string) => {
  const lines = note.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const validLines = lines.filter((line) => line !== "---" && line !== "***");
  const sections: Array<{ title: string; body: string }> = [];
  let current: { title: string; body: string } | null = null;
  const intro: string[] = [];

  const finalizeSection = () => {
    if (current && current.body.trim()) {
      sections.push({ ...current, body: cleanStructuredText(current.body) });
    }
    current = null;
  };

  for (const line of validLines) {
    const headingMatch = line.match(/^#{1,6}\s*(.+)$/);
    if (headingMatch) {
      if (sections.length === 0 && intro.length > 0) {
        sections.push({ title: t("Market highlights"), body: cleanStructuredText(intro.join("\n")) });
        intro.length = 0;
      }
      finalizeSection();
      current = { title: cleanStructuredText(headingMatch[1]), body: "" };
      continue;
    }

    if (!current) {
      intro.push(line);
      continue;
    }
    current.body = current.body ? `${current.body}\n${line}` : line;
  }

  if (sections.length === 0 && intro.length > 0) {
    sections.push({ title: t("Market highlights"), body: cleanStructuredText(intro.join("\n")) });
  }
  if (current && (current.body || intro.length === 0)) {
    finalizeSection();
  }

  if (sections.length > 0) {
    return sections.filter((section) => section.title && section.body).slice(0, 12);
  }

  return note
    .split(/\n{2,}/)
    .map((segment) => segment.trim())
    .filter(Boolean)
    .slice(0, 8)
    .map((segment, index) => ({
      title: t("{index}) Details", { index: index + 1 }),
      body: cleanStructuredText(segment),
    }));
};

const normalizeComparableText = (value: string) =>
  cleanStructuredText(value)
    .replace(/\s+/g, "")
    .replace(/[:,.!?;'"()]/g, "")
    .toLowerCase();

const isInsightDuplicateForModule = (moduleName: string, note: string, insight: { title: string; body: string }) => {
  const normalizedModuleName = normalizeComparableText(moduleName);
  const normalizedInsightTitle = normalizeComparableText(insight.title);
  const normalizedInsightBody = normalizeComparableText(insight.body);
  const normalizedNote = normalizeComparableText(note);

  if (!normalizedInsightBody) return normalizedInsightTitle === normalizedModuleName;
  if (normalizedInsightTitle === "") return false;
  if (normalizedInsightTitle === normalizedModuleName) return true;
  if (normalizedInsightBody && normalizedInsightBody.length <= normalizedInsightTitle.length + 4 && normalizedNote.includes(normalizedInsightTitle))
    return true;
  if (normalizedInsightBody.length >= 80 && normalizedNote.includes(normalizedInsightBody.slice(0, 80))) return true;
  return normalizedNote.includes(normalizedInsightBody);
};

const isAggregateInsight = (_item: { title: string; body: string }) => false;

const buildModuleAliases = (moduleName: string) => {
  const normalized = normalizeText(moduleName);
  const aliases = new Set<string>([normalized]);
  return Array.from(aliases).filter(Boolean);
};

const moduleMatchesInsight = (moduleName: string, insight: { title: string; body: string }) => {
  const normName = normalizeText(moduleName);
  const normTitle = normalizeText(insight.title);
  if (normName === normTitle || normTitle.includes(normName) || normName.includes(normTitle)) {
    return true;
  }

  return buildModuleAliases(moduleName).some((alias) => {
    if (!alias) return false;
    return normTitle === alias || normTitle.includes(alias) || alias.includes(normTitle);
  });
};

const resolveModuleOwner = (insight: { title: string; body: string }, moduleNames: string[]) => {
  return moduleNames.find((name) => moduleMatchesInsight(name, insight));
};

const RESEARCH_TEXT_ALIASES: Record<string, string> = {
  sector: "Sector strategy",
  longhubang: "Dragon tiger list",
  "dragon tiger list": "Dragon tiger list",
  news: "News flow",
  macro: "Macro analysis",
  cycle: "Macro cycle",
};

const localizeResearchText = (value: string | undefined) => {
  const source = (value ?? "").trim();
  if (!source) return "";
  const normalized = source.toLowerCase();
  if (normalized.startsWith("dragon tiger analysis c")) {
    return t("Dragon tiger analysis completed");
  }
  const alias = RESEARCH_TEXT_ALIASES[source] ?? RESEARCH_TEXT_ALIASES[normalized] ?? source;
  const localizedAlias = t(alias);
  if (localizedAlias !== alias || alias !== source) {
    return localizedAlias;
  }
  return t(source);
};

export function ResearchPage({ client }: ResearchPageProps) {
  const taskClient = client ?? apiClient;
  const resource = usePageData("research", client);
  const [search, setSearch] = useState("");
  const [batching, setBatching] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [resettingList, setResettingList] = useState(false);
  const [runFeedback, setRunFeedback] = useState("");
  const [taskJob, setTaskJob] = useState<ResearchSnapshot["taskJob"]>(null);
  const [selectedModuleName, setSelectedModuleName] = useState("");
  const selectAllRef = useRef<HTMLInputElement | null>(null);

  const snapshot = resource.data;
  const searchTerm = search.trim();
  const normalizedSearch = searchTerm.toLowerCase();
  const sourceRows = snapshot?.outputTable.rows ?? [];
  const researchBusy = Boolean(taskJob && ["queued", "running"].includes(taskJob.status));
  const filteredRows = useMemo(
    () =>
      sourceRows.filter((row) => {
        const text = [row.id, row.reason ?? "", ...row.cells, ...(row.badges ?? [])].join(" ").toLowerCase();
        return text.includes(normalizedSearch);
      }),
    [normalizedSearch, sourceRows],
  );
  const maxOutputCount = useMemo(() => {
    if (!snapshot) return 1;
    const values = snapshot.modules.map((item) => getOutputScore(item.output));
    const maxValue = Math.max(...values, 0);
    return maxValue > 0 ? maxValue : 1;
  }, [snapshot]);
  const modulesWithInsights = useMemo<ResearchModuleWithInsights[]>(() => {
    if (!snapshot) return [];
    const outputInsights: ResearchSnapshot["marketView"] = Array.isArray(snapshot.marketView) ? snapshot.marketView : [];
    const moduleNames = snapshot.modules.map((module) => module.name);
    const seenInsight = new Set<string>();
    const insightBuckets = new Map<string, ResearchModuleWithInsights["insights"]>();

    moduleNames.forEach((name) => {
      insightBuckets.set(name, []);
    });

    outputInsights.forEach((insight: ResearchSnapshot["marketView"][number]) => {
      if (isAggregateInsight(insight) || isCompositeInsight(insight)) {
        return;
      }
      const dedupeKey = `${normalizeText(insight.title)}::${normalizeText(insight.body).slice(0, 80)}`;
      if (seenInsight.has(dedupeKey)) {
        return;
      }
      const owner = resolveModuleOwner(insight, moduleNames);
      if (!owner) {
        return;
      }
      seenInsight.add(dedupeKey);
      insightBuckets.get(owner)?.push({ ...insight, tone: insight.tone ?? "neutral" });
    });

    return snapshot.modules
      .map((module) => {
        const sections = extractStructuredSections(module.note);
        const insights = (insightBuckets.get(module.name) ?? []).filter(
          (insight) => !isInsightDuplicateForModule(module.name, module.note, insight),
        );
        return {
          ...module,
          outputDetail: module.output,
          insights,
          sections,
        };
      })
      .sort((left, right) => getOutputScore(right.output) - getOutputScore(left.output));
  }, [snapshot]);
  const selectedModule = useMemo(() => {
    if (!modulesWithInsights.length) return undefined;
    const hit = modulesWithInsights.find((module) => module.name === selectedModuleName);
    return hit ?? modulesWithInsights[0];
  }, [modulesWithInsights, selectedModuleName]);
  const rowIds = useMemo(() => filteredRows.map((row) => row.id), [filteredRows]);
  const selection = useSelection(rowIds);
  const selectedRows = filteredRows.filter((row) => selection.isSelected(row.id));
  const selectedCodes = selectedRows.map((row) => row.id);
  const canBatchWatchlist = selectedCodes.length > 0;
  const selectedPreview = selectedRows.slice(0, 3);
  const selectedPreviewLabel =
    selection.selectedCount > 0
      ? t("{count} stocks selected. Batch add to watchlist is available.", { count: selection.selectedCount })
      : t("Select stock outputs first, then batch add to watchlist.");
  const outputEmptyLabel = normalizedSearch
    ? t('No stock output matches "{keyword}"', { keyword: searchTerm })
    : localizeResearchText(snapshot?.outputTable.emptyLabel) || t("No stock output");
  const outputEmptyMessage =
    normalizedSearch && snapshot
      ? t("Try filtering by code, name, source module, or next action.")
      : localizeResearchText(snapshot?.outputTable.emptyMessage);

  const derivedMetrics = snapshot
    ? [
        { label: t("Research modules"), value: String(snapshot.modules.length) },
        { label: t("Stock outputs"), value: String(snapshot.outputTable.rows.length) },
        { label: t("Market view"), value: String(snapshot.marketView.length) },
        { label: t("Last update"), value: snapshot.updatedAt || "--" },
      ]
    : [];
  const taskLogs = (taskJob?.logs ?? []).slice().reverse();

  const handleBatchWatchlist = async () => {
    if (!canBatchWatchlist || batching) return;
    setBatching(true);
    try {
      await resource.runAction("batch-watchlist", { codes: selectedCodes });
      selection.clear();
      setRunFeedback(t("Added to watchlist"));
    } catch (error) {
      setRunFeedback(`${t("Failed")}: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBatching(false);
    }
  };

  const handleSingleWatchlist = async (code: string) => {
    try {
      await resource.runAction("item-watchlist", { code });
      setRunFeedback(t("Added to watchlist"));
    } catch (error) {
      setRunFeedback(`${t("Failed")}: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const handleRunModule = async (moduleName?: string) => {
    if (isRegenerating || researchBusy || resettingList) return;
    setIsRegenerating(true);
    setRunFeedback(t("Submitting research task..."));
    const pollTask = async (taskId: string) => {
      for (let index = 0; index < RESEARCH_TASK_POLL_MAX_ROUNDS; index += 1) {
        const latest = (await taskClient.getTaskStatus(taskId)) as ResearchSnapshot["taskJob"];
        setTaskJob(latest);
        if (latest) {
          const latestMessage = localizeResearchText(latest.message) || t("Research task running...");
          const latestProgress = typeof latest.progress === "number" ? ` (${latest.progress}%)` : "";
          setRunFeedback(`${latestMessage}${latestProgress}`);
        }
        if (latest && ["completed", "failed"].includes(latest.status)) {
          await resource.refresh();
          return latest;
        }
        await new Promise((resolve) => {
          setTimeout(resolve, 1000);
        });
      }
      await resource.refresh();
      return null;
    };
    try {
      const payload = moduleName ? { module: moduleName } : undefined;
      const result = await resource.runAction("run-module", payload);
      if (!result) {
        setRunFeedback(t("Research task submission failed. Please retry."));
        return;
      }
      const taskId = result?.taskId;
      if (taskId) {
        const finished = await pollTask(taskId);
        if (finished?.status === "completed") {
          setRunFeedback(localizeResearchText(finished.message) || t("Research refreshed."));
        } else if (finished?.status === "failed") {
          setRunFeedback(
            t("Research task failed: {message}", {
              message: localizeResearchText(finished.message) || t("Please check task logs"),
            }),
          );
        } else {
          setRunFeedback(t("Research task submitted and running in background."));
        }
        return;
      }
      if (moduleName) {
        setRunFeedback(t("Module {name} refreshed.", { name: localizeResearchText(moduleName) }));
      } else {
        setRunFeedback(t("Research refreshed."));
      }
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleResetList = async () => {
    if (resettingList || isRegenerating || researchBusy) return;
    setResettingList(true);
    try {
      await resource.runAction("reset-list");
      selection.clear();
      setSearch("");
      setSelectedModuleName("");
      setRunFeedback(t("Research list reset completed."));
    } finally {
      setResettingList(false);
    }
  };

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selection.someSelected;
    }
  }, [selection.someSelected]);

  useEffect(() => {
    setTaskJob(snapshot?.taskJob ?? null);
  }, [snapshot?.taskJob]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void resource.refresh();
    }, 5 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [resource.refresh]);

  if (resource.status === "loading" && !snapshot) {
    return <PageLoadingState title={t("Research loading...")} description={t("Loading sector, dragon-tiger list, news, and macro view.")} />;
  }

  if (resource.status === "error" && !snapshot) {
    return (
      <PageErrorState
        title={t("Research failed to load")}
        description={resource.error ?? t("Unable to load research data. Please retry later.")}
        actionLabel={t("Refresh")}
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title={t("Research has no data")} description={t("Backend has not returned a research snapshot yet.")} actionLabel={t("Refresh")} onAction={resource.refresh} />;
  }

  return (
    <div>
      <PageHeader
        eyebrow={t("Research")}
        title={t("Research")}
        description={localizeResearchText("Aggregate sector strategy, dragon-tiger list, news flow, macro analysis, and macro cycle in one page.")}
        actions={
          <>
            <button className="button button--secondary" type="button" onClick={() => void handleRunModule()} disabled={isRegenerating || researchBusy || resettingList}>
              {isRegenerating || researchBusy ? t("Regenerating...") : t("Regenerate")}
            </button>
            <button className="button button--secondary" type="button" onClick={() => void handleResetList()} disabled={isRegenerating || researchBusy || resettingList}>
              {resettingList ? t("Resetting...") : t("Reset list")}
            </button>
            <button className="button button--primary" type="button" onClick={() => void handleBatchWatchlist()} disabled={!canBatchWatchlist || batching || resettingList}>
              {t("Add selected to watchlist")}
            </button>
          </>
        }
      />
      <div className="stack">
        <div className="metric-grid">
          {derivedMetrics.map((metric) => (
            <WorkbenchCard className="metric-card" key={metric.label}>
              <div className="metric-card__label">{metric.label}</div>
              <div className="metric-card__value">{metric.value}</div>
            </WorkbenchCard>
          ))}
        </div>

        <WorkbenchCard>
          <h2 className="section-card__title">{t("Module analysis")}</h2>
          <p className="section-card__description">{localizeResearchText(snapshot.summary.title)}</p>
          {runFeedback ? <div className="discover-candidate-toolbar__feedback">{runFeedback}</div> : null}
          {taskJob ? (
            <div className="summary-list" style={{ marginTop: "10px" }}>
              <div className="summary-item">
                <div className="summary-item__title">{t("Task status")}</div>
                <div className="summary-item__body">
                  {t("Status {status} · Stage {stage} · Progress {progress}%", {
                    status: localizeResearchText(taskJob.status || "running"),
                    stage: localizeResearchText(taskJob.stage || "--"),
                    progress: String(taskJob.progress ?? 0),
                  })}
                </div>
                <div className="summary-item__body">{localizeResearchText(taskJob.message)}</div>
                {taskLogs.length > 0 ? (
                  <div style={{ marginTop: "10px", maxHeight: "170px", overflowY: "auto" }}>
                    {taskLogs.map((log, index) => (
                      <div key={`${log.time}-${index}`} className="summary-item__body" style={{ marginBottom: "6px" }}>
                        [{log.time}] {localizeResearchText(log.stage)} · {localizeResearchText(log.message)}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
          <div className="research-module-layout">
            <aside className="research-module-list" aria-label={t("Research module list")}>
              {modulesWithInsights.map((module) => {
                const isActive = module.name === selectedModule?.name;
                return (
                  <button
                    key={module.name}
                    className={`research-module-list__item ${isActive ? "is-active" : ""}`}
                    type="button"
                    onClick={() => setSelectedModuleName(module.name)}
                  >
                    <div className="research-module-list__title">{localizeResearchText(module.name)}</div>
                    <div className="research-module-list__output">{localizeResearchText(module.output)}</div>
                  </button>
                );
              })}
            </aside>
            <section className="research-module-detail">
              {selectedModule ? (
                <div className="research-module-card research-module-card--detail">
                  <div className="research-module-card__output">
                    <div className="research-module-card__output-meta">
                      <span>{t("Output visualization")}</span>
                      <span>{localizeResearchText(selectedModule.output)}</span>
                    </div>
                    <div className="research-module-card__meter-track">
                      {(() => {
                        const sentiment = extractOutputSentiment(selectedModule.output);
                        if (sentiment) {
                          const normalizer = Math.max(maxOutputCount, sentiment.total, 1);
                          const bullishRate = Math.max(4, Math.round((sentiment.bullish / normalizer) * 100));
                          const bearishRate = Math.max(4, Math.round((sentiment.bearish / normalizer) * 100));
                          const neutralRate = Math.max(0, 100 - bullishRate - bearishRate);
                          return (
                            <>
                              <div
                                className="research-module-card__meter-fill research-module-card__meter-fill--accent"
                                style={{ width: `${Math.min(100, bullishRate)}%` }}
                                title={t("Bullish {count}", { count: sentiment.bullish })}
                              />
                              <div
                                className="research-module-card__meter-track-separator"
                                style={{ width: `${neutralRate}px` }}
                              />
                              <div
                                className="research-module-card__meter-fill research-module-card__meter-fill--muted"
                                style={{ width: `${Math.min(100, bearishRate)}%` }}
                                title={t("Bearish {count}", { count: sentiment.bearish })}
                              />
                            </>
                          );
                        }

                        const ratio = Math.max(
                          6,
                          Math.round((extractOutputCount(selectedModule.output) / maxOutputCount) * 100),
                        );
                        return <div className="research-module-card__meter-fill" style={{ width: `${ratio}%` }} />;
                      })()}
                    </div>
                  </div>
                  <div className="research-module-card__divider" />
                  <div className="research-module-card__header">
                    <div>
                      <h3 className="research-module-card__name">{localizeResearchText(selectedModule.name)}</h3>
                      <div className="research-module-card__note">
                        {selectedModule.sections.length > 0 ? t("Full analysis expanded. See thematic details below.") : localizeResearchText(selectedModule.note)}
                      </div>
                    </div>
                    <span className={`badge badge--${getOutputTone(selectedModule.output)}`}>{localizeResearchText(selectedModule.output)}</span>
                  </div>
                  <div className="research-module-card__divider" />
                  <div className="research-module-card__insight-title">{t("Top-level result")}</div>
                  {selectedModule.sections.length > 0 ? (
                    <div className="research-module-card__insight-list">
                      {selectedModule.sections.map((section, index) => (
                        <div className="research-module-card__insight-item" key={`${section.title}-${index}`}>
                          <div className="research-module-card__insight-item-title">{localizeResearchText(section.title)}</div>
                          <div className="research-module-card__insight-item-body">{section.body}</div>
                        </div>
                      ))}
                    </div>
                  ) : selectedModule.note && hasStructuredText(selectedModule.note) ? (
                    <div className="research-module-card__detail-body">{localizeResearchText(selectedModule.note)}</div>
                  ) : selectedModule.note ? (
                    <p className="research-module-card__empty-note">{localizeResearchText(selectedModule.note)}</p>
                  ) : selectedModule.outputDetail ? (
                    <p className="research-module-card__empty-note">{localizeResearchText(selectedModule.outputDetail)}</p>
                  ) : (
                    <p className="research-module-card__empty-note">{t("No structured detail for this module yet.")}</p>
                  )}
                  {selectedModule.insights.length > 0 ? (
                    <>
                      <div className="research-module-card__divider" />
                      <div className="research-module-card__insight-title">{t("Additional insights")}</div>
                      <div className="research-module-card__insight-list">
                        {selectedModule.insights.map((insight, index) => (
                          <div className="research-module-card__insight-item" key={`${insight.title}-${index}`}>
                            <div className="research-module-card__insight-item-title">{localizeResearchText(insight.title)}</div>
                            <div className="research-module-card__insight-item-body">{localizeResearchText(insight.body)}</div>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : null}
                </div>
              ) : null}
            </section>
          </div>
        </WorkbenchCard>

        <WorkbenchCard>
          <h2 className="section-card__title">{t("Research summary")}</h2>
          <p className="section-card__description">{localizeResearchText(snapshot.summary.body)}</p>
          <div className="summary-list">
            <div className="summary-item">
              <div className="summary-item__title">{t("Summary")}</div>
              <div className="summary-item__body">{localizeResearchText(snapshot.summary.title)}</div>
            </div>
          </div>
        </WorkbenchCard>

        <WorkbenchCard>
          <div className="toolbar">
            <div>
              <h2 className="section-card__title" style={{ margin: 0 }}>
                {t("Stock outputs")}
              </h2>
              <p className="table__caption" style={{ marginBottom: 0 }}>
                {t("Watchlist actions appear only when a module outputs explicit stocks.")}
              </p>
            </div>
            <span className="toolbar__spacer" />
            <label className="field" style={{ minWidth: "260px" }}>
              <span className="field__label">{t("Search output")}</span>
              <input
                className="input"
                data-size="compact-input"
                placeholder={t("Input code, name, source, or reason")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <span className="badge badge--neutral">{t("Selected output {count}", { count: filteredRows.length })}</span>
            <span className="badge badge--accent">{t("Selected {count} stocks", { count: selection.selectedCount })}</span>
          </div>
          <div className="toolbar" style={{ marginTop: "10px" }}>
            <IconButton
              icon="↻"
              label={isRegenerating ? t("Running...") : t("Refresh research")}
              tone="neutral"
              disabled={isRegenerating || researchBusy || resettingList}
              onClick={() => void handleRunModule(selectedModule?.name)}
            />
            <IconButton
              icon="🗑"
              label={resettingList ? t("Resetting...") : t("Reset list")}
              tone="danger"
              onClick={() => void handleResetList()}
              disabled={isRegenerating || researchBusy || resettingList}
            />
            <IconButton
              icon="⭐"
              label={t("Add selected to watchlist")}
              tone="accent"
              onClick={() => void handleBatchWatchlist()}
              disabled={!canBatchWatchlist || batching || resettingList}
            />
            <IconButton icon="✕" label={t("Clear selection")} tone="neutral" onClick={selection.clear} />
            <span className="toolbar__status">{t("Selected {count} stocks", { count: selection.selectedCount })}</span>
          </div>
          <div className="table-shell">
            <table className="table">
              <thead>
                <tr>
                  <th className="table__checkbox-cell">
                    <input
                      ref={selectAllRef}
                      type="checkbox"
                      aria-label={t("Select all current research outputs")}
                      checked={selection.allSelected}
                      onChange={selection.toggleAll}
                    />
                </th>
                  {snapshot.outputTable.columns.map((column) => (
                    <th key={column}>{localizeResearchText(column)}</th>
                  ))}
                  <th className="table__actions-head">{t("Actions")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.length === 0 ? (
                  <tr>
                    <td className="table__empty" colSpan={snapshot.outputTable.columns.length + 2}>
                      <div className="summary-item">
                        <div className="summary-item__title">{outputEmptyLabel}</div>
                        {outputEmptyMessage ? <div className="summary-item__body">{outputEmptyMessage}</div> : null}
                      </div>
                    </td>
                  </tr>
                ) : (
                  filteredRows.map((row, rowIndex) => {
                    const rowKey = `${row.id}-${String(row.cells[2] ?? row.source ?? "")}-${rowIndex}`;
                    return (
                    <tr
                      key={rowKey}
                      className={selection.isSelected(row.id) ? "table__row--selected" : undefined}
                      onClick={() => selection.toggle(row.id)}
                    >
                      <td className="table__checkbox-cell" onClick={(event) => event.stopPropagation()}>
                        <input
                          type="checkbox"
                          aria-label={t("Select {name}", { name: String(row.cells[1] ?? row.id) })}
                          checked={selection.isSelected(row.id)}
                          onChange={() => selection.toggle(row.id)}
                        />
                      </td>
                      {row.cells.map((cell, index) => (
                        <td key={`${rowKey}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                          {typeof cell === "string" ? localizeResearchText(cell) : cell}
                        </td>
                      ))}
                      <td>
                        <div className="table__actions">
                          <button
                            className="button button--secondary"
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleSingleWatchlist(row.id);
                            }}
                          >
                            <span aria-hidden="true">{row.actions?.[0]?.icon ?? "⭐"}</span>
                            <span>{localizeResearchText(row.actions?.[0]?.label) || t("Add to watchlist")}</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </WorkbenchCard>

        <WorkbenchCard>
          <h2 className="section-card__title">{t("Latest result summary")}</h2>
          <p className="section-card__description">{localizeResearchText(snapshot.summary.body)}</p>
          <div className="summary-list">
            <div className="summary-item">
              <div className="summary-item__title">{localizeResearchText(snapshot.summary.title)}</div>
              <div className="summary-item__body">{t("Snapshot updated at: {time}", { time: snapshot.updatedAt })}</div>
            </div>
          </div>
          <div className="chip-row">
            {snapshot.modules.map((module) => (
              <span className="badge badge--neutral" key={module.name}>
                {localizeResearchText(module.name)} · {localizeResearchText(module.output)}
              </span>
            ))}
          </div>
          <div className="card-divider" />
          <div className="summary-list">
            <div className="summary-item">
              <div className="summary-item__title">{t("Current step")}</div>
              <div className="summary-item__body">
                {selectedRows.length > 0 ? selectedPreviewLabel : t("Research defaults to market view; watchlist add appears only with explicit stock outputs.")}
              </div>
              {selectedPreview.length > 0 ? (
                <div className="chip-row" style={{ marginTop: "10px" }}>
                  {selectedPreview.map((row, previewIndex) => (
                    <span className="badge badge--neutral" key={`${row.id}-${previewIndex}`}>
                      {localizeResearchText(String(row.cells[1] ?? row.id))} · {localizeResearchText(String(row.cells[2] ?? row.source ?? t("Source not marked")))}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </WorkbenchCard>
      </div>
    </div>
  );
}
