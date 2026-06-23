"""
安全数字监督员 - AI Agent 安全监控面板
启动: streamlit run frontend.py
"""

import io, sys, os, re, time, json
import streamlit as st
import pandas as pd

# ---- 配置 ----
_cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
_cfg = json.load(open(_cfg_path, encoding="utf-8")) if os.path.exists(_cfg_path) else {}
_ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()

st.set_page_config(page_title="安全数字监督员", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")

# ---- 自定义主题（柔和暗色，不刺眼，所有颜色显式）----
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;700&display=swap');

/* 配色方案 (普通浅中性色系，柔和且保护视力，不跟随系统) */
:root {
    --bg: #f4f6fa;          /* 主背景 - 浅灰蓝，非常平缓舒适 */
    --sidebar: #eaedf4;     /* 侧边栏 - 略深灰蓝 */
    --card: #ffffff;        /* 卡片背景 - 纯白 */
    --border: #dbe1ec;      /* 边框线 - 低对比度浅灰 */
    --text: #2d3243;        /* 主文字 - 深蓝灰，降低黑白对比，更柔和 */
    --text-muted: #5f6679;  /* 次要文字 */
    --blue: #3b82f6;        /* 主色调/按钮蓝 - 经典柔和蓝 */
    --blue-hover: #2563eb;
    --green: #10b981;       /* 正常绿 */
    --green-bg: #e6f7f0;
    --red: #ef4444;         /* 隐患红 */
    --red-bg: #fee2e2;
    --yellow: #f59e0b;      /* 警告黄 */
    --yellow-bg: #fef3c7;
}

/* 全局覆盖，强制不跟随系统暗色模式 */
html, body, [data-testid="stAppViewContainer"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    color-scheme: light !important;
    overflow: hidden !important; /* 隐藏浏览器视口及外层容器滚动条，防止双滚动条 */
}

/* 仅在 Streamlit 实际的内容滚动容器上强制启用垂直滚动条轨道，锁定排版宽度，彻底杜绝闪烁和抖动 */
.main, [data-testid="stMain"] {
    overflow-y: scroll !important;
    overflow-x: hidden !important;
}

/* 侧边栏允许其内容超出时正常垂直滚动 */
section[data-testid="stSidebar"] {
    overflow-y: auto !important;
}

.stApp {
    background: var(--bg) !important;
}
.stApp > header { background: transparent !important; }
.block-container {
    padding: 0.5rem 1.2rem 0.3rem 1.2rem;
    max-width: 100%;
    color: var(--text);
}
#MainMenu, footer, header { display: none !important; }

/* 字体全局优化 */
* {
    font-family: 'Inter', sans-serif;
}

/* 侧边栏样式 */
section[data-testid="stSidebar"] {
    background: var(--sidebar) !important;
    border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] .block-container {
    padding-top: 0.6rem;
    color: var(--text);
}
section[data-testid="stSidebar"] label {
    color: var(--text-muted) !important;
    font-size: 12px !important;
    font-weight: 500 !important;
}
section[data-testid="stSidebar"] .stTextInput input {
    background: var(--card) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
}

/* Tabs 选项卡 */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: var(--sidebar);
    border-radius: 10px;
    padding: 4px;
    border: 1px solid var(--border);
}
.stTabs [data-baseweb="tab"] {
    color: var(--text-muted) !important;
    font-size: 13px !important;
    padding: 8px 20px !important;
    border-radius: 8px !important;
    background: transparent !important;
    transition: all 0.2s ease !important;
}
.stTabs [aria-selected="true"] {
    color: var(--text) !important;
    background: var(--card) !important;
    font-weight: 600 !important;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05) !important;
}

/* 按钮样式（上传 / 拍照 / 处理 / 下载） */
.stButton > button, .stDownloadButton > button {
    background: var(--blue) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 8px 16px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    min-height: 40px !important;
    transition: background-color 0.2s ease, box-shadow 0.2s ease !important;
    box-shadow: 0 2px 6px rgba(59, 130, 246, 0.15) !important;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    background: var(--blue-hover) !important;
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.25) !important;
}
.stButton > button:active, .stDownloadButton > button:active {
    box-shadow: 0 1px 3px rgba(59, 130, 246, 0.1) !important;
}
.stButton > button:disabled, .stDownloadButton > button:disabled {
    background: #e2e8f0 !important;
    color: #94a3b8 !important;
    box-shadow: none !important;
    cursor: not-allowed !important;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--blue) 0%, #4f46e5 100%) !important;
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, var(--blue-hover) 0%, #4338ca 100%) !important;
}

/* 上传区 (stFileUploader) */
[data-testid="stFileUploader"], [data-testid="stCameraInput"] { padding: 0 !important; margin: 0 !important; }
[data-testid="stFileUploader"] section, [data-testid="stCameraInput"] section {
    background: var(--card) !important;
    border: 2px dashed var(--border) !important;
    border-radius: 10px !important;
    padding: 16px !important;
    min-height: 80px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: all 0.25s ease !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.01) !important;
}
[data-testid="stFileUploader"] section:hover, [data-testid="stCameraInput"] section:hover {
    border-color: var(--blue) !important;
    background: #f8fafc !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.03) !important;
}
[data-testid="stFileUploader"] label, [data-testid="stCameraInput"] label {
    color: var(--text) !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    margin-bottom: 6px !important;
}
[data-testid="stFileUploader"] section svg, [data-testid="stCameraInput"] section svg {
    fill: var(--blue) !important;
}
[data-testid="stFileUploader"] section p, [data-testid="stCameraInput"] section p {
    color: var(--text-muted) !important;
    font-size: 12px !important;
}

/* 隐藏自带的相机图片预览 */
[data-testid="stCameraInput"] [data-testid="stImage"] { display: none !important; }
[data-testid="stHorizontalBlock"] { gap: 8px !important; }

/* 输入框 / 文本区域 / 选择框 */
.stTextInput input, .stTextArea textarea, .stSelectbox [data-baseweb="select"] {
    background: var(--card) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.02) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--blue) !important;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15) !important;
}

/* KPI 指标卡 */
.kpi {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 12px 14px !important;
    text-align: center !important;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.03) !important;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    border-top: 3px solid var(--blue) !important;
}
.kpi:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 16px rgba(0, 0, 0, 0.06) !important;
}
.kpi-val {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 22px !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
}
.kpi-lbl {
    font-size: 11px !important;
    color: var(--text-muted) !important;
    text-transform: uppercase !important;
    letter-spacing: 0.8px !important;
    margin-top: 4px !important;
}

/* 状态徽章 */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    text-align: center;
}
.badge-ok { background: var(--green-bg); color: var(--green) !important; border: 1px solid #a7f3d0; }
.badge-warn { background: var(--yellow-bg); color: var(--yellow) !important; border: 1px solid #fde68a; }
.badge-err { background: var(--red-bg); color: var(--red) !important; border: 1px solid #fecaca; }

/* 提示框 - 保留 Streamlit 浅色原生警示色，仅美化圆角和阴影 */
.stAlert {
    border-radius: 10px !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03) !important;
}
/* 防止全局文字颜色覆盖警示框内部的文字颜色 */
div[data-testid="stAlert"] .stMarkdown, 
div[data-testid="stAlert"] .stMarkdown p, 
div[data-testid="stAlert"] .stMarkdown span {
    color: inherit !important;
}
div[data-baseweb="notification"] {
    border-radius: 10px !important;
}

/* 护眼黑客风格日志面板 */
.hlog, .hlog * {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important;
}
.hlog {
    background: #090d16 !important; /* 更深的黑蓝背景，大幅提高对比度 */
    border: 1px solid #10b981 !important; /* 绿色边框 */
    border-radius: 10px !important;
    padding: 14px !important;
    color: #34d399 !important; /* 主文本：高亮经典绿 */
    line-height: 1.6 !important;
    overflow-y: auto !important;
    box-shadow: inset 0 2px 8px rgba(0,0,0,0.4), 0 4px 12px rgba(16, 185, 129, 0.08) !important;
    position: relative !important;
    margin-top: 28px !important; /* 往下移动，防止与上面的按钮或进度条重叠 */
    margin-bottom: 16px !important;
}
.hlog::after {
    content: " " !important;
    display: block !important;
    position: absolute !important;
    top: 0; left: 0; bottom: 0; right: 0 !important;
    background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.1) 50%) !important;
    z-index: 2 !important;
    background-size: 100% 2px !important;
    pointer-events: none !important;
}
.stMarkdown .hlog div {
    color: #34d399 !important; /* 默认未分类日志行：高亮经典绿 */
}
.stMarkdown .hlog div.lt {
    color: #10b981 !important; /* 头部标题：亮绿 */
    font-weight: 700 !important;
    border-bottom: 1px solid #1f2937 !important;
    padding-bottom: 6px !important;
    margin-bottom: 10px !important;
    font-size: 13px !important;
}
.stMarkdown .hlog div.lo { color: #a7f3d0 !important; } /* 工具输出：淡绿 */
.stMarkdown .hlog div.le { color: #f87171 !important; font-weight: bold !important; } /* 错误：红色高亮 */
.stMarkdown .hlog div.lk { color: #34d399 !important; font-weight: bold !important; } /* 完成/通过：经典绿 */
.stMarkdown .hlog div.lw { color: #fbbf24 !important; font-weight: bold !important; } /* 警告：黄色 */

/* 进度条 */
.stProgress { margin: 8px 0 !important; padding: 0 !important; }
.stProgress > div { height: 6px !important; border-radius: 3px !important; background: #e2e8f0 !important; overflow: hidden; }
.stProgress > div > div {
    background: linear-gradient(90deg, var(--blue) 0%, #6366f1 100%) !important;
    transition: width 0.3s ease-out !important;
}
.stSpinner { display: none !important; }

/* 图片 */
[data-testid="stImage"] img {
    border-radius: 8px;
    cursor: zoom-in;
    transition: all 0.25s ease;
}
[data-testid="stImage"] img:hover {
    opacity: 0.95;
    transform: scale(1.01);
}

/* 折叠面板 (st.expander) */
details {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 8px 12px !important;
    margin-bottom: 12px !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.01) !important;
}
details summary {
    color: var(--text) !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
}
details[open] {
    border-color: var(--blue) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.03) !important;
}

/* 数据表格 */
.stDataFrame { border-radius: 10px !important; overflow: hidden !important; }
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    background-color: var(--card) !important;
}

/* 文字及排版覆盖 */
.stMarkdown, .stMarkdown p, .stMarkdown div, .stMarkdown span, .stMarkdown strong {
    color: var(--text) !important;
}
h1, h2, h3, h4, h5, h6 {
    color: var(--text) !important;
    font-weight: 700 !important;
}
.stCaption { color: var(--text-muted) !important; }

/* 引导步骤条 */
.guide-box {
    background: #eff6ff;
    border-left: 4px solid var(--blue);
    border-radius: 0 10px 10px 0;
    padding: 12px 16px;
    margin-bottom: 12px;
    color: var(--text);
    font-size: 14px;
    box-shadow: 0 2px 6px rgba(59, 130, 246, 0.05);
    display: flex;
    align-items: center;
    gap: 10px;
}
.guide-badge {
    background: var(--blue);
    color: white !important;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
}

/* 空白提示页 */
.empty-state {
    text-align: center;
    padding: 40px 20px;
    background: var(--card);
    border-radius: 12px;
    border: 1px solid var(--border);
    box-shadow: 0 4px 12px rgba(0,0,0,0.02);
    margin-top: 16px;
    animation: fadeInUp 0.5s ease-out;
}
.empty-icon {
    font-size: 48px;
    margin-bottom: 14px;
    filter: drop-shadow(0 4px 6px rgba(0,0,0,0.05));
}
.empty-title {
    font-size: 16px;
    color: var(--text);
    font-weight: 600;
    margin-bottom: 8px;
}
.empty-desc {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: 12px;
}
.empty-action {
    font-size: 12px;
    color: var(--text-muted);
}

/* 对话框 / 确认弹窗 */
div[role="dialog"] {
    background: var(--card) !important;
    border-radius: 12px !important;
    border: 1px solid var(--border) !important;
    box-shadow: 0 10px 30px rgba(0,0,0,0.08) !important;
}
div[role="dialog"] p, div[role="dialog"] h1, div[role="dialog"] h2, div[role="dialog"] h3 {
    color: var(--text) !important;
}

/* 动效：上滑淡入 */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
</style>
""", unsafe_allow_html=True)

# ---- Session State ----
if "results" not in st.session_state: st.session_state.results = []
if "delete_id" not in st.session_state: st.session_state.delete_id = None
if "pending_files" not in st.session_state: st.session_state.pending_files = None
if "show_uploader" not in st.session_state: st.session_state.show_uploader = False
if "show_camera" not in st.session_state: st.session_state.show_camera = False
if "upload_done" not in st.session_state: st.session_state.upload_done = False


def kpi(label, value, color="var(--blue)"):
    return f'<div class="kpi"><div class="kpi-val" style="color:{color}">{value}</div><div class="kpi-lbl">{label}</div></div>'

def badge(text, level="ok"):
    return f'<span class="badge badge-{level}">{text}</span>'


# ---- 侧边栏 ----
with st.sidebar:
    st.markdown(f"**🛡️ 安全数字监督员** `v{_ver}`")
    st.caption("牡丹江中燃 HSE · AI Agent")
    st.markdown("---")

    # API 配置
    api_key = st.text_input("API Key", _cfg.get("api_key", ""), type="password")
    base_url = st.text_input("API URL", _cfg.get("base_url", ""))
    model_name = st.text_input("模型", _cfg.get("model_name", ""))

    # 设置面板
    st.markdown("---")
    with st.expander("⚙️ 通知设置", expanded=False):
        wechat_webhook = st.text_input("企业微信 Webhook", _cfg.get("wechat_webhook", ""), type="password", help="企业微信群机器人 Webhook 地址")
        dingtalk_webhook = st.text_input("钉钉 Webhook", _cfg.get("dingtalk_webhook", ""), type="password", help="钉钉群机器人 Webhook 地址")
        if st.button("💾 保存设置", use_container_width=True):
            _cfg["wechat_webhook"] = wechat_webhook
            _cfg["dingtalk_webhook"] = dingtalk_webhook
            with open(_cfg_path, "w", encoding="utf-8") as f:
                json.dump(_cfg, f, ensure_ascii=False, indent=2)
            st.success("已保存")

# ---- 主面板 ----
tab1, tab2 = st.tabs(["📷 处理作业票", "📊 AI 看板"])


# ==================== Tab 1 ====================
with tab1:
    # ---- API 配置检查 ----
    if not api_key:
        st.warning("⚠️ 请先在左侧边栏填写 API Key，否则无法处理。点击左上角 **>** 展开边栏。")

    # ---- 操作引导（根据当前状态动态显示）----
    step = 1
    if st.session_state.get("upload_done") and st.session_state.get("pending_files"):
        step = 2
    if st.session_state.get("run_processing"):
        step = 3

    guide = st.empty()
    if step == 1:
        guide.markdown("""
        <div class="guide-box">
            <span class="guide-badge">第 1 步</span> 选择下方 <b>📤 上传</b> 或 <b>📷 拍照</b> 提供作业票照片
        </div>
        """, unsafe_allow_html=True)
    elif step == 2:
        guide.markdown("""
        <div class="guide-box">
            <span class="guide-badge">第 2 步</span> 照片已就绪，点击 <b>⚙️ 处理</b> 开始 AI 分析
        </div>
        """, unsafe_allow_html=True)

    # ---- 三个按钮：上传 / 拍照 / 处理 ----
    c1, c2, c3 = st.columns(3)
    with c1:
        show_upload = st.button("📤 上传", use_container_width=True)
    with c2:
        show_cam = st.button("📷 拍照", use_container_width=True)
    with c3:
        can_process = st.session_state.get("upload_done") and st.session_state.get("pending_files")
        run_clicked = st.button("⚙️ 处理", type="primary", use_container_width=True, disabled=not can_process)

    # 点击按钮切换模式
    if show_upload:
        st.session_state.show_uploader = True
        st.session_state.show_camera = False
        st.session_state.upload_done = False
        st.session_state.pending_files = None
    if show_cam:
        st.session_state.show_camera = True
        st.session_state.show_uploader = False
        st.session_state.upload_done = False
        st.session_state.pending_files = None

    # ---- 文件选择 ----
    if st.session_state.get("show_uploader"):
        picked = st.file_uploader("选择图片", type=["jpg","jpeg","png","bmp"], accept_multiple_files=False, label_visibility="collapsed", key="fu_main")
        if picked and not st.session_state.get("upload_done"):
            # 模拟上传进度条
            st.session_state.pending_files = [picked]
            prog_ph = st.empty()
            status_ph = st.empty()
            for pct in range(0, 101, 5):
                prog_ph.progress(pct)
                status_ph.caption(f"📤 上传中... {picked.name} — {pct}%")
                time.sleep(0.05)
            prog_ph.empty()
            status_ph.success(f"✅ 上传完成 — {picked.name}（{picked.size/1024:.0f} KB）")
            st.session_state.upload_done = True
            st.rerun()
        elif picked and st.session_state.get("upload_done"):
            st.success(f"✅ {picked.name}（{picked.size/1024:.0f} KB）")

    # ---- 拍照 ----
    if st.session_state.get("show_camera"):
        camera_photo = st.camera_input("拍照上传", label_visibility="collapsed", key="cam_main")
        if camera_photo and not st.session_state.get("upload_done"):
            st.session_state.pending_files = [camera_photo]
            prog_ph = st.empty()
            status_ph = st.empty()
            for pct in range(0, 101, 5):
                prog_ph.progress(pct)
                status_ph.caption(f"📤 上传中... {camera_photo.name} — {pct}%")
                time.sleep(0.05)
            prog_ph.empty()
            status_ph.success(f"✅ 上传完成 — {camera_photo.name}（{camera_photo.size/1024:.0f} KB）")
            st.session_state.upload_done = True
            st.rerun()
        elif camera_photo and st.session_state.get("upload_done"):
            st.success(f"📷 {camera_photo.name}（{camera_photo.size/1024:.0f} KB）")

    # 无文件 + 有历史结果：显示上次结果
    # 合并最终文件
    final_files = st.session_state.get("pending_files") or []

    if not final_files and not run_clicked:
        if st.session_state.results:
            st.markdown("**上次处理结果**")
            for item in st.session_state.results:
                d = item["data"]
                c1, c2, c3, c4, c5 = st.columns(5)
                with c1: st.markdown(kpi("票号", d.ticket_id), unsafe_allow_html=True)
                with c2: st.markdown(kpi("状态", f"{len(d.issues)}项" if d.has_abnormal else "正常", "#ef4444" if d.has_abnormal else "#10b981"), unsafe_allow_html=True)
                with c3: st.markdown(kpi("措施", f"{len(d.safety_measures)}"), unsafe_allow_html=True)
                with c4:
                    rl = d.risk_level or "-"
                    rc = {"重大":"#ef4444","较大":"#f59e0b","一般":"#f59e0b","低风险":"#10b981"}.get(rl, "#3b82f6")
                    st.markdown(kpi("风险", rl, rc), unsafe_allow_html=True)
                with c5: st.markdown(kpi("浓度", ", ".join(f"{v}%" for v in d.gas_concentration) or "无"), unsafe_allow_html=True)
                if d.approval_opinion:
                    ic = {"重大":"🔴","较大":"🟡","一般":"🟡","低风险":"🟢"}.get(d.risk_level or "", "")
                    (st.warning if d.has_abnormal else st.success)(f"{ic} {d.approval_opinion}")
        else:
            st.markdown("""
            <div class="empty-state">
                <div class="empty-icon">🛡️</div>
                <div class="empty-title">上传作业票照片，AI 自动完成全部分析</div>
                <div class="empty-desc">支持：动火作业票 · 带气作业票 · 临时用电作业票</div>
                <div class="empty-action">点击上方 <b>📤 上传</b> 选择照片，或 <b>📷 拍照</b> 直接拍摄</div>
            </div>
            """, unsafe_allow_html=True)

    # 有文件：预览缩略图
    if final_files and not run_clicked and not st.session_state.get("run_processing"):
        thumbs = st.columns(min(len(final_files) + 1, 6))
        for i, f in enumerate(final_files[:5]):
            with thumbs[i]: st.image(f, width=100)
        with thumbs[min(len(final_files), 5)]:
            st.markdown(f"<div style='text-align:center;padding-top:35px;color:#57606a;font-size:12px'>{len(final_files)}张</div>", unsafe_allow_html=True)

    # 开始处理
    if run_clicked and final_files:
        st.session_state.run_processing = True
        st.rerun()

    if st.session_state.get("run_processing") and final_files:
        st.session_state.run_processing = False

        from agent_core import SecurityAgent, LLMBrain
        brain = LLMBrain(api_key=api_key, base_url=base_url, model_name=model_name)
        agent = SecurityAgent(brain=brain)
        st.session_state.results = []

        # ---- 上传保存进度 ----
        upload_status = st.empty()
        upload_progress = st.progress(0)
        saved_paths = []
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        for i, f in enumerate(final_files):
            pct = int((i / len(final_files)) * 100)
            upload_progress.progress(pct)
            upload_status.caption(f"📤 保存中... {f.name} ({i+1}/{len(final_files)})")
            suffix = os.path.splitext(f.name)[1] or ".jpg"
            save_path = os.path.join(upload_dir, f"{int(time.time())}_{i}{suffix}")
            with open(save_path, "wb") as fp:
                fp.write(f.getvalue())
            saved_paths.append(save_path)
            time.sleep(0.1)  # 让进度条可见

        upload_progress.progress(100)
        upload_status.caption(f"✅ {len(saved_paths)} 张图片已保存，开始 Agent 处理...")
        time.sleep(0.3)
        upload_progress.empty()
        upload_status.empty()

        # ---- 逐张处理 ----
        for idx, uploaded in enumerate(final_files):
            save_path = saved_paths[idx]

            # 分栏：左边结果，右边日志
            col_r, col_l = st.columns([3, 2])

            # 左栏：进度条 + 预览图（处理完自动收起）
            with col_r:
                status_text = st.empty()
                progress = st.progress(0)
                img_placeholder = st.empty()
                status_text.caption(f"[{idx+1}/{len(final_files)}] {uploaded.name} — 准备中...")
                img_placeholder.image(save_path, caption=uploaded.name, use_container_width=True)

            # 右栏：日志面板
            with col_l:
                pass  # 日志由 log_ph 占位渲染

            log_ph = col_l.empty()
            log_buf = []

            def hlog(line, _save_path=save_path, _name=uploaded.name):
                log_buf.append(line)
                import html as _h
                parts = []
                for l in log_buf[-30:]:
                    c = ""
                    if "Tool" in l: c = "lo"
                    elif "FAIL" in l or "出错" in l: c = "le"
                    elif "OK" in l or "通过" in l or "完成" in l: c = "lk"
                    elif "重试" in l or "未通过" in l: c = "lw"
                    parts.append(f'<div class="{c}">{_h.escape(l)}</div>')
                log_ph.markdown(
                    f'<div class="hlog">'
                    f'<div class="lt">📄 {_h.escape(_name)} | 🤖 AGENT THINKING...</div>'
                    f'{"".join(parts)}</div>',
                    unsafe_allow_html=True)

            hlog(f">>> 收到任务: {uploaded.name}")

            _orig = sys.stdout
            result = {"ocr": None, "data": None}
            _sp = {"Plan":10,"Perceive":25,"Reason":50,"Reflect":70,"Act":85,"Report":98}
            _sc = {"Plan":"规划","Perceive":"感知","Reason":"推理","Reflect":"反思","Act":"执行","Report":"总结"}

            class Cap(io.TextIOBase):
                def write(self, s):
                    s = s.strip()
                    if s:
                        hlog(s)
                        for k, p in _sp.items():
                            if f"Agent {k}" in s:
                                progress.progress(p)
                                status_text.caption(f"[{idx+1}/{len(final_files)}] {_sc[k]}...")
                    return len(s) if s else 0
                def flush(self): pass

            sys.stdout = Cap()
            try:
                ocr_text, structured = agent.run(save_path)
                result["ocr"], result["data"] = ocr_text, structured
            except Exception as e:
                hlog(f"❌ {e}")
            finally:
                sys.stdout = _orig

            progress.progress(100)
            status_text.caption(f"[{idx+1}/{len(final_files)}] ✅ 完成")
            # 预览图收进折叠面板，需要时可展开
            with img_placeholder:
                with st.expander("🖼️ 查看原图", expanded=False):
                    st.image(save_path, caption=uploaded.name, use_container_width=True)

            # 左栏：结果展示
            with col_r:
                if result["data"]:
                    d = result["data"]
                    st.session_state.results.append(result)

                    # KPI 行
                    c1, c2, c3, c4, c5 = st.columns(5)
                    with c1: st.markdown(kpi("票号", d.ticket_id), unsafe_allow_html=True)
                    with c2: st.markdown(kpi("状态", f"{len(d.issues)}项" if d.has_abnormal else "正常", "#cf222e" if d.has_abnormal else "#116329"), unsafe_allow_html=True)
                    with c3: st.markdown(kpi("措施", f"{len(d.safety_measures)}"), unsafe_allow_html=True)
                    with c4:
                        rl = d.risk_level or "-"
                        rc = {"重大":"#cf222e","较大":"#9a6700","一般":"#9a6700","低风险":"#116329"}.get(rl, "#0969da")
                        st.markdown(kpi("风险", rl, rc), unsafe_allow_html=True)
                    with c5: st.markdown(kpi("浓度", ", ".join(f"{v}%" for v in d.gas_concentration) or "无"), unsafe_allow_html=True)

                    # 审批建议
                    if d.approval_opinion:
                        ic = {"重大":"🔴","较大":"🟡","一般":"🟡","低风险":"🟢"}.get(d.risk_level or "", "")
                        (st.warning if d.has_abnormal else st.success)(f"{ic} {d.approval_opinion}")

                    # 通知推送
                    nc1, nc2 = st.columns(2)
                    with nc1:
                        dt_url = _cfg.get("dingtalk_webhook", "")
                        if not dt_url:
                            st.button("📱 发送钉钉", key=f"dt_{idx}", use_container_width=True, disabled=True, help="请在侧边栏通知设置中配置钉钉 Webhook")
                            st.caption("⚠️ 未配置钉钉 Webhook，请在左侧边栏设置")
                        elif st.button("📱 发送钉钉", key=f"dt_{idx}", use_container_width=True):
                            import requests as _req
                            msg = f"【安全数字监督员】\n票号: {d.ticket_id}\n场站: {d.station_name}\n状态: {'有隐患' if d.has_abnormal else '正常'}\n风险: {d.risk_level or '-'}\n审批: {d.approval_opinion or '-'}"
                            try:
                                _resp = _req.post(dt_url, json={"msgtype": "text", "text": {"content": msg}}, timeout=10)
                                if _resp.status_code == 200:
                                    st.success("✅ 钉钉发送成功")
                                else:
                                    st.error(f"发送失败: {_resp.status_code}")
                            except Exception as e:
                                st.error(f"发送失败: {e}")
                    with nc2:
                        wx_url = _cfg.get("wechat_webhook", "")
                        if not wx_url:
                            st.button("💬 发送微信", key=f"wx_{idx}", use_container_width=True, disabled=True, help="请在侧边栏通知设置中配置微信 Webhook")
                            st.caption("⚠️ 未配置微信 Webhook，请在左侧边栏设置")
                        elif st.button("💬 发送微信", key=f"wx_{idx}", use_container_width=True):
                            import requests as _req
                            msg = f"**【安全数字监督员】**\n> 票号: {d.ticket_id}\n> 场站: {d.station_name}\n> 状态: {'有隐患' if d.has_abnormal else '正常'}\n> 风险: {d.risk_level or '-'}\n> 审批: {d.approval_opinion or '-'}"
                            try:
                                _resp = _req.post(wx_url, json={"msgtype": "markdown", "markdown": {"content": msg}}, timeout=10)
                                if _resp.status_code == 200:
                                    st.success("✅ 微信发送成功")
                                else:
                                    st.error(f"发送失败: {_resp.status_code}")
                            except Exception as e:
                                st.error(f"发送失败: {e}")

                    # OCR + 隐患（折叠）
                    if result["ocr"]:
                        with st.expander("📝 OCR 识别原文"):
                            ocr_rows = []
                            for line in result["ocr"].strip().split("\n"):
                                line = line.strip()
                                if not line: continue
                                if "：" in line:
                                    p = line.split("：", 1); ocr_rows.append({"字段": p[0].strip(), "值": p[1].strip()})
                                elif ":" in line and line.index(":") > 0:
                                    p = line.split(":", 1); ocr_rows.append({"字段": p[0].strip(), "值": p[1].strip()})
                                else:
                                    ocr_rows.append({"字段": "", "值": line})
                            if ocr_rows:
                                st.dataframe(pd.DataFrame(ocr_rows), use_container_width=True, height=min(len(ocr_rows)*28+30, 350))

                    if d.issues:
                        with st.expander(f"⚠️ 隐患明细 ({len(d.issues)})", expanded=True):
                            # 未落实的安全措施
                            unimpl = [m for m in d.safety_measures if not m.implemented]
                            if unimpl:
                                st.markdown("**安全措施未落实：**")
                                for m in unimpl:
                                    st.markdown(f"  🔴 第{m.measure_id}项 `{m.description}` — 标记为**未落实×**")
                            # 浓度异常
                            conc_high = [(i, v) for i, v in enumerate(d.gas_concentration) if v > 0]
                            if conc_high:
                                st.markdown("**浓度异常：**")
                                for i, v in conc_high:
                                    st.markdown(f"  🟡 第{i+1}次检测 `{v}%` — 超过0%阈值")
                            # 其他隐患
                            for issue in d.issues:
                                reason = issue.raw_text or "OCR识别为异常标记"
                                st.markdown(f"  ⚠️ **{issue.item_name}** — {reason}")

        # 批量汇总
        if len(st.session_state.results) > 1:
            abn = sum(1 for r in st.session_state.results if r["data"].has_abnormal)
            st.markdown(f"**📊 汇总** {len(st.session_state.results)}张 {badge('正常'+str(len(st.session_state.results)-abn), 'ok')} {badge('隐患'+str(abn), 'err' if abn else 'ok')}", unsafe_allow_html=True)
            rows = [{"票号": r["data"].ticket_id, "场站": r["data"].station_name, "状态": "有隐患" if r["data"].has_abnormal else "正常", "风险": r["data"].risk_level or "-"} for r in st.session_state.results]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=min(len(rows)*28+30, 200))


# ==================== Tab 2: AI 看板 ====================
with tab2:
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
    _del_pwd = _cfg.get("delete_password", "123")

    if not os.path.exists(db_path):
        st.caption("📭 暂无数据，处理作业票后自动保存。")
    else:
        conn = sqlite3.connect(db_path)
        try:
            rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,approval_opinion,risk_level,created_at,image_path FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()
        except:
            rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,'','',created_at,'' FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()

        total = len(rows_db)
        abn_cnt = sum(1 for r in rows_db if r[5])

        # KPI 行
        k1, k2, k3, k4 = st.columns(4)
        with k1: st.markdown(kpi("总票数", total), unsafe_allow_html=True)
        with k2: st.markdown(kpi("有隐患", abn_cnt, "#ef4444" if abn_cnt else "#10b981"), unsafe_allow_html=True)
        with k3: st.markdown(kpi("正常", total - abn_cnt, "#10b981"), unsafe_allow_html=True)
        with k4: st.markdown(kpi("隐患率", f"{abn_cnt/total*100:.0f}%" if total else "0%"), unsafe_allow_html=True)

        # 高频隐患
        issue_counter = {}
        try:
            for (ij,) in conn.execute("SELECT issues_json FROM hse_fire_work_tickets WHERE has_abnormal=1").fetchall():
                if ij:
                    for item in json.loads(ij):
                        n = item.get("item_name", "未知"); issue_counter[n] = issue_counter.get(n, 0) + 1
        except: pass
        conn.close()

        if issue_counter:
            top5 = sorted(issue_counter.items(), key=lambda x: -x[1])[:5]
            cols = st.columns(len(top5))
            for i, (name, count) in enumerate(top5):
                with cols[i]: st.markdown(kpi(name, f"{count}次", "#ef4444"), unsafe_allow_html=True)

        # 删除弹窗
        if st.session_state.delete_id:
            @st.dialog("🗑️ 确认删除", width="small")
            def confirm_delete():
                st.warning(f"删除 **#{st.session_state.delete_id}**？")
                pwd = st.text_input("密码", type="password")
                fc1, fc2 = st.columns(2)
                with fc1:
                    if st.button("✅ 确认", type="primary", use_container_width=True):
                        if pwd == _del_pwd:
                            c2 = sqlite3.connect(db_path)
                            c2.execute("DELETE FROM hse_fire_work_tickets WHERE id=?", (st.session_state.delete_id,))
                            c2.commit(); c2.close()
                            st.session_state.delete_id = None; st.rerun()
                        else: st.error("密码错误")
                with fc2:
                    if st.button("❌ 取消", use_container_width=True):
                        st.session_state.delete_id = None; st.rerun()
            confirm_delete()

        # 搜索框（回车或点按钮触发）
        with st.form("search_form", clear_on_submit=False):
            sf1, sf2 = st.columns([5, 1])
            with sf1:
                search = st.text_input("🔍 搜索票号", placeholder="输入票号模糊查询...", label_visibility="collapsed")
            with sf2:
                st.form_submit_button("🔍 搜索", use_container_width=True)

        # 记录列表（搜索过滤）
        for row in rows_db:
            rid, ticket, station, worker, date, abnormal, opinion, risk, created, img_path = row
            if search and search.lower() not in (ticket or "").lower():
                continue
            icon = "🚨" if abnormal else "✅"
            badge_md = f" | :{'red' if risk=='重大' else ('orange' if risk in ['较大','一般'] else 'green')}[{risk}]" if risk else ""

            cm, cd = st.columns([9, 1])
            with cm:
                with st.expander(f"{icon} #{rid} | {ticket} | {station} | {date}{badge_md}", expanded=False):
                    ca, cb = st.columns(2)
                    with ca: st.markdown(f"**票号** {ticket}  \n**场站** {station}  \n**动火人** {worker}  \n**日期** {date}")
                    with cb:
                        st.markdown(f"**状态** {'🔴 有隐患' if abnormal else '🟢 正常'}")
                        if risk: st.markdown(f"**风险** {risk}")
                        st.caption(f"处理: {created}")
                        if opinion: st.caption(f"审批: {opinion}")
                    # 查看原图 + 下载按钮
                    if img_path and os.path.exists(img_path):
                        dc1, dc2 = st.columns(2)
                        with dc1:
                            if st.button("🖼️ 查看原图", key=f"img_{rid}", use_container_width=True):
                                @st.dialog("原图", width="large")
                                def show_orig_img(_path=img_path, _name=ticket):
                                    st.image(_path, caption=_name, use_container_width=True)
                                show_orig_img()
                        with dc2:
                            ext = os.path.splitext(img_path)[1] or ".png"
                            dl_name = f"{ticket or f'作业票_{rid}'}{ext}"
                            with open(img_path, "rb") as f:
                                img_bytes = f.read()
                            st.download_button("⬇️ 下载原图", data=img_bytes, file_name=dl_name, mime="image/png", key=f"dl_{rid}", use_container_width=True)
                    else:
                        st.caption("原图不可用")
            with cd:
                st.markdown("<div style='padding-top:18px'></div>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{rid}", help=f"删除 #{rid}"):
                    st.session_state.delete_id = rid; st.rerun()
