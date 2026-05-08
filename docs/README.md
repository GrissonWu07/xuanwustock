# 文档中心

这份索引只推荐当前仍与代码一致的文档。`docs/superpowers/` 下的 spec 和 plan 保留为开发记录，描述的是设计过程或目标态，不等于所有内容都已完整上线。

## 当前优先阅读

| 文档 | 用途 |
|---|---|
| [QUICK_START.md](QUICK_START.md) | 启动项目和走一遍当前主流程 |
| [工作台工作流指南.md](工作台工作流指南.md) | 理解工作台、股票池、发现、研究、持仓诊断、实时量化、历史回放之间的关系 |
| [股票数据流说明.md](股票数据流说明.md) | 理解 `stock_universe`、live DB、replay DB、selector 结果缓存的边界 |
| [量化交易快速指南.md](量化交易快速指南.md) | 使用实时量化和历史回放 |
| [量化模拟算法设计.md](量化模拟算法设计.md) | 对齐实时模拟和历史回放共用的策略、门控、资金槽与执行约束 |
| [前端页面与交互清单.md](前端页面与交互清单.md) | 对齐 SPA 页面、按钮和快照接口 |
| [后端能力与服务接口清单.md](后端能力与服务接口清单.md) | 对齐网关、服务、数据库和调度器 |

## 当前主线

当前产品主线已经不是“关注池 + 独立量化候选池”。

真实主线是：

`发现股票 / 研究情报 / 手工录入 -> 统一股票池(stock_universe) -> 按标签筛选 -> 持仓诊断 / 实时量化 / 历史回放`

其中：

- `watched` 表示持续关注。
- `quant_enabled` 表示纳入实时量化和历史回放默认范围。
- `registered_position_enabled` 表示纳入持仓诊断。
- 实时量化状态落在 `xuanwu_stock.db`。
- 历史回放结果落在 `xuanwu_stock_replay.db`。

## 历史文档说明

以下内容在旧文档里仍然可能出现，但已经不是当前实现：

- `watchlist.db` 作为主关注池数据库
- `candidate_pool` 作为独立量化池主表
- `/api/v1/quant/his-replay/actions/continue`
- 历史回放写入 live-sim 状态表
- 实时量化默认 15 分钟调度

看到这些口径时，以 [股票数据流说明.md](股票数据流说明.md) 和 [docs/superpowers/specs/2026-05-05-stock-universe-refresh-architecture-design.md](superpowers/specs/2026-05-05-stock-universe-refresh-architecture-design.md) 为准。
