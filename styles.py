# -*- coding: utf-8 -*-
"""自定义 CSS 主题 — 中国燃气 · 白底科技风"""

# 定义全局自定义 CSS 样式字符串，用于注入到 Streamlit 页面实现高端定制化 UI 视觉设计
CUSTOM_CSS = """
<style>
/* 导入外部高端无衬线和等宽字体，包括英文字体 Inter、代码字体 JetBrains Mono 以及 Rajdhani 科技风标题字体 */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&family=Rajdhani:wght@500;600;700&display=swap');

/* ============== 中国燃气 · 白底科技风 CSS 根属性常量 ============== */
:root {
    --bg: #F5F6FA; /* 设定全局主背景色为科技银灰偏白颜色 */
    --sidebar: #ECEEF5; /* 设定左侧配置侧边栏背景颜色 */
    --card: rgba(255, 255, 255, 0.72); /* 设定半透明高光毛玻璃卡片背景色 */
    --card-solid: #FFFFFF; /* 设定不透明实色卡片背景色 */
    --card-hover: #FFFFFF; /* 设定卡片在鼠标悬停悬浮态时的背景色 */
    --border: #E2E5EE; /* 设定基础灰色边框线条颜色 */
    --border-strong: rgba(0, 82, 204, 0.18); /* 设定高对比强化的深蓝投影边框线 */
    --text: #1C2230; /* 设定主标题及常规加粗字体的深黑字色 */
    --text-muted: #697386; /* 设定辅助类、占位及解释性说明文字的暗灰字色 */

    --crimson: #FF1E27; /* 设定中燃特色亮红色 */
    --crimson-text: #D6131C; /* 设定红色字体的深红字色 */
    --crimson-glow: rgba(255, 30, 39, 0.22); /* 设定中燃红色对应的渐变发光半透明光影 */
    --blue: #0052CC; /* 设定科技风高饱和蓝色 */
    --blue-bright: #0066FF; /* 设定交互高亮状态的亮蓝色 */
    --blue-glow: rgba(0, 82, 204, 0.22); /* 设定蓝色对应的渐变发光半透明光影 */

    --green: #059669; /* 设定正常通过绿颜色 */
    --green-bg: rgba(5, 150, 105, 0.10); /* 设定绿色背景下的微弱浅绿填充 */
    --red: #D6131C; /* 设定隐患警告红颜色 */
    --red-bg: rgba(255, 30, 39, 0.08); /* 设定红色背景下的微弱浅红填充 */
    --yellow: #D97706; /* 设定中风险警告橙黄色 */
    --yellow-bg: rgba(217, 119, 6, 0.10); /* 设定橙黄色背景下的微弱浅黄填充 */

    --glass-bg: rgba(255, 255, 255, 0.6); /* 设定毛玻璃效果的白色高光背景色 */
    --glass-border: rgba(0, 82, 204, 0.10); /* 设定毛玻璃卡片的深蓝发光细微线条 */
    --glass-blur: 14px; /* 设定高斯模糊滤波半径像素数 */
    --glass-shadow: 0 6px 24px rgba(15, 23, 42, 0.06); /* 设定大范围柔和的微阴影 */
    --neon-red-shadow: 0 0 12px rgba(255, 30, 39, 0.15), 0 0 24px rgba(255, 30, 39, 0.06); /* 红色按钮的霓虹外发光投影 */
    --neon-blue-shadow: 0 0 12px rgba(0, 82, 204, 0.18), 0 0 24px rgba(0, 82, 204, 0.06); /* 蓝色及选中页签的霓虹外发光投影 */

    /* ============== 间距可调参数 ============== */
    --sidebar-gap: 0.35rem; /* 侧边栏组件之间上下间距参数，可根据需要调大或调小（例如 0.2rem 至 1.0rem） */
}

/* ============== 全局背景：白底 + 微网格 + 色斑 ============== */
html, body, [data-testid="stAppViewContainer"] {
    background-color: var(--bg) !important; /* 强制页面容器应用灰白主色背景 */
    color: var(--text) !important; /* 强制主文字内容颜色 */
    color-scheme: light !important; /* 指定页面的标准色彩渲染方案为亮色 */
}
[data-testid="stAppViewContainer"] {
    /* 注入水平网格线、垂直网格线、左上角微红斑和右下角浅蓝晕，营造极简的高端科技风 */
    background-image:
        linear-gradient(rgba(15,23,42,0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(15,23,42,0.018) 1px, transparent 1px),
        radial-gradient(ellipse at 10% -10%, rgba(255,30,39,0.04), transparent 38%),
        radial-gradient(ellipse at 92% 105%, rgba(0,82,204,0.05), transparent 42%) !important;
    background-size: 52px 52px, 52px 52px, 100% 100%, 100% 100% !important; /* 限制网格线方格跨度为 52 像素 */
    background-attachment: fixed !important; /* 固定背景图案不随滚动条拉动而产生移动错位 */
}
.main, [data-testid="stMain"] {
    overflow-y: auto !important; /* 允许主面板垂直方向滚动 */
    overflow-x: hidden !important; /* 隐藏并防止横向溢出滚动条 */
}
section[data-testid="stSidebar"] {
    overflow-y: auto !important; /* 允许侧边栏面板垂直方向滚动 */
}
.stApp { background: transparent !important; } /* 清除 Streamlit 应用底盘层默认背景 */
.stApp > header { background: transparent !important; } /* 清除 Streamlit 页眉条默认灰色背景 */
.block-container {
    padding: 0.8rem 1.4rem 0.8rem 1.4rem; /* 设定容器四周的外距呼吸边空间 */
    max-width: 100%; /* 允许横向百分百拉平显示 */
    color: var(--text); /* 设定全局默认文字着色 */
}

/* 确保 caption 不与 markdown 重叠 */
[data-testid="stCaptionContainer"] {
    display: block !important; /* 强制设置为块状元素排列 */
    position: relative !important; /* 开启相对定位模式 */
    z-index: 1 !important; /* 控制覆盖堆叠优先级为 1 */
    margin-top: 2px !important; /* 设置顶部的外边距以防贴合 */
    clear: both !important; /* 清除浮动带来的错位排布 */
}
[data-testid="stMarkdownContainer"] {
    display: block !important; /* 强制块状排列 */
    position: relative !important; /* 开启相对定位模式 */
    max-width: 100% !important; /* 强制宽度最大为百分百 */
    overflow-wrap: break-word !important; /* 当长词溢出时自动强制折行换行 */
}
/* 所有 Streamlit 垂直块容器正确排列 */
[data-testid="stVerticalBlock"] {
    display: flex !important; /* 开启弹性盒排版模型 */
    flex-direction: column !important; /* 主轴方向向下垂直排列 */
    gap: 0.25rem !important; /* 调整并收缩子元素在垂直上的行间隙 */
}
/* 所有 Streamlit 水平块容器正确间距 */
[data-testid="stHorizontalBlock"] {
    gap: 0.5rem !important; /* 限制列与列之间的横向间距 */
    align-items: flex-start !important; /* 控制子项在垂直方向上沿顶格对齐 */
}
/* 列容器约束子元素不溢出 */
[data-testid="stColumn"] {
    overflow: hidden !important; /* 溢出列宽宽度的多余元素直接做切割裁剪 */
    min-width: 0 !important; /* 重置最小宽度，防止在弹性盒下撑开变形 */
}

/* 隐藏原生 chrome + Streamlit 原生菜单与页脚 */
#MainMenu, footer { display: none !important; } /* 彻底隐藏右上角的三个点菜单以及底部 Streamlit 广告声明页脚 */

/* 允许 toolbar 显示，以保证侧边栏展开按钮可见 */
header [data-testid="stToolbar"] {
    display: flex !important; /* 允许展开按钮的横带显示 */
    background: transparent !important; /* 背景透明 */
    pointer-events: none !important; /* 穿透点击流，防止由于占位导致后面的交互元素不可用 */
}
/* 隐藏除展开按钮以外的工具栏项 (如开发者选项) */
header [data-testid="stToolbar"] button:not([data-testid="stExpandSidebarButton"]) {
    display: none !important; /* 隐藏右上角其他原生按钮，保持右上角绝对纯净 */
}

/* ============== 侧边栏折叠/展开按钮 ============== */
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button {
    border-radius: 50% !important; /* 将侧边栏内的收起按钮调整为优雅的圆形外观 */
    transition: opacity 0.2s ease !important; /* 设置在 hover 时渐变显示的动画时间 */
}
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button:hover {
    opacity: 0.7 !important; /* hover 时降低透明度提供微弱的点击反馈 */
}

/* 折叠态下，展开按钮（Streamlit 1.58 中为 [data-testid="stExpandSidebarButton"]）完全保持悬浮可见 */
[data-testid="stExpandSidebarButton"] {
    position: fixed !important; /* 悬浮固定定位，使其脱离文档流 */
    top: 12px !important; /* 距离页面顶部 12 像素 */
    left: 8px !important; /* 距离页面左侧 8 像素 */
    z-index: 9999999 !important; /* 设置非常高的堆叠层级，保证浮动在所有页面元素之上 */
    display: flex !important; /* 弹性居中 */
    visibility: visible !important; /* 强制设为可见状态，打破原生的隐藏行为 */
    opacity: 1 !important; /* 设置完全不透明度 */
    pointer-events: auto !important; /* 恢复可鼠标点击事件响应 */
    /* 展开按钮的精致毛玻璃外观设计 */
    background: var(--glass-bg) !important;
    backdrop-filter: blur(var(--glass-blur)) !important;
    -webkit-backdrop-filter: blur(var(--glass-blur)) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 8px !important;
    box-shadow: var(--glass-shadow) !important;
    padding: 2px !important;
    transition: box-shadow 0.2s ease, border-color 0.2s ease !important; /* 设置交互时的动画平滑度 */
}
[data-testid="stExpandSidebarButton"]:hover {
    box-shadow: var(--glass-shadow), var(--neon-blue-shadow) !important; /* 鼠标划过时添加浅蓝色的霓虹影子外发光 */
    border-color: var(--border-strong) !important; /* 划过时将边框变为强蓝色 */
}

/* ============== 侧边栏折叠时保留 20px 宽度 ============== */
[data-testid="stSidebar"][aria-expanded="false"] {
    min-width: 20px !important; /* 强制折叠后侧边栏留出 20 像素的细竖条区域 */
    width: 20px !important;
    max-width: 20px !important;
    overflow: visible !important; /* 允许在细条上的元素如展开按钮可以溢出边界显示 */
}
/* 主内容区对应收缩，避免与 20px 条带重叠 */
[data-testid="stSidebar"][aria-expanded="false"] ~ [data-testid="stMain"] {
    margin-left: 20px !important; /* 将主面板向右退移 20 像素，避免内容被展开按钮遮挡 */
}

/* z-index 层级修复 */
[data-testid="stMain"] { z-index: 1 !important; }
header { z-index: 999999 !important; background: transparent !important; }

/* 顶部霓虹渐变彩色光带 */
[data-testid="stAppViewContainer"]::before {
    content: "" !important; /* 创建伪类 */
    position: fixed !important; /* 悬浮固定 */
    top: 0; left: 0; right: 0; height: 3px !important; /* 高度为 3 像素 */
    background: linear-gradient(90deg,
        var(--crimson) 0%, var(--crimson) 30%,
        var(--blue) 60%, var(--blue-bright) 100%) !important; /* 渐变由红变蓝 */
    box-shadow: 0 0 10px var(--crimson-glow), 0 0 18px var(--blue-glow) !important; /* 发光投影 */
    z-index: 1000000 !important; /* 极高层级固定最顶部 */
    pointer-events: none !important;
}

section[data-testid="stSidebar"] {
    overflow-y: auto !important;
    transition: width 0.25s ease, min-width 0.25s ease, max-width 0.25s ease,
                padding 0.25s ease, margin 0.25s ease !important; /* 侧边栏开启与折叠动作时的缓动效果时间 */
    overflow-x: hidden !important;
}

* { font-family: 'Inter', sans-serif; } /* 绑定全局中英文字体为高端无衬线 Inter 字体 */

/* ============== 侧边栏修饰 ============== */
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
    position: relative !important;
    height: 30px !important;
    min-height: 0px !important;
    padding: 15px !important;
    margin: 15px 2rem !important;
    display: flex !important;
    justify-content: flex-end !important; /* 让折叠按钮靠右对齐 */
    background: transparent !important;
    border: none !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] {
    position: relative !important;
    top: 0px !important;
    right: 0px !important;
    z-index: 99 !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
section[data-testid="stSidebar"] .block-container {
    padding: 15px !important;
}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: var(--sidebar-gap) !important; /* 调整侧边栏内组件上下垂直间距 */
}
section[data-testid="stSidebar"] .block-container > [data-testid="stVerticalBlock"] > div {
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
}
section[data-testid="stSidebar"] .block-container > [data-testid="stVerticalBlock"] > div:first-child {
    padding: 0px !important;
    margin: 0px !important;
}
section[data-testid="stSidebar"] [data-testid="stImage"] img {
    border-radius: 0px !important;
    border: none !important;
    transform: none !important;
    cursor: default !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] [data-testid="stImage"] img:hover {
    transform: none !important;
    box-shadow: none !important;
    opacity: 1 !important;
}
section[data-testid="stSidebar"] {
    background: var(--sidebar) !important;
    border-right: 1px solid var(--border) !important; /* 在右侧划出细线与主页面分割 */
}
section[data-testid="stSidebar"] label {
    color: var(--text-muted) !important; /* 将侧边栏的表单标签统一置灰显示，看起来专业而有秩序 */
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
/* 标题横幅左侧精致的红蓝霓虹装饰竖线条 */
.hero-banner::before {
    content: "";
    position: absolute; top: 0; left: 0; bottom: 0; width: 4px;
    background: linear-gradient(180deg, var(--crimson), var(--blue));
    box-shadow: 2px 0 10px var(--crimson-glow), 2px 0 20px var(--blue-glow);
}
.hero-left { display: flex; align-items: center; gap: 14px; z-index: 1; }
.hero-icon {
    font-size: 30px;
    filter: drop-shadow(0 2px 6px var(--blue-glow)); /* 为图标添加微弱的蓝色背光效果 */
}
.hero-title {
    font-family: 'Rajdhani', 'Inter', sans-serif;
    font-size: 23px;
    font-weight: 700;
    letter-spacing: 0.5px;
    background: linear-gradient(90deg, var(--crimson) 0%, var(--blue) 90%); /* 文字红蓝渐变色彩设计 */
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent; /* 将文字显示为透明以呈现上面的渐变填充 */
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
/* 自定义呼吸点闪烁动画 */
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
/* 选中选项卡后呈现红蓝渐变色彩并带有蓝霓虹外阴影效果 */
.stTabs [aria-selected="true"] {
    color: #fff !important;
    background: linear-gradient(120deg, var(--crimson) 0%, var(--blue) 100%) !important;
    box-shadow: var(--neon-blue-shadow) !important;
}
.stTabs [data-baseweb="tab-border"] { display: none !important; }
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }

/* ============== 按钮 · 统一中燃渐变风格 ============== */
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

/* 按钮悬停交互发光强化效果 */
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

/* 按钮点击瞬间陷入动效 */
.stButton > button:active,
.stDownloadButton > button:active,
.stFormSubmitButton > button:active,
.stButton > button[kind="primary"]:active {
    box-shadow: 0 1px 4px var(--blue-glow) inset !important;
    transform: translateY(0) !important;
}

/* 禁用失效按钮的样式退火与灰度显示（确保覆盖原有的渐变颜色背景） */
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

/* ============== 文件上传交互区域 ============== */
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

/* ============== KPI 数据卡（毛玻璃 + 霓虹顶部双色边框线） ============== */
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
/* 卡片悬停向外漂浮动效 */
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

/* ============== 状态小徽章样式 ============== */
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

/* ============== 提示警告栏样式 ============== */
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

/* ============== 终端日志面板（深色背景终端，仿黑客数字流） ============== */
.hlog, .hlog * {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important;
}
.hlog {
    background: #0b0f17 !important;
    border: 1px solid rgba(52,211,153,0.4) !important;
    border-radius: 10px !important;
    padding: 14px !important;
    color: #34d399 !important;
    line-height: 1.6 !important;
    overflow-x: hidden !important;
    box-shadow: inset 0 2px 8px rgba(0,0,0,0.35), 0 4px 14px rgba(15,23,42,0.1) !important;
    position: relative !important;
    margin-top: 8px !important;
    margin-bottom: 8px !important;
    box-sizing: border-box !important;
    width: 100% !important;
    max-width: 100% !important;
}
/* 模拟古老终端的极细扫描线横波滤镜效果 */
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

/* ============== 进度条修饰 ============== */
.stProgress { margin: 8px 0 !important; padding: 0 !important; }
.stProgress > div { height: 6px !important; border-radius: 3px !important; background: #E8EAF0 !important; overflow: hidden; }
.stProgress > div > div {
    background: linear-gradient(90deg, var(--crimson) 0%, var(--blue) 100%) !important;
    box-shadow: 0 0 6px var(--blue-glow) !important;
    transition: width 0.3s ease-out !important;
}
.stSpinner { display: none !important; } /* 隐藏丑陋的原生圆形加载加载器 */

/* ============== 图像圆角及悬浮放大切割效果 ============== */
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

/* ============== 展开面板 折叠菜单详情（毛玻璃风格） ============== */
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
/* 重新定制折叠面板的左侧三角形箭头，并着科技蓝 */
details summary::before {
    content: "▸" !important;
    display: inline-block !important;
    margin-right: 8px !important;
    transition: transform 0.2s ease !important;
    color: var(--blue) !important;
    font-size: 12px !important;
}
details[open] summary::before {
    transform: rotate(90deg) !important; /* 开启时旋转 90 度向下指向 */
}
details summary:hover { color: var(--blue) !important; }
details[open] {
    border-color: var(--border-strong) !important;
    box-shadow: var(--glass-shadow), var(--neon-blue-shadow) !important;
}
details > div, details > .stMarkdown, details > [data-testid] {
    overflow: hidden !important;
}

/* ============== 数据报表表格 ============== */
.stDataFrame { border-radius: 11px !important; overflow: hidden !important; }
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 11px !important;
    background-color: var(--card-solid) !important;
}

/* ============== 文字与排版 ============== */
.stMarkdown p, .stMarkdown strong {
    color: var(--text) !important;
}
h1, h2, h3, h4, h5, h6 {
    color: var(--text) !important;
    font-weight: 700 !important;
    font-family: 'Rajdhani', 'Inter', sans-serif !important;
}
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--text-muted) !important;
}

/* ============== 操作引导步骤框 ============== */
.guide-box {
    background: var(--glass-bg);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid var(--glass-border);
    border-left: 3px solid var(--crimson); /* 左侧红色宽指示线条 */
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

/* ============== 主页图片空状态占位符 ============== */
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
    animation: fadeInUp 0.5s ease-out; /* 渐进渐现动画 */
    position: relative;
    overflow: hidden;
}
.empty-state::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, var(--crimson), var(--blue), transparent); /* 顶部的渐变彩线 */
}
/* 空状态小图标微弱浮动飘逸动画效果 */
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

/* ============== 系统级交互对话框 / 弹窗 ============== */
div[role="dialog"] {
    background: var(--card-solid) !important;
    border-radius: 14px !important;
    border: 1px solid var(--border-strong) !important;
    box-shadow: 0 16px 36px rgba(15,23,42,0.18) !important;
}
div[role="dialog"] p, div[role="dialog"] h1, div[role="dialog"] h2, div[role="dialog"] h3 {
    color: var(--text) !important;
}

/* ============== 滚动条滑槽与滚动块美化 ============== */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, rgba(255,30,39,0.3), rgba(0,82,204,0.35)); /* 滚动滑块呈红蓝渐变微透明色 */
    border-radius: 6px;
}
::-webkit-scrollbar-thumb:hover { background: var(--blue-bright); } /* 鼠标滑过时高亮 */

/* ============== CSS 关键帧动画声明 ============== */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes floatIcon {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-6px); }
}

/* ============== Streamlit 其它表单子选择框组件适配 ============== */
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

/* 表单容器 */
[data-testid="stForm"] {
    background: var(--glass-bg) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    padding: 12px !important;
    backdrop-filter: blur(8px) !important;
    -webkit-backdrop-filter: blur(8px) !important;
}

/* 多选/复选/单选标签文字 */
.stCheckbox label span, .stRadio label span {
    color: var(--text) !important;
}
</style>
"""
