"""自定义 CSS 主题 — 中国燃气 · 白底科技风"""

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&family=Rajdhani:wght@500;600;700&display=swap');

/* ============== 中国燃气 · 白底科技风 ============== */
:root {
    --bg: #F5F6FA;
    --sidebar: #ECEEF5;
    --card: rgba(255, 255, 255, 0.72);
    --card-solid: #FFFFFF;
    --card-hover: #FFFFFF;
    --border: #E2E5EE;
    --border-strong: rgba(0, 82, 204, 0.18);
    --text: #1C2230;
    --text-muted: #697386;

    --crimson: #FF1E27;
    --crimson-text: #D6131C;
    --crimson-glow: rgba(255, 30, 39, 0.22);
    --blue: #0052CC;
    --blue-bright: #0066FF;
    --blue-glow: rgba(0, 82, 204, 0.22);

    --green: #059669;
    --green-bg: rgba(5, 150, 105, 0.10);
    --red: #D6131C;
    --red-bg: rgba(255, 30, 39, 0.08);
    --yellow: #D97706;
    --yellow-bg: rgba(217, 119, 6, 0.10);

    --glass-bg: rgba(255, 255, 255, 0.6);
    --glass-border: rgba(0, 82, 204, 0.10);
    --glass-blur: 14px;
    --glass-shadow: 0 6px 24px rgba(15, 23, 42, 0.06);
    --neon-red-shadow: 0 0 12px rgba(255, 30, 39, 0.15), 0 0 24px rgba(255, 30, 39, 0.06);
    --neon-blue-shadow: 0 0 12px rgba(0, 82, 204, 0.18), 0 0 24px rgba(0, 82, 204, 0.06);
}

/* ============== 全局背景：白底 + 微网格 + 色斑 ============== */
html, body, [data-testid="stAppViewContainer"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    color-scheme: light !important;
}
[data-testid="stAppViewContainer"] {
    background-image:
        linear-gradient(rgba(15,23,42,0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(15,23,42,0.018) 1px, transparent 1px),
        radial-gradient(ellipse at 10% -10%, rgba(255,30,39,0.04), transparent 38%),
        radial-gradient(ellipse at 92% 105%, rgba(0,82,204,0.05), transparent 42%) !important;
    background-size: 52px 52px, 52px 52px, 100% 100%, 100% 100% !important;
    background-attachment: fixed !important;
}
.main, [data-testid="stMain"] {
    overflow-y: auto !important;
    overflow-x: hidden !important;
}
section[data-testid="stSidebar"] {
    overflow-y: auto !important;
}
.stApp { background: transparent !important; }
.stApp > header { background: transparent !important; }
.block-container {
    padding: 0.6rem 1.4rem 0.4rem 1.4rem;
    max-width: 100%;
    color: var(--text);
}

/* 隐藏原生 chrome + Streamlit 原生菜单与页脚 */
#MainMenu, footer { display: none !important; }

/* 允许 toolbar 显示，以保证侧边栏展开按钮可见 */
header [data-testid="stToolbar"] {
    display: flex !important;
    background: transparent !important;
    pointer-events: none !important; /* 避免遮挡页面点击 */
}
/* 隐藏除展开按钮以外的工具栏项 (如开发者选项) */
header [data-testid="stToolbar"] button:not([data-testid="stExpandSidebarButton"]) {
    display: none !important;
}

/* ============== 侧边栏折叠/展开按钮 ============== */
/* 仅对侧边栏内的收起按钮做轻微美化，不影响折叠状态下的展开按钮 */
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button {
    border-radius: 50% !important;
    transition: opacity 0.2s ease !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button:hover {
    opacity: 0.7 !important;
}

/* 折叠态下，展开按钮（Streamlit 1.58 中为 [data-testid="stExpandSidebarButton"]）完全保持悬浮可见 */
[data-testid="stExpandSidebarButton"] {
    /* 脱离文档流，始终悬浮在页面左上角 */
    position: fixed !important;
    top: 12px !important;
    left: 8px !important;
    z-index: 9999999 !important;
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important; /* 恢复可点击 */
    /* 毛玻璃外观 */
    background: var(--glass-bg) !important;
    backdrop-filter: blur(var(--glass-blur)) !important;
    -webkit-backdrop-filter: blur(var(--glass-blur)) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 8px !important;
    box-shadow: var(--glass-shadow) !important;
    padding: 2px !important;
    transition: box-shadow 0.2s ease, border-color 0.2s ease !important;
}
[data-testid="stExpandSidebarButton"]:hover {
    box-shadow: var(--glass-shadow), var(--neon-blue-shadow) !important;
    border-color: var(--border-strong) !important;
}

/* ============== 侧边栏折叠时保留 20px 宽度 ============== */
/* Streamlit 折叠后 sidebar 宽度变为 0，强制保留 20px 作为展开触发区 */
[data-testid="stSidebar"][aria-expanded="false"] {
    min-width: 20px !important;
    width: 20px !important;
    max-width: 20px !important;
    overflow: visible !important;
}
/* 主内容区对应收缩，避免与 20px 条带重叠 */
[data-testid="stSidebar"][aria-expanded="false"] ~ [data-testid="stMain"] {
    margin-left: 20px !important;
}

/* z-index 层级修复 */
[data-testid="stMain"] { z-index: 1 !important; }
header { z-index: 999999 !important; background: transparent !important; }

/* 顶部霓虹光带 */
[data-testid="stAppViewContainer"]::before {
    content: "" !important;
    position: fixed !important;
    top: 0; left: 0; right: 0; height: 3px !important;
    background: linear-gradient(90deg,
        var(--crimson) 0%, var(--crimson) 30%,
        var(--blue) 60%, var(--blue-bright) 100%) !important;
    box-shadow: 0 0 10px var(--crimson-glow), 0 0 18px var(--blue-glow) !important;
    z-index: 1000000 !important;
    pointer-events: none !important;
}

section[data-testid="stSidebar"] {
    overflow-y: auto !important;
    transition: width 0.25s ease, min-width 0.25s ease, max-width 0.25s ease,
                padding 0.25s ease, margin 0.25s ease !important;
    overflow-x: hidden !important;
}

* { font-family: 'Inter', sans-serif; }

/* ============== 侧边栏 ============== */
section[data-testid="stSidebar"] {
    background: var(--sidebar) !important;
    border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] .block-container {
    padding-top: 1.5rem !important; /* 给顶部的折叠按钮预留点呼吸空间 */
    color: var(--text);
}
section[data-testid="stSidebar"] label {
    color: var(--text-muted) !important;
    font-size: 12px !important;
    font-weight: 500 !important;
}
section[data-testid="stSidebar"] .stTextInput input {
    background: var(--card-solid) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] .stTextInput input:focus {
    border-color: var(--blue) !important;
    box-shadow: 0 0 0 3px var(--blue-glow) !important;
}
section[data-testid="stSidebar"] hr { border-color: var(--border) !important; }

/* ============== 主标题 Hero 横幅（毛玻璃） ============== */
.hero-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--glass-border);
    border-radius: 16px;
    padding: 18px 24px;
    margin-bottom: 14px;
    box-shadow: var(--glass-shadow);
    position: relative;
    overflow: hidden;
}
.hero-banner::before {
    content: "";
    position: absolute; top: 0; left: 0; bottom: 0; width: 4px;
    background: linear-gradient(180deg, var(--crimson), var(--blue));
    box-shadow: 2px 0 10px var(--crimson-glow), 2px 0 20px var(--blue-glow);
}
.hero-left { display: flex; align-items: center; gap: 14px; z-index: 1; }
.hero-icon {
    font-size: 30px;
    filter: drop-shadow(0 2px 6px var(--blue-glow));
}
.hero-title {
    font-family: 'Rajdhani', 'Inter', sans-serif;
    font-size: 23px;
    font-weight: 700;
    letter-spacing: 0.5px;
    background: linear-gradient(90deg, var(--crimson) 0%, var(--blue) 90%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    line-height: 1.3;
}
.hero-sub {
    font-size: 12.5px;
    color: var(--text-muted);
    letter-spacing: 0.3px;
    margin-top: 2px;
}
.hero-right { display: flex; gap: 10px; z-index: 1; }
.hero-pill {
    display: flex; align-items: center; gap: 7px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11.5px;
    font-weight: 600;
    padding: 6px 13px;
    border-radius: 20px;
    letter-spacing: 0.4px;
}
.pill-dot {
    width: 7px; height: 7px; border-radius: 50%;
    display: inline-block;
    animation: pulseDot 1.6s infinite ease-in-out;
}
.pill-ok { background: var(--green-bg); color: var(--green) !important; border: 1px solid rgba(5,150,105,0.3); }
.pill-ok .pill-dot { background: var(--green); box-shadow: 0 0 5px var(--green); }
.pill-warn { background: var(--yellow-bg); color: var(--yellow) !important; border: 1px solid rgba(217,119,6,0.3); }
.pill-warn .pill-dot { background: var(--yellow); box-shadow: 0 0 5px var(--yellow); }
.pill-version { background: rgba(15,23,42,0.04); color: var(--text-muted) !important; border: 1px solid var(--border); }
@keyframes pulseDot { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }

/* ============== Tabs 选项卡 ============== */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: var(--sidebar);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 5px;
}
.stTabs [data-baseweb="tab"] {
    color: var(--text-muted) !important;
    font-size: 13.5px !important;
    font-weight: 600 !important;
    padding: 9px 22px !important;
    border-radius: 9px !important;
    background: transparent !important;
    transition: all 0.2s ease !important;
}
.stTabs [aria-selected="true"] {
    color: #fff !important;
    background: linear-gradient(120deg, var(--crimson) 0%, var(--blue) 100%) !important;
    box-shadow: var(--neon-blue-shadow) !important;
}
.stTabs [data-baseweb="tab-border"] { display: none !important; }
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }

/* ============== 按钮 · 统一渐变风格 ============== */
.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button,
[data-testid="stForm"] .stButton > button {
    background-image: linear-gradient(120deg, var(--crimson) 0%, var(--blue) 100%) !important;
    background-color: transparent !important;
    color: #fff !important;
    border: none !important;
    border-radius: 9px !important;
    padding: 8px 20px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    min-height: 40px !important;
    transition: all 0.2s ease !important;
    box-shadow: var(--neon-red-shadow), var(--neon-blue-shadow) !important;
}

/* Streamlit primary 按钮额外覆盖 */
.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"],
button[data-testid="stBaseButton-primary"],
button[kind="primary"] {
    background-image: linear-gradient(120deg, var(--crimson) 0%, var(--blue) 100%) !important;
    background-color: transparent !important;
    color: #fff !important;
    border: none !important;
    box-shadow: var(--neon-red-shadow), var(--neon-blue-shadow) !important;
}

/* hover 统一 */
.stButton > button:hover,
.stDownloadButton > button:hover,
.stFormSubmitButton > button:hover,
[data-testid="stForm"] .stButton > button:hover,
.stButton > button[kind="primary"]:hover,
.stDownloadButton > button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover,
button[kind="primary"]:hover {
    box-shadow: 0 0 18px var(--crimson-glow), 0 0 28px var(--blue-glow) !important;
    transform: translateY(-1px) !important;
    filter: brightness(1.08) !important;
    border: none !important;
}

/* active 统一 */
.stButton > button:active,
.stDownloadButton > button:active,
.stFormSubmitButton > button:active,
.stButton > button[kind="primary"]:active {
    box-shadow: 0 1px 4px var(--blue-glow) inset !important;
    transform: translateY(0) !important;
}

/* disabled 统一（特异性提升，确保覆盖渐变） */
.stButton > button:disabled,
.stButton > button[disabled],
.stDownloadButton > button:disabled,
.stDownloadButton > button[disabled],
.stFormSubmitButton > button:disabled,
.stButton > button[kind="primary"]:disabled {
    background-image: none !important;
    background-color: #E8EAF0 !important;
    color: #A0A8B8 !important;
    border: 1px solid var(--border) !important;
    box-shadow: none !important;
    cursor: not-allowed !important;
    transform: none !important;
    filter: none !important;
}

/* ============== 上传区 ============== */
[data-testid="stFileUploader"] { padding: 0 !important; margin: 0 !important; }
[data-testid="stFileUploader"] section {
    background: var(--card-solid) !important;
    border: 2px dashed var(--border-strong) !important;
    border-radius: 12px !important;
    padding: 16px !important;
    min-height: 80px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: all 0.25s ease !important;
}
[data-testid="stFileUploader"] section:hover {
    border-color: var(--blue) !important;
    background: rgba(0,82,204,0.03) !important;
    box-shadow: var(--neon-blue-shadow) !important;
}
[data-testid="stFileUploader"] label {
    color: var(--text) !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    margin-bottom: 6px !important;
}
[data-testid="stFileUploader"] section svg {
    fill: var(--blue) !important;
}
[data-testid="stFileUploader"] section p {
    color: var(--text-muted) !important;
    font-size: 12px !important;
}
[data-testid="stHorizontalBlock"] { gap: 8px !important; }

/* ============== 输入框 / 文本区域 / 选择框 ============== */
.stTextInput input, .stTextArea textarea, .stSelectbox [data-baseweb="select"] {
    background: var(--card-solid) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    box-shadow: inset 0 1px 2px rgba(15,23,42,0.03) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--blue) !important;
    box-shadow: 0 0 0 3px var(--blue-glow) !important;
}
.stSelectbox [data-baseweb="select"]:focus-within {
    border-color: var(--blue) !important;
    box-shadow: 0 0 0 3px var(--blue-glow) !important;
}

/* ============== KPI 数据卡（毛玻璃 + 霓虹顶部边框） ============== */
.kpi {
    background: var(--glass-bg) !important;
    backdrop-filter: blur(var(--glass-blur)) !important;
    -webkit-backdrop-filter: blur(var(--glass-blur)) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 12px !important;
    padding: 13px 14px !important;
    text-align: center !important;
    box-shadow: var(--glass-shadow) !important;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    border-top: 3px solid transparent !important;
    border-image: linear-gradient(90deg, var(--crimson), var(--blue)) 1 !important;
    position: relative !important;
}
.kpi:hover {
    transform: translateY(-3px) !important;
    box-shadow: var(--glass-shadow), 0 0 0 1px var(--border-strong), var(--neon-blue-shadow) !important;
}
.kpi-val {
    font-family: 'Rajdhani', 'JetBrains Mono', monospace !important;
    font-size: 24px !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
}
.kpi-lbl {
    font-size: 11px !important;
    color: var(--text-muted) !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    margin-top: 5px !important;
}

/* ============== 状态徽章 ============== */
.badge {
    display: inline-block;
    padding: 3px 11px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    text-align: center;
    letter-spacing: 0.3px;
}
.badge-ok { background: var(--green-bg); color: var(--green) !important; border: 1px solid rgba(5,150,105,0.3); }
.badge-warn { background: var(--yellow-bg); color: var(--yellow) !important; border: 1px solid rgba(217,119,6,0.3); }
.badge-err { background: var(--red-bg); color: var(--red) !important; border: 1px solid rgba(255,30,39,0.3); }

/* ============== 提示框 ============== */
.stAlert {
    border-radius: 10px !important;
    box-shadow: 0 3px 10px rgba(15,23,42,0.04) !important;
}
div[data-testid="stAlert"] .stMarkdown,
div[data-testid="stAlert"] .stMarkdown p,
div[data-testid="stAlert"] .stMarkdown span {
    color: inherit !important;
}
div[data-baseweb="notification"] { border-radius: 10px !important; }

/* ============== 终端日志面板（深色终端，对比清晰） ============== */
.hlog, .hlog * {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important;
}
.hlog {
    background: #0b0f17 !important;
    border: 1px solid rgba(5,150,105,0.4) !important;
    border-radius: 10px !important;
    padding: 14px !important;
    color: #34d399 !important;
    line-height: 1.6 !important;
    overflow-y: auto !important;
    max-height: 500px !important;
    box-shadow: inset 0 2px 8px rgba(0,0,0,0.35), 0 4px 14px rgba(15,23,42,0.1) !important;
    position: relative !important;
    margin-top: 8px !important;
    margin-bottom: 8px !important;
}
.hlog::after {
    content: " " !important;
    display: block !important;
    position: absolute !important;
    top: 0; left: 0; bottom: 0; right: 0 !important;
    background: linear-gradient(rgba(0,0,0,0) 50%, rgba(0,0,0,0.12) 50%) !important;
    z-index: 2 !important;
    background-size: 100% 2px !important;
    pointer-events: none !important;
}
.stMarkdown .hlog div { color: #34d399 !important; }
.stMarkdown .hlog div.lt {
    color: #5ab1ff !important;
    font-weight: 700 !important;
    border-bottom: 1px solid rgba(255,255,255,0.08) !important;
    padding-bottom: 6px !important;
    margin-bottom: 10px !important;
    font-size: 13px !important;
}
.stMarkdown .hlog div.lo { color: #8be9c7 !important; }
.stMarkdown .hlog div.le { color: #ff6b6f !important; font-weight: bold !important; }
.stMarkdown .hlog div.lk { color: #34d399 !important; font-weight: bold !important; }
.stMarkdown .hlog div.lw { color: #fbbf24 !important; font-weight: bold !important; }
.stMarkdown .hlog div.lh { color: #fbbf24 !important; font-weight: 700 !important; font-size: 13px !important; }
.stMarkdown .hlog div.ls {
    border-top: 1px dashed rgba(52,211,153,0.35) !important;
    margin: 6px 0 4px 0 !important;
    height: 0 !important;
    padding: 0 !important;
}

/* ============== 进度条 ============== */
.stProgress { margin: 8px 0 !important; padding: 0 !important; }
.stProgress > div { height: 6px !important; border-radius: 3px !important; background: #E8EAF0 !important; overflow: hidden; }
.stProgress > div > div {
    background: linear-gradient(90deg, var(--crimson) 0%, var(--blue) 100%) !important;
    box-shadow: 0 0 6px var(--blue-glow) !important;
    transition: width 0.3s ease-out !important;
}
.stSpinner { display: none !important; }

/* ============== 图片 ============== */
[data-testid="stImage"] img {
    border-radius: 9px;
    cursor: zoom-in;
    transition: all 0.25s ease;
    border: 1px solid var(--border);
}
[data-testid="stImage"] img:hover {
    opacity: 0.96;
    transform: scale(1.01);
    box-shadow: var(--neon-blue-shadow);
}

/* ============== 折叠面板（DOM 修复 + 毛玻璃） ============== */
details {
    background: var(--glass-bg) !important;
    backdrop-filter: blur(10px) !important;
    -webkit-backdrop-filter: blur(10px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 11px !important;
    padding: 8px 12px !important;
    margin-bottom: 12px !important;
    box-shadow: var(--glass-shadow) !important;
    overflow: hidden !important;
    position: relative !important;
}
details summary {
    color: var(--text) !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    cursor: pointer !important;
    padding: 4px 0 !important;
    border-radius: 8px !important;
    transition: color 0.2s ease !important;
    list-style: none !important;
}
details summary::-webkit-details-marker { display: none !important; }
details summary::before {
    content: "▸" !important;
    display: inline-block !important;
    margin-right: 8px !important;
    transition: transform 0.2s ease !important;
    color: var(--blue) !important;
    font-size: 12px !important;
}
details[open] summary::before {
    transform: rotate(90deg) !important;
}
details summary:hover { color: var(--blue) !important; }
details[open] {
    border-color: var(--border-strong) !important;
    box-shadow: var(--glass-shadow), var(--neon-blue-shadow) !important;
}
details > div, details > .stMarkdown, details > [data-testid] {
    overflow: hidden !important;
}

/* ============== 数据表格 ============== */
.stDataFrame { border-radius: 11px !important; overflow: hidden !important; }
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 11px !important;
    background-color: var(--card-solid) !important;
}

/* ============== 文字及排版 ============== */
.stMarkdown, .stMarkdown p, .stMarkdown div, .stMarkdown span, .stMarkdown strong {
    color: var(--text) !important;
}
h1, h2, h3, h4, h5, h6 {
    color: var(--text) !important;
    font-weight: 700 !important;
    font-family: 'Rajdhani', 'Inter', sans-serif !important;
}
.stCaption { color: var(--text-muted) !important; }

/* ============== 引导步骤条 ============== */
.guide-box {
    background: var(--glass-bg);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid var(--glass-border);
    border-left: 3px solid var(--crimson);
    border-radius: 0 11px 11px 0;
    padding: 12px 16px;
    margin-bottom: 12px;
    color: var(--text);
    font-size: 14px;
    box-shadow: var(--glass-shadow);
    display: flex;
    align-items: center;
    gap: 10px;
}
.guide-badge {
    background: linear-gradient(120deg, var(--crimson), var(--blue));
    color: white !important;
    padding: 2px 9px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 700;
}

/* ============== 空状态页 ============== */
.empty-state {
    text-align: center;
    padding: 46px 20px;
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--border-strong);
    border-radius: 16px;
    box-shadow: var(--glass-shadow);
    margin-top: 16px;
    animation: fadeInUp 0.5s ease-out;
    position: relative;
    overflow: hidden;
}
.empty-state::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, var(--crimson), var(--blue), transparent);
}
.empty-icon {
    font-size: 50px;
    margin-bottom: 14px;
    filter: drop-shadow(0 4px 10px var(--blue-glow));
    animation: floatIcon 3s ease-in-out infinite;
}
.empty-title {
    font-size: 17px;
    color: var(--text);
    font-weight: 700;
    margin-bottom: 8px;
    font-family: 'Rajdhani', 'Inter', sans-serif;
    letter-spacing: 0.3px;
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

/* ============== 对话框 / 确认弹窗 ============== */
div[role="dialog"] {
    background: var(--card-solid) !important;
    border-radius: 14px !important;
    border: 1px solid var(--border-strong) !important;
    box-shadow: 0 16px 36px rgba(15,23,42,0.18) !important;
}
div[role="dialog"] p, div[role="dialog"] h1, div[role="dialog"] h2, div[role="dialog"] h3 {
    color: var(--text) !important;
}

/* ============== 滚动条 ============== */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, rgba(255,30,39,0.3), rgba(0,82,204,0.35));
    border-radius: 6px;
}
::-webkit-scrollbar-thumb:hover { background: var(--blue-bright); }

/* ============== 动效 ============== */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes floatIcon {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-6px); }
}

/* ============== Streamlit 原生组件适配 ============== */
.stSelectbox [data-baseweb="popover"],
.stSelectbox [data-baseweb="menu"] {
    background: var(--card-solid) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
}
div[data-baseweb="popover"] {
    background: var(--card-solid) !important;
    border: 1px solid var(--border) !important;
    box-shadow: var(--glass-shadow) !important;
}

/* 表单 */
[data-testid="stForm"] {
    background: var(--glass-bg) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    padding: 12px !important;
    backdrop-filter: blur(8px) !important;
    -webkit-backdrop-filter: blur(8px) !important;
}

/* 多选/复选/单选 */
.stCheckbox label span, .stRadio label span {
    color: var(--text) !important;
}
</style>
"""
