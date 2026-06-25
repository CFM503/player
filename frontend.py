"""
安全数字监督员 - AI Agent 安全监控面板
启动: streamlit run frontend.py
"""

import io, sys, os, time, json
import check_deps  # noqa: F401 — 启动时强制校验依赖版本，不通过则退出
import streamlit.components.v1 as _components
import streamlit as st
import pandas as pd
from styles import CUSTOM_CSS
from components import (
    badge, render_kpi_row, render_ticket_kpis,
    render_notification_btn, render_record_badge,
)

# ---- 配置 ----
_cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
_cfg = json.load(open(_cfg_path, encoding="utf-8")) if os.path.exists(_cfg_path) else {}
_ver = open(os.path.join(os.path.dirname(__file__), "VERSION"), encoding="utf-8").read().strip()

st.set_page_config(page_title="安全数字监督员", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")

# ---- 自定义主题 ----
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ---- 强制展开侧边栏：清除 localStorage + 自动点击展开按钮 ----
# st.markdown 的 <script> 不会被 Streamlit 执行，必须用 components.v1.html()
_components.html("""
<script>
(function() {
    // 1. 清除所有侧边栏相关 localStorage 缓存
    try {
        Object.keys(localStorage).forEach(function(k) {
            if (k.toLowerCase().indexOf('sidebar') !== -1) {
                localStorage.removeItem(k);
            }
        });
    } catch(e) {}

    // 2. 如果侧边栏仍处于折叠态，找到展开按钮并点击
    function tryExpand() {
        var root = window.parent.document;
        var btn = root.querySelector('[data-testid="stExpandSidebarButton"]');
        if (btn) {
            btn.click();
            return true;
        }
        return false;
    }
    // 等 Streamlit DOM 渲染完再执行
    setTimeout(function() {
        if (!tryExpand()) setTimeout(tryExpand, 500);
    }, 300);
})();
</script>
""", height=0)

# ---- Session State ----
if "results" not in st.session_state: st.session_state.results = []
if "delete_id" not in st.session_state: st.session_state.delete_id = None
if "pending_files" not in st.session_state: st.session_state.pending_files = None
if "show_uploader" not in st.session_state: st.session_state.show_uploader = False
if "upload_done" not in st.session_state: st.session_state.upload_done = False


# ---- 侧边栏 ----
with st.sidebar:
    st.markdown(f"**🛡️ 安全数字监督员** `v{_ver}`")
    st.caption("牡丹江中燃 HSE · AI Agent")
    st.markdown("---")

    # API 配置
    api_key = st.text_input("API Key", _cfg.get("api_key", ""), type="password")
    base_url = st.text_input("API URL", _cfg.get("base_url", ""))
    model_name = st.text_input("模型", _cfg.get("model_name", ""))

    # OCR 表格识别模式
    _ocr_modes = {
        "坐标聚类（默认）": "cluster",
        "精细网格（列对齐）": "grid",
        "自适应边框检测": "adaptive",
        "多方向检测": "multidir",
    }
    ocr_mode_label = st.selectbox(
        "📋 OCR 表格模式",
        list(_ocr_modes.keys()),
        index=0,
        help="坐标聚类：基于文字坐标重建表格行列\n精细网格：X坐标聚类识别列边界，对齐输出\n自适应边框检测：OpenCV检测表格线段，按单元格组织文本\n多方向检测：分离水平/垂直文本分别处理",
    )
    ocr_mode = _ocr_modes[ocr_mode_label]

    # 设置面板
    st.markdown("---")
    with st.expander("⚙️ 通知设置", expanded=False):
        wechat_webhook = st.text_input("企业微信 Webhook", _cfg.get("wechat_webhook", ""), type="password", help="企业微信群机器人 Webhook 地址")
        dingtalk_webhook = st.text_input("钉钉 Webhook", _cfg.get("dingtalk_webhook", ""), type="password", help="钉钉群机器人 Webhook 地址")
        if st.button("💾 保存设置", use_container_width=True):
            _cfg["wechat_webhook"] = wechat_webhook
            _cfg["dingtalk_webhook"] = dingtalk_webhook
            with open(_cfg_path, "w", encoding="utf-8") as f:
                json.dump(_cfg, f, ensure_ascii=False, indent=2)
            st.success("已保存")

# ---- 主面板：Hero 横幅 ----
_status_ok = bool(api_key)
st.markdown(f"""
<div class="hero-banner">
    <div class="hero-left">
        <div class="hero-icon">🛡️</div>
        <div>
            <div class="hero-title">安全数字监督员</div>
            <div class="hero-sub">牡丹江中燃 · HSE AI Agent 安全监控系统</div>
        </div>
    </div>
    <div class="hero-right">
        <span class="hero-pill {'pill-ok' if _status_ok else 'pill-warn'}">
            <span class="pill-dot"></span>{'AI 引擎已就绪' if _status_ok else '请配置 API Key'}
        </span>
        <span class="hero-pill pill-version">v{_ver}</span>
    </div>
</div>
""", unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📷 处理作业票", "📊 AI 看板"])


# ==================== Tab 1 ====================
with tab1:
    # ---- API 配置检查 ----
    if not api_key:
        st.warning("⚠️ 请先在左侧边栏填写 API Key，否则无法处理。点击左上角 **>** 展开边栏。")

    # ---- 操作引导（根据当前状态动态显示）----
    step = 1
    if st.session_state.get("upload_done") and st.session_state.get("pending_files"):
        step = 2

    guide = st.empty()
    if step == 1:
        guide.markdown("""
        <div class="guide-box">
            <span class="guide-badge">第 1 步</span> 点击下方 <b>📤 上传</b> 提供作业票照片
        </div>
        """, unsafe_allow_html=True)
    elif step == 2:
        guide.markdown("""
        <div class="guide-box">
            <span class="guide-badge">第 2 步</span> 照片已就绪，点击 <b>⚙️ 处理</b> 开始 AI 分析
        </div>
        """, unsafe_allow_html=True)

    # ---- 两个按钮：上传 / 处理 ----
    c1, c2 = st.columns(2)
    with c1:
        show_upload = st.button("📤 上传", use_container_width=True)
    with c2:
        can_process = st.session_state.get("upload_done") and st.session_state.get("pending_files")
        run_clicked = st.button("⚙️ 处理", use_container_width=True, disabled=not can_process)

    # 点击按钮切换模式
    if show_upload:
        st.session_state.show_uploader = True
        st.session_state.upload_done = False
        st.session_state.pending_files = None

    # ---- 文件选择 ----
    if st.session_state.get("show_uploader"):
        picked = st.file_uploader("选择图片", type=["jpg","jpeg","png","bmp"], accept_multiple_files=False, label_visibility="collapsed", key="fu_main")
        if picked and not st.session_state.get("upload_done"):
            # 模拟上传进度条
            st.session_state.pending_files = [picked]
            prog_ph = st.empty()
            status_ph = st.empty()
            for pct in range(0, 101, 5):
                prog_ph.progress(pct)
                status_ph.caption(f"📤 上传中... {picked.name} — {pct}%")
                time.sleep(0.05)
            prog_ph.empty()
            status_ph.success(f"✅ 上传完成 — {picked.name}（{picked.size/1024:.0f} KB）")
            st.session_state.upload_done = True
            st.rerun()
        elif picked and st.session_state.get("upload_done"):
            st.success(f"✅ {picked.name}（{picked.size/1024:.0f} KB）")

    # 无文件 + 有历史结果：显示上次结果
    # 合并最终文件
    final_files = st.session_state.get("pending_files") or []

    if not final_files and not run_clicked:
        if st.session_state.results:
            st.markdown("**上次处理结果**")
            for item in st.session_state.results:
                d = item["data"]
                render_ticket_kpis(d)
        else:
            st.markdown("""
            <div class="empty-state">
                <div class="empty-icon">🛡️</div>
                <div class="empty-title">上传作业票照片，AI 自动完成全部分析</div>
                <div class="empty-desc">支持：动火作业票 · 带气作业票 · 临时用电作业票</div>
                <div class="empty-action">点击上方 <b>📤 上传</b> 选择照片开始分析</div>
            </div>
            """, unsafe_allow_html=True)

    # 有文件：预览缩略图
    if final_files and not run_clicked and not st.session_state.get("run_processing"):
        thumbs = st.columns(min(len(final_files) + 1, 6))
        for i, f in enumerate(final_files[:5]):
            with thumbs[i]: st.image(f, width=100)
        with thumbs[min(len(final_files), 5)]:
            st.markdown(f"<div style='text-align:center;padding-top:35px;color:#69707f;font-size:12px'>{len(final_files)}张</div>", unsafe_allow_html=True)

    # 开始处理
    if run_clicked and final_files:
        st.session_state.run_processing = True
        st.rerun()

    if st.session_state.get("run_processing") and final_files:
        st.session_state.run_processing = False

        from agent_core import SecurityAgent, LLMBrain
        brain = LLMBrain(api_key=api_key, base_url=base_url, model_name=model_name)
        agent = SecurityAgent(brain=brain, ocr_mode=ocr_mode)
        st.session_state.results = []

        # ---- 上传保存进度 ----
        upload_status = st.empty()
        upload_progress = st.progress(0)
        saved_paths = []
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        for i, f in enumerate(final_files):
            pct = int((i / len(final_files)) * 100)
            upload_progress.progress(pct)
            upload_status.caption(f"📤 保存中... {f.name} ({i+1}/{len(final_files)})")
            suffix = os.path.splitext(f.name)[1] or ".jpg"
            save_path = os.path.join(upload_dir, f"{int(time.time())}_{i}{suffix}")
            with open(save_path, "wb") as fp:
                fp.write(f.getvalue())
            saved_paths.append(save_path)
            time.sleep(0.1)  # 让进度条可见

        upload_progress.progress(100)
        upload_status.caption(f"✅ {len(saved_paths)} 张图片已保存，开始 Agent 处理...")
        time.sleep(0.3)
        upload_progress.empty()
        upload_status.empty()

        # ---- 逐张处理 ----
        for idx, uploaded in enumerate(final_files):
            save_path = saved_paths[idx]

            # 分栏：左边结果，右边日志
            col_r, col_l = st.columns([3, 2])

            # 左栏：进度条 + 预览图（处理完自动收起）
            with col_r:
                status_text = st.empty()
                progress = st.progress(0)
                img_placeholder = st.empty()
                status_text.caption(f"[{idx+1}/{len(final_files)}] {uploaded.name} — 准备中...")
                img_placeholder.image(save_path, caption=uploaded.name, use_container_width=True)

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
                                status_text.caption(f"[{idx+1}/{len(final_files)}] {_sc[k]}...")
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
            status_text.caption(f"[{idx+1}/{len(final_files)}] ✅ 完成")
            # 预览图收进折叠面板，需要时可展开
            with img_placeholder:
                with st.expander("🖼️ 查看原图", expanded=False):
                    st.image(save_path, caption=uploaded.name, use_container_width=True)

            # 左栏：结果展示
            with col_r:
                if result["data"]:
                    d = result["data"]
                    st.session_state.results.append(result)

                    # KPI 行 + 审批建议
                    render_ticket_kpis(d)

                    # 通知推送
                    nc1, nc2 = st.columns(2)
                    with nc1:
                        def _dt_fmt(d):
                            return ("text", f"【安全数字监督员】\n票号: {d.ticket_id}\n场站: {d.station_name}\n状态: {'有隐患' if d.has_abnormal else '正常'}\n风险: {d.risk_level or '-'}\n审批: {d.approval_opinion or '-'}")
                        render_notification_btn("钉钉", "📱", "dingtalk_webhook", _dt_fmt, d, idx, _cfg)
                    with nc2:
                        def _wx_fmt(d):
                            return ("markdown", f"**【安全数字监督员】**\n> 票号: {d.ticket_id}\n> 场站: {d.station_name}\n> 状态: {'有隐患' if d.has_abnormal else '正常'}\n> 风险: {d.risk_level or '-'}\n> 审批: {d.approval_opinion or '-'}")
                        render_notification_btn("微信", "💬", "wechat_webhook", _wx_fmt, d, idx, _cfg)

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
                        with st.expander(f"⚠️ 隐患明细 ({len(d.issues)})", expanded=True):
                            # 未落实的安全措施
                            unimpl = [m for m in d.safety_measures if not m.implemented]
                            if unimpl:
                                st.markdown("**安全措施未落实：**")
                                for m in unimpl:
                                    st.markdown(f"  🔴 第{m.measure_id}项 `{m.description}` — 标记为**未落实×**")
                            # 浓度异常
                            conc_high = [(i, v) for i, v in enumerate(d.gas_concentration) if v > 0]
                            if conc_high:
                                st.markdown("**浓度异常：**")
                                for i, v in conc_high:
                                    st.markdown(f"  🟡 第{i+1}次检测 `{v}%` — 超过0%阈值")
                            # 其他隐患
                            for issue in d.issues:
                                reason = issue.raw_text or "OCR识别为异常标记"
                                st.markdown(f"  ⚠️ **{issue.item_name}** — {reason}")

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
            rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,approval_opinion,risk_level,created_at,image_path FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()
        except Exception:
            rows_db = conn.execute("SELECT id,ticket_id,station_name,worker_id,check_date,has_abnormal,'','',created_at,'' FROM hse_fire_work_tickets ORDER BY id DESC").fetchall()

        total = len(rows_db)
        abn_cnt = sum(1 for r in rows_db if r[5])

        # KPI 行
        render_kpi_row([
            ("总票数", str(total), ""),
            ("有隐患", str(abn_cnt), "#d6131c" if abn_cnt else "#059669"),
            ("正常", str(total - abn_cnt), "#059669"),
            ("隐患率", f"{abn_cnt/total*100:.0f}%" if total else "0%", ""),
        ])

        # 高频隐患
        issue_counter = {}
        try:
            for (ij,) in conn.execute("SELECT issues_json FROM hse_fire_work_tickets WHERE has_abnormal=1").fetchall():
                if ij:
                    for item in json.loads(ij):
                        n = item.get("item_name", "未知"); issue_counter[n] = issue_counter.get(n, 0) + 1
        except Exception: pass
        conn.close()

        if issue_counter:
            top5 = sorted(issue_counter.items(), key=lambda x: -x[1])[:5]
            render_kpi_row([(name, f"{count}次", "#d6131c") for name, count in top5])

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

        # 搜索框（回车或点按钮触发）
        with st.form("search_form", clear_on_submit=False):
            sf1, sf2 = st.columns([5, 1])
            with sf1:
                search = st.text_input("🔍 搜索票号", placeholder="输入票号模糊查询...", label_visibility="collapsed")
            with sf2:
                st.form_submit_button("🔍 搜索", use_container_width=True)

        # 记录列表（搜索过滤）
        for row in rows_db:
            rid, ticket, station, worker, date, abnormal, opinion, risk, created, img_path = row
            if search and search.lower() not in (ticket or "").lower():
                continue
            icon = "🚨" if abnormal else "✅"
            badge_md = render_record_badge(risk, abnormal)

            cm, cd = st.columns([9, 1])
            with cm:
                with st.expander(f"{icon} #{rid} | {ticket} | {station} | {date}{badge_md}", expanded=False):
                    ca, cb = st.columns(2)
                    with ca: st.markdown(f"**票号** {ticket}  \n**场站** {station}  \n**动火人** {worker}  \n**日期** {date}")
                    with cb:
                        st.markdown(f"**状态** {'🔴 有隐患' if abnormal else '🟢 正常'}")
                        if risk: st.markdown(f"**风险** {risk}")
                        st.caption(f"处理: {created}")
                        if opinion: st.caption(f"审批: {opinion}")
                    # 查看原图 + 下载按钮
                    if img_path and os.path.exists(img_path):
                        dc1, dc2 = st.columns(2)
                        with dc1:
                            if st.button("🖼️ 查看原图", key=f"img_{rid}", use_container_width=True):
                                @st.dialog("原图", width="large")
                                def show_orig_img(_path=img_path, _name=ticket):
                                    st.image(_path, caption=_name, use_container_width=True)
                                show_orig_img()
                        with dc2:
                            ext = os.path.splitext(img_path)[1] or ".png"
                            dl_name = f"{ticket or f'作业票_{rid}'}{ext}"
                            with open(img_path, "rb") as f:
                                img_bytes = f.read()
                            st.download_button("⬇️ 下载原图", data=img_bytes, file_name=dl_name, mime="image/png", key=f"dl_{rid}", use_container_width=True)
                    else:
                        st.caption("原图不可用")
            with cd:
                st.markdown("<div style='padding-top:18px'></div>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{rid}", help=f"删除 #{rid}"):
                    st.session_state.delete_id = rid; st.rerun()
