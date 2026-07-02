"""
可复用 UI 组件库 — 安全数字监督员
所有共享的渲染逻辑、常量、工具函数统一收归此处。
"""

import streamlit as st
import requests as _req


# ============================================================
# 常量
# ============================================================

RISK_COLOR = {
    "重大": "#d6131c", "较大": "#d97706",
    "一般": "#d97706", "低风险": "#059669",
}
RISK_ICON = {
    "重大": "🔴", "较大": "🟡",
    "一般": "🟡", "低风险": "🟢",
}
RISK_ST_COLOR = {
    "重大": "red", "较大": "orange",
    "一般": "orange", "低风险": "green",
}
APPROVAL_COLOR = {
    "自动通过": "#059669", "待审批": "#0052CC", "已驳回": "#d6131c",
}
APPROVAL_ICON = {
    "自动通过": "✅", "待审批": "⏳", "已驳回": "🚫",
}


# ============================================================
# 原子组件（返回 HTML 字符串）
# ============================================================

def kpi(label: str, value: str, color: str = "var(--blue)") -> str:
    """单个 KPI 数据卡 HTML。"""
    return (
        f'<div class="kpi">'
        f'<div class="kpi-val" style="color:{color}">{value}</div>'
        f'<div class="kpi-lbl">{label}</div>'
        f'</div>'
    )


def badge(text: str, level: str = "ok") -> str:
    """状态徽章 HTML。level: ok | warn | err"""
    return f'<span class="badge badge-{level}">{text}</span>'


# ============================================================
# 组合组件（直接渲染到页面）
# ============================================================

def render_kpi_row(items: list) -> None:
    """
    自动分列渲染 KPI 卡片行。

    Args:
        items: [(label, value, color), ...]  color 可为空字符串用默认色。
    """
    if not items:
        return
    cols = st.columns(len(items))
    for col, (label, value, color) in zip(cols, items):
        with col:
            st.markdown(kpi(label, value, color or "var(--blue)"), unsafe_allow_html=True)


def render_ticket_kpis(d) -> None:
    """
    单张作业票的完整结果摘要：KPI 行 + 审批建议。

    Args:
        d: SecuritySheetData — agent_core 结构化结果。
    """
    rl = d.risk_level or "-"
    status_color = "#d6131c" if d.has_abnormal else "#059669"
    status_text = f"{len(d.issues)}项" if d.has_abnormal else "正常"
    conc_text = ", ".join(f"{v}%" for v in d.gas_concentration) or "无"
    ap_status = d.approval_status or "-"
    ap_color = APPROVAL_COLOR.get(ap_status, "#0052CC")

    render_kpi_row([
        ("票号", d.ticket_id, ""),
        ("状态", status_text, status_color),
        ("风险", rl, RISK_COLOR.get(rl, "#0052CC")),
        ("浓度", conc_text, ""),
        ("审批", ap_status, ap_color),
    ])

    # 审批建议
    if d.approval_opinion:
        ic = APPROVAL_ICON.get(ap_status, RISK_ICON.get(d.risk_level or "", ""))
        if ap_status == "已驳回":
            st.error(f"{ic} {d.approval_opinion}")
        elif ap_status == "待审批":
            st.warning(f"{ic} {d.approval_opinion}")
        else:
            st.success(f"{ic} {d.approval_opinion}")


def render_guide(step: int, text: str) -> None:
    """
    操作引导步骤条。

    Args:
        step: 步骤序号（1, 2, ...）。
        text: 引导文案（可含 <b> 等 HTML 标签）。
    """
    st.markdown(
        f'<div class="guide-box">'
        f'<span style="background:linear-gradient(120deg,#FF1E27,#0052CC);color:#fff;'
        f'padding:2px 9px;border-radius:6px;font-size:12px;font-weight:700;'
        f'white-space:nowrap">第 {step} 步</span> {text}'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_notification_btn(
    platform: str,
    emoji: str,
    mcp_key: str,
    msg_fmt,
    d,
    idx: int,
    cfg: dict,
) -> None:
    """
    钉钉 AI 表格写入按钮。

    Args:
        platform:    显示名，如 "钉钉 AI 表格"。
        emoji:       按钮前缀 emoji。
        mcp_key:     cfg 中的 key，如 "dingtalk_mcp_url"。
        msg_fmt:     callable(d) -> (msgtype: str, content: str)。
        d:           结果数据对象（需有 ticket_id, station_name 等属性）。
        idx:         唯一 key 后缀（防 Streamlit key 冲突）。
        cfg:         应用配置字典。
    """
    url = cfg.get(mcp_key, "")
    key = f"{mcp_key}_{idx}"

    if not url:
        st.error(f"⚠️ 未配置钉钉 MCP 地址，无法写入 AI 表格")
        st.button(
            f"{emoji} 写入{platform}", key=key,
            use_container_width=True, disabled=True,
            help=f"请在左侧「钉钉 MCP 地址」中配置后重试",
        )
        return

    if st.button(f"{emoji} 写入{platform}", key=key, use_container_width=True):
        # 导入 agent 工具写表格
        from agent_core import AgentTools
        _, content = msg_fmt(d)
        # 写 AI 表格：编号 / 图片附件 / 问题描述 / 责任人 / 等级
        result = AgentTools.write_dingtalk_table(
            ticket_id=d.ticket_id,
            image_path="",  # 手动触发时无图片路径
            description=content[:200],
            person_name=AgentTools.extract_filler_name("", d.worker_id or ""),
            risk_level=d.risk_level or "",
        )
        if result:
            st.success(f"✅ 已写入{platform}")
        else:
            st.error(f"写入{platform}失败，请查看运行日志")


def render_record_badge(risk: str | None, abnormal: bool) -> str:
    """
    Tab2 记录列表中的风险/状态徽章（Streamlit markdown 语法）。

    Args:
        risk:     风险等级（"重大"/"较大"/"一般"/"低风险"/None）。
        abnormal: 是否有隐患。

    Returns:
        如 " | :red[重大]" 的 markdown 片段，无风险时返回空串。
    """
    if not risk:
        return ""
    st_color = RISK_ST_COLOR.get(risk, "blue")
    return f" | :{st_color}[{risk}]"
