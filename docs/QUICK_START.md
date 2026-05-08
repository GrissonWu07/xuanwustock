# 快速开始

这份指南按当前实现写，不再使用“独立关注池数据库 + 独立量化候选池数据库”的旧口径。

当前主线是：

`工作台股票池 -> 发现股票 / 研究情报 -> 启用实时量化 -> 实时量化 / 历史回放`

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. 配置 `.env`

```bash
copy .env.example .env
```

最低建议：

```env
DEEPSEEK_API_KEY=your_api_key
DEFAULT_MODEL_NAME=deepseek-chat
TDX_ENABLED=true
```

可选：

- `TUSHARE_TOKEN`
- 邮件 / Webhook
- MiniQMT 相关配置

## 3. 启动服务

```bash
python app.py
```

默认入口：

- 工作台：`http://127.0.0.1:8501/main`
- 健康检查：`http://127.0.0.1:8501/api/health`

如果要本地开发前端：

```bash
cd ui
npm install
npm run dev
```

前端开发地址：

`http://127.0.0.1:4173`

## 4. 先看工作台

工作台当前展示的是统一股票池视图，不只是旧的 `watched=1` 列表。

它会合并展示至少一类有效成员：

- `watched`
- `quant_enabled`
- `registered_position_enabled`

你可以在这里做三类动作：

1. 手工添加股票。
2. 批量启用实时量化。
3. 批量登记持仓。

## 5. 从发现或研究写入股票池

如果你还没有目标股票：

1. 打开 `发现股票` 或 `研究情报`。
2. 运行策略或模块。
3. 将股票加入工作台股票池。
4. 回到工作台继续分析或启用实时量化。

这些页面的结果存放在 `data/selector_results/*.json`，不直接决定 live-sim 或 his-replay 的范围。

## 6. 启用实时量化

1. 在工作台勾选股票。
2. 批量执行 `加入量化`。
3. 这会把对应 `stock_universe.quant_enabled` 设为 `1`。
4. 打开 `实时量化` 页面。

当前实时量化读取的是：

- `xuanwu_stock.db.stock_universe` 中 `quant_enabled=1` 的股票
- `xuanwu_stock.db` 中独立的 live-sim 账户、持仓、成交、信号

## 7. 使用实时量化

在 `/live-sim`：

1. 配置市场、时间粒度、策略档案、初始资金。
2. 启动调度器。
3. 默认调度周期是 `10` 分钟。
4. 只在交易时段运行。

新库默认策略档案是 `aggressive`；策略配置页可以切换或克隆 `aggressive / stable / conservative`，三档都使用同一套实时/回放共享策略内核。

运行时依赖：

- 行情技术刷新走 local-first
- 实时 quote TTL 是 `2` 分钟
- 失败股票进入冷却，不会每轮都重复远程拉取

## 8. 使用历史回放

在 `/his-replay`：

1. 历史回放会冻结当前 `quant_enabled=1` 的股票范围。
2. 启动方式只有：
   - `开始回溯`
   - `取消`
   - `删除`
3. 不再支持“接续到实时模拟账户”。

当前历史回放：

- 结果写入 `xuanwu_stock_replay.db`
- 不写 `sim_positions`、`sim_trades`、`sim_account`
- 准备阶段按区间 local-first 补历史 K 线和指标
- checkpoint 运行阶段只读准备结果，不再远程拉实时数据

## 9. 持仓诊断

`/portfolio` 读取的不是独立 `portfolio_stocks.db`，而是 `xuanwu_stock.db.stock_universe` 上的登记持仓字段。

你可以：

1. 在工作台批量登记持仓。
2. 在持仓诊断页查看组合和个股诊断。
3. 对单只股票继续进入详情页 `/portfolio/position/:symbol`。

## 10. 当前要避开的旧认知

以下说法已经不成立：

- “量化候选池是独立主表”
- “关注池写在 `watchlist.db`”
- “历史回放可以接续到 live-sim 账户”
- “实时量化默认 15 分钟”
- “工作台只展示 watched 股票”

## 11. 推荐上手顺序

1. 配好 `.env`
2. 启动 `python app.py`
3. 在工作台手工加 1 到 2 只股票
4. 运行一次单股分析
5. 去 `发现股票` 挑几只加入股票池
6. 在工作台批量启用实时量化
7. 体验一次 `/live-sim`
8. 再体验一次 `/his-replay`
