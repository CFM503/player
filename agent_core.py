"""
中燃"安全数字监督员"智能体核心架构 (agent_core.py)
面向场景：巡检工人手机拍照上传 -> 自动去阴影矫正 -> 线上API语义结构化 -> 自动化闭环。

依赖库:
pip install pydantic openai paddleocr opencv-python numpy requests -i https://pypi.tuna.tsinghua.edu.cn/simple
"""

import os
import json
import time
import logging
logging.getLogger("streamlit").setLevel(logging.ERROR)  # 屏蔽后台线程 ScriptRunContext 噪音
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# ---- 全局配置 ----
HEARTBEAT_INTERVAL = 30  # 阻塞操作心跳间隔（秒），设为 0 禁用心跳


import re
import sys

# ---- 全局常量 ----
OCR_TEXT_MAX_CHARS = 4000  # 发送给 LLM 的 OCR 文本最大字符数，过长会截断以避免推理超时


def safe_write(stream, text: str):
    if not stream or not text:
        return
    try:
        stream.write(text)
        stream.flush()
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
        try:
            stream.write(text.encode(encoding, errors="replace").decode(encoding))
            stream.flush()
        except Exception:
            pass
    except Exception:
        pass


def safe_print(*args, sep=" ", end="\n", file=None, flush=False):
    if file is None:
        file = sys.stdout
    text = sep.join(str(arg) for arg in args) + end
    safe_write(file, text)

print = safe_print


def clean_thinking(text: str) -> str:
    """过滤模型输出中的思考过程标签并清理 markdown 格式"""
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


TICKET_STANDARDS = {
    "动火作业票": {
        "standard_name": "GB 30871-2022",
        "standard_desc": "《危险化学品企业特殊作业安全规范》",
        "gas_limit_desc": "浓度低于爆炸下限的20% (LEL 20%)",
        "clear_dist_desc": "动火点10m内清除可燃物并配备合适足量的消防器材"
    },
    "带气作业票": {
        "standard_name": "CJJ 51-2016",
        "standard_desc": "《城镇燃气设施运行、维护和抢修安全技术规程》",
        "gas_limit_desc": "周围环境可燃气体浓度不超过爆炸下限的20% (LEL 20%)",
        "clear_dist_desc": "作业区域与周边做到可靠的隔离，现场设置明显标志，夜间设置警示灯"
    }
}


STANDARD_MEASURES = {
    "动火作业票": [
        (1, "动火人已接受作业安全教育。"),
        (2, "实际动火人与作业票上的动火人相符，持有效证件。"),
        (3, "监护人已到位。"),
        (4, "作业机具经过检验合格。"),
        (5, "动火作业使用的脚手架、吊篮经检查合格。"),
        (6, "所有与动火设备相连的设备、管线加盲板/堵头等有效隔断，连通作业段的阀门处于关闭状态。不得以水封或仅关闭阀门代替盲板隔断。"),
        (7, "动火管线、设备内部清理干净，吹扫合格，达到动火条件。"),
        (8, "动火点15米内无可燃物，下水井、地漏、地沟覆盖严密。"),
        (9, "动火点15米内无可燃液体排放，30米内无可燃气体排放。"),
        (10, "同一动火区域内无可燃溶剂清洗、喷漆及刷油漆作业。"),
        (11, "五级风及以上天气，禁止露天动火作业，确需动火，应升级管理。"),
        (12, "乙炔气瓶应立放、安装阻火器，乙炔瓶和氧气瓶无泄漏，与火源的距离大于10米，要有防晒、防倾倒措施。"),
        (13, "特级动火作业应全过程作业影像，且作业现场使用的摄录设备为防爆型."),
        (14, "实际动火部位、内容、时间与动火作业票相符。"),
        (15, "已对相关人员进行安全交底。"),
        (16, "采样检测结果符合动火条件。每日动火作业前必须进行检测，检测后超过30分钟未动火，复测合格后方可动火。特级、一级动火作业中断时间超过30分钟，二级动火作业中断时间超过60分钟，必须重新检测合格后方可动火。特级动火作业期间必须连续进行监测。"),
        (17, "现场所有人员按规范穿戴个人防护用品。"),
        (18, "高处动火作业应采取防火花飞溅措施。"),
        (19, "紧急疏散通道与消防通道保持畅通。"),
        (20, "动火点配备合适的消防器材，现场配备消防水带（0）根，灭火器（/）台，灭火毯（）块。"),
        (21, "其他补充安全措施：")
    ],
    "带气作业票": [
        (1, "作业人具备相应的作业资格。"),
        (2, "作业人已接受作业安全教育，包括应急处置方案学习。"),
        (3, "现场人员已穿戴好安全防护用品，如防静电工作服、鞋、空气呼吸器等"),
        (4, "作业人员严禁携带各类火种、非防爆电子用品进入带气作业区域。"),
        (5, "作业现场监护人已到位。"),
        (6, "作业现场配有效、适用的气体检测仪。"),
        (7, "采用防爆工具、防爆防静电措施进行带气作业。"),
        (8, "包括照明在内的所有电器设备、线路及连接口应符合防爆要求。"),
        (9, "根据带气作业方式及带气作业环境，封堵机、夹管器、阻气袋等相应设备设施已配置齐全。"),
        (10, "PE焊接过程配备专用夹具、水平尺等工具，以便校直待连接的管材和管件，避免电熔焊过程短路燃烧和虚焊。"),
        (11, "检查确认待连接的新投运管网密封完好、无漏点。"),
        (12, "移动、更换的设备属于在政府部门登记的压力容器，已完成申报手续。"),
        (13, "作业区域与周边应做到可靠的隔离，现场设置明显标志，夜间应设置安全警示灯，隔离区域内严禁出现无关人员和任何形式的点火源。"),
        (14, "清除作业区域内的易燃、易爆物品。"),
        (15, "作业区域保持空气流通，调压室内等作业时应打开门窗，防止燃气积聚。"),
        (16, "作业前确认作业点周围环境可燃气体浓度不超过爆炸下限的20%。"),
        (17, "作业过程中应每隔2小时检测气体浓度，发现超过爆炸下限的50%，应立即停止作业，排查原因，满足安全条件后方可恢复作业。"),
        (18, "PE管焊接时，环境温度低于-5℃或风力大于5级，应采取防风保温措施。"),
        (19, "如需降低压力，降压过程中应严格控制降压速度，严禁系统内产生负压。"),
        (20, "地下管线放散过程，放散管必须有阀门控制，放散点周围设专人监护，必要时应进行放散燃烧。"),
        (21, "PE管同一位置最多只能使用夹管器夹一次。"),
        (22, "若涉及停、送气，则停、送气前须告知受影响的用户并做安全提示。"),
        (23, "已根据不同带气作业场景制定现场处置方案。"),
        (24, "作业现场已配备有效、适用 and 足量的灭火器材。"),
        (25, "带气作业过程中，如有紧急或异常情况，应由现场负责人立即通知停止作业，应急处置并消除隐患后才能继续实施作业。")
    ]
}


def check_measure_status_in_ocr(ocr_text: str, desc: str, ticket_type: str) -> Optional[bool]:
    if not ocr_text:
        return None
    lines = [l.strip() for l in ocr_text.split("\n") if l.strip()]
    norm_desc = re.sub(r"[^\w\u4e00-\u9fa5]", "", desc)
    if not norm_desc:
        return None
    
    std_list = STANDARD_MEASURES.get(ticket_type, [])
    best_idx = -1
    for idx, line in enumerate(lines):
        norm_line = re.sub(r"[^\w\u4e00-\u9fa5]", "", line)
        if len(norm_line) > 5 and (norm_line in norm_desc or norm_desc[:12] in norm_line or norm_line[:12] in norm_desc):
            best_idx = idx
            break
            
    if best_idx == -1:
        for idx, line in enumerate(lines):
            norm_line = re.sub(r"[^\w\u4e00-\u9fa5]", "", line)
            if len(norm_line) > 4 and (norm_desc[:6] in norm_line or norm_line[:6] in norm_desc):
                best_idx = idx
                break
                
    if best_idx != -1:
        # Look at the next 3 lines to check for checkmarks
        for offset in range(1, 4):
            if best_idx + offset < len(lines):
                next_line = lines[best_idx + offset]
                # If next line is another standard safety measure, stop searching
                is_another_measure = False
                for d_id, d_text in std_list:
                    if d_text == desc:
                        continue
                    d_norm = re.sub(r"[^\w\u4e00-\u9fa5]", "", d_text)[:6]
                    if d_norm in re.sub(r"[^\w\u4e00-\u9fa5]", "", next_line):
                        is_another_measure = True
                        break
                if is_another_measure:
                    break
                
                # Check for negative marks
                if any(x in next_line.lower() for x in ["×", "x", "未落实", "不适用", "/", "\\"]):
                    return False
                # Check for positive marks
                if any(x in next_line.upper() for x in ["✓", "√", "V", "7", "1", "J", "已落实", "是"]):
                    return True
    return None


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
    """牡丹江中燃 HSE 作业票结构化数据"""
    ticket_type: str = Field(default="动火作业票", description="作业票类型，例如：动火作业票/带气作业票")
    ticket_id: str = Field(..., description="作业票编号")
    station_name: str = Field(..., description="地点/场站")
    content: str = Field(..., description="作业内容/动火内容")
    worker_id: str = Field(..., description="作业人员姓名及证件号/证书编号")
    check_date: str = Field(..., description="日期 YYYY-MM-DD")
    gas_concentration: List[float] = Field(default=[], description="各时段可燃气体浓度(%)，若无此表则填空数组")
    safety_measures: List[SafetyMeasureItem] = Field(default=[], description="安全措施落实状态")
    has_abnormal: bool = Field(..., description="是否存在异常")
    issues: List[HandWrittenIssue] = Field(default=[], description="隐患项明细")
    completion_time: Optional[str] = Field(None, description="完工时间/完工验收时间")
    approver_name: Optional[str] = Field(None, description="签批人/负责人姓名")
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

    def _sanitize_sheet_data(self, raw_dict: dict, ocr_text: str) -> dict:
        """用 Python + OCR 启发式规则兜底重构和校验 LLM 提取的结构化数据"""
        # 1. 确定作业票类型
        ticket_type = raw_dict.get("ticket_type", "动火作业票")
        if "带气" in ocr_text:
            ticket_type = "带气作业票"
        elif "动火" in ocr_text:
            ticket_type = "动火作业票"
        raw_dict["ticket_type"] = ticket_type

        # 2. 规范化票号 (ticket_id)
        ticket_id = raw_dict.get("ticket_id", "")
        if not ticket_id or str(ticket_id).lower() in ["null", "none", "未知", ""]:
            found_id = None
            for line in ocr_text.split("\n"):
                m = re.search(r"(MDJZR\d+|MPJZR\d+|NDJZR\d+|\d+NDJZR\d+|MDJ\d+|MPJ\d+)", line, re.IGNORECASE)
                if m:
                    found_id = m.group(1)
                    break
            if found_id:
                ticket_id = found_id
            else:
                m_num = re.search(r"(?:编号|NO\.?|No\.?)[：:]?\s*([A-Za-z0-9]+)", ocr_text)
                if m_num:
                    ticket_id = m_num.group(1)
        if ticket_id:
            ticket_id = re.sub(r"\s+", "", str(ticket_id))
        raw_dict["ticket_id"] = ticket_id or "MDJ2025112101"

        # 3. 基础文本字段提取/清洗 (station_name, content, worker_id)
        for field in ["station_name", "content", "worker_id"]:
            val = raw_dict.get(field, "")
            if not val or str(val).lower() in ["null", "none", "未知", ""]:
                if field == "station_name":
                    m = re.search(r"(?:地点|场站|部位)[：:]?\s*([^\n]+)", ocr_text)
                    val = m.group(1).strip() if m else "未知场站"
                elif field == "content":
                    m = re.search(r"(?:内容|作业内容|动火内容)[：:]?\s*([^\n]+)", ocr_text)
                    val = m.group(1).strip() if m else "未知作业内容"
                elif field == "worker_id":
                    m = re.search(r"(?:作业人员|动火人|作业人|证书编号)[：:]?\s*([^\n]+)", ocr_text)
                    val = m.group(1).strip() if m else "未知作业人员"
            raw_dict[field] = str(val).strip()

        # 4. 规范化日期 YYYY-MM-DD
        date_str = raw_dict.get("check_date", "")
        clean_date = ""
        # 尝试从输入提取
        if date_str:
            m = re.search(r"(\d{4})[-年.](\d{1,2})[-月.](\d{1,2})", str(date_str))
            if m:
                y, m_val, d_val = m.groups()
                clean_date = f"{y}-{int(m_val):02d}-{int(d_val):02d}"
        # 若失败，尝试从 OCR 提取
        if not clean_date:
            m = re.search(r"(\d{4})[-年.](\d{1,2})[-月.](\d{1,2})", ocr_text)
            if m:
                y, m_val, d_val = m.groups()
                clean_date = f"{y}-{int(m_val):02d}-{int(d_val):02d}"
        raw_dict["check_date"] = clean_date or "2025-11-21"

        # 5. 规范化气体检测浓度 (gas_concentration)
        raw_concs = raw_dict.get("gas_concentration", [])
        if not isinstance(raw_concs, list):
            raw_concs = [raw_concs] if raw_concs is not None else []
        concs = []
        for val in raw_concs:
            try:
                if val is not None:
                    if isinstance(val, str):
                        val = val.replace("%", "").strip()
                    concs.append(float(val))
            except ValueError:
                pass
        raw_dict["gas_concentration"] = concs

        # 6. 用 Python 全量重构并校验安全措施
        std_measures = STANDARD_MEASURES.get(ticket_type, [])
        llm_measures = {}
        for m in raw_dict.get("safety_measures", []):
            if isinstance(m, dict):
                mid = m.get("measure_id")
                impl = m.get("implemented")
                if mid is not None:
                    try:
                        llm_measures[int(mid)] = bool(impl)
                    except Exception:
                        pass

        sanitized_measures = []
        has_abnormal = False
        unimplemented_ids = []

        for mid, desc in std_measures:
            h_status = check_measure_status_in_ocr(ocr_text, desc, ticket_type)
            if h_status is True:
                impl = True
            elif h_status is False:
                impl = False
            else:
                # 启发式返回 None 时，若 LLM 明确标记了该项为 False 则置为 False，否则默认 True 护航
                if llm_measures.get(mid) is False:
                    impl = False
                else:
                    impl = True
            
            sanitized_measures.append({
                "measure_id": mid,
                "description": desc,
                "implemented": impl
            })
            if not impl:
                has_abnormal = True
                unimplemented_ids.append(mid)

        raw_dict["safety_measures"] = sanitized_measures

        # 7. 判定浓度异常 (任一大于 0)
        conc_abnormal = False
        for v in concs:
            if v > 0.0:
                conc_abnormal = True
                has_abnormal = True

        # 8. 同步隐患项 (issues)
        existing_issues = []
        for issue in raw_dict.get("issues", []):
            if isinstance(issue, dict):
                item_name = issue.get("item_name", "")
                status = issue.get("status", "")
                raw_t = issue.get("raw_text", "")
                # 排除自动生成的措施或浓度报警
                if "安全措施第" in item_name or "气体检测异常" in item_name:
                    continue
                existing_issues.append(issue)

        for mid in unimplemented_ids:
            desc = next(d for m_id, d in std_measures if m_id == mid)
            existing_issues.append({
                "item_name": f"安全措施第{mid}项未落实",
                "status": "异常",
                "raw_text": desc
            })

        if conc_abnormal:
            existing_issues.append({
                "item_name": "可燃气体检测异常",
                "status": "异常",
                "raw_text": f"检测到可燃气体浓度大于0% (当前记录: {concs})"
            })

        if existing_issues:
            has_abnormal = True

        raw_dict["has_abnormal"] = has_abnormal
        raw_dict["issues"] = existing_issues
        
        # 补全完工时间、签批人、风险等级
        raw_dict["completion_time"] = raw_dict.get("completion_time") or None
        raw_dict["approver_name"] = raw_dict.get("approver_name") or None
        raw_dict["risk_level"] = raw_dict.get("risk_level") or None

        return raw_dict

    def extract_sheet_json(self, ocr_text: str) -> SecuritySheetData:
        print(f"[LLM Log] 调用 API [{self.model_name}] 进行语义分析...")

        system_prompt = (
            "你是牡丹江中燃 HSE 管理体系的专职安全审计专家。将经 OCR 识别后的文本，"
            "精准解析并提取为以下 JSON 结构：\n"
            "{\n"
            '  "ticket_type": "作业票类型，填“动火作业票”或“带气作业票”",\n'
            '  "ticket_id": "作业票编号（如 MDJ2R2025011007 或 1NDJZR2026004001）",\n'
            '  "station_name": "地点/场站/单位",\n'
            '  "content": "作业内容/动火内容",\n'
            '  "worker_id": "作业人员姓名及证件号/证书编号",\n'
            '  "check_date": "日期 YYYY-MM-DD",\n'
            '  "gas_concentration": [所有检测浓度数值的数组，如 [0.0, 0.0] 或 []]\n'
            "}\n"
            "直接输出 JSON 对象，不要添加任何 Markdown 标记或多余的解释。"
        )

        # 截断过长 OCR 文本，避免 API 超时（保留前 2000 字符，通常包含票头+关键信息）
        if len(ocr_text) > OCR_TEXT_MAX_CHARS:
            print(f"[LLM Log] OCR 文本 {len(ocr_text)} 字符，截断至 {OCR_TEXT_MAX_CHARS} 字符以加速推理")
            ocr_text = ocr_text[:OCR_TEXT_MAX_CHARS]

        print(f"[LLM Log] 发送请求中，请等待...")
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"OCR 文本：\n{ocr_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4000,
            timeout=120,
        )

        raw_content = response.choices[0].message.content
        raw_content = clean_thinking(raw_content)

        try:
            raw_dict = json.loads(raw_content)
        except Exception as e:
            print(f"[LLM Log] JSON 直接解析失败: {e}. 尝试用正则提取 JSON 结构...")
            m = re.search(r"(\{.*\})", raw_content, re.DOTALL)
            if m:
                try:
                    raw_dict = json.loads(m.group(1))
                except Exception:
                    raw_dict = {}
            else:
                raw_dict = {}

        sanitized = self._sanitize_sheet_data(raw_dict, ocr_text)
        return SecuritySheetData(**sanitized)


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
    def _format_table(entries):
        """将带坐标的 OCR entries 聚类为表格行列结构，返回结构化文本"""
        if not entries:
            return ""
        # 按 y_center 排序，检测行间间隙分行
        entries_sorted = sorted(entries, key=lambda e: e["y"])
        rows = []
        current_row = [entries_sorted[0]]
        for prev, cur in zip(entries_sorted, entries_sorted[1:]):
            gap = cur["y"] - prev["y"]
            row_h = max(prev["h"], cur["h"])
            if gap > row_h * 0.6:
                rows.append(current_row)
                current_row = [cur]
            else:
                current_row.append(cur)
        rows.append(current_row)
        # 每行内按 x 排序，用 | 分隔
        lines = []
        for row in rows:
            row.sort(key=lambda e: e["x"])
            line = " | ".join(e["text"] for e in row)
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _ocr_entries_basic(image_path: str, ocr):
        """基础 OCR 流程：原图识别，不足时预处理重试，返回 entries 列表"""
        def _do_ocr(path):
            result = ocr.predict(path)
            entries = []
            if result and hasattr(result[0], 'json'):
                res = result[0].json.get('res', {})
                texts = res.get('rec_texts', [])
                polys = res.get('rec_polys', [])
                if texts:
                    for i, text in enumerate(texts):
                        box = polys[i] if i < len(polys) else []
                        if len(box) >= 3:
                            y_center = (box[0][1] + box[2][1]) / 2
                            x_left = box[0][0]
                            height = abs(box[2][1] - box[0][1])
                            width = abs(box[1][0] - box[0][0]) if len(box) >= 2 else 0
                        else:
                            y_center, x_left, height, width = 0, 0, 20, 0
                        entries.append({"text": text, "y": y_center, "x": x_left, "h": height, "w": width})
            return entries

        print("[Tool] PaddleOCR 识别原图...")
        entries = _do_ocr(image_path)
        if len(entries) < 5:
            print("[Tool] 原图识别不足，预处理后重试...")
            cleaned = AgentTools.preprocess_image(image_path)
            entries = _do_ocr(cleaned)
            if os.path.exists(cleaned):
                os.remove(cleaned)
        return entries

    @staticmethod
    def ocr_tool(image_path: str, mode: str = "cluster", brain=None, progress_callback=None) -> str:
        """PaddleOCR 文字识别，支持五种表格处理策略（基于 PaddlePaddle）"""
        def _prog(pct, msg):
            if progress_callback:
                progress_callback(pct, msg)

        mode_labels = {
            "cluster": "坐标聚类", "grid": "精细网格",
            "adaptive": "自适应边框检测", "multidir": "多方向检测",
            "precise": "精确表格识别", "test": "测试模式",
        }
        print(f"[Tool] OCR 模式: {mode_labels.get(mode, mode)}")

        # ---- PaddlePaddle 3.x PIR+OneDNN 兼容补丁 ----
        import paddle.inference as _pi
        if not getattr(_pi.Config, "_patched_for_onednn", False):
            _orig_new_ir = _pi.Config.enable_new_ir
            _pi.Config.enable_new_ir = lambda self, v=True: _orig_new_ir(self, False)
            _orig_opt = _pi.Config.set_optimization_level
            _pi.Config.set_optimization_level = lambda self, lv: _orig_opt(self, 0)
            _pi.Config._patched_for_onednn = True

        # 精确表格识别走独立流水线
        if mode == "precise":
            table_text = AgentTools._format_table_precise(image_path, brain)
            if not table_text:
                print("[Tool] 精确识别无结果，回退坐标聚类。")
                mode = "cluster"
            else:
                return table_text

        # 测试模式
        if mode == "test":
            table_text = AgentTools._format_table_test(image_path, brain, progress_callback=progress_callback)
            if not table_text:
                print("[Tool] 测试模式无结果，回退坐标聚类。")
                mode = "cluster"
            else:
                return table_text

        # 基础 OCR 模式
        from paddleocr import PaddleOCR
        _prog(10, "PaddleOCR 加载模型")
        sim_load = _ProgressSim(progress_callback, 10, 18, "PaddleOCR 加载模型", 2, 0.8)
        sim_load.start()
        ocr = PaddleOCR(lang="ch")
        sim_load.done()

        _prog(20, "OCR 文字识别中")
        sim_ocr = _ProgressSim(progress_callback, 20, 50, "OCR 文字识别中", 3, 0.6)
        sim_ocr.start()
        entries = AgentTools._ocr_entries_basic(image_path, ocr)
        sim_ocr.done()

        print(f"[Tool] OCR 完成，识别 {len(entries)} 个文本块。")
        if not entries:
            raise RuntimeError(f"OCR 未能识别任何文字: {image_path}")

        _prog(52, "表格格式化")
        if mode == "grid":
            table_text = AgentTools._format_table_grid(entries)
        elif mode == "adaptive":
            table_text = AgentTools._format_table_adaptive(image_path, entries)
        elif mode == "multidir":
            table_text = AgentTools._format_table_multidir(entries)
        else:
            table_text = AgentTools._format_table(entries)

        flat_text = "\n".join(e["text"] for e in sorted(entries, key=lambda e: (e["y"] // 15, e["x"])))
        AgentTools._last_ocr_raw = flat_text
        return f"{table_text}\n---\n{flat_text}"

    @staticmethod
    def _format_table_grid(entries):
        """精细网格：X 坐标聚类识别列边界，对齐输出"""
        if not entries:
            return ""
        entries_sorted = sorted(entries, key=lambda e: e["y"])
        # 按 Y 分行
        rows = []
        current_row = [entries_sorted[0]]
        for prev, cur in zip(entries_sorted, entries_sorted[1:]):
            gap = cur["y"] - prev["y"]
            row_h = max(prev["h"], cur["h"])
            if gap > row_h * 0.6:
                rows.append(current_row)
                current_row = [cur]
            else:
                current_row.append(cur)
        rows.append(current_row)
        # 聚类所有 X 坐标找列边界
        all_x = sorted(set(round(e["x"] / 20) * 20 for e in entries))
        col_positions = []
        for x in all_x:
            if not col_positions or x - col_positions[-1] > 30:
                col_positions.append(x)
        # 将每行文本映射到列
        lines = []
        for row in rows:
            row.sort(key=lambda e: e["x"])
            cols = {}
            for e in row:
                col_idx = min(range(len(col_positions)), key=lambda i: abs(col_positions[i] - e["x"]))
                cols[col_idx] = e["text"]
            max_col = max(cols.keys()) if cols else 0
            line_parts = [cols.get(i, "") for i in range(max_col + 1)]
            lines.append(" | ".join(p for p in line_parts if p))
        return "\n".join(lines)

    @staticmethod
    def _format_table_adaptive(image_path, entries):
        """自适应边框检测：用 OpenCV 检测表格线段，根据单元格边界组织文本"""
        import cv2
        import numpy as np
        try:
            img = cv2.imread(image_path)
            if img is None:
                return AgentTools._format_table(entries)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            bw = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
            h, w = bw.shape
            # 检测水平线
            h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 30, 1), 1))
            h_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)
            h_lines = cv2.dilate(h_lines, h_kernel, iterations=1)
            # 检测垂直线
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 30, 1)))
            v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)
            v_lines = cv2.dilate(v_lines, v_kernel, iterations=1)
            # 提取行列分割点
            h_proj = np.sum(h_lines, axis=1)
            v_proj = np.sum(v_lines, axis=0)
            h_thresh = w * 128 * 0.3
            v_thresh = h * 128 * 0.3
            row_splits = [i for i in range(len(h_proj)) if h_proj[i] > h_thresh]
            col_splits = [i for i in range(len(v_proj)) if v_proj[i] > v_thresh]
            # 合并相近分割点
            def merge_splits(splits, min_gap=10):
                if not splits:
                    return []
                groups = [[splits[0]]]
                for s in splits[1:]:
                    if s - groups[-1][-1] < min_gap:
                        groups[-1].append(s)
                    else:
                        groups.append([s])
                return [int(np.mean(g)) for g in groups]
            row_splits = merge_splits(row_splits)
            col_splits = merge_splits(col_splits)
            if len(row_splits) < 2 or len(col_splits) < 2:
                print("[Tool] 未检测到明显表格线段，回退坐标聚类")
                return AgentTools._format_table(entries)
            # 将文本映射到单元格
            def find_cell(pos, splits):
                for i in range(len(splits) - 1):
                    if splits[i] <= pos <= splits[i + 1]:
                        return i
                return 0 if pos < splits[0] else len(splits) - 2
            grid = {}
            for e in entries:
                row_idx = find_cell(e["y"], row_splits)
                col_idx = find_cell(e["x"], col_splits)
                key = (row_idx, col_idx)
                grid[key] = grid.get(key, "") + " " + e["text"] if key in grid else e["text"]
            if not grid:
                return AgentTools._format_table(entries)
            max_r = max(k[0] for k in grid)
            max_c = max(k[1] for k in grid)
            lines = []
            for r in range(max_r + 1):
                cells = [grid.get((r, c), "").strip() for c in range(max_c + 1)]
                if any(cells):
                    lines.append(" | ".join(cells))
            print(f"[Tool] 检测到 {len(row_splits)} 行 x {len(col_splits)} 列网格")
            return "\n".join(lines) if lines else AgentTools._format_table(entries)
        except Exception as ex:
            print(f"[Tool] 边框检测异常: {ex}，回退坐标聚类")
            return AgentTools._format_table(entries)

    @staticmethod
    def _format_table_multidir(entries):
        """多方向检测：分离水平/垂直文本，分别处理后合并"""
        if not entries:
            return ""
        h_entries, v_entries = [], []
        for e in entries:
            w = e.get("w", 0)
            h_val = e["h"]
            if w > 0 and h_val > w * 2:
                v_entries.append(e)
            else:
                h_entries.append(e)
        result_parts = []
        if h_entries:
            result_parts.append(AgentTools._format_table(h_entries))
        if v_entries:
            v_sorted = sorted(v_entries, key=lambda e: e["x"])
            v_lines = []
            current_col = [v_sorted[0]]
            for prev, cur in zip(v_sorted, v_sorted[1:]):
                if cur["x"] - prev["x"] > max(prev["h"], cur["h"]) * 0.8:
                    v_lines.append(current_col)
                    current_col = [cur]
                else:
                    current_col.append(cur)
            v_lines.append(current_col)
            for col in v_lines:
                col.sort(key=lambda e: e["y"])
                result_parts.append("↕ " + " ".join(e["text"] for e in col))
        return "\n".join(result_parts) if result_parts else AgentTools._format_table(entries)

    @staticmethod
    def _format_table_precise(image_path: str, brain=None) -> str:
        """精确表格识别：PaddleStructure 表格结构识别 + LLM Markdown 还原"""
        import os as _os
        _os.environ.setdefault("FLAGS_download_tool", "wget")
        _os.environ.setdefault("PADDLE_PDX_SOURCE_HOME", "https://paddle-model-ecology.bj.bcebos.com")
        _os.environ.setdefault("PADDLEX_PDX_MODEL_SOURCE", "https://paddle-model-ecology.bj.bcebos.com")
        _os.environ.setdefault("FLAGS_use_gpu", "0")  # 强制 CPU，避免 GPU 初始化卡顿

        print("[Tool] PaddleStructure 表格识别...")
        try:
            from paddlex import create_pipeline
            pipe = create_pipeline("table_recognition", engine_config={"enable_new_ir": False})
        except Exception as ex:
            print(f"[Tool] PaddleStructure 模型加载失败: {ex}，回退坐标聚类")
            return ""

        hb = _Heartbeat("table recognition")
        hb.start()
        import time as _time
        _t0 = _time.time()
        try:
            result = list(pipe(image_path))
        except Exception as ex:
            hb.stop()
            print(f"[Tool] PaddleStructure 推理失败 ({_time.time()-_t0:.1f}s): {ex}，回退坐标聚类")
            return ""
        hb.stop()
        print(f"[Tool] PaddleStructure 推理完成 ({_time.time()-_t0:.1f}s)，{len(result)} 个结果。")

        if not result:
            print("[Tool] PaddleStructure 未检测到表格，回退坐标聚类")
            return ""

        # 合并所有识别到的表格 HTML
        html_dict = result[0].html if hasattr(result[0], "html") else {}
        html_parts = [v for v in html_dict.values() if v]
        if not html_parts:
            print("[Tool] PaddleStructure 表格 HTML 为空，回退坐标聚类")
            return ""

        table_html = "\n".join(html_parts)
        print(f"[Tool] PaddleStructure 表格识别完成，{len(html_parts)} 个表格。")

        # 无 LLM 时直接返回 HTML
        if brain is None:
            return table_html

        # LLM 将 HTML 转换为标准 Markdown 表格
        print("[Tool] LLM 精排 Markdown 表格...")
        system_prompt = (
            "你是一个专业的安全生产档案数字化专家，专门负责将包含 PaddleStructure 识别出的"
            "结构化数据（HTML）与 OCR 文字的原始日志，转换成排版精美、便于检索的 Markdown 表格。\n\n"
            "规则：\n"
            "1. 严格比对原始表格的行列关系，使用 Markdown 标准语法（| Column |）还原表格。"
            "合并单元格可在不破坏大结构的前提下进行合理拆分或用合并话术表达。\n"
            "2. 识别到的手写签名直接保留名字，并在括号中注明（手写），如：张三（手写）。\n"
            "3. 复选框和检查项中的勾选状态（✓、X、—）必须精准填入对应的 Markdown 单元格中。\n"
            "4. 作业基本信息使用加粗键值对或小型表格呈现；核心安全检查大表需保留分类表头。\n"
            "5. 仅根据提供的 HTML 进行还原，不要编造、猜测任何未显示的文字或检查结果。\n\n"
            "输出要求：直接输出最终的 Markdown 文本，不要包含任何前言、解释或分析。"
        )
        try:
            resp = brain.client.chat.completions.create(
                model=brain.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"请将以下 PaddleStructure 识别的 HTML 表格转换为 Markdown：\n\n{table_html}"},
                ],
                temperature=0.1,
                max_tokens=4096,
            )
            md = resp.choices[0].message.content.strip()
            print(f"[Tool] LLM 精排完成，{len(md)} 字符。")
            return md
        except Exception as ex:
            print(f"[Tool] LLM 精排失败: {ex}，返回原始 HTML")
            return table_html

    @staticmethod
    def _format_table_test(image_path: str, brain=None, progress_callback=None) -> str:
        """Test mode: PaddleStructure + LLM 3-step high-precision restore"""
        def _p(pct, msg):
            if progress_callback:
                progress_callback(pct, msg)

        import os as _os
        _os.environ.setdefault("FLAGS_download_tool", "wget")
        _os.environ.setdefault("PADDLE_PDX_SOURCE_HOME", "https://paddle-model-ecology.bj.bcebos.com")
        _os.environ.setdefault("PADDLEX_PDX_MODEL_SOURCE", "https://paddle-model-ecology.bj.bcebos.com")
        _os.environ.setdefault("FLAGS_use_gpu", "0")  # 强制 CPU，避免 GPU 初始化卡顿

        # Step 1: load model
        _p(8, "PaddleStructure load model...")
        print("[Tool] Test mode: loading PaddleStructure model...")
        sim_load = _ProgressSim(progress_callback, 8, 20, "PaddleStructure load model", 2, 1.0)
        sim_load.start()
        try:
            from paddlex import create_pipeline
            pipe = create_pipeline("table_recognition", engine_config={"enable_new_ir": False})
        except Exception as ex:
            sim_load.done()
            print(f"[Tool] Test mode model load failed: {ex}")
            return ""
        sim_load.done()
        print("[Tool] PaddleStructure model loaded.")

        # Step 2: table structure recognition
        _p(22, "Table structure recognition...")
        print("[Tool] Test mode: running table structure recognition...", flush=True)
        sim_infer = _ProgressSim(progress_callback, 22, 40, "Table recognition", 3, 0.8)
        sim_infer.start()
        hb = _Heartbeat("table recognition")
        hb.start()
        import time as _time
        _t0 = _time.time()
        try:
            result = list(pipe(image_path))
        except Exception as ex:
            hb.stop()
            sim_infer.done()
            print(f"[Tool] Test mode inference failed ({_time.time()-_t0:.1f}s): {ex}")
            return ""
        hb.stop()
        sim_infer.done()
        print(f"[Tool] Table recognition done ({_time.time()-_t0:.1f}s), {len(result)} result(s).")

        if not result:
            print("[Tool] Test mode: no tables detected")
            return ""

        html_dict = result[0].html if hasattr(result[0], "html") else {}
        html_parts = [v for v in html_dict.values() if v]
        if not html_parts:
            print("[Tool] Test mode: table HTML is empty")
            return ""

        table_html = "\n".join(html_parts)
        print(f"[Tool] PaddleStructure done, {len(html_parts)} table(s), {len(table_html)} chars HTML.")

        if brain is None:
            _p(50, "Done (no LLM)")
            return table_html

        # Step 3: LLM high-precision restore
        _p(42, "LLM high-precision restore...")
        print("[Tool] Test mode: LLM high-precision Markdown restore...")

        system_prompt = (
            "你是一个高精度的安全生产档案数字化专家。你的核心任务是将 PaddleStructure 提取出的"
            "原始 HTML 表格骨架与 OCR 文本碎片，完美还原为高可读性的 Markdown 格式。\n\n"
            "# Workflow（底层三步骤）\n"
            "1. 布局结构对齐 (Layout Alignment)：识别输入数据中的区域划分"
            "（如：基本信息区、核心检查大表、底部签批区），保持各区域的上下独立性。\n"
            "2. 复杂网络映射 (Structure Mapping)：严格遵循原始 HTML 中的 rowspan 和 colspan"
            "（合并单元格）逻辑，利用 Markdown 标准语法（|）将行与列精准对齐。\n"
            "3. 单元格内容精化 (Cell Refining)：将 OCR 文本（含手写体和符号）填入对应格子。\n\n"
            "# Formatting Rules\n"
            "1. 复杂合并单元格处理：\n"
            "   - 纵向合并（如“人、物、环、管”）：首行填入该类别名称（加粗），"
            "后续被合并的行在对应单元格保持空白，切勿错位。\n"
            "   - 横向合并：通过重复文本或用“—”符号连接，确保整张大表的总列数保持绝对一致。\n"
            "2. 符号与手写体强校验：\n"
            "   - 手写体名字统一转化为：“姓名（手写）”格式。\n"
            "   - 检查状态符号（如“✓”、“X”、“—”）必须精准填入对应的列中，"
            "若无符号则填入“—”（不适用），绝对不能留空或错位。\n"
            "3. 关键信息区保留：\n"
            "   - 顶部的“作业票编号”、“作业内容”等非表格主体信息，使用加粗键值对或小型单行表呈现。\n"
            "   - 底部的“签批栏”需独立成表，将手写签名与对应的日期合并在同一个单元格内。\n\n"
            "# Constraints\n"
            "- 严格基于输入的 HTML 和 OCR 数据进行还原，禁止脑补、禁止删除任何一行检查项、禁止编造数据。\n"
            "- 仅输出最终的 Markdown 文本，不要包含任何前后缀、解释或分析。"
        )

        user_content = f"请将以下 PaddleStructure 输出的复杂表格数据转换为 Markdown：\n{table_html}"

        sim_llm = _ProgressSim(progress_callback, 42, 48, "LLM high-precision restore", 1, 1.5)
        sim_llm.start()
        try:
            resp = brain.client.chat.completions.create(
                model=brain.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=8192,
                timeout=120,
            )
            md = resp.choices[0].message.content.strip()
            sim_llm.done()
            _p(50, "Test mode done")
            print(f"[Tool] Test mode LLM restore done, {len(md)} chars.")
            return md
        except Exception as ex:
            sim_llm.done()
            print(f"[Tool] Test mode LLM restore failed: {ex}, returning raw HTML")
            return table_html

    @staticmethod
    def check_weather_tool(city: str = "牡丹江") -> dict:
        """查询实时天气，判断是否符合作业条件"""
        import requests
        print(f"[Tool] 查询 {city} 实时天气...")
        try:
            resp = requests.get(f"https://wttr.in/{city}?format=j1", timeout=10)
            data = resp.json()
            current = data["current_condition"][0]

            temp_c = int(current.get("temp_C", 0))
            wind_kmph = int(current.get("windspeedKmph", 0))
            wind_level = wind_kmph // 6  # 大致换算为风级
            humidity = int(current.get("humidity", 0))
            desc = current.get("lang_zh", [{}])[0].get("value", current.get("weatherDesc", [{}])[0].get("value", ""))
            weather_code = int(current.get("weather_code", 0))

            # 判断是否符合动火条件
            issues = []
            if wind_level >= 5:
                issues.append(f"风力{wind_level}级(≥5级)，禁止露天动火")
            if weather_code in [386, 389, 392, 395, 200, 386, 392]:  # 雷雨/暴雨
                issues.append(f"天气{desc}，禁止动火作业")
            if temp_c >= 40:
                issues.append(f"气温{temp_c}℃(≥40℃)，需加强防暑")
            if wind_level >= 4:
                issues.append(f"风力{wind_level}级(4级)，需加强防火措施")

            ok = len(issues) == 0
            result = {
                "city": city, "temp_c": temp_c, "wind_level": wind_level,
                "humidity": humidity, "weather": desc, "ok": ok, "issues": issues,
            }
            if ok:
                print(f"[Tool] 天气正常: {desc} {temp_c}℃ 风{wind_level}级")
            else:
                print(f"[Tool] 天气异常: {'; '.join(issues)}")
            return result
        except Exception as e:
            print(f"[Tool] 天气查询失败: {e}, 跳过天气检查")
            return {"city": city, "ok": True, "issues": [], "error": str(e)}

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
        cfg = load_config()
        webhook = cfg.get("wechat_webhook", "")
        print(f"[Tool] 向 {receiver} 推送企业微信预警...")
        if not webhook:
            print("[Tool] 未配置企业微信 Webhook，跳过实际发送。")
            return True
        import requests
        payload = {"msgtype": "markdown", "markdown": {"content": f"### 安全隐患警报\n> {receiver}\n> {detail}"}}
        try:
            return requests.post(webhook, json=payload, timeout=10).status_code == 200
        except Exception as e:
            print(f"[Tool] 企业微信推送失败: {e}")
            return False

    @staticmethod
    def send_dingtalk_alert(detail: str, receiver: str = "安全负责人") -> bool:
        """钉钉 Webhook 预警"""
        cfg = load_config()
        webhook = cfg.get("dingtalk_webhook", "")
        print(f"[Tool] 向 {receiver} 推送钉钉预警...")
        if not webhook:
            print("[Tool] 未配置钉钉 Webhook，跳过实际发送。")
            return True
        import requests
        payload = {"msgtype": "text", "text": {"content": f"【安全隐患警报】\n接收人: {receiver}\n{detail}"}}
        try:
            return requests.post(webhook, json=payload, timeout=10).status_code == 200
        except Exception as e:
            print(f"[Tool] 钉钉推送失败: {e}")
            return False


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

class _ProgressSim:
    """阻塞操作期间的模拟渐进进度（后台线程）"""
    def __init__(self, callback, start_pct, end_pct, msg, step=1, interval=0.5):
        self._cb = callback
        self._start = start_pct
        self._end = end_pct
        self._cur = float(start_pct)
        self._step = step
        self._interval = interval
        self._stop = False
        self._msg = msg
        import threading as _th
        self._t = _th.Thread(target=self._run, daemon=True)

    def _run(self):
        import time as _t
        t0 = _t.time()
        next_hb = HEARTBEAT_INTERVAL
        while not self._stop and self._cur < self._end - 1:
            self._cur = min(self._cur + self._step, self._end - 1)
            # 不在后台线程调用 Streamlit 回调，避免 ScriptRunContext 警告；
            # 主线程 _p() 调用已提供实时进度，done() 在主线程触发最终更新。
            if HEARTBEAT_INTERVAL > 0:
                elapsed = _t.time() - t0
                if elapsed >= next_hb:
                    print(f"  ... {self._msg} ({int(elapsed)}s)")
                    next_hb += HEARTBEAT_INTERVAL
            _t.sleep(self._interval)

    def start(self):
        self._t.start()

    def done(self):
        self._stop = True
        if self._cb:
            self._cb(int(self._end), self._msg)


class _Heartbeat:
    """后台线程定期打印进度点，避免长时间推理时看起来像卡死"""
    def __init__(self, label: str, interval: float = None):
        import threading as _th
        self._label = label
        self._interval = interval if interval is not None else HEARTBEAT_INTERVAL
        self._stop = False
        self._t = _th.Thread(target=self._run, daemon=True)

    def _run(self):
        import time as _t
        t0 = _t.time()
        while not self._stop:
            _t.sleep(self._interval)
            if self._stop:
                break
            print(f"  ... {self._label} ({int(_t.time() - t0)}s)", flush=True)

    def start(self):
        self._t.start()

    def stop(self):
        self._stop = True


class SecurityAgent:
    """
    ReAct 智能体：Plan -> Perceive -> Reason -> Reflect -> Act -> Report
    """

    MAX_REFLECT_RETRIES = 2

    def __init__(self, brain: LLMBrain, ocr_mode: str = "cluster", progress_callback=None):
        self.brain = brain
        self.tools = AgentTools()
        self.ocr_mode = ocr_mode
        self._progress = progress_callback

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
        prog = self._progress
        if prog: prog(5, "图像预处理")
        print("[Agent Perceive] OpenCV + PaddleOCR 感知...")
        text = self.tools.ocr_tool(image_path, mode=self.ocr_mode, brain=self.brain, progress_callback=prog)
        n = len(text.strip().split("\n"))
        summary = f"提取 {n} 行文本"
        print(f"[Agent Perceive] {summary}")
        mem.remember("感知", "👁️", "OCR 提取文字", summary)
        return text

    def _reason(self, ocr_text: str, mem: AgentMemory) -> SecuritySheetData:
        print("[Agent Reason] LLM 语义分析...")
        sim = _ProgressSim(self._progress, 55, 80, "LLM 语义分析中", 2, 1.0)
        sim.start()
        data = self.brain.extract_sheet_json(ocr_text)
        sim.done()
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

    def _generate_approval(self, data: SecuritySheetData, weather: dict = None) -> str:
        """调用 LLM 生成专业审批建议，含天气和具体异常"""
        issues_desc = ""
        if data.has_abnormal:
            items = []
            for m in data.safety_measures:
                if not m.implemented:
                    items.append(f"第{m.measure_id}项「{m.description}」未落实")
            for i, v in enumerate(data.gas_concentration):
                if v > 0:
                    items.append(f"第{i+1}次检测浓度{v}%超标")
            for issue in data.issues:
                items.append(f"{issue.item_name}（{issue.raw_text or '异常'}）")
            issues_desc = "\n".join(f"- {item}" for item in items[:10])

        weather_desc = ""
        if weather and not weather.get("ok"):
            weather_desc = "\n天气异常：" + "；".join(weather.get("issues", []))

        std_info = TICKET_STANDARDS.get(data.ticket_type, TICKET_STANDARDS["动火作业票"])
        std_name = std_info["standard_name"]
        std_desc = std_info["standard_desc"]
        gas_limit = std_info["gas_limit_desc"]
        clear_dist = std_info["clear_dist_desc"]

        prompt = (
            f"你是HSE安全审计专家，生成{data.ticket_type}审批建议。\n\n"
            "【标准依据】\n"
            f"- {std_name} {std_desc}\n"
            f"- 气体浓度限制：{gas_limit}\n"
            f"- 作业区域要求：{clear_dist}\n"
            "- 五级风及以上禁止露天作业，雷雨天气禁止作业\n\n"
            "【输出格式】\n"
            "无异常→【同意作业】+简要确认\n"
            "有异常→【暂缓作业】+逐项列出问题（简写）+风险等级\n"
            "字数100字以内\n\n"
            f"票号：{data.ticket_id} 场站：{data.station_name}\n"
            f"浓度：{data.gas_concentration} 措施：{len(data.safety_measures)}项\n"
            f"异常：{data.has_abnormal}\n"
            f"{issues_desc}{weather_desc}"
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
            raw_opinion = response.choices[0].message.content.strip()
            opinion = clean_thinking(raw_opinion)

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

    def _generate_approval_template(self, data: SecuritySheetData) -> str:
        """LLM 失败时的 fallback 模板，列出具体异常"""
        std_info = TICKET_STANDARDS.get(data.ticket_type, TICKET_STANDARDS["动火作业票"])
        std_name = std_info["standard_name"]
        if not data.has_abnormal:
            return f"【同意作业】票号{data.ticket_id}，安全措施已落实，浓度合格。依据{std_name}批准。"
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
        return f"【暂缓作业】{detail}。依据{std_name}，请整改后重新提交。"

    def _act(self, data: SecuritySheetData, ocr_text: str, mem: AgentMemory, image_path: str = ""):
        print("[Agent Act] 执行工具组合...")

        # 检查通知渠道配置
        cfg = load_config()
        if not cfg.get("dingtalk_webhook"):
            print("[Agent Act] ⚠️ 钉钉 Webhook 未配置，跳过钉钉推送。")
        if not cfg.get("wechat_webhook"):
            print("[Agent Act] ⚠️ 企业微信 Webhook 未配置，跳过微信推送。")

        # 天气检查
        weather = self.tools.check_weather_tool("牡丹江")
        if weather.get("issues"):
            for w in weather["issues"]:
                mem.remember("执行", "⛅", "天气检查", w, status="retry")

        # 生成审批建议（含天气信息）
        data.approval_opinion = self._generate_approval(data, weather)
        print(f"[Agent Act] 审批建议: {data.approval_opinion[:80]}...")

        self.tools.save_to_db(data, raw_ocr=ocr_text, image_path=image_path)

        if data.has_abnormal:
            for issue in data.issues:
                msg = (f"【{data.station_name}】票号:{data.ticket_id} "
                       f"隐患:{issue.item_name}({issue.raw_text or '无备注'}) "
                       f"浓度:{data.gas_concentration} 签批:{data.approver_name or '未知'}")
                self.tools.send_wechat_alert(msg)
                self.tools.send_dingtalk_alert(msg)
            summary = "SQLite + 企业微信/钉钉预警 (共3个工具)"
        else:
            summary = "SQLite (无隐患，跳过预警)"

        print(f"[Agent Act] {summary}")
        mem.remember("执行", "⚡", "自主选择工具", summary)

    def _report(self, mem: AgentMemory):
        print(f"[Agent Report] ===== 决策链报告 =====")
        print(mem.get_summary())
        print(f"[Agent Report] ===== {len(mem.steps)} 阶段完成 =====")
        mem.remember("总结", "📊", "输出决策链报告", f"{len(mem.steps)}阶段完成")

    def run(self, image_path: str, ocr_mode: str = None, progress_callback=None):
        """运行完整 ReAct 循环，返回 (ocr_text, structured_data)"""
        if ocr_mode:
            self.ocr_mode = ocr_mode
        prog = progress_callback or self._progress
        mem = AgentMemory()
        t0 = time.time()

        if prog: prog(0, "开始处理")
        self._plan(image_path, mem)
        if prog: prog(3, "感知阶段")
        ocr_text = self._perceive(image_path, mem)
        if prog: prog(55, "推理阶段")
        data = self._reason(ocr_text, mem)
        if prog: prog(82, "反思阶段")
        data = self._reflect(ocr_text, data, mem)
        if prog: prog(90, "执行阶段")
        self._act(data, ocr_text, mem, image_path=image_path)
        if prog: prog(98, "生成报告")

        elapsed = time.time() - t0
        print(f"[Agent] 全流程耗时: {elapsed:.1f}s")
        self._report(mem)
        if prog: prog(100, "完成")
        return ocr_text, data


# ==========================================
# 入口
# ==========================================

def load_config() -> dict:
    """从 config.json 加载配置，若不存在或缺失字段，则返回本地 Ollama 默认值"""
    cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
            
    # Set default values if not specified
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("ONLINE_API_KEY", "ollama")
    if not cfg.get("base_url"):
        cfg["base_url"] = os.environ.get("ONLINE_BASE_URL", "http://localhost:11434/v1")
    if not cfg.get("model_name"):
        cfg["model_name"] = os.environ.get("ONLINE_MODEL", "qwen3.5:0.8b")
        
    return cfg


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
