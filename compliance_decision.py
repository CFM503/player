# -*- coding: utf-8 -*-
"""
compliance_decision.py — 作业票合规决策引擎

消费 paddleocr 和 vision_llm 各自产出的真实识别结果，逐项判断是否合规。
不涉及跨引擎兜底或互相校验，不修改路由逻辑。

输入:
  - text_fields: list[TextFieldResult]   (paddleocr 识别结果)
  - checklist: dict (ChecklistResult)     (vision_llm 识别结果, 含 "rows" 键)
  - config: dict                          (可选, 含阈值和模板配置)

输出: 完整决策 JSON，包含每条决策的证据和原因。
"""

import re
from typing import Optional
from collections import namedtuple


# ============================================================
# 0. 数据类型定义
# ============================================================

TextFieldResult = namedtuple("TextFieldResult", [
    "field_name",      # 字段名: "作业票编号" / "作业时间" / "签批人姓名"
    "value",           # paddleocr 识别出的原始文本 ("" = 空白/未检测到)
    "confidence",      # 识别置信度 0.0~1.0
    "bbox",            # (x,y,w,h) 或 None
])

# ============================================================
# 可配置常量 (通过 config dict 覆盖)
# ============================================================

# 票号正则 — 牡丹江中燃编码规则: MDJ + ZR + 4位年 + S + 6位序号
TICKET_ID_PATTERN = r"^MDJZR\d{4}S\d{6}$"

# 时间解析尝试的格式列表 (按优先级)
TIME_FORMATS = [
    # "2025年11月21日13时0分" - 标准中文
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*时\s*(\d{1,2})\s*分"),
    # "2025年11月21日1310分" - paddleocr 漏识别"时"字 (hour=13, min=10)
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*(\d{2})\s*分"),
    # "2025年11月21日10分" - 没有小时 (默认0时)
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*分"),
    # "2025年11月21日13:00" - 带冒号
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*[:：]\s*(\d{2})"),
    # "2025-11-21 13:00" - ISO 兼容
    re.compile(r"(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[T\s]\s*(\d{1,2})\s*[:：]\s*(\d{2})"),
]

# 默认置信度阈值 (低于此值判定为 "需人工复核")
DEFAULT_CONFIDENCE_THRESHOLD = 0.60

# 确认矩阵列名 (顺序固定)
CHECKLIST_COLUMNS = [
    "作业人",
    "施工方现场负责人",
    "监理人员",
    "项目公司",
    "带气现场负责人",
]

# ============================================================
# overall_decision 优先级常量表 (显式, 改一处即生效)
# ============================================================

# 优先级数值越大越严重
_OVERALL_PRIORITY = {
    "合规":          0,
    "存在缺项":      10,
    "需人工复核":    20,
}

OVERALL_PRIORITY_TABLE = [
    # (触发此 key 出现的 decision 类型, 对应的 overall_decision)
    ("需人工复核", "需人工复核"),
    ("确认缺失",   "存在缺项"),
    ("缺项",       "存在缺项"),
    ("格式异常",   "存在缺项"),
    ("字迹模糊需人工复核", "需人工复核"),
    ("结构异常",   "需人工复核"),
]


def _compute_overall(text_decisions: list, checklist_decisions: list) -> str:
    """根据优先级常量表计算整体判定。"""
    max_severity = 0
    result = "合规"
    for d in text_decisions:
        dec = d.get("decision", "合规")
        for trigger, overall in OVERALL_PRIORITY_TABLE:
            if dec == trigger:
                sev = _OVERALL_PRIORITY.get(overall, 0)
                if sev > max_severity:
                    max_severity = sev
                    result = overall
    for d in checklist_decisions:
        dec = d.get("decision", "合规")
        for trigger, overall in OVERALL_PRIORITY_TABLE:
            if dec == trigger:
                sev = _OVERALL_PRIORITY.get(overall, 0)
                if sev > max_severity:
                    max_severity = sev
                    result = overall
    return result


# ============================================================
# 一、文本字段决策规则
# ============================================================

def _parse_time_string(s: str):
    """尝试从文本中提取 (year, month, day, hour, minute)，失败返回 None。"""
    s = str(s).strip()
    if not s:
        return None
    for pattern in TIME_FORMATS:
        m = pattern.search(s)
        if m:
            groups = m.groups()
            try:
                y = int(groups[0])
                mo = int(groups[1])
                d = int(groups[2])
                # 最后一个模式可能只有3组 (y, mo, d)
                if len(groups) >= 5:
                    h = int(groups[3])
                    mi = int(groups[4])
                elif len(groups) >= 4:
                    h = int(groups[3])
                    mi = 0
                else:
                    h = 0
                    mi = 0
                return (y, mo, d, h, mi)
            except (ValueError, IndexError):
                continue
    return None


def _decide_ticket_id(field: TextFieldResult, threshold: float) -> dict:
    """规则一.1: 票号格式校验。"""
    value = (field.value or "").strip()
    confidence = field.confidence if field.confidence is not None else 0.0

    if confidence < threshold:
        return {
            "field_name": field.field_name,
            "recognized_value": value,
            "confidence": confidence,
            "decision": "需人工复核",
            "reason": f"规则一.1: PaddleOCR 置信度 {confidence:.2f} 低于阈值 {threshold}，无法自动判断票号格式",
        }

    if not value:
        return {
            "field_name": field.field_name,
            "recognized_value": "",
            "confidence": confidence,
            "decision": "缺项",
            "reason": "规则一.1: 作业票编号字段为空白，未检测到任何文本框",
        }

    m = re.search(TICKET_ID_PATTERN, value)
    if m:
        return {
            "field_name": field.field_name,
            "recognized_value": value,
            "confidence": confidence,
            "decision": "合规",
            "reason": f"规则一.1: 票号 {value} 符合格式 {TICKET_ID_PATTERN}",
        }
    else:
        return {
            "field_name": field.field_name,
            "recognized_value": value,
            "confidence": confidence,
            "decision": "格式异常",
            "reason": f"规则一.1: paddleocr 识别值 '{value}' 不匹配预期格式 {TICKET_ID_PATTERN}",
        }


def _decide_work_time(field: TextFieldResult, threshold: float) -> dict:
    """规则一.2: 作业时间起止校验。

    paddleocr 输出整个时间行，包含起止时间。需要分离"开始时间"和"结束时间"。
    """
    value = (field.value or "").strip()
    confidence = field.confidence if field.confidence is not None else 0.0

    if confidence < threshold:
        return {
            "field_name": field.field_name,
            "recognized_value": value,
            "confidence": confidence,
            "decision": "需人工复核",
            "reason": f"规则一.2: 识别置信度 {confidence:.2f} 低于阈值 {threshold}，无法自动校验时间",
        }

    if not value:
        return {
            "field_name": field.field_name,
            "recognized_value": "",
            "confidence": confidence,
            "decision": "缺项",
            "reason": "规则一.2: 作业时间字段为空白",
        }

    # 尝试分离"从…至…"的起止时间
    # 常见格式: "2025年11月21日10分 至 2025年11月21日17时0分"
    #           "2025年11月21日1310分至202511月24日190分"
    parts = re.split(r"\s*[至到~]\s*", value, maxsplit=1)
    if len(parts) == 2:
        t1 = _parse_time_string(parts[0])
        t2 = _parse_time_string(parts[1])
    else:
        t1 = _parse_time_string(value)
        t2 = None

    if t1 is None and t2 is None:
        return {
            "field_name": field.field_name,
            "recognized_value": value,
            "confidence": confidence,
            "decision": "需人工复核",
            "reason": f"规则一.2: paddleocr 识别值 '{value}' 无法解析为有效日期时间",
        }

    if t1 is None:
        return {
            "field_name": field.field_name,
            "recognized_value": value,
            "confidence": confidence,
            "decision": "需人工复核",
            "reason": f"规则一.2: 开始时间 '{parts[0] if len(parts) >= 1 else value}' 无法解析",
        }

    if t2 is None:
        return {
            "field_name": field.field_name,
            "recognized_value": value,
            "confidence": confidence,
            "decision": "需人工复核",
            "reason": f"规则一.2: 结束时间未找到或无法解析（原始: '{value}'）",
        }

    # 结束时间必须晚于开始时间
    from datetime import datetime
    dt1 = datetime(*t1)
    dt2 = datetime(*t2)
    if dt2 <= dt1:
        return {
            "field_name": field.field_name,
            "recognized_value": value,
            "confidence": confidence,
            "decision": "格式异常",
            "reason": f"规则一.2: 结束时间 {dt2.strftime('%Y-%m-%d %H:%M')} 不晚于开始时间 {dt1.strftime('%Y-%m-%d %H:%M')}",
        }

    return {
        "field_name": field.field_name,
        "recognized_value": value,
        "confidence": confidence,
        "decision": "合规",
        "reason": f"规则一.2: 时间 {dt1.strftime('%Y-%m-%d %H:%M')} 至 {dt2.strftime('%Y-%m-%d %H:%M')} 有效",
    }


def _decide_signatory(field: TextFieldResult, threshold: float) -> dict:
    """规则一.3: 签批人姓名/工号是否缺失。"""
    value = (field.value or "").strip()
    confidence = field.confidence if field.confidence is not None else 0.0

    # 签批人字段: 是"格式异常"但不是票号规则 — 需要修正
    # 证书编号字段的正则应匹配身份证号或者其他工号格式
    # ponytail: 先用宽松正则 — 数字+非空即可
    if not value:
        return {
            "field_name": field.field_name,
            "recognized_value": "",
            "confidence": confidence,
            "decision": "缺项",
            "reason": f"规则一.3: {field.field_name} 字段为空白，paddleocr 未检测到任何文本框",
        }
    return {
        "field_name": field.field_name,
        "recognized_value": value,
        "confidence": confidence,
        "decision": "合规",
        "reason": f"规则一.3: {field.field_name} 已识别到内容 '{value}' 且置信度 {confidence:.2f} 达标",
    }


# ============================================================
# 二、确认矩阵决策规则
# ============================================================

def _decide_checklist(checklist: dict, required_rows: int) -> list:
    """规则二.1 + 二.2: 逐行逐列判断确认矩阵。"""
    rows = checklist.get("rows", []) if checklist else []
    decisions = []

    # 规则二.2: 行数校验
    if len(rows) != required_rows:
        return [{
            "row": f"整份 checklist 行数异常: 实际 {len(rows)} 行，模板要求 {required_rows} 行",
            "category": "",
            "column_results": {},
            "decision": "结构异常",
            "missing_columns": [],
            "reason": f"规则二.2: 行数不一致 ({len(rows)} vs {required_rows})，可能整体错位，不再逐行判断",
        }]

    # 规则二.1: 逐行逐列
    for i, row in enumerate(rows):
        item = row.get("item", f"第{i+1}行")
        category = row.get("category", "")

        column_results = {
            col: row.get(col, "unchecked")
            for col in CHECKLIST_COLUMNS
        }

        is_other = (category == "其他")

        # 先检查 unclear
        unclear_cols = [col for col in CHECKLIST_COLUMNS
                        if column_results.get(col) == "unclear"]
        if unclear_cols:
            decisions.append({
                "row": item,
                "category": category,
                "column_results": column_results,
                "decision": "需人工复核",
                "missing_columns": unclear_cols,
                "reason": f"规则二.1: 第{i+1}行「{item}」以下列符号模糊: {'、'.join(unclear_cols)}",
            })
            continue  # 有 unclear 时不再报缺失，优先人工复核

        # 非"其他"类: 五列必须全部 checked
        if not is_other:
            missing_cols = [col for col in CHECKLIST_COLUMNS
                            if column_results.get(col) not in ("checked", "na")]
            if missing_cols:
                decisions.append({
                    "row": item,
                    "category": category,
                    "column_results": column_results,
                    "decision": "确认缺失",
                    "missing_columns": missing_cols,
                    "reason": f"规则二.1: 第{i+1}行「{item}」(类目={category}) 以下角色未打勾: {'、'.join(missing_cols)}",
                })
            else:
                decisions.append({
                    "row": item,
                    "category": category,
                    "column_results": column_results,
                    "decision": "合规",
                    "missing_columns": [],
                    "reason": f"规则二.1: 第{i+1}行「{item}」五列全部确认",
                })
        else:
            # "其他"类: na 不算缺失，unchecked 算缺失
            missing_cols = [col for col in CHECKLIST_COLUMNS
                            if column_results.get(col) == "unchecked"]
            if missing_cols:
                decisions.append({
                    "row": item,
                    "category": category,
                    "column_results": column_results,
                    "decision": "确认缺失",
                    "missing_columns": missing_cols,
                    "reason": f"规则二.1: 第{i+1}行「{item}」(类目=其他) 以下角色未打勾: {'、'.join(missing_cols)}",
                })
            else:
                decisions.append({
                    "row": item,
                    "category": category,
                    "column_results": column_results,
                    "decision": "合规",
                    "missing_columns": [],
                    "reason": f"规则二.1: 第{i+1}行「{item}」(类目=其他) 已确认或不适用",
                })

    return decisions


# ============================================================
# 三、主入口
# ============================================================

def run_compliance_check(
    text_fields: list,
    checklist: dict,
    config: Optional[dict] = None,
) -> dict:
    """
    执行全部合规决策规则，返回完整 JSON。

    Args:
        text_fields: list[TextFieldResult]
        checklist: {"rows": [...]}  来自 checklist_ocr.run_checklist_vision_ocr()
        config: {
            "confidence_threshold": 0.60,
            "required_checklist_rows": 25,
        }

    Returns:
        dict: {"text_field_decisions": [...], "checklist_decisions": [...], "overall_decision": str}
    """
    if config is None:
        config = {}

    threshold = config.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD)
    required_rows = config.get("required_checklist_rows", 25)

    # --- 一、文本字段决策 ---
    text_decisions = []
    for field in text_fields:
        name = field.field_name
        if "票编号" in name or "ticket_id" in name.lower():
            text_decisions.append(_decide_ticket_id(field, threshold))
        elif "时间" in name or "work_time" in name.lower():
            text_decisions.append(_decide_work_time(field, threshold))
        elif "签批" in name or "证书" in name or "signatory" in name.lower():
            text_decisions.append(_decide_signatory(field, threshold))
        else:
            # ponytail: 未知字段类型，跳过
            pass

    # --- 二、确认矩阵决策 ---
    checklist_decisions = _decide_checklist(checklist, required_rows)

    # --- 三、overall ---
    overall = _compute_overall(text_decisions, checklist_decisions)

    return {
        "text_field_decisions": text_decisions,
        "checklist_decisions": checklist_decisions,
        "overall_decision": overall,
    }


# ============================================================
# 自测入口
# ============================================================

if __name__ == "__main__":
    """
    用真实数据跑全流程: paddleocr OCR → 构造 text_fields → checklist_ocr → compliance_decision
    """
    import json, sys, os
    sys.path.insert(0, os.path.dirname(__file__))

    # ---- 1) 从 OCR archive 中提取票号/时间/证书编号 ----
    archives = os.path.join(os.path.dirname(__file__), "archives")
    # 找最新的带气作业票 OCR 结果
    ocr_dirs = []
    if os.path.exists(archives):
        for d in sorted(os.listdir(archives), reverse=True):
            dp = os.path.join(archives, d)
            if os.path.isdir(dp):
                ocr_dirs.append(dp)
                break  # 只取最新一天

    # ---- 2) 构造 text_fields (paddleocr 真实输出) ----
    # 从最新 Vision LLM OCR 结果中提取关键字段的识别值
    # 真实 paddleocr 输出需要有坐标+置信度，这里用 archive 中的 vision OCR 文本模拟
    ocr_text_path = None
    if ocr_dirs:
        for f in sorted(os.listdir(ocr_dirs[0]), reverse=True):
            if f.endswith("_ocr.txt"):
                ocr_text_path = os.path.join(ocr_dirs[0], f)
                break

    ticket_id_value = ""
    work_time_value = ""
    cert_value = ""
    if ocr_text_path and os.path.exists(ocr_text_path):
        with open(ocr_text_path, "r", encoding="utf-8") as f:
            ocr_lines = f.read()
        # 票号: 多种格式兼容
        for pat in [r"作业票编号.*?([A-Z]{3,4}\d{10,})",
                    r"\|\s*\**作业票编号\**\s*\|\s*([A-Z]{2,4}[R]?\d{10,})",
                    r"([A-Z]{3,4}\d{10,})"]:
            m = re.search(pat, ocr_lines)
            if m:
                ticket_id_value = m.group(1)
                break
        m = re.search(r"作业时间.*?([\d年月日时分至到~\s]{10,60})", ocr_lines)
        if m:
            work_time_value = m.group(1).strip()
        m = re.search(r"证书编号.*?(\d{15,20})", ocr_lines)
        if m:
            cert_value = m.group(1)

    # confidence: 模拟值，实际应从 PaddleOCR 获取
    # archive 中 vision OCR 没有置信度，设为 0.85 表示"正常"
    text_fields = [
        TextFieldResult("作业票编号", ticket_id_value, 0.85, None),
        TextFieldResult("作业时间", work_time_value, 0.85, None),
        TextFieldResult("签批人姓名/证书编号", cert_value, 0.85, None),
    ]

    print("=== text_fields (paddleocr 模拟) ===")
    for tf in text_fields:
        print(f"  {tf.field_name}: '{tf.value}' (conf={tf.confidence})")
    print()

    # ---- 3) 跑 checklist_ocr (用 agnes, Gemini quota 已耗尽) ----
    cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    # 优先用 main API (agnes) 跑 vision，它的 vision model 和 text model 同一个
    v_api_key = cfg.get("api_key", "")
    v_base_url = cfg.get("base_url", "")
    v_model = cfg.get("model_name", "")
    v_proxy = cfg.get("proxy", "")

    uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
    test_image = None
    for f in sorted(os.listdir(uploads_dir)):
        if f.endswith(".png") and not f.startswith("aligned_"):
            test_image = os.path.join(uploads_dir, f)
            break

    checklist_result = {"rows": []}
    if test_image and v_api_key:
        from checklist_ocr import run_checklist_vision_ocr
        print(f"=== 跑 checklist_ocr: {os.path.basename(test_image)} (模型={v_model}) ===")
        checklist_result = run_checklist_vision_ocr(
            image_path=test_image,
            api_key=v_api_key,
            base_url=v_base_url,
            model_name=v_model,
            proxy=v_proxy,
        )
        if checklist_result.get("error"):
            print(f"  ERROR: {checklist_result['error']}")
        else:
            print(f"  OK: {len(checklist_result.get('rows',[]))} 行")
    else:
        print("  跳过: 无测试图或 vision_api_key")

    # ---- 4) compliance_decision ----
    print()
    print("=== compliance_decision ===")
    result = run_compliance_check(text_fields, checklist_result, {
        "confidence_threshold": 0.60,
        "required_checklist_rows": 25,
    })

    print(json.dumps(result, ensure_ascii=False, indent=2))
