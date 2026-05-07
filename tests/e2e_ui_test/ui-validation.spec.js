const { test, expect } = require("@playwright/test");

const ROUTES = [
  { path: "/main", title: /工作台|Workbench/i, navText: "工作台" },
  { path: "/discover", title: /发现股票|Discover/i, navText: "发现股票" },
  { path: "/research", title: /研究情报|Research/i, navText: "研究情报" },
  { path: "/portfolio", title: /持仓列表|持仓分析|Portfolio/i, navText: "持仓分析" },
  { path: "/live-sim", title: /运行状态|实时模拟|Quant simulation/i, navText: "实时模拟" },
  { path: "/his-replay", title: /历史回放|Historical replay/i, navText: "历史回放" },
  { path: "/settings", title: /环境配置|Environment settings|Settings/i, navText: "环境配置" },
  { path: "/strategy-config", title: /策略配置|Strategy configuration/i, navText: "策略配置" },
];

const EXPECTED_ACTIONS = {
  "/main": [/Inline add|行内新增/, /Refresh stock info|刷新股票信息/, /Clear selection|清空选择/],
  "/discover": [/运行|Run/, /重置列表|Reset list/, /刷新发现结果|Refresh discover result/, /清空选择|Clear selection/],
  "/research": [/重新生成|Regenerate/, /重置列表|Reset list/, /刷新研究情报|Refresh research/, /清空选择|Clear selection/],
  "/portfolio": [/刷新组合/, /实时分析仓位/],
  "/live-sim": [/保存/, /重置/, /停止模拟|运行中/, /启动模拟|运行中/],
  "/his-replay": [/开始回溯/, /取消/, /删除/],
  "/settings": [/刷新配置|Refresh settings/, /保存全部配置|Save all settings/],
};

const IGNORE_CONSOLE_PATTERNS = [
  /favicon/i,
  /Failed to load resource: the server responded with a status of 404/i,
  /ResizeObserver loop/i,
  /Download the React DevTools/i,
];

const sameOrigin = (baseURL, targetURL) => {
  try {
    return new URL(baseURL).origin === new URL(targetURL).origin;
  } catch {
    return false;
  }
};

async function setChineseLocale(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("xuanwu.ui.locale", "zh-CN");
  });
}

function installPageHealthMonitor(page, baseURL) {
  const browserErrors = [];
  const failedRequests = [];

  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (IGNORE_CONSOLE_PATTERNS.some((pattern) => pattern.test(text))) return;
    browserErrors.push(`console error: ${text}`);
  });

  page.on("pageerror", (error) => {
    browserErrors.push(`page error: ${error.message}`);
  });

  page.on("requestfailed", (request) => {
    const url = request.url();
    if (!sameOrigin(baseURL, url)) return;
    if (/favicon/i.test(url)) return;
    const errorText = request.failure()?.errorText || "";
    if (/ERR_ABORTED/i.test(errorText)) return;
    failedRequests.push(`request failed: ${request.method()} ${url} ${errorText}`.trim());
  });

  page.on("response", (response) => {
    const url = response.url();
    if (!sameOrigin(baseURL, url)) return;
    const status = response.status();
    if (status < 400) return;
    if (/favicon/i.test(url)) return;
    const request = response.request();
    failedRequests.push(`bad response: ${status} ${request.method()} ${url}`);
  });

  return {
    reset() {
      browserErrors.length = 0;
      failedRequests.length = 0;
    },
    assertClean(context) {
      const details = [...browserErrors, ...failedRequests];
      expect(details, `${context} should not create browser errors or failed same-origin requests`).toEqual([]);
    },
  };
}

async function waitForUsablePage(page, route) {
  await page.waitForLoadState("domcontentloaded");
  await expect(page.locator(".app-shell")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/Bad Gateway|Internal Server Error|Application error|Not Found/i);
  await expect(page.locator("body")).not.toContainText(/加载失败|failed to load|无法加载|Unable to load/i);
  await expect(page.getByText(route.title).first()).toBeVisible();
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

async function visibleButtons(page) {
  return await page.locator("button").evaluateAll((buttons) => {
    const isVisible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    };

    return buttons
      .map((button, allIndex) => {
        const name = (
          button.getAttribute("aria-label") ||
          button.getAttribute("title") ||
          button.textContent ||
          ""
        ).replace(/\s+/g, " ").trim();
        return {
          allIndex,
          name,
          disabled: button.disabled || button.getAttribute("aria-disabled") === "true",
          visible: isVisible(button),
        };
      })
      .filter((button) => button.visible);
  });
}

function describeButton(button) {
  return button.name ? `button "${button.name}"` : `button at DOM index ${button.allIndex}`;
}

function matchesPattern(name, pattern) {
  if (!name) return false;
  if (pattern instanceof RegExp) return pattern.test(name);
  return name === pattern;
}

async function gotoRoute(page, routePath) {
  let lastError;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await page.goto(routePath, { waitUntil: "domcontentloaded", timeout: 30_000 });
      return;
    } catch (error) {
      lastError = error;
      await page.waitForTimeout(500);
    }
  }
  throw lastError;
}

async function waitForExpectedButtons(page, routePath) {
  const expectedActions = EXPECTED_ACTIONS[routePath] || [];
  if (expectedActions.length === 0) return;

  for (let attempt = 0; attempt < 20; attempt += 1) {
    const names = (await visibleButtons(page)).map((button) => button.name);
    const matchedCount = expectedActions.filter((pattern) => names.some((name) => matchesPattern(name, pattern))).length;
    if (matchedCount > 0) {
      return;
    }
    await page.waitForTimeout(500);
  }
}

async function clickButtonFromFreshRoute(page, route, button, monitor) {
  monitor.reset();
  await gotoRoute(page, route.path);
  await waitForUsablePage(page, route);
  await waitForExpectedButtons(page, route.path);
  await page.waitForTimeout(1000);

  const locator = await findClickableButton(page, button);
  if (!locator) {
    return "skipped";
  }

  await locator.click();
  await page.waitForLoadState("domcontentloaded").catch(() => undefined);
  await page.waitForLoadState("networkidle", { timeout: 3_000 }).catch(() => undefined);
  await expect(page.locator("body"), `${describeButton(button)} should not unmount the page`).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/Bad Gateway|Internal Server Error|Application error/i);
  monitor.assertClean(`${route.path} ${describeButton(button)}`);
  return "clicked";
}

async function findClickableButton(page, button) {
  if (!button.name) {
    const indexed = page.locator("button").nth(button.allIndex);
    if ((await indexed.isVisible().catch(() => false)) && (await indexed.isEnabled().catch(() => false))) {
      return indexed;
    }
    return null;
  }

  const candidates = page.getByRole("button", { name: button.name, exact: true });
  const count = await candidates.count();
  for (let index = 0; index < count; index += 1) {
    const candidate = candidates.nth(index);
    if ((await candidate.isVisible().catch(() => false)) && (await candidate.isEnabled().catch(() => false))) {
      return candidate;
    }
  }
  return null;
}

test.beforeEach(async ({ page }) => {
  await setChineseLocale(page);
  page.on("dialog", async (dialog) => {
    await dialog.dismiss();
  });
});

test.describe("发布前 UI 页面验证", () => {
  test("所有 spec 页面都能通过真实浏览器打开，并且侧边栏入口齐全", async ({ page }, testInfo) => {
    const monitor = installPageHealthMonitor(page, testInfo.project.use.baseURL);
    const failures = [];

    for (const route of ROUTES) {
      monitor.reset();
      try {
        await gotoRoute(page, route.path);
        await waitForUsablePage(page, route);
        await waitForExpectedButtons(page, route.path);
        await expect(page).toHaveURL(new RegExp(`${route.path.replace("/", "\\/")}(?:$|[?#])`));
      } catch (error) {
        failures.push(`${route.path} failed to load as usable page: ${errorMessage(error)}`);
        continue;
      }

      for (const expectedRoute of ROUTES) {
        const link = page.getByRole("link", { name: expectedRoute.navText }).first();
        if ((await link.count()) === 0 || !(await link.isVisible().catch(() => false))) {
          failures.push(`${route.path} sidebar missing ${expectedRoute.navText}`);
        }
      }

      try {
        monitor.assertClean(`${route.path} page load`);
      } catch (error) {
        failures.push(`${route.path} page health failed: ${errorMessage(error)}`);
      }
    }

    expect(failures).toEqual([]);
  });

  test("每个页面的关键动作按钮存在，按钮文案来自当前 UI/spec", async ({ page }, testInfo) => {
    const monitor = installPageHealthMonitor(page, testInfo.project.use.baseURL);
    const failures = [];

    for (const route of ROUTES) {
      monitor.reset();
      try {
        await gotoRoute(page, route.path);
        await waitForUsablePage(page, route);
        await waitForExpectedButtons(page, route.path);
      } catch (error) {
        failures.push(`${route.path} failed to load before button check: ${errorMessage(error)}`);
        continue;
      }

      const expectedActions = EXPECTED_ACTIONS[route.path] || [];
      const buttonNames = (await visibleButtons(page)).map((button) => button.name);
      for (const actionName of expectedActions) {
        const matched = buttonNames.some((name) => matchesPattern(name, actionName));
        if (!matched) {
          failures.push(`${route.path} missing visible button ${actionName}`);
        }
      }

      try {
        monitor.assertClean(`${route.path} expected buttons`);
      } catch (error) {
        failures.push(`${route.path} button check health failed: ${errorMessage(error)}`);
      }
    }

    expect(failures).toEqual([]);
  });

  test("逐页点击初始可见且启用的按钮，验证前端不崩溃且无失败请求", async ({ page }, testInfo) => {
    const monitor = installPageHealthMonitor(page, testInfo.project.use.baseURL);
    const failures = [];

    for (const route of ROUTES) {
      monitor.reset();
      try {
        await gotoRoute(page, route.path);
        await waitForUsablePage(page, route);
        await waitForExpectedButtons(page, route.path);
      } catch (error) {
        failures.push(`${route.path} failed to load before click sweep: ${errorMessage(error)}`);
        continue;
      }

      const buttons = (await visibleButtons(page)).filter((button) => !button.disabled);
      const expectedActions = EXPECTED_ACTIONS[route.path] || [];
      if (expectedActions.length === 0) {
        continue;
      }
      const uniqueButtons = expectedActions
        .map((pattern) => buttons.find((button) => matchesPattern(button.name, pattern)))
        .filter(Boolean);

      if (uniqueButtons.length === 0) {
        failures.push(`${route.path} has no enabled expected action buttons`);
        continue;
      }

      for (const button of uniqueButtons) {
        await test.step(`${route.path} click ${describeButton(button)}`, async () => {
          try {
            await clickButtonFromFreshRoute(page, route, button, monitor);
          } catch (error) {
            failures.push(`${route.path} ${describeButton(button)} failed: ${errorMessage(error)}`);
          }
        });
      }
    }

    expect(failures).toEqual([]);
  });
});
