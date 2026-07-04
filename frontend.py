# -*- coding: utf-8 -*-
"""
数字化安全监督员 - AI Agent 安全监控面板
启动: streamlit run frontend.py
"""

import io  # 导入数据流模块用于截取日志数据
import sys  # 导入系统接口模块用于修改标准输出流
import os  # 导入操作系统接口模块用于处理文件路径及环境变量
import time  # 导入时间时间戳模块用于生成唯一图名及模拟延时
import json  # 导入 JSON 数据解析库以加载/保存本地运行配置参数
import warnings  # 导入警告过滤模块以屏蔽第三方库的多余警告信息
warnings.filterwarnings("ignore", category=UserWarning, module="paddle")  # 忽略 Paddle 内部关于 ccache 等非致命性用户警告

import check_deps  # 引入启动自检模块，自动检查环境及第三方库版本
import streamlit as st  # 导入 Streamlit 前端渲染框架
import pandas as pd  # 导入 Pandas 数据分析库用于在汇总页展示表格报表
from styles import CUSTOM_CSS  # 从 styles 导入精美的全局科技风样式定义字符串
from components import (  # 从原子组件库中引入状态徽章、KPI 统计栏、审批显示及通知写入等组件
    badge, render_kpi_row, render_ticket_kpis,
    render_notification_btn, render_record_badge,
)  # 结束组件解包导入

# ---- 配置（优先环境变量，其次 config.json） ----
from agent_core import load_config  # 从智能体核心层中引入加载配置的工具函数
_cfg = load_config()  # 执行配置加载，读取字典数据并存入局部 _cfg 变量中
_ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()  # 从 VERSION 文件读取当前小版本号并剥离换行

st.set_page_config(page_title="数字化安全监督员", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")  # 强制初始化 Streamlit 页面配置，布局设为宽看板模式

# ---- 自定义主题 ----
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)  # 注入全局自定义的 CSS 样式代码到本页面以获得顶级科技白底风外观

# ---- 强制展开侧边栏：清除 localStorage + 自动点击展开按钮 ----
st.html("""
<script>
(function() {
    // 1. 清除所有侧边栏相关 localStorage 缓存防止原生记忆
    try {
        Object.keys(localStorage).forEach(function(k) {
            if (k.toLowerCase().indexOf('sidebar') !== -1) {
                localStorage.removeItem(k);
            }
        });
    } catch(e) {}

    // 2. 如果侧边栏仍处于折叠态，找到悬浮的展开按钮并点击
    function tryExpand() {
        var root = window.parent.document;
        var btn = root.querySelector('[data-testid="stExpandSidebarButton"]');
        if (btn) {
            btn.click();
            return true;
        }
        return false;
    }
    // 延迟 300 毫秒等 Streamlit DOM 全部渲染完成后执行 JavaScript 模拟展开点击
    setTimeout(function() {
        if (!tryExpand()) setTimeout(tryExpand, 500);
    }, 300);

    // 3. 将 stSidebarHeader 移动到 stCaptionContainer (副标题) 的下方
    function moveHeader() {
        var root = window.parent.document;
        var header = root.querySelector('[data-testid="stSidebarHeader"]');
        var sidebar = root.querySelector('[data-testid="stSidebar"]');
        if (!sidebar || !header) return;
        
        var captions = sidebar.querySelectorAll('[data-testid="stCaptionContainer"]');
        var targetCaption = null;
        for (var i = 0; i < captions.length; i++) {
            if (captions[i].textContent.indexOf('HSE') !== -1) {
                targetCaption = captions[i];
                break;
            }
        }
        
        if (targetCaption) {
            var container = targetCaption;
            while (container && container.parentNode && container.parentNode.getAttribute('data-testid') !== 'stVerticalBlock') {
                container = container.parentNode;
            }
            if (container && container.parentNode && header.previousSibling !== container) {
                container.parentNode.insertBefore(header, container.nextSibling);
            }
        }
    }
    // 每 300 毫秒执行一次，保持稳定贴合
    setInterval(moveHeader, 300);

    // 自动滚动日志终端到底部
    function scrollLogs() {
        var root = window.parent.document;
        var logs = root.querySelectorAll('.hlog');
        logs.forEach(function(log) {
            var isAtBottom = (log.scrollHeight - log.clientHeight - log.scrollTop) < 50;
            var lastHeight = log.getAttribute('data-last-height') || 0;
            var currentHeight = log.scrollHeight;
            if (currentHeight !== parseInt(lastHeight)) {
                log.setAttribute('data-last-height', currentHeight);
                if (isAtBottom || lastHeight === 0) {
                    log.scrollTop = log.scrollHeight;
                }
            }
        });
    }
    // 每 300 毫秒执行一次，保持终端滚动到底部
    setInterval(scrollLogs, 300);
})();
</script>
""", unsafe_allow_javascript=True)  # 注入页面执行脚本，并使能 JavaScript 允许机制

# ---- Session State (全局会话状态维护) ----
if "results" not in st.session_state: st.session_state.results = []  # 若 results 未初始化，则初始化为一个空的分析结果列表
if "delete_id" not in st.session_state: st.session_state.delete_id = None  # 初始化记录待删除数据 ID 标识变量为空
if "pending_files" not in st.session_state: st.session_state.pending_files = None  # 初始化暂存准备上传的作业图片文件句柄为空
if "show_uploader" not in st.session_state: st.session_state.show_uploader = False  # 初始化控制上传组件面板的显示显示标记为否
if "upload_done" not in st.session_state: st.session_state.upload_done = False  # 初始化当前上传操作是否完全完成的标记为否


# ---- 侧边栏配置面板 ----
with st.sidebar:  # 进入侧边栏渲染上下文本环境
    _logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
    if os.path.exists(_logo_path):
        st.image(_logo_path, use_container_width=False)
    st.caption(f"**🛡️ 牡丹江中燃 HSE · AI Agent** `v{_ver}`")  # 渲染侧边栏主标题及对应版本号

    # API 基本信息配置
    api_key = st.text_input("API Key", _cfg.get("api_key", ""), type="password")  # 渲染主大模型密钥输入框，设定为密码类型隐藏字符
    base_url = st.text_input("API URL", _cfg.get("base_url", ""))  # 渲染主大模型 API 服务域名路由基地址输入框
    model_name = st.text_input("模型", _cfg.get("model_name", ""))  # 渲染主推理大模型的模型具体别名输入框

    # OCR 表格识别模式切换选择
    _ocr_modes = {  # 映射中文选择别名到程序底层所要求的模式代码字典
        "坐标聚类（默认）": "cluster",
        "自适应边框检测": "adaptive",
    }  # 结束模式字典定义
    ocr_mode_label = st.selectbox(  # 渲染下拉单选框以供用户切换 OCR 算法类型选择
        "📋 OCR 表格模式",
        list(_ocr_modes.keys()),  # 传入中文选项列表
        index=0,  # 默认选中第一项：坐标聚类模式
        help="坐标聚类：基于文字坐标重建表格行列\n自适应边框检测：OpenCV检测表格线段，按单元格组织文本",  # 气泡帮助帮助说明
    )  # 结束下拉框渲染
    ocr_mode = _ocr_modes[ocr_mode_label]  # 从映射字典中提取当前选中的底层处理模式参数

    # OCR 底层推理引擎选择
    _ocr_engines = {  # 映射中文引擎别名到底层引擎代码字典
        "本地 PaddleOCR（带坐标）": "paddleocr",
        "视觉大模型": "vision",
    }  # 结束引擎字典定义
    ocr_engine_label = st.selectbox(  # 渲染下拉单选框以供切换核心 OCR 技术选型
        "🔍 OCR 引擎",
        list(_ocr_engines.keys()),  # 传入中文引擎选项列表
        index=0,  # 默认选中第一项：本地 PaddleOCR 推理模式
        help="本地 PaddleOCR：默认，本地推理，输出带坐标，支持责任人定位\n"
             "视觉大模型：调用 VL 模型直接读图识别，一步完成结构+文字+符号，不支持坐标定位",  # 气泡说明
    )  # 结束下拉框渲染
    ocr_engine = _ocr_engines[ocr_engine_label]  # 从字典提取选定的底层引擎处理类型

    # OCR 推理设备选择（CPU / GPU）
    _ocr_devices = {  # 映射中文设备别名到底层设备代码字典
        "CPU（默认）": "cpu",
        "GPU 加速": "gpu",
    }  # 结束设备字典定义
    ocr_device_label = st.selectbox(  # 渲染下拉单选框以供切换 OCR 推理硬件设备
        "⚡ OCR 推理设备",
        list(_ocr_devices.keys()),  # 传入中文设备选项列表
        index=0,  # 默认选中第一项：CPU 模式
        help="CPU：兼容性最佳，无需额外依赖\nGPU 加速：需安装 paddlepaddle-gpu，推理速度提升 5~10 倍",  # 气泡帮助说明
    )  # 结束下拉框渲染
    ocr_device = _ocr_devices[ocr_device_label]  # 从映射字典中提取当前选中的底层设备参数
    if ocr_device == "gpu":  # 如果选定为 GPU 模式
        try:  # 尝试检测 GPU 可用性
            import paddle as _pd  # 临时导入 paddle
            if not _pd.device.is_compiled_with_cuda():  # 检测是否安装了 GPU 版
                st.caption("⚠️ 当前安装的是 CPU 版 PaddlePaddle，GPU 不可用，将自动回退到 CPU")  # 警告 GPU 不可用
            else:  # 如果已安装 GPU 版
                _gpu_count = _pd.device.cuda.device_count()  # 获取 GPU 数量
                st.caption(f"✅ 检测到 {_gpu_count} 个 GPU 设备，已启用加速")  # 显示 GPU 可用提示
        except Exception:  # 捕获导入失败等异常
            st.caption("⚠️ 无法检测 GPU 状态")  # 显示未知状态提示

    # 视觉引擎下 OCR 模式不生效的动态高亮提示
    if ocr_engine == "vision":  # 如果当前选定为视觉大模型引擎
        st.caption("💡 视觉大模型直接读图返回 Markdown，OCR 表格模式不生效，责任人定位不可用")  # 在侧边栏渲染提示说明文字进行强调

    # 视觉大模型独立配置展开
    vision_api_key = _cfg.get("vision_api_key", "")  # 获取配置中的视觉模型密钥
    vision_base_url = _cfg.get("vision_base_url", "")  # 获取配置中的视觉模型 API 基础地址
    vision_model_name = _cfg.get("vision_model_name", "")  # 获取配置中的视觉模型具体名称参数
    if ocr_engine == "vision":  # 判断若开启了视觉引擎模式
        st.markdown("**👁️ 视觉模型配置**")  # 渲染侧边栏分组标题说明
        vision_api_key = st.text_input("视觉 API Key", vision_api_key, type="password", key="_v_key", help="视觉大模型的 API Key，可与主模型不同")  # 视觉大模型专用的密码类型输入框
        vision_base_url = st.text_input("视觉 API URL", vision_base_url, key="_v_url", help="视觉大模型的 API 地址")  # 视觉大模型专用的基础 URL 地址输入框
        vision_model_name = st.text_input("视觉模型", vision_model_name, key="_v_model", help="支持视觉的模型名称，如 Qwen-VL / GPT-4o")  # 视觉大模型具体的模型名称输入框
        if not vision_model_name:  # 检查如果用户在此处清空了视觉模型名称
            st.warning("⚠️ 请配置视觉模型名称")  # 在下方给出黄色的警告气泡框提醒

    # 代理服务器设置
    proxy_enabled = st.checkbox("🌐 使用代理访问 AI 模型", value=bool(_cfg.get("proxy", "")), key="_proxy_on", help="勾选后通过代理服务器访问 Google/Gemini 等海外 AI 模型")  # 提供代理使能多选复选框
    proxy_url = ""  # 初始化代理地址变量为空
    if proxy_enabled:  # 如果用户勾选启用了网络代理
        proxy_url = st.text_input("代理地址", _cfg.get("proxy", "http://127.0.0.1:9192"), key="_proxy_url", help="格式: http://127.0.0.1:端口")  # 渲染代理具体地址输入框，默认提供 9192 端口

    # 钉钉 AI 多维表配置
    st.markdown("---")
    dingtalk_mcp_url = st.text_input(  # 渲染钉钉多维表 MCP 写入基地址输入框
        "钉钉 MCP 地址",  # 输入框说明
        _cfg.get("dingtalk_mcp_url", ""),  # 从配置字典中提取默认值
        type="password",  # 密码模式屏蔽明文
        help="钉钉 AI 表格 MCP Streamable HTTP 地址",  # 气泡解释
        key="_dd",  # 绑定状态 key
        placeholder="https://mcp-gw.dingtalk.com/server/...?key=...",  # 示例占位字符
    )  # 结束文本框定义
    if not dingtalk_mcp_url:  # 检查如果钉钉多维表 MCP 地址为空
        st.markdown("<div style='font-size: 11.5px; color: #D97706; background-color: rgba(217, 119, 6, 0.08); border: 1px solid rgba(217, 119, 6, 0.2); padding: 8px; border-radius: 6px; margin-top: 4px; line-height: 1.4;'>⚠️ 未配置钉钉 MCP 地址，将无法写入 AI 表格，请在上方设置后点击「💾 保存设置」</div>", unsafe_allow_html=True)

    # 保存配置按钮逻辑段
    st.markdown("---")  # 渲染第三条侧边栏分割横线
    if st.button("💾 保存设置", use_container_width=True):  # 渲染一个拉平填满侧栏的保存设置按键
        _cfg["api_key"] = api_key  # 将当前输入的 API 密钥存入配置缓存
        _cfg["base_url"] = base_url  # 将当前输入的 URL 写入配置缓存
        _cfg["model_name"] = model_name  # 将当前输入的模型别名写入配置缓存
        _cfg["vision_api_key"] = vision_api_key  # 保存视觉模型的密钥参数
        _cfg["vision_base_url"] = vision_base_url  # 保存视觉模型的基础 URL 参数
        _cfg["vision_model_name"] = vision_model_name  # 保存视觉模型的名字参数
        _cfg["proxy"] = proxy_url if proxy_enabled else ""  # 根据代理勾选状态写入代理字符串或清空配置
        _cfg["dingtalk_mcp_url"] = st.session_state.get("_dd", _cfg.get("dingtalk_mcp_url", ""))  # 保存写入 of 钉钉 MCP 数据库网关地址
        # 将配置同步到全局 Python 环境变量，保证 Agent 可直接读取
        if api_key: os.environ["ONLINE_API_KEY"] = api_key  # 同步 API Key 到系统环境变量
        if base_url: os.environ["ONLINE_BASE_URL"] = base_url  # 同步 API Base URL 到系统环境变量
        if model_name: os.environ["ONLINE_MODEL"] = model_name  # 同步 Model Name 到系统环境变量
        _save_path = os.path.join(os.path.dirname(__file__), "config.json")  # 准备并合成 config.json 配置文件的保存路径
        _tmp_path = _save_path + ".tmp"  # 设置临时的写入中转文件防并发损坏
        try:  # 开启写入防灾防护
            with open(_tmp_path, "w", encoding="utf-8") as f:  # 新建并写入临时文件
                json.dump(_cfg, f, ensure_ascii=False, indent=2)  # 将配置字典对象格式化输出为 JSON 字符串
            os.replace(_tmp_path, _save_path)  # 通过原子替换操作覆盖正式配置文件，保障文件完整性
        except Exception:  # 若写文件发生硬件或权限错误
            try:  # 尝试安全清理
                os.remove(_tmp_path)  # 清理残留的垃圾临时文件
            except OSError:  # 捕获清理失败的异常
                pass  # 安全跳过
            st.error("保存配置失败")  # 在侧栏底部报红色错误提示
            st.stop()  # 阻断当前 Streamlit 页面的执行
        st.success("已保存（环境变量 + 配置文件）")  # 报绿色成功保存状态气泡提示

# ---- 主面板顶部：Hero 巨幅渐变装饰性横幅 ----
_status_ok = bool(api_key)  # 以 API 密钥是否已配置作为引擎是否准备就绪的布尔标记
st.markdown(f"""
<div class="hero-banner">
    <div class="hero-left">
        <div class="hero-icon">🛡️</div>
        <div>
            <div class="hero-title">数字化安全监督员</div>
            <div class="hero-sub">牡丹江中燃 · HSE AI Agent 安全监控系统</div>
        </div>
    </div>
    <div class="hero-right">
        <span class="hero-pill {'pill-ok' if _status_ok else 'pill-warn'}">
            <span class="pill-dot"></span>{'AI 引擎已就绪' if _status_ok else '请配置 API Key'}
        </span>
        <span class="hero-pill pill-version">v{_ver}</span>
    </div>
</div>
""", unsafe_allow_html=True)  # 通过 markdown 注入上面拼接的 Hero html 代码，允许 HTML 标签渲染

tab1, tab2 = st.tabs(["📷 处理作业票", "📊 AI 看板"])  # 在主面板创建两个大标签 Tab：📷 处理作业票 以及 📊 AI 看板


# ==================== Tab 1: 作业票智能感知、分析与反思执行流程 ====================
with tab1:  # 进入第一个 Tab 面板的渲染环境
    # ---- 基础前置配置检查 ----
    if not api_key:  # 检测主大模型密钥是否为空
        st.warning("⚠️ 请先在左侧边栏填写 API Key，否则无法处理。点击左上角 **>** 展开边栏。")  # 提醒用户需要先填写 Key

    # ---- 动态操作向导步骤条 ----
    step = 1  # 设定初始第 1 步
    if st.session_state.get("upload_done") and st.session_state.get("pending_files"):  # 判断若图片成功上传并就绪
        step = 2  # 调整为第 2 步

    guide = st.empty()  # 创建操作引导占位符容器
    if step == 1:  # 如果当前在第 1 步
        guide.markdown("""
        <div class="guide-box">
            <span class="guide-badge">第 1 步</span> 点击下方 <b>📤 上传</b> 提供作业票照片
        </div>
        """, unsafe_allow_html=True)  # 渲染引导点击上传的提示框
    elif step == 2:  # 如果当前在第 2 步
        guide.markdown("""
        <div class="guide-box">
            <span class="guide-badge">第 2 步</span> 照片已就绪，点击 <b>⚙️ 处理</b> 开始 AI 分析
        </div>
        """, unsafe_allow_html=True)  # 渲染引导点击处理的提示框

    # ---- 动作按钮栏：上传 vs. 处理 ----
    c1, c2 = st.columns(2)  # 将交互按键行划分为两等份的分栏
    with c1:  # 进入第一分栏
        show_upload = st.button("📤 上传", use_container_width=True)  # 渲染上传大按键并填平列宽
    with c2:  # 进入第二分栏
        can_process = st.session_state.get("upload_done") and st.session_state.get("pending_files")  # 感知是否可被处理
        run_clicked = st.button("⚙️ 处理", use_container_width=True, disabled=not can_process)  # 渲染处理大按键，当无文件时置灰失效

    # 按钮点击状态切换事件处理
    if show_upload:  # 如果用户点击了上传按键
        st.session_state.show_uploader = True  # 设置展示上传选择器标志为真
        st.session_state.upload_done = False  # 重置上传就绪标志为否，进入新一轮上传状态
        st.session_state.pending_files = None  # 清空暂存的待处理文件

    # ---- 文件拖拽选择器 ----
    if st.session_state.get("show_uploader"):  # 判断如果控制显示上传面板的标志为真
        picked = st.file_uploader("选择图片", type=["jpg","jpeg","png","bmp"], accept_multiple_files=False, label_visibility="collapsed", key="fu_main")  # 显示 Streamlit 原生上传面板，限制单张图片
        if picked and not st.session_state.get("upload_done"):  # 判断用户选择了图片且此图尚未触发上传流水线
            st.session_state.pending_files = [picked]  # 将上传的文件句柄存入会话状态 pending_files 列表中
            prog_ph = st.empty()  # 创建进度条占位容器
            status_ph = st.empty()  # 创建文字状态占位容器
            for pct in range(0, 101, 5):  # 模拟上传百分比循环（提供顶级视觉缓动感）
                prog_ph.progress(pct)  # 更新进度条百分比值
                status_ph.caption(f"📤 上传中... {picked.name} — {pct}%")  # 显示已上传多少的文字提示
                time.sleep(0.05)  # 睡眠 50 毫秒以提供极佳的动画展示时间
            prog_ph.empty()  # 清空进度条占位符
            status_ph.success(f"✅ 上传完成 — {picked.name}（{picked.size/1024:.0f} KB）")  # 显示绿色高亮上传成功的最终字样
            st.session_state.upload_done = True  # 设定上传完毕就绪标志为真
            st.rerun()  # 触发 Streamlit 重绘刷新，重写刷新顶部的操作引导步骤条
        elif picked and st.session_state.get("upload_done"):  # 若属于已重绘刷新重绘完毕的状态
            st.success(f"✅ {picked.name}（{picked.size/1024:.0f} KB）")  # 静态显示当前就绪的图片名称体积

    # 空状态看板和上次处理历史展示逻辑
    final_files = st.session_state.get("pending_files") or []  # 提取就绪的待处理文件列表，无则置空列表

    if not final_files and not run_clicked:  # 如果当前无上传文件且未触发处理行为
        if st.session_state.results:  # 检查会话缓存中是否存有上一张作业票的历史处理结果
            st.markdown("**上次处理结果**")  # 渲染段落小标题
            for item in st.session_state.results:  # 遍历获取历史卡片条目
                d = item["data"]  # 提取结构化数据结果
                render_ticket_kpis(d)  # 通过组件渲染历史作业票的 KPI 主横幅
        else:  # 若没有任何处理历史，则显示顶级质感的空状态装饰画页
            st.markdown("""
            <div class="empty-state">
                <div class="empty-icon">🛡️</div>
                <div class="empty-title">上传作业票照片，AI 自动完成全部分析</div>
                <div class="empty-desc">支持：动火作业票 · 带气作业票 · 临时用电作业票</div>
                <div class="empty-action">点击上方 <b>📤 上传</b> 选择照片开始分析</div>
            </div>
            """, unsafe_allow_html=True)  # 渲染高质感的空状态面板 HTML 代码

    # 待处理图片缩略预览图
    if final_files and not run_clicked and not st.session_state.get("run_processing"):  # 当有文件但尚未点击“处理”按钮时
        thumbs = st.columns(min(len(final_files) + 1, 6))  # 划分预览图片的列容器
        for i, f in enumerate(final_files[:5]):  # 限制最多渲染 5 张预览小图
            with thumbs[i]: st.image(f, width=100)  # 在列中以 100 像素大小预览该图
        with thumbs[min(len(final_files), 5)]:  # 在预览图的最后一格
            st.markdown(f"<div style='text-align:center;padding-top:35px;color:#69707f;font-size:12px'>{len(final_files)}张</div>", unsafe_allow_html=True)  # 显示总图片张数

    # 触发 AI 算法核心处理段
    if run_clicked and final_files:  # 如果用户点击了处理并且文件已上传
        st.session_state.run_processing = True  # 设置运行中标志为真
        st.rerun()  # 触发 Streamlit 重绘刷新进入下面的真执行主逻辑

    if st.session_state.get("run_processing") and final_files:  # 捕获由重绘刷新触发的真执行阶段
        st.session_state.run_processing = False  # 瞬间复位执行标志以防二次刷新重试

        from agent_core import SecurityAgent, LLMBrain, AgentTools  # 在执行时动态按需引入核心库，提高系统首次加载效率
        _proxy = proxy_url if proxy_enabled else ""  # 判定是否打包代理设置
        brain = LLMBrain(api_key=api_key, base_url=base_url, model_name=model_name, proxy=_proxy)  # 实例化主力决策分析的 LLMBrain
        vision_brain = None  # 初始化视觉大模型大脑为空
        if ocr_engine == "vision":  # 如果当前选定由视觉大模型来直接读图识别
            vk = vision_api_key or api_key  # 若视觉模型专属密钥为空则退回使用主密钥
            vu = vision_base_url or base_url  # 若专属地址为空退回使用主基地址
            vm = vision_model_name  # 使用专属的视觉大模型工程名称，如 qwen2.5-vl
            if not vm:  # 检查如果忘记填写大模型名字
                st.error("❌ 视觉大模型引擎需要配置视觉模型名称")  # 终端及界面报错并阻断
                st.stop()  # 页面执行断点
            vision_brain = LLMBrain(api_key=vk, base_url=vu, model_name=vm, proxy=_proxy)  # 实例化专属视觉大模型大脑
        agent = SecurityAgent(brain=brain, ocr_mode=ocr_mode, ocr_engine=ocr_engine, ocr_device=ocr_device, vision_brain=vision_brain)  # 传入各级大脑及模式和设备以构造 Agent 主代理
        st.session_state.results = []  # 重置并清空历史处理结果列表，只显示本次全新任务的结果

        # ---- 上传并持久化保存文件至 uploads 文件夹 ----
        upload_status = st.empty()  # 新建图片保存提示信息文字容器
        upload_progress = st.progress(0)  # 新建图片保存进度条容器
        saved_paths = []  # 初始化物理保存文件的绝对路径列表
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads")  # 定位并计算 uploads 存储物理目录
        os.makedirs(upload_dir, exist_ok=True)  # 自动检测并递归创建该 uploads 存储目录以防目录不存在报错

        for i, f in enumerate(final_files):  # 迭代将文件从 Streamlit 临时缓存写入物理磁盘
            pct = int((i / len(final_files)) * 100)  # 计算当前保存百分比
            upload_progress.progress(pct)  # 刷新展示进度条
            upload_status.caption(f"📤 保存中... {f.name} ({i+1}/{len(final_files)})")  # 展示当前正在写入的图片基础名称
            suffix = os.path.splitext(f.name)[1] or ".jpg"  # 提取图片后缀格式，默认兜底使用 .jpg
            save_path = os.path.join(upload_dir, f"{int(time.time())}_{i}{suffix}")  # 用时间戳和索引命名生成唯一的本地图片物理路径
            with open(save_path, "wb") as fp:  # 以二进制覆写模式新建并打开物理存储文件
                fp.write(f.getvalue())  # 将 Streamlit 临时内存中的图片字节流写入物理硬盘
            saved_paths.append(save_path)  # 将成功生成的物理物理文件路径存入列表
            time.sleep(0.1)  # 短暂睡眠 100 毫秒让保存进度条细节能被人类眼睛看见

        upload_progress.progress(100)  # 进度条打满 100%
        upload_status.caption(f"✅ {len(saved_paths)} 张图片已保存，开始 Agent 处理...")  # 提示进入智能体处理阶段
        time.sleep(0.3)  # 睡眠 300 毫秒以过渡动画
        upload_progress.empty()  # 清空并释放进度条占位容器
        upload_status.empty()  # 清空保存文字提示容器

        # ---- Agent 核心迭代逐张分析图片流程 ----
        for idx, uploaded in enumerate(final_files):  # 循环迭代开始主算法的执行
            save_path = saved_paths[idx]  # 获取当前迭代对应的本地物理图像文件路径

            # 界面采用黄金比例分栏：左侧 3 份显示核心结论，右侧 2 份显示黑客风 Agent 思考日志数据流
            col_r, col_l = st.columns([3, 2])  # 创建该结构划分

            # 左侧分栏：用来呈现当前处理大图的缩略图及处理进度提示
            with col_r:  # 进入左栏上下文
                status_text = st.empty()  # 创建左栏子状态文字容器
                progress = st.progress(0)  # 创建左栏处理总进度条容器
                img_placeholder = st.empty()  # 创建图片展示临时占位符
                status_text.caption(f"[{idx+1}/{len(final_files)}] {uploaded.name} — 准备中...")  # 提示该文件准备中
                img_placeholder.image(save_path, caption=uploaded.name, use_container_width=True)  # 显示完整的待分析原图

            # 右侧分栏：提供日志流的视觉占位
            with col_l:  # 进入右栏上下文
                pass  # 日志将由下面的独立 log_ph 来进行局部刷新替换渲染

            log_ph = col_l.empty()  # 新建用来展现黑客风 Thinking 思考控制台的专用占位容器
            log_buf = []  # 初始化该图的本地终端日志缓存列表，仅保存本图片的运行信息
            _t0_img = time.time()  # 记录当前图片启动执行的初始系统时间点
            _last_stage = [""]  # 用单元素列表形式包装当前处理阶段，以便在闭包函数 hlog 中可以动态覆写修改

            def hlog(line, _save_path=save_path, _name=uploaded.name):  # 定义用于捕获底层 stdio 输出以渲染黑客日志终端的辅助闭包函数
                _dt = time.time() - _t0_img  # 计算从启动分析到当前这行日志输出的相对耗时
                _mm, _ss = divmod(int(_dt), 60)  # 将秒数转换为分秒格式
                _ts = f"[{_mm:02d}:{_ss:02d}] "  # 格式化时间戳前缀，如 "[00:14] "
                log_buf.append(_ts + line)  # 拼接时间戳与输出日志内容，并存入日志缓存中
                import html as _h  # 导入自带的 html 工具包对日志中可能存在的特殊符号进行实体字元安全编码，防样式崩塌
                parts = []  # 初始化拼接的 HTML 行列表
                for l in log_buf:  # 展示完整的日志数据，防止日志截断
                    # 检测当前日志文本中是否包含表示阶段进度的特征括号，如 "[规划]" 或 "[感知]"
                    stage = ""  # 初始化匹配阶段为空
                    if "[" in l and "]" in l:  # 若左右括号同时存在
                        _bracket = l.split("]", 1)[0].split("[", 1)[-1] if "[" in l else ""  # 解析提取中括号内的文本字串，如 "规划"
                        if _bracket in ("规划", "感知", "归档", "推理", "反思", "执行", "总结"):  # 如果是核心 7 大主线步骤之一
                            stage = _bracket  # 将当前的主线步骤赋值给当前行阶段变量
                    # 感知到新阶段进入后，自动插入一行虚线分割线，形成清晰的模块化视觉阅读效果
                    is_header = False  # 初始化当前行是否属于大阶段头标志为假
                    if stage and stage != _last_stage[0] and _last_stage[0] != "":  # 若发生了阶段转换且不是第一行
                        parts.append('<div class="ls"></div>')  # 往 HTML 数组中插入一条包含 ls 类的自定义水平虚线分割标签
                        is_header = True  # 判定本行为该阶段的头部行
                    elif stage and _last_stage[0] == "":  # 若属于首行首阶段
                        is_header = True  # 设定为大阶段头部行
                    if stage:  # 若本行被标记了有效阶段
                        _last_stage[0] = stage  # 覆写列表元素记录当前所处的阶段

                    c = "lh" if is_header else ""  # 如果是阶段标题，应用带有 lh (高亮绿标题) 的类样式
                    if not c:  # 若不属于阶段头，则根据日志包含的内容特征码，分别着以不同的颜色
                        if "Tool" in l: c = "lo"  # 底层工具库及外部调用调用（如 OCR / DB / Vision API）输出渲染为蓝色 text (lo)
                        elif "FAIL" in l or "出错" in l: c = "le"  # 识别错误、流程报错、异常抛出着为红色 text (le)
                        elif "OK" in l or "通过" in l or "完成" in l: c = "lk"  # 校验通过、安全检查完毕及流程结束着为绿色 text (lk)
                        elif "重试" in l or "未通过" in l: c = "lw"  # 重试重整及隐患检查发现着为橙黄色 text (lw)
                    parts.append(f'<div class="{c}">{_h.escape(l)}</div>')  # 逃逸日志文本内容后包裹带有特定 CSS 着色类名的 HTML div 标签并写入列表
                log_ph.markdown(  # 在右侧控制台占位符渲染上面整理好的 HTML 终端面板，注入 styles.py 中定义的 .hlog 类
                    f'<div class="hlog">'  # 外层深色终端主盒子
                    f'<div class="lt">📄 {_h.escape(_name)} | 🤖 AGENT THINKING...</div>'  # 终端最上方标题行
                    f'{"".join(parts)}</div>',  # 拼接 30 行日志的 innerHTML 元素
                    unsafe_allow_html=True)  # 开启 HTML 安全解析以实现极客科技风

            hlog(f">>> 收到任务: {uploaded.name}")  # 写入终端第一行首任务提示

            _orig = sys.stdout  # 缓存并保存系统默认的常规标准输出流对象
            _orig_err = sys.stderr  # 缓存保存系统默认的标准错误流对象
            result = {"ocr": None, "data": None}  # 初始化存放本张图片最终产出的 OCR 原始数据和语义 JSON 对象的字典
            _sp = {"Plan":10,"Perceive":25,"Reason":50,"Reflect":70,"Act":85,"Report":98}  # 定义智能体生命周期对应左栏总进度条百分比位置的映射字典
            _sc = {"Plan":"规划","Perceive":"感知","Reason":"推理","Reflect":"反思","Act":"执行","Report":"总结"}  # 定义左栏进度文字对应的中文描述字典

            class Cap(io.TextIOBase):  # 自定义继承自 TextIOBase 的重定向输出类，用于捕获 print 并输出到 hlog 中
                def write(self, s):  # 覆写 write 方法
                    s = s.strip()  # 去除空格
                    if s:  # 若字符串非空
                        for line in s.split("\n"):  # 按照换行符分割可能连贯的多条输出日志
                            line = line.strip()  # 去除行内多余空格
                            if line:  # 判断行非空
                                hlog(line)  # 将当前输出输出行送入 hlog 闭包函数，刷新右侧黑客思考控制台的 UI 面板
                                for k, p in _sp.items():  # 检索当前日志行内是否包含控制左侧进度条波动的阶段状态特征字符串
                                    if f"Agent {k}" in line:  # 如检测到 "Agent Perceive" 等特征字
                                        progress.progress(p)  # 刷新左侧总进度条至对应的百分比刻度
                                        status_text.caption(f"[{idx+1}/{len(final_files)}] {_sc[k]}...")  # 刷新左侧的阶段中文状态字
                        _dt = time.time() - _t0_img  # 计算执行时长
                        _mm, _ss = divmod(int(_dt), 60)  # 转成分秒
                        print(f"[{_mm:02d}:{_ss:02d}] {s}", file=_orig_err, flush=True)  # 在后台的标准错误输出控制台照常输出，保留日志备份
                    return len(s) if s else 0  # 返回写入的数据字符长度
                def flush(self): pass  # 覆写 flush 空实现以防框架调用抛出未定义异常

            def prog_cb(pct, msg):  # 定义提供给底层 PaddleOCR 与 AI 大模型的精准小进度更新回调函数
                progress.progress(pct)  # 强制波动左侧主进度条到精确的百分比值 pct
                _dt = time.time() - _t0_img  # 计算时长
                _mm, _ss = divmod(int(_dt), 60)  # 转成分秒
                status_text.caption(f"[{idx+1}/{len(final_files)}] {msg} ({pct}%) {_mm:02d}:{_ss:02d}")  # 精准呈现当前底层的动作及时间信息

            # 屏蔽后台线程调用 Streamlit 时触发的 ScriptRunContext 警告日志，防止污染控制台与终端日志
            import logging
            for name in list(logging.root.manager.loggerDict.keys()):
                if "streamlit" in name:
                    logging.getLogger(name).setLevel(logging.ERROR)

            sys.stdout = Cap()  # 重定向 python 全局的标准输出流 sys.stdout 至我们自定义的 Cap 捕获器类
            try:  # 开启安全防崩溃守护
                ocr_text, structured = agent.run(save_path, progress_callback=prog_cb)  # 执行 Agent 对象的 run 算法以进行核心安全自检工作
                result["ocr"], result["data"] = ocr_text, structured  # 将正常运行完毕得出的结果存入 result 中
            except Exception as e:  # 若处理过程中不幸崩溃
                hlog(f"❌ {e}")  # 往黑客控制台输出带叉的红色错误诊断信息
            finally:  # 最终清理复原
                sys.stdout = _orig  # 还原全局标准输出流，避免污染系统的其他输出流导致页面假死崩溃

            progress.progress(100)  # 处理完毕，强制打满左侧主进度条
            status_text.caption(f"[{idx+1}/{len(final_files)}] ✅ 完成")  # 提示本张图片已处理完成
            # 将占据左侧大量垂直空间的原图收纳归档进一个默认折叠的 Expander Panel 中，释放视口空间
            with img_placeholder:  # 进入原图临时占位符
                with st.expander("🖼️ 查看原图", expanded=False):  # 渲染折叠折叠菜单，默认关闭
                    st.image(save_path, caption=uploaded.name, use_container_width=True)  # 在折叠内提供原图预览以备复查

            # 左栏下方：利用组件库渲染生成的结构化安全结论
            with col_r:  # 进入左栏上下文
                if result["data"]:  # 判断是否成功获得了规范的数据行对象 d
                    d = result["data"]  # 缓存解包
                    st.session_state.results.append(result)  # 将本次识别结果插入全局缓存列表 results，供 Tab2 或重载后看板使用

                    # KPI 行 + 审批建议组件渲染
                    render_ticket_kpis(d)  # 渲染由票号、风险评估、浓度监控及智能意见组成的摘要排布面板

                    # OCR 识别原文折叠栏（备用，用于人工进行文字核对）
                    if result["ocr"]:  # 判断原文非空
                        with st.expander("📝 OCR 识别原文"):  # 新建 OCR 原文折叠组件
                            raw = getattr(AgentTools, "_last_ocr_raw", "")  # 尝试从 Agent 工具类中拉取刚才未经过任何格式重构的原始 OCR 字符串
                            ocr_out = result["ocr"].split("\n---\n")[-1] if "\n---\n" in result["ocr"] else result["ocr"]  # 截取坐标文字
                            is_html = "<table" in ocr_out.lower()  # 判定是否属于表格结构
                            if raw:  # 若原始无偏移文本有效
                                st.code(raw, language=None, line_numbers=True)  # 以纯文本代码块渲染这串文字，并开启行号
                            elif is_html:  # 若是网页表格结构
                                st.markdown(ocr_out, unsafe_allow_html=True)  # 渲染表格并启用标签解析
                            else:  # 若为其他扁平文字
                                st.text(ocr_out)  # 纯文本直接输出

                    # 作业票异常隐患详情清单（折叠展开，只有在存在隐患时才被渲染展示）
                    if d.issues:  # 判断存在隐患
                        with st.expander(f"⚠️ 隐患明细 ({len(d.issues)})", expanded=True):  # 新建默认强行展开的隐患折叠卡片栏
                            # 安全措施未落实明细收集
                            unimpl = [m for m in d.safety_measures if not m.implemented]  # 过滤寻找所有被勾选或圈选为“未落实(×)”的安全防范措施项
                            if unimpl:  # 若存在不合规的未落实项
                                st.markdown("**安全措施未落实：**")  # 渲染子分类小标题
                                for m in unimpl:  # 遍历这些不合规条目
                                    st.markdown(f"  🔴 第{m.measure_id}项 `{m.description}` — 标记为**未落实×**")  # 红色点点标识具体未落实的条款名称和编号
                            # 气体浓度超出安全限值指标检查
                            conc_high = [(i, v) for i, v in enumerate(d.gas_concentration) if v > 0]  # 检查所有测爆检测数值是否大于 0% 浓度限值
                            if conc_high:  # 若发现超标气体残留
                                st.markdown("**浓度异常：**")  # 渲染子小标题
                                for i, v in conc_high:  # 遍历超标指标
                                    st.markdown(f"  🟡 第{i+1}次检测 `{v}%` — 超过0%安全限值阈值")  # 黄色高亮显示第几次检测超标及具体数值
                            # 其它杂项隐患（如时间过期、无签名、错漏字等）
                            for issue in d.issues:  # 遍历其他的隐患列表
                                reason = issue.raw_text or "OCR识别为异常标记"  # 获取隐患发生定位的上下文文本说明
                                st.markdown(f"  ⚠️ **{issue.item_name}** — {reason}")  # 黄色三角警告图标标识具体异常

        # 多图批量上传时的统计与大汇总组件排版
        if len(st.session_state.results) > 1:  # 检查如果刚刚批量处理了多张图片作业票
            abn = sum(1 for r in st.session_state.results if r["data"].has_abnormal)  # 统计带有异常问题的危险作业票数量
            st.markdown(f"**📊 汇总** {len(st.session_state.results)}张 {badge('正常'+str(len(st.session_state.results)-abn), 'ok')} {badge('隐患'+str(abn), 'err' if abn else 'ok')}", unsafe_allow_html=True)  # 渲染大汇总结果，附带对应颜色的 HTML 徽标
            rows = [{"票号": r["data"].ticket_id, "场站": r["data"].station_name, "状态": "有隐患" if r["data"].has_abnormal else "正常", "风险": r["data"].risk_level or "-", "审批": r["data"].approval_status or "-"} for r in st.session_state.results]  # 整理成 Pandas DataFrame 要求的数据格式
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=min(len(rows)*28+30, 200))  # 渲染精美的数据表报表汇总视图


# ==================== Tab 2: 历史作业票数据总看板与数据删除流 ====================
with tab2:  # 进入第二个 Tab 页签渲染上下文环境
    import sqlite3  # 引入本地嵌入式数据库驱动模块 SQLite
    db_path = os.path.join(os.path.dirname(__file__), "security_data.db")  # 定位并合成数据保存的目标数据库路径
    _del_pwd = _cfg.get("delete_password", "123")  # 从配置字典中提取用于物理删除的安全验证码（默认 123）

    if not os.path.exists(db_path):  # 检查物理数据库文件是否尚未建立
        st.caption("📭 暂无数据，处理作业票后自动保存。")  # 若无文件，显示灰色提示词说明
    else:  # 若数据库文件已建立并可用
        conn = None  # 初始化连接变量为 None
        try:  # 开启数据库异常监视防护
            conn = sqlite3.connect(db_path)  # 建立与 security_data.db 数据库的连接句柄
            try:  # 开启首次数据拉取
                rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,approval_opinion,risk_level,approval_status,approval_level,created_at,image_path FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()  # 降序查询所有安全监督归档行
            except Exception:  # 若查询发生字段异常（例如旧库结构版本不一致）
                try:  # 尝试兼容查询
                    rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,approval_opinion,risk_level,approval_status,approval_level,created_at,image_path FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()  # 降序查询
                except Exception:  # 二次失败说明库表损坏
                    rows_db = []  # 重置数据列表为空

            total = len(rows_db)  # 计算库内已存储的作业票总数记录行数
            abn_cnt = sum(1 for r in rows_db if r[5])  # 计算字段 has_abnormal(位置5) 值为真的高危隐患记录数

            # 全局指标大横幅卡片组渲染展示
            render_kpi_row([  # 调用 KPI 卡片组件展示看板四大核心总统计数
                ("总票数", str(total), ""),  # 数据库存储的历史作业票总量
                ("有隐患", str(abn_cnt), "#d6131c" if abn_cnt else "#059669"),  # 发现隐患数（有隐患红，无隐患绿）
                ("正常", str(total - abn_cnt), "#059669"),  # 合规正常通过的作业票数
                ("隐患率", f"{abn_cnt/total*100:.0f}%" if total else "0%", ""),  # 隐患发生率百分比
            ])  # 结束指标卡片定义

            # 统计高频高危隐患发生频次的前五项（Top 5 Rank）
            issue_counter = {}  # 初始化隐患频次统计词典
            try:  # 开启隐患字段反序列化解析过程防护
                for (ij,) in conn.execute("SELECT issues_json FROM hse_fire_work_tickets WHERE has_abnormal=1").fetchall():  # 获取所有异常作业票的 issues_json 隐患详情字段数据
                    if ij:  # 确保字段非空
                        for item in json.loads(ij):  # 反序列化隐患列表，遍历每一项问题
                            n = item.get("item_name", "未知")  # 获取问题发生的违规项目名称，默认未知
                            issue_counter[n] = issue_counter.get(n, 0) + 1  # 频次计数累加 1
            except Exception:  # 捕获解析过程异常
                pass  # 安全跳过频次统计

            if issue_counter:  # 若发现至少一项隐患记录频次
                top5 = sorted(issue_counter.items(), key=lambda x: -x[1])[:5]  # 按发生次数进行降序排序，截取前 5 位高危项
                render_kpi_row([(name, f"{count}次", "#d6131c") for name, count in top5])  # 渲染一整排高频隐患红色高亮警告卡片组
        finally:  # 最终关闭清理
            if conn:  # 判断连接有效
                conn.close()  # 回收数据库句柄连接资源并归还系统
                conn = None  # 置空变量

        # 历史记录确认物理删除提示弹窗 (Dialog)
        if st.session_state.delete_id:  # 判断当前是否已触发了对某一条 ID 记录行的删除行为
            @st.dialog("🗑️ 确认删除", width="small")  # 使用 Streamlit 官方自带的 dialog 模态弹框装饰器，宽度为小
            def confirm_delete():  # 定义弹框内部的交互函数
                st.warning(f"确定要永久删除记录 **#{st.session_state.delete_id}** 吗？")  # 渲染安全警告提示语
                pwd = st.text_input("请输入删除权限验证码", type="password")  # 渲染验证码输入框，并使用密码字符隐藏
                fc1, fc2 = st.columns(2)  # 对话框内按钮排版左右划分
                with fc1:  # 左栏
                    if st.button("✅ 确认", type="primary", use_container_width=True):  # 确认按键，设为红色主格按键样式
                        if pwd == _del_pwd:  # 判断输入的密码与配置的 delete_password 是否一致
                            try:  # 启动删除流程防崩溃
                                c2 = sqlite3.connect(db_path)  # 重新建立独立的 SQLite 删除通道连接句柄
                                c2.execute("DELETE FROM hse_fire_work_tickets WHERE id=?", (st.session_state.delete_id,))  # 执行 DELETE 物理删除删除数据库对应主键行
                                c2.commit()  # 提交执行以使事务在磁盘生效永久固化
                            except Exception as e:  # 捕获可能出现的报错情况
                                st.error(f"删除失败: {e}")  # 弹红色错误
                            finally:  # 清理
                                c2.close()  # 安全关闭删除通道
                            st.session_state.delete_id = None  # 复位清空删除 ID 状态变量
                            st.rerun()  # 触发 Streamlit 重绘刷新，重置看板记录列表
                        else: st.error("验证码错误，请重试")  # 提示密码不匹配
                with fc2:  # 右栏
                    if st.button("❌ 取消", use_container_width=True):  # 取消删除按键
                        st.session_state.delete_id = None  # 仅清空删除 ID，不执行任何数据库指令
                        st.rerun()  # 触发重绘重写关闭模态弹窗
            confirm_delete()  # 执行该弹窗组件函数

        # 数据表单多维搜索框（基于原生 Streamlit Form 封装以降低重绘频次，提高输入流畅度）
        with st.form("search_form", clear_on_submit=False):  # 创建搜索表单
            sf1, sf2 = st.columns([5, 1])  # 比例为 5:1 的检索输入布局划分
            with sf1:  # 检索列
                search = st.text_input("🔍 搜索票号", placeholder="输入票号模糊查询...", label_visibility="collapsed")  # 渲染搜索框输入，隐藏顶部的自带 Label 提示以防破坏紧凑感
            with sf2:  # 按钮列
                st.form_submit_button("🔍 搜索", use_container_width=True)  # 渲染触发提交并检索的表单提交按键

        # 看板核心列表：遍历渲染历史记录条目列表
        for row in rows_db:  # 遍历从数据库查出的所有历史作业票记录元组
            rid = row[0]  # 提取数据库自增唯一 ID 号 rid
            ticket = row[1]  # 提取历史识别所得票号 ticket_id
            station = row[2]  # 提取场站中文名称 station_name
            worker = row[3]  # 提取填表人姓名/工号 worker_id
            date = row[4]  # 提取自检日期数据 check_date
            abnormal = row[5]  # 提取是否存在隐患的布尔标记 has_abnormal (0/1)
            opinion = row[6]  # 提取智能决策审核意见 approval_opinion
            risk = row[7]  # 提取安全风险级别评估文字 risk_level
            ap_status = row[8]  # 提取智能审批流的当前状态
            ap_level = row[9]  # 提取智能审批审批人的建议级别
            created = row[10]  # 提取数据库记录插入时间戳字符串 created_at
            img_path = row[11]  # 提取原始作业票图片在本地硬盘的实际存放物理路径
            
            if search and search.lower() not in (ticket or "").lower():  # 检查如果开启了搜索框检索，且当前行票号并不匹配所查文字
                continue  # 跳过这一行，不予以渲染展示
                
            icon = "🚨" if abnormal else "✅"  # 根据有无隐患为折叠面板的摘要头配置表情标志（异常为红色警铃，正常为绿色对勾）
            badge_md = render_record_badge(risk, abnormal)  # 根据风险等级使用组件返回彩色 markdown 字体片段，如 " | :red[重大]"

            cm, cd = st.columns([9, 1])  # 将这一行分为 9:1 的两大部分列容器
            with cm:  # 记录信息大折叠面板列
                with st.expander(f"{icon} #{rid} | {ticket} | {station} | {date}{badge_md}", expanded=False):  # 新建默认折叠的 Expander 面板，头包含票号场站及彩色风险级标签
                    ca, cb = st.columns(2)  # 折叠内部左右 1:1 分栏以对齐排版
                    with ca: st.markdown(f"**票号** {ticket}  \n**场站** {station}  \n**动火人** {worker}  \n**日期** {date}")  # 左侧输出识别提取的基本信息
                    with cb:  # 右侧栏
                        st.markdown(f"**状态** {'🔴 有隐患' if abnormal else '🟢 正常'}")  # 高亮输出隐患等级状态
                        if risk: st.markdown(f"**风险** {risk}")  # 输出风险评级数据
                        if ap_status: st.markdown(f"**审批** {ap_status}")  # 输出只能审批意见数据
                        st.caption(f"处理: {created}")  # 输出数据处理入库时间
                        if opinion: st.caption(f"建议: {opinion}")  # 渲染展现大模型的详细建议说明
                    
                    # 看板详情内部的图片查看及导出下载功能
                    if img_path and os.path.exists(img_path):  # 校验该本地图片路径有效并且磁盘物理文件确实完好存在
                        dc1, dc2 = st.columns(2)  # 在底部开出左右两个平分按钮
                        with dc1:  # 左按钮：查看原图弹窗动作
                            if st.button("🖼️ 查看原图", key=f"img_{rid}", use_container_width=True):  # 渲染查看大图的按钮，附加 rid 后缀 key
                                @st.dialog("原图", width="large")  # 新建查看原图大尺寸 dialog 弹窗组件，设定宽度为大模式
                                def show_orig_img(_path=img_path, _name=ticket):  # 弹窗渲染内部函数
                                    st.image(_path, caption=_name, use_container_width=True)  # 在弹窗居中展示该本地物理大图原图
                                show_orig_img()  # 执行弹窗渲染
                        with dc2:  # 右按钮：直连导出下载该原图到用户个人电脑
                            ext = os.path.splitext(img_path)[1] or ".png"  # 从路径中拆分提取图片的后缀格式，默认使用 .png
                            dl_name = f"{ticket or f'作业票_{rid}'}{ext}"  # 合成下载文件展示的文件名，首选票号命名
                            with open(img_path, "rb") as f:  # 以二进制制度方式打开对应的本地物理大图原图
                                img_bytes = f.read()  # 读取全部大图字节数据流
                            st.download_button("⬇️ 下载原图", data=img_bytes, file_name=dl_name, mime="image/png", key=f"dl_{rid}", use_container_width=True)  # 调用 Streamlit download_button 实现将原图流通过浏览器直下载保存
                    else:  # 若物理图片发生丢失或路径发生破坏
                        st.caption("原图不可用")  # 显示灰色字说明原图已丢失损坏
            with cd:  # 右侧独立的红色垃圾桶物理删除动作列
                st.markdown("<div style='padding-top:18px'></div>", unsafe_allow_html=True)  # 注入空的 CSS padding 高度以对齐左侧大折叠卡片的垂直居中高度
                if st.button("🗑️", key=f"del_{rid}", help=f"删除 #{rid}"):  # 渲染垃圾桶按钮，悬停提示删除该 rid 条目
                    st.session_state.delete_id = rid  # 设置删除状态标志为当前行 rid
                    st.rerun()  # 触发 Streamlit 重绘刷新，在顶部直接呼出安全删除验证 dialog 模态弹框
