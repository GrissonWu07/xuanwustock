# Project Learnings

## 股票发现与量化入池

- AI/外部数据类单元测试必须显式注入 fake provider 或 fixture。默认单元测试不能依赖 AkShare、TDX 或其他真实行情服务的可用性。
- 股票发现后的数据快照 ready 是量化评分门禁，不是评分降权项。缺失、failed、incomplete、stale 或 stale_unprepared 快照必须阻止有效 `candidate_score` 和 `candidate_confidence` 计算。
- 自动入池门禁不应按发现来源放宽或收紧。来源、source score 和 source confidence 只能作为审计信息，不能替代行情和技术指标评分。
- 候选排序稳定性测试需要构造前置排序键全部相等的场景，再断言 tie-breaker；否则测试可能被更早的评分差异遮蔽。
- AI Scanner 相关变更的最小验证命令：`python -m pytest -q tests/test_ai_stock_scanner.py --cov=app.discover.ai_stock_scanner --cov-report=term-missing --cov-fail-under=85`。
