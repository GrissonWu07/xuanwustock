from console_utils import configure_standard_streams, install_safe_print

configure_standard_streams()
install_safe_print()

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import json
from datetime import datetime
import time
import base64
import os
import config
from streamlit_flash import queue_flash_message, render_flash_messages

from stock_data import StockDataFetcher
from ai_agents import StockAnalysisAgents
from pdf_generator import display_pdf_export_section
from database import db
from monitor_manager import display_monitor_manager, get_monitor_summary
from monitor_service import monitor_service
from notification_service import notification_service
from config_manager import config_manager
from main_force_ui import display_main_force_selector
from sector_strategy_ui import display_sector_strategy
from longhubang_ui import display_longhubang
from quant_sim.ui import display_quant_replay, display_quant_sim
from smart_monitor_ui import smart_monitor_ui
from news_flow_ui import display_news_flow_monitor
from watchlist_ui import display_watchlist_workbench

# 页面配置
st.set_page_config(
    page_title="复合多AI智能体股票团队分析系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

SIDEBAR_VIEW_FLAGS = [
    "show_history",
    "show_monitor",
    "show_config",
    "show_main_force",
    "show_low_price_bull",
    "show_small_cap",
    "show_profit_growth",
    "show_value_stock",
    "show_sector_strategy",
    "show_longhubang",
    "show_news_flow",
    "show_macro_analysis",
    "show_macro_cycle",
    "show_portfolio",
    "show_quant_sim",
    "show_quant_replay",
    "show_smart_monitor",
]

SIDEBAR_HOME_ITEM = {
    "title": "工作台",
    "label": "进入工作台",
    "icon": "🏠",
    "key": "nav_home",
    "flag": None,
    "help": "返回工作台，先看关注池，再继续分析、发现股票和量化验证",
}

SIDEBAR_NAV_GROUPS = [
    {
        "title": "选股",
        "description": "根据不同策略筛选优质股票",
        "items": [
            {"label": "主力选股", "icon": "💰", "key": "nav_main_force", "flag": "show_main_force", "help": "基于主力资金流向的选股策略"},
            {"label": "低价擒牛", "icon": "🐂", "key": "nav_low_price_bull", "flag": "show_low_price_bull", "help": "低价高成长股票筛选策略"},
            {"label": "小市值策略", "icon": "📊", "key": "nav_small_cap", "flag": "show_small_cap", "help": "小盘高成长股票筛选策略"},
            {"label": "净利增长", "icon": "📈", "key": "nav_profit_growth", "flag": "show_profit_growth", "help": "净利润增长稳健股票筛选策略"},
            {"label": "低估值策略", "icon": "💎", "key": "nav_value_stock", "flag": "show_value_stock", "help": "低PE+低PB+高股息+低负债 价值投资筛选"},
        ],
    },
    {
        "title": "策略",
        "description": "AI驱动的板块和龙虎榜策略",
        "items": [
            {"label": "智策板块", "icon": "🎯", "key": "nav_sector_strategy", "flag": "show_sector_strategy", "help": "AI板块策略分析"},
            {"label": "智瞰龙虎", "icon": "🐉", "key": "nav_longhubang", "flag": "show_longhubang", "help": "龙虎榜深度分析"},
            {"label": "新闻流量", "icon": "📰", "key": "nav_news_flow", "flag": "show_news_flow", "help": "新闻流量监测与短线指导"},
            {"label": "宏观分析", "icon": "🌏", "key": "nav_macro_analysis", "flag": "show_macro_analysis", "help": "国家统计局宏观数据 × A股行业映射 × 优质标的"},
            {"label": "宏观周期", "icon": "🧭", "key": "nav_macro_cycle", "flag": "show_macro_cycle", "help": "康波周期 × 美林投资时钟 × 政策分析"},
        ],
    },
    {
        "title": "投资管理",
        "description": "持仓跟踪与实时监测",
        "items": [
            {"label": "持仓分析", "icon": "📊", "key": "nav_portfolio", "flag": "show_portfolio", "help": "投资组合分析与定时跟踪"},
            {"label": "量化模拟", "icon": "🧪", "key": "nav_quant_sim", "flag": "show_quant_sim", "help": "统一候选池、策略信号、人工执行与模拟持仓"},
            {"label": "历史回放", "icon": "🕰️", "key": "nav_quant_replay", "flag": "show_quant_replay", "help": "策略历史区间回放与连续模拟结果分析"},
            {"label": "AI盯盘", "icon": "🤖", "key": "nav_smart_monitor", "flag": "show_smart_monitor", "help": "DeepSeek AI自动盯盘决策交易（支持A股T+1）"},
            {"label": "实时监测", "icon": "📡", "key": "nav_monitor", "flag": "show_monitor", "help": "价格监控与预警提醒"},
        ],
    },
    {
        "title": "系统",
        "description": "常用记录与系统配置",
        "items": [
            {"label": "历史记录", "icon": "📖", "key": "nav_history", "flag": "show_history", "help": "查看历史分析记录"},
            {"label": "环境配置", "icon": "⚙️", "key": "nav_config", "flag": "show_config", "help": "系统设置与API配置"},
        ],
    },
]


def activate_sidebar_view(target_flag: str | None) -> None:
    """切换侧边栏目标页面，并清理其他页面标志。"""
    for key in SIDEBAR_VIEW_FLAGS:
        if key in st.session_state:
            del st.session_state[key]
    if target_flag:
        st.session_state[target_flag] = True


def get_active_sidebar_view() -> str:
    """返回当前被激活的侧边栏视图 key。"""
    for group in SIDEBAR_NAV_GROUPS:
        for item in group["items"]:
            if item["flag"] and st.session_state.get(item["flag"]):
                return item["key"]
    return SIDEBAR_HOME_ITEM["key"]


def render_sidebar_nav_styles() -> None:
    """为现代化侧边栏导航注入局部样式。"""
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] .sidebar-nav-shell {
            padding-top: 0.1rem;
            padding-bottom: 0.75rem;
        }

        [data-testid="stSidebar"] .sidebar-nav-card {
            background: rgba(255, 255, 255, 0.74);
            border: 1px solid rgba(210, 219, 242, 0.90);
            border-radius: 18px;
            padding: 0.9rem 0.85rem 0.8rem 0.85rem;
            margin-bottom: 0.9rem;
            box-shadow: 0 12px 30px rgba(40, 34, 88, 0.08);
            backdrop-filter: blur(10px);
        }

        [data-testid="stSidebar"] .sidebar-nav-card-title {
            font-size: 1rem;
            font-weight: 800;
            color: #23304d !important;
            margin-bottom: 0.18rem;
        }

        [data-testid="stSidebar"] .sidebar-nav-card-note {
            font-size: 0.78rem;
            line-height: 1.45;
            color: #6b7394 !important;
            margin-bottom: 0.7rem;
        }

        [data-testid="stSidebar"] .sidebar-nav-item {
            margin-bottom: 0.42rem;
        }

        [data-testid="stSidebar"] .sidebar-nav-item:last-child {
            margin-bottom: 0;
        }

        [data-testid="stSidebar"] .sidebar-nav-item.active .sidebar-nav-accent {
            background: linear-gradient(180deg, #c7d2fe 0%, #ffffff 100%);
            box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.45);
        }

        [data-testid="stSidebar"] .sidebar-nav-accent {
            width: 4px;
            min-height: 2.25rem;
            border-radius: 999px;
            background: transparent;
            margin-top: 0.05rem;
        }

        [data-testid="stSidebar"] .stButton > button[kind="secondary"] {
            background: rgba(255, 255, 255, 0.90);
            color: #28324c;
            border: 1px solid rgba(219, 227, 255, 0.85);
            border-radius: 14px;
            min-height: 2.28rem;
            padding: 0.4rem 0.75rem;
            font-size: 0.95rem;
            font-weight: 600;
            box-shadow: none;
            display: flex;
            justify-content: flex-start;
            align-items: center;
        }

        [data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
            background: #ffffff;
            border-color: rgba(255, 255, 255, 0.95);
            box-shadow: 0 10px 24px rgba(40, 34, 88, 0.10);
            transform: translateY(-1px);
        }

        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, rgba(237, 241, 255, 0.98) 0%, rgba(227, 233, 255, 0.98) 100%);
            color: #20305a;
            border: 1px solid rgba(190, 203, 255, 0.98);
            border-radius: 14px;
            min-height: 2.28rem;
            padding: 0.4rem 0.75rem;
            font-size: 0.95rem;
            font-weight: 700;
            box-shadow: 0 10px 22px rgba(23, 31, 72, 0.14);
            display: flex;
            justify-content: flex-start;
            align-items: center;
        }

        [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
            transform: translateY(-1px);
            box-shadow: 0 12px 28px rgba(23, 31, 72, 0.16);
        }

        [data-testid="stSidebar"] .sidebar-meta-block {
            background: rgba(255, 255, 255, 0.76);
            border: 1px solid rgba(210, 219, 242, 0.88);
            border-radius: 16px;
            padding: 0.8rem 0.9rem;
            margin-top: 0.95rem;
        }

        [data-testid="stSidebar"] .sidebar-meta-title {
            font-size: 0.86rem;
            font-weight: 700;
            color: #23304d !important;
            margin-bottom: 0.45rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_nav_item(item: dict, active_key: str) -> None:
    """渲染一个紧凑的侧边栏导航项。"""
    item_active = item["key"] == active_key
    accent_class = "sidebar-nav-item active" if item_active else "sidebar-nav-item"
    accent_col, button_col = st.columns([0.08, 0.92], gap="small")
    with accent_col:
        st.markdown(
            f'<div class="{accent_class}"><div class="sidebar-nav-accent"></div></div>',
            unsafe_allow_html=True,
        )
    with button_col:
        if st.button(
            f'{item["icon"]} {item["label"]}',
            key=item["key"],
            help=item["help"],
            type="primary" if item_active else "secondary",
            use_container_width=True,
        ):
            activate_sidebar_view(item["flag"])


def render_sidebar_nav_group(title: str, description: str, items: list[dict], active_key: str) -> None:
    """渲染一个分组导航卡片。"""
    with st.container(border=True):
        st.markdown(f'<div class="sidebar-nav-card-title">{title}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="sidebar-nav-card-note">{description}</div>', unsafe_allow_html=True)
        for item in items:
            render_sidebar_nav_item(item, active_key)


def render_sidebar_navigation() -> None:
    """渲染现代化分组侧边栏导航。"""
    render_sidebar_nav_styles()
    active_key = get_active_sidebar_view()
    st.markdown('<div class="sidebar-nav-shell">', unsafe_allow_html=True)
    render_sidebar_nav_group(
        SIDEBAR_HOME_ITEM["title"],
        "进入工作台，先看关注池，再继续分析、发现股票和量化验证",
        [SIDEBAR_HOME_ITEM],
        active_key,
    )
    for group in SIDEBAR_NAV_GROUPS:
        render_sidebar_nav_group(group["title"], group["description"], group["items"], active_key)
    st.markdown("</div>", unsafe_allow_html=True)


def render_workbench_page_header(title: str, description: str, *, primary_action_label: str | None = None, secondary_action_label: str | None = None) -> None:
    """渲染统一工作台风格的页面页头。"""
    has_actions = bool(primary_action_label or secondary_action_label)
    if has_actions:
        left_col, right_col = st.columns([1.7, 0.8], gap="large")
    else:
        left_col, right_col = st.container(), None
    with left_col:
        st.markdown('<div class="workbench-page-title">', unsafe_allow_html=True)
        st.markdown(f"<h1>{title}</h1>", unsafe_allow_html=True)
        st.markdown(f'<p class="workbench-page-subtitle">{description}</p>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    if right_col is not None:
        with right_col:
            action_cols = st.columns(2, gap="small")
            with action_cols[0]:
                if secondary_action_label:
                    st.button(secondary_action_label, key="workbench_header_secondary_action", use_container_width=True)
            with action_cols[1]:
                if primary_action_label:
                    st.button(primary_action_label, key="workbench_header_primary_action", type="primary", use_container_width=True)


def render_workbench_section_header(title: str, description: str) -> None:
    """渲染统一工作台区块标题。"""
    st.markdown(
        f"""
        <div class="workbench-section-header">
            <div class="workbench-section-title">{title}</div>
            <div class="workbench-section-note">{description}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# 自定义CSS样式 - 专业版
st.markdown("""
<style>
    /* 全局样式 */
    .main {
        background: #f5f8fd;
        background-attachment: fixed;
    }
    
    .stApp {
        background: #f5f8fd;
    }
    
    /* 主容器 */
    .block-container {
        padding-top: 1.35rem;
        padding-bottom: 2rem;
        background: #fbfcff;
        border-radius: 28px;
        border: 1px solid #e5ecf8;
        box-shadow: 0 18px 40px rgba(93, 112, 160, 0.08);
        margin-top: 0.75rem;
    }

    .workbench-shell {
        display: flex;
        flex-direction: column;
        gap: 1.2rem;
    }

    .workbench-page-title {
        padding: 0.15rem 0;
    }

    .workbench-page-title h1 {
        font-size: 2.2rem;
        font-weight: 800;
        color: #1f2840;
        margin: 0;
        letter-spacing: -0.03em;
    }

    .workbench-page-subtitle {
        text-align: left;
        color: #6f7c99;
        font-size: 0.98rem;
        margin: 0.55rem 0 0 0;
        font-weight: 400;
        line-height: 1.65;
        max-width: 54rem;
    }

    .workbench-section-title {
        font-size: 1.65rem;
        font-weight: 800;
        color: #23304d;
        margin: 0;
        letter-spacing: -0.03em;
    }

    .workbench-section-note {
        color: #71809a;
        font-size: 0.92rem;
        line-height: 1.6;
        margin: 0.55rem 0 0 0;
    }

    .workbench-section-card {
        background: #ffffff;
        border: 1px solid #e5ecf8;
        border-radius: 24px;
        padding: 1.45rem 1.5rem;
        box-shadow: 0 12px 26px rgba(100, 112, 156, 0.06);
    }
    
    /* 标签页样式 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
        background: #edf3fb;
        padding: 0.75rem 1rem;
        border-radius: 15px;
        border: 1px solid #dce5f2;
        box-shadow: 0 8px 18px rgba(121, 140, 182, 0.08);
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 52px;
        background: rgba(255, 255, 255, 0.76);
        border-radius: 10px;
        color: #42506b;
        font-weight: 600;
        font-size: 1rem;
        padding: 0 1.35rem;
        border: 1px solid transparent;
        transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background: #f8fbff;
    }
    
    .stTabs [aria-selected="true"] {
        background: white !important;
        color: #3656dc !important;
        border: 1px solid #cfd9ee;
        box-shadow: 0 8px 16px rgba(96, 112, 154, 0.12);
    }
    
    /* 侧边栏美化 */
    .css-1d391kg, [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #eef3ff 0%, #ebe9ff 54%, #f5f2ff 100%);
        padding-top: 0.35rem;
    }

    [data-testid="stSidebarUserContent"] {
        padding-top: 0.15rem !important;
    }

    [data-testid="stSidebarContent"] {
        padding-top: 0 !important;
    }

    [data-testid="stSidebarHeader"] {
        min-height: 0 !important;
        height: auto !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        margin-bottom: 0 !important;
    }

    [data-testid="stSidebarHeader"] > div {
        margin: 0 !important;
        min-height: 0 !important;
    }

    [data-testid="stSidebarCollapseButton"] {
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }
    
    .css-1d391kg h1, .css-1d391kg h2, .css-1d391kg h3,
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        color: #23304d !important;
    }
    
    .css-1d391kg .stMarkdown, [data-testid="stSidebar"] .stMarkdown {
        color: #3b4867 !important;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(255, 255, 255, 0.76);
        border: 1px solid rgba(188, 198, 235, 0.72);
        border-radius: 18px;
        box-shadow: 0 10px 28px rgba(87, 97, 152, 0.10);
        backdrop-filter: blur(8px);
    }
    
    /* 分析师卡片 */
    .agent-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        margin: 1rem 0;
        border-left: 5px solid #667eea;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        transition: transform 0.3s ease;
    }
    
    .agent-card:hover {
        transform: translateX(5px);
    }
    
    /* 决策卡片 */
    .decision-card {
        background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
        padding: 2rem;
        border-radius: 15px;
        border: 3px solid #4caf50;
        margin: 1.5rem 0;
        box-shadow: 0 8px 30px rgba(76, 175, 80, 0.2);
    }
    
    /* 警告卡片 */
    .warning-card {
        background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        border-left: 5px solid #ff9800;
        box-shadow: 0 4px 15px rgba(255, 152, 0, 0.2);
    }
    
    /* 指标卡片 */
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
        text-align: center;
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        border-top: 4px solid #667eea;
    }
    
    .metric-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.15);
    }
    
    /* 按钮美化 */
    .stButton>button {
        border-radius: 14px;
        padding: 0.46rem 0.84rem;
        font-weight: 600;
        font-size: 0.92rem;
        transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
        box-shadow: 0 4px 10px rgba(121, 140, 182, 0.08);
        min-height: 2.32rem;
    }

    .stButton>button[kind="secondary"] {
        background: #ffffff;
        color: #25324b;
        border: 1px solid #d8e2f0;
    }

    .stButton>button[kind="secondary"]:hover {
        background: #f5f8fd;
        color: #1f2c45;
        border-color: #c7d5ea;
        box-shadow: 0 8px 18px rgba(121, 140, 182, 0.10);
    }

    .stButton>button[kind="primary"] {
        background: #4f6ef7;
        color: white;
        border: 1px solid #4f6ef7;
        box-shadow: 0 8px 18px rgba(79, 110, 247, 0.16);
    }
    
    .stButton>button[kind="primary"]:hover {
        background: #4562e3;
        border-color: #4562e3;
        box-shadow: 0 10px 20px rgba(79, 110, 247, 0.18);
    }
    
    /* 输入框美化 */
    .stTextInput>div>div>input {
        border-radius: 10px;
        border: 2px solid #e0e0e0;
        padding: 0.75rem;
        font-size: 1rem;
        transition: border-color 0.3s ease;
    }
    
    .stTextInput>div>div>input:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }
    
    /* 进度条美化 */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    }
    
    /* 成功/错误/警告/信息消息框 */
    .stSuccess, .stError, .stWarning, .stInfo {
        border-radius: 10px;
        padding: 1rem;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    }
    
    /* 图表容器 */
    .js-plotly-plot {
        border-radius: 15px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
    }
    
    /* Expander美化 */
    .streamlit-expanderHeader {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        border-radius: 10px;
        font-weight: 600;
    }
    
    /* 数据框美化 */
    .dataframe {
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    }
    
    /* 隐藏Streamlit默认元素 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 响应式设计 */
    @media (max-width: 768px) {
        .workbench-page-title h1 {
            font-size: 1.7rem;
        }
        .stTabs [data-baseweb="tab"] {
            font-size: 0.9rem;
            padding: 0 1rem;
        }
    }
</style>
""", unsafe_allow_html=True)

def main():
    st.session_state.setdefault("selected_model", config.DEFAULT_MODEL_NAME)
    api_key_status = check_api_key()

    # 侧边栏
    with st.sidebar:
        render_sidebar_navigation()

    # 检查是否显示历史记录
    if 'show_history' in st.session_state and st.session_state.show_history:
        display_history_records()
        return

    # 检查是否显示监测面板
    if 'show_monitor' in st.session_state and st.session_state.show_monitor:
        display_monitor_manager()
        return

    # 检查是否显示主力选股
    if 'show_main_force' in st.session_state and st.session_state.show_main_force:
        display_main_force_selector()
        return
    
    # 检查是否显示低价擒牛
    if 'show_low_price_bull' in st.session_state and st.session_state.show_low_price_bull:
        from low_price_bull_ui import display_low_price_bull
        display_low_price_bull()
        return
    
    # 检查是否显示小市值策略
    if 'show_small_cap' in st.session_state and st.session_state.show_small_cap:
        from small_cap_ui import display_small_cap
        display_small_cap()
        return
    
    # 检查是否显示净利增长策略
    if 'show_profit_growth' in st.session_state and st.session_state.show_profit_growth:
        from profit_growth_ui import display_profit_growth
        display_profit_growth()
        return

    # 检查是否显示低估值策略
    if 'show_value_stock' in st.session_state and st.session_state.show_value_stock:
        from value_stock_ui import display_value_stock
        display_value_stock()
        return

    # 检查是否显示智策板块
    if 'show_sector_strategy' in st.session_state and st.session_state.show_sector_strategy:
        display_sector_strategy()
        return

    # 检查是否显示智瞰龙虎
    if 'show_longhubang' in st.session_state and st.session_state.show_longhubang:
        display_longhubang()
        return

    # 检查是否显示AI盯盘
    if 'show_smart_monitor' in st.session_state and st.session_state.show_smart_monitor:
        smart_monitor_ui()
        return

    # 检查是否显示量化模拟
    if 'show_quant_sim' in st.session_state and st.session_state.show_quant_sim:
        display_quant_sim()
        return

    # 检查是否显示历史回放
    if 'show_quant_replay' in st.session_state and st.session_state.show_quant_replay:
        display_quant_replay()
        return

    # 检查是否显示持仓分析
    if 'show_portfolio' in st.session_state and st.session_state.show_portfolio:
        from portfolio_ui import display_portfolio_manager
        display_portfolio_manager()
        return

    # 检查是否显示新闻流量监测
    if 'show_news_flow' in st.session_state and st.session_state.show_news_flow:
        display_news_flow_monitor()
        return

    # 检查是否显示宏观分析
    if 'show_macro_analysis' in st.session_state and st.session_state.show_macro_analysis:
        from macro_analysis_ui import display_macro_analysis
        display_macro_analysis()
        return

    # 检查是否显示宏观周期分析
    if 'show_macro_cycle' in st.session_state and st.session_state.show_macro_cycle:
        from macro_cycle_ui import display_macro_cycle
        display_macro_cycle()
        return
    
    # 检查是否显示环境配置
    if 'show_config' in st.session_state and st.session_state.show_config:
        display_config_manager()
        return

    render_workbench_page_header(
        "股票工作台",
        "先看关注池，再继续做股票分析、发现股票、研究情报和量化验证，让后续动作围绕同一个主池展开。",
    )

    display_watchlist_workbench(activate_sidebar_view)

    st.markdown("---")

    workspace_left, workspace_right = st.columns([1.05, 1.35], gap="large")

    with workspace_left:
        render_workbench_section_header(
            "分析工作区",
            "在统一的工作台里配置分析模式、输入股票并组合分析师团队，保持操作入口清晰稳定。",
        )
        with st.container(border=True):
            col_mode1, col_mode2, col_mode3 = st.columns([1.1, 1.7, 1.2], gap="large")
            with col_mode1:
                analysis_mode = st.radio(
                    "分析模式",
                    ["单个分析", "批量分析"],
                    horizontal=True,
                    help="单个分析：分析单只股票；批量分析：同时分析多只股票",
                )

            with col_mode2:
                if analysis_mode == "批量分析":
                    batch_mode = st.radio(
                        "批量模式",
                        ["顺序分析", "多线程并行"],
                        horizontal=True,
                        help="顺序分析：按次序分析，稳定但较慢；多线程并行：同时分析多只，快速但消耗资源",
                    )
                    st.session_state.batch_mode = batch_mode
                else:
                    st.caption("单股模式会直接输出完整分析、团队讨论和最终决策。")

            with col_mode3:
                period = st.selectbox(
                    "数据周期",
                    ["1y", "6mo", "3mo", "1mo"],
                    index=0,
                    help="选择历史数据的时间范围",
                )

            st.divider()

            if not api_key_status:
                st.warning("❌ 当前未配置模型 API Key，请先在 .env 中设置后再开始分析。")

            if analysis_mode == "单个分析":
                input_col, analyze_col, clear_col = st.columns([4.8, 1.15, 0.95], gap="small")

                with input_col:
                    stock_input = st.text_input(
                        "🔍 请输入股票代码或名称",
                        placeholder="例如: AAPL, 000001, 00700",
                        help="支持A股(如000001)、港股(如00700)和美股(如AAPL)",
                    )

                with analyze_col:
                    st.markdown('<div style="height: 1.95rem;"></div>', unsafe_allow_html=True)
                    analyze_button = st.button("分析", type="primary", use_container_width=True)

                with clear_col:
                    st.markdown('<div style="height: 1.95rem;"></div>', unsafe_allow_html=True)
                    if st.button("清除", use_container_width=True):
                        st.cache_data.clear()
                        st.success("缓存已清除")

            else:
                stock_input = st.text_area(
                    "🔍 请输入多个股票代码（每行一个或用逗号分隔）",
                    placeholder="例如:\n000001\n600036\n00700\n\n或者: 000001, 600036, 00700, AAPL",
                    height=120,
                    help="支持多种格式：每行一个代码或用逗号分隔。支持A股、港股、美股",
                )

                action_spacer, action_col = st.columns([2.85, 1.15], gap="medium")
                with action_col:
                    action_cols = st.columns([1.0, 0.9, 0.9], gap="small")
                    with action_cols[0]:
                        analyze_button = st.button("批量", type="primary", use_container_width=True)
                    with action_cols[1]:
                        if st.button("清除", use_container_width=True):
                            st.cache_data.clear()
                            st.success("缓存已清除")
                    with action_cols[2]:
                        if st.button("清空", use_container_width=True):
                            if "batch_analysis_results" in st.session_state:
                                del st.session_state.batch_analysis_results
                            st.success("已清除批量分析结果")

            st.divider()
            st.markdown("#### 👥 分析师团队")
            st.caption("按需组合不同分析师视角，让结果和后续工作台保持同一套结构化输出。")

            col1, col2, col3 = st.columns(3, gap="large")

            with col1:
                enable_technical = st.checkbox(
                    "📊 技术分析师",
                    value=True,
                    help="负责技术指标分析、图表形态识别、趋势判断",
                )
                enable_fundamental = st.checkbox(
                    "💼 基本面分析师",
                    value=True,
                    help="负责公司财务分析、行业研究、估值分析",
                )

            with col2:
                enable_fund_flow = st.checkbox(
                    "💰 资金面分析师",
                    value=True,
                    help="负责资金流向分析、主力行为研究",
                )
                enable_risk = st.checkbox(
                    "⚠️ 风险管理师",
                    value=True,
                    help="负责风险识别、风险评估、风险控制策略制定",
                )

            with col3:
                enable_sentiment = st.checkbox(
                    "📈 市场情绪分析师",
                    value=True,
                    help="负责市场情绪研究、ARBR指标分析（仅A股）",
                )
                enable_news = st.checkbox(
                    "📰 新闻分析师",
                    value=True,
                    help="负责新闻事件分析、舆情研究（仅A股，qstock数据源）",
                )

            selected_analysts = []
            if enable_technical:
                selected_analysts.append("技术分析师")
            if enable_fundamental:
                selected_analysts.append("基本面分析师")
            if enable_fund_flow:
                selected_analysts.append("资金面分析师")
            if enable_risk:
                selected_analysts.append("风险管理师")
            if enable_sentiment:
                selected_analysts.append("市场情绪分析师")
            if enable_news:
                selected_analysts.append("新闻分析师")

            if selected_analysts:
                st.success(f"✅ 已选择 {len(selected_analysts)} 位分析师：{', '.join(selected_analysts)}")
            else:
                st.warning("⚠️ 请至少选择一位分析师")

    with workspace_right:
        render_workbench_section_header(
            "统一结果工作台",
            "分析结果、图表、团队观点和最终决策会在同一套结果面板中展开，保持阅读和复盘体验一致。",
        )
        with st.container(border=True):
            overview_left, overview_right = st.columns([1.1, 0.9], gap="large")
            with overview_left:
                st.markdown("##### 当前设置")
                st.caption("先确认当前模式与团队配置，再启动分析。")
                st.write(f"**分析模式：** {analysis_mode}")
                if analysis_mode == "批量分析":
                    st.write(f"**批量模式：** {st.session_state.get('batch_mode', '顺序分析')}")
                st.write(f"**分析师数量：** {len(selected_analysts)} 位")
            with overview_right:
                st.markdown("##### 结果将展示什么")
                st.caption("统一结果面板会承接摘要、图表、分析师观点、团队讨论和最终决策。")
                st.write("• 股票基础信息与技术指标")
                st.write("• 多分析师独立观点")
                st.write("• 团队讨论与综合结论")
                st.write("• 风险提示与操作建议")

    # 保存选择到session_state
    st.session_state.enable_technical = enable_technical
    st.session_state.enable_fundamental = enable_fundamental
    st.session_state.enable_fund_flow = enable_fund_flow
    st.session_state.enable_risk = enable_risk
    st.session_state.enable_sentiment = enable_sentiment
    st.session_state.enable_news = enable_news

    if analyze_button and stock_input:
        if not api_key_status:
            st.error("❌ 请先配置 DeepSeek API Key")
            return

        # 检查是否至少选择了一位分析师
        if not selected_analysts:
            st.error("❌ 请至少选择一位分析师参与分析")
            return

        if analysis_mode == "单个分析":
            # 单个股票分析
            # 清除之前的分析结果
            if 'analysis_completed' in st.session_state:
                del st.session_state.analysis_completed
            if 'stock_info' in st.session_state:
                del st.session_state.stock_info
            if 'agents_results' in st.session_state:
                del st.session_state.agents_results
            if 'discussion_result' in st.session_state:
                del st.session_state.discussion_result
            if 'final_decision' in st.session_state:
                del st.session_state.final_decision
            if 'just_completed' in st.session_state:
                del st.session_state.just_completed

            run_stock_analysis(stock_input, period)

        else:
            # 批量股票分析
            # 解析股票代码列表
            stock_list = parse_stock_list(stock_input)

            if not stock_list:
                st.error("❌ 请输入有效的股票代码")
                return

            if len(stock_list) > 20:
                st.warning(f"⚠️ 检测到 {len(stock_list)} 只股票，建议一次分析不超过20只")

            st.info(f"📊 准备分析 {len(stock_list)} 只股票: {', '.join(stock_list)}")

            # 清除之前的分析结果（包括单个和批量）
            if 'batch_analysis_results' in st.session_state:
                del st.session_state.batch_analysis_results
            if 'analysis_completed' in st.session_state:
                del st.session_state.analysis_completed
            if 'stock_info' in st.session_state:
                del st.session_state.stock_info
            if 'agents_results' in st.session_state:
                del st.session_state.agents_results
            if 'discussion_result' in st.session_state:
                del st.session_state.discussion_result
            if 'final_decision' in st.session_state:
                del st.session_state.final_decision
            if 'just_completed' in st.session_state:
                del st.session_state.just_completed

            # 获取批量模式
            batch_mode = st.session_state.get('batch_mode', '顺序分析')

            # 运行批量分析
            run_batch_analysis(stock_list, period, batch_mode)

    # 检查是否有已完成的批量分析结果（优先显示批量结果）
    if 'batch_analysis_results' in st.session_state and st.session_state.batch_analysis_results:
        display_batch_analysis_results(st.session_state.batch_analysis_results, period)

    # 检查是否有已完成的单个分析结果（但不是刚刚完成的，避免重复显示）
    elif 'analysis_completed' in st.session_state and st.session_state.analysis_completed:
        # 如果是刚刚完成的分析，清除标志，避免重复显示
        if st.session_state.get('just_completed', False):
            st.session_state.just_completed = False
        else:
            # 重新显示之前的分析结果（页面刷新后）
            stock_info = st.session_state.stock_info
            agents_results = st.session_state.agents_results
            discussion_result = st.session_state.discussion_result
            final_decision = st.session_state.final_decision

            # 重新获取股票数据用于显示图表
            stock_info_current, stock_data, indicators = get_stock_data(stock_info['symbol'], period)

            # 显示股票基本信息
            display_stock_info(stock_info, indicators)

            # 显示股票图表
            if stock_data is not None:
                display_stock_chart(stock_data, stock_info)

            # 显示各分析师报告
            display_agents_analysis(agents_results)

            # 显示团队讨论
            display_team_discussion(discussion_result)

            # 显示最终决策
            display_final_decision(final_decision, stock_info, agents_results, discussion_result)

    # 示例和说明
    elif not stock_input:
        st.divider()
        show_example_interface()

def check_api_key():
    """检查API密钥是否配置"""
    try:
        import config
        return bool(config.DEEPSEEK_API_KEY and config.DEEPSEEK_API_KEY.strip())
    except:
        return False

@st.cache_data(ttl=300, show_spinner=False)  # 缓存5分钟
def get_stock_data(symbol, period):
    """获取股票数据（带缓存）"""
    fetcher = StockDataFetcher()
    stock_data = fetcher.get_stock_data(symbol, period)
    stock_info = fetcher.get_stock_info(symbol, include_price_snapshot=False)

    if isinstance(stock_data, dict) and "error" in stock_data:
        if isinstance(stock_info, dict):
            stock_info["data_error"] = stock_data["error"]
        return stock_info, None, None

    if isinstance(stock_info, dict) and stock_data is not None and len(stock_data) > 0:
        latest = stock_data.iloc[-1]
        if stock_info.get("current_price") in (None, "N/A", ""):
            stock_info["current_price"] = latest.get("Close", "N/A")
        if len(stock_data) > 1:
            previous = stock_data.iloc[-2]
            prev_close = previous.get("Close")
            latest_close = latest.get("Close")
            if prev_close not in (None, 0, "N/A") and latest_close not in (None, "N/A"):
                try:
                    if stock_info.get("change_percent") in (None, "N/A", ""):
                        stock_info["change_percent"] = round(((latest_close - prev_close) / prev_close) * 100, 2)
                except Exception:
                    pass

    stock_data_with_indicators = fetcher.calculate_technical_indicators(stock_data)
    indicators = fetcher.get_latest_indicators(stock_data_with_indicators)

    return stock_info, stock_data_with_indicators, indicators

def parse_stock_list(stock_input):
    """解析股票代码列表

    支持的格式：
    - 每行一个代码
    - 逗号分隔
    - 空格分隔
    """
    if not stock_input or not stock_input.strip():
        return []

    # 先按换行符分割
    lines = stock_input.strip().split('\n')

    # 处理每一行
    stock_list = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 检查是否包含逗号
        if ',' in line:
            codes = [code.strip() for code in line.split(',')]
            stock_list.extend([code for code in codes if code])
        # 检查是否包含空格
        elif ' ' in line:
            codes = [code.strip() for code in line.split()]
            stock_list.extend([code for code in codes if code])
        else:
            stock_list.append(line)

    # 去重并保持顺序
    seen = set()
    unique_list = []
    for code in stock_list:
        if code not in seen:
            seen.add(code)
            unique_list.append(code)

    return unique_list

def analyze_single_stock_for_batch(symbol, period, enabled_analysts_config=None, selected_model=None):
    """单个股票分析（用于批量分析）

    Args:
        symbol: 股票代码
        period: 数据周期
        enabled_analysts_config: 分析师配置字典
        selected_model: 选择的AI模型，默认从 .env 的 DEFAULT_MODEL_NAME 读取

    返回分析结果或错误信息
    """
    try:
        # 使用默认模型
        if selected_model is None:
            selected_model = config.DEFAULT_MODEL_NAME
        
        # 使用默认配置
        if enabled_analysts_config is None:
            enabled_analysts_config = {
                'technical': True,
                'fundamental': True,
                'fund_flow': True,
                'risk': True,
                'sentiment': False,
                'news': False
            }

        # 1. 获取股票数据
        stock_info, stock_data, indicators = get_stock_data(symbol, period)

        if "error" in stock_info:
            return {"symbol": symbol, "error": stock_info['error'], "success": False}

        if stock_data is None:
            return {"symbol": symbol, "error": "无法获取股票历史数据", "success": False}

        # 2. 获取财务数据
        fetcher = StockDataFetcher()
        financial_data = fetcher.get_financial_data(symbol)

        # 2.5 获取季报数据（仅A股）
        quarterly_data = None
        enable_fundamental = enabled_analysts_config.get('fundamental', True)
        if enable_fundamental and fetcher._is_chinese_stock(symbol):
            try:
                from quarterly_report_data import QuarterlyReportDataFetcher
                quarterly_fetcher = QuarterlyReportDataFetcher()
                quarterly_data = quarterly_fetcher.get_quarterly_reports(symbol)
            except:
                pass

        # 获取分析师选择状态（从参数而不是session_state）
        enable_fund_flow = enabled_analysts_config.get('fund_flow', True)
        enable_sentiment = enabled_analysts_config.get('sentiment', False)
        enable_news = enabled_analysts_config.get('news', False)

        # 3. 获取资金流向数据（akshare数据源，可选）
        fund_flow_data = None
        if enable_fund_flow and fetcher._is_chinese_stock(symbol):
            try:
                from fund_flow_akshare import FundFlowAkshareDataFetcher
                fund_flow_fetcher = FundFlowAkshareDataFetcher()
                fund_flow_data = fund_flow_fetcher.get_fund_flow_data(symbol)
            except:
                pass

        # 4. 获取市场情绪数据（可选）
        sentiment_data = None
        if enable_sentiment and fetcher._is_chinese_stock(symbol):
            try:
                from market_sentiment_data import MarketSentimentDataFetcher
                sentiment_fetcher = MarketSentimentDataFetcher()
                sentiment_data = sentiment_fetcher.get_market_sentiment_data(symbol, stock_data)
            except:
                pass

        # 5. 获取新闻数据（qstock数据源，可选）
        news_data = None
        if enable_news and fetcher._is_chinese_stock(symbol):
            try:
                from qstock_news_data import QStockNewsDataFetcher
                news_fetcher = QStockNewsDataFetcher()
                news_data = news_fetcher.get_stock_news(symbol)
            except:
                pass

        # 5.5 获取风险数据（限售解禁、大股东减持、重要事件，可选）
        risk_data = None
        enable_risk = enabled_analysts_config.get('risk', True)
        if enable_risk and fetcher._is_chinese_stock(symbol):
            try:
                risk_data = fetcher.get_risk_data(symbol)
            except:
                pass

        # 6. 初始化AI分析系统
        agents = StockAnalysisAgents(model=selected_model)

        # 使用传入的分析师配置
        enabled_analysts = enabled_analysts_config

        # 7. 运行多智能体分析
        agents_results = agents.run_multi_agent_analysis(
            stock_info, stock_data, indicators, financial_data,
            fund_flow_data, sentiment_data, news_data, quarterly_data, risk_data,
            enabled_analysts=enabled_analysts_config
        )

        # 8. 团队讨论
        discussion_result = agents.conduct_team_discussion(agents_results, stock_info)

        # 9. 最终决策
        final_decision = agents.make_final_decision(discussion_result, stock_info, indicators)

        # 保存到数据库
        saved_to_db = False
        db_error = None
        try:
            record_id = db.save_analysis(
                symbol=stock_info.get('symbol', ''),
                stock_name=stock_info.get('name', ''),
                period=period,
                stock_info=stock_info,
                agents_results=agents_results,
                discussion_result=discussion_result,
                final_decision=final_decision
            )
            saved_to_db = True
            print(f"✅ {symbol} 成功保存到数据库，记录ID: {record_id}")
        except Exception as e:
            db_error = str(e)
            print(f"❌ {symbol} 保存到数据库失败: {db_error}")

        return {
            "symbol": symbol,
            "success": True,
            "stock_info": stock_info,
            "indicators": indicators,
            "agents_results": agents_results,
            "discussion_result": discussion_result,
            "final_decision": final_decision,
            "saved_to_db": saved_to_db,
            "db_error": db_error
        }

    except Exception as e:
        return {"symbol": symbol, "error": str(e), "success": False}

def run_batch_analysis(stock_list, period, batch_mode="顺序分析"):
    """运行批量股票分析"""
    import concurrent.futures
    import threading

    # 在开始分析前获取配置（从session_state）
    enabled_analysts_config = {
        'technical': st.session_state.get('enable_technical', True),
        'fundamental': st.session_state.get('enable_fundamental', True),
        'fund_flow': st.session_state.get('enable_fund_flow', True),
        'risk': st.session_state.get('enable_risk', True),
        'sentiment': st.session_state.get('enable_sentiment', False),
        'news': st.session_state.get('enable_news', False)
    }
    selected_model = st.session_state.get('selected_model', config.DEFAULT_MODEL_NAME)

    # 创建进度显示
    st.subheader(f"📊 批量分析进行中 ({batch_mode})")

    progress_bar = st.progress(0)
    status_text = st.empty()

    # 存储结果
    results = []
    total = len(stock_list)

    if batch_mode == "多线程并行":
        # 多线程并行分析
        status_text.text(f"🚀 使用多线程并行分析 {total} 只股票...")

        # 创建线程锁用于更新进度
        lock = threading.Lock()
        completed = [0]  # 使用列表以便在闭包中修改
        progress_status = [{}]  # 存储进度状态

        def analyze_with_progress(symbol):
            """包装分析函数，不在线程中访问Streamlit上下文"""
            try:
                result = analyze_single_stock_for_batch(symbol, period, enabled_analysts_config, selected_model)
                with lock:
                    completed[0] += 1
                    progress_status[0][symbol] = result
                return result
            except Exception as e:
                with lock:
                    completed[0] += 1
                    error_result = {"symbol": symbol, "error": str(e), "success": False}
                    progress_status[0][symbol] = error_result
                return error_result

        # 使用线程池执行，限制最大并发数为3以避免API限流
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_symbol = {executor.submit(analyze_with_progress, symbol): symbol
                              for symbol in stock_list}

            for future in concurrent.futures.as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    result = future.result(timeout=300)  # 5分钟超时
                    results.append(result)

                    # 在主线程中更新UI
                    progress = len(results) / total
                    progress_bar.progress(progress)

                    if result['success']:
                        status_text.text(f"✅ [{len(results)}/{total}] {symbol} 分析完成")
                    else:
                        status_text.text(f"❌ [{len(results)}/{total}] {symbol} 分析失败: {result.get('error', '未知错误')}")

                except concurrent.futures.TimeoutError:
                    results.append({"symbol": symbol, "error": "分析超时（5分钟）", "success": False})
                    progress_bar.progress(len(results) / total)
                    status_text.text(f"⏱️ [{len(results)}/{total}] {symbol} 分析超时")
                except Exception as e:
                    results.append({"symbol": symbol, "error": str(e), "success": False})
                    progress_bar.progress(len(results) / total)
                    status_text.text(f"❌ [{len(results)}/{total}] {symbol} 出现错误")

    else:
        # 顺序分析
        status_text.text(f"📝 按顺序分析 {total} 只股票...")

        for i, symbol in enumerate(stock_list, 1):
            status_text.text(f"🔍 [{i}/{total}] 正在分析 {symbol}...")

            try:
                result = analyze_single_stock_for_batch(symbol, period, enabled_analysts_config, selected_model)
            except Exception as e:
                result = {"symbol": symbol, "error": str(e), "success": False}

            results.append(result)

            # 更新进度
            progress = i / total
            progress_bar.progress(progress)

            if result['success']:
                status_text.text(f"✅ [{i}/{total}] {symbol} 分析完成")
            else:
                status_text.text(f"❌ [{i}/{total}] {symbol} 分析失败: {result.get('error', '未知错误')}")

    # 完成
    progress_bar.progress(1.0)

    # 统计结果
    success_count = sum(1 for r in results if r['success'])
    failed_count = total - success_count
    saved_count = sum(1 for r in results if r.get('saved_to_db', False))

    # 显示完成信息
    if success_count > 0:
        status_text.success(f"✅ 批量分析完成！成功 {success_count} 只，失败 {failed_count} 只，已保存 {saved_count} 只到历史记录")

        # 显示保存失败的股票
        save_failed = [r['symbol'] for r in results if r.get('success') and not r.get('saved_to_db', False)]
        if save_failed:
            st.warning(f"⚠️ 以下股票分析成功但保存失败: {', '.join(save_failed)}")
    else:
        status_text.error(f"❌ 批量分析完成，但所有股票都分析失败")

    # 保存结果到session_state
    st.session_state.batch_analysis_results = results
    st.session_state.batch_analysis_mode = batch_mode

    progress_bar.empty()

    # 自动显示结果
    st.rerun()

def run_stock_analysis(symbol, period):
    """运行股票分析"""

    # 进度条
    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        # 1. 获取股票数据
        status_text.text("📈 正在获取股票数据...")
        progress_bar.progress(10)

        stock_info, stock_data, indicators = get_stock_data(symbol, period)

        if "error" in stock_info:
            st.error(f"❌ {stock_info['error']}")
            return

        if stock_data is None:
            data_error = stock_info.get("data_error") if isinstance(stock_info, dict) else None
            if data_error:
                st.error(f"❌ 无法获取股票历史数据：{data_error}")
            else:
                st.error("❌ 无法获取股票历史数据")
            return

        # 显示股票基本信息
        display_stock_info(stock_info, indicators)
        progress_bar.progress(20)

        # 显示股票图表
        display_stock_chart(stock_data, stock_info)
        progress_bar.progress(30)

        # 2. 获取财务数据
        status_text.text("📊 正在获取财务数据...")
        fetcher = StockDataFetcher()  # 创建fetcher实例
        financial_data = fetcher.get_financial_data(symbol)
        progress_bar.progress(35)

        # 2.5 获取季报数据（仅在选择了基本面分析师且为A股时）
        enable_fundamental = st.session_state.get('enable_fundamental', True)
        quarterly_data = None
        if enable_fundamental and fetcher._is_chinese_stock(symbol):
            status_text.text("📊 正在获取季报数据（akshare数据源）...")
            try:
                from quarterly_report_data import QuarterlyReportDataFetcher
                quarterly_fetcher = QuarterlyReportDataFetcher()
                quarterly_data = quarterly_fetcher.get_quarterly_reports(symbol)
                if quarterly_data and quarterly_data.get('data_success'):
                    income_count = quarterly_data.get('income_statement', {}).get('periods', 0) if quarterly_data.get('income_statement') else 0
                    balance_count = quarterly_data.get('balance_sheet', {}).get('periods', 0) if quarterly_data.get('balance_sheet') else 0
                    cash_flow_count = quarterly_data.get('cash_flow', {}).get('periods', 0) if quarterly_data.get('cash_flow') else 0
                    st.info(f"✅ 成功获取季报数据：利润表{income_count}期，资产负债表{balance_count}期，现金流量表{cash_flow_count}期")
                else:
                    st.warning("⚠️ 未能获取季报数据，将基于基本财务数据分析")
            except Exception as e:
                st.warning(f"⚠️ 获取季报数据时出错: {str(e)}")
                quarterly_data = None
        elif enable_fundamental and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持季报数据")
        progress_bar.progress(37)

        # 获取分析师选择状态
        enable_fund_flow = st.session_state.get('enable_fund_flow', True)
        enable_sentiment = st.session_state.get('enable_sentiment', False)
        enable_news = st.session_state.get('enable_news', False)

        # 3. 获取资金流向数据（仅在选择了资金面分析师时，使用akshare数据源）
        fund_flow_data = None
        if enable_fund_flow and fetcher._is_chinese_stock(symbol):
            status_text.text("💰 正在获取资金流向数据（akshare数据源）...")
            try:
                from fund_flow_akshare import FundFlowAkshareDataFetcher
                fund_flow_fetcher = FundFlowAkshareDataFetcher()
                fund_flow_data = fund_flow_fetcher.get_fund_flow_data(symbol)
                if fund_flow_data and fund_flow_data.get('data_success'):
                    days = fund_flow_data.get('fund_flow_data', {}).get('days', 0) if fund_flow_data.get('fund_flow_data') else 0
                    st.info(f"✅ 成功获取 {days} 个交易日的资金流向数据")
                else:
                    st.warning("⚠️ 未能获取资金流向数据，将基于技术指标进行资金面分析")
            except Exception as e:
                st.warning(f"⚠️ 获取资金流向数据时出错: {str(e)}")
                fund_flow_data = None
        elif enable_fund_flow and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持资金流向数据")
        progress_bar.progress(40)

        # 4. 获取市场情绪数据（仅在选择了市场情绪分析师时）
        sentiment_data = None
        if enable_sentiment and fetcher._is_chinese_stock(symbol):
            status_text.text("📊 正在获取市场情绪数据（ARBR等指标）...")
            try:
                from market_sentiment_data import MarketSentimentDataFetcher
                sentiment_fetcher = MarketSentimentDataFetcher()
                sentiment_data = sentiment_fetcher.get_market_sentiment_data(symbol, stock_data)
                if sentiment_data and sentiment_data.get('data_success'):
                    st.info("✅ 成功获取市场情绪数据（ARBR、换手率、涨跌停等）")
                else:
                    st.warning("⚠️ 未能获取完整的市场情绪数据，将基于基本信息进行分析")
            except Exception as e:
                st.warning(f"⚠️ 获取市场情绪数据时出错: {str(e)}")
                sentiment_data = None
        elif enable_sentiment and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持市场情绪数据（ARBR等指标）")
        progress_bar.progress(45)

        # 5. 获取新闻数据（仅在选择了新闻分析师时，使用qstock数据源）
        news_data = None
        if enable_news and fetcher._is_chinese_stock(symbol):
            status_text.text("📰 正在获取新闻数据...")
            try:
                from qstock_news_data import QStockNewsDataFetcher
                news_fetcher = QStockNewsDataFetcher()
                news_data = news_fetcher.get_stock_news(symbol)
                if news_data and news_data.get('data_success'):
                    news_count = news_data.get('news_data', {}).get('count', 0) if news_data.get('news_data') else 0
                    st.info(f"✅ 成功从东方财富获取个股 {news_count} 条新闻")
                else:
                    st.warning("⚠️ 未能获取新闻数据，将基于基本信息进行分析")
            except Exception as e:
                st.warning(f"⚠️ 获取新闻数据时出错: {str(e)}")
                news_data = None
        elif enable_news and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持新闻数据")
        progress_bar.progress(45)

        # 5.5 获取风险数据（仅在选择了风险管理师时，使用问财数据源）
        enable_risk = st.session_state.get('enable_risk', True)
        risk_data = None
        if enable_risk and fetcher._is_chinese_stock(symbol):
            status_text.text("⚠️ 正在获取风险数据（限售解禁、大股东减持、重要事件）...")
            try:
                risk_data = fetcher.get_risk_data(symbol)
                if risk_data and risk_data.get('data_success'):
                    # 统计获取到的风险数据类型
                    risk_types = []
                    if risk_data.get('lifting_ban') and risk_data['lifting_ban'].get('has_data'):
                        risk_types.append("限售解禁")
                    if risk_data.get('shareholder_reduction') and risk_data['shareholder_reduction'].get('has_data'):
                        risk_types.append("大股东减持")
                    if risk_data.get('important_events') and risk_data['important_events'].get('has_data'):
                        risk_types.append("重要事件")

                    if risk_types:
                        st.info(f"✅ 成功获取风险数据：{', '.join(risk_types)}")
                    else:
                        st.info("ℹ️ 暂无风险相关数据")
                else:
                    st.info("ℹ️ 暂无风险相关数据，将基于基本信息进行风险分析")
            except Exception as e:
                st.warning(f"⚠️ 获取风险数据时出错: {str(e)}")
                risk_data = None
        elif enable_risk and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持风险数据（限售解禁、大股东减持等）")
        progress_bar.progress(50)

        # 6. 初始化AI分析系统
        status_text.text("🤖 正在初始化AI分析系统...")
        # 使用选择的模型
        selected_model = st.session_state.get('selected_model', config.DEFAULT_MODEL_NAME)
        agents = StockAnalysisAgents(model=selected_model)
        progress_bar.progress(55)

        # 获取所有分析师选择状态
        enable_technical = st.session_state.get('enable_technical', True)
        enable_fundamental = st.session_state.get('enable_fundamental', True)
        enable_risk = st.session_state.get('enable_risk', True)

        # 创建分析师启用字典
        enabled_analysts = {
            'technical': enable_technical,
            'fundamental': enable_fundamental,
            'fund_flow': enable_fund_flow,
            'risk': enable_risk,
            'sentiment': enable_sentiment,
            'news': enable_news
        }

        # 7. 运行多智能体分析（传入所有数据和分析师选择）
        status_text.text("🔍 AI分析师团队正在分析,请耐心等待几分钟...")
        agents_results = agents.run_multi_agent_analysis(
            stock_info, stock_data, indicators, financial_data,
            fund_flow_data, sentiment_data, news_data, quarterly_data, risk_data,
            enabled_analysts=enabled_analysts
        )
        progress_bar.progress(75)

        # 显示各分析师报告
        display_agents_analysis(agents_results)

        # 8. 团队讨论
        status_text.text("🤝 分析团队正在讨论...")
        discussion_result = agents.conduct_team_discussion(agents_results, stock_info)
        progress_bar.progress(88)

        # 显示团队讨论
        display_team_discussion(discussion_result)

        # 9. 最终决策
        status_text.text("📋 正在制定最终投资决策...")
        final_decision = agents.make_final_decision(discussion_result, stock_info, indicators)
        progress_bar.progress(100)

        # 显示最终决策
        display_final_decision(final_decision, stock_info, agents_results, discussion_result)

        # 保存分析结果到session_state（用于页面刷新后显示）
        st.session_state.analysis_completed = True
        st.session_state.stock_info = stock_info
        st.session_state.agents_results = agents_results
        st.session_state.discussion_result = discussion_result
        st.session_state.final_decision = final_decision
        st.session_state.just_completed = True  # 标记刚刚完成分析

        # 保存到数据库
        try:
            db.save_analysis(
                symbol=stock_info.get('symbol', ''),
                stock_name=stock_info.get('name', ''),
                period=period,
                stock_info=stock_info,
                agents_results=agents_results,
                discussion_result=discussion_result,
                final_decision=final_decision
            )
            st.success("✅ 分析记录已保存到数据库")
        except Exception as e:
            st.warning(f"⚠️ 保存到数据库时出现错误: {str(e)}")

        status_text.text("✅ 分析完成！")
        status_text.empty()
        progress_bar.empty()

    except Exception as e:
        st.error(f"❌ 分析过程中出现错误: {str(e)}")
        progress_bar.empty()
        status_text.empty()

def display_stock_info(stock_info, indicators):
    """显示股票基本信息"""
    st.subheader(f"📊 {stock_info.get('name', 'N/A')} ({stock_info.get('symbol', 'N/A')})")

    # 基本信息卡片
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        current_price = stock_info.get('current_price', 'N/A')
        st.metric("当前价格", f"{current_price}")

    with col2:
        change_percent = stock_info.get('change_percent', 'N/A')
        if isinstance(change_percent, (int, float)):
            st.metric("涨跌幅", f"{change_percent:.2f}%", f"{change_percent:.2f}%")
        else:
            st.metric("涨跌幅", f"{change_percent}")

    with col3:
        pe_ratio = stock_info.get('pe_ratio', 'N/A')
        st.metric("市盈率", f"{pe_ratio}")

    with col4:
        pb_ratio = stock_info.get('pb_ratio', 'N/A')
        st.metric("市净率", f"{pb_ratio}")

    with col5:
        market_cap = stock_info.get('market_cap', 'N/A')
        if isinstance(market_cap, (int, float)):
            market_cap_str = f"{market_cap/1e9:.2f}B" if market_cap > 1e9 else f"{market_cap/1e6:.2f}M"
            st.metric("市值", market_cap_str)
        else:
            st.metric("市值", f"{market_cap}")

    # 技术指标
    if indicators and not isinstance(indicators, dict) or "error" not in indicators:
        st.subheader("📈 关键技术指标")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            rsi = indicators.get('rsi', 'N/A')
            if isinstance(rsi, (int, float)):
                rsi_color = "normal"
                if rsi > 70:
                    rsi_color = "inverse"
                elif rsi < 30:
                    rsi_color = "off"
                st.metric("RSI", f"{rsi:.2f}")
            else:
                st.metric("RSI", f"{rsi}")

        with col2:
            ma20 = indicators.get('ma20', 'N/A')
            if isinstance(ma20, (int, float)):
                st.metric("MA20", f"{ma20:.2f}")
            else:
                st.metric("MA20", f"{ma20}")

        with col3:
            volume_ratio = indicators.get('volume_ratio', 'N/A')
            if isinstance(volume_ratio, (int, float)):
                st.metric("量比", f"{volume_ratio:.2f}")
            else:
                st.metric("量比", f"{volume_ratio}")

        with col4:
            macd = indicators.get('macd', 'N/A')
            if isinstance(macd, (int, float)):
                st.metric("MACD", f"{macd:.4f}")
            else:
                st.metric("MACD", f"{macd}")

def display_stock_chart(stock_data, stock_info):
    """显示股票图表"""
    st.subheader("📈 股价走势图")

    # 创建蜡烛图
    fig = go.Figure()

    # 添加蜡烛图
    fig.add_trace(go.Candlestick(
        x=stock_data.index,
        open=stock_data['Open'],
        high=stock_data['High'],
        low=stock_data['Low'],
        close=stock_data['Close'],
        name="K线"
    ))

    # 添加移动平均线
    if 'MA5' in stock_data.columns:
        fig.add_trace(go.Scatter(
            x=stock_data.index,
            y=stock_data['MA5'],
            name="MA5",
            line=dict(color='orange', width=1)
        ))

    if 'MA20' in stock_data.columns:
        fig.add_trace(go.Scatter(
            x=stock_data.index,
            y=stock_data['MA20'],
            name="MA20",
            line=dict(color='blue', width=1)
        ))

    if 'MA60' in stock_data.columns:
        fig.add_trace(go.Scatter(
            x=stock_data.index,
            y=stock_data['MA60'],
            name="MA60",
            line=dict(color='purple', width=1)
        ))

    # 布林带
    if 'BB_upper' in stock_data.columns and 'BB_lower' in stock_data.columns:
        fig.add_trace(go.Scatter(
            x=stock_data.index,
            y=stock_data['BB_upper'],
            name="布林上轨",
            line=dict(color='red', width=1, dash='dash')
        ))
        fig.add_trace(go.Scatter(
            x=stock_data.index,
            y=stock_data['BB_lower'],
            name="布林下轨",
            line=dict(color='green', width=1, dash='dash'),
            fill='tonexty',
            fillcolor='rgba(0,100,80,0.1)'
        ))

    fig.update_layout(
        title=f"{stock_info.get('name', 'N/A')} 股价走势",
        xaxis_title="日期",
        yaxis_title="价格",
        height=500,
        showlegend=True
    )

    # 生成唯一的key
    chart_key = f"main_stock_chart_{stock_info.get('symbol', 'unknown')}_{int(time.time())}"
    st.plotly_chart(fig, use_container_width=True, config={'responsive': True}, key=chart_key)

    # 成交量图
    if 'Volume' in stock_data.columns:
        fig_volume = go.Figure()
        fig_volume.add_trace(go.Bar(
            x=stock_data.index,
            y=stock_data['Volume'],
            name="成交量",
            marker_color='lightblue'
        ))

        fig_volume.update_layout(
            title="成交量",
            xaxis_title="日期",
            yaxis_title="成交量",
            height=200
        )

        # 生成唯一的key
        volume_key = f"volume_chart_{stock_info.get('symbol', 'unknown')}_{int(time.time())}"
        st.plotly_chart(fig_volume, use_container_width=True, config={'responsive': True}, key=volume_key)

def display_agents_analysis(agents_results):
    """显示各分析师报告"""
    st.subheader("🤖 AI分析师团队报告")

    # 创建标签页
    tab_names = []
    tab_contents = []

    for agent_key, agent_result in agents_results.items():
        agent_name = agent_result.get('agent_name', '未知分析师')
        tab_names.append(agent_name)
        tab_contents.append(agent_result)

    tabs = st.tabs(tab_names)

    for i, tab in enumerate(tabs):
        with tab:
            agent_result = tab_contents[i]

            # 分析师信息
            st.markdown(f"""
            <div class="agent-card">
                <h4>👨‍💼 {agent_result.get('agent_name', '未知')}</h4>
                <p><strong>职责：</strong>{agent_result.get('agent_role', '未知')}</p>
                <p><strong>关注领域：</strong>{', '.join(agent_result.get('focus_areas', []))}</p>
                <p><strong>分析时间：</strong>{agent_result.get('timestamp', '未知')}</p>
            </div>
            """, unsafe_allow_html=True)

            # 分析报告
            st.markdown("**📄 分析报告:**")
            st.write(agent_result.get('analysis', '暂无分析'))

def display_team_discussion(discussion_result):
    """显示团队讨论"""
    st.subheader("🤝 分析团队讨论")

    st.markdown("""
    <div class="agent-card">
        <h4>💭 团队综合讨论</h4>
        <p>各位分析师正在就该股票进行深入讨论，整合不同维度的分析观点...</p>
    </div>
    """, unsafe_allow_html=True)

    st.write(discussion_result)

def display_final_decision(final_decision, stock_info, agents_results=None, discussion_result=None):
    """显示最终投资决策"""
    st.subheader("📋 最终投资决策")

    if isinstance(final_decision, dict) and "decision_text" not in final_decision:
        # JSON格式的决策
        col1, col2 = st.columns([1, 2])

        with col1:
            # 投资评级
            rating = final_decision.get('rating', '未知')
            rating_color = {"买入": "🟢", "持有": "🟡", "卖出": "🔴"}.get(rating, "⚪")

            st.markdown(f"""
            <div class="decision-card">
                <h3 style="text-align: center;">{rating_color} {rating}</h3>
                <h4 style="text-align: center;">投资评级</h4>
            </div>
            """, unsafe_allow_html=True)

            # 关键指标
            confidence = final_decision.get('confidence_level', 'N/A')
            st.metric("信心度", f"{confidence}/10")

            target_price = final_decision.get('target_price', 'N/A')
            st.metric("目标价格", f"{target_price}")

            position_size = final_decision.get('position_size', 'N/A')
            st.metric("建议仓位", f"{position_size}")

        with col2:
            # 详细建议
            st.markdown("**🎯 操作建议:**")
            st.write(final_decision.get('operation_advice', '暂无建议'))

            st.markdown("**📍 关键位置:**")
            col2_1, col2_2 = st.columns(2)

            with col2_1:
                st.write(f"**进场区间:** {final_decision.get('entry_range', 'N/A')}")
                st.write(f"**止盈位:** {final_decision.get('take_profit', 'N/A')}")

            with col2_2:
                st.write(f"**止损位:** {final_decision.get('stop_loss', 'N/A')}")
                st.write(f"**持有周期:** {final_decision.get('holding_period', 'N/A')}")

        # 风险提示
        risk_warning = final_decision.get('risk_warning', '')
        if risk_warning:
            st.markdown(f"""
            <div class="warning-card">
                <h4>⚠️ 风险提示</h4>
                <p>{risk_warning}</p>
            </div>
            """, unsafe_allow_html=True)

    else:
        # 文本格式的决策
        decision_text = final_decision.get('decision_text', str(final_decision))
        st.write(decision_text)

    # 添加PDF导出功能
    st.markdown("---")
    if agents_results and discussion_result:
        display_pdf_export_section(stock_info, agents_results, discussion_result, final_decision)
    else:
        st.warning("⚠️ PDF导出功能需要完整的分析数据")

def show_example_interface():
    """显示示例界面"""
    render_workbench_section_header(
        "快速上手",
        "先熟悉支持市场、分析维度和示例代码，再进入统一结果工作台查看完整结论。",
    )

    intro_col, sample_col = st.columns(2, gap="large")
    with intro_col:
        with st.container(border=True):
            st.markdown("##### 如何使用")
            st.caption("按照固定节奏完成输入、分析和复盘，结果会统一落到工作台面板。")
            st.markdown(
                """
                1. **输入股票代码**：支持 A 股（如 000001）、港股（如 00700）和美股（如 AAPL）
                2. **点击开始分析**：系统会启动多位 AI 分析师并行给出观点
                3. **查看统一结果面板**：摘要、图表、分析师观点、讨论和最终决策会同步呈现
                4. **结合风险提示执行**：将结论延伸到量化模拟、历史回放和后续跟踪
                """
            )
            st.markdown("##### 分析维度")
            st.markdown(
                """
                - **技术面**：趋势、指标、支撑阻力
                - **基本面**：财务、估值、行业分析
                - **资金面**：资金流向、主力行为
                - **风险管理**：风险识别与控制
                - **市场情绪**：情绪指标、热点分析
                """
            )
    with sample_col:
        with st.container(border=True):
            st.markdown("##### 示例股票代码")
            st.caption("可直接复制这些示例，快速验证单股分析、批量分析和跨市场支持。")
            st.markdown(
                """
                **A股热门**
                - 000001（平安银行）
                - 600036（招商银行）
                - 600519（贵州茅台）

                **港股热门**
                - 00700 / 700（腾讯控股）
                - 09988 / 9988（阿里巴巴-SW）
                - 01810 / 1810（小米集团-W）

                **美股热门**
                - AAPL（苹果）
                - MSFT（微软）
                - NVDA（英伟达）
                """
            )

    st.info("💡 首次运行前，请先在 .env 中配置 `DEEPSEEK_API_KEY`，分析工作台才能正常调用模型。")

    with st.container(border=True):
        st.markdown("##### 市场支持说明")
        st.caption("不同市场的数据完备度不同，建议先从支持最完整的 A 股工作流开始。")
        st.markdown(
            """
            - **A股**：完整支持（技术分析、财务数据、资金流向、市场情绪、新闻数据 qstock）
            - **港股**：部分支持（技术分析、21 项财务指标）
            - **美股**：完整支持（技术分析、财务数据）
            """
        )
        st.markdown("##### 港股支持的财务指标")
        st.write("盈利能力（6项）、营运能力（3项）、偿债能力（2项）、市场表现（4项）、分红指标（3项）、股本结构（3项）")

def display_history_records():
    """显示历史分析记录"""
    st.subheader("📚 历史分析记录")

    # 获取所有记录
    records = db.get_all_records()

    if not records:
        st.info("📭 暂无历史分析记录")
        return

    st.write(f"📊 共找到 {len(records)} 条分析记录")

    # 搜索和筛选
    col1, col2 = st.columns([3, 1])
    with col1:
        search_term = st.text_input("🔍 搜索股票代码或名称", placeholder="输入股票代码或名称进行搜索")
    with col2:
        st.write("")
        st.write("")
        if st.button("🔄 刷新列表"):
            st.rerun()

    # 筛选记录
    filtered_records = records
    if search_term:
        filtered_records = [
            record for record in records
            if search_term.lower() in record['symbol'].lower() or
               search_term.lower() in record['stock_name'].lower()
        ]

    if not filtered_records:
        st.warning("🔍 未找到匹配的记录")
        return

    # 显示记录列表
    for record in filtered_records:
        # 根据评级设置颜色和图标
        rating = record.get('rating', '未知')
        rating_color = {
            "买入": "🟢",
            "持有": "🟡",
            "卖出": "🔴",
            "强烈买入": "🟢",
            "强烈卖出": "🔴"
        }.get(rating, "⚪")

        with st.expander(f"{rating_color} {record['stock_name']} ({record['symbol']}) - {record['analysis_date']}"):
            col1, col2, col3, col4 = st.columns([2, 2, 1, 1])

            with col1:
                st.write(f"**股票代码:** {record['symbol']}")
                st.write(f"**股票名称:** {record['stock_name']}")

            with col2:
                st.write(f"**分析时间:** {record['analysis_date']}")
                st.write(f"**数据周期:** {record['period']}")
                st.write(f"**投资评级:** **{rating}**")

            with col3:
                if st.button("👀 查看详情", key=f"view_{record['id']}"):
                    st.session_state.viewing_record_id = record['id']

            with col4:
                if st.button("➕ 监测", key=f"add_monitor_{record['id']}"):
                    st.session_state.add_to_monitor_id = record['id']
                    st.session_state.viewing_record_id = record['id']

            # 删除按钮（新增一行）
            col5, _, _, _ = st.columns(4)
            with col5:
                if st.button("🗑️ 删除", key=f"delete_{record['id']}"):
                    if db.delete_record(record['id']):
                        st.success("✅ 记录已删除")
                        st.rerun()
                    else:
                        st.error("❌ 删除失败")

    # 查看详细记录
    if 'viewing_record_id' in st.session_state:
        display_record_detail(st.session_state.viewing_record_id)

def display_add_to_monitor_dialog(record):
    """显示加入监测的对话框"""
    st.markdown("---")
    st.subheader("➕ 加入监测")

    final_decision = record['final_decision']

    # 从final_decision中提取关键数据
    if isinstance(final_decision, dict):
        # 解析进场区间
        entry_range_str = final_decision.get('entry_range', 'N/A')
        entry_min = 0.0
        entry_max = 0.0

        # 尝试解析进场区间字符串，支持多种格式
        if entry_range_str and entry_range_str != 'N/A':
            try:
                import re
                # 移除常见的前缀和单位
                clean_str = str(entry_range_str).replace('¥', '').replace('元', '').replace('$', '')
                # 使用正则表达式提取数字
                # 支持格式：10.5-12.0, 10.5 - 12.0, 10.5~12.0, 10.5至12.0 等
                numbers = re.findall(r'\d+\.?\d*', clean_str)
                if len(numbers) >= 2:
                    entry_min = float(numbers[0])
                    entry_max = float(numbers[1])
            except:
                # 如果解析失败，尝试用分隔符split
                try:
                    clean_str = str(entry_range_str).replace('¥', '').replace('元', '').replace('$', '')
                    # 尝试多种分隔符
                    for sep in ['-', '~', '至', '到']:
                        if sep in clean_str:
                            parts = clean_str.split(sep)
                            if len(parts) == 2:
                                entry_min = float(parts[0].strip())
                                entry_max = float(parts[1].strip())
                                break
                except:
                    pass

        # 提取止盈和止损
        take_profit_str = final_decision.get('take_profit', 'N/A')
        stop_loss_str = final_decision.get('stop_loss', 'N/A')

        take_profit = 0.0
        stop_loss = 0.0

        # 解析止盈位
        if take_profit_str and take_profit_str != 'N/A':
            try:
                import re
                # 移除单位和符号
                clean_str = str(take_profit_str).replace('¥', '').replace('元', '').replace('$', '').strip()
                # 提取第一个数字
                numbers = re.findall(r'\d+\.?\d*', clean_str)
                if numbers:
                    take_profit = float(numbers[0])
            except:
                pass

        # 解析止损位
        if stop_loss_str and stop_loss_str != 'N/A':
            try:
                import re
                # 移除单位和符号
                clean_str = str(stop_loss_str).replace('¥', '').replace('元', '').replace('$', '').strip()
                # 提取第一个数字
                numbers = re.findall(r'\d+\.?\d*', clean_str)
                if numbers:
                    stop_loss = float(numbers[0])
            except:
                pass

        # 获取评级
        rating = final_decision.get('rating', '买入')

        # 检查是否已经在监测列表中
        from monitor_db import monitor_db
        existing_stocks = monitor_db.get_monitored_stocks()
        is_duplicate = any(stock['symbol'] == record['symbol'] for stock in existing_stocks)

        if is_duplicate:
            st.warning(f"⚠️ {record['symbol']} 已经在监测列表中。继续添加将创建重复监测项。")

        st.info(f"""
        **从分析结果中提取的数据：**
        - 进场区间: {entry_min} - {entry_max}
        - 止盈位: {take_profit if take_profit > 0 else '未设置'}
        - 止损位: {stop_loss if stop_loss > 0 else '未设置'}
        - 投资评级: {rating}
        """)

        # 显示表单供用户确认或修改
        with st.form(key=f"monitor_form_{record['id']}"):
            st.markdown("**请确认或修改监测参数：**")

            col1, col2 = st.columns([1, 1])

            with col1:
                st.subheader("🎯 关键位置")
                new_entry_min = st.number_input("进场区间最低价", value=float(entry_min), step=0.01, format="%.2f")
                new_entry_max = st.number_input("进场区间最高价", value=float(entry_max), step=0.01, format="%.2f")
                new_take_profit = st.number_input("止盈价位", value=float(take_profit), step=0.01, format="%.2f")
                new_stop_loss = st.number_input("止损价位", value=float(stop_loss), step=0.01, format="%.2f")

            with col2:
                st.subheader("⚙️ 监测设置")
                check_interval = st.slider("监测间隔(分钟)", 5, 120, 30)
                notification_enabled = st.checkbox("启用通知", value=True)
                new_rating = st.selectbox("投资评级", ["买入", "持有", "卖出"],
                                         index=["买入", "持有", "卖出"].index(rating) if rating in ["买入", "持有", "卖出"] else 0)

            col_a, col_b, col_c = st.columns(3)

            with col_a:
                submit = st.form_submit_button("✅ 确认加入监测", type="primary", width='stretch')

            with col_b:
                cancel = st.form_submit_button("❌ 取消", width='stretch')

            if submit:
                if new_entry_min > 0 and new_entry_max > 0 and new_entry_max > new_entry_min:
                    try:
                        # 添加到监测数据库
                        entry_range = {"min": new_entry_min, "max": new_entry_max}

                        stock_id = monitor_db.add_monitored_stock(
                            symbol=record['symbol'],
                            name=record['stock_name'],
                            rating=new_rating,
                            entry_range=entry_range,
                            take_profit=new_take_profit if new_take_profit > 0 else None,
                            stop_loss=new_stop_loss if new_stop_loss > 0 else None,
                            check_interval=check_interval,
                            notification_enabled=notification_enabled
                        )

                        st.success(f"✅ 已成功将 {record['symbol']} 加入监测列表！")
                        st.balloons()

                        # 立即更新一次价格
                        from monitor_service import monitor_service
                        monitor_service.manual_update_stock(stock_id)

                        # 清理session state并跳转到监测页面
                        if 'add_to_monitor_id' in st.session_state:
                            del st.session_state.add_to_monitor_id
                        if 'viewing_record_id' in st.session_state:
                            del st.session_state.viewing_record_id
                        if 'show_history' in st.session_state:
                            del st.session_state.show_history

                        # 设置跳转到监测页面
                        st.session_state.show_monitor = True
                        st.session_state.monitor_jump_highlight = record['symbol']  # 标记要高亮显示的股票

                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ 加入监测失败: {str(e)}")
                else:
                    st.error("❌ 请输入有效的进场区间（最低价应小于最高价，且都大于0）")

            if cancel:
                if 'add_to_monitor_id' in st.session_state:
                    del st.session_state.add_to_monitor_id
                st.rerun()
    else:
        st.warning("⚠️ 无法从分析结果中提取关键数据")
        if st.button("❌ 取消"):
            if 'add_to_monitor_id' in st.session_state:
                del st.session_state.add_to_monitor_id
            st.rerun()

def display_record_detail(record_id):
    """显示单条记录的详细信息"""
    st.markdown("---")
    st.subheader("📋 详细分析记录")

    record = db.get_record_by_id(record_id)
    if not record:
        st.error("❌ 记录不存在")
        return

    # 基本信息
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("股票代码", record['symbol'])
    with col2:
        st.metric("股票名称", record['stock_name'])
    with col3:
        st.metric("分析时间", record['analysis_date'])

    # 股票基本信息
    st.subheader("📊 股票基本信息")
    stock_info = record['stock_info']
    if stock_info:
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            current_price = stock_info.get('current_price', 'N/A')
            st.metric("当前价格", f"{current_price}")

        with col2:
            change_percent = stock_info.get('change_percent', 'N/A')
            if isinstance(change_percent, (int, float)):
                st.metric("涨跌幅", f"{change_percent:.2f}%", f"{change_percent:.2f}%")
            else:
                st.metric("涨跌幅", f"{change_percent}")

        with col3:
            pe_ratio = stock_info.get('pe_ratio', 'N/A')
            st.metric("市盈率", f"{pe_ratio}")

        with col4:
            pb_ratio = stock_info.get('pb_ratio', 'N/A')
            st.metric("市净率", f"{pb_ratio}")

        with col5:
            market_cap = stock_info.get('market_cap', 'N/A')
            if isinstance(market_cap, (int, float)):
                market_cap_str = f"{market_cap/1e9:.2f}B" if market_cap > 1e9 else f"{market_cap/1e6:.2f}M"
                st.metric("市值", market_cap_str)
            else:
                st.metric("市值", f"{market_cap}")

    # 各分析师报告
    st.subheader("🤖 AI分析师团队报告")
    agents_results = record['agents_results']
    if agents_results:
        tab_names = []
        tab_contents = []

        for agent_key, agent_result in agents_results.items():
            agent_name = agent_result.get('agent_name', '未知分析师')
            tab_names.append(agent_name)
            tab_contents.append(agent_result)

        tabs = st.tabs(tab_names)

        for i, tab in enumerate(tabs):
            with tab:
                agent_result = tab_contents[i]

                st.markdown(f"""
                <div class="agent-card">
                    <h4>👨‍💼 {agent_result.get('agent_name', '未知')}</h4>
                    <p><strong>职责：</strong>{agent_result.get('agent_role', '未知')}</p>
                    <p><strong>关注领域：</strong>{', '.join(agent_result.get('focus_areas', []))}</p>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("**📄 分析报告:**")
                st.write(agent_result.get('analysis', '暂无分析'))

    # 团队讨论
    st.subheader("🤝 分析团队讨论")
    discussion_result = record['discussion_result']
    if discussion_result:
        st.markdown("""
        <div class="agent-card">
            <h4>💭 团队综合讨论</h4>
        </div>
        """, unsafe_allow_html=True)
        st.write(discussion_result)

    # 最终决策
    st.subheader("📋 最终投资决策")
    final_decision = record['final_decision']
    if final_decision:
        if isinstance(final_decision, dict) and "decision_text" not in final_decision:
            col1, col2 = st.columns([1, 2])

            with col1:
                rating = final_decision.get('rating', '未知')
                rating_color = {"买入": "🟢", "持有": "🟡", "卖出": "🔴"}.get(rating, "⚪")

                st.markdown(f"""
                <div class="decision-card">
                    <h3 style="text-align: center;">{rating_color} {rating}</h3>
                    <h4 style="text-align: center;">投资评级</h4>
                </div>
                """, unsafe_allow_html=True)

                confidence = final_decision.get('confidence_level', 'N/A')
                st.metric("信心度", f"{confidence}/10")

                target_price = final_decision.get('target_price', 'N/A')
                st.metric("目标价格", f"{target_price}")

                position_size = final_decision.get('position_size', 'N/A')
                st.metric("建议仓位", f"{position_size}")

            with col2:
                st.markdown("**🎯 操作建议:**")
                st.write(final_decision.get('operation_advice', '暂无建议'))

                st.markdown("**📍 关键位置:**")
                col2_1, col2_2 = st.columns(2)

                with col2_1:
                    st.write(f"**进场区间:** {final_decision.get('entry_range', 'N/A')}")
                    st.write(f"**止盈位:** {final_decision.get('take_profit', 'N/A')}")

                with col2_2:
                    st.write(f"**止损位:** {final_decision.get('stop_loss', 'N/A')}")
                    st.write(f"**持有周期:** {final_decision.get('holding_period', 'N/A')}")
        else:
            decision_text = final_decision.get('decision_text', str(final_decision))
            st.write(decision_text)

    # 加入监测功能
    st.markdown("---")
    st.subheader("🎯 操作")

    # 检查是否需要显示加入监测的对话框
    if 'add_to_monitor_id' in st.session_state and st.session_state.add_to_monitor_id == record_id:
        display_add_to_monitor_dialog(record)
    else:
        # 只有在不显示对话框时才显示按钮
        col1, col2 = st.columns([1, 3])

        with col1:
            if st.button("➕ 加入监测", type="primary", width='stretch'):
                st.session_state.add_to_monitor_id = record_id
                st.rerun()

    # 返回按钮
    st.markdown("---")
    if st.button("⬅️ 返回历史记录列表"):
        if 'viewing_record_id' in st.session_state:
            del st.session_state.viewing_record_id
        if 'add_to_monitor_id' in st.session_state:
            del st.session_state.add_to_monitor_id
        st.rerun()

def display_config_manager():
    """显示环境配置管理界面"""
    render_flash_messages("app_config")
    st.subheader("⚙️ 环境配置管理")

    st.markdown("""
    <div class="agent-card">
        <p>在这里可以配置系统的环境变量，包括API密钥、数据源配置、量化交易配置等。</p>
        <p><strong>注意：</strong>配置修改后需要重启应用才能生效。</p>
    </div>
    """, unsafe_allow_html=True)

    # 获取当前配置
    config_info = config_manager.get_config_info()

    # 创建标签页
    tab1, tab2, tab3, tab4 = st.tabs(["📝 基本配置", "📊 数据源配置", "🤖 量化交易配置", "📢 通知配置"])

    # 使用session_state保存临时配置
    if 'temp_config' not in st.session_state:
        st.session_state.temp_config = {key: info["value"] for key, info in config_info.items()}

    with tab1:
        st.markdown("### DeepSeek API配置")
        st.markdown("DeepSeek是系统的核心AI引擎，必须配置才能使用分析功能。")
        st.markdown("DeepSeek:https://api.deepseek.com/v1")
        st.markdown("硅基流动:https://api.siliconflow.cn/v1")
        st.markdown("火山引擎:https://ark.cn-beijing.volces.com/api/v3")
        st.markdown("阿里:https://dashscope.aliyuncs.com/compatible-mode/v1")

    # DeepSeek API Key
        api_key_info = config_info["DEEPSEEK_API_KEY"]
        current_api_key = st.session_state.temp_config.get("DEEPSEEK_API_KEY", "")

        new_api_key = st.text_input(
            f"🔑 {api_key_info['description']} {'*' if api_key_info['required'] else ''}",
            value=current_api_key,
            type="password",
            help="从 https://platform.deepseek.com 获取API密钥",
            key="input_deepseek_api_key"
        )
        st.session_state.temp_config["DEEPSEEK_API_KEY"] = new_api_key

        # 显示当前状态
        if new_api_key:
            masked_key = new_api_key[:8] + "*" * (len(new_api_key) - 12) + new_api_key[-4:] if len(new_api_key) > 12 else "***"
            st.success(f"✅ API密钥已设置: {masked_key}")
        else:
            st.warning("⚠️ 未设置API密钥，系统无法使用AI分析功能")

        st.markdown("---")

        # DeepSeek Base URL
        base_url_info = config_info["DEEPSEEK_BASE_URL"]
        current_base_url = st.session_state.temp_config.get("DEEPSEEK_BASE_URL", "")

        new_base_url = st.text_input(
            f"🌐 {base_url_info['description']}",
            value=current_base_url,
            help="一般无需修改，保持默认即可",
            key="input_deepseek_base_url"
        )
        st.session_state.temp_config["DEEPSEEK_BASE_URL"] = new_base_url

        st.markdown("---")

        # AI模型名称
        model_name_info = config_info["DEFAULT_MODEL_NAME"]
        current_model_name = st.session_state.temp_config.get("DEFAULT_MODEL_NAME", "deepseek-chat")

        new_model_name = st.text_input(
            f"🤖 {model_name_info['description']}",
            value=current_model_name,
            help="输入OpenAI兼容的模型名称，修改后重启生效",
            key="input_default_model_name"
        )
        st.session_state.temp_config["DEFAULT_MODEL_NAME"] = new_model_name

        if new_model_name:
            st.success(f"✅ 当前模型: **{new_model_name}**")
        else:
            st.warning("⚠️ 未设置模型名称，将使用默认值 deepseek-chat")

        st.markdown("""
        **常用模型名称参考：**
        - `deepseek-chat` — DeepSeek Chat（默认）
        - `deepseek-reasoner` — DeepSeek Reasoner（推理增强）
        - `qwen-plus` — 通义千问 Plus
        - `qwen-turbo` — 通义千问 Turbo
        - `gpt-4o` — OpenAI GPT-4o
        - `gpt-4o-mini` — OpenAI GPT-4o Mini
        
        > 💡 使用非 DeepSeek 模型时，请同时修改上方的 API地址 和 API密钥
        """)

        st.info("💡 如何获取DeepSeek API密钥？\n\n1. 访问 https://platform.deepseek.com\n2. 注册/登录账号\n3. 进入API密钥管理页面\n4. 创建新的API密钥\n5. 复制密钥并粘贴到上方输入框")

    with tab2:
        st.markdown("### Tushare数据接口（可选）")
        st.markdown("Tushare提供更丰富的A股财务数据，配置后可以获取更详细的财务分析。")

        tushare_info = config_info["TUSHARE_TOKEN"]
        current_tushare = st.session_state.temp_config.get("TUSHARE_TOKEN", "")

        new_tushare = st.text_input(
            f"🎫 {tushare_info['description']}",
            value=current_tushare,
            type="password",
            help="从 https://tushare.pro 获取Token",
            key="input_tushare_token"
        )
        st.session_state.temp_config["TUSHARE_TOKEN"] = new_tushare

        if new_tushare:
            st.success("✅ Tushare Token已设置")
        else:
            st.info("ℹ️ 未设置Tushare Token，系统将使用其他数据源")

        st.info("💡 如何获取Tushare Token？\n\n1. 访问 https://tushare.pro\n2. 注册账号\n3. 进入个人中心\n4. 获取Token\n5. 复制并粘贴到上方输入框")

    with tab3:
        st.markdown("### MiniQMT量化交易配置（可选）")
        st.markdown("配置后可以使用量化交易功能，自动执行交易策略。")

        # 启用开关
        miniqmt_enabled_info = config_info["MINIQMT_ENABLED"]
        current_enabled = st.session_state.temp_config.get("MINIQMT_ENABLED", "false") == "true"

        new_enabled = st.checkbox(
            "启用MiniQMT量化交易",
            value=current_enabled,
            help="开启后可以使用量化交易功能",
            key="input_miniqmt_enabled"
        )
        st.session_state.temp_config["MINIQMT_ENABLED"] = "true" if new_enabled else "false"

        # 其他配置
        col1, col2 = st.columns(2)

        with col1:
            account_id_info = config_info["MINIQMT_ACCOUNT_ID"]
            current_account_id = st.session_state.temp_config.get("MINIQMT_ACCOUNT_ID", "")

            new_account_id = st.text_input(
                f"🆔 {account_id_info['description']}",
                value=current_account_id,
                disabled=not new_enabled,
                key="input_miniqmt_account_id"
            )
            st.session_state.temp_config["MINIQMT_ACCOUNT_ID"] = new_account_id

            host_info = config_info["MINIQMT_HOST"]
            current_host = st.session_state.temp_config.get("MINIQMT_HOST", "")

            new_host = st.text_input(
                f"🖥️ {host_info['description']}",
                value=current_host,
                disabled=not new_enabled,
                key="input_miniqmt_host"
            )
            st.session_state.temp_config["MINIQMT_HOST"] = new_host

        with col2:
            port_info = config_info["MINIQMT_PORT"]
            current_port = st.session_state.temp_config.get("MINIQMT_PORT", "")

            new_port = st.text_input(
                f"🔌 {port_info['description']}",
                value=current_port,
                disabled=not new_enabled,
                key="input_miniqmt_port"
            )
            st.session_state.temp_config["MINIQMT_PORT"] = new_port

        if new_enabled:
            st.success("✅ MiniQMT已启用")
        else:
            st.info("ℹ️ MiniQMT未启用")

        st.warning("⚠️ 警告：量化交易涉及真实资金操作，请谨慎配置和使用！")

    with tab4:
        st.markdown("### 通知配置")
        st.markdown("配置邮件和Webhook通知，用于实时监测和智策定时分析的提醒。")

        # 创建两列布局
        col_email, col_webhook = st.columns(2)

        with col_email:
            st.markdown("#### 📧 邮件通知")

            # 邮件启用开关
            email_enabled_info = config_info.get("EMAIL_ENABLED", {"value": "false"})
            current_email_enabled = st.session_state.temp_config.get("EMAIL_ENABLED", "false") == "true"

            new_email_enabled = st.checkbox(
                "启用邮件通知",
                value=current_email_enabled,
                help="开启后可以接收邮件提醒",
                key="input_email_enabled"
            )
            st.session_state.temp_config["EMAIL_ENABLED"] = "true" if new_email_enabled else "false"

            # SMTP服务器
            smtp_server_info = config_info.get("SMTP_SERVER", {"description": "SMTP服务器地址", "value": ""})
            current_smtp_server = st.session_state.temp_config.get("SMTP_SERVER", "")

            new_smtp_server = st.text_input(
                f"📮 {smtp_server_info['description']}",
                value=current_smtp_server,
                disabled=not new_email_enabled,
                placeholder="smtp.qq.com",
                key="input_smtp_server"
            )
            st.session_state.temp_config["SMTP_SERVER"] = new_smtp_server

            # SMTP端口
            smtp_port_info = config_info.get("SMTP_PORT", {"description": "SMTP端口", "value": "587"})
            current_smtp_port = st.session_state.temp_config.get("SMTP_PORT", "587")

            new_smtp_port = st.text_input(
                f"🔌 {smtp_port_info['description']}",
                value=current_smtp_port,
                disabled=not new_email_enabled,
                placeholder="587 (TLS) 或 465 (SSL)",
                key="input_smtp_port"
            )
            st.session_state.temp_config["SMTP_PORT"] = new_smtp_port

            # 发件人邮箱
            email_from_info = config_info.get("EMAIL_FROM", {"description": "发件人邮箱", "value": ""})
            current_email_from = st.session_state.temp_config.get("EMAIL_FROM", "")

            new_email_from = st.text_input(
                f"📤 {email_from_info['description']}",
                value=current_email_from,
                disabled=not new_email_enabled,
                placeholder="your-email@qq.com",
                key="input_email_from"
            )
            st.session_state.temp_config["EMAIL_FROM"] = new_email_from

            # 邮箱授权码
            email_password_info = config_info.get("EMAIL_PASSWORD", {"description": "邮箱授权码", "value": ""})
            current_email_password = st.session_state.temp_config.get("EMAIL_PASSWORD", "")

            new_email_password = st.text_input(
                f"🔐 {email_password_info['description']}",
                value=current_email_password,
                type="password",
                disabled=not new_email_enabled,
                help="不是邮箱登录密码，而是SMTP授权码",
                key="input_email_password"
            )
            st.session_state.temp_config["EMAIL_PASSWORD"] = new_email_password

            # 收件人邮箱
            email_to_info = config_info.get("EMAIL_TO", {"description": "收件人邮箱", "value": ""})
            current_email_to = st.session_state.temp_config.get("EMAIL_TO", "")

            new_email_to = st.text_input(
                f"📥 {email_to_info['description']}",
                value=current_email_to,
                disabled=not new_email_enabled,
                placeholder="receiver@qq.com",
                key="input_email_to"
            )
            st.session_state.temp_config["EMAIL_TO"] = new_email_to

            if new_email_enabled and all([new_smtp_server, new_email_from, new_email_password, new_email_to]):
                st.success("✅ 邮件配置完整")
            elif new_email_enabled:
                st.warning("⚠️ 邮件配置不完整")
            else:
                st.info("ℹ️ 邮件通知未启用")

            st.caption("💡 QQ邮箱授权码获取：设置 → 账户 → POP3/IMAP/SMTP → 生成授权码")

        with col_webhook:
            st.markdown("#### 📱 Webhook通知")

            # Webhook启用开关
            webhook_enabled_info = config_info.get("WEBHOOK_ENABLED", {"value": "false"})
            current_webhook_enabled = st.session_state.temp_config.get("WEBHOOK_ENABLED", "false") == "true"

            new_webhook_enabled = st.checkbox(
                "启用Webhook通知",
                value=current_webhook_enabled,
                help="开启后可以发送到钉钉或飞书群",
                key="input_webhook_enabled"
            )
            st.session_state.temp_config["WEBHOOK_ENABLED"] = "true" if new_webhook_enabled else "false"

            # Webhook类型选择
            webhook_type_info = config_info.get("WEBHOOK_TYPE", {"description": "Webhook类型", "value": "dingtalk", "options": ["dingtalk", "feishu"]})
            current_webhook_type = st.session_state.temp_config.get("WEBHOOK_TYPE", "dingtalk")

            new_webhook_type = st.selectbox(
                f"📲 {webhook_type_info['description']}",
                options=webhook_type_info.get('options', ["dingtalk", "feishu"]),
                index=0 if current_webhook_type == "dingtalk" else 1,
                disabled=not new_webhook_enabled,
                key="input_webhook_type"
            )
            st.session_state.temp_config["WEBHOOK_TYPE"] = new_webhook_type

            # Webhook URL
            webhook_url_info = config_info.get("WEBHOOK_URL", {"description": "Webhook地址", "value": ""})
            current_webhook_url = st.session_state.temp_config.get("WEBHOOK_URL", "")

            new_webhook_url = st.text_input(
                f"🔗 {webhook_url_info['description']}",
                value=current_webhook_url,
                disabled=not new_webhook_enabled,
                placeholder="https://oapi.dingtalk.com/robot/send?access_token=...",
                key="input_webhook_url"
            )
            st.session_state.temp_config["WEBHOOK_URL"] = new_webhook_url

            # Webhook自定义关键词（钉钉安全验证）
            webhook_keyword_info = config_info.get("WEBHOOK_KEYWORD", {"description": "自定义关键词（钉钉安全验证）", "value": "aiagents通知"})
            current_webhook_keyword = st.session_state.temp_config.get("WEBHOOK_KEYWORD", "aiagents通知")

            new_webhook_keyword = st.text_input(
                f"🔑 {webhook_keyword_info['description']}",
                value=current_webhook_keyword,
                disabled=not new_webhook_enabled or new_webhook_type != "dingtalk",
                placeholder="aiagents通知",
                help="钉钉机器人安全设置中的自定义关键词，飞书不需要此设置",
                key="input_webhook_keyword"
            )
            st.session_state.temp_config["WEBHOOK_KEYWORD"] = new_webhook_keyword

            # 测试连通按钮
            if new_webhook_enabled and new_webhook_url:
                if st.button("🧪 测试Webhook连通", width='stretch', key="test_webhook_btn"):
                    with st.spinner("正在发送测试消息..."):
                        # 临时更新配置
                        temp_env_backup = {}
                        for key in ["WEBHOOK_ENABLED", "WEBHOOK_TYPE", "WEBHOOK_URL", "WEBHOOK_KEYWORD"]:
                            temp_env_backup[key] = os.getenv(key)
                            os.environ[key] = st.session_state.temp_config.get(key, "")

                        try:
                            # 创建临时通知服务实例
                            from notification_service import NotificationService
                            temp_notification_service = NotificationService()
                            success, message = temp_notification_service.send_test_webhook()

                            if success:
                                st.success(f"✅ {message}")
                            else:
                                st.error(f"❌ {message}")
                        except Exception as e:
                            st.error(f"❌ 测试失败: {str(e)}")
                        finally:
                            # 恢复环境变量
                            for key, value in temp_env_backup.items():
                                if value is not None:
                                    os.environ[key] = value
                                elif key in os.environ:
                                    del os.environ[key]

            if new_webhook_enabled and new_webhook_url:
                st.success(f"✅ Webhook配置完整 ({new_webhook_type})")
            elif new_webhook_enabled:
                st.warning("⚠️ 请配置Webhook URL")
            else:
                st.info("ℹ️ Webhook通知未启用")

            # 显示帮助信息
            if new_webhook_type == "dingtalk":
                st.caption("💡 钉钉机器人配置：\n1. 进入钉钉群 → 设置 → 智能群助手\n2. 添加机器人 → 自定义\n3. 复制Webhook地址\n4. 安全设置选择【自定义关键词】，填写上方的关键词")
            else:
                st.caption("💡 飞书机器人配置：\n1. 进入飞书群 → 设置 → 群机器人\n2. 添加机器人 → 自定义机器人\n3. 复制Webhook地址")

        st.markdown("---")
        st.info("💡 **使用说明**：\n- 可以同时启用邮件和Webhook通知\n- 实时监测和智策定时分析都会使用配置的通知方式\n- 配置后建议使用各功能中的测试按钮验证通知是否正常")

    # 操作按钮
    st.markdown("---")
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

    with col1:
        if st.button("💾 保存配置", type="primary", width='stretch'):
            # 验证配置
            is_valid, message = config_manager.validate_config(st.session_state.temp_config)

            if is_valid:
                # 保存配置
                if config_manager.write_env(st.session_state.temp_config):
                    queue_flash_message(st.session_state, "app_config", "success", "✅ 配置已保存到 .env 文件")
                    queue_flash_message(st.session_state, "app_config", "info", "ℹ️ 请重启应用使配置生效")

                    # 尝试重新加载配置
                    try:
                        config_manager.reload_config()
                        queue_flash_message(st.session_state, "app_config", "success", "✅ 配置已重新加载")
                    except Exception as e:
                        queue_flash_message(st.session_state, "app_config", "warning", f"⚠️ 配置重新加载失败: {e}")

                    st.rerun()
                else:
                    st.error("❌ 保存配置失败")
            else:
                st.error(f"❌ 配置验证失败: {message}")

    with col2:
        if st.button("🔄 重置", width='stretch'):
            # 重置为当前文件中的值
            st.session_state.temp_config = {key: info["value"] for key, info in config_info.items()}
            st.success("✅ 已重置为当前配置")
            st.rerun()

    with col3:
        if st.button("⬅️ 返回", width='stretch'):
            if 'show_config' in st.session_state:
                del st.session_state.show_config
            if 'temp_config' in st.session_state:
                del st.session_state.temp_config
            st.rerun()

    # 显示当前.env文件内容
    st.markdown("---")
    with st.expander("📄 查看当前 .env 文件内容"):
        current_config = config_manager.read_env()

        st.code(f"""# AI股票分析系统环境配置
# 由系统自动生成和管理

# ========== DeepSeek API配置 ==========
DEEPSEEK_API_KEY="{current_config.get('DEEPSEEK_API_KEY', '')}"
DEEPSEEK_BASE_URL="{current_config.get('DEEPSEEK_BASE_URL', '')}"

# ========== Tushare数据接口（可选）==========
TUSHARE_TOKEN="{current_config.get('TUSHARE_TOKEN', '')}"

# ========== MiniQMT量化交易配置（可选）==========
MINIQMT_ENABLED="{current_config.get('MINIQMT_ENABLED', 'false')}"
MINIQMT_ACCOUNT_ID="{current_config.get('MINIQMT_ACCOUNT_ID', '')}"
MINIQMT_HOST="{current_config.get('MINIQMT_HOST', '127.0.0.1')}"
MINIQMT_PORT="{current_config.get('MINIQMT_PORT', '58610')}"

# ========== 邮件通知配置（可选）==========
EMAIL_ENABLED="{current_config.get('EMAIL_ENABLED', 'false')}"
SMTP_SERVER="{current_config.get('SMTP_SERVER', '')}"
SMTP_PORT="{current_config.get('SMTP_PORT', '587')}"
EMAIL_FROM="{current_config.get('EMAIL_FROM', '')}"
EMAIL_PASSWORD="{current_config.get('EMAIL_PASSWORD', '')}"
EMAIL_TO="{current_config.get('EMAIL_TO', '')}"

# ========== Webhook通知配置（可选）==========
WEBHOOK_ENABLED="{current_config.get('WEBHOOK_ENABLED', 'false')}"
WEBHOOK_TYPE="{current_config.get('WEBHOOK_TYPE', 'dingtalk')}"
WEBHOOK_URL="{current_config.get('WEBHOOK_URL', '')}"
WEBHOOK_KEYWORD="{current_config.get('WEBHOOK_KEYWORD', 'aiagents通知')}"
""", language="bash")

def display_batch_analysis_results(results, period):
    """显示批量分析结果（对比视图）"""

    st.subheader("📊 批量分析结果对比")

    # 统计信息
    total = len(results)
    success_results = [r for r in results if r['success']]
    failed_results = [r for r in results if not r['success']]
    saved_count = sum(1 for r in results if r.get('saved_to_db', False))

    # 显示统计
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总数", total)
    with col2:
        st.metric("成功", len(success_results), delta=None, delta_color="normal")
    with col3:
        st.metric("失败", len(failed_results), delta=None, delta_color="inverse")
    with col4:
        st.metric("已保存", saved_count, delta=None, delta_color="normal")

    # 提示信息
    if saved_count > 0:
        st.info(f"💾 已有 {saved_count} 只股票的分析结果保存到历史记录，可在侧边栏点击「📖 历史记录」查看")

    st.markdown("---")

    # 失败的股票列表
    if failed_results:
        with st.expander(f"❌ 查看失败的 {len(failed_results)} 只股票", expanded=False):
            for result in failed_results:
                st.error(f"**{result['symbol']}**: {result.get('error', '未知错误')}")

    # 保存失败的股票列表
    save_failed_results = [r for r in success_results if not r.get('saved_to_db', False)]
    if save_failed_results:
        with st.expander(f"⚠️ 查看分析成功但保存失败的 {len(save_failed_results)} 只股票", expanded=False):
            for result in save_failed_results:
                db_error = result.get('db_error', '未知错误')
                st.warning(f"**{result['symbol']} - {result['stock_info'].get('name', 'N/A')}**: {db_error}")

    # 成功的股票分析结果
    if not success_results:
        st.warning("⚠️ 没有成功分析的股票")
        return

    # 创建对比视图选项
    view_mode = st.radio(
        "显示模式",
        ["对比表格", "详细卡片"],
        horizontal=True,
        help="对比表格：横向对比多只股票；详细卡片：逐个查看详细分析"
    )

    if view_mode == "对比表格":
        # 表格对比视图
        display_comparison_table(success_results)
    else:
        # 详细卡片视图
        display_detailed_cards(success_results, period)

def display_comparison_table(results):
    """显示对比表格"""
    import pandas as pd

    st.subheader("📋 股票对比表格")

    # 构建对比数据
    comparison_data = []
    for result in results:
        stock_info = result['stock_info']
        indicators = result.get('indicators', {})
        final_decision = result['final_decision']

        # 解析评级
        if isinstance(final_decision, dict):
            rating = final_decision.get('rating', 'N/A')
            confidence = final_decision.get('confidence_level', 'N/A')
            target_price = final_decision.get('target_price', 'N/A')
        else:
            rating = 'N/A'
            confidence = 'N/A'
            target_price = 'N/A'

        # 确保信心度为字符串类型，避免类型混合导致的序列化错误
        if isinstance(confidence, (int, float)):
            confidence = str(confidence)

        row = {
            '股票代码': stock_info.get('symbol', 'N/A'),
            '股票名称': stock_info.get('name', 'N/A'),
            '当前价格': stock_info.get('current_price', 'N/A'),
            '涨跌幅(%)': stock_info.get('change_percent', 'N/A'),
            '市盈率': stock_info.get('pe_ratio', 'N/A'),
            '市净率': stock_info.get('pb_ratio', 'N/A'),
            'RSI': indicators.get('rsi', 'N/A'),
            'MACD': indicators.get('macd', 'N/A'),
            '投资评级': rating,
            '信心度': confidence,
            '目标价格': target_price
        }
        comparison_data.append(row)

    # 创建DataFrame
    df = pd.DataFrame(comparison_data)

    # 应用样式
    # 显示表格（不使用样式，避免matplotlib导入问题）
    st.dataframe(
        df,
        width='stretch',
        height=400
    )

    # 添加评级说明
    st.caption("💡 投资评级说明：强烈买入 > 买入 > 持有 > 卖出 > 强烈卖出")

    # 添加筛选功能
    st.markdown("---")
    st.subheader("🔍 快速筛选")

    col1, col2 = st.columns(2)
    with col1:
        rating_filter = st.multiselect(
            "按评级筛选",
            options=df['投资评级'].unique().tolist(),
            default=df['投资评级'].unique().tolist()
        )

    with col2:
        # 按涨跌幅排序
        sort_by = st.selectbox(
            "排序方式",
            ["默认", "涨跌幅降序", "涨跌幅升序", "信心度降序", "RSI降序"]
        )

    # 应用筛选
    filtered_df = df[df['投资评级'].isin(rating_filter)]

    # 应用排序
    if sort_by == "涨跌幅降序":
        filtered_df = filtered_df.sort_values('涨跌幅(%)', ascending=False)
    elif sort_by == "涨跌幅升序":
        filtered_df = filtered_df.sort_values('涨跌幅(%)', ascending=True)
    elif sort_by == "信心度降序":
        filtered_df = filtered_df.sort_values('信心度', ascending=False)
    elif sort_by == "RSI降序":
        filtered_df = filtered_df.sort_values('RSI', ascending=False)

    if not filtered_df.empty:
        st.dataframe(filtered_df, width='stretch')
    else:
        st.info("没有符合条件的股票")

def display_detailed_cards(results, period):
    """显示详细卡片视图"""

    st.subheader("📇 详细分析卡片")

    # 选择要查看的股票
    stock_options = [f"{r['stock_info']['symbol']} - {r['stock_info']['name']}" for r in results]
    selected_stock = st.selectbox("选择股票", options=stock_options)

    # 找到对应的结果
    selected_index = stock_options.index(selected_stock)
    result = results[selected_index]

    # 显示详细分析
    stock_info = result['stock_info']
    indicators = result['indicators']
    agents_results = result['agents_results']
    discussion_result = result['discussion_result']
    final_decision = result['final_decision']

    # 获取股票数据用于显示图表
    try:
        stock_info_current, stock_data, _ = get_stock_data(stock_info['symbol'], period)

        # 显示股票基本信息
        display_stock_info(stock_info, indicators)

        # 显示股票图表
        if stock_data is not None:
            display_stock_chart(stock_data, stock_info)

        # 显示各分析师报告
        display_agents_analysis(agents_results)

        # 显示团队讨论
        display_team_discussion(discussion_result)

        # 显示最终决策
        display_final_decision(final_decision, stock_info, agents_results, discussion_result)

    except Exception as e:
        st.error(f"显示详细信息时出错: {str(e)}")

if __name__ == "__main__":
    main()
