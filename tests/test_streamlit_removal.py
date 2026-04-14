from pathlib import Path
import importlib


REMOVED_MODULES = [
    "app.discovery_hub_ui",
    "app.research_hub_ui",
    "app.watchlist_ui",
    "app.portfolio_ui",
    "app.monitor_ui",
    "app.smart_monitor_ui",
    "app.longhubang_ui",
    "app.news_flow_ui",
    "app.macro_analysis_ui",
    "app.macro_cycle_ui",
    "app.sector_strategy_ui",
    "app.main_force_ui",
    "app.main_force_history_ui",
    "app.low_price_bull_ui",
    "app.low_price_bull_monitor_ui",
    "app.profit_growth_ui",
    "app.small_cap_ui",
    "app.value_stock_ui",
    "app.quant_sim.ui",
    "app.stm",
]


REMOVED_FILES = [
    ".streamlit/config.toml",
    "app/discovery_hub_ui.py",
    "app/research_hub_ui.py",
    "app/watchlist_ui.py",
    "app/portfolio_ui.py",
    "app/monitor_ui.py",
    "app/smart_monitor_ui.py",
    "app/longhubang_ui.py",
    "app/news_flow_ui.py",
    "app/macro_analysis_ui.py",
    "app/macro_cycle_ui.py",
    "app/sector_strategy_ui.py",
    "app/main_force_ui.py",
    "app/main_force_history_ui.py",
    "app/low_price_bull_ui.py",
    "app/low_price_bull_monitor_ui.py",
    "app/profit_growth_ui.py",
    "app/small_cap_ui.py",
    "app/value_stock_ui.py",
    "app/quant_sim/ui.py",
    "app/stm.py",
    "app/main_force_pdf_generator.py",
]


def test_removed_streamlit_files_are_gone():
    project_root = Path(__file__).resolve().parents[1]
    for relative_path in REMOVED_FILES:
        assert not (project_root / relative_path).exists(), relative_path


def test_removed_streamlit_modules_cannot_be_imported():
    for module_name in REMOVED_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"expected {module_name} to be removed")

def test_legacy_streamlit_main_module_is_removed():
    project_root = Path(__file__).resolve().parents[1]
    assert not (project_root / "app" / "app.py").exists()
    try:
        importlib.import_module("app.app")
    except ModuleNotFoundError:
        return
    raise AssertionError("expected app.app to be removed")


def test_runtime_python_sources_do_not_reference_streamlit():
    project_root = Path(__file__).resolve().parents[1]
    python_files = [
        path
        for path in (project_root / "app").rglob("*.py")
        if path.name not in {"sitecustomize.py"}
    ] + [
        project_root / "app.py",
        project_root / "run.py",
    ]

    offenders: list[str] = []
    for path in python_files:
        text = path.read_text(encoding="utf-8")
        if "streamlit" in text.lower():
            offenders.append(str(path.relative_to(project_root)))

    assert offenders == [], f"runtime files still reference streamlit: {offenders}"


def test_current_user_docs_do_not_reference_streamlit_runtime():
    project_root = Path(__file__).resolve().parents[1]
    current_docs = [
        project_root / "README.md",
        project_root / "docs" / "README.md",
        project_root / "docs" / "QUICK_START.md",
        project_root / "docs" / "PORTFOLIO_USAGE.md",
        project_root / "docs" / "LONGHUBANG_BATCH_ANALYSIS.md",
        project_root / "docs" / "MULTI_SCHEDULE_GUIDE.md",
        project_root / "docs" / "TDX数据源快速配置.md",
        project_root / "docs" / "TDX数据源集成完成说明.md",
        project_root / "docs" / "主力选股使用指南.md",
        project_root / "docs" / "主力选股功能说明.md",
        project_root / "docs" / "主力选股批量分析功能说明.md",
        project_root / "docs" / "主力选股快速开始.md",
        project_root / "docs" / "低价擒牛实现总结.md",
        project_root / "docs" / "低价擒牛快速开始.md",
        project_root / "docs" / "新闻流量监测快速开始.md",
        project_root / "docs" / "智瞰龙虎功能说明.md",
        project_root / "docs" / "智瞰龙虎快速开始.md",
        project_root / "docs" / "智策定时分析使用指南.md",
        project_root / "docs" / "智策定时分析功能完成说明.md",
        project_root / "docs" / "智策定时分析部署清单.md",
        project_root / "docs" / "智策板块快速开始.md",
        project_root / "docs" / "智能盯盘使用指南.md",
    ]

    offenders: list[str] = []
    for path in current_docs:
        text = path.read_text(encoding="utf-8")
        if "streamlit run app.py" in text.lower() or "streamlit应用" in text or "streamlit app" in text.lower():
            offenders.append(str(path.relative_to(project_root)))

    assert offenders == [], f"current docs still reference streamlit runtime: {offenders}"
