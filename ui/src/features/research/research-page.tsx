import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { IconButton } from "../../components/ui/icon-button";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import { useSelection } from "../../lib/use-selection";
import type { ResearchSnapshot } from "../../lib/page-models";
import { t } from "../../lib/i18n";
import {
  BatchPromoteDialog,
  EligibleBadge,
  entryStatusOf,
  ignoreResultOverrides,
  postQuantEntryAction,
  promoteResultOverrides,
  type EntryStatusOverride,
  type QuantEntryActionResult,
} from "../quant/quant-entry-controls";

type ResearchPageProps = {
  client?: ApiClient;
};

const RESEARCH_AUTO_REFRESH_MS = 3 * 60 * 1000;

const stockDetailPath = (code: string) => `/portfolio/position/${encodeURIComponent(code)}`;

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
    return sections.filter((section) => section.title && section.body);
  }

  return note
    .split(/\n{2,}/)
    .map((segment) => segment.trim())
    .filter(Boolean)
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
  const [promotingToTrial, setPromotingToTrial] = useState(false);
  const [promoteDialogOpen, setPromoteDialogOpen] = useState(false);
  const [promoteTargetCodes, setPromoteTargetCodes] = useState<string[]>([]);
  const [entryOverrides, setEntryOverrides] = useState<Record<string, EntryStatusOverride>>({});
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [resettingList, setResettingList] = useState(false);
  const [runFeedback, setRunFeedback] = useState("");
  const [taskJob, setTaskJob] = useState<ResearchSnapshot["taskJob"]>(null);
  const [selectedModuleName, setSelectedModuleName] = useState("");
  const [tableSnapshot, setTableSnapshot] = useState<ResearchSnapshot | null>(null);
  const [outputPage, setOutputPage] = useState(1);
  const selectAllRef = useRef<HTMLInputElement | null>(null);

  const snapshot = tableSnapshot ?? resource.data;
  const searchTerm = search.trim();
  const sourceRows = snapshot?.outputTable.rows ?? [];
  const researchBusy = Boolean(taskJob && ["queued", "running"].includes(taskJob.status));
  const outputTotalRows = Number(snapshot?.outputTable.pagination?.totalRows ?? sourceRows.length);
  const outputTotalPages = Math.max(1, Number(snapshot?.outputTable.pagination?.totalPages ?? 1));
  const outputCurrentPage = Math.max(1, Number(snapshot?.outputTable.pagination?.page ?? outputPage));
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
  const rowIds = useMemo(() => sourceRows.map((row) => row.id), [sourceRows]);
  const selection = useSelection(rowIds);
  const selectedRows = sourceRows.filter((row) => selection.isSelected(row.id));
  const selectedCodes = selectedRows.map((row) => row.id);
  const canBatchWatchlist = selectedCodes.length > 0;
  const canBatchPromoteToTrial = selectedCodes.length > 0;
  const dialogPromoteCodes = promoteTargetCodes.length > 0 ? promoteTargetCodes : selectedCodes;
  const selectedPreview = selectedRows.slice(0, 3);
  const selectedPreviewLabel =
    selection.selectedCount > 0
      ? t("{count} stocks selected. Batch add to watchlist is available.", { count: selection.selectedCount })
      : t("Select stock outputs first, then batch add to watchlist.");
  const outputEmptyLabel = searchTerm
    ? t('No stock output matches "{keyword}"', { keyword: searchTerm })
    : localizeResearchText(snapshot?.outputTable.emptyLabel) || t("No stock output");
  const outputEmptyMessage =
    searchTerm && snapshot
      ? t("Try filtering by code, name, source module, or next action.")
      : localizeResearchText(snapshot?.outputTable.emptyMessage);

  const derivedMetrics = snapshot
    ? [
        { label: t("Research modules"), value: String(snapshot.modules.length) },
        { label: t("Stock outputs"), value: String(outputTotalRows) },
        { label: t("Market view"), value: String(snapshot.marketView.length) },
        { label: t("Last update"), value: snapshot.updatedAt || "--" },
      ]
    : [];
  const taskLogs = (taskJob?.logs ?? []).slice().reverse();

  useEffect(() => {
    if (!resource.data) return;
    let cancelled = false;
    void taskClient.getPageSnapshot<ResearchSnapshot>("research", {
      search: searchTerm,
      page: outputPage,
      pageSize: 20,
    }).then((next) => {
      if (!cancelled) setTableSnapshot(next);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [outputPage, resource.data, searchTerm, taskClient]);

  useEffect(() => {
    setOutputPage(1);
  }, [searchTerm]);

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

  const handleBatchPromoteToTrial = async () => {
    if (dialogPromoteCodes.length === 0 || promotingToTrial) return;
    setPromotingToTrial(true);
    try {
      const result = await postQuantEntryAction<QuantEntryActionResult>(
        "/api/v1/quant/universe/actions/promote-to-trial",
        {
          stock_codes: dialogPromoteCodes,
          source_type: "research",
        },
      );
      const updates = promoteResultOverrides(result);
      setEntryOverrides((current) => ({ ...current, ...updates }));
      setRunFeedback(t("Quant trial entry result updated."));
      setPromoteDialogOpen(false);
      setPromoteTargetCodes([]);
    } catch (error) {
      setRunFeedback(`${t("Failed")}: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setPromotingToTrial(false);
    }
  };

  const handleIgnoreAutoEntry = async (codes: string[]) => {
    if (codes.length === 0) return;
    try {
      const result = await postQuantEntryAction<QuantEntryActionResult>("/api/v1/quant/universe/actions/ignore-auto-entry", {
        stock_codes: codes,
        source_type: "research",
      });
      setEntryOverrides((current) => ({ ...current, ...ignoreResultOverrides(codes, result) }));
      setRunFeedback(t("Auto-entry candidate ignored."));
    } catch (error) {
      setRunFeedback(`${t("Failed")}: ${error instanceof Error ? error.message : String(error)}`);
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
      void taskClient.getPageSnapshot<ResearchSnapshot>("research", {
        search: searchTerm,
        page: outputPage,
        pageSize: 20,
      }).then((next) => setTableSnapshot(next)).catch(() => undefined);
    }, RESEARCH_AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [outputPage, searchTerm, taskClient]);

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
            <button
              className="button button--primary"
              type="button"
              onClick={() => {
                setPromoteTargetCodes(selectedCodes);
                setPromoteDialogOpen(true);
              }}
              disabled={!canBatchPromoteToTrial || promotingToTrial || resettingList}
            >
              纳入量化试运行
            </button>
            <button className="button button--secondary" type="button" onClick={() => void handleIgnoreAutoEntry(selectedCodes)} disabled={selectedCodes.length === 0 || resettingList}>
              忽略自动纳入
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
                  </button>
                );
              })}
            </aside>
            <section className="research-module-detail">
              {selectedModule ? (
                <div className="research-module-card research-module-card--detail">
                  <div className="research-module-card__analysis-head">
                    <h3 className="research-module-card__name">{localizeResearchText(selectedModule.name)}</h3>
                  </div>
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
            <span className="badge badge--neutral">{t("Selected output {count}", { count: outputTotalRows })}</span>
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
            <button className="button button--secondary" type="button" disabled={outputCurrentPage <= 1} onClick={() => setOutputPage((page) => Math.max(1, page - 1))}>
              ←
            </button>
            <span className="badge badge--neutral">{`第 ${outputCurrentPage} / ${outputTotalPages} 页`}</span>
            <button className="button button--secondary" type="button" disabled={outputCurrentPage >= outputTotalPages} onClick={() => setOutputPage((page) => Math.min(outputTotalPages, page + 1))}>
              →
            </button>
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
                  <th>{t("Quant status")}</th>
                  <th className="table__actions-head">{t("Actions")}</th>
                </tr>
              </thead>
              <tbody>
                {sourceRows.length === 0 ? (
                  <tr>
                    <td className="table__empty" colSpan={snapshot.outputTable.columns.length + 3}>
                      <div className="summary-item">
                        <div className="summary-item__title">{outputEmptyLabel}</div>
                        {outputEmptyMessage ? <div className="summary-item__body">{outputEmptyMessage}</div> : null}
                      </div>
                    </td>
                  </tr>
                ) : (
                  sourceRows.map((row, rowIndex) => {
                    const rowKey = `${row.id}-${String(row.source ?? row.cells[3] ?? "")}-${rowIndex}`;
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
                      {row.cells.map((cell, index) => {
                        const code = String(row.code || row.id || row.cells[0] || "").trim();
                        const content = typeof cell === "string" ? localizeResearchText(cell) : cell;
                        const shouldLink = code && (index === 0 || index === 1);
                        return (
                          <td key={`${rowKey}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                            {shouldLink ? (
                              <Link className="stock-link" to={stockDetailPath(code)} onClick={(event) => event.stopPropagation()}>
                                {content}
                              </Link>
                            ) : content}
                          </td>
                        );
                      })}
                      <td>
                        <EligibleBadge row={row} override={entryOverrides[row.id]} />
                      </td>
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
                          {entryStatusOf(row, entryOverrides[row.id]) === "eligible" ? (
                            <>
                              <button
                                className="button button--secondary"
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setPromoteTargetCodes([row.id]);
                                  setPromoteDialogOpen(true);
                                }}
                              >
                                <span>纳入 trial</span>
                              </button>
                              <button
                                className="button button--secondary"
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void handleIgnoreAutoEntry([row.id]);
                                }}
                              >
                                <span>忽略自动纳入</span>
                              </button>
                            </>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          <BatchPromoteDialog
            open={promoteDialogOpen}
            count={dialogPromoteCodes.length}
            pending={promotingToTrial}
            onCancel={() => {
              setPromoteDialogOpen(false);
              setPromoteTargetCodes([]);
            }}
            onConfirm={() => void handleBatchPromoteToTrial()}
          />
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
                      {localizeResearchText(String(row.cells[1] ?? row.id))} · {localizeResearchText(String(row.source ?? row.cells[3] ?? t("Source not marked")))}
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
