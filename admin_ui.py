# -*- coding: utf-8 -*-
# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
"""
数字化安全监督员 - 管理 / 测试页
由 frontend.py 路由加载（url_path=admin），勿单独 st.set_page_config。
"""

import io  # 导入数据流模块用于截取日志数据
import sys  # 导入系统接口模块用于修改标准输出流
import os  # 导入操作系统接口模块用于处理文件路径及环境变量
import time  # 导入时间时间戳模块用于生成唯一图名及模拟延时
import json  # 导入 JSON 数据解析库以加载/保存本地运行配置参数
import warnings  # 导入警告过滤模块以屏蔽第三方库的多余警告信息
warnings.filterwarnings("ignore", category=UserWarning, module="paddle")  # 忽略 Paddle 内部关于 ccache 等非致命性用户警告

import streamlit as st  # 导入 Streamlit 前端渲染框架
import pandas as pd  # 导入 Pandas 数据分析库用于在汇总页展示表格报表
from styles import CUSTOM_CSS  # 从 styles 导入精美的全局科技风样式定义字符串
from components import (  # 从原子组件库中引入状态徽章、KPI 统计栏、审批显示及通知写入等组件
    badge, render_kpi_row, render_ticket_kpis,
    render_record_badge,
)  # 结束组件解包导入

# ---- 配置（优先环境变量，其次 config.json） ----
from agent_core import load_config  # 从智能体核心层中引入加载配置的工具函数
_cfg = load_config()  # 执行配置加载，读取字典数据并存入局部 _cfg 变量中
_ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()  # 从 VERSION 文件读取当前小版本号并剥离换行

# ---- 自定义主题 ----
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)  # 注入全局自定义的 CSS 样式代码到本页面以获得顶级科技白底风外观

# ---- 侧栏展开 + 日志贴底（仅注入一次，避免每次 rerun 叠加 setInterval 越点越卡）----
# 注意：不要再移动 stSidebarHeader，否则会把 frontend 的 st.logo 顶到 HSE 标题下面
st.html("""
<script>
(function() {
    var w = window.parent || window;
    if (w.__hseAdminSidebarInit) return;
    w.__hseAdminSidebarInit = true;
    var root = w.document;

    function tryExpand() {
        var btn = root.querySelector('[data-testid="stExpandSidebarButton"]');
        if (btn) { btn.click(); return true; }
        return false;
    }
    setTimeout(function() {
        if (!tryExpand()) setTimeout(tryExpand, 500);
    }, 300);

    function scrollLogs() {
        root.querySelectorAll('.hlog').forEach(function(log) {
            var lastHeight = log.getAttribute('data-last-height') || 0;
            var currentHeight = log.scrollHeight;
            if (currentHeight !== parseInt(lastHeight)) {
                log.setAttribute('data-last-height', currentHeight);
                log.scrollTop = log.scrollHeight;
            }
        });
    }
    setInterval(scrollLogs, 800);
})();
</script>
""", unsafe_allow_javascript=True)

# ---- Session State (全局会话状态维护) ----
if "results" not in st.session_state: st.session_state.results = []  # 若 results 未初始化，则初始化为一个空的分析结果列表
if "delete_id" not in st.session_state: st.session_state.delete_id = None  # 初始化记录待删除数据 ID 标识变量为空
if "pending_files" not in st.session_state: st.session_state.pending_files = None  # 初始化暂存准备上传的作业图片文件句柄为空
if "show_uploader" not in st.session_state: st.session_state.show_uploader = False  # 初始化控制上传组件面板的显示显示标记为否
if "upload_done" not in st.session_state: st.session_state.upload_done = False  # 初始化当前上传操作是否完全完成的标记为否
if "uploader_key_suffix" not in st.session_state: st.session_state.uploader_key_suffix = 0  # 初始化控制上传选择器动态 Key 变化的序号，用于清空图片缓存
if "selected_ticket_type" not in st.session_state: st.session_state.selected_ticket_type = "带气作业票"


# ---- 侧边栏配置面板（Logo 已在 frontend 最上方 st.logo）----
with st.sidebar:  # 进入侧边栏渲染上下文本环境
    # API 基本信息配置
    api_key = st.text_input("API Key", _cfg.get("api_key", ""), type="password")  # 渲染主大模型密钥输入框，设定为密码类型隐藏字符
    base_url = st.text_input("API URL", _cfg.get("base_url", ""))  # 渲染主大模型 API 服务域名路由基地址输入框
    model_name = st.text_input(
        "模型",
        _cfg.get("model_name", ""),
        help="DeepSeek 官方仅支持：deepseek-v4-flash 或 deepseek-v4-pro（全小写，勿写 DeepSeek-V4-Flash）",
    )  # 渲染主推理大模型的模型具体别名输入框

    ocr_mode = "cluster"  # 现已固定为坐标聚类模式，移除冗余的 UI 选项

    # OCR 底层推理引擎选择
    _ocr_engines = {  # 映射中文引擎别名到底层引擎代码字典
        "本地 PaddleOCR（带坐标）": "paddleocr",
        "视觉大模型": "vision",
    }  # 结束引擎字典定义
    _saved_engine = _cfg.get("ocr_engine", "paddleocr")
    _engine_values = list(_ocr_engines.values())
    _default_engine_idx = _engine_values.index(_saved_engine) if _saved_engine in _engine_values else 0
    ocr_engine_label = st.selectbox(  # 渲染下拉单选框以供切换核心 OCR 技术选型
        "🔍 OCR 引擎",
        list(_ocr_engines.keys()),  # 传入中文引擎选项列表
        index=_default_engine_idx,  # 动态设置默认索引
        help="本地 PaddleOCR：默认，本地推理，输出带坐标，支持责任人定位\n"
             "视觉大模型：调用 VL 模型直接读图识别，一步完成结构+文字+符号，不支持坐标定位",  # 气泡说明
    )  # 结束下拉框渲染
    ocr_engine = _ocr_engines[ocr_engine_label]  # 从字典提取选定的底层引擎处理类型

    # OCR 推理设备选择（CPU / GPU）
    _ocr_devices = {  # 映射中文设备别名到底层设备代码字典
        "CPU": "cpu",
        "GPU 加速（默认）": "gpu",
    }  # 结束设备字典定义
    _saved_device = _cfg.get("ocr_device", "gpu")
    _device_values = list(_ocr_devices.values())
    _default_device_idx = _device_values.index(_saved_device) if _saved_device in _device_values else 0
    ocr_device_label = st.selectbox(  # 渲染下拉单选框以供切换 OCR 推理硬件设备
        "⚡ OCR 推理设备",
        list(_ocr_devices.keys()),  # 传入中文设备选项列表
        index=_default_device_idx,  # 动态设置默认索引
        help="CPU：兼容性最佳，无需额外依赖\nGPU 加速：需安装 paddlepaddle-gpu，推理速度提升 5~10 倍",  # 气泡帮助说明
    )  # 结束下拉框渲染
    ocr_device = _ocr_devices[ocr_device_label]  # 从映射字典中提取当前选中的底层设备参数
    if ocr_device == "gpu":  # 如果选定为 GPU 模式
        try:  # 尝试检测 GPU 可用性
            import paddle as _pd  # 临时导入 paddle
            if not _pd.device.is_compiled_with_cuda():  # 检测是否安装了 GPU 版
                st.caption("⚠️ 当前安装的是 CPU 版 PaddlePaddle，GPU 不可用，将自动回退到 CPU")  # 警告 GPU 不可用
                ocr_device = "cpu"  # 强制将设备降级回 cpu
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
        help="钉钉 AI 表格 MCP Streamable HTTP 地址。人工介入（待审批/已驳回）经此推送至钉钉 AI 表格，并由表格自动化发消息。",
        key="_dd",  # 绑定状态 key
        placeholder="https://mcp-gw.dingtalk.com/server/...?key=...",  # 示例占位字符
    )  # 结束文本框定义
    if not dingtalk_mcp_url:  # 检查如果钉钉多维表 MCP 地址为空
        st.markdown(
            "<div style='font-size: 11.5px; color: #D97706; background-color: rgba(217, 119, 6, 0.08); "
            "border: 1px solid rgba(217, 119, 6, 0.2); padding: 8px; border-radius: 6px; margin-top: 4px; line-height: 1.4;'>"
            "⚠️ 未配置钉钉 MCP 地址：无法推送钉钉 AI 表格，人工介入链路不可用。请设置后点击「💾 保存设置」</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("人工介入 = 经 MCP 推送钉钉 AI 表格（待审批/已驳回由主管在钉钉侧处理）")

    # ---- PaddleOCR 四模型参数（钉钉 MCP 下方，可保存到 config.json） ----
    from ocr import DEFAULT_OCR_PARAMS, merge_ocr_params  # 默认参数与合并工具
    _ocr_saved = merge_ocr_params(_cfg.get("ocr_params") if isinstance(_cfg.get("ocr_params"), dict) else None)

    def _sel_idx(options, value, default_idx=0):
        try:
            return options.index(value)
        except ValueError:
            return default_idx

    st.markdown("**🔤 PaddleOCR 四模型参数**")
    st.caption("本地引擎生效；保存后写入 config.json，下次启动自动加载。")

    # ---- ocr9 纠错记忆（入库即生效，无需导出）----
    from ocr import ocr9_memory_status_detail
    from datetime import datetime as _dt

    _mem_info = ocr9_memory_status_detail()  # 每次侧栏渲染读盘，不缓存
    _ocr9_n = int(_mem_info.get("n_hash") or 0)
    _ocr9_mem_path = str(_mem_info.get("path") or "")
    _ocr9_ns = int(_mem_info.get("n_sample") or 0)
    _ocr9_latest = (_mem_info.get("latest_updated_at") or "").strip()
    try:
        _ocr9_mtime = (
            _dt.fromtimestamp(float(_mem_info.get("mtime") or 0)).strftime("%m-%d %H:%M:%S")
            if _mem_info.get("mtime")
            else "-"
        )
    except Exception:
        _ocr9_mtime = "-"
    # 条数放在 caption，避免 checkbox 固定 key 时标题看起来「不刷新」
    _use_ocr9_mem = st.checkbox(
        "使用 ocr9 纠错记忆",
        value=bool(_ocr9_n),
        disabled=not bool(_ocr9_n),
        key="_use_ocr9_memory",
        help="在「OCR文字训练」改真值并入库后，按裁剪图图像哈希命中时替换。"
             "同一框重复入库只更新真值、哈希条数不增加。"
             "禁止 t:文本硬改 / 字符串替换兜底。",
    )
    if _ocr9_n:
        if _use_ocr9_mem:
            os.environ.pop("OCR9_MEMORY_OFF", None)
            st.caption(
                f"已启用 · **{_ocr9_n}** 个哈希"
                + (f"（约 {_ocr9_ns} 次入库样本）" if _ocr9_ns else "")
                + f" · 文件 `{os.path.basename(_ocr9_mem_path)}` mtime {_ocr9_mtime}"
                + (f" · 最新 {_ocr9_latest}" if _ocr9_latest else "")
            )
            st.caption(
                "说明：数字=不同图像哈希数，不是入库点击次数；"
                "同一检测框重复入库会覆盖，条数不变。切页/刷新后更新。"
            )
        else:
            os.environ["OCR9_MEMORY_OFF"] = "1"
            st.caption(f"已关闭纠错记忆（本次会话）· 磁盘仍有 {_ocr9_n} 个哈希")
    else:
        os.environ.pop("OCR9_MEMORY_OFF", None)
        st.caption("暂无哈希记忆：到 OCR文字训练 入库即可。")

    with st.expander("展开设置 det / rec / 行方向 / 页方向", expanded=False):
        # ② 文本检测
        st.markdown("`PP-OCRv6_*_det` 文本检测")
        _det_models = [
            "PP-OCRv6_medium_det",
            "PP-OCRv6_small_det",
            "PP-OCRv6_tiny_det",
        ]
        ocr_det_model = st.selectbox(
            "检测模型",
            _det_models,
            index=_sel_idx(_det_models, _ocr_saved.get("text_detection_model_name"), 0),
            key="_ocr_det_model",
            help="找文字框。medium 均衡；small/tiny 更快、精度可能下降。",
        )
        ocr_det_thresh = st.number_input(
            "像素阈值 text_det_thresh",
            min_value=0.05, max_value=0.95, step=0.05,
            value=float(_ocr_saved.get("text_det_thresh", 0.3)),
            key="_ocr_det_thresh",
            help="像素级文字概率阈值。降低→淡字更易检出；升高→更干净。默认约 0.3。",
        )
        ocr_det_box_thresh = st.number_input(
            "框阈值 text_det_box_thresh",
            min_value=0.05, max_value=0.95, step=0.05,
            value=float(_ocr_saved.get("text_det_box_thresh", 0.2)),
            key="_ocr_det_box",
            help="文本框置信度。降低→少漏小字/手写√×（推荐 0.2~0.4）；升高→少误检。",
        )
        ocr_det_unclip = st.number_input(
            "框扩张 text_det_unclip_ratio",
            min_value=0.5, max_value=3.0, step=0.1,
            value=float(_ocr_saved.get("text_det_unclip_ratio", 1.5)),
            key="_ocr_det_unclip",
            help="文本框扩张系数。增大可减少切字；过大可能粘连相邻字。默认约 1.5。",
        )

        st.markdown("---")
        # ④ 文本识别
        st.markdown("`PP-OCRv6_*_rec` 文本识别")
        _rec_models = [
            "PP-OCRv6_medium_rec",
            "PP-OCRv6_small_rec",
            "PP-OCRv6_tiny_rec",
        ]
        ocr_rec_model = st.selectbox(
            "识别模型",
            _rec_models,
            index=_sel_idx(_rec_models, _ocr_saved.get("text_recognition_model_name"), 0),
            key="_ocr_rec_model",
            help="认字模型，建议与检测同档（medium/small/tiny）。",
        )
        ocr_rec_score = st.number_input(
            "置信度阈值 text_rec_score_thresh",
            min_value=0.0, max_value=0.99, step=0.05,
            value=float(_ocr_saved.get("text_rec_score_thresh", 0.1)),
            key="_ocr_rec_score",
            help="低于该分的识别结果丢弃。手写建议 0.0~0.1；提高会更干净但易丢字。",
        )

        st.markdown("---")
        # ③ 文本行方向
        st.markdown("`PP-LCNet_*_textline_ori` 文本行方向")
        ocr_use_textline_ori = st.checkbox(
            "启用文本行方向分类",
            value=bool(_ocr_saved.get("use_textline_orientation", True)),
            key="_ocr_use_tl_ori",
            help="对每个文本行判断 0°/180°。票面已对齐时可关闭以提速。",
        )
        _tl_models = [
            "PP-LCNet_x1_0_textline_ori",
            "PP-LCNet_x0_25_textline_ori",
        ]
        ocr_textline_model = st.selectbox(
            "行方向模型",
            _tl_models,
            index=_sel_idx(_tl_models, _ocr_saved.get("textline_orientation_model_name"), 0),
            key="_ocr_tl_model",
            help="x1_0 默认；x0_25 更轻量。",
            disabled=not ocr_use_textline_ori,
        )

        st.markdown("---")
        # ① 文档整页方向
        st.markdown("`PP-LCNet_x1_0_doc_ori` 文档整页方向")
        ocr_use_doc_ori = st.checkbox(
            "启用整页方向分类",
            value=bool(_ocr_saved.get("use_doc_orientation_classify", True)),
            key="_ocr_use_doc_ori",
            help="判断整图 0°/90°/180°/270°。手机随意拍时开启；已摆正可关闭提速。",
        )
        _doc_models = ["PP-LCNet_x1_0_doc_ori"]
        ocr_doc_model = st.selectbox(
            "页方向模型",
            _doc_models,
            index=_sel_idx(_doc_models, _ocr_saved.get("doc_orientation_classify_model_name"), 0),
            key="_ocr_doc_model",
            help="默认 PP-LCNet_x1_0_doc_ori。",
            disabled=not ocr_use_doc_ori,
        )
        ocr_use_unwarp = st.checkbox(
            "启用文档展平 UVDoc",
            value=bool(_ocr_saved.get("use_doc_unwarping", False)),
            key="_ocr_use_unwarp",
            help="弯曲纸面矫正。平面扫描/已对齐作业票建议关闭（更快）。",
        )

    ocr_params = merge_ocr_params({
        "text_detection_model_name": ocr_det_model,
        "text_det_thresh": float(ocr_det_thresh),
        "text_det_box_thresh": float(ocr_det_box_thresh),
        "text_det_unclip_ratio": float(ocr_det_unclip),
        "text_recognition_model_name": ocr_rec_model,
        "text_rec_score_thresh": float(ocr_rec_score),
        "use_textline_orientation": bool(ocr_use_textline_ori),
        "textline_orientation_model_name": ocr_textline_model,
        "use_doc_orientation_classify": bool(ocr_use_doc_ori),
        "doc_orientation_classify_model_name": ocr_doc_model,
        "use_doc_unwarping": bool(ocr_use_unwarp),
    })

    # 侧栏当前参数 → 会话运行时配置（用户页自动同步，无需先点保存）
    from process_helpers import publish_runtime_config
    _runtime = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": model_name,
        "vision_api_key": vision_api_key,
        "vision_base_url": vision_base_url,
        "vision_model_name": vision_model_name,
        "proxy": proxy_url if proxy_enabled else "",
        "dingtalk_mcp_url": dingtalk_mcp_url or st.session_state.get("_dd", _cfg.get("dingtalk_mcp_url", "")),
        "ocr_engine": ocr_engine,
        "ocr_device": ocr_device,
        "ocr_mode": ocr_mode,
        "ocr_params": ocr_params,
    }
    publish_runtime_config(_runtime)

    # 保存配置按钮逻辑段
    st.markdown("---")  # 渲染第三条侧边栏分割横线
    st.caption("侧栏参数实时同步到「提交作业票」用户页；点保存写入 config.json。")
    if st.button("💾 保存设置", use_container_width=True):  # 渲染一个拉平填满侧栏的保存设置按键
        _cfg["api_key"] = api_key  # 将当前输入的 API 密钥存入配置缓存
        _cfg["base_url"] = base_url  # 将当前输入的 URL 写入配置缓存
        _cfg["model_name"] = model_name  # 将当前输入的模型别名写入配置缓存
        _cfg["vision_api_key"] = vision_api_key  # 保存视觉模型的密钥参数
        _cfg["vision_base_url"] = vision_base_url  # 保存视觉模型的基础 URL 参数
        _cfg["vision_model_name"] = vision_model_name  # 保存视觉模型的名字参数
        _cfg["proxy"] = proxy_url if proxy_enabled else ""  # 根据代理勾选状态写入代理字符串或清空配置
        _cfg["dingtalk_mcp_url"] = st.session_state.get("_dd", _cfg.get("dingtalk_mcp_url", ""))  # 保存写入 of 钉钉 MCP 数据库网关地址
        _cfg["ocr_engine"] = ocr_engine  # 保存 OCR 引擎配置
        _cfg["ocr_device"] = ocr_device  # 保存 OCR 推理硬件设备配置 (cpu/gpu)
        _cfg["ocr_params"] = ocr_params  # 保存 PaddleOCR 四模型参数
        # 将配置同步到全局 Python 环境变量，保证 Agent 可直接读取
        publish_runtime_config({**_runtime, "dingtalk_mcp_url": _cfg["dingtalk_mcp_url"]})
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
        st.success("已保存（环境变量 + 配置文件 + 用户页同步）")  # 报绿色成功保存状态气泡提示

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

tab1, tab2 = st.tabs(["📷 处理作业票", "📊 数据看板"])  # 处理 / 历史数据


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
        # 增加重新上传按钮，当已经上传完成或有历史处理结果时，按钮自动变为“重新上传”
        if st.session_state.get("upload_done") or st.session_state.results:
            show_upload = st.button("🔄 重新上传", use_container_width=True)
        else:
            show_upload = st.button("📤 上传", use_container_width=True)  # 渲染上传大按键并填平列宽
    with c2:  # 进入第二分栏
        can_process = st.session_state.get("upload_done") and st.session_state.get("pending_files")  # 感知是否可被处理
        run_clicked = st.button("⚙️ 处理", use_container_width=True, disabled=not can_process)  # 渲染处理大按键，当无文件时置灰失效

    # 按钮点击状态切换事件处理
    if show_upload:  # 如果用户点击了上传/重新上传按键
        st.session_state.show_uploader = True  # 设置展示上传选择器标志为真
        st.session_state.upload_done = False  # 重置上传就绪标志为否，进入新一轮上传状态
        st.session_state.pending_files = None  # 清空暂存的待处理文件
        st.session_state.results = []  # 清空历史处理结果，进入全新一轮的识别流程
        st.session_state.uploader_key_suffix += 1  # 递增 Key 序号，强制销毁并重新初始化 file_uploader 组件以彻底清空图片缓存
        st.rerun()  # 触发 Streamlit 强制重绘，复位上传器的前端状态

    # ---- 文件拖拽选择器 ----
    if st.session_state.get("show_uploader"):  # 判断如果控制显示上传面板的标志为真
        st.caption("请先选择票型（**带气 / 动火流水线完全分离**，模板与措施不交叉）")
        st.radio(
            "作业票类型",
            options=["带气作业票", "动火作业票"],
            horizontal=True,
            key="selected_ticket_type",
            help="带气→dq.png + ocr5 25×5；动火→dh.png + ocr5 21×5 确认格，互不混用。",
        )
        # 动态传入后缀 key 强制在点击“重新上传”后复位组件
        uploader_key = f"fu_main_{st.session_state.uploader_key_suffix}"
        picked = st.file_uploader("选择图片", type=["jpg","jpeg","png","bmp"], accept_multiple_files=False, label_visibility="collapsed", key=uploader_key)  # 显示 Streamlit 原生上传面板，限制单张图片
        if picked and not st.session_state.get("upload_done"):  # 判断用户选择了图片且此图尚未触发上传流水线
            st.session_state.pending_files = [picked]  # 将上传的文件句柄存入会话状态 pending_files 列表中
            st.session_state.upload_done = True  # 设定上传完毕就绪标志为真
            # 不再用 time.sleep 假进度（会空等约 1s）；直接 rerun 刷新步骤条
            st.rerun()
        elif picked and st.session_state.get("upload_done"):  # 若属于已重绘刷新重绘完毕的状态
            st.success(f"✅ {picked.name}（{picked.size/1024:.0f} KB）")  # 静态显示当前就绪的图片名称体积

    # 空状态看板和上次处理历史展示逻辑
    final_files = st.session_state.get("pending_files") or []  # 提取就绪的待处理文件列表，无则置空列表
    _is_processing = bool(st.session_state.get("run_processing"))

    # 待处理图片缩略预览图
    if final_files and not run_clicked and not _is_processing:
        thumbs = st.columns(min(len(final_files) + 1, 6))
        for i, f in enumerate(final_files[:5]):
            with thumbs[i]:
                st.image(f, width=100)
        with thumbs[min(len(final_files), 5)]:
            st.markdown(
                f"<div style='text-align:center;padding-top:35px;color:#69707f;font-size:12px'>{len(final_files)}张</div>",
                unsafe_allow_html=True,
            )

    if not final_files and not run_clicked and not st.session_state.results:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-icon">🛡️</div>
            <div class="empty-title">上传作业票照片，AI 自动完成全部分析</div>
            <div class="empty-desc">支持带气 / 动火作业票（分路处理；先选票型再上传，点「处理」）</div>
            <div class="empty-action">点击上方 <b>📤 上传</b> 选择照片开始分析</div>
        </div>
        """, unsafe_allow_html=True)

    # 触发 AI 算法核心处理段（点「处理」后直接执行，去掉中间空 rerun，少一整轮脚本重跑）
    if run_clicked and final_files:
        st.session_state.run_processing = False

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
        agent = SecurityAgent(
            brain=brain,
            ocr_mode=ocr_mode,
            ocr_engine=ocr_engine,
            ocr_device=ocr_device,
            vision_brain=vision_brain,
            ocr_params=ocr_params,  # 侧边栏四模型参数（可与 config.json 同步）
        )
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

        upload_progress.progress(100)  # 进度条打满 100%
        upload_status.caption(f"✅ {len(saved_paths)} 张图片已保存，开始 Agent 处理...")  # 提示进入智能体处理阶段
        upload_progress.empty()  # 清空并释放进度条占位容器
        upload_status.empty()  # 清空保存文字提示容器

        # ---- Agent 核心迭代逐张分析图片流程 ----
        for idx, uploaded in enumerate(final_files):  # 循环迭代开始主算法的执行
            save_path = saved_paths[idx]  # 获取当前迭代对应的本地物理图像文件路径

            status_text = st.empty()  # 创建子状态文字容器，置于分栏上方以防撑开首行高度
            progress = st.progress(0)  # 创建处理总进度条容器，置于分栏上方
            status_text.caption(f"[{idx+1}/{len(final_files)}] {uploaded.name} — 准备中...")  # 提示该文件准备中

            # 界面采用黄金比例分栏：左侧 3 份显示核心结论，右侧 2 份显示黑客风 Agent 思考日志数据流
            col_r, col_l = st.columns([3, 2])  # 创建该结构划分

            # 左侧分栏：用来呈现当前处理大图的缩略图
            with col_r:  # 进入左栏上下文
                img_placeholder = st.empty()  # 创建图片展示临时占位符
                img_placeholder.image(save_path, caption=uploaded.name, use_container_width=True)  # 显示完整的待分析原图

            # 右侧分栏：提供日志流的视觉占位
            with col_l:  # 进入右栏上下文
                log_ph = st.empty()  # 在右栏内部首个位置建立黑客风控制台的专用占位容器，确保与左侧图片顶部完美平齐
            log_buf = []  # 初始化该图的本地终端日志缓存列表，仅保存本图片的运行信息
            _t0_img = time.time()  # 记录当前图片启动执行的初始系统时间点
            _last_stage = [""]  # 用单元素列表形式包装当前处理阶段，以便在闭包函数 hlog 中可以动态覆写修改

            def hlog(line, _save_path=save_path, _name=uploaded.name):  # 定义用于捕获底层 stdio 输出以渲染黑客日志终端的辅助闭包函数
                from datetime import datetime, timezone, timedelta
                _ts = datetime.now(timezone(timedelta(hours=8))).strftime("[%H:%M:%S] ")
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
                        elif "重试" in l or "未通过" in l: c = "lw"  # 重试重整及异常检查发现着为橙黄色 text (lw)
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
                ticket_type_val = st.session_state.get("selected_ticket_type", "带气作业票")
                ocr_text, structured = agent.run(save_path, progress_callback=prog_cb, ticket_type=ticket_type_val)  # 执行 Agent 对象的 run 算法以进行核心安全自检工作
                result["ocr"], result["data"] = ocr_text, structured  # 将正常运行完毕得出的结果存入 result 中
            except Exception as e:  # 若处理过程中不幸崩溃
                hlog(f"❌ {e}")  # 往黑客控制台输出带叉的红色错误诊断信息
            finally:  # 最终清理复原
                sys.stdout = _orig  # 还原全局标准输出流，避免污染系统的其他输出流导致页面假死崩溃

            progress.progress(100)  # 处理完毕，强制打满左侧主进度条
            status_text.caption(f"[{idx+1}/{len(final_files)}] ✅ 完成")  # 提示本张图片已处理完成
            # 原图收纳到折叠区；审批结果画在左栏（与截图红框一致：查看原图下方）
            with img_placeholder:
                with st.expander("🖼️ 查看原图", expanded=False):
                    st.image(save_path, caption=uploaded.name, use_container_width=True)

            # 左栏：KPI + 审批建议（与截图红框一致：查看原图下方）
            with col_r:
                if result["data"]:
                    d = result["data"]
                    result["image_path"] = save_path
                    result["name"] = uploaded.name
                    st.session_state.results.append(result)
                    st.session_state["_results_painted_inline"] = True
                    render_ticket_kpis(d)
                    if result.get("ocr"):
                        with st.expander("📝 OCR 识别原文"):
                            ocr_out = (
                                result["ocr"].split("\n---\n")[-1]
                                if "\n---\n" in result["ocr"]
                                else result["ocr"]
                            )
                            if "<table" in ocr_out.lower():
                                st.markdown(ocr_out, unsafe_allow_html=True)
                            else:
                                st.text(ocr_out)
                    if d.issues:
                        with st.expander(f"⚠️ 问题明细 ({len(d.issues)})", expanded=True):
                            unimpl = [m for m in d.safety_measures if not m.implemented]
                            if unimpl:
                                st.markdown("**安全措施未落实：**")
                                for m in unimpl:
                                    st.markdown(
                                        f"  🔴 第{m.measure_id}项 `{m.description}` — 标记为**未落实×**"
                                    )
                            for issue in d.issues:
                                reason = issue.raw_text or "OCR识别为异常标记"
                                st.markdown(f"  ⚠️ **{issue.item_name}** — {reason}")
                else:
                    st.warning("本张未得到结构化结果，请查看右侧日志。")

        if len(st.session_state.results) > 1:
            abn = sum(
                1 for r in st.session_state.results
                if r.get("data") and r["data"].has_abnormal
            )
            st.markdown(
                f"**📊 汇总** {len(st.session_state.results)}张 "
                f"{badge('正常' + str(len(st.session_state.results) - abn), 'ok')} "
                f"{badge('问题' + str(abn), 'err' if abn else 'ok')}",
                unsafe_allow_html=True,
            )

    # ==================== 处理结果持久展示（页面重绘后仍可见） ====================
    # 处理当次已在 col_r 画过则跳过；否则（如用户点了侧栏/上传后）用全宽补画，避免审批建议消失。
    if (
        st.session_state.results
        and not st.session_state.get("run_processing")
    ):
        if st.session_state.pop("_results_painted_inline", False):
            pass  # 本 run 已在左栏展示
        else:
            st.markdown("---")
            st.markdown("### 处理结果 · 审批建议")
            for item in st.session_state.results:
                d = item.get("data")
                if not d:
                    continue
                name = item.get("name") or ""
                if name:
                    st.caption(f"文件：{name}")
                render_ticket_kpis(d)
                if item.get("ocr"):
                    with st.expander("📝 OCR 识别原文"):
                        ocr_out = (
                            item["ocr"].split("\n---\n")[-1]
                            if "\n---\n" in item["ocr"]
                            else item["ocr"]
                        )
                        if "<table" in ocr_out.lower():
                            st.markdown(ocr_out, unsafe_allow_html=True)
                        else:
                            st.text(ocr_out)
                if d.issues:
                    with st.expander(f"⚠️ 问题明细 ({len(d.issues)})", expanded=False):
                        for issue in d.issues:
                            st.markdown(
                                f"  ⚠️ **{issue.item_name}** — {issue.raw_text or '异常'}"
                            )
                img_path = item.get("image_path")
                if img_path and os.path.exists(img_path):
                    with st.expander("🖼️ 查看原图", expanded=False):
                        st.image(img_path, use_container_width=True)


# ==================== Tab 2: 数据看板（精简） ====================
with tab2:
    import sqlite3
    from agent_core import AgentTools, DB_TABLE_GAS, DB_TABLE_HOT

    db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
    _del_pwd = _cfg.get("delete_password", "123")

    st.caption("历史作业票 · 带气表 / 动火表分库 · 审批：自动通过 / 待审批(钉钉人工) / 已驳回")
    board_kind = st.radio(
        "看板票型",
        options=["全部", "带气作业票", "动火作业票"],
        horizontal=True,
        key="board_ticket_kind",
    )

    # 统一展示行：dict，含 kind / table / id 等
    rows_db = []

    if not os.path.exists(db_path):
        st.caption("📭 暂无数据，在「处理作业票」中处理后自动入库。")
    else:
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            AgentTools.ensure_ticket_tables(conn)
            conn.row_factory = sqlite3.Row

            def _load_gas():
                out = []
                try:
                    for r in conn.execute(
                        f"SELECT id,ticket_id,station_name,content,work_time,worker_id,"
                        f"check_date,completion_time,risk_level,approver_name,"
                        f"operators,construction_leader,supervisor,company_monitor,gas_leader,"
                        f"has_abnormal,approval_opinion,approval_status,approval_level,"
                        f"created_at,image_path FROM {DB_TABLE_GAS} ORDER BY id DESC"
                    ):
                        out.append({
                            "kind": "带气", "table": DB_TABLE_GAS, "id": r["id"],
                            "ticket_id": r["ticket_id"], "unit": r["station_name"],
                            "content": r["content"], "work_time": r["work_time"],
                            "worker": r["worker_id"], "check_date": r["check_date"],
                            "has_abnormal": r["has_abnormal"],
                            "approval_opinion": r["approval_opinion"],
                            "risk_level": r["risk_level"],
                            "approval_status": r["approval_status"],
                            "approval_level": r["approval_level"],
                            "created_at": r["created_at"], "image_path": r["image_path"],
                            "extra": {
                                "作业单位": r["station_name"],
                                "作业内容": r["content"],
                                "作业时间": r["work_time"],
                                "作业人姓名及证书编号": r["worker_id"],
                                "日期": r["check_date"],
                                "完工时间": r["completion_time"],
                                "作业等级": r["risk_level"],
                                "发起人签字确认": r["approver_name"],
                                "作业人员": r["operators"],
                                "施工方现场负责人": r["construction_leader"],
                                "监理人员": r["supervisor"],
                                "项目公司监护人": r["company_monitor"],
                                "带气现场负责人": r["gas_leader"],
                            },
                        })
                except Exception:
                    pass
                return out

            def _load_hot():
                out = []
                try:
                    for r in conn.execute(
                        f"SELECT id,ticket_id,fire_unit,fire_location,content,work_time,"
                        f"fire_method,worker_id,sampling_result,risk_level,"
                        f"fire_personnel,construction_leader,supervisor,company_monitor,"
                        f"fire_leader_project,fire_leader,check_date,"
                        f"has_abnormal,approval_opinion,approval_status,approval_level,"
                        f"created_at,image_path FROM {DB_TABLE_HOT} ORDER BY id DESC"
                    ):
                        out.append({
                            "kind": "动火", "table": DB_TABLE_HOT, "id": r["id"],
                            "ticket_id": r["ticket_id"],
                            "unit": r["fire_unit"] or r["fire_location"] or "-",
                            "content": r["content"], "work_time": r["work_time"],
                            "worker": r["worker_id"], "check_date": r["check_date"],
                            "has_abnormal": r["has_abnormal"],
                            "approval_opinion": r["approval_opinion"],
                            "risk_level": r["risk_level"],
                            "approval_status": r["approval_status"],
                            "approval_level": r["approval_level"],
                            "created_at": r["created_at"], "image_path": r["image_path"],
                            "extra": {
                                "动火单位": r["fire_unit"],
                                "动火地点": r["fire_location"],
                                "动火方式": r["fire_method"],
                                "采样检测": r["sampling_result"],
                                "动火人员": r["fire_personnel"],
                                "施工方现场负责人": r["construction_leader"],
                                "监理人员": r["supervisor"],
                                "项目公司监护人员": r["company_monitor"],
                                "动火现场负责人(项目公司)": r["fire_leader_project"],
                                "动火现场负责人": r["fire_leader"],
                            },
                        })
                except Exception:
                    pass
                return out

            if board_kind == "带气作业票":
                rows_db = _load_gas()
            elif board_kind == "动火作业票":
                rows_db = _load_hot()
            else:
                rows_db = _load_gas() + _load_hot()
                rows_db.sort(key=lambda x: x.get("created_at") or "", reverse=True)

            total = len(rows_db)
            abn_cnt = sum(1 for r in rows_db if r.get("has_abnormal"))
            auto_cnt = sum(1 for r in rows_db if (r.get("approval_status") or "") == "自动通过")
            human_cnt = sum(1 for r in rows_db if (r.get("approval_status") or "") in ("待审批", "已驳回"))

            render_kpi_row([
                ("总票数", str(total), ""),
                ("发现漏填", str(abn_cnt), "#d6131c" if abn_cnt else "#059669"),
                ("自动通过", str(auto_cnt), "#059669"),
                ("钉钉介入", str(human_cnt), "#0052CC" if human_cnt else ""),
            ])
        finally:
            if conn:
                conn.close()
                conn = None

        if st.session_state.delete_id:
            @st.dialog("确认删除", width="small")
            def confirm_delete():
                did = st.session_state.delete_id
                # delete_id 可能是 (table, id) 或 纯 id
                if isinstance(did, (list, tuple)) and len(did) == 2:
                    del_table, del_id = did
                else:
                    del_table, del_id = DB_TABLE_GAS, did
                st.warning(f"删除 {del_table} 记录 #{del_id}？不可恢复。")
                pwd = st.text_input("删除验证码", type="password")
                fc1, fc2 = st.columns(2)
                with fc1:
                    if st.button("确认", type="primary", use_container_width=True):
                        if pwd == _del_pwd:
                            try:
                                c2 = sqlite3.connect(db_path)
                                if del_table not in (DB_TABLE_GAS, DB_TABLE_HOT):
                                    raise ValueError(f"非法表名: {del_table}")
                                c2.execute(
                                    f"DELETE FROM {del_table} WHERE id=?",
                                    (del_id,),
                                )
                                c2.commit()
                            except Exception as e:
                                st.error(f"删除失败: {e}")
                            finally:
                                c2.close()
                            st.session_state.delete_id = None
                            st.rerun()
                        else:
                            st.error("验证码错误")
                with fc2:
                    if st.button("取消", use_container_width=True):
                        st.session_state.delete_id = None
                        st.rerun()
            confirm_delete()

        with st.form("search_form", clear_on_submit=False):
            sf1, sf2 = st.columns([5, 1])
            with sf1:
                search = st.text_input(
                    "搜索", placeholder="票号关键字…", label_visibility="collapsed",
                )
            with sf2:
                st.form_submit_button("搜索", use_container_width=True)

        for row in rows_db:
            rid = row["id"]
            kind = row["kind"]
            table = row["table"]
            ticket = row.get("ticket_id") or "-"
            station = row.get("unit") or "-"
            content = row.get("content") or ""
            work_time = row.get("work_time") or ""
            worker = row.get("worker") or ""
            date = row.get("check_date") or ""
            abnormal = row.get("has_abnormal")
            opinion = row.get("approval_opinion") or ""
            grade = row.get("risk_level") or "-"
            ap_status = row.get("approval_status") or "-"
            created = row.get("created_at") or ""
            img_path = row.get("image_path")

            if search and search.lower() not in (ticket or "").lower():
                continue

            icon = "🚨" if abnormal else "✅"
            badge_md = render_record_badge(grade, abnormal)
            title = f"{icon} [{kind}] {ticket} · {station} · {grade} · {ap_status}{badge_md}"

            cm, cd = st.columns([9, 1])
            with cm:
                with st.expander(title, expanded=False):
                    if kind == "动火":
                        ex = row.get("extra") or {}
                        grade_note = (
                            "（特级最高）" if grade == "特级"
                            else ("（一级最低）" if grade == "一级" else "")
                        )
                        md = (
                            f"| 项目 | 内容 |\n|---|---|\n"
                            f"| 票型 | 动火作业票 |\n"
                            f"| 票号 | {ticket} |\n"
                            f"| 动火单位 | {ex.get('动火单位') or station} |\n"
                            f"| 动火地点 | {ex.get('动火地点') or '-'} |\n"
                            f"| 动火内容 | {content[:40]}{'…' if len(content) > 40 else ''} |\n"
                            f"| 动火时间 | {work_time or date} |\n"
                            f"| 动火方式 | {ex.get('动火方式') or '-'} |\n"
                            f"| 动火人 | {worker} |\n"
                            f"| 采样检测 | {ex.get('采样检测') or '-'} |\n"
                            f"| 动火等级 | {grade}{grade_note} |\n"
                            f"| 动火人员 | {ex.get('动火人员') or '-'} |\n"
                            f"| 施工方现场负责人 | {ex.get('施工方现场负责人') or '-'} |\n"
                            f"| 监理人员 | {ex.get('监理人员') or '-'} |\n"
                            f"| 项目公司监护人员 | {ex.get('项目公司监护人员') or '-'} |\n"
                            f"| 动火现场负责人(项目公司) | {ex.get('动火现场负责人(项目公司)') or '-'} |\n"
                            f"| 动火现场负责人 | {ex.get('动火现场负责人') or '-'} |\n"
                            f"| 状态 | {'发现漏填' if abnormal else '正常'} |\n"
                            f"| 审批 | {ap_status} |\n"
                        )
                    else:
                        ex = row.get("extra") or {}
                        grade_note = "（一级危险最高）" if grade == "一级" else ""
                        _c = content or ex.get("作业内容") or ""
                        md = (
                            f"| 项目 | 内容 |\n|---|---|\n"
                            f"| 票型 | 带气作业票 |\n"
                            f"| 作业票编号 | {ticket} |\n"
                            f"| 作业单位 | {ex.get('作业单位') or station} |\n"
                            f"| 作业内容 | {_c[:40]}{'…' if len(_c) > 40 else ''} |\n"
                            f"| 作业时间 | {ex.get('作业时间') or work_time or date} |\n"
                            f"| 作业人姓名及证书编号 | {ex.get('作业人姓名及证书编号') or worker} |\n"
                            f"| 日期 | {ex.get('日期') or date or '-'} |\n"
                            f"| 完工时间 | {ex.get('完工时间') or '-'} |\n"
                            f"| 作业等级 | {grade}{grade_note} |\n"
                            f"| 发起人签字确认 | {ex.get('发起人签字确认') or '-'} |\n"
                            f"| 作业人员 | {ex.get('作业人员') or '-'} |\n"
                            f"| 施工方现场负责人 | {ex.get('施工方现场负责人') or '-'} |\n"
                            f"| 监理人员 | {ex.get('监理人员') or '-'} |\n"
                            f"| 项目公司监护人 | {ex.get('项目公司监护人') or '-'} |\n"
                            f"| 带气现场负责人 | {ex.get('带气现场负责人') or '-'} |\n"
                            f"| 状态 | {'发现漏填' if abnormal else '正常'} |\n"
                            f"| 审批 | {ap_status} |\n"
                        )
                    st.markdown(md)
                    if opinion:
                        st.caption(f"建议：{opinion[:120]}{'…' if len(opinion) > 120 else ''}")
                    st.caption(f"入库：{created} · 表 {table}")

                    if img_path and os.path.exists(img_path):
                        dc1, dc2 = st.columns(2)
                        with dc1:
                            if st.button("查看原图", key=f"img_{table}_{rid}", use_container_width=True):
                                @st.dialog("原图", width="large")
                                def show_orig_img(_path=img_path, _name=ticket):
                                    st.image(_path, caption=_name, use_container_width=True)
                                show_orig_img()
                        with dc2:
                            ext = os.path.splitext(img_path)[1] or ".png"
                            dl_name = f"{ticket or f'ticket_{rid}'}{ext}"
                            with open(img_path, "rb") as f:
                                img_bytes = f.read()
                            st.download_button(
                                "下载原图", data=img_bytes, file_name=dl_name,
                                mime="image/png", key=f"dl_{table}_{rid}", use_container_width=True,
                            )
                    else:
                        st.caption("原图不可用")
            with cd:
                st.markdown("<div style='padding-top:18px'></div>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{table}_{rid}", help=f"删除 {table} #{rid}"):
                    st.session_state.delete_id = (table, rid)
                    st.rerun()
