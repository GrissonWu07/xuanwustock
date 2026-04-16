import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AiMonitorPage } from "../features/monitor/ai-monitor-page";
import { PortfolioPage } from "../features/portfolio/portfolio-page";
import { RealMonitorPage } from "../features/monitor/real-monitor-page";
import { HistoryPage } from "../features/history/history-page";
import { SettingsPage } from "../features/settings/settings-page";
import { HisReplayPage } from "../features/quant/his-replay-page";
import { LiveSimPage } from "../features/quant/live-sim-page";
import type { ApiClient } from "../lib/api-client";
import { createApiClient } from "../lib/api-client";
import { mockPageSnapshot } from "./mock-backend";
import type { HistorySnapshot, LiveSimSnapshot, RealMonitorSnapshot } from "../lib/page-models";

const makeClient = (snapshot: unknown, runAction?: ReturnType<typeof vi.fn>): ApiClient =>
  ({
    baseUrl: "/api",
    mode: "live",
    getPageSnapshot: async () => snapshot,
    runPageAction:
      runAction ??
      vi.fn(async () => {
        return snapshot;
      }),
  }) as unknown as ApiClient;

describe("ui api contracts", () => {
  it("defaults api client to live mode", () => {
    const client = createApiClient();
    expect(client.mode).toBe("live");
  });

  it("uses the canonical shared snapshot and action endpoints", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/quant/live-sim")) {
        return new Response(JSON.stringify(mockPageSnapshot("live-sim")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/api/v1/monitor/real/actions/update-rule")) {
        return new Response(JSON.stringify(mockPageSnapshot("real-monitor")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as typeof fetch;

    const client = createApiClient({ baseUrl: "/api", mode: "live", fetchImpl });

    await client.getPageSnapshot("live-sim");
    await client.runPageAction("real-monitor", "update-rule", { index: 0, title: "test" });

    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/quant/live-sim", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/monitor/real/actions/update-rule",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ index: 0, title: "test" }),
      }),
    );
  });

  it("dispatches live-sim candidate actions by their labels", async () => {
    const snapshot = mockPageSnapshot("live-sim") as LiveSimSnapshot;
    const runAction = vi.fn(async () => snapshot);
    render(<LiveSimPage client={makeClient(snapshot, runAction)} />);

    const analyzeButtons = await screen.findAllByRole("button", { name: "分析" });
    const deleteButtons = screen.getAllByRole("button", { name: "删除" });

    fireEvent.click(analyzeButtons[0]);
    fireEvent.click(deleteButtons[0]);

    expect(runAction).toHaveBeenCalledWith("live-sim", "analyze-candidate", "301307");
    expect(runAction).toHaveBeenCalledWith("live-sim", "delete-candidate", "301307");
  });

  it("shows ai monitor actions explicitly", async () => {
    const snapshot = mockPageSnapshot("ai-monitor");
    const runAction = vi.fn(async () => snapshot);
    render(<AiMonitorPage client={makeClient(snapshot, runAction)} />);

    expect(await screen.findByRole("button", { name: "启动盯盘" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "停止盯盘" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "立即分析" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清空队列" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "启动盯盘" }));
    expect(runAction).toHaveBeenCalledWith("ai-monitor", "start", undefined);
    fireEvent.click(screen.getAllByRole("button", { name: "分析" })[0]);
    expect(runAction).toHaveBeenCalledWith("ai-monitor", "analyze", { id: "301291" });
  });

  it("renders real monitor rule actions with aligned payloads", async () => {
    const snapshot = mockPageSnapshot("real-monitor") as RealMonitorSnapshot;
    const runAction = vi.fn(async () => snapshot);
    render(<RealMonitorPage client={makeClient(snapshot, runAction)} />);

    expect(await screen.findByRole("button", { name: "启动" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "停止" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存规则" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "删除规则" }).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("规则名称"), { target: { value: "价格突破提醒（测试）" } });
    fireEvent.change(screen.getByLabelText("规则说明"), { target: { value: "价格突破后再触发提醒。" } });
    fireEvent.change(screen.getByLabelText("提醒级别"), { target: { value: "warning" } });
    await waitFor(() => {
      expect(screen.getByDisplayValue("价格突破提醒（测试）")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "保存规则" }));
    expect(runAction).toHaveBeenCalledWith(
      "real-monitor",
      "update-rule",
      expect.objectContaining({ index: 0, title: "价格突破提醒（测试）", body: "价格突破后再触发提醒。", tone: "warning" }),
    );
  });

  it("wires portfolio action buttons to backend actions", async () => {
    const snapshot = mockPageSnapshot("portfolio");
    const runAction = vi.fn(async () => snapshot);
    render(<PortfolioPage client={makeClient(snapshot, runAction)} />);

    expect(await screen.findByRole("heading", { name: "持仓分析" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "刷新组合" }));
    fireEvent.click(screen.getByRole("button", { name: "保存调度" }));
    fireEvent.click(screen.getByRole("button", { name: "启动调度" }));
    fireEvent.click(screen.getByRole("button", { name: "停止调度" }));
    fireEvent.click(screen.getAllByRole("button", { name: "🔎分析" })[0]);

    expect(runAction).toHaveBeenCalledWith("portfolio", "refresh-portfolio", undefined);
    expect(runAction).toHaveBeenCalledWith(
      "portfolio",
      "schedule-save",
      expect.objectContaining({
        scheduleTime: "09:30",
        analysisMode: "sequential",
        maxWorkers: 1,
        autoSyncMonitor: true,
        sendNotification: true,
      }),
    );
    expect(runAction).toHaveBeenCalledWith("portfolio", "schedule-start", undefined);
    expect(runAction).toHaveBeenCalledWith("portfolio", "schedule-stop", undefined);
    expect(runAction).toHaveBeenCalledWith("portfolio", "analyze", "002463");
  });

  it("wires history rerun to backend action", async () => {
    const snapshot = mockPageSnapshot("history");
    const runAction = vi.fn(async () => snapshot);
    render(<HistoryPage client={makeClient(snapshot, runAction)} />);

    expect(await screen.findByRole("heading", { name: "历史记录" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重新整理" }));

    expect(runAction).toHaveBeenCalledWith("history", "rerun", undefined);
  });

  it("wires settings refresh button to snapshot reload", async () => {
    const snapshot = mockPageSnapshot("settings");
    const runAction = vi.fn(async () => snapshot);
    render(<SettingsPage client={makeClient(snapshot, runAction)} />);

    expect(await screen.findByRole("heading", { name: "环境配置" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新配置" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "刷新配置" }));
  });

  it("uses replay history curve data from snapshots instead of placeholder points", async () => {
    const snapshot = {
      ...(mockPageSnapshot("history") as HistorySnapshot),
      curve: [
        { label: "T-2", value: 90 },
        { label: "T-1", value: 120 },
        { label: "Today", value: 150 },
      ],
    } as HistorySnapshot;

    render(<HistoryPage client={makeClient(snapshot)} />);

    expect(await screen.findByText("T-2")).toBeInTheDocument();
    expect(screen.getByText("T-1")).toBeInTheDocument();
    expect(screen.getByText("Today")).toBeInTheDocument();
    const sparkline = screen.getByRole("img", { name: "曲线" });
    expect(within(sparkline).queryByText("昨天")).not.toBeInTheDocument();
    expect(within(sparkline).queryByText("今天")).not.toBeInTheDocument();
    expect(within(sparkline).queryByText("最新")).not.toBeInTheDocument();
  });

  it("does not expose fake signal buttons in his replay", async () => {
    const snapshot = mockPageSnapshot("his-replay");
    render(<HisReplayPage client={makeClient(snapshot)} />);

    expect(await screen.findByRole("heading", { name: "历史回放" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "详情" })).not.toBeInTheDocument();
  });
});

