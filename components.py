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
        f'<span class="guide-badge">第 {step} 步</span> {text}'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_notification_btn(
    platform: str,
    emoji: str,
    webhook_key: str,
    msg_fmt,
    d,
    idx: int,
    cfg: dict,
) -> None:
    """
    通用通知推送按钮（钉钉/微信等）。

    未配置 Webhook → disabled 按钮 + 提示文案。
    已配置 → 点击发送，显示成功/失败反馈。

    Args:
        platform:    显示名，如 "钉钉"。
        emoji:       按钮前缀 emoji。
        webhook_key: cfg 中的 key，如 "dingtalk_webhook"。
        msg_fmt:     callable(d) -> (msgtype: str, content: str)。
        d:           结果数据对象（需有 ticket_id, station_name 等属性）。
        idx:         唯一 key 后缀（防 Streamlit key 冲突）。
        cfg:         应用配置字典。
    """
    url = cfg.get(webhook_key, "")
    key = f"{webhook_key}_{idx}"

    if not url:
        st.button(
            f"{emoji} 发送{platform}", key=key,
            use_container_width=True, disabled=True,
            help=f"请在侧边栏通知设置中配置{platform} Webhook",
        )
        st.caption(f"⚠️ 未配置{platform} Webhook，请在左侧边栏设置")
        return

    if st.button(f"{emoji} 发送{platform}", key=key, use_container_width=True):
        msgtype, content = msg_fmt(d)
        try:
            resp = _req.post(
                url,
                json={"msgtype": msgtype, msgtype: {"content": content}},
                timeout=10,
            )
            if resp.status_code == 200:
                st.success(f"✅ {platform}发送成功")
            else:
                st.error(f"发送失败: {resp.status_code}")
        except Exception as e:
            st.error(f"发送失败: {e}")


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
