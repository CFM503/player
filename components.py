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
}  # 结束风险颜色字典定义
RISK_ICON = {  # 定义不同风险级别显示的警告标志 emoji 字典
    "重大": "🔴", "较大": "🟡",  # 重大风险使用红球，较大风险使用黄球
    "一般": "🟡", "低风险": "🟢",  # 一般风险使用黄球，低风险使用绿球
}  # 结束风险标志字典定义
RISK_ST_COLOR = {  # 定义 Streamlit markdown 彩色字体所支持的颜色名称字典
    "重大": "red", "较大": "orange",  # 重大风险映射为 red 红色，较大风险为 orange 橙色
    "一般": "orange", "低风险": "green",  # 一般风险为 orange，低风险为 green 绿色
}  # 结束映射定义
APPROVAL_COLOR = {  # 定义审批流程各种状态的颜色配置字典
    "自动通过": "#059669", "待审批": "#0052CC", "已驳回": "#d6131c",  # 自动通过为绿色，待审批为蓝色，已驳回为红色
}  # 结束审批颜色定义
APPROVAL_ICON = {  # 定义审批状态代表的 emoji 徽章字典
    "自动通过": "✅", "待审批": "⏳", "已驳回": "🚫",  # 通过显示对勾，等待显示沙漏，拒绝显示禁止符
}  # 结束审批徽章定义


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
    
    render_kpi_row([  # 调用 KPI 行渲染组件渲染这 4 个关键的作业票数据卡片
        ("票号", d.ticket_id, ""),  # 作业票票号指标
        ("状态", status_text, status_color),  # 隐患状态指标
        ("风险", rl, RISK_COLOR.get(rl, "#0052CC")),  # 风险评级指标
        ("审批", ap_status, ap_color),  # 智能流程审批状态指标
    ])  # 结束数组定义

    # 审批建议
    if d.approval_opinion:  # 检查该作业票是否含有由 Agent 产出的审批意见文本
        ic = APPROVAL_ICON.get(ap_status, RISK_ICON.get(d.risk_level or "", ""))  # 获取匹配状态的 emoji 徽章，作为消息前缀
        
        # 格式化提取的核心变量信息，末尾附加 [变量名]
        info_lines = [
            f"作业票编号：{d.ticket_id or ''} [ticket_id]",
            f"作业单位：{d.station_name or ''} [station_name]",
            f"作业内容：{d.content or ''} [content]",
            f"作业时间：{d.work_time or ''} [work_time]",
            f"作业人姓名及证书编号：{d.worker_id or ''} [worker_id]",
            f"发起人签字确认：{d.approver_name or ''} [approver_name]"
        ]
        info_block = "\n\n".join(info_lines)
        
        # 拼接审批结果与核心信息
        full_text = f"{ic} {d.approval_opinion}\n\n---\n\n{info_block}"
        
        if ap_status == "已驳回":  # 若审批被智能判定驳回拒绝
            st.error(full_text)  # 在 Streamlit 界面显示红色的 error 级别错误框提示
        elif ap_status == "待审批":  # 若属于需人工流转审批
            st.warning(full_text)  # 在 Streamlit 界面显示黄色的 warning 警告框提示
        else:  # 若属于自动通过的安全范畴
            st.success(full_text)  # 在 Streamlit 界面显示绿色的 success 成功成功框提示


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


def render_notification_btn(  # 定义用于将作业数据写入钉钉 MCP AI 表格的动作按钮组件函数
    platform: str,  # 参数一：写入目的地平台的显示名称，如 "钉钉 AI 表格"
    emoji: str,  # 参数二：显示在按钮左侧的前缀表情，如 "📱"
    mcp_key: str,  # 参数三：配置项中代表 MCP 路由基地址的键名，如 "dingtalk_mcp_url"
    msg_fmt,  # 参数四：回调函数格式化器，根据结果生成要存入多维表的摘要说明文字
    d,  # 参数五：待处理的整个作业票安全数据结果实体对象
    idx: int,  # 参数六：防止 Streamlit 出现按键 key 冲突而特别需要的唯一数字索引号
    cfg: dict,  # 参数七：应用当前运行加载的全部配置数据字典
) -> None:  # 表明此渲染逻辑没有返回值
    # 构建带有 MCP 校验的通知写入按钮
    url = cfg.get(mcp_key, "")  # 尝试从应用配置中获取钉钉 MCP 的路由服务基地址
    key = f"{mcp_key}_{idx}"  # 合成一个确保在该行表格详情内唯一的交互控件 key 值

    if not url:  # 判断用户是否尚未在应用左侧侧边栏中配置该 MCP 地址
        st.error(f"⚠️ 未配置钉钉 MCP 地址，无法写入 AI 表格")  # 在界面上弹窗红色提示指出配置项缺失错误
        st.button(  # 渲染一个不可被点击的失效灰色按钮
            f"{emoji} 写入{platform}", key=key,  # 按钮标题内容，附带后缀 key 进行控制
            use_container_width=True, disabled=True,  # 设置按钮拉伸平铺填满宽度，并设置为禁用失效状态
            help=f"请在左侧「钉钉 MCP 地址」中配置后重试",  # 当用户鼠标悬浮时展示气泡提示
        )  # 结束按钮定义
        return  # 提前阻断返回，跳过后续真实的交互行为

    if st.button(f"{emoji} 写入{platform}", key=key, use_container_width=True):  # 当检测到用户真实点击了这一行对应的写入按钮时
        # 导入 agent 模块以获取运行期实时更新的全局变量
        import agent_core  # 动态按需引入智能体核心模块以读取全局坐标
        AgentTools = agent_core.AgentTools
        if hasattr(d, "image_path") and d.image_path:
            AgentTools._last_image_path = d.image_path
        _, content = msg_fmt(d)  # 解包获取回调格式化器生成的隐患详细报告文字
        # 写 AI 表格：编号 / 图片附件 / 问题描述 / 责任人 / 等级
        result = AgentTools.write_dingtalk_table(  # 调用 AgentTools 中的底层多维表 MCP 写入工具方法
            ticket_id=d.ticket_id,  # 传入识别所得的作业票编号
            image_path="",  # 手动点击触发时通常无局部大图文件缓存，传递空字符串
            description=content[:200],  # 截取报告文本前 200 字存入问题描述字段中
            person_name=AgentTools.extract_filler_name(630, 190, 195, 150),  # 直接使用固定裁剪范围进行责任人姓名提取
            risk_level=d.risk_level or "",  # 写入识别并给出的安全风险级别
        )  # 结束调用并接收布尔返回值状态
        if result:  # 如果底层 MCP 返回成功写入的确认
            st.success(f"✅ 已写入{platform}")  # 在该按钮下方渲染绿色的成功提示框
        else:  # 若写入发生异常或接口超时失败
            st.error(f"写入{platform}失败，请查看运行日志")  # 渲染红色的写入失败指示框，提醒用户排错


def render_record_badge(risk: str | None, abnormal: bool) -> str:  # 定义用于在历史看版 Tab2 的摘要条中渲染彩字风险级别的函数
    # 拼接并生成彩色指示后缀
    if not risk:  # 判断该条目是否尚无评估风险级别
        return ""  # 若没有，返回空串不追加任何后缀
    st_color = RISK_ST_COLOR.get(risk, "blue")  # 根据风险名在 Streamlit 颜色字典中提取出对应的文本着色名称
    return f" | :{st_color}[{risk}]"  # 拼接并返回满足 Streamlit Markdown 着色语法的彩色标记字符串后缀，如 " | :red[重大]"
