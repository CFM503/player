"""
安全数字监督员 - Agent 可视化决策链面板
启动: streamlit run frontend.py
"""

import io, sys, os, re, time, tempfile, json
import streamlit as st
import pandas as pd

_cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
_cfg = json.load(open(_cfg_path, encoding="utf-8")) if os.path.exists(_cfg_path) else {}

st.set_page_config(page_title="安全数字监督员", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1rem; padding-bottom: 0.5rem; }
.metric-card { background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 10px 14px; text-align: center; }
.metric-val { font-size: 22px; font-weight: 700; color: #00d4ff; }
.metric-label { font-size: 11px; color: #888; }
.hacker-log {
    background: #0a0a0a; border: 1px solid #00ff41; border-radius: 8px;
    padding: 12px 16px; font-family: 'Courier New', monospace;
    font-size: 13px; color: #00ff41; line-height: 1.6;
    max-height: 75vh; overflow-y: auto; box-shadow: 0 0 20px rgba(0,255,65,0.1);
}
.hacker-log .log-tool { color: #00ccaa; }
.hacker-log .log-err { color: #ff4444; }
.hacker-log .log-ok { color: #00ff41; }
.hacker-log .log-warn { color: #ffb800; }
.hacker-log .log-title { color: #00ff41; font-weight: bold; font-size: 14px; border-bottom: 1px solid #00ff4133; padding-bottom: 4px; margin-bottom: 8px; }
#MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

if "results" not in st.session_state:
    st.session_state.results = []
if "delete_id" not in st.session_state:
    st.session_state.delete_id = None

with st.sidebar:
    _ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()
    st.markdown(f"### 🛡️ 安全数字监督员 v{_ver}")
    st.caption("牡丹江中燃 HSE · AI Agent")
    st.divider()
    api_key = st.text_input("🔑 API Key", _cfg.get("api_key", ""), type="password")
    base_url = st.text_input("🌐 Base URL", _cfg.get("base_url", ""))
    model_name = st.text_input("🤖 Model", _cfg.get("model_name", ""))

tab_process, tab_dashboard = st.tabs(["📷 处理作业票", "🤖 AI 看板"])


# ==================== Tab 1 ====================
with tab_process:
    # 手机拍照 或 选择文件
    col_cam, col_file = st.columns(2)
    with col_cam:
        camera_photo = st.camera_input("📷 拍照上传", help="手机端点击唤起摄像头")
    with col_file:
        uploaded_files = st.file_uploader(
            "📁 选择图片", type=["jpg","jpeg","png","bmp"],
            accept_multiple_files=True, help="从相册选择",
        )

    # 合并：拍照结果也当作一张图片处理
    if camera_photo is not None:
        uploaded_files = [camera_photo]  # 拍照优先，覆盖文件选择

    if not uploaded_files:
        if st.session_state.results:
            st.markdown("### 📋 上次处理结果")
            for item in st.session_state.results:
                d = item["data"]
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.markdown(f'<div class="metric-card"><div class="metric-val">{d.ticket_id}</div><div class="metric-label">票号</div></div>', unsafe_allow_html=True)
                with c2:
                    color = "#ff4444" if d.has_abnormal else "#00ff41"
                    val = f"{len(d.issues)} 项隐患" if d.has_abnormal else "正常"
                    st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:{color}">{val}</div><div class="metric-label">状态</div></div>', unsafe_allow_html=True)
                with c3:
                    st.markdown(f'<div class="metric-card"><div class="metric-val">{len(d.safety_measures)}</div><div class="metric-label">措施</div></div>', unsafe_allow_html=True)
                with c4:
                    conc = ", ".join(f"{v}%" for v in d.gas_concentration) if d.gas_concentration else "无"
                    st.markdown(f'<div class="metric-card"><div class="metric-val" style="font-size:14px">{conc}</div><div class="metric-label">浓度</div></div>', unsafe_allow_html=True)
                if d.approval_opinion:
                    icon = {"重大":"🔴","较大":"🟡","一般":"🟡","低风险":"🟢"}.get(d.risk_level or "", "")
                    (st.warning if d.has_abnormal else st.success)(f"{icon} **审批建议：** {d.approval_opinion}")
        else:
            st.info("👆 上传作业票照片，Agent 将自主完成：感知 → 推理 → 反思 → 执行 → 生成审批建议")

    else:
        st.markdown(f"**已上传 {len(uploaded_files)} 张**")

        if not st.session_state.get("run_processing"):
            cols = st.columns(min(len(uploaded_files), 4))
            for i, f in enumerate(uploaded_files[:4]):
                with cols[i % 4]:
                    st.image(f, caption=f.name, width=180)
            if st.button("🚀 开始处理", type="primary", use_container_width=True):
                st.session_state.run_processing = True
                st.rerun()

        else:
            st.session_state.run_processing = False

            from agent_core import SecurityAgent, LLMBrain
            brain = LLMBrain(api_key=api_key, base_url=base_url, model_name=model_name)
            agent = SecurityAgent(brain=brain)
            st.session_state.results = []

            for idx, uploaded in enumerate(uploaded_files):
                progress = st.progress(0, text=f"[{idx+1}/{len(uploaded_files)}] {uploaded.name}")
                col_result, col_log = st.columns([3, 2])
                log_ph = col_log.empty()
                log_lines = []

                def hack_log(line):
                    log_lines.append(line)
                    import html as _html
                    parts = []
                    for l in log_lines[-40:]:
                        css = "log-line"
                        if "Tool" in l: css = "log-tool"
                        elif "FAIL" in l or "出错" in l: css = "log-err"
                        elif "OK" in l or "通过" in l or "完成" in l: css = "log-ok"
                        elif "重试" in l or "未通过" in l: css = "log-warn"
                        parts.append(f'<div class="{css}">{_html.escape(l)}</div>')
                    log_ph.markdown(
                        f'<div class="hacker-log"><div class="log-title">🤖 AGENT THINKING...</div>{"".join(parts)}</div>',
                        unsafe_allow_html=True)

                suffix = os.path.splitext(uploaded.name)[1] or ".jpg"
                tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                tmp.write(uploaded.getvalue())
                tmp.close()

                with col_result:
                    st.image(uploaded, caption=uploaded.name, width=350)

                hack_log(f">>> 收到任务: {uploaded.name}")
                progress.progress(5, text=f"[{idx+1}/{len(uploaded_files)}] OCR...")

                _orig = sys.stdout
                result = {"ocr": None, "data": None}
                _sp = {"Plan":10,"Perceive":25,"Reason":50,"Reflect":70,"Act":85,"Report":98}
                _sc = {"Plan":"规划","Perceive":"感知","Reason":"推理","Reflect":"反思","Act":"执行","Report":"总结"}

                class Cap(io.TextIOBase):
                    def write(self, s):
                        s = s.strip()
                        if s:
                            hack_log(s)
                            for k, p in _sp.items():
                                if f"Agent {k}" in s:
                                    progress.progress(p, text=f"[{idx+1}/{len(uploaded_files)}] {_sc[k]}...")
                        return len(s) if s else 0
                    def flush(self): pass

                sys.stdout = Cap()
                try:
                    ocr_text, structured = agent.run(tmp.name)
                    result["ocr"] = ocr_text
                    result["data"] = structured
                except Exception as e:
                    hack_log(f"❌ 出错: {e}")
                finally:
                    sys.stdout = _orig

                if os.path.exists(tmp.name):
                    os.remove(tmp.name)

                progress.progress(100, text=f"[{idx+1}/{len(uploaded_files)}] ✅ 完成")

                with col_result:
                    if result["data"]:
                        d = result["data"]
                        st.session_state.results.append(result)

                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            st.markdown(f'<div class="metric-card"><div class="metric-val">{d.ticket_id}</div><div class="metric-label">票号</div></div>', unsafe_allow_html=True)
                        with c2:
                            color = "#ff4444" if d.has_abnormal else "#00ff41"
                            val = f"{len(d.issues)} 项隐患" if d.has_abnormal else "正常"
                            st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:{color}">{val}</div><div class="metric-label">状态</div></div>', unsafe_allow_html=True)
                        with c3:
                            st.markdown(f'<div class="metric-card"><div class="metric-val">{len(d.safety_measures)}</div><div class="metric-label">措施</div></div>', unsafe_allow_html=True)
                        with c4:
                            conc = ", ".join(f"{v}%" for v in d.gas_concentration) if d.gas_concentration else "无"
                            st.markdown(f'<div class="metric-card"><div class="metric-val" style="font-size:14px">{conc}</div><div class="metric-label">浓度</div></div>', unsafe_allow_html=True)

                        if d.approval_opinion:
                            icon = {"重大":"🔴","较大":"🟡","一般":"🟡","低风险":"🟢"}.get(d.risk_level or "", "")
                            (st.warning if d.has_abnormal else st.success)(f"{icon} **审批建议（{d.risk_level or '-'}）：** {d.approval_opinion}")

                        if d.has_abnormal:
                            st.error(f"🚨 {len(d.issues)} 项隐患")

                        if result["ocr"]:
                            with st.expander("📝 OCR 识别结果", expanded=False):
                                ocr_rows = []
                                for line in result["ocr"].strip().split("\n"):
                                    line = line.strip()
                                    if not line:
                                        continue
                                    if "：" in line:
                                        p = line.split("：", 1)
                                        ocr_rows.append({"字段": p[0].strip(), "识别值": p[1].strip()})
                                    elif ":" in line and line.index(":") > 0:
                                        p = line.split(":", 1)
                                        ocr_rows.append({"字段": p[0].strip(), "识别值": p[1].strip()})
                                    else:
                                        ocr_rows.append({"字段": "", "识别值": line})
                                if ocr_rows:
                                    st.dataframe(pd.DataFrame(ocr_rows), use_container_width=True, height=min(len(ocr_rows)*35+40, 500))
                                else:
                                    st.code(result["ocr"], language=None)

                        t1, t2 = st.tabs(["📦 结构化数据", f"⚠️ 隐患 ({len(d.issues)})"])
                        with t1:
                            st.json(d.model_dump())
                        with t2:
                            if d.issues:
                                for issue in d.issues:
                                    st.markdown(f"- **{issue.item_name}** — {issue.status}" + (f" ({issue.raw_text})" if issue.raw_text else ""))
                            else:
                                st.success("无隐患。")

            if len(st.session_state.results) > 1:
                st.divider()
                st.markdown(f"### 📊 汇总（{len(st.session_state.results)} 张）")
                abn = sum(1 for r in st.session_state.results if r["data"].has_abnormal)
                sc1, sc2, sc3 = st.columns(3)
                with sc1: st.metric("总处理", len(st.session_state.results))
                with sc2: st.metric("有隐患", abn)
                with sc3: st.metric("正常", len(st.session_state.results) - abn)

                summary_rows = []
                for r in st.session_state.results:
                    d = r["data"]
                    summary_rows.append({"票号": d.ticket_id, "场站": d.station_name, "动火人": d.worker_id, "日期": d.check_date,
                                         "状态": "有隐患" if d.has_abnormal else "正常", "风险": d.risk_level or "-", "隐患": len(d.issues)})
                st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)


# ==================== Tab 2: AI 看板 ====================
with tab_dashboard:
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
    _del_pwd = _cfg.get("delete_password", "123")

    st.markdown("#### 📊 安全数据看板")

    if not os.path.exists(db_path):
        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1: st.metric("总处理票数", 0)
        with sc2: st.metric("有隐患", 0)
        with sc3: st.metric("正常", 0)
        with sc4: st.metric("隐患率", "0%")
        st.info("📭 暂无数据，处理作业票后自动保存到这里。")
    else:
        conn = sqlite3.connect(db_path)
        try:
            rows_db = conn.execute("""
                SELECT id, ticket_id, station_name, worker_id, check_date,
                       has_abnormal, approval_opinion, risk_level, created_at
                FROM hse_fire_work_tickets ORDER BY id DESC
            """).fetchall()
        except Exception:
            rows_db = conn.execute("""
                SELECT id, ticket_id, station_name, worker_id, check_date,
                       has_abnormal, '' as approval_opinion, '' as risk_level, created_at
                FROM hse_fire_work_tickets ORDER BY id DESC
            """).fetchall()

        total = len(rows_db)
        abn_cnt = sum(1 for r in rows_db if r[5])

        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1: st.metric("总处理票数", total)
        with sc2: st.metric("有隐患", abn_cnt)
        with sc3: st.metric("正常", total - abn_cnt)
        with sc4: st.metric("隐患率", f"{abn_cnt/total*100:.0f}%" if total else "0%")

        # 高频隐患 Top 5
        issue_counter = {}
        try:
            for (ij,) in conn.execute("SELECT issues_json FROM hse_fire_work_tickets WHERE has_abnormal=1").fetchall():
                if ij:
                    for item in json.loads(ij):
                        n = item.get("item_name", "未知")
                        issue_counter[n] = issue_counter.get(n, 0) + 1
        except Exception:
            pass

        if issue_counter:
            st.markdown("**高频隐患 Top 5：**")
            for name, count in sorted(issue_counter.items(), key=lambda x: -x[1])[:5]:
                bar = min(count * 20, 200)
                st.markdown(f"<div style='margin:2px 0'>{name} <span style='background:#ff4444;display:inline-block;width:{bar}px;height:14px;border-radius:3px;vertical-align:middle'></span> {count}次</div>", unsafe_allow_html=True)

        conn.close()

        # 删除密码弹窗
        if st.session_state.delete_id:
            @st.dialog("🗑️ 确认删除", width="small")
            def confirm_delete():
                st.warning(f"删除记录 **#{st.session_state.delete_id}**？此操作不可撤销。")
                pwd = st.text_input("🔑 输入删除密码", type="password")
                fc1, fc2 = st.columns(2)
                with fc1:
                    if st.button("✅ 确认删除", type="primary", use_container_width=True):
                        if pwd == _del_pwd:
                            conn2 = sqlite3.connect(db_path)
                            conn2.execute("DELETE FROM hse_fire_work_tickets WHERE id=?", (st.session_state.delete_id,))
                            conn2.commit()
                            conn2.close()
                            st.session_state.delete_id = None
                            st.rerun()
                        else:
                            st.error("密码错误")
                with fc2:
                    if st.button("❌ 取消", use_container_width=True):
                        st.session_state.delete_id = None
                        st.rerun()
            confirm_delete()

        # 记录列表
        st.divider()
        st.markdown(f"**共 {total} 条记录**")
        for row in rows_db:
            rid, ticket, station, worker, date, abnormal, opinion, risk, created = row
            icon = "🚨" if abnormal else "✅"
            badge = f" [{risk}]" if risk else ""

            col_main, col_del = st.columns([9, 1])
            with col_main:
                with st.expander(f"{icon} #{rid} | {ticket} | {station} | {date}{badge}", expanded=False):
                    ca, cb = st.columns(2)
                    with ca:
                        st.markdown(f"**票号:** {ticket}  \n**场站:** {station}  \n**动火人:** {worker}  \n**日期:** {date}")
                    with cb:
                        st.markdown(f"**状态:** :{'red' if abnormal else 'green'}[{'有隐患' if abnormal else '正常'}]")
                        if risk: st.markdown(f"**风险等级:** {risk}")
                        st.markdown(f"**处理时间:** {created}")
                        if opinion: st.markdown(f"**审批建议:** {opinion}")
            with col_del:
                st.markdown("<div style='padding-top:28px'></div>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{rid}", help=f"删除 #{rid}"):
                    st.session_state.delete_id = rid
                    st.rerun()
