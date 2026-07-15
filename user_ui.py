# -*- coding: utf-8 -*-
"""
用户页 — PPT 第 4 页极简风格
- 左侧 + ：上传作业票
- 右侧 ↑ ：提交处理
参数跟随管理页；无拍照入口
"""

from __future__ import annotations

import html as _html
import io
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="paddle")

import streamlit as st

from components import APPROVAL_COLOR, APPROVAL_HINT, APPROVAL_ICON, RISK_COLOR
from process_helpers import (
    build_agent_from_config,
    config_ready,
    get_effective_config,
    run_ticket,
    save_uploaded_bytes,
)
from styles import USER_CSS

_ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()
st.markdown(USER_CSS, unsafe_allow_html=True)

# ---- session ----
for _k, _v in {
    "user_result": None,
    "user_processing": False,
    "user_uploader_key": 0,
    "user_job_name": None,
    "user_job_bytes": None,
    "user_ticket_type": "带气作业票",
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

cfg = get_effective_config()
ready = config_ready(cfg)

_engine = cfg.get("ocr_engine", "paddleocr")
_device = cfg.get("ocr_device", "gpu")
_model = cfg.get("model_name") or "-"
_engine_lbl = "视觉大模型" if _engine == "vision" else "PaddleOCR"
_dd_ok = bool(cfg.get("dingtalk_mcp_url"))

# ---- Hero ----
st.markdown(
    f"""
<div class="user-hero">
  <div class="user-hero-title">一句话，跑通全流程。</div>
  <p class="user-hero-sub">点 + 选票 · 点 ↑ 提交或重新提交</p>
</div>
""",
    unsafe_allow_html=True,
)

if not ready:
    st.warning("尚未配置 API Key。请到左侧 **管理测试** 填写并保存，本页会自动同步参数。")
    st.stop()

# ---- 票型（与管理页一致：带气 / 动火完全分路）----
st.radio(
    "作业票类型",
    options=["带气作业票", "动火作业票"],
    horizontal=True,
    key="user_ticket_type",
    help="带气与动火使用不同模板与校验规则，互不交叉。",
)

# ---- 胶囊条：+ 上传 | 文案 | 安全监督员 | ↑ 提交 ----
c_plus, c_text, c_brand, c_send = st.columns([0.9, 4.0, 1.7, 0.95], gap="small")

with c_plus:
    picked = st.file_uploader(
        "upload",
        type=["jpg", "jpeg", "png", "bmp"],
        accept_multiple_files=False,
        label_visibility="collapsed",
        key=f"user_fu_{st.session_state.user_uploader_key}",
    )

# 选中后写入会话，便于点 ↑ 时仍可用
if picked is not None:
    st.session_state.user_job_name = getattr(picked, "name", None) or "ticket.jpg"
    st.session_state.user_job_bytes = picked.getvalue()

has_file = bool(st.session_state.user_job_bytes)
_tt_lbl = st.session_state.get("user_ticket_type") or "带气作业票"
mid_label = st.session_state.user_job_name if has_file else f"选一张{_tt_lbl}"
mid_cls = "prompt-mid-text" if has_file else "prompt-mid-text muted"

with c_text:
    st.markdown(f'<p class="{mid_cls}">{_html.escape(mid_label)}</p>', unsafe_allow_html=True)

with c_brand:
    st.markdown('<p class="prompt-brand-label">安全监督员</p>', unsafe_allow_html=True)

with c_send:
    submit = st.button(
        "↑",
        type="primary",
        use_container_width=True,
        disabled=not has_file or st.session_state.user_processing,
        help="提交 / 重新提交",
        key="user_submit",
    )

st.markdown(
    f"""
<p class="user-hint">
  {_engine_lbl} · {_device.upper()} · {_html.escape(str(_model)[:28])}
  · 钉钉{"已配" if _dd_ok else "未配"}
  · v{_ver}
</p>
""",
    unsafe_allow_html=True,
)

# ---- ↑ 提交 / 重新提交：点按钮后直接执行，去掉中间空 rerun ----
if submit and has_file and not st.session_state.user_processing:
    st.session_state.user_result = None
    st.session_state.user_processing = True

if st.session_state.user_processing and st.session_state.user_job_bytes:
    st.session_state.user_processing = False
    job_name = st.session_state.user_job_name or "ticket.jpg"
    job_bytes = st.session_state.user_job_bytes

    status = st.empty()
    bar = st.progress(0)

    stage_pct = {
        "Plan": 10, "Perceive": 28, "Reason": 52,
        "Reflect": 72, "Act": 88, "Report": 96,
    }
    stage_cn = {
        "Plan": "规划",
        "Perceive": "感知 · 识别",
        "Reason": "推理 · 结构化",
        "Reflect": "反思 · 校验",
        "Act": "执行 · 审批",
        "Report": "总结 · 入库",
    }

    def prog_cb(pct: int, msg: str = ""):
        p = max(0, min(100, int(pct)))
        bar.progress(p)
        status.caption(f"{msg or '处理中'} · {p}%")

    class _Cap(io.TextIOBase):
        def write(self, s):
            s = (s or "").strip()
            if not s:
                return 0
            for line in s.split("\n"):
                line = line.strip()
                if not line:
                    continue
                for k, p in stage_pct.items():
                    if f"Agent {k}" in line:
                        prog_cb(p, stage_cn[k])
            return len(s)

        def flush(self):
            pass

    try:
        cfg = get_effective_config()
        status.caption("保存图片…")
        bar.progress(4)
        path = save_uploaded_bytes(job_name, job_bytes)

        status.caption("加载管理页参数 · 初始化引擎…")
        bar.progress(8)
        agent = build_agent_from_config(cfg)

        t0 = time.time()
        _orig = sys.stdout
        sys.stdout = _Cap()
        try:
            ocr_text, data = run_ticket(
                agent,
                path,
                progress_callback=prog_cb,
                ticket_type=st.session_state.get("user_ticket_type") or "带气作业票",
            )
        finally:
            sys.stdout = _orig

        bar.progress(100)
        elapsed = int(time.time() - t0)
        status.caption(f"完成 · 用时 {elapsed}s")
        st.session_state.user_result = {
            "ocr": ocr_text,
            "data": data,
            "image_path": path,
            "name": job_name,
            "elapsed": elapsed,
            "cfg_engine": cfg.get("ocr_engine"),
            "cfg_device": cfg.get("ocr_device"),
        }
    except Exception as e:
        bar.progress(100)
        status.error(f"处理失败：{e}")
        st.session_state.user_result = None

# ---- 审批结果 ----
res = st.session_state.user_result
if res and res.get("data"):
    d = res["data"]
    ap = d.approval_status or "-"
    ap_color = APPROVAL_COLOR.get(ap, "#0052CC")
    icon = APPROVAL_ICON.get(ap, "📋")
    hint = APPROVAL_HINT.get(ap, "")
    rl = d.risk_level or "未识别"
    status_text = f"{len(d.issues)} 项问题" if d.has_abnormal else "正常"
    status_color = "#d6131c" if d.has_abnormal else "#059669"

    if ap == "已驳回":
        box_cls = "approval-reject"
    elif ap == "待审批":
        box_cls = "approval-wait"
    else:
        box_cls = "approval-ok"

    opinion = (d.approval_opinion or "（无审批建议文本）").strip()
    opinion_esc = _html.escape(opinion)
    hint_esc = _html.escape(hint) if hint else ""

    st.markdown(
        f"""
<div class="result-card">
  <div class="result-kpis">
    <div class="result-kpi"><div class="v">{_html.escape(d.ticket_id or "-")}</div><div class="l">票号</div></div>
    <div class="result-kpi"><div class="v" style="color:{RISK_COLOR.get(rl, '#111')}">{_html.escape(rl)}</div><div class="l">作业等级</div></div>
    <div class="result-kpi"><div class="v" style="color:{status_color}">{_html.escape(status_text)}</div><div class="l">状态</div></div>
    <div class="result-kpi"><div class="v" style="color:{ap_color}">{_html.escape(ap)}</div><div class="l">审批</div></div>
  </div>
  <div class="approval-box {box_cls}">
    <div class="approval-title">{icon} 审批建议</div>
    <div>{opinion_esc}</div>
    {f'<div style="margin-top:0.65rem;opacity:0.85;font-size:0.82rem">{hint_esc}</div>' if hint_esc else ''}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    if d.issues:
        with st.expander(f"问题明细（{len(d.issues)}）", expanded=True):
            for issue in d.issues:
                reason = issue.raw_text or "OCR 识别为异常"
                st.markdown(f"- **{issue.item_name}** — {reason}")

    with st.expander("更多信息", expanded=False):
        st.markdown(
            f"""
| 项目 | 内容 |
|---|---|
| 作业单位 | {d.station_name or "-"} |
| 作业内容 | {d.content or "-"} |
| 作业时间 | {d.work_time or "-"} |
| 发起人 | {d.approver_name or "-"} |
| 用时 | {res.get("elapsed", "-")}s |
| OCR | {res.get("cfg_engine", "-")} / {res.get("cfg_device", "-")} |
"""
        )
        if res.get("image_path") and os.path.exists(res["image_path"]):
            st.image(res["image_path"], caption=res.get("name", ""), use_container_width=True)

elif res is not None and not res.get("data"):
    st.error("未能生成审批结果。请到「管理测试」用同一张图查看完整日志。")
elif not st.session_state.user_processing and st.session_state.user_result is None:
    st.markdown(
        '<p class="user-hint" style="margin-top:1rem">点 + 选票，点 ↑ 提交；再次点 ↑ 可重新提交</p>',
        unsafe_allow_html=True,
    )
