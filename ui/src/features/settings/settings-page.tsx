import type { ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { SectionEmptyState } from "../../components/ui/section-empty";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";

type SettingsPageProps = {
  client?: ApiClient;
};

export function SettingsPage({ client }: SettingsPageProps) {
  const resource = usePageData("settings", client);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title="环境配置加载中" description="正在读取模型配置、数据源和运行参数。" />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title="环境配置加载失败"
        description={resource.error ?? "无法加载环境配置数据，请稍后重试。"}
        actionLabel="重新加载"
        onAction={resource.refresh}
      />
    );
  }

  const snapshot = resource.data;
  if (!snapshot) {
    return <PageEmptyState title="环境配置暂无数据" description="后台尚未返回环境配置快照。" actionLabel="刷新" onAction={resource.refresh} />;
  }

  return (
    <div>
      <PageHeader
        eyebrow="Settings"
        title="环境配置"
        description="模型、数据源、运行参数和路径约定统一在这个页面管理。"
      />

      <div className="stack">
        <WorkbenchCard>
          <h2 className="section-card__title">快照概览</h2>
          <p className="section-card__description">
            当前页面读取的是最新环境配置快照，快照更新时间决定了模型、数据源和运行参数的可见状态。
          </p>
          <div className="summary-item summary-item--accent">
            <div className="summary-item__title">快照更新时间</div>
            <div className="summary-item__body">{snapshot.updatedAt}</div>
          </div>
        </WorkbenchCard>

        <div className="metric-grid">
          {snapshot.metrics.map((metric) => (
            <WorkbenchCard className="metric-card" key={metric.label}>
              <div className="metric-card__label">{metric.label}</div>
              <div className="metric-card__value">{metric.value}</div>
            </WorkbenchCard>
          ))}
        </div>

        <div className="section-grid">
          <WorkbenchCard>
            <div className="toolbar">
              <div>
                <h2 className="section-card__title">模型配置</h2>
                <p className="section-card__description" style={{ marginBottom: 0 }}>
                  当前前端只展示模型和密钥的状态摘要，不暴露敏感值。
                </p>
              </div>
              <span className="toolbar__spacer" />
              <button className="button button--primary" type="button" onClick={() => resource.runAction("save")}>
                保存配置
              </button>
            </div>
            {snapshot.modelConfig.length === 0 ? (
              <SectionEmptyState title="模型配置暂无数据" description="等待后端返回模型状态后，这里会显示默认模型、密钥状态和相关说明。" />
            ) : (
              <div className="summary-list">
                {snapshot.modelConfig.map((item) => (
                  <div className="summary-item" key={item.title}>
                    <div className="summary-item__title">{item.title}</div>
                    <div className="summary-item__body">{item.body}</div>
                  </div>
                ))}
              </div>
            )}
          </WorkbenchCard>

          <WorkbenchCard>
            <h2 className="section-card__title">数据源</h2>
            {snapshot.dataSources.length === 0 ? (
              <SectionEmptyState title="数据源暂无数据" description="行情源、关注池报价和其他数据接口准备好后会在这里集中展示。" />
            ) : (
              <div className="summary-list">
                {snapshot.dataSources.map((item) => (
                  <div className="summary-item" key={item.title}>
                    <div className="summary-item__title">{item.title}</div>
                    <div className="summary-item__body">{item.body}</div>
                  </div>
                ))}
              </div>
            )}
          </WorkbenchCard>
        </div>

        <div className="section-grid">
          <WorkbenchCard>
            <h2 className="section-card__title">运行参数</h2>
            {snapshot.runtimeParams.length === 0 ? (
              <SectionEmptyState title="运行参数暂无数据" description="日志目录、数据库目录和其他运行约定会在这里统一展示。" />
            ) : (
              <div className="summary-list">
                {snapshot.runtimeParams.map((item) => (
                  <div className="summary-item" key={item.title}>
                    <div className="summary-item__title">{item.title}</div>
                    <div className="summary-item__body">{item.body}</div>
                  </div>
                ))}
              </div>
            )}
          </WorkbenchCard>

          <WorkbenchCard>
            <h2 className="section-card__title">路径清单</h2>
            {snapshot.paths.length === 0 ? (
              <SectionEmptyState title="路径清单暂无数据" description="配置路径准备好后，这里会列出所有关键文件和目录。" />
            ) : (
              <div className="chip-row">
                {snapshot.paths.map((path) => (
                  <span className="badge badge--neutral" key={path}>
                    {path}
                  </span>
                ))}
              </div>
            )}
            <div className="card-divider" />
            <button className="button button--secondary" type="button" onClick={resource.refresh}>
              刷新配置
            </button>
          </WorkbenchCard>
        </div>
      </div>
    </div>
  );
}
