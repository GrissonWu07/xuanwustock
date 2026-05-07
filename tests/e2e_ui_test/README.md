# UI E2E Browser Tests

这组测试是发布前的真实浏览器前端验证，不是 API 合同测试。测试会打开目标站点，逐页验证页面可见、侧边栏入口、关键动作按钮，并点击每个初始可见且启用的按钮，检查前端没有崩溃、控制台没有错误、站内请求没有 4xx/5xx。

## 本地运行

```bash
cd tests/e2e_ui_test
npm install
npm run install:browsers
npm test
```

默认目标地址：

```bash
http://family-mac:12080
```

覆盖目标地址：

```bash
$env:E2E_UI_BASE_URL="http://family-mac:12080"
npm test
```

有头模式便于人工观察：

```bash
$env:E2E_UI_HEADED="1"
npm run test:headed
```

## 通过 pytest 触发

发布流水线如果统一使用 pytest，可以显式打开包装器：

```bash
$env:E2E_UI_ENABLE="1"
$env:E2E_UI_BASE_URL="http://family-mac:12080"
pytest tests/e2e_ui_test
```

未设置 `E2E_UI_ENABLE=1` 时，pytest 包装器会跳过，避免普通单元测试误连发布环境。

## 覆盖范围

- `/main`
- `/discover`
- `/research`
- `/portfolio`
- `/live-sim`
- `/his-replay`
- `/settings`
- `/strategy-config`

测试会保留失败时的截图、trace、video 和 HTML report，输出目录在 `tests/e2e_ui_test/test-results` 与 `tests/e2e_ui_test/playwright-report`。
