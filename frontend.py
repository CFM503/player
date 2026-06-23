"""
安全数字监督员 - AI Agent 安全监控面板
启动: streamlit run frontend.py
"""

import io, sys, os, re, time, json
import streamlit as st
import pandas as pd

# ---- 配置 ----
_cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
_cfg = json.load(open(_cfg_path, encoding="utf-8")) if os.path.exists(_cfg_path) else {}
_ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()

st.set_page_config(page_title="安全数字监督员", page_icon="🛡️", layout="wide", initial_sidebar_state="collapsed")

# ---- 全局暗色主题 CSS ----
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');

:root {{
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --green: #3fb950; --red: #f85149; --yellow: #d29922; --blue: #58a6ff; --cyan: #39d353;
    --text: #c9d1d9; --dim: #8b949e;
}}

/* 全局 */
.stApp {{ background: var(--bg); }}
.block-container {{ padding: 0.4rem 1rem 0.2rem 1rem; max-width: 100%; }}
#MainMenu, footer, header {{ display: none !important; }}

/* 侧边栏 */
section[data-testid="stSidebar"] {{ background: var(--card); border-right: 1px solid var(--border); }}
section[data-testid="stSidebar"] .block-container {{ padding-top: 0.5rem; }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{ gap: 0; background: var(--card); border-radius: 6px; padding: 2px; border: 1px solid var(--border); }}
.stTabs [data-baseweb="tab"] {{ color: var(--dim); font-size: 13px; padding: 6px 16px; border-radius: 4px; }}
.stTabs [aria-selected="true"] {{ color: var(--text) !important; background: var(--bg) !important; }}

/* 上传区 - 自适应宽度 */
[data-testid="stFileUploader"], [data-testid="stCameraInput"] {{ padding: 0 !important; margin: 0 !important; }}
[data-testid="stFileUploader"] section, [data-testid="stCameraInput"] section {{
    background: var(--card) !important; border: 1px dashed var(--border) !important;
    border-radius: 6px !important; padding: 4px 8px !important; min-height: 0 !important;
}}
/* 上传区 - 统一蓝色按钮外观 */
[data-testid="stFileUploader"], [data-testid="stCameraInput"] {{ padding: 0 !important; margin: 0 !important; }}
[data-testid="stFileUploader"] section, [data-testid="stCameraInput"] section {{
    background: #007BFF !important; border: none !important;
    border-radius: 8px !important; padding: 8px 16px !important;
    min-height: 40px !important; display: flex !important; align-items: center !important; justify-content: center !important;
}}
[data-testid="stFileUploader"] label, [data-testid="stCameraInput"] label {{ color: #fff !important; font-size: 14px !important; font-weight: 500 !important; }}
[data-testid="stFileUploader"] section svg, [data-testid="stCameraInput"] section svg {{ fill: #fff !important; }}
[data-testid="stFileUploader"] section p, [data-testid="stCameraInput"] section p {{ color: rgba(255,255,255,0.8) !important; font-size: 12px !important; }}
[data-testid="stCameraInput"] [data-testid="stImage"] {{ display: none !important; }}
/* 列间距 */
[data-testid="stHorizontalBlock"] {{ gap: 6px !important; }}

/* 按钮 - 统一蓝色 */
.stButton > button {{
    background: #007BFF !important; color: #fff !important;
    border: none !important; border-radius: 8px !important;
    padding: 8px 16px !important; font-size: 14px !important; font-weight: 500 !important;
    min-height: 40px !important; transition: all 0.15s;
}}
.stButton > button:hover {{ background: #0056b3 !important; }}
.stButton > button:disabled {{ background: #b0d4ff !important; color: #fff !important; }}
.stButton > button[kind="primary"] {{ background: #007BFF !important; }}
.stButton > button[kind="primary"]:hover {{ background: #0056b3 !important; }}

/* 指标卡 */
.kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; text-align: center; }}
.kpi-val {{ font-family: 'JetBrains Mono', monospace; font-size: 20px; font-weight: 700; color: var(--blue); line-height: 1.3; }}
.kpi-lbl {{ font-size: 10px; color: var(--dim); text-transform: uppercase; letter-spacing: 0.5px; }}

/* 状态徽章 */
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
.badge-ok {{ background: #0d1117; color: var(--green); border: 1px solid var(--green); }}
.badge-warn {{ background: #1c1b00; color: var(--yellow); border: 1px solid var(--yellow); }}
.badge-err {{ background: #1c0d0d; color: var(--red); border: 1px solid var(--red); }}

/* 黑客日志面板 */
.hlog {{
    background: #0a0e14; border: 1px solid #1a3a1a; border-radius: 6px;
    padding: 10px 12px; font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 12px; color: var(--green); line-height: 1.5;
    overflow-y: auto; box-shadow: inset 0 0 30px rgba(0,255,65,0.03);
}}
.hlog .lt {{ color: var(--green); font-weight: bold; border-bottom: 1px solid #1a3a1a; padding-bottom: 3px; margin-bottom: 6px; font-size: 13px; }}
.hlog .lo {{ color: #39d353; }} .hlog .le {{ color: #f85149; }} .hlog .lk {{ color: #58a6ff; }} .hlog .lw {{ color: #d29922; }}

/* 进度条 - 细线，不重叠 */
.stProgress {{ margin: 0 !important; padding: 0 !important; }}
.stProgress > div {{ margin: 0 !important; height: 3px !important; border-radius: 2px !important; }}
.stProgress > div > div {{ background: var(--green) !important; }}
/* 隐藏 Streamlit 自带的蓝色 spinner 进度条 */
.stSpinner {{ display: none !important; }}
/* 图片自适应，hover 放大提示 */
[data-testid="stImage"] img {{ border-radius: 4px; cursor: zoom-in; }}
[data-testid="stImage"] img:hover {{ opacity: 0.85; }}

/* 表格 */
.stDataFrame {{ border: 1px solid var(--border); border-radius: 6px; }}

/* Expander */
details {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px; }}
details summary {{ color: var(--text); font-size: 13px; }}
</style>
""", unsafe_allow_html=True)

# ---- Session State ----
if "results" not in st.session_state: st.session_state.results = []
if "delete_id" not in st.session_state: st.session_state.delete_id = None


def kpi(label, value, color="var(--blue)"):
    return f'<div class="kpi"><div class="kpi-val" style="color:{color}">{value}</div><div class="kpi-lbl">{label}</div></div>'

def badge(text, level="ok"):
    return f'<span class="badge badge-{level}">{text}</span>'


# ---- 侧边栏 ----
with st.sidebar:
    st.markdown(f"**🛡️ 安全数字监督员** `v{_ver}`")
    st.caption("牡丹江中燃 HSE · AI Agent")
    st.markdown("---")
    api_key = st.text_input("API Key", _cfg.get("api_key", ""), type="password")
    base_url = st.text_input("API URL", _cfg.get("base_url", ""))
    model_name = st.text_input("模型", _cfg.get("model_name", ""))
    st.markdown("---")
    st.caption("📋 Plan → 👁️ Perceive → 🤔 Reason → 🔍 Reflect → ⚡ Act → 📊 Report")


# ---- 主面板 ----
tab1, tab2 = st.tabs(["📷 处理作业票", "📊 AI 看板"])


# ==================== Tab 1 ====================
with tab1:
    # ---- 三个按钮：上传 / 拍照 / 处理 ----
    c1, c2, c3 = st.columns(3)
    with c1:
        uploaded_files = st.file_uploader("📤 上传", type=["jpg","jpeg","png","bmp"], accept_multiple_files=True, label_visibility="collapsed")
    with c2:
        camera_photo = st.camera_input("📷 拍照", label_visibility="collapsed")
    with c3:
        has_files = bool(uploaded_files) or camera_photo is not None
        run_clicked = st.button("⚙️ 处理", type="primary", use_container_width=True, disabled=not has_files)

    if camera_photo is not None:
        uploaded_files = [camera_photo]

    # 无文件 + 有历史结果：显示上次结果
    if not uploaded_files and not run_clicked:
        if st.session_state.results:
            st.markdown("**上次处理结果**")
            for item in st.session_state.results:
                d = item["data"]
                c1, c2, c3, c4, c5 = st.columns(5)
                with c1: st.markdown(kpi("票号", d.ticket_id), unsafe_allow_html=True)
                with c2: st.markdown(kpi("状态", f"{len(d.issues)}项" if d.has_abnormal else "正常", "var(--red)" if d.has_abnormal else "var(--green)"), unsafe_allow_html=True)
                with c3: st.markdown(kpi("措施", f"{len(d.safety_measures)}"), unsafe_allow_html=True)
                with c4:
                    rl = d.risk_level or "-"
                    rc = {"重大":"var(--red)","较大":"var(--yellow)","一般":"var(--yellow)","低风险":"var(--green)"}.get(rl, "var(--blue)")
                    st.markdown(kpi("风险", rl, rc), unsafe_allow_html=True)
                with c5: st.markdown(kpi("浓度", ", ".join(f"{v}%" for v in d.gas_concentration) or "无"), unsafe_allow_html=True)
                if d.approval_opinion:
                    ic = {"重大":"🔴","较大":"🟡","一般":"🟡","低风险":"🟢"}.get(d.risk_level or "", "")
                    (st.warning if d.has_abnormal else st.success)(f"{ic} {d.approval_opinion}")
        else:
            st.caption("📷 拍照或选择作业票图片，Agent 自动完成识别 → 结构化 → 审批建议 → 预警")

    # 有文件：预览缩略图
    if uploaded_files and not run_clicked and not st.session_state.get("run_processing"):
        thumbs = st.columns(min(len(uploaded_files) + 1, 6))
        for i, f in enumerate(uploaded_files[:5]):
            with thumbs[i]: st.image(f, width=100)
        with thumbs[min(len(uploaded_files), 5)]:
            st.markdown(f"<div style='text-align:center;padding-top:35px;color:var(--dim);font-size:12px'>{len(uploaded_files)}张</div>", unsafe_allow_html=True)

    # 开始处理
    if run_clicked and uploaded_files:
        st.session_state.run_processing = True
        st.rerun()

    if st.session_state.get("run_processing") and uploaded_files:
        st.session_state.run_processing = False

        from agent_core import SecurityAgent, LLMBrain
        brain = LLMBrain(api_key=api_key, base_url=base_url, model_name=model_name)
        agent = SecurityAgent(brain=brain)
        st.session_state.results = []

        for idx, uploaded in enumerate(uploaded_files):
            # 先保存文件
            suffix = os.path.splitext(uploaded.name)[1] or ".jpg"
            upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            save_path = os.path.join(upload_dir, f"{int(time.time())}_{idx}{suffix}")
            with open(save_path, "wb") as f: f.write(uploaded.getvalue())

            # 分栏：左边结果，右边日志
            col_r, col_l = st.columns([3, 2])

            # 左栏：进度条 + 预览图（点击放大可看原图）
            with col_r:
                status_text = st.empty()
                progress = st.progress(0)
                status_text.caption(f"[{idx+1}/{len(uploaded_files)}] {uploaded.name} — 准备中...")
                st.image(save_path, caption=uploaded.name, use_container_width=True)

            # 右栏：日志面板
            with col_l:
                pass  # 日志由 log_ph 占位渲染

            log_ph = col_l.empty()
            log_buf = []

            def hlog(line, _save_path=save_path, _name=uploaded.name):
                log_buf.append(line)
                import html as _h
                parts = []
                for l in log_buf[-30:]:
                    c = ""
                    if "Tool" in l: c = "lo"
                    elif "FAIL" in l or "出错" in l: c = "le"
                    elif "OK" in l or "通过" in l or "完成" in l: c = "lk"
                    elif "重试" in l or "未通过" in l: c = "lw"
                    parts.append(f'<div class="{c}">{_h.escape(l)}</div>')
                log_ph.markdown(
                    f'<div class="hlog">'
                    f'<div class="lt">📄 {_h.escape(_name)} | 🤖 AGENT THINKING...</div>'
                    f'{"".join(parts)}</div>',
                    unsafe_allow_html=True)

            hlog(f">>> 收到任务: {uploaded.name}")

            _orig = sys.stdout
            result = {"ocr": None, "data": None}
            _sp = {"Plan":10,"Perceive":25,"Reason":50,"Reflect":70,"Act":85,"Report":98}
            _sc = {"Plan":"规划","Perceive":"感知","Reason":"推理","Reflect":"反思","Act":"执行","Report":"总结"}

            class Cap(io.TextIOBase):
                def write(self, s):
                    s = s.strip()
                    if s:
                        hlog(s)
                        for k, p in _sp.items():
                            if f"Agent {k}" in s:
                                progress.progress(p)
                                status_text.caption(f"[{idx+1}/{len(uploaded_files)}] {_sc[k]}...")
                    return len(s) if s else 0
                def flush(self): pass

            sys.stdout = Cap()
            try:
                ocr_text, structured = agent.run(save_path)
                result["ocr"], result["data"] = ocr_text, structured
            except Exception as e:
                hlog(f"❌ {e}")
            finally:
                sys.stdout = _orig

            progress.progress(100)
            status_text.caption(f"[{idx+1}/{len(uploaded_files)}] ✅ 完成")

            # 左栏：结果展示
            with col_r:
                if result["data"]:
                    d = result["data"]
                    st.session_state.results.append(result)

                    # KPI 行
                    c1, c2, c3, c4, c5 = st.columns(5)
                    with c1: st.markdown(kpi("票号", d.ticket_id), unsafe_allow_html=True)
                    with c2: st.markdown(kpi("状态", f"{len(d.issues)}项" if d.has_abnormal else "正常", "var(--red)" if d.has_abnormal else "var(--green)"), unsafe_allow_html=True)
                    with c3: st.markdown(kpi("措施", f"{len(d.safety_measures)}"), unsafe_allow_html=True)
                    with c4:
                        rl = d.risk_level or "-"
                        rc = {"重大":"var(--red)","较大":"var(--yellow)","一般":"var(--yellow)","低风险":"var(--green)"}.get(rl, "var(--blue)")
                        st.markdown(kpi("风险", rl, rc), unsafe_allow_html=True)
                    with c5: st.markdown(kpi("浓度", ", ".join(f"{v}%" for v in d.gas_concentration) or "无"), unsafe_allow_html=True)

                    # 审批建议
                    if d.approval_opinion:
                        ic = {"重大":"🔴","较大":"🟡","一般":"🟡","低风险":"🟢"}.get(d.risk_level or "", "")
                        (st.warning if d.has_abnormal else st.success)(f"{ic} {d.approval_opinion}")

                    # OCR + 隐患（折叠）
                    if result["ocr"]:
                        with st.expander("📝 OCR 识别原文"):
                            ocr_rows = []
                            for line in result["ocr"].strip().split("\n"):
                                line = line.strip()
                                if not line: continue
                                if "：" in line:
                                    p = line.split("：", 1); ocr_rows.append({"字段": p[0].strip(), "值": p[1].strip()})
                                elif ":" in line and line.index(":") > 0:
                                    p = line.split(":", 1); ocr_rows.append({"字段": p[0].strip(), "值": p[1].strip()})
                                else:
                                    ocr_rows.append({"字段": "", "值": line})
                            if ocr_rows:
                                st.dataframe(pd.DataFrame(ocr_rows), use_container_width=True, height=min(len(ocr_rows)*28+30, 350))

                    if d.issues:
                        with st.expander(f"⚠️ 隐患 ({len(d.issues)})"):
                            for issue in d.issues:
                                st.caption(f"• {issue.item_name} — {issue.status}" + (f" ({issue.raw_text})" if issue.raw_text else ""))

        # 批量汇总
        if len(st.session_state.results) > 1:
            abn = sum(1 for r in st.session_state.results if r["data"].has_abnormal)
            st.markdown(f"**📊 汇总** {len(st.session_state.results)}张 {badge('正常'+str(len(st.session_state.results)-abn), 'ok')} {badge('隐患'+str(abn), 'err' if abn else 'ok')}", unsafe_allow_html=True)
            rows = [{"票号": r["data"].ticket_id, "场站": r["data"].station_name, "状态": "有隐患" if r["data"].has_abnormal else "正常", "风险": r["data"].risk_level or "-"} for r in st.session_state.results]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=min(len(rows)*28+30, 200))


# ==================== Tab 2: AI 看板 ====================
with tab2:
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
    _del_pwd = _cfg.get("delete_password", "123")

    if not os.path.exists(db_path):
        st.caption("📭 暂无数据，处理作业票后自动保存。")
    else:
        conn = sqlite3.connect(db_path)
        try:
            rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,approval_opinion,risk_level,created_at FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()
        except:
            rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,'','',created_at FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()

        total = len(rows_db)
        abn_cnt = sum(1 for r in rows_db if r[5])

        # KPI 行
        k1, k2, k3, k4 = st.columns(4)
        with k1: st.markdown(kpi("总票数", total), unsafe_allow_html=True)
        with k2: st.markdown(kpi("有隐患", abn_cnt, "var(--red)" if abn_cnt else "var(--green)"), unsafe_allow_html=True)
        with k3: st.markdown(kpi("正常", total - abn_cnt, "var(--green)"), unsafe_allow_html=True)
        with k4: st.markdown(kpi("隐患率", f"{abn_cnt/total*100:.0f}%" if total else "0%"), unsafe_allow_html=True)

        # 高频隐患
        issue_counter = {}
        try:
            for (ij,) in conn.execute("SELECT issues_json FROM hse_fire_work_tickets WHERE has_abnormal=1").fetchall():
                if ij:
                    for item in json.loads(ij):
                        n = item.get("item_name", "未知"); issue_counter[n] = issue_counter.get(n, 0) + 1
        except: pass
        conn.close()

        if issue_counter:
            top5 = sorted(issue_counter.items(), key=lambda x: -x[1])[:5]
            cols = st.columns(len(top5))
            for i, (name, count) in enumerate(top5):
                with cols[i]: st.markdown(kpi(name, f"{count}次", "var(--red)"), unsafe_allow_html=True)

        # 删除弹窗
        if st.session_state.delete_id:
            @st.dialog("🗑️ 确认删除", width="small")
            def confirm_delete():
                st.warning(f"删除 **#{st.session_state.delete_id}**？")
                pwd = st.text_input("密码", type="password")
                fc1, fc2 = st.columns(2)
                with fc1:
                    if st.button("✅ 确认", type="primary", use_container_width=True):
                        if pwd == _del_pwd:
                            c2 = sqlite3.connect(db_path)
                            c2.execute("DELETE FROM hse_fire_work_tickets WHERE id=?", (st.session_state.delete_id,))
                            c2.commit(); c2.close()
                            st.session_state.delete_id = None; st.rerun()
                        else: st.error("密码错误")
                with fc2:
                    if st.button("❌ 取消", use_container_width=True):
                        st.session_state.delete_id = None; st.rerun()
            confirm_delete()

        # 记录列表
        for row in rows_db:
            rid, ticket, station, worker, date, abnormal, opinion, risk, created = row
            icon = "🚨" if abnormal else "✅"
            badge_html = f' {badge(risk, "err" if risk=="重大" else ("warn" if risk in ["较大","一般"] else "ok"))}' if risk else ""

            cm, cd = st.columns([9, 1])
            with cm:
                with st.expander(f"{icon} #{rid} | {ticket} | {station} | {date}{badge_html}", expanded=False):
                    ca, cb = st.columns(2)
                    with ca: st.markdown(f"**票号** {ticket}  \n**场站** {station}  \n**动火人** {worker}  \n**日期** {date}")
                    with cb:
                        st.markdown(f"**状态** {'🔴 有隐患' if abnormal else '🟢 正常'}")
                        if risk: st.markdown(f"**风险** {risk}")
                        st.caption(f"处理: {created}")
                        if opinion: st.caption(f"审批: {opinion}")
            with cd:
                st.markdown("<div style='padding-top:18px'></div>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{rid}", help=f"删除 #{rid}"):
                    st.session_state.delete_id = rid; st.rerun()
