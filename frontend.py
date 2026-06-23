"""
安全数字监督员 - Agent 可视化决策链面板
启动: streamlit run frontend.py
"""

import io, sys, os, re, time, json
import streamlit as st
import pandas as pd

_cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
_cfg = json.load(open(_cfg_path, encoding="utf-8")) if os.path.exists(_cfg_path) else {}

st.set_page_config(page_title="安全数字监督员", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
/* 全局紧凑 */
.block-container { padding: 0.5rem 1rem 0.3rem 1rem; }
section[data-testid="stSidebar"] .block-container { padding-top: 0.5rem; }
/* 隐藏 Streamlit 默认元素 */
#MainMenu, footer, header { display: none !important; }
/* 上传区域压缩 */
[data-testid="stFileUploader"] { padding: 0 !important; }
[data-testid="stFileUploader"] section { padding: 4px 8px !important; min-height: 0 !important; }
[data-testid="stCameraInput"] { padding: 0 !important; }
[data-testid="stCameraInput"] section { padding: 4px 8px !important; min-height: 0 !important; }
/* 按钮紧凑 */
.stButton > button { padding: 4px 12px !important; min-height: 0 !important; font-size: 13px !important; }
/* Tab 紧凑 */
.stTabs [data-baseweb="tab-list"] { gap: 4px; }
.stTabs [data-baseweb="tab"] { padding: 4px 12px; font-size: 13px; }
/* 指标卡 */
.mcard { background: #1a1a2e; border: 1px solid #333; border-radius: 6px; padding: 6px 10px; text-align: center; }
.mval { font-size: 18px; font-weight: 700; color: #00d4ff; line-height: 1.2; }
.mlbl { font-size: 10px; color: #888; }
/* 黑客日志 */
.hlog { background: #0a0a0a; border: 1px solid #00ff41; border-radius: 6px; padding: 8px 10px; font-family: 'Courier New', monospace; font-size: 12px; color: #00ff41; line-height: 1.4; overflow-y: auto; box-shadow: 0 0 15px rgba(0,255,65,0.08); }
.hlog .lt { color: #00ff41; font-weight: bold; font-size: 12px; border-bottom: 1px solid #00ff4133; padding-bottom: 3px; margin-bottom: 4px; }
.hlog .lo { color: #00ccaa; } .hlog .le { color: #ff4444; } .hlog .lk { color: #00ff41; } .hlog .lw { color: #ffb800; }
/* 进度条紧凑 */
.stProgress > div { margin: 0 !important; }
</style>
""", unsafe_allow_html=True)

if "results" not in st.session_state: st.session_state.results = []
if "delete_id" not in st.session_state: st.session_state.delete_id = None


def metric_card(label, value, color="#00d4ff"):
    return f'<div class="mcard"><div class="mval" style="color:{color}">{value}</div><div class="mlbl">{label}</div></div>'


# ---- 侧边栏 ----
with st.sidebar:
    _ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()
    st.markdown(f"### 🛡️ 安全数字监督员 v{_ver}")
    st.caption("牡丹江中燃 HSE · AI Agent")
    api_key = st.text_input("🔑 API Key", _cfg.get("api_key", ""), type="password")
    base_url = st.text_input("🌐 URL", _cfg.get("base_url", ""))
    model_name = st.text_input("🤖 Model", _cfg.get("model_name", ""))

# ---- 主面板 ----
tab1, tab2 = st.tabs(["📷 处理作业票", "🤖 AI 看板"])


# ==================== Tab 1 ====================
with tab1:
    # 上传区：一行搞定
    c_up, c_cam = st.columns([3, 1])
    with c_up:
        uploaded_files = st.file_uploader("📁 选择图片", type=["jpg","jpeg","png","bmp"], accept_multiple_files=True, label_visibility="collapsed")
    with c_cam:
        camera_photo = st.camera_input("📷", label_visibility="collapsed", help="拍照上传")

    if camera_photo is not None:
        uploaded_files = [camera_photo]

    if not uploaded_files:
        if st.session_state.results:
            st.markdown("**📋 上次结果：**", help="上传新图片覆盖")
            for item in st.session_state.results:
                d = item["data"]
                ic1, ic2, ic3, ic4, ic5 = st.columns(5)
                with ic1: st.markdown(metric_card("票号", d.ticket_id), unsafe_allow_html=True)
                with ic2: st.markdown(metric_card("状态", f"{len(d.issues)}项隐患" if d.has_abnormal else "正常", "#ff4444" if d.has_abnormal else "#00ff41"), unsafe_allow_html=True)
                with ic3: st.markdown(metric_card("措施", f"{len(d.safety_measures)}项"), unsafe_allow_html=True)
                with ic4: st.markdown(metric_card("风险", d.risk_level or "-", "#ff4444" if d.has_abnormal else "#00ff41"), unsafe_allow_html=True)
                with ic5: st.markdown(metric_card("浓度", ", ".join(f"{v}%" for v in d.gas_concentration) if d.gas_concentration else "无"), unsafe_allow_html=True)
                if d.approval_opinion:
                    icon = {"重大":"🔴","较大":"🟡","一般":"🟡","低风险":"🟢"}.get(d.risk_level or "", "")
                    (st.warning if d.has_abnormal else st.success)(f"{icon} {d.approval_opinion}")
        else:
            st.caption("👆 拍照或选择作业票图片，Agent 自动完成全部流程")

    else:
        # 有文件：预览 + 开始按钮（一行）
        pc1, pc2 = st.columns([5, 1])
        with pc1:
            thumbs = st.columns(min(len(uploaded_files), 4))
            for i, f in enumerate(uploaded_files[:4]):
                with thumbs[i]: st.image(f, width=120)
        with pc2:
            st.markdown(f"<div style='text-align:center;padding-top:30px;font-size:12px;color:#888'>{len(uploaded_files)} 张</div>", unsafe_allow_html=True)
            if st.button("🚀 开始处理", type="primary", use_container_width=True):
                st.session_state.run_processing = True
                st.rerun()

        if st.session_state.get("run_processing"):
            st.session_state.run_processing = False

            from agent_core import SecurityAgent, LLMBrain
            brain = LLMBrain(api_key=api_key, base_url=base_url, model_name=model_name)
            agent = SecurityAgent(brain=brain)
            st.session_state.results = []

            for idx, uploaded in enumerate(uploaded_files):
                progress = st.progress(0, text=f"[{idx+1}/{len(uploaded_files)}] {uploaded.name}")
                col_r, col_l = st.columns([3, 2])
                log_ph = col_l.empty()
                log_buf = []

                def hlog(line):
                    log_buf.append(line)
                    import html as _h
                    parts = []
                    for l in log_buf[-35:]:
                        c = ""
                        if "Tool" in l: c = "lo"
                        elif "FAIL" in l or "出错" in l: c = "le"
                        elif "OK" in l or "通过" in l or "完成" in l: c = "lk"
                        elif "重试" in l or "未通过" in l: c = "lw"
                        parts.append(f'<div class="{c}">{_h.escape(l)}</div>')
                    log_ph.markdown(f'<div class="hlog"><div class="lt">🤖 AGENT THINKING...</div>{"".join(parts)}</div>', unsafe_allow_html=True)

                suffix = os.path.splitext(uploaded.name)[1] or ".jpg"
                upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
                os.makedirs(upload_dir, exist_ok=True)
                save_path = os.path.join(upload_dir, f"{int(time.time())}_{idx}{suffix}")
                with open(save_path, "wb") as f: f.write(uploaded.getvalue())

                with col_r:
                    st.image(save_path, caption=uploaded.name, width=280)

                hlog(f">>> {uploaded.name}")
                progress.progress(5, text=f"[{idx+1}/{len(uploaded_files)}] OCR...")

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
                                    progress.progress(p, text=f"[{idx+1}/{len(uploaded_files)}] {_sc[k]}...")
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

                progress.progress(100, text=f"[{idx+1}/{len(uploaded_files)}] ✅")

                with col_r:
                    if result["data"]:
                        d = result["data"]
                        st.session_state.results.append(result)

                        # 紧凑指标行
                        ic1, ic2, ic3, ic4, ic5 = st.columns(5)
                        with ic1: st.markdown(metric_card("票号", d.ticket_id), unsafe_allow_html=True)
                        with ic2: st.markdown(metric_card("状态", f"{len(d.issues)}项隐患" if d.has_abnormal else "正常", "#ff4444" if d.has_abnormal else "#00ff41"), unsafe_allow_html=True)
                        with ic3: st.markdown(metric_card("措施", f"{len(d.safety_measures)}项"), unsafe_allow_html=True)
                        with ic4: st.markdown(metric_card("风险", d.risk_level or "-", "#ff4444" if d.has_abnormal else "#00ff41"), unsafe_allow_html=True)
                        with ic5: st.markdown(metric_card("浓度", ", ".join(f"{v}%" for v in d.gas_concentration) if d.gas_concentration else "无"), unsafe_allow_html=True)

                        # 审批建议
                        if d.approval_opinion:
                            ic = {"重大":"🔴","较大":"🟡","一般":"🟡","低风险":"🟢"}.get(d.risk_level or "", "")
                            (st.warning if d.has_abnormal else st.success)(f"{ic} {d.approval_opinion}")

                        # OCR + 隐患（折叠）
                        if result["ocr"]:
                            with st.expander("📝 OCR 原文", expanded=False):
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
                                    st.dataframe(pd.DataFrame(ocr_rows), use_container_width=True, height=min(len(ocr_rows)*30+30, 400))

                        if d.issues:
                            with st.expander(f"⚠️ 隐患明细 ({len(d.issues)})", expanded=False):
                                for issue in d.issues:
                                    st.caption(f"• **{issue.item_name}** — {issue.status}" + (f" ({issue.raw_text})" if issue.raw_text else ""))

            # 批量汇总
            if len(st.session_state.results) > 1:
                abn = sum(1 for r in st.session_state.results if r["data"].has_abnormal)
                st.caption(f"📊 汇总: {len(st.session_state.results)}张 | 有隐患{abn} | 正常{len(st.session_state.results)-abn}")
                rows = [{"票号": r["data"].ticket_id, "场站": r["data"].station_name, "状态": "有隐患" if r["data"].has_abnormal else "正常", "风险": r["data"].risk_level or "-"} for r in st.session_state.results]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=min(len(rows)*30+30, 200))


# ==================== Tab 2: AI 看板 ====================
with tab2:
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
    _del_pwd = _cfg.get("delete_password", "123")

    if not os.path.exists(db_path):
        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1: st.metric("总票数", 0)
        with sc2: st.metric("隐患", 0)
        with sc3: st.metric("正常", 0)
        with sc4: st.metric("隐患率", "0%")
        st.caption("📭 暂无数据")
    else:
        conn = sqlite3.connect(db_path)
        try:
            rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,approval_opinion,risk_level,created_at FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()
        except:
            rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,'','',created_at FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()

        total = len(rows_db)
        abn_cnt = sum(1 for r in rows_db if r[5])

        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1: st.metric("总票数", total)
        with sc2: st.metric("隐患", abn_cnt)
        with sc3: st.metric("正常", total - abn_cnt)
        with sc4: st.metric("隐患率", f"{abn_cnt/total*100:.0f}%" if total else "0%")

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
                with cols[i]:
                    st.markdown(metric_card(name, f"{count}次", "#ff4444"), unsafe_allow_html=True)

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
            badge = f" [{risk}]" if risk else ""
            cm, cd = st.columns([9, 1])
            with cm:
                with st.expander(f"{icon} #{rid} | {ticket} | {station} | {date}{badge}", expanded=False):
                    ca, cb = st.columns(2)
                    with ca: st.markdown(f"**票号:** {ticket}  \n**场站:** {station}  \n**动火人:** {worker}  \n**日期:** {date}")
                    with cb:
                        st.markdown(f"**状态:** :{'red' if abnormal else 'green'}[{'有隐患' if abnormal else '正常'}]")
                        if risk: st.markdown(f"**风险:** {risk}")
                        st.caption(f"处理时间: {created}")
                        if opinion: st.caption(f"审批: {opinion}")
            with cd:
                st.markdown("<div style='padding-top:20px'></div>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{rid}", help=f"删除 #{rid}"):
                    st.session_state.delete_id = rid; st.rerun()
