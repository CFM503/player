# -*- coding: utf-8 -*-
"""
可复用 UI 组件库 — 安全数字监督员
所有共享的渲染逻辑、常量、工具函数统一收归此处。
"""

import streamlit as st  # 导入 Streamlit 核心前端库，用于界面布局与内容显示
import requests as _req  # 导入 requests 库，作为底层可能需要的 HTTP 请求请求库


# ============================================================
# 常量
# ============================================================

RISK_COLOR = {  # 定义不同风险等级所对应的十六进制颜色字典
    "重大": "#d6131c", "较大": "#d97706",  # 重大风险对应深红色，较大风险对应深黄色
    "一般": "#d97706", "低风险": "#059669",  # 一般风险对应黄色，低风险对应深绿色
    # 带气作业票表头作业等级：一级危险最高
    "一级": "#d6131c", "二级": "#d97706", "未识别": "#6b7280", "未填": "#6b7280",
}  # 结束风险颜色字典定义
RISK_ICON = {  # 定义不同风险级别显示的警告标志 emoji 字典
    "重大": "🔴", "较大": "🟡",  # 重大风险使用红球，较大风险使用黄球
    "一般": "🟡", "低风险": "🟢",  # 一般风险使用黄球，低风险使用绿球
    "一级": "🔴", "二级": "🟡", "未识别": "⚪", "未填": "⚪",
}  # 结束风险标志字典定义
RISK_ST_COLOR = {  # 定义 Streamlit markdown 彩色字体所支持的颜色名称字典
    "重大": "red", "较大": "orange",  # 重大风险映射为 red 红色，较大风险为 orange 橙色
    "一般": "orange", "低风险": "green",  # 一般风险为 orange，低风险为 green 绿色
    "一级": "red", "二级": "orange", "未识别": "gray", "未填": "gray",
}  # 结束映射定义
APPROVAL_COLOR = {  # 定义审批流程各种状态的颜色配置字典
    "自动通过": "#059669", "待审批": "#0052CC", "已驳回": "#d6131c",  # 自动通过为绿色，待审批为蓝色，已驳回为红色
}  # 结束审批颜色定义
APPROVAL_ICON = {  # 定义审批状态代表的 emoji 徽章字典
    "自动通过": "✅", "待审批": "⏳", "已驳回": "🚫",  # 通过显示对勾，等待显示沙漏，拒绝显示禁止符
}  # 结束审批徽章定义
# 审批状态 → 人工介入说明（人工介入 = MCP 推送钉钉 AI 表格）
APPROVAL_HINT = {
    "自动通过": "系统自动通过",
    "待审批": "人工介入：经 MCP 推送钉钉 AI 表格，主管在钉钉侧处理",
    "已驳回": "禁止放行：经 MCP 推送钉钉 AI 表格，主管在钉钉侧处理",
}


# ============================================================
# 原子组件（返回 HTML 字符串）
# ============================================================

def kpi(label: str, value: str, color: str = "var(--blue)") -> str:  # 定义构建单个 KPI 信息指标卡片 HTML 代码的函数
    # 拼接并生成指标卡片的 HTML 字符串
    return (  # 返回拼接出的 HTML 代码字符串对象
        f'<div class="kpi">'  # 卡片最外层容器元素，添加自定义的 kpi 样式类
        f'<div class="kpi-val" style="color:{color}">{value}</div>'  # 指标主要数值元素，使用指定的字体色呈现
        f'<div class="kpi-lbl">{label}</div>'  # 指标底部名称标签文本
        f'</div>'  # 结束最外层卡片容器元素
    )  # 结束返回值定义


def badge(text: str, level: str = "ok") -> str:  # 定义生成简单状态徽章 HTML 代码的原子组件函数
    """状态徽章 HTML。level: ok | warn | err"""
    return f'<span class="badge badge-{level}">{text}</span>'  # 根据参数拼接并返回徽章对应的 HTML span 标签


# ============================================================
# 组合组件（直接渲染到页面）
# ============================================================

def render_kpi_row(items: list) -> None:  # 定义一整行分栏展示多个 KPI 统计卡片的渲染函数
    # 构建一整行的 KPI 结构布局
    if not items:  # 判断传入的 KPI 指标数组是否为空
        return  # 若空则跳过，不渲染任何界面
    cols = st.columns(len(items))  # 调用 Streamlit 的 columns 方法根据指标数量创建对应数量的分栏列对象
    for col, (label, value, color) in zip(cols, items):  # 将列对象与对应的指标参数元组进行一一配对循环处理
        with col:  # 开启当前列的上下运行上下文
            st.markdown(kpi(label, value, color or "var(--blue)"), unsafe_allow_html=True)  # 在列中渲染生成的数据卡片 HTML，开启 HTML 解析


def render_ticket_kpis(d) -> None:  # 定义单张作业票的完整摘要信息展示函数
    # 提取作业票属性生成指标栏
    rl = d.risk_level or "-"  # 提取获取风险等级，若不存在则使用 "-" 占位
    status_color = "#d6131c" if d.has_abnormal else "#059669"  # 根据是否存在隐患判定状态卡的颜色，异常为红，正常为绿
    status_text = f"{len(d.issues)}项" if d.has_abnormal else "正常"  # 判断状态文本：有隐患时显示隐患条数，无隐患显示正常
    ap_status = d.approval_status or "-"  # 提取审批状态值，不存在默认为 "-"
    ap_color = APPROVAL_COLOR.get(ap_status, "#0052CC")  # 根据状态从颜色字典中提取对应的色值
    
    # 带气主流程展示「作业等级」（一级/二级）
    risk_label = "作业等级"
    render_kpi_row([
        ("票号", d.ticket_id, ""),
        ("状态", status_text, status_color),
        (risk_label, rl if rl != "-" else "未识别", RISK_COLOR.get(rl, "#0052CC")),
        ("审批", ap_status, ap_color),
    ])
    # 审批状态旁注：人工介入 = MCP → 钉钉 AI 表格
    ap_hint = APPROVAL_HINT.get(ap_status, "")
    if ap_hint:
        st.caption(ap_hint)

    # 审批建议
    if d.approval_opinion:  # 检查该作业票是否含有由 Agent 产出的审批意见文本
        ic = APPROVAL_ICON.get(ap_status, RISK_ICON.get(d.risk_level or "", ""))  # 获取匹配状态的 emoji 徽章，作为消息前缀
        
        # 格式化提取的核心变量信息，末尾附加 [变量名]
        grade_line = ""
        gl = d.risk_level or "未识别"
        grade_line = (
            f"作业等级：{gl}"
            + ("（一级危险最高）" if gl == "一级" else "")
            + ("（识别失败·禁止兜底）" if not d.risk_level else "")
            + " [risk_level]"
        )
        info_lines = [
            f"作业票编号：{d.ticket_id or ''} [ticket_id]",
            f"作业单位：{d.station_name or ''} [station_name]",
            f"作业内容：{d.content or ''} [content]",
            f"作业时间：{d.work_time or ''} [work_time]",
            f"作业人姓名及证书编号：{d.worker_id or ''} [worker_id]",
        ]
        if grade_line:
            info_lines.append(grade_line)
        info_lines += [
            f"发起人签字确认：{d.approver_name or ''} [approver_name]",
            f"作业人员：{d.operators or ''} [operators]",
            f"施工方现场负责人：{d.construction_leader or ''} [construction_leader]",
            f"监理人员：{d.supervisor or ''} [supervisor]",
            f"项目公司监护人：{d.company_monitor or ''} [company_monitor]",
            f"带气现场负责人：{d.gas_leader or ''} [gas_leader]",
        ]
        if ap_hint:
            info_lines.append(f"审批路径：{ap_hint}")
        info_block = "\n\n".join(info_lines)
        
        # 拼接审批结果与核心信息
        full_text = f"{ic} {d.approval_opinion}\n\n---\n\n{info_block}"
        
        if ap_status == "已驳回":  # 禁止放行 → 钉钉人工介入
            st.error(full_text)
        elif ap_status == "待审批":  # 人工介入：MCP 推送钉钉 AI 表格
            st.warning(full_text)
        else:  # 自动通过
            st.success(full_text)


def render_guide(step: int, text: str) -> None:  # 定义顶部操作向导提示框的渲染函数
    # 渲染生成带渐变背景的第 N 步向导卡片
    st.markdown(  # 在页面渲染 markdown 内容，开启 HTML 标签解析
        f'<div class="guide-box">'  # 外层大提示框容器开始标签
        f'<span style="background:linear-gradient(120deg,#FF1E27,#0052CC);color:#fff;'  # 设置带红蓝线性渐变背景的徽标标签
        f'padding:2px 9px;border-radius:6px;font-size:12px;font-weight:700;'  # 设置内部微调边距和文字大小粗细样式
        f'white-space:nowrap">第 {step} 步</span> {text}'  # 徽章内容及后面的详细向导说明文本
        f'</div>',  # 结束提示框标签
        unsafe_allow_html=True,  # 允许解析内部的 style 和 span 标签
    )  # 结束 markdown 渲染调用





def render_record_badge(grade: str | None, abnormal: bool) -> str:
    """历史列表标题后缀：作业等级着色（一级/二级 或旧值兼容）。"""
    if not grade or grade in ("-", "未识别", "未填"):
        return ""
    st_color = RISK_ST_COLOR.get(grade, "blue")
    return f" · :{st_color}[{grade}]"
