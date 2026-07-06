# -*- coding: utf-8 -*-
"""
checklist_ocr.py — 带气作业票"检查内容确认矩阵"打勾校验模块

复用 ocr.py 的 align_to_template() / crop_image()，调用视觉大模型
对红框区域逐格判断打勾状态，输出严格 JSON，并校验合规性。
"""

import json
import os
import re
import base64
import cv2
from typing import Optional

from ocr import align_to_template, crop_image


# --- 确认矩阵在模板坐标系中的裁剪区域 (x, y, w, h) ---
# 这些坐标基于对齐后 794×1030 模板图。可通过 config.json 覆盖。
DEFAULT_CHECKLIST_CROP = {
    "x": 500,
    "y": 230,
    "w": 250,
    "h": 670,
}

# 固定的五列角色名（视觉大模型输出 JSON 的 key）
CHECKLIST_COLUMNS = [
    "作业人",
    "施工方现场负责人",
    "监理人员",
    "项目公司",
    "带气现场负责人",
]


def _load_checklist_coords(config_path: Optional[str] = None):
    """从 config.json 读取 checklist_grid 裁剪坐标，未配置时使用默认值。"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            grid = cfg.get("checklist_grid")
            if grid and all(k in grid for k in ("x", "y", "w", "h")):
                return {k: int(grid[k]) for k in ("x", "y", "w", "h")}
    except Exception:
        pass
    return dict(DEFAULT_CHECKLIST_CROP)


def run_checklist_vision_ocr(
    image_path: str,
    api_key: str,
    base_url: str,
    model_name: str,
    config_path: Optional[str] = None,
    template_path: Optional[str] = None,
    save_crop_path: Optional[str] = None,
    proxy: Optional[str] = None,
) -> dict:
    """
    对齐 → 裁剪矩阵区域 → 视觉大模型返回严格 JSON。

    Returns:
        dict: {"rows": [...], "raw_json": "...", "error": "..."}
    """
    from openai import OpenAI
    import httpx as _httpx

    if template_path is None:
        template_path = os.path.join(os.path.dirname(__file__), "template", "dq.png")

    # 1) 对齐到模板坐标系
    aligned, is_aligned = align_to_template(image_path, template_path)
    if aligned is None or not is_aligned:
        # 对齐失败，直接用原图（可能坐标不准，但给个警告）
        aligned = cv2.imread(image_path)
        if aligned is None:
            return {"rows": [], "error": f"无法读取图片: {image_path}"}

    aligned_path = image_path + ".checklist_aligned.png"
    cv2.imwrite(aligned_path, aligned)

    # 2) 按坐标裁剪确认矩阵
    coords = _load_checklist_coords(config_path)
    try:
        crop = crop_image(aligned_path, coords["x"], coords["y"], coords["w"], coords["h"], save_crop_path)
    except ValueError as e:
        return {"rows": [], "error": f"裁剪区域无效: {e}"}

    if save_crop_path is None:
        # 自动保存到临时位置用于调试
        save_crop_path = image_path + ".checklist_crop.jpg"
        cv2.imwrite(save_crop_path, crop)

    # 3) 编码裁剪图发 visual LLM
    with open(save_crop_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    columns_str = "、".join(CHECKLIST_COLUMNS)

    prompt = (
        "你是一个严格的结构化数据提取器。请仔细观察这张图片，"
        "这是燃气行业带气作业票中检查内容确认矩阵的完整区域截图，"
        "包含左侧的类别标签（人/物/环/管/应急/其他）、安全措施描述文字，"
        "以及右侧5列打勾确认格。\n\n"
        f"5列打勾格从左到右依次固定为：{columns_str}。\n\n"
        "你必须逐行从上到下识别图片中实际出现的每一行，输出对应的JSON对象。"
        "图片中一共显示了大约25行——请按实际可见行数输出，不要凭空增加。\n\n"
        "每格的状态判断规则：\n"
        "- checked = 该格有手写打勾符号（√、✓、V等笔迹）\n"
        "- na = 该格是横线—，表示不适用\n"
        "- unchecked = 该格是空白（应打勾但未打）\n"
        "- unclear = 有笔迹但符号模糊无法判断\n\n"
        "category字段：根据行首的类别标签判断，必须是下列值之一：人、物、环、管、应急、其他。\n"
        "item字段：原样抄录该行的安全措施描述文字（中文，不要翻译或改写）。\n\n"
        "注意：\n"
        "1. 不要跳过任何一行\n"
        "2. 不要把5列误判成4列\n"
        "3. 基于图片实情逐格判断，不要猜测或假设\n"
        "4. 只输出JSON对象，不要markdown代码块，不要任何解释\n\n"
        '输出格式：{{"rows":[{{"category":"人","item":"作业人员具备相应的作业资格","作业人":"checked",'
        '"施工方现场负责人":"checked","监理人员":"checked","项目公司":"checked",'
        '"带气现场负责人":"checked"}}]}}'
    )

    # proxy
    proxy_s = proxy
    if proxy_s is None:
        # 先读 config 的 proxy
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "config.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                proxy_s = cfg.get("proxy", "")
        except Exception:
            pass
    if not proxy_s:
        proxy_s = os.environ.get("HTTP_PROXY", os.environ.get("http_proxy", ""))

    client_kwargs = dict(api_key=api_key, base_url=base_url)
    if proxy_s:
        client_kwargs["http_client"] = _httpx.Client(proxy=proxy_s, timeout=180.0)
    client = OpenAI(**client_kwargs)

    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0.0,
            max_tokens=16384,
            timeout=180,
        )
        raw = resp.choices[0].message.content.strip()
        # 检测截断
        finish = resp.choices[0].finish_reason
        if finish == "length":
            raw += "\n[WARN] 输出被截断，max_tokens 不足"
    except Exception as e:
        return {"rows": [], "error": f"Vision LLM 调用失败: {e}"}

    # 4) 解析 JSON
    parsed = _parse_checklist_json(raw)
    parsed["raw_json"] = raw
    return parsed


def _parse_checklist_json(raw: str) -> dict:
    """从 LLM 返回文本中提取 JSON，兼容截断、Markdown 代码块包裹等格式。"""
    errors = []

    # 先尝试直接解析
    try:
        obj = json.loads(raw)
        return {"rows": obj.get("rows", [])}
    except json.JSONDecodeError as e:
        errors.append(f"直接解析: {e}")

    # 尝试去掉 ```json ... ``` 包裹
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw)
    if m:
        try:
            obj = json.loads(m.group(1))
            return {"rows": obj.get("rows", [])}
        except json.JSONDecodeError as e:
            errors.append(f"代码块解析: {e}")

    # 尝试 regex 提取 {...} 最外层
    m = re.search(r'\{[\s\S]*"rows"[\s\S]*\}', raw)
    if m:
        try:
            obj = json.loads(m.group(0))
            return {"rows": obj.get("rows", [])}
        except json.JSONDecodeError as e:
            errors.append(f"regex提取: {e}")

    # 截断修复：如果最后一行 JSON 不完整，尝试补全
    truncated = _repair_truncated_rows(raw)
    if truncated:
        return {"rows": truncated}

    return {"rows": [], "error": f"无法解析 LLM 返回的 JSON: {raw[:200]}", "parse_errors": errors}


def _repair_truncated_rows(raw: str) -> list:
    """尝试从截断的 JSON 中恢复已完整的行。"""
    valid_rows = []
    # 找到 "rows": [ 后面的内容
    m = re.search(r'"rows"\s*:\s*\[', raw)
    if not m:
        return []
    tail = raw[m.end():]

    # 逐个提取完整的 {...} 对象
    i = 0
    while i < len(tail):
        if tail[i] == '{':
            depth = 0
            in_string = False
            j = i
            while j < len(tail):
                ch = tail[j]
                if ch == '"' and (j == 0 or tail[j-1] != '\\'):
                    in_string = not in_string
                if not in_string:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                obj = json.loads(tail[i:j+1])
                                valid_rows.append(obj)
                            except json.JSONDecodeError:
                                pass
                            i = j + 1
                            break
                j += 1
            else:
                # 没找到闭合的 }，说明截断了，停止
                break
        else:
            i += 1
    return valid_rows


def validate_checklist(result_json: dict, required_rows: int = 25) -> list:
    """
    校验 checklist 识别结果。

    Args:
        result_json: run_checklist_vision_ocr() 的返回 dict，含 "rows" 键。
        required_rows: 模板要求的行数（带气作业票默认 25 行）。

    Returns:
        list of dict: 不合规项，每项 {"row_index": int, "item": str, "missing_columns": [...], "reason": str}
    """
    rows = result_json.get("rows", [])
    violations = []

    # 行数不足
    if len(rows) < required_rows:
        violations.append({
            "row_index": -1,
            "item": f"行数不足：期望 {required_rows} 行，实际识别 {len(rows)} 行",
            "missing_columns": [],
            "reason": "行数不匹配，可能有行被跳过或合并",
        })

    for i, row in enumerate(rows):
        item = row.get("item", f"第{i+1}行")
        category = row.get("category", "")

        missing = []
        unclear = []
        for col in CHECKLIST_COLUMNS:
            status = row.get(col, "unchecked")
            if status == "unchecked":
                # "其他" 类目下允许 na，但 unchecked 仍然不行（除非是 na）
                missing.append(col)
            elif status == "unclear":
                unclear.append(col)
            elif status == "na":
                # "其他"类目下 na 是合法的，不报
                if category != "其他":
                    # 非"其他"类目出现 na，可能也需要关注
                    # ponytail: 先宽松处理，仅记录但不算 missing
                    pass

        if missing:
            violations.append({
                "row_index": i,
                "item": item,
                "missing_columns": missing,
                "reason": f"第{i+1}行「{item}」的以下角色未打勾: {'、'.join(missing)}",
            })
        if unclear:
            violations.append({
                "row_index": i,
                "item": item,
                "missing_columns": unclear,
                "reason": f"第{i+1}行「{item}」的以下角色符号模糊需人工复核: {'、'.join(unclear)}",
            })

    return violations


# ---- 自测入口 ----
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python checklist_ocr.py <image_path>")
        print("  从 config.json 读取 vision_api_key / vision_base_url / vision_model_name")
        sys.exit(1)

    image_path = sys.argv[1]

    # 从 config.json 读取视觉模型配置
    cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    api_key = cfg.get("vision_api_key", os.environ.get("VISION_API_KEY", ""))
    base_url = cfg.get("vision_base_url", os.environ.get("VISION_BASE_URL", ""))
    model_name = cfg.get("vision_model_name", os.environ.get("VISION_MODEL_NAME", "gemini-2.5-flash"))

    if not api_key:
        print("ERROR: 未配置 vision_api_key")
        sys.exit(1)

    print(f"处理图片: {image_path}")
    print(f"模型: {model_name}")
    print()

    result = run_checklist_vision_ocr(
        image_path=image_path,
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )

    if result.get("error"):
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    rows = result.get("rows", [])
    print(f"识别到 {len(rows)} 行")
    print()

    # 输出 JSON
    print("=== OCR 识别 JSON ===")
    print(json.dumps({"rows": rows}, ensure_ascii=False, indent=2))
    print()

    # 校验
    violations = validate_checklist(result, required_rows=25)
    print(f"=== 合规校验结果 ({len(violations)} 条不合规) ===")
    if violations:
        for v in violations:
            print(f"  [{v['row_index']}] {v['reason']}")
    else:
        print("  ✅ 全部通过")
