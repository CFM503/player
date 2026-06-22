"""
安全哨兵 - Agent 可视化决策链面板
直接 import agent_core，无需 FastAPI/Node/网络层
启动: streamlit run frontend.py
"""

import io
import sys
import os
import re
import time
import tempfile
from dataclasses import dataclass, field
from typing import List
import streamlit as st

st.set_page_config(
    page_title="安全哨兵 · AI Agent 自主决策控制台",
    page_icon="🛡️",
    layout="wide",
)

# ---- CSS ----
st.markdown("""
<style>
.step-card {
    border: 1px solid #262626;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
    background: #111;
}
.step-header { font-weight: bold; font-size: 15px; margin-bottom: 6px; }
.step-action { color: #888; font-size: 13px; margin-bottom: 4px; }
.step-result { color: #e0e0e0; font-size: 13px; }
.step-result-ok { color: #00ff41; }
.step-result-retry { color: #ffb800; }
.step-result-error { color: #ff4444; }
.check-line { font-size: 13px; line-height: 1.8; }
.agent-thought { color: #ffb800; font-weight: bold; font-size: 14px; padding: 8px 12px; background: #1a1500; border-radius: 6px; margin: 6px 0; }
.tool-line { color: #00cc33; font-size: 13px; margin: 2px 0 2px 16px; }
.raw-log { background: #0a0a0a; border: 1px solid #222; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 12px; color: #666; max-height: 300px; overflow-y: auto; line-height: 1.6; }
#MainMenu, footer, header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


@dataclass
class AgentStep:
    """Agent 决策链中的一个步骤"""
    name: str
    emoji: str
    action: str = ""
    result: str = ""
    status: str = "pending"  # pending | running | done | retry | error
    checks: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    raw_lines: List[str] = field(default_factory=list)


def parse_log_to_steps(lines: List[str]) -> List[AgentStep]:
    """将 Agent 的原始日志解析为结构化的 Step 卡片"""
    step_map = {
        "Plan": ("规划", "📋"),
        "Perceive": ("感知", "👁️"),
        "Reason": ("推理", "🤔"),
        "Reflect": ("反思", "🔍"),
        "Act": ("执行", "⚡"),
        "Report": ("总结", "📊"),
    }
    steps: List[AgentStep] = []
    current_step = None

    for line in lines:
        m = re.search(r'\[Agent\s+\S+\s+(\w+)\]\s*(.*)', line)
        if m:
            phase, content = m.group(1), m.group(2)
            if phase in step_map:
                name, emoji = step_map[phase]
                # 找到同名 step 或新建
                existing = next((s for s in steps if s.name == name), None)
                if existing is None:
                    current_step = AgentStep(name=name, emoji=emoji, status="running")
                    steps.append(current_step)
                else:
                    current_step = existing
                    if current_step.status != "done":  # 不重置已完成的 step
                        current_step.status = "running"

        if current_step is None:
            continue

        current_step.raw_lines.append(line)

        # 解析具体内容 — 当新 step 开始时，上一个 step 自动标记 done（除了反思的重试）
        if current_step and current_step.status == "running":
            # 如果 current_step 不是当前 line 所属的 step，标记上一步完成
            pass  # 由下面的逻辑逐步标记

        if "Plan" in line and "执行计划" in line:
            current_step.action = "分析任务并制定执行计划"
        elif "Plan" in line and ("①" in line or "②" in line or "③" in line or "④" in line or "⑤" in line):
            current_step.result += line.split("Plan]")[-1].strip() + "\n" if "Plan]" in line else line.strip() + "\n"
            # 最后一个⑤ 行时标记 Plan 完成
            if "⑤" in line:
                current_step.status = "done"
        elif "Perceive" in line and "调用感知工具" in line:
            # Plan 完成
            for s in steps:
                if s.name == "规划" and s.status == "running":
                    s.status = "done"
            current_step.action = "OpenCV 去阴影 + PaddleOCR 文字识别"
        elif "Perceive" in line and "感知完成" in line:
            current_step.result = line.split("感知完成。")[-1]
            current_step.status = "done"
        elif "Reason" in line and "调用推理工具" in line:
            current_step.action = "LLM 语义分析，结构化为 HSE 作业票 JSON"
        elif "Reason" in line and "推理完成" in line:
            current_step.result = line.split("推理完成。")[-1]
            current_step.status = "done"
        elif "Reflect" in line and "进入反思" in line:
            current_step.action = "校验结构化数据的完整性和业务合理性"
        elif "Reflect" in line and ("✅" in line or "⚠️" in line):
            current_step.checks.append(line.split("Reflect]")[-1].strip() if "Reflect]" in line else line)
        elif "Reflect" in line and "反思通过" in line:
            current_step.result = "所有校验项合格，数据可信"
            current_step.status = "done"
        elif "Reflect" in line and "反思未通过" in line:
            current_step.status = "retry"
        elif "Reflect" in line and "最大重试" in line:
            current_step.result = "达到最大重试次数，标记高风险"
            current_step.status = "error"
        elif "Act" in line and "进入执行" in line:
            current_step.action = "根据反思结果，自主选择并调用业务工具"
        elif "Act" in line and "选择工具" in line:
            tool = line.split("选择工具:")[-1].strip() if "选择工具:" in line else line
            current_step.tools.append(tool)
        elif "Act" in line and "已执行" in line:
            current_step.result = line.split("Act]")[-1].strip() if "Act]" in line else line
            current_step.status = "done"
        elif "Report" in line and "完整报告" in line:
            current_step.action = "输出完整决策链报告"
        elif "Report" in line and "阶段全部完成" in line:
            current_step.result = line.split("Report]")[-1].strip() if "Report]" in line else line
            current_step.status = "done"
        elif "⏱️" in line:
            # 耗时行归到最后一步
            if steps:
                steps[-1].raw_lines.append(line)

        # 解析计划文本（多行）
        if current_step and current_step.name == "规划" and line.strip().startswith(("①", "②", "③", "④", "⑤")):
            current_step.result += line.strip() + "\n"

    return steps


# ---- 侧边栏 ----
with st.sidebar:
    st.title("🛡️ 安全哨兵")
    st.caption("牡丹江中燃 HSE · AI Agent 自主智能体")
    st.divider()

    use_online = st.toggle("☁️ 线上 API 模式", value=os.environ.get("USE_ONLINE_API", "false").lower() == "true")
    if use_online:
        api_key = st.text_input("API Key", os.environ.get("ONLINE_API_KEY", ""), type="password")
        base_url = st.text_input("Base URL", os.environ.get("ONLINE_BASE_URL", "https://api.siliconflow.cn/v1"))
        model_name = st.text_input("Model", os.environ.get("ONLINE_MODEL", "Qwen/Qwen2.5-7B-Instruct"))
    else:
        gguf_path = st.text_input("GGUF 模型路径",
                                   os.environ.get("GGUF_MODEL_PATH", "models/qwen2.5-3b-instruct-q4_k_m.gguf"))
    st.divider()
    mock_mode = st.checkbox("🧪 Mock 模式 (无需 OCR/LLM 依赖)", value=False)

# ---- 主面板 ----
st.markdown("### 📷 上传巡检作业票 → Agent 自主处理")

col_upload, col_info = st.columns([1, 1])

with col_upload:
    uploaded = st.file_uploader(
        "拍照或选择作业票图片",
        type=["jpg", "jpeg", "png", "bmp"],
        accept_multiple_files=False,
        help="手机浏览器点击可直接唤起后置摄像头拍摄",
        label_visibility="collapsed",
    )
    if uploaded:
        st.image(uploaded, caption=f"📎 {uploaded.name} ({uploaded.size/1024:.1f} KB)", width=350)

with col_info:
    st.markdown("""
    **🤖 Agent ReAct 决策架构：**
    - 📋 **Plan** — 自主规划执行步骤
    - 👁️ **Perceive** — 调用 OpenCV + PaddleOCR 感知
    - 🤔 **Reason** — 调用 LLM 推理结构化
    - 🔍 **Reflect** — 自主反思校验，不通过则重试
    - ⚡ **Act** — 自主选择工具组合执行
    - 📊 **Report** — 输出完整决策链报告
    """)

st.divider()

# ---- Agent 执行区 ----
if uploaded:
    if st.button("🚀 提交给 Agent 处理", type="primary", use_container_width=True):

        suffix = os.path.splitext(uploaded.name)[1] or ".jpg"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(uploaded.getvalue())
        tmp.close()
        image_path = tmp.name

        # 收集所有原始日志
        raw_logs: List[str] = []
        log_container = st.empty()
        step_container = st.empty()

        def render_steps(logs: List[str]):
            """实时渲染 Agent 决策链 Step 卡片"""
            steps = parse_log_to_steps(logs)
            with step_container.container():
                for step in steps:
                    status_icon = {"pending": "⬜", "running": "🔄", "done": "✅", "retry": "🔄", "error": "❌"}.get(step.status, "⬜")
                    border_color = {"done": "#1a3a1a", "running": "#3a3a00", "retry": "#3a2a00", "error": "#3a1a1a"}.get(step.status, "#262626")

                    st.markdown(f'<div class="step-card" style="border-color:{border_color}">', unsafe_allow_html=True)
                    st.markdown(f'<div class="step-header">{status_icon} Step {steps.index(step)+1} {step.emoji} {step.name}</div>', unsafe_allow_html=True)

                    if step.action:
                        st.markdown(f'<div class="step-action">→ {step.action}</div>', unsafe_allow_html=True)

                    for tool in step.tools:
                        st.markdown(f'<div class="tool-line">🔧 {tool}</div>', unsafe_allow_html=True)

                    for check in step.checks:
                        st.markdown(f'<div class="check-line">{check}</div>', unsafe_allow_html=True)

                    if step.result:
                        cls = {"done": "step-result-ok", "retry": "step-result-retry", "error": "step-result-error"}.get(step.status, "step-result")
                        # 多行结果（计划）
                        for rline in step.result.strip().split("\n"):
                            if rline.strip():
                                st.markdown(f'<div class="{cls}">{rline}</div>', unsafe_allow_html=True)

                    st.markdown('</div>', unsafe_allow_html=True)

        def render_raw_log(logs: List[str]):
            with log_container.expander("📜 Agent 完整原始日志", expanded=False):
                st.markdown('<div class="raw-log">' + "<br>".join(logs) + "</div>", unsafe_allow_html=True)

        if mock_mode:
            mock_steps = [
                "[Agent 📋 Plan] 收到一张巡检作业票照片，Agent 开始制定执行计划...",
                "[Agent 📋 Plan] 执行计划：",
                "[Agent 📋 Plan]   ① 感知：调用 OpenCV 清洗图像 + PaddleOCR 提取文字",
                "[Agent 📋 Plan]   ② 推理：调用 LLM 将 OCR 文本结构化为 HSE 作业票 JSON",
                "[Agent 📋 Plan]   ③ 反思：校验结构化数据的完整性和合理性",
                "[Agent 📋 Plan]   ④ 执行：根据是否存在隐患，自主选择工具组合",
                "[Agent 📋 Plan]   ⑤ 总结：输出完整决策链报告",
                "[Tool Log] 📸 触发手机相片前置清洗算子：启动自适应去阴影与对比度锐化...",
                "[Tool Log] 📸 CLAHE 直方图均衡化完成，自适应阈值二值化完成",
                "[Tool Log] 🤖 图像清洗完毕。正在拉起本地 PaddleOCR 提取手写体...",
                "[Tool Log] 🤖 OCR 提取完成，共识别 12 行文本",
                "[Agent 👁️ Perceive] 调用感知工具链：OpenCV 去阴影 → PaddleOCR 文字识别",
                "[Agent 👁️ Perceive] 感知完成。提取到 12 行文本，包含作业票编号、动火信息、浓度数据",
                "[Agent 🤔 Reason] 调用推理工具：LLM 语义分析，将 OCR 文本结构化为 HSE 作业票 JSON",
                "[Agent 🤔 Reason] 推理完成。票号=MPJZR2026004001 | 场站=光86了单元 | 浓度=[0.0, 0.3] | 含隐患=True",
                "[Agent 🔍 Reflect] 进入反思阶段：校验结构化数据的完整性和业务合理性...",
                "[Agent 🔍 Reflect]   ✅ 票号格式: MPJZR2026004001 ✅",
                "[Agent 🔍 Reflect]   ✅ 浓度范围: [0.0, 0.3] ∈ [0,100] ✅",
                "[Agent 🔍 Reflect]   ✅ 异常一致性: has_abnormal=True, issues=1条 ✅",
                "[Agent 🔍 Reflect]   ✅ 安全措施判定: 1项未落实, has_abnormal=True ✅",
                "[Agent 🔍 Reflect] 反思通过，所有校验项合格，数据可信。",
                "[Agent ⚡ Act] 进入执行阶段：根据反思结果，自主选择并调用业务工具...",
                "[Agent ⚡ Act]   → 选择工具: SQLite 数据沉淀",
                "[Tool Log] 💾 作业票 MPJZR2026004001 已沉淀至本地 SQLite",
                "[Agent ⚡ Act]   → 选择工具: 企业微信自动预警推送",
                "[Tool Log] 🚨 已向安全负责人推送企业微信警报",
                "[Agent ⚡ Act]   → 选择工具: Playwright OA 表单自动填报",
                "[Tool Log] 🌐 启动 Playwright 自动填报作业票 MPJZR2026004001",
                "[Agent ⚡ Act] 已执行: SQLite存库 + 企业微信预警 + Playwright填报（共3个工具）",
                "[Agent ⏱️] 全流程耗时: 4.2 秒",
                "[Agent 📊 Report] ========== Agent 决策链完整报告 ==========",
                "[Agent 📊 Report] ========== 共执行 6 个阶段，Agent 任务完成 ==========",
            ]
            for line in mock_steps:
                raw_logs.append(line)
                render_steps(raw_logs)
                render_raw_log(raw_logs)
                time.sleep(0.35)

        else:
            from agent_core import SecurityAgentOrchestrator, OnlineApiBrain, LocalGgufBrain

            if use_online:
                brain = OnlineApiBrain(api_key=api_key, base_url=base_url, model_name=model_name)
            else:
                brain = LocalGgufBrain(model_path=gguf_path)

            agent = SecurityAgentOrchestrator(brain=brain)

            _orig_stdout = sys.stdout
            ocr_result = {"text": None, "json": None}

            class StreamlitCapture(io.TextIOBase):
                def write(self, s):
                    s = s.strip()
                    if s:
                        raw_logs.append(s)
                        render_steps(raw_logs)
                        render_raw_log(raw_logs)
                    return len(s) if s else 0
                def flush(self):
                    pass

            sys.stdout = StreamlitCapture()  # type: ignore
            try:
                ocr_text, structured_data = agent.run_pipeline(image_path)
                ocr_result["text"] = ocr_text
                ocr_result["json"] = structured_data
            except Exception as e:
                raw_logs.append(f"❌ Pipeline 出错: {e}")
                render_steps(raw_logs)
                render_raw_log(raw_logs)
            finally:
                sys.stdout = _orig_stdout

            # 展示 OCR 原文和结构化 JSON
            if ocr_result["text"] or ocr_result["json"]:
                st.divider()
                result_col1, result_col2 = st.columns(2)
                with result_col1:
                    st.markdown("#### 📝 OCR 识别原文")
                    if ocr_result["text"]:
                        st.code(ocr_result["text"], language=None)
                with result_col2:
                    st.markdown("#### 📦 结构化 JSON 输出")
                    if ocr_result["json"]:
                        st.json(ocr_result["json"].model_dump())

        if os.path.exists(image_path):
            os.remove(image_path)

else:
    st.info("👆 请先上传一张巡检工人手机拍摄的作业票照片，Agent 将自主完成全部处理流程")
