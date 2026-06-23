"""
中燃"安全数字监督员"智能体核心架构 (agent_core.py)
面向场景：巡检工人手机拍照上传 -> 自动去阴影矫正 -> 线上API语义结构化 -> 自动化闭环。

依赖库:
pip install pydantic openai paddleocr opencv-python numpy requests
"""

import os
import json
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


# ==========================================
# 1. 结构化数据 Schema
# ==========================================

class HandWrittenIssue(BaseModel):
    """HSE 作业票中识别出的具体隐患项"""
    item_name: str = Field(..., description="隐患/检查项名称")
    status: str = Field(..., description="状态：'异常' 或 '正常'")
    raw_text: Optional[str] = Field(None, description="OCR 原文备注")


class SafetyMeasureItem(BaseModel):
    """动火安全措施逐项落实状态"""
    measure_id: int = Field(..., description="措施序号")
    description: str = Field(..., description="措施内容原文")
    implemented: bool = Field(..., description="True=已落实, False=未落实")


class SecuritySheetData(BaseModel):
    """牡丹江中燃 HSE 动火作业票结构化数据"""
    ticket_id: str = Field(..., description="作业票编号")
    station_name: str = Field(..., description="动火地点/场站")
    content: str = Field(..., description="动火内容")
    worker_id: str = Field(..., description="动火人姓名及证件号")
    check_date: str = Field(..., description="动火日期 YYYY-MM-DD")
    gas_concentration: List[float] = Field(default=[], description="各时段可燃气体浓度(%)")
    safety_measures: List[SafetyMeasureItem] = Field(default=[], description="安全措施落实状态")
    has_abnormal: bool = Field(..., description="是否存在异常")
    issues: List[HandWrittenIssue] = Field(default=[], description="隐患项明细")
    completion_time: Optional[str] = Field(None, description="完工验收时间")
    approver_name: Optional[str] = Field(None, description="签批人姓名")
    approval_opinion: Optional[str] = Field(None, description="自动生成的审批建议")
    risk_level: Optional[str] = Field(None, description="风险等级：重大/较大/一般/低风险")


# ==========================================
# 2. LLM 大脑 (OpenAI 兼容 API)
# ==========================================

class LLMBrain:
    """通过 OpenAI 兼容协议调用线上大模型"""

    def __init__(self, api_key: str, base_url: str, model_name: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
        self.model_name = model_name

    def extract_sheet_json(self, ocr_text: str) -> SecuritySheetData:
        print(f"[LLM Log] 调用 API [{self.model_name}] 进行语义分析...")

        system_prompt = (
            "你是牡丹江中燃 HSE 管理体系的专职安全审计专家。将巡检工人手机拍摄、"
            "经 OCR 识别后可能包含错字的动火作业票文本，精准解析为结构化安全记录。\n\n"
            f"输出纯 JSON，严格匹配 Schema：\n{SecuritySheetData.model_json_schema()}\n\n"
            "提取规则：\n"
            "1. ticket_id：作业票编号（如 MPJZR2026004001）\n"
            "2. station_name：动火地点\n"
            "3. content：动火内容\n"
            "4. worker_id：动火人姓名及证件号\n"
            "5. check_date：YYYY-MM-DD\n"
            "6. gas_concentration：所有可燃气体浓度数值数组，如 [0.0, 0.3]\n"
            "7. safety_measures：安全措施列表，每项含 measure_id、description、implemented(✓=true, ×=false)\n"
            "8. has_abnormal：浓度>0% 或 安全措施未落实 → true\n"
            "9. issues：仅异常项明细\n"
            "10. completion_time / approver_name：无则 null\n"
            "OCR容错：✓可能识别为√/V/7，×识别为X/x"
        )

        # 截断过长 OCR 文本，避免 API 超时（保留前 2000 字符，通常包含票头+关键信息）
        if len(ocr_text) > 2000:
            print(f"[LLM Log] OCR 文本 {len(ocr_text)} 字符，截断至 2000 字符以加速推理")
            ocr_text = ocr_text[:2000]

        print(f"[LLM Log] 发送请求中，请等待...")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"OCR 文本：\n{ocr_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=120,
        )

        return SecuritySheetData(**json.loads(response.choices[0].message.content))


# ==========================================
# 3. 工具集
# ==========================================

class AgentTools:
    """Agent 的执行工具：图像预处理、OCR、数据库、通知"""

    @staticmethod
    def preprocess_image(image_path: str) -> str:
        """OpenCV 去阴影 + 自适应二值化"""
        import cv2
        import tempfile
        print("[Tool] 图像预处理：CLAHE 去阴影 + 自适应二值化...")

        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"无法读取图片: {image_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        binary = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8
        )

        tmp = tempfile.NamedTemporaryFile(suffix="_cleaned.png", delete=False)
        cv2.imwrite(tmp.name, binary)
        return tmp.name

    @staticmethod
    def ocr_tool(image_path: str) -> str:
        """PaddleOCR 文字识别：先试原图，识别不足时再预处理重试"""
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(lang="ch", engine="onnxruntime")

        def _do_ocr(path):
            result = ocr.predict(path)
            lines = []
            if result and hasattr(result[0], 'json'):
                res = result[0].json.get('res', {})
                texts = res.get('rec_texts', [])
                polys = res.get('rec_polys', [])
                if texts:
                    entries = []
                    for i, text in enumerate(texts):
                        box = polys[i] if i < len(polys) else []
                        y = (box[0][1] + box[2][1]) / 2 if len(box) >= 3 else 0
                        x = box[0][0] if box else 0
                        entries.append((y, x, text))
                    entries.sort(key=lambda e: (e[0] // 15, e[1]))
                    lines = [e[2] for e in entries]
            return lines

        # 先试原图
        print("[Tool] PaddleOCR 识别原图...")
        lines = _do_ocr(image_path)

        # 原图识别不足 5 行，预处理后重试
        if len(lines) < 5:
            print("[Tool] 原图识别不足，预处理后重试...")
            cleaned = AgentTools.preprocess_image(image_path)
            lines = _do_ocr(cleaned)
            if os.path.exists(cleaned):
                os.remove(cleaned)

        full_text = "\n".join(lines)
        print(f"[Tool] OCR 完成，识别 {len(lines)} 行。")

        if not full_text:
            raise RuntimeError(f"OCR 未能识别任何文字: {image_path}")
        return full_text

    @staticmethod
    def save_to_db(data: SecuritySheetData, raw_ocr: str = "", image_path: str = "") -> bool:
        """写入 SQLite，自动迁移旧表"""
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
        print(f"[Tool] 写入 SQLite: {db_path}")

        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hse_fire_work_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL, station_name TEXT NOT NULL,
                content TEXT NOT NULL, worker_id TEXT NOT NULL,
                check_date TEXT NOT NULL, gas_concentration_json TEXT,
                safety_measures_json TEXT, has_abnormal INTEGER NOT NULL,
                issues_json TEXT, completion_time TEXT, approver_name TEXT,
                approval_opinion TEXT, risk_level TEXT, raw_ocr_text TEXT,
                image_path TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 自动迁移：给旧表补列
        existing = {row[1] for row in conn.execute("PRAGMA table_info(hse_fire_work_tickets)").fetchall()}
        for col, typ in [("approval_opinion", "TEXT"), ("risk_level", "TEXT"), ("image_path", "TEXT")]:
            if col not in existing:
                conn.execute(f"ALTER TABLE hse_fire_work_tickets ADD COLUMN {col} {typ}")
                print(f"[Tool] 旧表迁移：新增列 {col}")

        conn.execute(
            "INSERT INTO hse_fire_work_tickets "
            "(ticket_id,station_name,content,worker_id,check_date,"
            "gas_concentration_json,safety_measures_json,has_abnormal,"
            "issues_json,completion_time,approver_name,approval_opinion,risk_level,raw_ocr_text,image_path) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.ticket_id, data.station_name, data.content, data.worker_id,
             data.check_date, json.dumps(data.gas_concentration, ensure_ascii=False),
             json.dumps([m.model_dump() for m in data.safety_measures], ensure_ascii=False),
             int(data.has_abnormal),
             json.dumps([i.model_dump() for i in data.issues], ensure_ascii=False),
             data.completion_time, data.approver_name, data.approval_opinion,
             data.risk_level, raw_ocr, image_path),
        )
        conn.commit()
        conn.close()
        print(f"[Tool] 作业票 {data.ticket_id} 已存入数据库。")
        return True

    @staticmethod
    def send_wechat_alert(detail: str, receiver: str = "安全负责人") -> bool:
        """企业微信 Webhook 预警"""
        webhook = os.environ.get("WECHAT_WEBHOOK_URL", "")
        print(f"[Tool] 向 {receiver} 推送企业微信预警...")
        if not webhook:
            print("[Tool] 未配置 WECHAT_WEBHOOK_URL，跳过实际发送。")
            return True
        import requests
        payload = {"msgtype": "markdown", "markdown": {"content": f"### 安全隐患警报\n> {receiver}\n> {detail}"}}
        return requests.post(webhook, json=payload, timeout=10).status_code == 200


# ==========================================
# 4. Agent 记忆系统
# ==========================================

class AgentMemory:
    def __init__(self):
        self.steps: List[Dict[str, Any]] = []

    def remember(self, step: str, emoji: str, action: str, result: str, status: str = "done"):
        self.steps.append({"step": step, "emoji": emoji, "action": action, "result": result, "status": status})

    def get_summary(self) -> str:
        return "\n".join(f"{s['emoji']} [{s['step']}] {s['action']} -> {s['result']}" for s in self.steps)


# ==========================================
# 5. Agent ReAct 编排器
# ==========================================

class SecurityAgent:
    """
    ReAct 智能体：Plan -> Perceive -> Reason -> Reflect -> Act -> Report
    """

    MAX_REFLECT_RETRIES = 2

    def __init__(self, brain: LLMBrain):
        self.brain = brain
        self.tools = AgentTools()

    def _plan(self, image_path: str, mem: AgentMemory):
        print("[Agent Plan] 收到作业票照片，制定执行计划...")
        plan = ("① 感知：OpenCV 清洗 + PaddleOCR 提取\n"
                "② 推理：LLM 结构化为 JSON\n"
                "③ 反思：校验数据完整性\n"
                "④ 执行：自主选择工具\n"
                "⑤ 总结：输出决策链报告")
        print(f"[Agent Plan] {plan}")
        mem.remember("规划", "📋", "制定5步执行计划", plan)

    def _perceive(self, image_path: str, mem: AgentMemory) -> str:
        print("[Agent Perceive] OpenCV + PaddleOCR 感知...")
        text = self.tools.ocr_tool(image_path)
        n = len(text.strip().split("\n"))
        summary = f"提取 {n} 行文本"
        print(f"[Agent Perceive] {summary}")
        mem.remember("感知", "👁️", "OCR 提取文字", summary)
        return text

    def _reason(self, ocr_text: str, mem: AgentMemory) -> SecuritySheetData:
        print("[Agent Reason] LLM 语义分析...")
        data = self.brain.extract_sheet_json(ocr_text)
        summary = (f"票号={data.ticket_id} | 场站={data.station_name} | "
                   f"浓度={data.gas_concentration} | 措施={len(data.safety_measures)}项 | "
                   f"异常={data.has_abnormal}")
        print(f"[Agent Reason] {summary}")
        mem.remember("推理", "🤔", "LLM 结构化解析", summary)
        return data

    def _reflect(self, ocr_text: str, data: SecuritySheetData, mem: AgentMemory) -> SecuritySheetData:
        print("[Agent Reflect] 校验数据完整性...")
        for attempt in range(1, self.MAX_REFLECT_RETRIES + 1):
            checks = []

            ticket_ok = bool(data.ticket_id) and len(data.ticket_id) >= 6
            checks.append(("票号", ticket_ok, f"{data.ticket_id} {'OK' if ticket_ok else '异常'}"))

            conc_ok = all(0 <= v <= 100 for v in data.gas_concentration)
            checks.append(("浓度", conc_ok, f"{data.gas_concentration} {'OK' if conc_ok else '超范围'}"))

            if data.has_abnormal:
                issues_ok = len(data.issues) > 0
                checks.append(("异常一致", issues_ok, f"异常={data.has_abnormal}, 明细={len(data.issues)}条 {'OK' if issues_ok else '缺失'}"))
            else:
                checks.append(("异常一致", True, "无异常 OK"))

            unimpl = [m for m in data.safety_measures if not m.implemented]
            if unimpl:
                checks.append(("措施判定", data.has_abnormal, f"{len(unimpl)}项未落实 {'OK' if data.has_abnormal else '未标记异常'}"))
            else:
                checks.append(("措施判定", True, "全部落实 OK"))

            all_pass = all(ok for _, ok, _ in checks)
            for name, ok, detail in checks:
                print(f"[Agent Reflect]   {'OK' if ok else '!!'} {name}: {detail}")

            if all_pass:
                print("[Agent Reflect] 校验通过。")
                mem.remember("反思", "🔍", "校验数据完整性", f"{len(checks)}项全部通过")
                return data

            failed = [n for n, ok, _ in checks if not ok]
            print(f"[Agent Reflect] 未通过({', '.join(failed)})，第{attempt}次重试...")
            mem.remember("反思", "🔍", f"第{attempt}次重试", f"未通过: {', '.join(failed)}", status="retry")
            hint = f"上次问题：{', '.join(failed)}。请严格按规则重新解析。"
            data = self.brain.extract_sheet_json(f"[重试] {hint}\n\n原文:\n{ocr_text}")

        print("[Agent Reflect] 达到最大重试，标记高风险。")
        mem.remember("反思", "🔍", "最大重试", "标记高风险", status="error")
        return data

    def _generate_approval(self, data: SecuritySheetData) -> str:
        """调用 LLM 生成专业审批建议，列出具体异常项"""
        # 构建异常摘要：逐项列出问题
        issues_desc = ""
        if data.has_abnormal:
            items = []
            # 未落实措施
            for m in data.safety_measures:
                if not m.implemented:
                    items.append(f"第{m.measure_id}项「{m.description}」未落实")
            # 浓度异常
            for i, v in enumerate(data.gas_concentration):
                if v > 0:
                    items.append(f"第{i+1}次检测浓度{v}%超标")
            # 隐患项
            for issue in data.issues:
                items.append(f"{issue.item_name}（{issue.raw_text or '异常'}）")
            issues_desc = "\n".join(f"- {item}" for item in items[:10])

        prompt = (
            "你是HSE安全审计专家，生成动火作业票审批建议。\n\n"
            "【标准依据】\n"
            "- GB 30871-2022 第5.3.2条：浓度低于LEL的20%\n"
            "- GB 30871-2022 第6.4条：动火点10m内清除可燃物配消防器材\n"
            "- GB 30871-2022 第6.5条：监护人全程在场\n\n"
            "【输出格式】\n"
            "无异常→【同意作业】+简要确认\n"
            "有异常→【暂缓作业】+逐项列出问题（简写）+风险等级\n"
            "字数100字以内\n\n"
            f"票号：{data.ticket_id} 场站：{data.station_name}\n"
            f"浓度：{data.gas_concentration} 措施：{len(data.safety_measures)}项\n"
            f"异常：{data.has_abnormal}\n"
            f"{issues_desc}"
        )

        try:
            print("[Agent Act] 调用 LLM 生成审批建议...")
            response = self.brain.client.chat.completions.create(
                model=self.brain.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
                timeout=120,
            )
            opinion = response.choices[0].message.content.strip()

            if data.has_abnormal:
                data.risk_level = self._assess_risk_level(data)
            else:
                data.risk_level = "低风险"

            return opinion
        except Exception as e:
            print(f"[Agent Act] LLM 审批建议生成失败，使用模板: {e}")
            return self._generate_approval_template(data)

    def _assess_risk_level(self, data: SecuritySheetData) -> str:
        """根据异常严重程度评估风险等级"""
        score = 0
        unimpl = [m for m in data.safety_measures if not m.implemented]
        conc_high = [v for v in data.gas_concentration if v > 0]

        if conc_high:
            max_conc = max(conc_high)
            if max_conc > 1.0:
                score += 4  # 重大
            elif max_conc > 0.5:
                score += 3
            elif max_conc > 0:
                score += 2

        score += min(len(unimpl), 3)  # 每项未落实 +1，最多 +3
        score += min(len(data.issues), 2)

        if score >= 5:
            return "重大"
        elif score >= 3:
            return "较大"
        elif score >= 1:
            return "一般"
        return "低风险"

    @staticmethod
    def _generate_approval_template(data: SecuritySheetData) -> str:
        """LLM 失败时的 fallback 模板，列出具体异常"""
        if not data.has_abnormal:
            return f"【同意作业】票号{data.ticket_id}，安全措施已落实，浓度合格。依据GB 30871-2022第5.1条批准。"
        items = []
        for m in data.safety_measures:
            if not m.implemented:
                items.append(f"第{m.measure_id}项未落实")
        for i, v in enumerate(data.gas_concentration):
            if v > 0:
                items.append(f"第{i+1}次浓度{v}%超标")
        for issue in data.issues:
            items.append(f"{issue.item_name}")
        detail = "；".join(items[:5]) if items else "存在异常"
        return f"【暂缓作业】{detail}。依据GB 30871-2022，请整改后重新提交。"

    def _act(self, data: SecuritySheetData, ocr_text: str, mem: AgentMemory, image_path: str = ""):
        print("[Agent Act] 执行工具组合...")

        # 生成审批建议
        data.approval_opinion = self._generate_approval(data)
        print(f"[Agent Act] 审批建议: {data.approval_opinion[:60]}...")

        self.tools.save_to_db(data, raw_ocr=ocr_text, image_path=image_path)

        if data.has_abnormal:
            for issue in data.issues:
                msg = (f"【{data.station_name}】票号:{data.ticket_id} "
                       f"隐患:{issue.item_name}({issue.raw_text or '无备注'}) "
                       f"浓度:{data.gas_concentration} 签批:{data.approver_name or '未知'}")
                self.tools.send_wechat_alert(msg)
            summary = "SQLite + 企业微信预警 (共2个工具)"
        else:
            summary = "SQLite (无隐患，跳过预警)"

        print(f"[Agent Act] {summary}")
        mem.remember("执行", "⚡", "自主选择工具", summary)

    def _report(self, mem: AgentMemory):
        print(f"[Agent Report] ===== 决策链报告 =====")
        print(mem.get_summary())
        print(f"[Agent Report] ===== {len(mem.steps)} 阶段完成 =====")
        mem.remember("总结", "📊", "输出决策链报告", f"{len(mem.steps)}阶段完成")

    def run(self, image_path: str):
        """运行完整 ReAct 循环，返回 (ocr_text, structured_data)"""
        mem = AgentMemory()
        t0 = time.time()

        self._plan(image_path, mem)
        ocr_text = self._perceive(image_path, mem)
        data = self._reason(ocr_text, mem)
        data = self._reflect(ocr_text, data, mem)
        self._act(data, ocr_text, mem, image_path=image_path)

        elapsed = time.time() - t0
        print(f"[Agent] 全流程耗时: {elapsed:.1f}s")
        self._report(mem)
        return ocr_text, data


# ==========================================
# 入口
# ==========================================

def load_config() -> dict:
    """从 config.json 加载配置"""
    cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


if __name__ == "__main__":
    cfg = load_config()
    brain = LLMBrain(
        api_key=cfg.get("api_key", os.environ.get("ONLINE_API_KEY", "")),
        base_url=cfg.get("base_url", os.environ.get("ONLINE_BASE_URL", "")),
        model_name=cfg.get("model_name", os.environ.get("ONLINE_MODEL", "")),
    )
    agent = SecurityAgent(brain=brain)
    ocr_text, result = agent.run("workspace/phone_captured_sheet.jpg")
    print(f"\nOCR:\n{ocr_text}")
    print(f"\nJSON:\n{result.model_dump_json(indent=2)}")
