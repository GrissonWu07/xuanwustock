import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { SectionEmptyState } from "../../components/ui/section-empty";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { Insight } from "../../lib/page-models";
import { usePageData } from "../../lib/use-page-data";
import { t } from "../../lib/i18n";

type RealMonitorPageProps = {
  client?: ApiClient;
};

type RuleTone = NonNullable<Insight["tone"]>;

const TONE_OPTIONS: { value: RuleTone; label: string }[] = [
  { value: "accent", label: t("信息") },
  { value: "warning", label: t("警告") },
  { value: "danger", label: t("严重") },
];

const badgeToneFromRule = (tone?: RuleTone) => {
  if (tone === "warning" || tone === "danger") return tone;
  return "neutral";
};

export function RealMonitorPage({ client }: RealMonitorPageProps) {
  const resource = usePageData("real-monitor", client);
  const snapshot = resource.data;
  const snapshotVersion = snapshot?.updatedAt ?? "loading";
  const initialRules = useMemo(() => snapshot?.rules ?? [], [snapshotVersion]);
  const [rules, setRules] = useState<Insight[]>(() => initialRules);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [ruleTitle, setRuleTitle] = useState("");
  const [ruleBody, setRuleBody] = useState("");
  const [ruleTone, setRuleTone] = useState<RuleTone>("accent");

  useEffect(() => {
    setRules(initialRules);
    if (initialRules.length === 0) {
      setSelectedIndex(0);
      return;
    }
    setSelectedIndex((current) => Math.min(current, initialRules.length - 1));
  }, [initialRules, snapshotVersion]);

  const renderRules = rules.length > 0 ? rules : initialRules;
  const currentRule = useMemo(() => renderRules[selectedIndex] ?? renderRules[0], [renderRules, selectedIndex]);

  useEffect(() => {
    if (renderRules.length === 0) {
      setRuleTitle("");
      setRuleBody("");
      setRuleTone("accent");
      return;
    }

    const nextRule = currentRule ?? renderRules[0];
    if (!nextRule) return;

    setRuleTitle(nextRule.title);
    setRuleBody(nextRule.body);
    setRuleTone((nextRule.tone ?? "accent") as RuleTone);
  }, [currentRule, renderRules]);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title={t("实时监控加载中")} description={t("正在读取监控规则、触发记录和通知状态。")} />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title={t("实时监控加载失败")}
        description={resource.error ?? t("无法加载实时监控数据，请稍后重试。")}
        actionLabel={t("重新加载")}
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title={t("实时监控暂无数据")} description={t("后台尚未返回实时监控快照。")} actionLabel={t("刷新")} onAction={resource.refresh} />;
  }

  const saveRule = async () => {
    if (!currentRule) return;
    const payload = {
      index: selectedIndex,
      title: (ruleTitle || currentRule.title).trim(),
      body: (ruleBody || currentRule.body).trim(),
      tone: ruleTone ?? currentRule.tone ?? "accent",
    };
    setRules((current) =>
      (current.length > 0 ? current : initialRules).map((rule, index) =>
        index === selectedIndex
          ? {
              title: payload.title || rule.title,
              body: payload.body || rule.body,
              tone: payload.tone,
            }
          : rule,
      ),
    );
    await resource.runAction("update-rule", payload);
  };

  const deleteRule = async () => {
    if (!currentRule) return;
    const sourceRules = renderRules;
    const targetRule = sourceRules[selectedIndex];
    const nextRules = sourceRules.filter((_, index) => index !== selectedIndex);
    setRules(nextRules);
    const nextIndex = Math.max(0, Math.min(selectedIndex, nextRules.length - 1));
    setSelectedIndex(nextIndex);
    const nextRule = nextRules[nextIndex];
    if (nextRule) {
      setRuleTitle(nextRule.title);
      setRuleBody(nextRule.body);
      setRuleTone((nextRule.tone ?? "accent") as RuleTone);
    } else {
      setRuleTitle("");
      setRuleBody("");
      setRuleTone("accent");
    }
    await resource.runAction("delete-rule", { index: selectedIndex, title: targetRule?.title });
  };

  return (
    <div>
      <PageHeader eyebrow="Monitor" title={t("实时监控")} description={t("价格监控、规则提醒和通知状态会在这里保持为一个更清爽的实时工作台。")} />
      <div className="stack">
        <WorkbenchCard>
          <h2 className="section-card__title">{t("快照概览")}</h2>
          <p className="section-card__description">
            {t("监控规则、触发记录和通知状态都来自同一份快照，规则保存后会同步回写当前页面状态。")}</p>
          <div className="mini-metric-grid">
            <div className="mini-metric">
              <div className="mini-metric__label">{t("快照更新时间")}</div>
              <div className="mini-metric__value">{snapshot.updatedAt}</div>
            </div>
            <div className="mini-metric">
              <div className="mini-metric__label">{t("监控规则")}</div>
              <div className="mini-metric__value">{renderRules.length}</div>
            </div>
            <div className="mini-metric">
              <div className="mini-metric__label">{t("通知状态")}</div>
              <div className="mini-metric__value">{snapshot.notificationStatus.length}</div>
            </div>
          </div>
          <div className="card-divider" />
          <SectionEmptyState
            title={t("可用动作")}
            description={snapshot.actions && snapshot.actions.length > 0 ? t("以下动作与实时监控的运行控制和规则维护直接对应。") : t("当前没有可用动作。")}
          >
            {snapshot.actions && snapshot.actions.length > 0 ? (
              snapshot.actions.map((action) => (
                <span className="badge badge--neutral" key={action}>
                  {action}
                </span>
              ))
            ) : (
              <span className="badge badge--neutral">{t("暂无动作")}</span>
            )}
          </SectionEmptyState>
        </WorkbenchCard>

        <div className="metric-grid">
          {snapshot.metrics.map((metric) => (
            <WorkbenchCard className="metric-card" key={metric.label}>
              <div className="metric-card__label">{metric.label}</div>
              <div className="metric-card__value">{metric.value}</div>
            </WorkbenchCard>
          ))}
        </div>

        <WorkbenchCard>
          <div className="toolbar">
            <div>
              <h2 className="section-card__title">{t("规则编辑器")}</h2>
              <p className="section-card__description" style={{ marginBottom: 0 }}>
                {t("选择一条监控规则后，直接编辑名称、说明和提醒级别，再保存或删除。")}</p>
            </div>
            <span className="toolbar__spacer" />
            <button className="button button--secondary" type="button" onClick={resource.refresh}>
              {t("刷新状态")}</button>
          </div>

          <div className="section-grid">
            <div className="summary-list">
              <div className="summary-item summary-item--accent">
                <div className="summary-item__title">{t("规则列表")}</div>
                <div className="chip-row">
                  {renderRules.length === 0 ? (
                    <div className="summary-item__body">{t("当前没有可编辑的监控规则")}</div>
                  ) : (
                    renderRules.map((rule, index) => (
                      <button
                        key={rule.title}
                        className={`chip${index === selectedIndex ? " chip--active" : ""}`}
                        type="button"
                        onClick={() => setSelectedIndex(index)}
                      >
                        {rule.title}
                      </button>
                    ))
                  )}
                </div>
              </div>

              <div className="summary-item">
                <div className="summary-item__title">{t("当前规则摘要")}</div>
                <div className="summary-item__body">{currentRule?.body ?? t("请选择一条规则进行编辑。")}</div>
              </div>
            </div>

            <div className="summary-list">
              <label className="field">
                <span className="field__label">{t("规则名称")}</span>
                <input
                  className="input"
                  value={ruleTitle ?? currentRule?.title ?? ""}
                  onChange={(event) => setRuleTitle(event.target.value)}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("规则说明")}</span>
                <textarea
                  className="input"
                  style={{ minHeight: 112, paddingTop: 12, paddingBottom: 12, resize: "vertical" }}
                  value={ruleBody ?? currentRule?.body ?? ""}
                  onChange={(event) => setRuleBody(event.target.value)}
                />
              </label>

              <label className="field">
                <span className="field__label">{t("提醒级别")}</span>
                <select
                  className="input"
                  value={(ruleTone ?? currentRule?.tone ?? "accent") as RuleTone}
                  onChange={(event) => setRuleTone(event.target.value as RuleTone)}
                >
                  {TONE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <div className="chip-row">
                <button className="button button--primary" type="button" onClick={saveRule} disabled={renderRules.length === 0}>
                  {t("保存规则")}</button>
                <button className="button button--secondary" type="button" onClick={deleteRule} disabled={renderRules.length === 0}>
                  {t("删除规则")}</button>
              </div>
            </div>
          </div>
        </WorkbenchCard>

        <div className="section-grid">
          <WorkbenchCard>
            <div className="toolbar">
              <div>
                <h2 className="section-card__title">{t("监控规则")}</h2>
                <p className="section-card__description" style={{ marginBottom: 0 }}>
                  {t("实时监控会围绕价格、量价异动和持仓风险持续触发提醒。")}</p>
              </div>
              <span className="toolbar__spacer" />
              <button
                className="button button--secondary"
                type="button"
                onClick={() =>
                  resource.runAction("update-rule", {
                    index: selectedIndex,
                    title: (ruleTitle ?? currentRule?.title ?? ""),
                    body: (ruleBody ?? currentRule?.body ?? ""),
                    tone: ruleTone ?? currentRule?.tone ?? "accent",
                  })
                }
                disabled={renderRules.length === 0}
              >
                {t("快速同步")}</button>
            </div>
            <div className="summary-list">
              {renderRules.map((rule) => (
                <div className="summary-item" key={rule.title}>
                  <div className="summary-item__title">{rule.title}</div>
                  <div className="summary-item__body">{rule.body}</div>
                  {rule.tone ? <div className={`badge badge--${badgeToneFromRule(rule.tone)}`}>{rule.tone}</div> : null}
                </div>
              ))}
            </div>
          </WorkbenchCard>

          <WorkbenchCard>
            <div className="toolbar">
              <div>
                <h2 className="section-card__title">{t("触发记录")}</h2>
                <p className="section-card__description" style={{ marginBottom: 0 }}>
                  {t("记录最近一次触发时间、触发对象和提醒原因。")}</p>
              </div>
              <span className="toolbar__spacer" />
              <button className="button button--secondary" type="button" onClick={resource.refresh}>
                {t("刷新")}</button>
            </div>
            {snapshot.triggers.length === 0 ? (
              <SectionEmptyState title={t("触发记录暂无数据")} description={t("当规则触发或刷新状态后，这里会追加时间、对象和原因。")} />
            ) : (
              <div className="timeline">
                {snapshot.triggers.map((item) => (
                  <div className="timeline__item" key={`${item.time}-${item.title}`}>
                    <div className="timeline__time">{item.time}</div>
                    <div className="timeline__content">
                      <strong>{item.title}</strong> · {item.body}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="card-divider" />
            <h3 className="section-card__title" style={{ fontSize: "1.2rem" }}>
              {t("通知状态")}</h3>
            {snapshot.notificationStatus.length === 0 ? (
              <div className="empty-note">{t("暂无通知状态")}</div>
            ) : (
              <div className="chip-row">
                {snapshot.notificationStatus.map((item) => (
                  <span className="badge badge--neutral" key={item}>
                    {item}
                  </span>
                ))}
              </div>
            )}
          </WorkbenchCard>
        </div>

        <WorkbenchCard>
          <div className="toolbar">
            <div>
              <h2 className="section-card__title">{t("实时操作")}</h2>
              <p className="section-card__description" style={{ marginBottom: 0 }}>
                {t("这里提供启动、停止和连接 MiniQMT 的真实动作入口。")}</p>
            </div>
            <span className="toolbar__spacer" />
            <button className="button button--primary" type="button" onClick={() => resource.runAction("start")}>
              {t("启动")}</button>
            <button className="button button--secondary" type="button" onClick={() => resource.runAction("stop")}>
              {t("停止")}</button>
            <button className="button button--secondary" type="button" onClick={resource.refresh}>
              {t("连接")}</button>
          </div>
        </WorkbenchCard>
      </div>
    </div>
  );
}
