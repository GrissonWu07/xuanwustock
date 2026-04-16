import { describe, expect, it, vi } from "vitest";
import { createApiClient, type ApiClient } from "../lib/api-client";
import { mockPageSnapshot } from "./mock-backend";

describe("api client endpoints", () => {
  it("uses canonical page and action endpoints for quant and monitor pages", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/quant/live-sim") {
        return new Response(JSON.stringify(mockPageSnapshot("live-sim")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url === "/api/v1/quant/live-sim/actions/stop") {
        return new Response(JSON.stringify(mockPageSnapshot("live-sim")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url === "/api/v1/portfolio/actions/refresh-portfolio") {
        return new Response(JSON.stringify(mockPageSnapshot("portfolio")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url === "/api/v1/portfolio/actions/schedule-start") {
        return new Response(JSON.stringify(mockPageSnapshot("portfolio")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url === "/api/v1/portfolio/actions/schedule-save") {
        return new Response(JSON.stringify(mockPageSnapshot("portfolio")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url === "/api/v1/portfolio/actions/schedule-stop") {
        return new Response(JSON.stringify(mockPageSnapshot("portfolio")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url === "/api/v1/monitor/real/actions/update-rule") {
        return new Response(JSON.stringify(mockPageSnapshot("real-monitor")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      throw new Error(`Unexpected fetch: ${url} ${init?.method ?? "GET"}`);
    }) as typeof fetch;

    const client: ApiClient = createApiClient({ baseUrl: "/api", mode: "live", fetchImpl });

    await client.getPageSnapshot("live-sim");
    await client.runPageAction("live-sim", "stop");
    await client.runPageAction("portfolio", "refresh-portfolio");
    await client.runPageAction("portfolio", "schedule-save");
    await client.runPageAction("portfolio", "schedule-start");
    await client.runPageAction("portfolio", "schedule-stop");
    await client.runPageAction("real-monitor", "update-rule", { index: 0, title: "test" });

    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/quant/live-sim", expect.objectContaining({ method: "GET" }));
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/quant/live-sim/actions/stop", expect.objectContaining({ method: "POST" }));
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/portfolio/actions/refresh-portfolio", expect.objectContaining({ method: "POST" }));
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/portfolio/actions/schedule-save", expect.objectContaining({ method: "POST" }));
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/portfolio/actions/schedule-start", expect.objectContaining({ method: "POST" }));
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/portfolio/actions/schedule-stop", expect.objectContaining({ method: "POST" }));
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/monitor/real/actions/update-rule",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ index: 0, title: "test" }),
      }),
    );
  });
});

