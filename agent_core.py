"""
中燃“安全哨兵”智能体核心架构 - 完整版 (agent_core.py)
面向场景：巡巡检工人手机拍照上传 -> 自动去阴影矫正 -> 本地/线上模型语义结构化 -> 自动化闭环。

设计模式：策略模式（统一大模型接口）。
请在 Claude Code 中运行此文件，并指示其补全其中的 pass 或 NotImplementedError 部分。

依赖库:
pip install pydantic openai llama-cpp-python playwright paddleocr opencv-python numpy
"""

import os
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# ==========================================
# 1. 严格的结构化数据 Schema (Data Schemas)
# ==========================================

class HandWrittenIssue(BaseModel):
    """HSE 作业票中识别出的具体隐患项或安全措施落实异常项"""
    item_name: str = Field(..., description="隐患/检查项名称，如：灭火器压力、阀门气密性、动火安全措施第3项")
    status: str = Field(..., description="状态，必须是 '异常' 或 '正常'")
    raw_text: Optional[str] = Field(None, description="手写备注或 OCR 原文片段，如：'2号消防栓水压偏低'、'可燃气体浓度0.3%'")

class SafetyMeasureItem(BaseModel):
    """动火主要安全措施逐项落实状态"""
    measure_id: int = Field(..., description="措施序号，如 1, 2, 3")
    description: str = Field(..., description="措施内容原文，如：'动火设备内部清洗置换合格'")
    implemented: bool = Field(..., description="是否已落实：True=已落实✓，False=未落实×")

class SecuritySheetData(BaseModel):
    """牡丹江中燃 HSE 管理体系动火作业票结构化数据"""
    ticket_id: str = Field(..., description="作业票编号，如：MPJZR2026004001")
    station_name: str = Field(..., description="动火地点/场站，如：光86了单元")
    content: str = Field(..., description="动火内容，如：引点锈蚀漏气焊接作业")
    worker_id: str = Field(..., description="动火人姓名及证书/身份证号，如：张三 230407198305200210")
    check_date: str = Field(..., description="动火日期，格式 YYYY-MM-DD")
    gas_concentration: List[float] = Field(default=[], description="各时段采样检测可燃气体浓度(%)，如：[0.0, 0.0]")
    safety_measures: List[SafetyMeasureItem] = Field(default=[], description="动火主要安全措施逐项落实状态列表")
    has_abnormal: bool = Field(..., description="是否存在异常：任一浓度>0%或任一安全措施未落实×则为True")
    issues: List[HandWrittenIssue] = Field(default=[], description="隐患项明细列表，若全部正常则为空")
    completion_time: Optional[str] = Field(None, description="完工验收时间，如：2026-06-21 17:30")
    approver_name: Optional[str] = Field(None, description="签批人姓名，如：王琳、刘老")

# ==========================================
# 2. LLM 大脑抽象基类 (接口隔离原则)
# ==========================================

class BaseLLMBrain(ABC):
    """
    大模型大脑的抽象基类。无论底层走线上免费 API 还是本地离线 GGUF，
    对外的输入输出完全一致：输入 OCR 文本，返回结构化的 SecuritySheetData 对象。
    """
    @abstractmethod
    def extract_sheet_json(self, ocr_text: str) -> SecuritySheetData:
        pass

# ------------------------------------------
# 实现类 A：线上免费/极低成本 API 大脑 (标准 OpenAI 兼容格式)
# ------------------------------------------
class OnlineApiBrain(BaseLLMBrain):
    """
    阶段一：快速开发与迭代。使用线上免费额度或低成本 API 平台跑通业务流。
    """
    def __init__(self, api_key: str, base_url: str, model_name: str):
        """
        [Claude Code 补全指引]:
        - 初始化 openai.OpenAI 客户端。
        - 传入兼容 OpenAI 协议的 base_url (例如：硅基流动、DeepSeek 等)。
        """
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

    def extract_sheet_json(self, ocr_text: str) -> SecuritySheetData:
        print(f"[LLM Log] 🌐 正在调用线上 API [{self.model_name}] 进行语义分析与结构化...")

        system_prompt = (
            "你是牡丹江中燃 HSE 管理体系的专职安全审计专家。你的任务是将一线巡检工人手机拍摄、"
            "经 OCR 识别后可能包含错字和噪声的动火作业票文本，精准解析为结构化安全记录。\n\n"
            "【字段提取规则】\n"
            f"输出一个纯 JSON 对象，严格匹配 Schema：\n{SecuritySheetData.model_json_schema()}\n\n"
            "1. ticket_id：作业票编号（如 MPJZR2026004001），直接提取原文。\n"
            "2. station_name：动火地点（如 光86了单元）。\n"
            "3. content：动火内容（如 引点锈蚀漏气焊接作业）。\n"
            "4. worker_id：动火人姓名及证件号（如 张三 230407198305200210）。\n"
            "5. check_date：动火日期，统一为 YYYY-MM-DD 格式。\n"
            "6. gas_concentration：从“采样检测”栏提取所有可燃气体浓度数值(%)，保持原始顺序。"
            "  例如 OCR 文本出现\"09:00 浓度0.0% 10:00 浓度0.0%\"则输出 [0.0, 0.0]。\n"
            "7. safety_measures：逐项提取“动火主要安全措施”列表，每项含 measure_id(序号)、"
            "  description(措施原文)、implemented(已落实✓=true，未落实×=false)。\n"
            "8. has_abnormal：【强制审计规则】以下任一条件成立则必须为 true：\n"
            "   a) gas_concentration 中任一值 > 0；\n"
            "   b) safety_measures 中任一项 implemented=false；\n"
            "   c) OCR 文本中出现“未落实×”、“不合格”、“未检测”等否定表述。\n"
            "9. issues：仅列出异常项明细，每项含 item_name、status(填'异常')、raw_text(原文备注或null)。\n"
            "10. completion_time：完工验收时间（如 2026-06-21 17:30），无则填 null。\n"
            "11. approver_name：签批人姓名（如 王琳、刘老），无则填 null。\n\n"
            "【OCR 容错】OCR 可能把✓识别为√/V/7，把×识别为X/x/×，请容错映射。"
        )

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"以下是巡检工人手机拍摄的牡丹江中燃 HSE 动火作业票 OCR 文本：\n\n{ocr_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        result_json = json.loads(response.choices[0].message.content)
        return SecuritySheetData(**result_json)

# ------------------------------------------
# 实现类 B：本地离线 GGUF 大脑 (为最终演示/完全断网安全合规准备的底牌)
# ------------------------------------------
class LocalGgufBrain(BaseLLMBrain):
    """
    阶段二：决赛现场无网演示、或安全部对核心隐患数据外泄敏感时，一键切换至纯本地运行。
    """
    def __init__(self, model_path: str = "models/qwen2.5-3b-instruct-q4_k_m.gguf", n_threads: int = 0):
        """
        - 导入 llama_cpp 的 Llama 类并初始化。
        - n_threads=0 时自动使用全部 CPU 核心。
        """
        from llama_cpp import Llama
        import multiprocessing
        self.model_path = model_path
        threads = n_threads if n_threads > 0 else multiprocessing.cpu_count()
        print(f"[LLM Log] 💻 加载本地模型: {model_path}, 使用 {threads} 线程")
        self.llm = Llama(model_path=model_path, n_ctx=2048, n_threads=threads)

    def extract_sheet_json(self, ocr_text: str) -> SecuritySheetData:
        print(f"[LLM Log] 💻 正在调用本地全离线模型 [{os.path.basename(self.model_path)}] 进行本地推理...")

        system_prompt = (
            "你是牡丹江中燃 HSE 安全审计专家。将以下动火作业票 OCR 文本解析为严格 JSON。\n"
            f"Schema: {SecuritySheetData.model_json_schema()}\n\n"
            "提取规则：\n"
            "- ticket_id=作业票编号，station_name=动火地点，content=动火内容，worker_id=动火人及证件号\n"
            "- check_date=YYYY-MM-DD\n"
            "- gas_concentration=采样检测所有浓度数值数组[浮点数]，如[0.0, 0.0]\n"
            "- safety_measures=安全措施列表[{measure_id序号, description原文, implemented:已落实✓=true/未落实×=false}]\n"
            "- has_abnormal: 浓度任一>0% 或 安全措施任一未落实× → true\n"
            "- issues=仅异常项[{item_name,status='异常',raw_text备注或null}]\n"
            "- completion_time=完工验收时间或null，approver_name=签批人姓名或null\n"
            "只输出纯JSON，无其他文字。"
        )

        response = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"牡丹江中燃 HSE 动火作业票 OCR 文本:\n{ocr_text}"},
            ],
            response_format={"type": "json_object", "schema": SecuritySheetData.model_json_schema()},
            temperature=0.1,
        )

        result_json = json.loads(response["choices"][0]["message"]["content"])
        return SecuritySheetData(**result_json)


# ==========================================
# 3. 本地执行工具集与前置算法 (Agent Tools)
# ==========================================

class SecurityAgentTools:
    """
    智能体的“手和脚”：负责图像预处理、OCR 识别、数据库写入、外部发信以及自动化表单录入。
    """
    
    @staticmethod
    def _preprocess_image(image_path: str) -> str:
        """
        [内部核心算法]：针对工人在一线使用手机拍摄照片产生的【光照不均、局部阴影、角度歪斜】进行前置清洗。
        
        [Claude Code 补全指引]:
        1. 使用 cv2.imread(image_path) 读取手机拍照图片。
        2. 转换为灰度图：cv2.cvtColor()
        3. 【核心抗阴影】: 使用自适应阈值 (Adaptive Thresholding) 或自适应直方图均衡化 (CLAHE) 
           消除手机遮挡、现场强光产生的局部大片阴影，使底纸变白，文字和 [✓/✗] 勾选符边缘被极其清晰地锐化出来。
           例如：cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        4. 保存处理后的清晰黑白单据图像到临时目录，返回该临时路径供 OCR 引擎读取。
        """
        import cv2
        import numpy as np
        import tempfile
        print(f"[Tool Log] 📸 触发手机相片前置清洗算子：启动自适应去阴影与对比度锐化...")

        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"无法读取图片: {image_path}")

        # 转灰度
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # CLAHE 自适应直方图均衡化：消除局部阴影，让底纸变白
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 自适应阈值二值化：锐化文字与勾选符号边缘
        binary = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8
        )

        # 保存到临时文件
        tmp = tempfile.NamedTemporaryFile(suffix="_cleaned.png", delete=False)
        cv2.imwrite(tmp.name, binary)
        print(f"[Tool Log] 📸 图像清洗完成，已保存至: {tmp.name}")
        return tmp.name

    @staticmethod
    def local_ocr_tool(image_path: str) -> str:
        """
        工具 1：多模态手机照片解析工具。先清洗图像，再通过 OCR 转化为包含文本与相对坐标特征的描述。
        """
        # 1. 自动执行手机照片去阴影、去噪点
        cleaned_path = SecurityAgentTools._preprocess_image(image_path)

        from paddleocr import PaddleOCR
        print("[Tool Log] 🤖 图像清洗完毕。正在拉起本地 PaddleOCR 提取手写体及 [✓/✗] 勾选符号...")

        ocr = PaddleOCR(lang="ch", engine="onnxruntime")
        result = ocr.predict(cleaned_path)

        # PaddleOCR 3.7.0 新 API：result[0].json['res'] 包含 rec_texts, rec_scores, rec_polys
        lines = []
        if result and hasattr(result[0], 'json'):
            res = result[0].json.get('res', {})
            texts = res.get('rec_texts', [])
            scores = res.get('rec_scores', [])
            polys = res.get('rec_polys', [])

            if texts:
                # 按行中心 y 坐标排序，同行内按 x 排序
                entries = []
                for i, text in enumerate(texts):
                    box = polys[i] if i < len(polys) else []
                    if len(box) >= 3:
                        y_center = (box[0][1] + box[2][1]) / 2
                        x_left = box[0][0]
                    else:
                        y_center, x_left = 0, 0
                    entries.append((y_center, x_left, text))

                entries.sort(key=lambda e: (e[0] // 30, e[1]))
                lines = [e[2] for e in entries]

        full_text = "\n".join(lines)
        print(f"[Tool Log] 🤖 OCR 提取完成，共识别 {len(lines)} 行文本。")

        # 清理临时预处理文件
        if cleaned_path != image_path and os.path.exists(cleaned_path):
            os.remove(cleaned_path)

        if not full_text:
            raise RuntimeError(f"OCR 未能从图片中识别任何文字: {image_path}")
        return full_text

    @staticmethod
    def send_wechat_alert_tool(issue_detail: str, receiver: str = "安全负责人") -> bool:
        webhook_url = os.environ.get("WECHAT_WEBHOOK_URL", "")
        print(f"[Tool Log] 🚨 [决策触发]：检测到隐患！已全自动向 {receiver} 推送企业微信警报: {issue_detail}")

        if not webhook_url:
            # ponytail: 无 webhook 地址时 mock 打印，不崩
            print("[Tool Log] ⚠️ 未配置 WECHAT_WEBHOOK_URL 环境变量，跳过实际发送。")
            return True

        import requests
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### 🚨 安全隐患自动警报\n> 接收人：{receiver}\n> {issue_detail}"
            }
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code == 200

    @staticmethod
    def playwright_auto_fill_tool(data: SecuritySheetData) -> bool:
        from playwright.sync_api import sync_playwright
        print(f"[Tool Log] 🌐 [决策触发]：启动 Playwright 自动填报作业票【{data.ticket_id}】...")

        form_path = os.path.join(os.path.dirname(__file__), "mock_oa_form.html")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"file:///{form_path}")

            page.fill("#ticket_id", data.ticket_id)
            page.fill("#station_name", data.station_name)
            page.fill("#content", data.content)
            page.fill("#worker_id", data.worker_id)
            page.fill("#check_date", data.check_date)

            if data.completion_time:
                page.fill("#completion_time", data.completion_time)
            if data.approver_name:
                page.fill("#approver_name", data.approver_name)

            page.click("#submit")
            print(f"[Tool Log] 🌐 作业票 {data.ticket_id} 自动填报完成。")
            browser.close()

        return True

    @staticmethod
    def save_to_sqlite_tool(data: SecuritySheetData, raw_ocr_text: str = "") -> bool:
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
        print(f"[Tool Log] 💾 正在写入 SQLite: {db_path}")

        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hse_fire_work_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                station_name TEXT NOT NULL,
                content TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                check_date TEXT NOT NULL,
                gas_concentration_json TEXT,
                safety_measures_json TEXT,
                has_abnormal INTEGER NOT NULL,
                issues_json TEXT,
                completion_time TEXT,
                approver_name TEXT,
                raw_ocr_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            """INSERT INTO hse_fire_work_tickets
               (ticket_id, station_name, content, worker_id, check_date,
                gas_concentration_json, safety_measures_json, has_abnormal,
                issues_json, completion_time, approver_name, raw_ocr_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.ticket_id,
                data.station_name,
                data.content,
                data.worker_id,
                data.check_date,
                json.dumps(data.gas_concentration, ensure_ascii=False),
                json.dumps([m.model_dump() for m in data.safety_measures], ensure_ascii=False),
                int(data.has_abnormal),
                json.dumps([i.model_dump() for i in data.issues], ensure_ascii=False),
                data.completion_time,
                data.approver_name,
                raw_ocr_text,
            ),
        )
        conn.commit()
        conn.close()
        print(f"[Tool Log] 💾 作业票 {data.ticket_id} 已成功沉淀至本地 SQLite 数据库。")
        return True


# ==========================================
# 4. Agent 记忆系统 (Agent Memory)
# ==========================================

class AgentMemory:
    """Agent 的工作记忆：记录每一步的决策过程，供反思回溯和前端展示"""

    def __init__(self):
        self.steps: List[Dict[str, Any]] = []

    def remember(self, step_name: str, emoji: str, action: str, result: str, status: str = "done"):
        self.steps.append({
            "step": step_name,
            "emoji": emoji,
            "action": action,
            "result": result,
            "status": status,  # "done" | "running" | "error" | "retry"
        })

    def get_summary(self) -> str:
        lines = []
        for s in self.steps:
            lines.append(f"{s['emoji']} [{s['step']}] {s['action']} -> {s['result']}")
        return "\n".join(lines)


# ==========================================
# 5. 智能体 ReAct 控制循环 (Agent Orchestrator)
# ==========================================

class SecurityAgentOrchestrator:
    """
    ReAct 智能体编排器：
    Plan(规划) → Perceive(感知) → Reason(推理) → Reflect(反思) → Act(执行) → Report(总结)

    每一步都有明确的日志输出，让不懂代码的人也能目测 Agent 的完整决策链。
    """

    MAX_REFLECT_RETRIES = 2

    def __init__(self, brain: BaseLLMBrain):
        self.brain = brain
        self.tools = SecurityAgentTools()

    # --------------------------------------------------
    # Step 1: 📋 规划 — Agent 分析任务，制定执行计划
    # --------------------------------------------------
    def _step_plan(self, image_path: str, memory: AgentMemory):
        print("[Agent 📋 Plan] 收到一张巡检作业票照片，Agent 开始制定执行计划...")
        plan_text = (
            "执行计划：\n"
            "  ① 感知：调用 OpenCV 清洗图像 + PaddleOCR 提取文字\n"
            "  ② 推理：调用 LLM 将 OCR 文本结构化为 HSE 作业票 JSON\n"
            "  ③ 反思：校验结构化数据的完整性和合理性\n"
            "  ④ 执行：根据是否存在隐患，自主选择工具组合\n"
            "  ⑤ 总结：输出完整决策链报告"
        )
        print(f"[Agent 📋 Plan] {plan_text}")
        memory.remember("规划", "📋", "分析任务并制定5步执行计划", plan_text)

    # --------------------------------------------------
    # Step 2: 👁️ 感知 — 调用图像预处理 + OCR 工具
    # --------------------------------------------------
    def _step_perceive(self, image_path: str, memory: AgentMemory) -> str:
        print("[Agent 👁️ Perceive] 调用感知工具链：OpenCV 去阴影 → PaddleOCR 文字识别")
        raw_ocr_text = self.tools.local_ocr_tool(image_path)
        line_count = len(raw_ocr_text.strip().split("\n"))
        summary = f"提取到 {line_count} 行文本，包含作业票编号、动火信息、浓度数据"
        print(f"[Agent 👁️ Perceive] 感知完成。{summary}")
        memory.remember("感知", "👁️", "OpenCV + PaddleOCR 提取文字", summary)
        return raw_ocr_text

    # --------------------------------------------------
    # Step 3: 🤔 推理 — 调用 LLM 将 OCR 文本结构化
    # --------------------------------------------------
    def _step_reason(self, ocr_text: str, memory: AgentMemory) -> SecuritySheetData:
        print("[Agent 🤔 Reason] 调用推理工具：LLM 语义分析，将 OCR 文本结构化为 HSE 作业票 JSON")
        data = self.brain.extract_sheet_json(ocr_text)
        summary = (
            f"票号={data.ticket_id} | 场站={data.station_name} | "
            f"动火人={data.worker_id} | 浓度={data.gas_concentration} | "
            f"安全措施={len(data.safety_measures)}项 | 含隐患={data.has_abnormal}"
        )
        print(f"[Agent 🤔 Reason] 推理完成。{summary}")
        memory.remember("推理", "🤔", "LLM 结构化解析", summary)
        return data

    # --------------------------------------------------
    # Step 4: 🔍 反思 — 校验结果，不通过则让 LLM 重试
    # --------------------------------------------------
    def _step_reflect(self, ocr_text: str, data: SecuritySheetData, memory: AgentMemory) -> SecuritySheetData:
        print("[Agent 🔍 Reflect] 进入反思阶段：校验结构化数据的完整性和业务合理性...")

        for attempt in range(1, self.MAX_REFLECT_RETRIES + 1):
            checks = []

            # 校验1: 票号格式
            ticket_ok = bool(data.ticket_id) and len(data.ticket_id) >= 6
            checks.append(("票号格式", ticket_ok, f"{data.ticket_id} {'✅' if ticket_ok else '⚠️ 格式异常'}"))

            # 校验2: 浓度范围
            conc_ok = all(0 <= v <= 100 for v in data.gas_concentration)
            checks.append(("浓度范围", conc_ok, f"{data.gas_concentration} ∈ [0,100] {'✅' if conc_ok else '⚠️ 超出合理范围'}"))

            # 校验3: 异常一致性 — has_abnormal=True 时 issues 应非空
            if data.has_abnormal:
                issues_ok = len(data.issues) > 0
                checks.append(("异常一致性", issues_ok, f"has_abnormal=True, issues={len(data.issues)}条 {'✅' if issues_ok else '⚠️ 标记异常但无明细'}"))
            else:
                checks.append(("异常一致性", True, "has_abnormal=False, 无异常 ✅"))

            # 校验4: 安全措施一致性 — 有未落实项时 has_abnormal 应为 True
            unimplemented = [m for m in data.safety_measures if not m.implemented]
            if unimplemented:
                measure_ok = data.has_abnormal
                checks.append(("安全措施判定", measure_ok, f"{len(unimplemented)}项未落实, has_abnormal={data.has_abnormal} {'✅' if measure_ok else '⚠️ 未落实但未标记异常'}"))
            else:
                checks.append(("安全措施判定", True, "全部已落实 ✅"))

            all_pass = all(ok for _, ok, _ in checks)

            # 输出每条校验结果
            for name, ok, detail in checks:
                icon = "✅" if ok else "⚠️"
                print(f"[Agent 🔍 Reflect]   {icon} {name}: {detail}")

            if all_pass:
                print("[Agent 🔍 Reflect] 反思通过，所有校验项合格，数据可信。")
                memory.remember("反思", "🔍", "校验数据完整性和业务合理性",
                                f"共{len(checks)}项校验全部通过 ✅")
                return data

            # 不通过 → 反思重试
            failed = [name for name, ok, _ in checks if not ok]
            print(f"[Agent 🔍 Reflect] 反思未通过（{', '.join(failed)}），第{attempt}次让 LLM 重新解析...")
            memory.remember("反思", "🔍", f"第{attempt}次校验未通过，触发 LLM 重试",
                            f"未通过项: {', '.join(failed)}", status="retry")

            # 用补充提示让 LLM 重试
            retry_hint = f"上一次解析有问题：{', '.join(failed)}。请严格按规则重新解析，注意校验。"
            data = self.brain.extract_sheet_json(f"[注意重试] {retry_hint}\n\n原始OCR文本:\n{ocr_text}")

        # 重试用完仍不通过 → 用最后一次结果，标记风险
        print("[Agent 🔍 Reflect] 已达最大重试次数，使用最后一次结果，标记为高风险待人工复核。")
        memory.remember("反思", "🔍", "达到最大重试次数", "使用最后一次结果，标记高风险", status="error")
        return data

    # --------------------------------------------------
    # Step 5: ⚡ 执行 — 根据数据自主选择工具组合
    # --------------------------------------------------
    def _step_act(self, data: SecuritySheetData, raw_ocr_text: str, memory: AgentMemory):
        print("[Agent ⚡ Act] 进入执行阶段：根据反思结果，自主选择并调用业务工具...")

        # 工具1: 数据沉淀（必选）
        print("[Agent ⚡ Act]   → 选择工具: SQLite 数据沉淀")
        self.tools.save_to_sqlite_tool(data, raw_ocr_text=raw_ocr_text)

        if data.has_abnormal:
            # 工具2: 企业微信预警
            print("[Agent ⚡ Act]   → 选择工具: 企业微信自动预警推送")
            for issue in data.issues:
                alert_msg = (f"【{data.station_name}】票号:{data.ticket_id} "
                             f"隐患项：{issue.item_name} -> 状态为【{issue.status}】"
                             f"({issue.raw_text or '无备注'}) | 浓度:{data.gas_concentration} "
                             f"签批人:{data.approver_name or '未知'}")
                self.tools.send_wechat_alert_tool(alert_msg)

            # 工具3: Playwright 自动填报
            print("[Agent ⚡ Act]   → 选择工具: Playwright OA 表单自动填报")
            self.tools.playwright_auto_fill_tool(data)

            summary = "已执行: SQLite存库 + 企业微信预警 + Playwright填报（共3个工具）"
        else:
            summary = "已执行: SQLite存库（无隐患，跳过预警和填报，节省资源）"

        print(f"[Agent ⚡ Act] {summary}")
        memory.remember("执行", "⚡", "自主选择工具组合并执行", summary)

    # --------------------------------------------------
    # Step 6: 📊 总结 — 输出完整决策链报告
    # --------------------------------------------------
    def _step_report(self, memory: AgentMemory):
        report = memory.get_summary()
        print(f"[Agent 📊 Report] ========== Agent 决策链完整报告 ==========")
        print(report)
        print(f"[Agent 📊 Report] ========== 共执行 {len(memory.steps)} 个阶段，Agent 任务完成 ==========")
        memory.remember("总结", "📊", "输出完整决策链报告", f"共{len(memory.steps)}个阶段全部完成 ✅")

    # --------------------------------------------------
    # 主入口：运行 Agent ReAct 循环
    # --------------------------------------------------
    def run_pipeline(self, image_path: str):
        """运行安全哨兵 Agent 的完整 ReAct 循环，返回 (ocr_text, structured_data)"""
        memory = AgentMemory()
        import time
        start_time = time.time()

        # Step 1: 规划
        self._step_plan(image_path, memory)

        # Step 2: 感知
        raw_ocr_text = self._step_perceive(image_path, memory)

        # Step 3: 推理
        structured_data = self._step_reason(raw_ocr_text, memory)

        # Step 4: 反思（含重试逻辑）
        structured_data = self._step_reflect(raw_ocr_text, structured_data, memory)

        # Step 5: 执行
        self._step_act(structured_data, raw_ocr_text, memory)

        # Step 6: 总结
        elapsed = time.time() - start_time
        print(f"[Agent ⏱️] 全流程耗时: {elapsed:.1f} 秒")
        self._step_report(memory)

        return raw_ocr_text, structured_data


# ==========================================
# 6. 策略一键切换开关与入口 (Entry Point)
# ==========================================

if __name__ == "__main__":
    # 🌟 核心开发/演示切换开关：
    # True  -> 使用线上第三方免费/便宜的 API（如硅基流动、DeepSeek），开发调试 Prompt 极快，不卡电脑。
    # False -> 切换至单机全离线部署模式（GGUF 格式），决赛现场演示或保障数据安全合规时使用。
    USE_ONLINE_FREE_API = os.environ.get("USE_ONLINE_API", "false").lower() == "true"

    if USE_ONLINE_FREE_API:
        brain_instance = OnlineApiBrain(
            api_key=os.environ.get("ONLINE_API_KEY", "your_free_api_key_here"),
            base_url=os.environ.get("ONLINE_BASE_URL", "https://api.siliconflow.cn/v1"),
            model_name=os.environ.get("ONLINE_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
        )
    else:
        brain_instance = LocalGgufBrain(
            model_path=os.environ.get("GGUF_MODEL_PATH", "models/qwen2.5-3b-instruct-q4_k_m.gguf")
        )
        
    # 实例化并运行数字哨兵智能体
    agent = SecurityAgentOrchestrator(brain=brain_instance)

    # 传入一张巡检工人用手机相机在场站随意拍摄的手制单照片进行模拟测试
    ocr_text, result = agent.run_pipeline("workspace/phone_captured_sheet.jpg")
    print(f"\n[最终结果] OCR 文本:\n{ocr_text}")
    print(f"\n[最终结果] 结构化 JSON:\n{result.model_dump_json(indent=2)}")