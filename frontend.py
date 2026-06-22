"""
安全哨兵 - Agent 可视化决策链面板 v2
启动: streamlit run frontend.py
"""

import io, sys, os, re, time, tempfile
from dataclasses import dataclass, field
from typing import List
import streamlit as st

st.set_page_config(page_title="安全哨兵", page_icon="🛡️", layout="wide")

# ---- 紧凑 CSS ----
st.markdown("""
<style>
.block-container { padding-top: 1rem; padding-bottom: 0.5rem; }
.step-card {
    border: 1px solid #2a2a2a; border-radius: 8px;
    padding: 8px 12px; margin-bottom: 6px; background: #111;
}
.step-header { font-weight: 600; font-size: 14px; margin-bottom: 3px; }
.step-action { color: #888; font-size: 12px; margin-bottom: 2px; }
.step-result-ok { color: #00ff41; font-size: 12px; }
.step-result-retry { color: #ffb800; font-size: 12px; }
.step-result-error { color: #ff4444; font-size: 12px; }
.step-result { color: #ccc; font-size: 12px; }
.check-line { font-size: 12px; line-height: 1.5; }
.tool-line { color: #00cc33; font-size: 12px; margin: 1px 0 1px 12px; }
.raw-log {
    background: #0a0a0a; border: 1px solid #222; border-radius: 6px;
    padding: 8px; font-family: monospace; font-size: 11px; color: #555;
    max-height: 200px; overflow-y: auto; line-height: 1.4;
}
.metric-card {
    background: #1a1a2e; border: 1px solid #333; border-radius: 8px;
    padding: 10px 14px; text-align: center;
}
.metric-val { font-size: 22px; font-weight: 700; color: #00d4ff; }
.metric-label { font-size: 11px; color: #888; }
#MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


@dataclass
class AgentStep:
    name: str
    emoji: str
    action: str = ""
    result: str = ""
    status: str = "pending"
    checks: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)


def parse_log_to_steps(lines: List[str]) -> List[AgentStep]:
    step_map = {
        "Plan": ("规划", "📋"), "Perceive": ("感知", "👁️"),
        "Reason": ("推理", "🤔"), "Reflect": ("反思", "🔍"),
        "Act": ("执行", "⚡"), "Report": ("总结", "📊"),
    }
    steps: List[AgentStep] = []
    cur = None

    for line in lines:
        m = re.search(r'\[Agent\s+\S+\s+(\w+)\]\s*(.*)', line)
        if m:
            phase, content = m.group(1), m.group(2)
            if phase in step_map:
                name, emoji = step_map[phase]
                existing = next((s for s in steps if s.name == name), None)
                if existing is None:
                    cur = AgentStep(name=name, emoji=emoji, status="running")
                    steps.append(cur)
                else:
                    cur = existing
                    if cur.status != "done":
                        cur.status = "running"
        if cur is None:
            continue

        if "Plan" in line and "执行计划" in line:
            cur.action = "分析任务并制定执行计划"
        elif "Plan" in line and ("①" in line or "②" in line or "③" in line or "④" in line or "⑤" in line):
            cur.result += line.split("Plan]")[-1].strip() + "\n" if "Plan]" in line else line.strip() + "\n"
            if "⑤" in line:
                cur.status = "done"
        elif "Perceive" in line and ("调用感知" in line or "OpenCV" in line):
            for s in steps:
                if s.name == "规划" and s.status == "running":
                    s.status = "done"
            cur.action = "OpenCV + PaddleOCR 文字识别"
        elif "Perceive" in line and "感知完成" in line:
            cur.result = line.split("感知完成。")[-1] if "感知完成。" in line else line.split("Perceive]")[-1].strip()
            cur.status = "done"
        elif "Reason" in line and ("调用推理" in line or "LLM" in line and "语义" in line):
            cur.action = "LLM 结构化解析"
        elif "Reason" in line and "推理完成" in line:
            cur.result = line.split("推理完成。")[-1] if "推理完成。" in line else line.split("Reason]")[-1].strip()
            cur.status = "done"
        elif "Reflect" in line and ("进入反思" in line or "校验" in line):
            cur.action = "校验数据完整性"
        elif "Reflect" in line and ("OK" in line or "!!" in line):
            cur.checks.append(line.split("Reflect]")[-1].strip() if "Reflect]" in line else line)
        elif "Reflect" in line and "校验通过" in line:
            cur.result = "所有校验通过"
            cur.status = "done"
        elif "Reflect" in line and "未通过" in line:
            cur.status = "retry"
        elif "Reflect" in line and "最大重试" in line:
            cur.result = "标记高风险"
            cur.status = "error"
        elif "Act" in line and "执行工具" in line:
            cur.action = "自主选择工具执行"
        elif "Act" in line and "选择工具" in line:
            cur.tools.append(line.split("选择工具:")[-1].strip() if "选择工具:" in line else line)
        elif "Act" in line and ("SQLite" in line or "已执行" in line):
            cur.result = line.split("Act]")[-1].strip() if "Act]" in line else line
            cur.status = "done"
        elif "Report" in line and "决策链报告" in line:
            cur.action = "输出决策链报告"
        elif "Report" in line and "完成" in line:
            cur.result = line.split("Report]")[-1].strip() if "Report]" in line else line
            cur.status = "done"
        elif "⏱️" in line and steps:
            steps[-1].result += f" | {line.split('耗时:')[-1].strip()}" if "耗时:" in line else ""

    return steps


# ---- 侧边栏：API 配置 ----
with st.sidebar:
    _ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()
    st.markdown(f"### 🛡️ 安全哨兵 v{_ver}")
    st.caption("牡丹江中燃 HSE · AI Agent")
    st.divider()

    api_key = st.text_input("🔑 API Key", os.environ.get("ONLINE_API_KEY", ""), type="password")
    base_url = st.text_input("🌐 Base URL", os.environ.get("ONLINE_BASE_URL", "https://api.siliconflow.cn/v1"))
    model_name = st.text_input("🤖 Model", os.environ.get("ONLINE_MODEL", "Qwen/Qwen2.5-7B-Instruct"))

    st.divider()
    with st.expander("ℹ️ 架构说明", expanded=False):
        st.markdown("""
**ReAct 决策链：**
📋 规划 → 👁️ 感知 → 🤔 推理 → 🔍 反思 → ⚡ 执行 → 📊 总结

**技术栈：**
- OpenCV: 图像去阴影
- PaddleOCR: 文字识别
- LLM: 语义结构化
- SQLite: 数据沉淀
- 企业微信: 隐患预警
        """)


# ---- 主面板 ----
uploaded = st.file_uploader(
    "📷 上传巡检作业票图片",
    type=["jpg", "jpeg", "png", "bmp"],
    accept_multiple_files=False,
    help="手机浏览器可直接唤起摄像头拍摄",
)

if not uploaded:
    st.info("👆 上传作业票照片，Agent 将自主完成：感知 → 推理 → 反思 → 执行")
    st.stop()

# 显示上传图片（紧凑）
col_img, col_btn = st.columns([3, 1])
with col_img:
    st.image(uploaded, caption=f"{uploaded.name} ({uploaded.size/1024:.0f}KB)", width=300)
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    run_btn = st.button("🚀 开始处理", type="primary", use_container_width=True)

if not run_btn:
    st.stop()

# ---- 执行 ----
suffix = os.path.splitext(uploaded.name)[1] or ".jpg"
tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
tmp.write(uploaded.getvalue())
tmp.close()
image_path = tmp.name

raw_logs: List[str] = []
step_ph = st.empty()
log_ph = st.empty()


def render(logs):
    steps = parse_log_to_steps(logs)
    with step_ph.container():
        for i, s in enumerate(steps):
            icon = {"pending": "⬜", "running": "🔄", "done": "✅", "retry": "🔄", "error": "❌"}.get(s.status, "⬜")
            bc = {"done": "#1a3a1a", "running": "#3a3a00", "retry": "#3a2a00", "error": "#3a1a1a"}.get(s.status, "#222")
            st.markdown(f'<div class="step-card" style="border-color:{bc}">', unsafe_allow_html=True)
            st.markdown(f'<div class="step-header">{icon} {s.emoji} {s.name}</div>', unsafe_allow_html=True)
            if s.action:
                st.markdown(f'<div class="step-action">→ {s.action}</div>', unsafe_allow_html=True)
            for t in s.tools:
                st.markdown(f'<div class="tool-line">🔧 {t}</div>', unsafe_allow_html=True)
            for c in s.checks:
                st.markdown(f'<div class="check-line">{c}</div>', unsafe_allow_html=True)
            if s.result:
                cls = {"done": "step-result-ok", "retry": "step-result-retry", "error": "step-result-error"}.get(s.status, "step-result")
                for rl in s.result.strip().split("\n"):
                    if rl.strip():
                        st.markdown(f'<div class="{cls}">{rl.strip()}</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
    with log_ph.expander("📜 原始日志", expanded=False):
        st.markdown(f'<div class="raw-log">{"<br>".join(logs)}</div>', unsafe_allow_html=True)


from agent_core import SecurityAgent, LLMBrain

brain = LLMBrain(api_key=api_key, base_url=base_url, model_name=model_name)
agent = SecurityAgent(brain=brain)

_orig = sys.stdout
result_data = {"text": None, "json": None}


class Capture(io.TextIOBase):
    def write(self, s):
        s = s.strip()
        if s:
            raw_logs.append(s)
            render(raw_logs)
        return len(s) if s else 0
    def flush(self):
        pass


sys.stdout = Capture()  # type: ignore
try:
    ocr_text, structured = agent.run(image_path)
    result_data["text"] = ocr_text
    result_data["json"] = structured
except Exception as e:
    raw_logs.append(f"❌ 出错: {e}")
    render(raw_logs)
finally:
    sys.stdout = _orig

if os.path.exists(image_path):
    os.path.exists(image_path) and os.remove(image_path)

# ---- 结果展示 ----
if result_data["json"]:
    d = result_data["json"]
    st.divider()

    # 指标卡片
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{d.ticket_id}</div><div class="metric-label">作业票号</div></div>', unsafe_allow_html=True)
    with c2:
        color = "#ff4444" if d.has_abnormal else "#00ff41"
        val = f"{len(d.issues)} 项" if d.has_abnormal else "正常"
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:{color}">{val}</div><div class="metric-label">安全隐患</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{len(d.safety_measures)}</div><div class="metric-label">安全措施</div></div>', unsafe_allow_html=True)
    with c4:
        conc = ", ".join(f"{v}%" for v in d.gas_concentration) if d.gas_concentration else "无数据"
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="font-size:16px">{conc}</div><div class="metric-label">气体浓度</div></div>', unsafe_allow_html=True)

    # 详情
    tab_json, tab_ocr, tab_issues = st.tabs(["📦 结构化数据", "📝 OCR 原文", f"⚠️ 隐患明细 ({len(d.issues)})"])

    with tab_json:
        st.json(d.model_dump())
    with tab_ocr:
        if result_data["text"]:
            st.code(result_data["text"], language=None)
    with tab_issues:
        if d.issues:
            for issue in d.issues:
                st.markdown(f"- **{issue.item_name}** — {issue.status}" + (f" ({issue.raw_text})" if issue.raw_text else ""))
        else:
            st.success("无隐患，所有检查项正常。")
