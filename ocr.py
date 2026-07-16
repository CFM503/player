# -*- coding: utf-8 -*-
# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
"""
中燃"安全数字监督员" OCR 处理器模块 (ocr.py)
面向场景：支持全图扫描/指定坐标区域裁剪扫描，保存裁剪子图及 Markdown 文本结果，
支持指定使用 CPU 或 GPU，以及选择不同的 OCR 引擎（本地 PaddleOCR 或 视觉大模型）。
可用作 Python 模块导入，亦可独立在命令行运行。

CLI 可配置 PP-OCRv6 流水线中的四个核心模型参数：
  - PP-OCRv6_medium_det          文本检测
  - PP-OCRv6_medium_rec          文本识别
  - PP-LCNet_x1_0_textline_ori   文本行方向分类
  - PP-LCNet_x1_0_doc_ori        文档整页方向分类
以及文档展平 UVDoc（文档预处理相关，可选）。

查看全部参数说明：
  python ocr.py -h
  python ocr.py --help
"""

import os
import json
import hashlib
import cv2
import argparse
from typing import List, Dict, Any, Optional, Tuple
import numpy as np


# ---------------------------------------------------------------------------
# ocr9 纠错记忆（入库后自动给 admin / user 用，无需额外导出）
# ---------------------------------------------------------------------------

def _ocr9_memory_paths() -> List[str]:
    root = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(root, "ocr_train_workspace", "memory", "corrections.json"),
        os.path.join(root, "ocr9_corrections.json"),  # 兼容若存在根目录副本
    ]


def imread_unicode(path: str):
    """支持中文路径的 imread（cv2.imread 在 Windows 中文路径下常失败）。"""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _clip_crop_bgr(img_bgr, x: int, y: int, w: int, h: int):
    """裁剪 BGR 子图；无效则 None。"""
    if img_bgr is None or w <= 0 or h <= 0:
        return None
    H, W = img_bgr.shape[:2]
    x1, y1 = max(0, int(x)), max(0, int(y))
    x2, y2 = min(W, int(x + w)), min(H, int(y + h))
    if x2 <= x1 or y2 <= y1:
        return None
    crop = img_bgr[y1:y2, x1:x2]
    return crop if crop is not None and crop.size > 0 else None


def _crop_region_phash(img_bgr, x: int, y: int, w: int, h: int) -> str:
    """与 ocr9.crop_phash 一致：精确 MD5 键（层0）。"""
    crop = _clip_crop_bgr(img_bgr, x, y, w, h)
    if crop is None:
        return ""
    small = cv2.resize(crop, (32, 16), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if len(small.shape) == 3 else small
    return hashlib.md5(gray.tobytes()).hexdigest()


def _crop_region_ahash_bits(img_bgr, x: int, y: int, w: int, h: int) -> Optional[int]:
    """
    64-bit 平均哈希（感知哈希简化版）：用于手写「差一点」增补匹配。
    返回 None 表示裁剪无效。
    """
    crop = _clip_crop_bgr(img_bgr, x, y, w, h)
    if crop is None:
        return None
    small = cv2.resize(crop, (8, 8), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if len(small.shape) == 3 else small
    avg = float(np.mean(gray))
    bits = 0
    for i, p in enumerate(gray.reshape(-1)):
        if float(p) >= avg:
            bits |= 1 << i
    return int(bits)


def ahash_bits_to_hex(bits: Optional[int]) -> str:
    if bits is None:
        return ""
    return f"{int(bits) & ((1 << 64) - 1):016x}"


def ahash_hex_to_bits(h: str) -> int:
    try:
        return int(str(h).strip(), 16) & ((1 << 64) - 1)
    except Exception:
        return 0


def hamming64(a: int, b: int) -> int:
    return int(bin((int(a) ^ int(b)) & ((1 << 64) - 1)).count("1"))


def box_iou(ax: float, ay: float, aw: float, ah: float,
            bx: float, by: float, bw: float, bh: float) -> float:
    """轴对齐框 IoU。"""
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def _crop_l1_distance(crop_a, crop_b) -> float:
    """两裁剪图归一化 L1 ∈ [0,1]；无效返回 1.0。"""
    if crop_a is None or crop_b is None:
        return 1.0
    try:
        ga = cv2.cvtColor(crop_a, cv2.COLOR_BGR2GRAY) if len(crop_a.shape) == 3 else crop_a
        gb = cv2.cvtColor(crop_b, cv2.COLOR_BGR2GRAY) if len(crop_b.shape) == 3 else crop_b
        ga = cv2.resize(ga, (32, 16), interpolation=cv2.INTER_AREA)
        gb = cv2.resize(gb, (32, 16), interpolation=cv2.INTER_AREA)
        d = np.mean(np.abs(ga.astype(np.float32) - gb.astype(np.float32))) / 255.0
        return float(min(1.0, max(0.0, d)))
    except Exception:
        return 1.0


# 模糊增补默认阈值（严：宁可不增补，禁止兜底乱改）
# IoU 门控 + 外观综合分 app = 0.45*(ham/64) + 0.55*L1  （手写平移时 aHash 易跳、L1 更稳）
# 环境变量：OCR9_FUZZY_IOU / OCR9_FUZZY_APP / OCR9_FUZZY_HAMMING_MAX（硬上限）
_OCR9_FUZZY_IOU_DEFAULT = 0.72
_OCR9_FUZZY_APP_DEFAULT = 0.16  # 综合外观上限；越小越严
_OCR9_FUZZY_HAMMING_MAX_DEFAULT = 20  # aHash 硬上限，防止仅 L1 误配


def _ocr9_fuzzy_enabled() -> bool:
    """模糊增补开关；默认开。OCR9_MEMORY_FUZZY=0/off 关闭。"""
    v = os.environ.get("OCR9_MEMORY_FUZZY", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _ocr9_fuzzy_thresholds() -> Tuple[float, float, int]:
    try:
        iou = float(os.environ.get("OCR9_FUZZY_IOU", _OCR9_FUZZY_IOU_DEFAULT))
    except Exception:
        iou = _OCR9_FUZZY_IOU_DEFAULT
    try:
        app = float(os.environ.get("OCR9_FUZZY_APP", _OCR9_FUZZY_APP_DEFAULT))
    except Exception:
        app = _OCR9_FUZZY_APP_DEFAULT
    try:
        ham_max = int(os.environ.get("OCR9_FUZZY_HAMMING_MAX", _OCR9_FUZZY_HAMMING_MAX_DEFAULT))
    except Exception:
        ham_max = _OCR9_FUZZY_HAMMING_MAX_DEFAULT
    return (
        max(0.5, min(0.99, iou)),
        max(0.05, min(0.4, app)),
        max(4, min(32, ham_max)),
    )


def ocr9_memory_status() -> Tuple[int, str]:
    """返回 (哈希条数, 路径)；无文件则 (0, 首选路径)。"""
    info = ocr9_memory_status_detail()
    return int(info.get("n_hash") or 0), str(info.get("path") or _ocr9_memory_paths()[0])


def ocr9_memory_status_detail() -> Dict[str, Any]:
    """
    纠错记忆状态（每次读盘，不缓存）。
    n_hash: 图像哈希键数量（同一区域重复入库会覆盖，条数不增）
    n_sample: 记忆里出现过的 distinct sample_id（仅供展示）
    """
    empty_path = _ocr9_memory_paths()[0]
    for path in _ocr9_memory_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("items"), dict):
                raw = raw["items"]
            if not isinstance(raw, dict):
                continue
            n_hash = 0
            sample_ids: set = set()
            latest = ""
            for k, v in raw.items():
                if not k or str(k).startswith("_") or str(k).startswith("t:"):
                    continue
                if isinstance(v, dict):
                    t = (v.get("text") or "").strip()
                    if not t:
                        continue
                    n_hash += 1
                    sid = (v.get("sample_id") or "").strip()
                    if sid:
                        sample_ids.add(sid)
                    ua = (v.get("updated_at") or "").strip()
                    if ua > latest:
                        latest = ua
                elif str(v or "").strip():
                    n_hash += 1
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0.0
            return {
                "n_hash": n_hash,
                "n_sample": len(sample_ids),
                "path": path,
                "mtime": mtime,
                "latest_updated_at": latest,
            }
        except Exception:
            continue
    return {
        "n_hash": 0,
        "n_sample": 0,
        "path": empty_path,
        "mtime": 0.0,
        "latest_updated_at": "",
    }


def _ocr9_memory_disabled() -> bool:
    if os.environ.get("OCR9_MEMORY_DISABLE", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("OCR9_MEMORY_OFF", "").strip() in ("1", "true", "yes"):
        return True
    return False


def load_ocr9_corrections() -> Dict[str, str]:
    """
    精确层：图像 MD5 哈希 -> 真值。
    禁止 t: 文本硬改 / 字符串替换 / 默认值兜底。
    """
    recs = load_ocr9_correction_records()
    return {r["key"]: r["text"] for r in recs if r.get("key") and r.get("text")}


def load_ocr9_correction_records() -> List[Dict[str, Any]]:
    """
    完整记忆条目（精确键 + 模糊增补元数据）。
    每条可含：key, text, box, ahash, sample_id, kind, crop_relpath, source
    """
    if _ocr9_memory_disabled():
        return []
    for path in _ocr9_memory_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            continue
        if isinstance(raw, dict) and isinstance(raw.get("items"), dict):
            raw = raw["items"]
        if not isinstance(raw, dict):
            continue
        # labels.jsonl 补全旧记忆缺失的 box / crop_relpath（增补元数据，不改真值）
        label_by_sid: Dict[str, Dict[str, Any]] = {}
        labels_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "ocr_train_workspace", "labels.jsonl",
        )
        if os.path.isfile(labels_path):
            try:
                with open(labels_path, "r", encoding="utf-8") as lf:
                    for ln in lf:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            lo = json.loads(ln)
                        except Exception:
                            continue
                        sid = (lo.get("sample_id") or "").strip()
                        if sid:
                            label_by_sid[sid] = lo
            except Exception:
                pass

        out: List[Dict[str, Any]] = []
        for k, v in raw.items():
            if not k or str(k).startswith("_") or str(k).startswith("t:"):
                continue
            if isinstance(v, dict):
                t = (v.get("text") or "").strip()
                if not t:
                    continue
                box = v.get("box")
                box_t: Optional[Tuple[float, float, float, float]] = None
                if isinstance(box, (list, tuple)) and len(box) >= 4:
                    try:
                        box_t = (
                            float(box[0]), float(box[1]),
                            float(box[2]), float(box[3]),
                        )
                    except Exception:
                        box_t = None
                sid = (v.get("sample_id") or "").strip()
                rel = (v.get("crop_relpath") or "").strip()
                ahash = (v.get("ahash") or "").strip()
                lab = label_by_sid.get(sid) if sid else None
                if lab:
                    if box_t is None:
                        b = lab.get("box")
                        if isinstance(b, (list, tuple)) and len(b) >= 4:
                            try:
                                box_t = (
                                    float(b[0]), float(b[1]),
                                    float(b[2]), float(b[3]),
                                )
                            except Exception:
                                pass
                    if not rel:
                        rel = (lab.get("crop_relpath") or "").strip()
                a_bits = ahash_hex_to_bits(ahash) if ahash else 0
                # 旧条目无 ahash 时从入库裁剪图补算（一次，供模糊增补）
                if not a_bits and rel:
                    crop_path = rel if os.path.isabs(rel) else os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        "ocr_train_workspace",
                        rel.replace("/", os.sep),
                    )
                    if os.path.isfile(crop_path):
                        mc = imread_unicode(crop_path)
                        if mc is not None:
                            b = _crop_region_ahash_bits(mc, 0, 0, mc.shape[1], mc.shape[0])
                            if b is not None:
                                a_bits = int(b)
                                if not ahash:
                                    ahash = ahash_bits_to_hex(a_bits)
                out.append({
                    "key": str(k),
                    "text": t,
                    "box": box_t,
                    "ahash": ahash,
                    "ahash_bits": a_bits,
                    "sample_id": sid,
                    "kind": (v.get("kind") or "").strip(),
                    "crop_relpath": rel,
                    "source": (v.get("source") or "").strip(),
                })
            else:
                t = str(v or "").strip()
                if t:
                    out.append({
                        "key": str(k), "text": t, "box": None, "ahash": "",
                        "ahash_bits": 0, "sample_id": "", "kind": "",
                        "crop_relpath": "", "source": "",
                    })
        if out:
            return out
    return []


def _entry_box_tl(
    e: Dict[str, Any], x_offset: int = 0, y_offset: int = 0
) -> Tuple[int, int, int, int]:
    """从 OCR entry 取左上角 AABB (x,y,w,h)。"""
    w = max(1, int(round(float(e.get("w") or 0))))
    h = max(1, int(round(float(e.get("h") or 0))))
    if e.get("y_tl") is not None:
        x1 = int(round(float(e.get("x_tl", e.get("x") or 0)) + x_offset))
        y1 = int(round(float(e.get("y_tl") or 0) + y_offset))
    else:
        x1 = int(round(float(e.get("x") or 0) + x_offset))
        y_c = float(e.get("y") or 0) + y_offset
        y1 = int(round(y_c - h / 2.0))
    return x1, y1, w, h


def lookup_ocr9_correction(
    img_bgr,
    x: int,
    y: int,
    w: int,
    h: int,
    records: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Optional[str], str]:
    """
    单框查询纠错真值（ocr9 增补，非兜底）。

    返回 (真值或 None, 模式)：
      - exact：MD5 精确命中
      - fuzzy：IoU 门控 + aHash/L1 外观增补
      - ""：不增补，保留模型输出

    规范：无证据不改写；禁止文本相似硬改、默认值填充。
    """
    if img_bgr is None or w <= 0 or h <= 0:
        return None, ""
    if _ocr9_memory_disabled():
        return None, ""
    recs = records if records is not None else load_ocr9_correction_records()
    if not recs:
        return None, ""

    mem_exact = {r["key"]: r["text"] for r in recs}
    # —— 层0：精确 MD5（含 pad 变体，与入库一致）——
    for pad in (0, 2, 1, 3):
        key = _crop_region_phash(img_bgr, x - pad, y - pad, w + 2 * pad, h + 2 * pad)
        if key and key in mem_exact:
            return mem_exact[key], "exact"

    # —— 层1+2：模糊增补（位置近 ∧ 外观近）；默认开，可关 ——
    if not _ocr9_fuzzy_enabled():
        return None, ""

    tau_iou, tau_app, ham_max = _ocr9_fuzzy_thresholds()
    q_bits = _crop_region_ahash_bits(img_bgr, x, y, w, h)
    q_crop = _clip_crop_bgr(img_bgr, x, y, w, h)
    if q_crop is None:
        return None, ""

    best: Optional[Tuple[float, float, float, str]] = None
    # best = (score, iou, app, text)
    root = os.path.dirname(os.path.abspath(__file__))
    ws_mem = os.path.join(root, "ocr_train_workspace")

    for r in recs:
        text = r.get("text") or ""
        if not text:
            continue
        box = r.get("box")
        # 无框元数据：无法做位置门控 → 不参与模糊（避免全页乱配，非兜底）
        if not box:
            continue
        mx, my, mw, mh = box
        iou = box_iou(float(x), float(y), float(w), float(h), mx, my, mw, mh)
        if iou < tau_iou:
            continue

        a_bits = int(r.get("ahash_bits") or 0)
        if not a_bits:
            mb = _crop_region_ahash_bits(img_bgr, int(mx), int(my), int(mw), int(mh))
            a_bits = int(mb) if mb is not None else 0

        ham = hamming64(int(q_bits), a_bits) if (q_bits is not None and a_bits) else 64
        if a_bits and ham > ham_max:
            continue

        l1 = 1.0
        has_l1 = False
        rel = (r.get("crop_relpath") or "").strip()
        if rel:
            crop_path = rel if os.path.isabs(rel) else os.path.join(
                ws_mem, rel.replace("/", os.sep)
            )
            if os.path.isfile(crop_path):
                m_crop = imread_unicode(crop_path)
                l1 = _crop_l1_distance(q_crop, m_crop)
                has_l1 = True

        # 外观综合：平移时 aHash 易升高，L1 更稳 → 互补（有 L1 时偏重 L1）
        ham_n = (ham / 64.0) if a_bits else 0.25
        if has_l1 and a_bits:
            app = 0.45 * ham_n + 0.55 * float(l1)
        elif has_l1:
            app = float(l1)
        elif a_bits:
            app = ham_n
        else:
            continue  # 无任何外观证据 → 不增补

        if app > tau_app:
            continue

        # 综合分：位置证据为主，外观惩罚为辅
        score = float(iou) - 0.5 * float(app)
        cand = (score, float(iou), float(app), text)
        if best is None or cand[0] > best[0]:
            best = cand

    if best is None:
        return None, ""
    return best[3], "fuzzy"


def apply_ocr9_corrections(
    img_bgr,
    entries: List[Dict[str, Any]],
    x_offset: int = 0,
    y_offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    ocr9 纠错记忆增补（非兜底）。

    层0 精确 MD5 → 层1 IoU 门控 + 层2 aHash/L1 模糊增补。
    无足够图像证据则保留模型输出；禁止 t:文本硬改、默认值填充。

    ocr9 入库 AABB：x=min(xs), y=min(ys)；历史 entry 的 y 可能是中心。
    """
    recs = load_ocr9_correction_records()
    if not recs or not entries or img_bgr is None:
        return entries, 0
    hit = 0
    n_exact = 0
    n_fuzzy = 0
    for e in entries:
        try:
            x1, y1, w, h = _entry_box_tl(e, x_offset, y_offset)
            text, mode = lookup_ocr9_correction(img_bgr, x1, y1, w, h, records=recs)
            if text and mode:
                e["text"] = text
                e["ocr9_mem"] = mode
                hit += 1
                if mode == "exact":
                    n_exact += 1
                else:
                    n_fuzzy += 1
        except Exception:
            continue
    if hit:
        print(
            f"[OCR] ocr9 纠错增补命中 {hit}/{len(entries)} "
            f"(精确 {n_exact} + 模糊 {n_fuzzy}；非兜底/无文本硬改)"
        )
    return entries, hit


# ---------------------------------------------------------------------------
# 图像裁剪 / 表格格式化
# ---------------------------------------------------------------------------

def crop_image(image_path: str, x: int, y: int, w: int, h: int, save_crop_path: Optional[str] = None):
    """裁剪图片区域，可选择性保存子图。"""
    img = imread_unicode(image_path)
    if img is None:
        img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"无法读取图片: {image_path}")
    img_h, img_w = img.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(img_w, x + w), min(img_h, y + h)
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"无效的裁剪区域: x1={x1}, y1={y1}, x2={x2}, y2={y2}")

    crop = img[y1:y2, x1:x2]
    if save_crop_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_crop_path)), exist_ok=True)
        cv2.imwrite(save_crop_path, crop)
        print(f"[OCR] 已保存裁剪图片到: {save_crop_path}")
    return crop


def format_table_cluster(entries: List[Dict[str, Any]]) -> str:
    """基于坐标聚类，将识别项格式化为类表格文本。"""
    if not entries:
        return ""
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

    lines = []
    for row in rows:
        row.sort(key=lambda e: e["x"])
        line = " | ".join(e["text"] for e in row)
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PaddleOCR 实例缓存与构建
# ---------------------------------------------------------------------------

_ocr_cache: Dict[Any, Any] = {}

# 可透传给 PaddleOCR(...) 的全部本地模型参数名（不含 device / enable_mkldnn）
_PADDLE_OCR_PARAM_KEYS = (
    # 文档方向 PP-LCNet_x1_0_doc_ori
    "doc_orientation_classify_model_name",
    "doc_orientation_classify_model_dir",
    "use_doc_orientation_classify",
    # 文档展平 UVDoc（预处理，与 doc_ori 同属 DocPreprocessor）
    "doc_unwarping_model_name",
    "doc_unwarping_model_dir",
    "use_doc_unwarping",
    # 文本检测 PP-OCRv6_medium_det
    "text_detection_model_name",
    "text_detection_model_dir",
    "text_det_limit_side_len",
    "text_det_limit_type",
    "text_det_thresh",
    "text_det_box_thresh",
    "text_det_unclip_ratio",
    "text_det_input_shape",
    # 文本行方向 PP-LCNet_x1_0_textline_ori
    "textline_orientation_model_name",
    "textline_orientation_model_dir",
    "textline_orientation_batch_size",
    "use_textline_orientation",
    # 文本识别 PP-OCRv6_medium_rec
    "text_recognition_model_name",
    "text_recognition_model_dir",
    "text_recognition_batch_size",
    "text_rec_score_thresh",
    "text_rec_input_shape",
    "return_word_box",
    # 版本 / 语言（在未显式指定 det/rec 模型名时生效）
    "lang",
    "ocr_version",
)

# Web UI / config.json 默认值（与 agent 侧历史硬编码阈值对齐：box_thresh=0.2, score=0.1）
DEFAULT_OCR_PARAMS: Dict[str, Any] = {
    # ① 文档整页方向 PP-LCNet_x1_0_doc_ori
    "use_doc_orientation_classify": True,
    "doc_orientation_classify_model_name": "PP-LCNet_x1_0_doc_ori",
    # 文档展平 UVDoc（预处理，与 doc_ori 同组）
    "use_doc_unwarping": False,
    # ② 文本检测 PP-OCRv6_medium_det
    "text_detection_model_name": "PP-OCRv6_medium_det",
    "text_det_thresh": 0.3,
    "text_det_box_thresh": 0.2,
    "text_det_unclip_ratio": 1.5,
    # ③ 文本行方向 PP-LCNet_x1_0_textline_ori
    "use_textline_orientation": True,
    "textline_orientation_model_name": "PP-LCNet_x1_0_textline_ori",
    # ④ 文本识别 PP-OCRv6_medium_rec
    "text_recognition_model_name": "PP-OCRv6_medium_rec",
    "text_rec_score_thresh": 0.1,
}


def merge_ocr_params(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """合并默认 OCR 参数与 config/UI 覆盖项，只保留可透传键。"""
    allowed = set(_PADDLE_OCR_PARAM_KEYS)
    merged: Dict[str, Any] = {
        k: v for k, v in DEFAULT_OCR_PARAMS.items() if k in allowed
    }
    if overrides:
        for k, v in overrides.items():
            if v is not None and k in allowed:
                merged[k] = v
    return merged


def _normalize_paddle_kwargs(
    *,
    det_db_box_thresh: Optional[float] = None,
    drop_score: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """合并旧别名参数，过滤 None，得到传给 PaddleOCR 的 kwargs。"""
    params: Dict[str, Any] = {}
    for key in _PADDLE_OCR_PARAM_KEYS:
        if key in kwargs and kwargs[key] is not None:
            params[key] = kwargs[key]

    # 兼容历史参数名（agent_core / 旧 CLI）
    if det_db_box_thresh is not None:
        params["text_det_box_thresh"] = det_db_box_thresh
    if drop_score is not None:
        params["text_rec_score_thresh"] = drop_score

    # 未显式指定 det/rec 模型时，用 lang + ocr_version 自动配对 medium_det/rec
    # （若已指定 model_name/dir，再传 lang/ocr_version 会触发 PaddleOCR 警告且被忽略）
    _explicit_det_rec = any(
        params.get(k) is not None
        for k in (
            "text_detection_model_name",
            "text_detection_model_dir",
            "text_recognition_model_name",
            "text_recognition_model_dir",
        )
    )
    if not _explicit_det_rec:
        params.setdefault("lang", "ch")
        params.setdefault("ocr_version", "PP-OCRv6")
    return params


def get_ocr_instance(
    device: str = "cpu",
    det_db_box_thresh: Optional[float] = None,
    drop_score: Optional[float] = None,
    **paddle_kwargs: Any,
):
    """
    获取或缓存 PaddleOCR 实例。

    缓存键 = (device, 规范化后的全部模型参数)。
    同一 device 下不同阈值/模型名会创建不同实例，避免参数互相覆盖。
    """
    global _ocr_cache
    params = _normalize_paddle_kwargs(
        det_db_box_thresh=det_db_box_thresh,
        drop_score=drop_score,
        **paddle_kwargs,
    )
    cache_key = (device, tuple(sorted(params.items(), key=lambda x: x[0])))

    if cache_key not in _ocr_cache:
        import paddle.inference as _pi
        if not getattr(_pi.Config, "_patched_for_onednn", False):
            try:
                _orig_new_ir = _pi.Config.enable_new_ir
                _pi.Config.enable_new_ir = lambda self, v=True: _orig_new_ir(self, False)
                _orig_opt = _pi.Config.set_optimization_level
                _pi.Config.set_optimization_level = lambda self, lv: _orig_opt(self, 0)
                _pi.Config._patched_for_onednn = True
            except AttributeError:
                pass

        if device == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        else:
            if "CUDA_VISIBLE_DEVICES" in os.environ:
                del os.environ["CUDA_VISIBLE_DEVICES"]

        from paddleocr import PaddleOCR
        kwargs = dict(params)
        kwargs["device"] = device
        if device == "cpu":
            kwargs["enable_mkldnn"] = True

        print(f"[OCR] 初始化 PaddleOCR: device={device}")
        for k, v in sorted(kwargs.items()):
            if k in ("device", "enable_mkldnn"):
                continue
            print(f"[OCR]   {k}={v!r}")

        _ocr_cache[cache_key] = PaddleOCR(**kwargs)

    return _ocr_cache[cache_key]


def run_vision_ocr(image_path: str, api_key: str, base_url: str, model_name: str) -> str:
    """调用 OpenAI 兼容接口，通过视觉大模型进行表格识别。"""
    import base64
    from openai import OpenAI

    if not api_key:
        raise ValueError("API key must be provided for vision engine.")

    client = OpenAI(api_key=api_key, base_url=base_url)

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    prompt = (
        "请识别这张表格图片中的全部内容，输出 Markdown 表格格式。\n"
        "要求：\n"
        "1. 保留所有勾选符号（✓、×、√、X），准确填入对应单元格\n"
        "2. 合并单元格用 Markdown 标准语法表达，保持行列对齐\n"
        "3. 手写体文字标注（手写）\n"
        "4. 仅输出 Markdown，不要解释"
    )

    resp = client.chat.completions.create(
        model=model_name,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        temperature=0.1,
        max_tokens=8192,
        timeout=120,
    )
    return resp.choices[0].message.content.strip()


def run_ocr(
    image_path: str,
    coords: Optional[tuple] = None,
    save_crop_path: Optional[str] = None,
    save_markdown_path: Optional[str] = None,
    mode: str = "cluster",
    device: str = "gpu",
    engine: str = "paddleocr",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
    det_db_box_thresh: Optional[float] = None,
    drop_score: Optional[float] = None,
    **paddle_kwargs: Any,
) -> str:
    """
    OCR 扫描主控。

    本地引擎下，det_db_box_thresh / drop_score 及 **paddle_kwargs 中的模型参数
    会全部透传给 get_ocr_instance → PaddleOCR。
    """
    if engine == "vision":
        print(f"[OCR] Running Vision LLM OCR: {image_path} (model: {model_name})")
        ocr_result = run_vision_ocr(image_path, api_key or "", base_url or "", model_name or "")
        if save_markdown_path:
            os.makedirs(os.path.dirname(os.path.abspath(save_markdown_path)), exist_ok=True)
            with open(save_markdown_path, "w", encoding="utf-8") as f:
                f.write(ocr_result)
            print(f"[OCR] Saved scan result in Markdown format to: {save_markdown_path}")
        return ocr_result

    if coords:
        x, y, w, h = coords
        print(f"[OCR] 区域裁剪 OCR: x={x}, y={y}, w={w}, h={h} (使用设备: {device})")
        img_for_ocr = crop_image(image_path, x, y, w, h, save_crop_path)
        x_offset, y_offset = x, y
    else:
        print(f"[OCR] 默认扫描全图 OCR: {image_path} (使用设备: {device})")
        img_for_ocr = imread_unicode(image_path)
        if img_for_ocr is None:
            img_for_ocr = cv2.imread(image_path)
        if img_for_ocr is None:
            raise FileNotFoundError(f"无法读取图片: {image_path}")
        x_offset, y_offset = 0, 0

    ocr = get_ocr_instance(
        device=device,
        det_db_box_thresh=det_db_box_thresh,
        drop_score=drop_score,
        **paddle_kwargs,
    )
    result = ocr.predict(img_for_ocr)

    entries = []
    if result and hasattr(result[0], "json") and result[0].json is not None:
        res = result[0].json.get("res", {}) or {}
        texts = res.get("rec_texts", []) or []
        # 与 ocr9 一致：优先 dt_polys（检测框），再 rec_polys
        polys = res.get("dt_polys") or res.get("rec_polys") or []
        if texts:
            for i, text in enumerate(texts):
                box = polys[i] if i < len(polys) else []
                if (
                    isinstance(box, (list, tuple, np.ndarray))
                    and len(box) >= 3
                    and all(
                        isinstance(pt, (list, tuple, np.ndarray)) and len(pt) >= 2
                        for pt in box[:3]
                    )
                ):
                    # 轴对齐 AABB，与 ocr9.OcrBox / crop_phash 入库一致
                    arr = np.asarray(box, dtype=float).reshape(-1, 2)
                    x_min = float(arr[:, 0].min())
                    y_min = float(arr[:, 1].min())
                    x_max = float(arr[:, 0].max())
                    y_max = float(arr[:, 1].max())
                    width = max(1.0, x_max - x_min)
                    height = max(1.0, y_max - y_min)
                    y_center = (y_min + y_max) / 2.0
                else:
                    x_min, y_min = 0.0, 0.0
                    width, height = 0.0, 20.0
                    y_center = 0.0
                entries.append({
                    "text": text,
                    "y": y_center,  # 行聚类仍用竖直中心
                    "x": x_min,
                    "h": height,
                    "w": width,
                    "x_tl": x_min,
                    "y_tl": y_min,
                })

    # ocr9 入库纠错：直接读 ocr_train_workspace/memory/corrections.json（入库即生效）
    entries, _ = apply_ocr9_corrections(img_for_ocr, entries, 0, 0)

    print(f"[OCR] OCR 识别完成，共 {len(entries)} 个文本块")
    if not entries:
        ocr_result = ""
    else:
        table_text = format_table_cluster(entries)
        flat_text = "\n".join(
            f"{e['text']}  [{int(e['x'] + x_offset)},{int(e['y'] + y_offset)},{int(e['w'])},{int(e['h'])}]"
            for e in sorted(entries, key=lambda e: (e["y"] // 15, e["x"]))
        )
        ocr_result = f"{table_text}\n---\n{flat_text}"

    if save_markdown_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_markdown_path)), exist_ok=True)
        with open(save_markdown_path, "w", encoding="utf-8") as f:
            f.write(ocr_result)
        print(f"[OCR] 已将扫描结果以 Markdown 格式保存至: {save_markdown_path}")

    return ocr_result


# ---------------------------------------------------------------------------
# CLI 参数构建
# ---------------------------------------------------------------------------

def _str2bool(value: str) -> bool:
    """将命令行字符串解析为 bool（true/false/1/0/yes/no/on/off）。"""
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError(
        f"无效布尔值 {value!r}，请使用 true/false、1/0、yes/no、on/off"
    )


def _parse_int_triple(value: str) -> Tuple[int, int, int]:
    """解析 C,H,W 形式的输入形状，例如 3,32,320。"""
    parts = [p.strip() for p in value.replace("x", ",").split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"输入形状须为 3 个整数 C,H,W，例如 3,32,320；收到: {value!r}"
        )
    try:
        c, h, w = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"输入形状须为整数: {value!r}") from e
    return (c, h, w)


_CLI_EPILOG = r"""
================================================================================
模型与参数说明（PaddleOCR 3.x / PP-OCRv6 流水线）
================================================================================

本 CLI 对应本地引擎 paddleocr 下的四类核心模型（以及可选的文档展平）：

  ┌──────────────────────────────────────────────────────────────────────────┐
  │ 1) 文档整页方向  PP-LCNet_x1_0_doc_ori                                   │
  │    判断整张图是 0°/90°/180°/270°，必要时旋转后再做后续 OCR。             │
  │ 2) 文本检测      PP-OCRv6_medium_det                                     │
  │    在图中找出文字区域（多边形框），不负责认字。                           │
  │ 3) 文本行方向    PP-LCNet_x1_0_textline_ori                              │
  │    对每个文本行判断是否需 180° 翻转（倒置文字行）。                       │
  │ 4) 文本识别      PP-OCRv6_medium_rec                                     │
  │    对裁出的文本行图像识别出具体字符。                                     │
  │ (可选) 文档展平  UVDoc                                                   │
  │    校正弯曲/卷曲纸面，与 doc_ori 同属文档预处理子流水线。                 │
  └──────────────────────────────────────────────────────────────────────────┘

默认模型目录：未指定 --*-model-dir 时，自动使用官方缓存
  Windows:  %%USERPROFILE%%\.paddlex\official_models\<模型名>
  日志中 Creating model: ('模型名', None, None) 表示 model_dir / engine 用默认。

--------------------------------------------------------------------------------
【重要】模型名与 ocr-version / lang 的关系
--------------------------------------------------------------------------------
  - 若未指定 --text-detection-model-name / --text-recognition-model-name
    （及其 model-dir），则由 --lang + --ocr-version 自动配对，例如：
      --lang ch --ocr-version PP-OCRv6
        → det=PP-OCRv6_medium_det , rec=PP-OCRv6_medium_rec
  - 一旦显式指定了 det 或 rec 的 model-name 或 model-dir，
    --lang 与 --ocr-version 对模型选择将失效（PaddleOCR 官方行为）。
  - 方向类模型不受 ocr-version 映射影响，始终可用 --*-model-name 覆盖。

--------------------------------------------------------------------------------
【调参建议】提高作业票类表格识别率
--------------------------------------------------------------------------------
  漏检小字/手写勾叉：
    --text-det-box-thresh 0.2~0.4   （默认流水线约 0.6，越低框越多）
    --text-det-thresh 0.2~0.3       （像素级阈值，越低越敏感）
  框切字导致识别错：
    --text-det-unclip-ratio 1.6~2.0 （框扩张，过大可能粘连相邻字）
  低置信结果被丢掉：
    --text-rec-score-thresh 0.0~0.1 （默认 0.0 表示几乎不过滤）
  票面方向固定且已对齐：
    --use-doc-orientation-classify false
    --use-textline-orientation false
    --use-doc-unwarping false         （可明显加速）
  手机拍照整页颠倒/横放：
    --use-doc-orientation-classify true
  个别行倒立：
    --use-textline-orientation true

  兼容旧参数（与上表等价）：
    --det-thresh  <->  --text-det-box-thresh
    --drop-score  <->  --text-rec-score-thresh

--------------------------------------------------------------------------------
示例
--------------------------------------------------------------------------------
  # 查看本说明
  python ocr.py -h

  # 默认全图识别（CPU）
  python ocr.py ticket.png

  # GPU + 调低检测阈值，少漏手写符号
  python ocr.py ticket.png --device gpu \
    --text-det-box-thresh 0.2 --text-det-thresh 0.25 --text-rec-score-thresh 0.1

  # 关闭方向校正加速（票面已对齐时）
  python ocr.py ticket.png \
    --use-doc-orientation-classify false \
    --use-textline-orientation false \
    --use-doc-unwarping false

  # 指定本地模型目录（自训练或离线拷贝）
  python ocr.py ticket.png \
    --text-detection-model-dir "D:/models/PP-OCRv6_medium_det" \
    --text-recognition-model-dir "D:/models/PP-OCRv6_medium_rec"

  # 换用更轻量检测模型（更快，精度可能下降）
  python ocr.py ticket.png \
    --text-detection-model-name PP-OCRv6_small_det \
    --text-recognition-model-name PP-OCRv6_small_rec

  # 裁剪区域并保存结果
  python ocr.py ticket.png --coord 300,80,200,100 \
    --save-crop crop.jpg --save-markdown out.md

  # 视觉大模型引擎
  python ocr.py ticket.png --engine vision \
    --api-key sk-xxx --base-url https://api.siliconflow.cn/v1 \
    --model-name Qwen/Qwen2.5-VL-7B-Instruct
================================================================================
"""


def build_arg_parser() -> argparse.ArgumentParser:
    """构建带分组、详细 help 的命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="ocr.py",
        description=(
            "中燃安全数字监督员 · OCR 命令行工具\n"
            "支持本地 PaddleOCR（PP-OCRv6 四模型流水线）与视觉大模型双引擎。"
        ),
        epilog=_CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ---------- 基础 ----------
    g_base = parser.add_argument_group("基础输入/输出")
    g_base.add_argument(
        "image",
        help="待识别图片路径（必填）。支持常见格式：png/jpg/jpeg/bmp 等。",
    )
    g_base.add_argument(
        "--coord",
        default=None,
        metavar="X,Y,W,H",
        help=(
            "可选裁剪区域，格式 x,y,w,h（像素，相对原图左上角）。"
            "例：--coord 300,80,200,100 。省略则扫描全图。"
        ),
    )
    g_base.add_argument(
        "--save-crop",
        default=None,
        metavar="PATH",
        help="若指定了 --coord，将裁剪子图保存到此路径。",
    )
    g_base.add_argument(
        "--save-markdown",
        default=None,
        metavar="PATH",
        help="将 OCR 结果（表格聚类文本 + 坐标明细）保存为 UTF-8 文本/Markdown 文件。",
    )
    g_base.add_argument(
        "--device",
        choices=["cpu", "gpu"],
        default="cpu",
        help="推理设备。cpu：兼容性好；gpu：需安装 CUDA 版 PaddlePaddle。默认: cpu。",
    )
    g_base.add_argument(
        "--engine",
        choices=["paddleocr", "vision"],
        default="paddleocr",
        help=(
            "OCR 引擎。paddleocr=本地四模型流水线（可调下方全部模型参数）；"
            "vision=云端视觉大模型（忽略本地模型参数）。默认: paddleocr。"
        ),
    )
    g_base.add_argument(
        "--lang",
        default=None,
        metavar="LANG",
        help=(
            "OCR 语言代码。与 --ocr-version 一起决定默认 det/rec 模型名。"
            "常用: ch（简体中文，默认）、en、chinese_cht、japan 等。"
            "注意：一旦显式指定 det/rec 的 model-name 或 model-dir，本项对模型选择失效。"
        ),
    )
    g_base.add_argument(
        "--ocr-version",
        default=None,
        choices=["PP-OCRv3", "PP-OCRv4", "PP-OCRv5", "PP-OCRv6"],
        metavar="VER",
        help=(
            "PP-OCR 版本。本项目默认逻辑为 PP-OCRv6（在未指定时由代码注入）。"
            "PP-OCRv6 + ch → PP-OCRv6_medium_det + PP-OCRv6_medium_rec。"
            "可选: PP-OCRv3 / PP-OCRv4 / PP-OCRv5 / PP-OCRv6。"
        ),
    )

    # ---------- 1. 文档整页方向 ----------
    g_doc = parser.add_argument_group(
        "① 文档整页方向模型  PP-LCNet_x1_0_doc_ori  "
        "(doc_orientation_classify)"
    )
    g_doc.add_argument(
        "--use-doc-orientation-classify",
        type=_str2bool,
        default=None,
        metavar="BOOL",
        help=(
            "是否启用整页方向分类（0°/90°/180°/270°）。"
            "true=启用（适合手机随意拍摄、整页颠倒）；"
            "false=关闭（票面已摆正/已对齐时建议关闭以提速）。"
            "未指定则使用 PaddleOCR/PaddleX 流水线默认（通常为开启）。"
            "取值: true/false、1/0、yes/no。"
        ),
    )
    g_doc.add_argument(
        "--doc-orientation-classify-model-name",
        default=None,
        metavar="NAME",
        help=(
            "整页方向分类模型名称。默认: PP-LCNet_x1_0_doc_ori。"
            "仅在需要替换为其它已注册官方模型名时修改。"
        ),
    )
    g_doc.add_argument(
        "--doc-orientation-classify-model-dir",
        default=None,
        metavar="DIR",
        help=(
            "整页方向分类模型本地目录（含推理文件）。"
            "None/省略=自动下载并使用 %%USERPROFILE%%\\.paddlex\\official_models\\PP-LCNet_x1_0_doc_ori 。"
            "离线部署时指向已拷贝的模型文件夹。"
        ),
    )

    # ---------- 文档展平（预处理，常与 doc_ori 一起讨论） ----------
    g_unwarp = parser.add_argument_group(
        "①b 文档展平模型  UVDoc  (doc_unwarping，可选预处理)"
    )
    g_unwarp.add_argument(
        "--use-doc-unwarping",
        type=_str2bool,
        default=None,
        metavar="BOOL",
        help=(
            "是否启用文档展平（弯曲纸面矫正）。"
            "true=启用，适合严重卷曲/透视弯曲的拍照；"
            "false=关闭，平面扫描件/已透视对齐的作业票建议关闭（更快）。"
            "未指定则用流水线默认。取值: true/false、1/0、yes/no。"
        ),
    )
    g_unwarp.add_argument(
        "--doc-unwarping-model-name",
        default=None,
        metavar="NAME",
        help="文档展平模型名称。默认: UVDoc。",
    )
    g_unwarp.add_argument(
        "--doc-unwarping-model-dir",
        default=None,
        metavar="DIR",
        help=(
            "文档展平模型本地目录。省略则使用官方缓存 "
            "%%USERPROFILE%%\\.paddlex\\official_models\\UVDoc 。"
        ),
    )

    # ---------- 2. 文本检测 ----------
    g_det = parser.add_argument_group(
        "② 文本检测模型  PP-OCRv6_medium_det  (text_detection)  "
        "— 对「找不找得到字」影响最大"
    )
    g_det.add_argument(
        "--text-detection-model-name",
        default=None,
        metavar="NAME",
        help=(
            "文本检测模型名称。PP-OCRv6 常见取值：\n"
            "  PP-OCRv6_medium_det  （默认，精度与速度均衡）\n"
            "  PP-OCRv6_small_det   （更轻更快，精度略降）\n"
            "  PP-OCRv6_tiny_det    （最快，精度最低）\n"
            "也可使用 v5 等其它已安装的检测模型名。"
            "若设置本项或 model-dir，则 --lang/--ocr-version 的自动配对失效。"
        ),
    )
    g_det.add_argument(
        "--text-detection-model-dir",
        default=None,
        metavar="DIR",
        help=(
            "文本检测模型本地目录。省略则使用 "
            "%%USERPROFILE%%\\.paddlex\\official_models\\PP-OCRv6_medium_det 。"
        ),
    )
    g_det.add_argument(
        "--text-det-thresh",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "检测「像素级」概率阈值（DB 算法，对应旧名 det_db_thresh）。"
            "概率图中高于该阈值的像素视为文字像素。"
            "流水线默认约 0.3。范围建议 0.1~0.5。"
            "↓ 降低：淡字、浅笔迹、细线更易被检出，噪声也可能增多；"
            "↑ 升高：更干净，但易漏检浅色手写。"
        ),
    )
    g_det.add_argument(
        "--text-det-box-thresh",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "检测「文本框」置信度阈值（对应旧名 det_db_box_thresh / --det-thresh）。"
            "框内平均得分高于此值才保留为文本区域。"
            "流水线默认约 0.6；作业票手写符号场景常降到 0.2~0.4 以减少漏检。"
            "↓ 降低：框更多（含小符号），误检可能上升；"
            "↑ 升高：框更少、更干净，易漏小字。"
        ),
    )
    g_det.add_argument(
        "--det-thresh",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "[兼容旧参数] 等价于 --text-det-box-thresh。"
            "若两者同时给出，以 --text-det-box-thresh 为准。"
        ),
    )
    g_det.add_argument(
        "--text-det-unclip-ratio",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "文本框扩张系数（对应旧名 det_db_unclip_ratio）。"
            "流水线默认约 1.5。越大框扩得越大，能包住更完整笔画，"
            "过大则相邻文字框可能粘连。建议 1.5~2.0。"
        ),
    )
    g_det.add_argument(
        "--text-det-limit-side-len",
        type=int,
        default=None,
        metavar="INT",
        help=(
            "送入检测模型前，对图像边长的限制数值。"
            "与 --text-det-limit-type 配合：type=min 时限制最短边，type=max 时限制最长边。"
            "PP-OCRv6 general 流水线默认 limit_side_len=64、limit_type=min。"
            "增大可保留更多细节（更慢、更占显存）；过小可能漏小字。"
        ),
    )
    g_det.add_argument(
        "--text-det-limit-type",
        default=None,
        choices=["min", "max"],
        metavar="TYPE",
        help=(
            "边长限制方式：min=限制最短边；max=限制最长边。"
            "须与 --text-det-limit-side-len 一起理解。默认流水线为 min。"
        ),
    )
    g_det.add_argument(
        "--text-det-input-shape",
        type=_parse_int_triple,
        default=None,
        metavar="C,H,W",
        help=(
            "检测模型输入张量形状，格式 C,H,W（例如 3,640,640）。"
            "一般无需设置，仅在自定义模型或官方要求固定 shape 时使用。"
        ),
    )

    # ---------- 3. 文本行方向 ----------
    g_cls = parser.add_argument_group(
        "③ 文本行方向模型  PP-LCNet_x1_0_textline_ori  "
        "(textline_orientation)"
    )
    g_cls.add_argument(
        "--use-textline-orientation",
        type=_str2bool,
        default=None,
        metavar="BOOL",
        help=(
            "是否启用文本行方向分类（0°/180°）。"
            "true=对每个检测行判断是否倒置并翻转；"
            "false=关闭（行方向正确时建议关闭提速）。"
            "旧参数名 use_angle_cls 已映射到本开关。"
            "取值: true/false、1/0、yes/no。未指定则用流水线默认。"
        ),
    )
    g_cls.add_argument(
        "--textline-orientation-model-name",
        default=None,
        metavar="NAME",
        help=(
            "文本行方向模型名称。默认: PP-LCNet_x1_0_textline_ori。"
            "另有更轻量 PP-LCNet_x0_25_textline_ori（若环境已提供）。"
        ),
    )
    g_cls.add_argument(
        "--textline-orientation-model-dir",
        default=None,
        metavar="DIR",
        help=(
            "文本行方向模型本地目录。省略则使用 "
            "%%USERPROFILE%%\\.paddlex\\official_models\\PP-LCNet_x1_0_textline_ori 。"
        ),
    )
    g_cls.add_argument(
        "--textline-orientation-batch-size",
        type=int,
        default=None,
        metavar="INT",
        help=(
            "文本行方向分类的批大小。默认流水线约 6。"
            "↑ 增大：吞吐更高，显存占用更大；"
            "↓ 减小：更省显存，略慢。通常无需修改。"
        ),
    )

    # ---------- 4. 文本识别 ----------
    g_rec = parser.add_argument_group(
        "④ 文本识别模型  PP-OCRv6_medium_rec  (text_recognition)  "
        "— 对「认对字」影响最大"
    )
    g_rec.add_argument(
        "--text-recognition-model-name",
        default=None,
        metavar="NAME",
        help=(
            "文本识别模型名称。PP-OCRv6 常见取值：\n"
            "  PP-OCRv6_medium_rec  （默认，与 medium_det 配对）\n"
            "  PP-OCRv6_small_rec\n"
            "  PP-OCRv6_tiny_rec\n"
            "若设置本项或 model-dir，则 --lang/--ocr-version 自动配对失效，"
            "请同时确认 det 模型与之匹配。"
        ),
    )
    g_rec.add_argument(
        "--text-recognition-model-dir",
        default=None,
        metavar="DIR",
        help=(
            "文本识别模型本地目录。省略则使用 "
            "%%USERPROFILE%%\\.paddlex\\official_models\\PP-OCRv6_medium_rec 。"
            "命令行 Creating model 日志中 rec 常在 det/方向之后最后加载，"
            "请滚到日志末尾确认 'PP-OCRv6_medium_rec'。"
        ),
    )
    g_rec.add_argument(
        "--text-recognition-batch-size",
        type=int,
        default=None,
        metavar="INT",
        help=(
            "识别批大小。默认流水线约 6。"
            "↑ 更大批次通常更快但更占显存；OOM 时可降到 1~2。"
        ),
    )
    g_rec.add_argument(
        "--text-rec-score-thresh",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "识别结果置信度阈值：得分低于该值的文本会被丢弃。"
            "流水线默认 0.0（不过滤）。"
            "手写/模糊场景可保持 0.0~0.1；需要更干净结果可升到 0.5+（会丢低置信行）。"
            "对应旧参数 --drop-score。"
        ),
    )
    g_rec.add_argument(
        "--drop-score",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "[兼容旧参数] 等价于 --text-rec-score-thresh。"
            "若两者同时给出，以 --text-rec-score-thresh 为准。"
        ),
    )
    g_rec.add_argument(
        "--text-rec-input-shape",
        type=_parse_int_triple,
        default=None,
        metavar="C,H,W",
        help=(
            "识别模型输入形状 C,H,W（例如 3,48,320）。"
            "一般无需设置，仅自定义模型时使用。"
        ),
    )
    g_rec.add_argument(
        "--return-word-box",
        type=_str2bool,
        default=None,
        metavar="BOOL",
        help=(
            "是否返回识别结果的字级/词级坐标框（若模型与流水线支持）。"
            "true=返回更细粒度坐标；false=仅行级。默认由流水线决定。"
            "取值: true/false、1/0、yes/no。"
        ),
    )

    # ---------- Vision ----------
    g_vis = parser.add_argument_group("视觉大模型引擎 (engine=vision 时生效)")
    g_vis.add_argument(
        "--api-key",
        default=None,
        help="Vision LLM API Key（engine=vision 时必填）。",
    )
    g_vis.add_argument(
        "--base-url",
        default="https://api.siliconflow.cn/v1",
        help="Vision LLM API Base URL。默认: https://api.siliconflow.cn/v1",
    )
    g_vis.add_argument(
        "--model-name",
        default="Qwen/Qwen2.5-7B-Instruct",
        help=(
            "Vision LLM 模型名（注意：这是云端模型，不是 PP-OCRv6_medium_rec）。"
            "默认: Qwen/Qwen2.5-7B-Instruct"
        ),
    )

    return parser


def _cli_to_paddle_kwargs(args: argparse.Namespace) -> Dict[str, Any]:
    """从 argparse Namespace 提取非 None 的 PaddleOCR 参数。"""
    # 新参数优先于旧别名
    box_thresh = args.text_det_box_thresh
    if box_thresh is None:
        box_thresh = args.det_thresh

    rec_score = args.text_rec_score_thresh
    if rec_score is None:
        rec_score = args.drop_score

    mapping = {
        "lang": args.lang,
        "ocr_version": args.ocr_version,
        # doc ori
        "use_doc_orientation_classify": args.use_doc_orientation_classify,
        "doc_orientation_classify_model_name": args.doc_orientation_classify_model_name,
        "doc_orientation_classify_model_dir": args.doc_orientation_classify_model_dir,
        # unwarping
        "use_doc_unwarping": args.use_doc_unwarping,
        "doc_unwarping_model_name": args.doc_unwarping_model_name,
        "doc_unwarping_model_dir": args.doc_unwarping_model_dir,
        # det
        "text_detection_model_name": args.text_detection_model_name,
        "text_detection_model_dir": args.text_detection_model_dir,
        "text_det_thresh": args.text_det_thresh,
        "text_det_box_thresh": box_thresh,
        "text_det_unclip_ratio": args.text_det_unclip_ratio,
        "text_det_limit_side_len": args.text_det_limit_side_len,
        "text_det_limit_type": args.text_det_limit_type,
        "text_det_input_shape": args.text_det_input_shape,
        # textline ori
        "use_textline_orientation": args.use_textline_orientation,
        "textline_orientation_model_name": args.textline_orientation_model_name,
        "textline_orientation_model_dir": args.textline_orientation_model_dir,
        "textline_orientation_batch_size": args.textline_orientation_batch_size,
        # rec
        "text_recognition_model_name": args.text_recognition_model_name,
        "text_recognition_model_dir": args.text_recognition_model_dir,
        "text_recognition_batch_size": args.text_recognition_batch_size,
        "text_rec_score_thresh": rec_score,
        "text_rec_input_shape": args.text_rec_input_shape,
        "return_word_box": args.return_word_box,
    }
    return {k: v for k, v in mapping.items() if v is not None}


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()

    coords = None
    if args.coord:
        try:
            parts = [int(p.strip()) for p in args.coord.split(",")]
            if len(parts) != 4:
                raise ValueError("Coordinates must consist of 4 integers: x,y,w,h")
            coords = tuple(parts)
        except Exception as e:
            parser.error(f"Invalid format for --coord: {e}. Please use x,y,w,h format.")

    paddle_kwargs = _cli_to_paddle_kwargs(args)

    try:
        res = run_ocr(
            image_path=args.image,
            coords=coords,
            save_crop_path=args.save_crop,
            save_markdown_path=args.save_markdown,
            device=args.device,
            engine=args.engine,
            api_key=args.api_key,
            base_url=args.base_url,
            model_name=args.model_name,
            **paddle_kwargs,
        )
        print("\n=== OCR Scanned Result ===")
        print(res)
    except Exception as e:
        print(f"[OCR] Execution error: {e}")
        raise SystemExit(1) from e
