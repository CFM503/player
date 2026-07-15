# -*- coding: utf-8 -*-
"""
ocr10.py — 带气作业票勾选格（√ / × / \\ / 空白）交互式标注与训练工作台

专门服务 ocr5.py 的 25×5 确认格分类，不训练文字 OCR（文字请用 ocr9.py）。

功能
----
1. 即时预览：对齐图上画出 25 行 × 5 列格子，显示 ocr5 预测标签与特征。
2. 逐格校对：改成真值（对号/叉号/斜杠/空白）→ 入库裁剪图 + 标签。
3. 训练：
   - 规则参数搜索（ink 阈值、叉号端点、斜杠 RMS 等）最大化标注准确率；
   - 可选 sklearn 特征分类器（若已安装 scikit-learn）。
4. 导出 active 模型/参数，供 ocr5.classify_mark 自动加载。
5. 纠错记忆：同位置格子哈希 → 真值，预览立刻覆盖。

启动
----
  python ocr10.py -h
  python ocr10.py
  python ocr10.py --port 8503
  streamlit run ocr10.py --server.port 8503
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import pickle
import random
import re
import shutil
import subprocess
import sys
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
_ENV_WS = os.environ.get("OCR10_WORKSPACE", "").strip()
WS = Path(_ENV_WS).expanduser().resolve() if _ENV_WS else (ROOT / "ocr_mark_workspace")

DIR_RAW = WS / "raw"
DIR_CELLS = WS / "cells"
DIR_MEMORY = WS / "memory"
DIR_MODELS = WS / "models"
DIR_RUNS = WS / "runs"
LABELS_PATH = WS / "labels.jsonl"
MEMORY_PATH = DIR_MEMORY / "corrections.json"
WS_CONFIG_PATH = WS / "config.json"
ACTIVE_MODEL_PATH = DIR_MODELS / "active_mark_model.pkl"
ACTIVE_PARAMS_PATH = DIR_MODELS / "active_mark_params.json"

# 与 ocr5 一致的四类标签
LABELS = ("check", "cross", "slash", "blank")  # check=对号✓=stroke
LABEL_CN = {
    "check": "对号✓",
    "cross": "叉号×",
    "slash": "斜杠\\",
    "blank": "空白-",
}
LABEL_COLOR_BGR = {
    "check": (0, 200, 0),      # 绿
    "cross": (0, 0, 220),      # 红
    "slash": (255, 128, 0),    # 蓝橙
    "blank": (160, 160, 160),  # 灰
    "wrong": (0, 255, 255),    # 黄：预测≠真值
}
# Web 展示用（与预览框一致：绿✓ 红× 蓝\ 灰-）
LABEL_COLOR_HEX = {
    "check": "#16a34a",
    "cross": "#dc2626",
    "slash": "#2563eb",
    "blank": "#6b7280",
}

ROLES = ["作业人", "施工方现场负责人", "监理", "监护人", "带气现场负责人"]
X_BOUNDS = [675, 715, 791, 829, 890, 951]
N_ROWS = 25
N_COLS = 5


def _ensure_dir(p: Path) -> None:
    if p.is_dir():
        return
    if p.exists() and not p.is_dir():
        p.rename(p.with_suffix(p.suffix + f".bak_{uuid.uuid4().hex[:6]}"))
    p.mkdir(parents=True, exist_ok=True)


def ensure_workspace() -> None:
    WS.mkdir(parents=True, exist_ok=True)
    for p in (
        DIR_RAW,
        DIR_CELLS / "check",
        DIR_CELLS / "cross",
        DIR_CELLS / "slash",
        DIR_CELLS / "blank",
        DIR_MEMORY,
        DIR_MODELS,
        DIR_RUNS,
    ):
        _ensure_dir(p)
    if not LABELS_PATH.exists():
        LABELS_PATH.write_text("", encoding="utf-8")
    if not MEMORY_PATH.exists():
        MEMORY_PATH.write_text("{}", encoding="utf-8")
    if not WS_CONFIG_PATH.exists():
        WS_CONFIG_PATH.write_text(
            json.dumps(default_ws_config(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def default_ws_config() -> Dict[str, Any]:
    return {
        "ink_ratio_thresh": 0.008,
        "min_component_area": 12,
        "inset": 0,
        "cross_endpoint_min": 3,
        "cross_endpoint_max": 5,
        "cross_min_spur_dist": 3,
        "slash_line_rms": 1.2,
        "remove_table_lines": True,
        "show_pred_on_cell": True,
        "auto_memory_apply": True,
    }


def load_ws_config() -> Dict[str, Any]:
    ensure_workspace()
    try:
        cfg = json.loads(WS_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    base = default_ws_config()
    base.update({k: v for k, v in cfg.items() if v is not None})
    return base


def save_ws_config(cfg: Dict[str, Any]) -> None:
    WS.mkdir(parents=True, exist_ok=True)
    WS_CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_ocr10_widget_keys() -> None:
    try:
        import streamlit as st
    except Exception:
        return
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("ocr10_") and re.search(r"_g\d+$", k):
            del st.session_state[k]


def _seed_ocr10_widget_defaults(ug: int, d: Dict[str, Any] | None = None) -> None:
    """有 key 的控件以 session_state 为准；重置时必须先写入默认再渲染。"""
    try:
        import streamlit as st
    except Exception:
        return
    d = d or default_ws_config()

    def sk(name: str) -> str:
        return f"ocr10_{name}_g{ug}"

    st.session_state[sk("auto_live")] = True
    st.session_state[sk("ink")] = float(d.get("ink_ratio_thresh", 0.008))
    st.session_state[sk("mca")] = int(d.get("min_component_area", 12))
    st.session_state[sk("slash_rms")] = float(d.get("slash_line_rms", 1.2))
    st.session_state[sk("spur")] = int(d.get("cross_min_spur_dist", 3))
    st.session_state[sk("ep_min")] = int(d.get("cross_endpoint_min", 3))
    st.session_state[sk("ep_max")] = int(d.get("cross_endpoint_max", 5))
    st.session_state[sk("rm_lines")] = bool(d.get("remove_table_lines", True))
    st.session_state[sk("auto_memory")] = bool(d.get("auto_memory_apply", True))


def _on_reset_ocr10_defaults() -> None:
    import streamlit as st

    d = default_ws_config()
    save_ws_config(d)
    _clear_ocr10_widget_keys()
    new_ug = int(st.session_state.get("ocr10_ui_gen", 0)) + 1
    st.session_state["ocr10_ui_gen"] = new_ug
    _seed_ocr10_widget_defaults(new_ug, d)
    st.session_state["ocr10_force_refresh"] = True
    st.session_state.pop("ocr10_param_sig", None)
    st.session_state["ocr10_reset_flash"] = (
        "已恢复默认参数："
        f"ink={d['ink_ratio_thresh']}, mca={d['min_component_area']}, "
        f"slash_rms={d['slash_line_rms']}, spur={d['cross_min_spur_dist']}"
    )


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def short_id() -> str:
    return uuid.uuid4().hex[:12]


def safe_name(name: str) -> str:
    import re
    name = re.sub(r"[^\w\u4e00-\u9fa5.\-]+", "_", name)
    return name[:80] or "img"


# ---------------------------------------------------------------------------
# 图像 IO
# ---------------------------------------------------------------------------

def load_bgr(path: str):
    import cv2
    import numpy as np

    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"无法读取: {path}")
    return img


def save_bgr(path: Path, img) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise RuntimeError(f"编码失败: {path}")
    path.write_bytes(buf.tobytes())


def bgr_to_rgb(img):
    import cv2
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def cell_phash(cell_gray) -> str:
    import cv2
    if cell_gray is None or cell_gray.size == 0:
        return ""
    small = cv2.resize(cell_gray, (24, 24), interpolation=cv2.INTER_AREA)
    return hashlib.md5(small.tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# ocr5 对接
# ---------------------------------------------------------------------------

def _import_ocr5():
    """导入 ocr5，压低其 DEBUG 日志。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import ocr5
    ocr5.logger.setLevel(logging.WARNING)
    return ocr5


def classify_with_params(cell_gray, cfg: Dict[str, Any]) -> Tuple[str, dict]:
    """
    用可调参数调用 ocr5.classify_mark，并映射 stroke→check。
    若存在 active 特征分类器，优先用分类器（规则特征）。
    """
    ocr5 = _import_ocr5()
    ink = float(cfg.get("ink_ratio_thresh", 0.008))
    mca = int(cfg.get("min_component_area", 12))
    inset = int(cfg.get("inset", 0))

    # 先跑规则拿 debug 特征
    label, dbg = ocr5.classify_mark(
        cell_gray, inset=inset, ink_ratio_thresh=ink, min_component_area=mca,
    )
    # 覆盖斜杠阈值：ocr5 内部写死 1.2，此处对 stroke 用 cfg 重判
    label = _refine_label_with_cfg(label, dbg, cell_gray, cfg, ocr5)

    # 可选 ML 覆盖
    clf_path = ACTIVE_MODEL_PATH
    if clf_path.exists():
        try:
            feat = features_from_debug(dbg, cell_gray)
            pred = predict_with_model(clf_path, feat)
            if pred in LABELS:
                dbg = dict(dbg or {})
                dbg["ml_pred"] = pred
                dbg["rule_pred"] = _map_ocr5_label(label)
                label = pred
                return label, dbg
        except Exception:
            pass

    return _map_ocr5_label(label), dbg


def _map_ocr5_label(label: str) -> str:
    if label == "stroke":
        return "check"
    if label in LABELS:
        return label
    return "blank"


def _refine_label_with_cfg(label: str, dbg: dict, cell_gray, cfg: Dict[str, Any], ocr5) -> str:
    """用侧栏参数微调 cross / slash 判定（在 ocr5 结果上再判一层）。"""
    dbg = dbg or {}
    ink = float(dbg.get("ink_ratio") or 0)
    if ink < float(cfg.get("ink_ratio_thresh", 0.008)):
        return "blank"

    n_branch = int(dbg.get("n_branch_px") or 0)
    n_endpoint = int(dbg.get("n_endpoint") or 0)
    n_skel_cc = int(dbg.get("n_skel_components") or 0)
    min_spur = float(dbg.get("min_spur_dist") or 999)
    ep_min = int(cfg.get("cross_endpoint_min", 3))
    ep_max = int(cfg.get("cross_endpoint_max", 5))
    spur_th = float(cfg.get("cross_min_spur_dist", 3))

    is_cross = (
        n_branch > 0
        and ep_min <= n_endpoint <= ep_max
        and n_skel_cc == 1
        and min_spur > spur_th
    )
    if is_cross:
        return "cross"

    # slash vs check
    line_rms = dbg.get("line_rms")
    if line_rms is None and n_endpoint == 2 and n_branch == 0:
        # 再算一次 RMS（ocr5 仅在 slash 路径写入）
        line_rms = _compute_line_rms(cell_gray, cfg, ocr5)
        dbg["line_rms"] = line_rms
    rms_th = float(cfg.get("slash_line_rms", 1.2))
    if line_rms is not None and line_rms < rms_th and n_endpoint == 2 and n_branch == 0:
        return "slash"
    if label in ("stroke", "slash", "check"):
        return "slash" if (line_rms is not None and line_rms < rms_th) else "check"
    return label if label in ("cross", "blank", "slash", "stroke") else "blank"


def _compute_line_rms(cell_gray, cfg, ocr5) -> Optional[float]:
    import cv2
    import numpy as np
    from skimage.morphology import skeletonize
    from scipy.ndimage import label as cc_label

    inset = int(cfg.get("inset", 0))
    mca = int(cfg.get("min_component_area", 12))
    h, w = cell_gray.shape[:2]
    y0, y1 = inset, max(inset + 1, h - inset)
    x0, x1 = inset, max(inset + 1, w - inset)
    roi = cell_gray[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    inv = 255 - roi
    _, bw = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    labeled, n = cc_label(bw > 0)
    clean = np.zeros_like(bw > 0)
    for i in range(1, n + 1):
        if (labeled == i).sum() >= mca:
            clean |= (labeled == i)
    if clean.sum() < 4:
        return None
    skel = skeletonize(clean)
    coords = np.argwhere(skel)
    if len(coords) < 4:
        return None
    ys = coords[:, 0].astype(np.float64)
    xs = coords[:, 1].astype(np.float64)
    i_min, i_max = int(np.argmin(ys)), int(np.argmax(ys))
    p1 = coords[i_min].astype(np.float64)
    p2 = coords[i_max].astype(np.float64)
    if abs(p2[0] - p1[0]) < 2 and abs(p2[1] - p1[1]) < 2:
        i_min, i_max = int(np.argmin(xs)), int(np.argmax(xs))
        p1 = coords[i_min].astype(np.float64)
        p2 = coords[i_max].astype(np.float64)
    seg = p2 - p1
    seg_len = float(np.linalg.norm(seg))
    if seg_len < 4:
        return None
    cross = np.abs((xs - p1[1]) * seg[0] - (ys - p1[0]) * seg[1])
    return float(np.sqrt(np.mean((cross / seg_len) ** 2)))


def extract_grid_cells(img_bgr, cfg: Dict[str, Any]) -> Tuple[List[dict], Any, List[int]]:
    """
    切 25×5 格子，返回 cell 列表、灰度图、y_lines。
    每 cell: row, col, role, x1,y1,x2,y2, gray, pred, debug

    注意：水平网格线必须在「未去表格线」的图上检测；去线后只用于格子内像素分类。
    """
    import cv2

    ocr5 = _import_ocr5()
    h0, w0 = img_bgr.shape[:2]

    # 1) 在原图（含表格线）上检 26 条水平线 + 缩放 x 边界
    gray_src = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    y_lines = ocr5.get_y_lines(gray_src)
    x_bounds = ocr5.get_x_bounds(w0) if hasattr(ocr5, "get_x_bounds") else [
        int(round(x * w0 / 1052.0)) for x in X_BOUNDS
    ]

    # 2) 去表格线后的灰度：仅用于 classify_mark
    work = img_bgr
    if cfg.get("remove_table_lines", True):
        try:
            from ocr7 import remove_table_lines
            work, _ = remove_table_lines(img_bgr, strength=1)
        except Exception:
            work = img_bgr
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

    cells = []
    for r in range(N_ROWS):
        y1, y2 = y_lines[r], y_lines[r + 1]
        for c in range(N_COLS):
            pad_x = min(6, (x_bounds[c + 1] - x_bounds[c]) // 3)
            pad_y = min(3, (y2 - y1) // 3)
            x1 = x_bounds[c] + pad_x
            x2 = x_bounds[c + 1] - pad_x
            cy1 = y1 + pad_y
            cy2 = y2 - pad_y
            # 边界保护
            cy1, cy2 = max(0, cy1), min(gray.shape[0], cy2)
            x1, x2 = max(0, x1), min(gray.shape[1], x2)
            cell_gray = gray[cy1:cy2, x1:x2]
            pred, dbg = classify_with_params(cell_gray, cfg)
            if cfg.get("auto_memory_apply", True):
                h = cell_phash(cell_gray)
                mt = memory_get(h)
                if mt in LABELS:
                    dbg = dict(dbg or {})
                    dbg["memory"] = mt
                    pred = mt
            cells.append({
                "row": r + 1,
                "col": c + 1,
                "role": ROLES[c],
                "x1": x1, "y1": cy1, "x2": x2, "y2": cy2,
                "pred": pred,
                "debug": dbg or {},
                "phash": cell_phash(cell_gray),
            })
    return cells, gray, y_lines


def draw_grid(img_bgr, cells: List[dict], highlight: Optional[Tuple[int, int]] = None, gt_map: Optional[dict] = None):
    import cv2

    vis = img_bgr.copy()
    for cell in cells:
        key = (cell["row"], cell["col"])
        pred = cell["pred"]
        gt = (gt_map or {}).get(key)
        if gt and gt != pred:
            color = LABEL_COLOR_BGR["wrong"]
        else:
            color = LABEL_COLOR_BGR.get(pred, (0, 200, 0))
        if highlight == key:
            color = (0, 255, 255)
            thick = 3
        else:
            thick = 2
        cv2.rectangle(vis, (cell["x1"], cell["y1"]), (cell["x2"], cell["y2"]), color, thick)
        # 票面图例：落实√ / 未落实× / 不适用\ / 空白-（斜杠是反斜杠 \，不是 /）
        tag = {"check": "V", "cross": "X", "slash": "\\", "blank": "-"}[pred]
        cv2.putText(
            vis, tag, (cell["x1"] + 2, min(cell["y2"] - 2, cell["y1"] + 14)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA,
        )
    return vis


# ---------------------------------------------------------------------------
# 记忆 / 标签
# ---------------------------------------------------------------------------

def load_memory() -> dict:
    ensure_workspace()
    try:
        return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_memory(mem: dict) -> None:
    MEMORY_PATH.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def memory_put(h: str, label: str) -> None:
    if not h or label not in LABELS:
        return
    mem = load_memory()
    mem[h] = {"label": label, "updated_at": now_iso()}
    save_memory(mem)


def memory_get(h: str) -> Optional[str]:
    item = load_memory().get(h)
    if isinstance(item, dict):
        return item.get("label")
    return None


@dataclass
class MarkSample:
    sample_id: str
    label: str
    source_image: str
    row: int
    col: int
    role: str
    crop_relpath: str
    features: dict
    pred_at_save: str
    created_at: str
    used_in_train: bool = False


def append_sample(s: MarkSample) -> None:
    ensure_workspace()
    with LABELS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")


def load_samples() -> List[MarkSample]:
    ensure_workspace()
    rows = []
    if not LABELS_PATH.exists():
        return rows
    for line in LABELS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            rows.append(MarkSample(**{k: d[k] for k in MarkSample.__dataclass_fields__ if k in d}))
        except Exception:
            continue
    return rows


def rewrite_samples(rows: List[MarkSample]) -> None:
    with LABELS_PATH.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def save_cell_sample(
    img_bgr, cell: dict, label: str, source_image: str, cfg: Dict[str, Any],
) -> MarkSample:
    import cv2

    if label not in LABELS:
        raise ValueError(f"非法标签: {label}")
    x1, y1, x2, y2 = cell["x1"], cell["y1"], cell["x2"], cell["y2"]
    # 从当前预览用的图裁（与分类一致：可含去表格线）
    work = img_bgr
    if cfg.get("remove_table_lines", True):
        try:
            from ocr7 import remove_table_lines
            work, _ = remove_table_lines(img_bgr, strength=1)
        except Exception:
            work = img_bgr
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    crop = gray[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError("裁剪为空")

    sid = short_id()
    rel = f"cells/{label}/{sid}.png"
    # 存 BGR 便于预览
    crop_bgr = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    save_bgr(WS / rel, crop_bgr)

    pred, dbg = classify_with_params(crop, cfg)
    memory_put(cell_phash(crop), label)

    s = MarkSample(
        sample_id=sid,
        label=label,
        source_image=source_image,
        row=int(cell["row"]),
        col=int(cell["col"]),
        role=cell["role"],
        crop_relpath=rel,
        features=features_from_debug(dbg, crop),
        pred_at_save=pred,
        created_at=now_iso(),
        used_in_train=False,
    )
    append_sample(s)
    return s


# ---------------------------------------------------------------------------
# 特征 / 训练
# ---------------------------------------------------------------------------

FEATURE_KEYS = [
    "ink_ratio", "n_branch_px", "n_endpoint", "n_skel_px",
    "n_skel_components", "min_spur_dist", "line_rms", "aspect", "fill_area",
]


def features_from_debug(dbg: dict, cell_gray) -> dict:
    import numpy as np
    dbg = dbg or {}
    h, w = cell_gray.shape[:2] if cell_gray is not None and cell_gray.size else (1, 1)
    feat = {
        "ink_ratio": float(dbg.get("ink_ratio") or 0),
        "n_branch_px": float(dbg.get("n_branch_px") or 0),
        "n_endpoint": float(dbg.get("n_endpoint") or 0),
        "n_skel_px": float(dbg.get("n_skel_px") or 0),
        "n_skel_components": float(dbg.get("n_skel_components") or 0),
        "min_spur_dist": float(dbg.get("min_spur_dist") if dbg.get("min_spur_dist") is not None else 999),
        "line_rms": float(dbg.get("line_rms") if dbg.get("line_rms") is not None else 99),
        "aspect": float(w) / max(float(h), 1.0),
        "fill_area": float(h * w),
    }
    return feat


def feat_vector(feat: dict) -> List[float]:
    return [float(feat.get(k, 0)) for k in FEATURE_KEYS]


def predict_with_model(path: Path, feat: dict) -> str:
    with path.open("rb") as f:
        obj = pickle.load(f)
    clf = obj["clf"]
    keys = obj.get("feature_keys", FEATURE_KEYS)
    x = [[float(feat.get(k, 0)) for k in keys]]
    pred = clf.predict(x)[0]
    return str(pred)


def evaluate_rules_on_samples(samples: List[MarkSample], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """用当前规则对已存裁剪图重分类，算准确率。"""
    import cv2
    import numpy as np

    if not samples:
        return {"n": 0, "acc": None, "by_label": {}}
    ok = 0
    by = {lb: {"n": 0, "ok": 0} for lb in LABELS}
    confusions = {}
    for s in samples:
        path = WS / s.crop_relpath
        if not path.exists():
            continue
        img = load_bgr(str(path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        # 评测规则时不用 ML 覆盖：临时改名
        bak = None
        if ACTIVE_MODEL_PATH.exists():
            bak = ACTIVE_MODEL_PATH.with_suffix(".pkl.bak_eval")
            try:
                ACTIVE_MODEL_PATH.rename(bak)
            except Exception:
                bak = None
        try:
            pred, _ = classify_with_params(gray, {**cfg, "auto_memory_apply": False})
        finally:
            if bak and bak.exists():
                try:
                    bak.rename(ACTIVE_MODEL_PATH)
                except Exception:
                    pass
        # 上面仍可能加载 ML；强制纯规则：
        pred, _ = _rule_only_predict(gray, cfg)
        by[s.label]["n"] += 1
        if pred == s.label:
            ok += 1
            by[s.label]["ok"] += 1
        confusions[f"{s.label}->{pred}"] = confusions.get(f"{s.label}->{pred}", 0) + 1
    n = sum(v["n"] for v in by.values())
    return {
        "n": n,
        "acc": ok / n if n else None,
        "by_label": {k: (v["ok"] / v["n"] if v["n"] else None) for k, v in by.items()},
        "confusion": confusions,
    }


def _rule_only_predict(cell_gray, cfg: Dict[str, Any]) -> Tuple[str, dict]:
    ocr5 = _import_ocr5()
    label, dbg = ocr5.classify_mark(
        cell_gray,
        inset=int(cfg.get("inset", 0)),
        ink_ratio_thresh=float(cfg.get("ink_ratio_thresh", 0.008)),
        min_component_area=int(cfg.get("min_component_area", 12)),
    )
    label = _refine_label_with_cfg(label, dbg, cell_gray, cfg, ocr5)
    return _map_ocr5_label(label), dbg


def train_rule_search(samples: List[MarkSample], base_cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    """网格搜索关键阈值，最大化标注准确率。"""
    if len(samples) < 4:
        raise ValueError("样本太少，至少 4 条再搜索参数")

    best_cfg = dict(base_cfg)
    best_acc = -1.0

    ink_grid = [0.004, 0.006, 0.008, 0.01, 0.012, 0.015]
    mca_grid = [8, 10, 12, 15, 18]
    rms_grid = [0.8, 1.0, 1.2, 1.5, 2.0]
    spur_grid = [2, 3, 4, 5]

    # 随机/笛卡尔子集，避免爆炸
    candidates = []
    for ink in ink_grid:
        for mca in mca_grid:
            for rms in rms_grid:
                for spur in spur_grid:
                    candidates.append((ink, mca, rms, spur))
    random.shuffle(candidates)
    candidates = candidates[:80]  # 上限

    for ink, mca, rms, spur in candidates:
        trial = dict(base_cfg)
        trial["ink_ratio_thresh"] = ink
        trial["min_component_area"] = mca
        trial["slash_line_rms"] = rms
        trial["cross_min_spur_dist"] = spur
        # 快速评测
        ok = n = 0
        import cv2
        for s in samples:
            path = WS / s.crop_relpath
            if not path.exists():
                continue
            img = load_bgr(str(path))
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            pred, _ = _rule_only_predict(gray, trial)
            n += 1
            if pred == s.label:
                ok += 1
        if n == 0:
            continue
        acc = ok / n
        if acc > best_acc:
            best_acc = acc
            best_cfg = trial

    return best_cfg, best_acc


def train_sklearn_clf(samples: List[MarkSample]) -> Tuple[Any, float, str]:
    """训练随机森林等特征分类器。"""
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import cross_val_score
        import numpy as np
    except ImportError:
        raise RuntimeError("未安装 scikit-learn，请: pip install scikit-learn")

    X, y = [], []
    for s in samples:
        path = WS / s.crop_relpath
        if not path.exists():
            continue
        import cv2
        img = load_bgr(str(path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        _, dbg = _rule_only_predict(gray, load_ws_config())
        feat = features_from_debug(dbg, gray)
        X.append(feat_vector(feat))
        y.append(s.label)
    if len(X) < 8:
        raise ValueError("有效样本不足 8 条，无法稳定训练分类器")

    import numpy as np
    X = np.array(X, dtype=np.float64)
    y = np.array(y)
    clf = RandomForestClassifier(n_estimators=80, max_depth=8, random_state=42, class_weight="balanced")
    if len(set(y.tolist())) >= 2 and len(X) >= 10:
        scores = cross_val_score(clf, X, y, cv=min(5, len(X)))
        cv_acc = float(scores.mean())
    else:
        cv_acc = float("nan")
    clf.fit(X, y)
    train_acc = float((clf.predict(X) == y).mean())
    msg = f"train_acc={train_acc:.3f}"
    if cv_acc == cv_acc:
        msg += f", cv_acc≈{cv_acc:.3f}"
    return clf, train_acc, msg


def export_active(cfg: Dict[str, Any], clf=None, note: str = "") -> Path:
    """写出 ocr5 可加载的 active 参数/模型。"""
    ensure_workspace()
    params = {
        "version": 1,
        "updated_at": now_iso(),
        "note": note,
        "ink_ratio_thresh": float(cfg.get("ink_ratio_thresh", 0.008)),
        "min_component_area": int(cfg.get("min_component_area", 12)),
        "inset": int(cfg.get("inset", 0)),
        "cross_endpoint_min": int(cfg.get("cross_endpoint_min", 3)),
        "cross_endpoint_max": int(cfg.get("cross_endpoint_max", 5)),
        "cross_min_spur_dist": float(cfg.get("cross_min_spur_dist", 3)),
        "slash_line_rms": float(cfg.get("slash_line_rms", 1.2)),
        "has_sklearn_model": clf is not None,
    }
    ACTIVE_PARAMS_PATH.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
    # 同步到项目根，方便 ocr5 默认发现
    root_params = ROOT / "ocr5_mark_params.json"
    root_params.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

    if clf is not None:
        with ACTIVE_MODEL_PATH.open("wb") as f:
            pickle.dump({"clf": clf, "feature_keys": FEATURE_KEYS, "labels": list(LABELS)}, f)
        shutil.copy2(ACTIVE_MODEL_PATH, ROOT / "ocr5_mark_model.pkl")
    return ACTIVE_PARAMS_PATH


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def render_app() -> None:
    import streamlit as st
    import cv2

    ensure_workspace()
    # 作为主应用多页嵌入时，frontend 已 set_page_config，此处不可再调
    try:
        st.set_page_config(page_title="OCR5 勾选训练", page_icon="☑️", layout="wide")
    except Exception:
        pass
    st.title("☑️ OCR5 勾选训练 · ocr5.py")
    st.caption(
        "对应生产 **ocr5.py** 的 25×5 确认格 √/×/\\ /空白 · 即时预览 · 逐格入库 · 规则/特征训练 · 导出给 ocr5 · "
        f"工作区 `{WS.name}/`（本页即原 ocr10 工作台）"
    )

    cfg = load_ws_config()
    _defaults = default_ws_config()

    # Streamlit 会缓存滑标旧值：重置时递增 ui_gen 换 key，强制用默认 value 重建
    if "ocr10_ui_gen" not in st.session_state:
        st.session_state["ocr10_ui_gen"] = 0
    _ug = int(st.session_state["ocr10_ui_gen"])

    def _k(name: str) -> str:
        return f"ocr10_{name}_g{_ug}"

    with st.sidebar:
        st.header("⚙️ 分类参数（规则）")
        auto_live = st.checkbox(
            "滑标/参数变更时自动刷新预览",
            value=True,
            help="已选图时，拖动阈值会立刻重跑 25×5 分类并更新色框",
            key=_k("auto_live"),
        )
        cfg["ink_ratio_thresh"] = st.slider(
            "空白 ink 阈值", 0.001, 0.05,
            float(cfg.get("ink_ratio_thresh", _defaults["ink_ratio_thresh"])), 0.001,
            help=f"默认 {_defaults['ink_ratio_thresh']}：低于此视为空白",
            key=_k("ink"),
        )
        cfg["min_component_area"] = st.slider(
            "最小连通域", 4, 40,
            int(cfg.get("min_component_area", _defaults["min_component_area"])), 1,
            help=f"默认 {_defaults['min_component_area']}",
            key=_k("mca"),
        )
        cfg["slash_line_rms"] = st.slider(
            "斜杠直线 RMS 上限", 0.3, 3.0,
            float(cfg.get("slash_line_rms", _defaults["slash_line_rms"])), 0.1,
            help=f"默认 {_defaults['slash_line_rms']}：更小→更严才判斜杠",
            key=_k("slash_rms"),
        )
        cfg["cross_min_spur_dist"] = st.slider(
            "叉号 min_spur_dist", 1, 10,
            int(cfg.get("cross_min_spur_dist", _defaults["cross_min_spur_dist"])), 1,
            help=f"默认 {_defaults['cross_min_spur_dist']}",
            key=_k("spur"),
        )
        cfg["cross_endpoint_min"] = st.number_input(
            "叉号端点 min", 2, 6, int(cfg.get("cross_endpoint_min", _defaults["cross_endpoint_min"])),
            help=f"默认 {_defaults['cross_endpoint_min']}",
            key=_k("ep_min"),
        )
        cfg["cross_endpoint_max"] = st.number_input(
            "叉号端点 max", 3, 8, int(cfg.get("cross_endpoint_max", _defaults["cross_endpoint_max"])),
            help=f"默认 {_defaults['cross_endpoint_max']}",
            key=_k("ep_max"),
        )
        cfg["remove_table_lines"] = st.checkbox(
            "去表格线后再分类",
            value=bool(cfg.get("remove_table_lines", True)),
            key=_k("rm_lines"),
        )
        cfg["auto_memory_apply"] = st.checkbox(
            "应用纠错记忆",
            value=bool(cfg.get("auto_memory_apply", True)),
            key=_k("auto_memory"),
        )

        if st.button("💾 保存参数", use_container_width=True, key=_k("btn_save")):
            save_ws_config(cfg)
            st.success("已保存到工作区 config.json")

        st.button(
            "↺ 重置为默认参数",
            use_container_width=True,
            type="secondary",
            key=_k("btn_reset"),
            on_click=_on_reset_ocr10_defaults,
        )
        _flash = st.session_state.pop("ocr10_reset_flash", None)
        if _flash:
            st.success(_flash)

        with st.expander("查看默认参数表"):
            st.json(_defaults)

        samples = load_samples()
        st.metric("标注样本", len(samples))
        for lb in LABELS:
            st.caption(f"{LABEL_CN[lb]}: {sum(1 for s in samples if s.label == lb)}")

    tab_prev, tab_data, tab_train, tab_export, tab_help = st.tabs(
        ["📷 预览与逐格训练", "📚 数据集", "🏋️ 训练", "📦 导出到 ocr5", "❓ 帮助"]
    )

    # ---------- 预览 ----------
    with tab_prev:
        c1, c2 = st.columns([1, 1.2])
        with c1:
            st.subheader("1. 选图（须对齐后的带气票）")
            mode = st.radio("来源", ["上传", "raw/", "archives/"], horizontal=True)
            image_path = None
            if mode == "上传":
                up = st.file_uploader("对齐图", type=["jpg", "jpeg", "png", "bmp"])
                if up:
                    name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name(up.name)}"
                    image_path = str(DIR_RAW / name)
                    (DIR_RAW / name).write_bytes(up.getvalue())
            elif mode == "raw/":
                files = sorted(
                    p for p in DIR_RAW.glob("*")
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
                )
                if files:
                    image_path = str(st.selectbox("图片", files, format_func=lambda p: p.name))
                else:
                    st.info("raw/ 为空")
            else:
                arch = ROOT / "archives"
                cands = []
                if arch.exists():
                    for p in arch.rglob("*"):
                        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                            cands.append(p)
                cands = sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)[:150]
                if cands:
                    image_path = str(
                        st.selectbox("archives", cands, format_func=lambda p: str(p.relative_to(ROOT)))
                    )
                else:
                    st.info("无 archives 图片")

            run = st.button("▶️ 运行 / 刷新网格预览", type="primary", use_container_width=True)
            only_wrong = st.checkbox("只列出可能错的（低墨迹/边界特征）", value=False)
            st.caption("提示：侧栏打开「滑标变更时自动刷新预览」后，调参会即时更新色框。")

        param_sig = json.dumps(
            {k: cfg.get(k) for k in (
                "ink_ratio_thresh", "min_component_area", "slash_line_rms",
                "cross_min_spur_dist", "cross_endpoint_min", "cross_endpoint_max",
                "remove_table_lines", "auto_memory_apply", "inset",
            )},
            sort_keys=True,
        )
        prev_sig = st.session_state.get("ocr10_param_sig")
        params_changed = prev_sig is not None and prev_sig != param_sig
        force_refresh = bool(st.session_state.pop("ocr10_force_refresh", False))

        need_run = False
        if image_path:
            path_same = st.session_state.get("ocr10_path") == image_path
            if run or force_refresh:
                need_run = True
            elif st.session_state.get("ocr10_cells") is None or not path_same:
                need_run = True
            elif auto_live and path_same and params_changed:
                need_run = True

        if image_path and need_run:
            try:
                with st.spinner("切格 + 分类中（当前侧栏参数已应用）…"):
                    img = load_bgr(image_path)
                    cells, gray, y_lines = extract_grid_cells(img, cfg)
                    st.session_state["ocr10_path"] = image_path
                    st.session_state["ocr10_cells"] = cells
                    st.session_state["ocr10_shape"] = img.shape[:2]
                    st.session_state["ocr10_param_sig"] = param_sig
            except Exception as e:
                st.error(str(e))
                st.code(traceback.format_exc())
        elif image_path and not need_run:
            st.session_state["ocr10_param_sig"] = param_sig

        cells = st.session_state.get("ocr10_cells") or []
        path_now = st.session_state.get("ocr10_path")

        with c2:
            st.subheader("2. 预览（绿✓ 红× 蓝\\ 灰-  黄=定位）")
            if path_now and cells:
                img = load_bgr(path_now)
                hi = st.session_state.get("ocr10_hi")
                vis = draw_grid(img, cells, highlight=hi)
                cap = f"{Path(path_now).name} · {len(cells)} 格"
                if params_changed and auto_live:
                    cap += " · 参数已即时刷新"
                st.image(bgr_to_rgb(vis), caption=cap, use_container_width=True)
                cnt = {lb: sum(1 for c in cells if c["pred"] == lb) for lb in LABELS}
                st.caption(
                    "预测统计: " + " · ".join(f"{LABEL_CN[k]}={v}" for k, v in cnt.items())
                    + f" · ink={cfg.get('ink_ratio_thresh')} rms={cfg.get('slash_line_rms')}"
                )
            else:
                st.info("请选图并运行预览（或开启自动刷新后拖动滑标）。")

        st.markdown("---")
        st.subheader("3. 逐格校对入库")
        if not cells:
            st.caption("暂无格子。")
        else:
            # 过滤
            view = cells
            if only_wrong:
                view = [
                    c for c in cells
                    if float((c.get("debug") or {}).get("ink_ratio") or 0) < 0.02
                    or (c.get("debug") or {}).get("line_rms") is not None
                ] or cells

            # 分页：默认一页 50 格，可选 25/50/全部 125
            pc1, pc2 = st.columns([1, 2])
            with pc1:
                page_size_opt = st.selectbox(
                    "每页格数",
                    options=[25, 50, 75, 100, 125],
                    index=1,  # 默认 50
                    help="25 行×5 列共 125 格；选 125 可一页看完",
                    key=_k("page_size"),
                )
            page_size = int(page_size_opt)
            n_pages = max(1, (len(view) + page_size - 1) // page_size)
            page_key = _k("page_num")
            # 换「每页格数」后页码可能超出，先钳制
            if page_key in st.session_state:
                try:
                    st.session_state[page_key] = max(
                        1, min(int(st.session_state[page_key]), n_pages)
                    )
                except Exception:
                    st.session_state[page_key] = 1
            with pc2:
                page = st.number_input(
                    f"页码（共 {n_pages} 页 / {len(view)} 格）",
                    min_value=1,
                    max_value=n_pages,
                    value=1,
                    key=page_key,
                )
            chunk = view[(int(page) - 1) * page_size: int(page) * page_size]
            st.caption(
                f"本页显示第 {(int(page)-1)*page_size + 1}–"
                f"{min(int(page)*page_size, len(view))} 格"
            )

            for cell in chunk:
                rid, cid = cell["row"], cell["col"]
                with st.container():
                    cols = st.columns([0.12, 0.28, 0.28, 0.32])
                    with cols[0]:
                        st.markdown(f"**R{rid}C{cid}**")
                        st.caption(cell["role"][:6])
                    with cols[1]:
                        if path_now:
                            img = load_bgr(path_now)
                            crop = img[cell["y1"]:cell["y2"], cell["x1"]:cell["x2"]]
                            if crop.size:
                                st.image(bgr_to_rgb(crop), use_container_width=True)
                    with cols[2]:
                        _pred = cell["pred"]
                        _cn = LABEL_CN.get(_pred, _pred)
                        _hex = LABEL_COLOR_HEX.get(_pred, "#374151")
                        st.markdown(
                            f'预测: <span style="color:{_hex};font-weight:700;'
                            f'font-size:1.1em">{_cn}</span>',
                            unsafe_allow_html=True,
                        )
                        dbg = cell.get("debug") or {}
                        st.caption(
                            f"ink={dbg.get('ink_ratio', '-')} ep={dbg.get('n_endpoint', '-')} "
                            f"br={dbg.get('n_branch_px', '-')} rms={dbg.get('line_rms', '-')}"
                        )
                        default_i = list(LABELS).index(cell["pred"]) if cell["pred"] in LABELS else 0
                        lab = st.selectbox(
                            "真值",
                            options=list(LABELS),
                            format_func=lambda x: LABEL_CN[x],
                            index=default_i,
                            key=f"lab_{rid}_{cid}_{page}",
                        )
                    with cols[3]:
                        if st.button("定位", key=f"hi_{rid}_{cid}_{page}"):
                            st.session_state["ocr10_hi"] = (rid, cid)
                            st.rerun()
                        if st.button("➕ 入库", key=f"add_{rid}_{cid}_{page}", type="primary"):
                            try:
                                img = load_bgr(path_now)
                                s = save_cell_sample(img, cell, lab, path_now, cfg)
                                st.success(f"已入库 {s.sample_id} → {LABEL_CN[lab]}")
                            except Exception as e:
                                st.error(str(e))
                        if st.button("⚡ 入库并导出参数", key=f"ft_{rid}_{cid}_{page}"):
                            try:
                                img = load_bgr(path_now)
                                save_cell_sample(img, cell, lab, path_now, cfg)
                                export_active(cfg, note="single_cell_export")
                                st.success("已入库并导出 active 参数供 ocr5 加载")
                            except Exception as e:
                                st.error(str(e))
                    st.markdown("---")

            if st.button("将当前页预测结果全部入库（慎用）"):
                img = load_bgr(path_now)
                n = 0
                for cell in chunk:
                    key = f"lab_{cell['row']}_{cell['col']}_{page}"
                    lab = st.session_state.get(key, cell["pred"])
                    try:
                        save_cell_sample(img, cell, lab, path_now, cfg)
                        n += 1
                    except Exception:
                        pass
                st.info(f"入库 {n} 格")

    # ---------- 数据 ----------
    with tab_data:
        samples = load_samples()
        if not samples:
            st.info("暂无样本。")
        else:
            import pandas as pd
            st.dataframe(pd.DataFrame([asdict(s) for s in samples]), use_container_width=True, height=400)
            del_id = st.text_input("删除 sample_id")
            if st.button("删除") and del_id.strip():
                keep = []
                for s in samples:
                    if s.sample_id == del_id.strip():
                        p = WS / s.crop_relpath
                        if p.exists():
                            p.unlink()
                    else:
                        keep.append(s)
                rewrite_samples(keep)
                st.success("已删")
                st.rerun()
        if st.button("清空纠错记忆"):
            save_memory({})
            st.warning("已清空")

    # ---------- 训练 ----------
    with tab_train:
        samples = load_samples()
        st.write(f"样本数: **{len(samples)}**")
        if st.button("用当前参数评测标注集（纯规则）"):
            with st.spinner("评测中…"):
                ev = evaluate_rules_on_samples(samples, cfg)
            st.json(ev)

        if st.button("🔍 规则参数网格搜索（推荐）", type="primary"):
            try:
                with st.spinner("搜索中，约数十次评测…"):
                    best, acc = train_rule_search(samples, cfg)
                cfg.update(best)
                save_ws_config(cfg)
                export_active(cfg, note=f"rule_search acc={acc:.4f}")
                st.success(f"最佳准确率 {acc:.3%}，参数已写入 config 与 ocr5_mark_params.json")
                st.json({k: best[k] for k in (
                    "ink_ratio_thresh", "min_component_area", "slash_line_rms", "cross_min_spur_dist"
                )})
            except Exception as e:
                st.error(str(e))

        if st.button("🌲 训练 sklearn 特征分类器"):
            try:
                with st.spinner("训练中…"):
                    clf, acc, msg = train_sklearn_clf(samples)
                export_active(cfg, clf=clf, note=msg)
                # 标记 used
                for s in samples:
                    s.used_in_train = True
                rewrite_samples(samples)
                st.success(f"分类器已导出。{msg}")
            except Exception as e:
                st.error(str(e))

        runs = sorted(DIR_RUNS.glob("*"), reverse=True)[:10] if DIR_RUNS.exists() else []
        for r in runs:
            st.text(r.name)

    # ---------- 导出 ----------
    with tab_export:
        st.subheader("导出给 ocr5 使用")
        st.markdown(
            f"""
训练结果会写入：

- `{ACTIVE_PARAMS_PATH}`
- 项目根 `{ROOT / "ocr5_mark_params.json"}`（ocr5 启动时自动读）
- 若训练了 sklearn：`{ACTIVE_MODEL_PATH}` 与 `{ROOT / "ocr5_mark_model.pkl"}`

`ocr5.classify_mark` 已支持：优先读项目根参数/模型，再走规则。
"""
        )
        if st.button("仅导出当前侧栏参数（不训练）", type="primary"):
            p = export_active(cfg, note="manual_export")
            st.success(f"已导出: {p}")
        if ACTIVE_PARAMS_PATH.exists():
            st.code(ACTIVE_PARAMS_PATH.read_text(encoding="utf-8"))
        if st.button("删除 active 模型（恢复纯规则）"):
            for p in (ACTIVE_MODEL_PATH, ROOT / "ocr5_mark_model.pkl"):
                if p.exists():
                    p.unlink()
            st.warning("已删除 ML 模型文件")

    # ---------- 帮助 ----------
    with tab_help:
        st.markdown(
            """
### 颜色图例
| 框色 | 含义 |
|------|------|
| 绿 | 预测对号 ✓ |
| 红 | 预测叉号 × |
| 蓝/橙 | 预测斜杠 \\\\ |
| 灰 | 预测空白 |
| 黄粗框 | 当前定位格 |

### 推荐流程
1. 选 **archives 对齐图**（1052×1487）→ 运行预览  
2. 对照票面，把错格改成真值 → **入库**  
3. 攒够每类若干样本后 → **规则参数网格搜索**  
4. 可选再训 **sklearn 分类器**  
5. 导出后重新跑 `python ocr5.py -i 对齐图.jpg` 验证  

### 与 ocr9 分工
- **ocr9**：文字 det/rec（姓名、日期…）  
- **ocr10**：勾选格 √×\\\\空白（ocr5）  
"""
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _is_streamlit_script_run() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


_CLI_EPILOG = r"""
示例
----
  python ocr10.py -h
  python ocr10.py
  python ocr10.py --port 8503
  python ocr10.py --port 8503 --browser
  python ocr10.py --host 0.0.0.0 --port 8503
  streamlit run ocr10.py --server.port 8503

功能（Web UI）
--------------
  1. 网格预览
     - 对齐带气票 25×5 确认格，调用 ocr5 拓扑特征分类
     - 颜色：绿✓ / 红× / 蓝斜杠 / 灰空白
  2. 逐格校对入库
     - 真值四选一 → cells/<label>/*.png + labels.jsonl + 纠错记忆
  3. 训练
     - 规则阈值网格搜索（推荐，可直接改进 ocr5）
     - 可选 sklearn 随机森林（特征=骨架拓扑）
  4. 导出
     - ocr5_mark_params.json / ocr5_mark_model.pkl 供 ocr5 自动加载

工作目录
--------
  ocr_mark_workspace/
    raw/  cells/{check,cross,slash,blank}/  labels.jsonl
    memory/  models/  runs/  config.json

与主项目
--------
  ocr5.py  : 生产勾选格识别（会读 ocr5_mark_params.json）
  ocr9.py  : 文字 OCR 训练（本工具不替代）
  agent    : 业务流；勾选结果仍来自 ocr5

依赖
----
  streamlit, opencv-python, numpy, scikit-image, scipy
  可选: scikit-learn（特征分类器）

注意
----
  - 输入须为模板对齐后的带气票（约 1052×1487），否则网格线检测失败
  - 空白必须标 blank，禁止把空白当叉号入库
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocr10.py",
        description=(
            "OCR10 · 勾选格 √/×/\\ /空白 交互式标注与训练工作台（Streamlit）\n"
            "专训 ocr5 的 25×5 确认格分类；即时预览 → 逐格入库 → 规则/特征训练 → 导出给 ocr5。"
        ),
        epilog=_CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8503,
        metavar="PORT",
        help="Streamlit 服务端口（默认: 8503）",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        metavar="ADDR",
        help="监听地址（默认: 127.0.0.1；局域网可用 0.0.0.0）",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="启动时尝试打开系统浏览器（默认 headless 不自动打开）",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        metavar="DIR",
        help="工作区目录（默认: 脚本旁 ocr_mark_workspace/）",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version="ocr10.py (勾选格 √/×/\\ 训练工作台) · 配套 ocr5.py",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.workspace:
        os.environ["OCR10_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())

    ws_show = (
        Path(os.environ["OCR10_WORKSPACE"])
        if os.environ.get("OCR10_WORKSPACE")
        else (ROOT / "ocr_mark_workspace")
    )
    ws_show.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(Path(__file__).resolve()),
        "--server.port", str(args.port),
        "--server.address", str(args.host),
        "--server.headless", "true" if not args.browser else "false",
    ]
    print("OCR10 勾选格训练工作台")
    print("  Starting:", " ".join(cmd))
    print(f"  Workspace: {ws_show}")
    print(f"  Open:      http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{args.port}")
    print("  Help:      python ocr10.py -h")
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    if any(a in ("-h", "--help", "-v", "--version") for a in sys.argv[1:]):
        raise SystemExit(main())
    if _is_streamlit_script_run():
        render_app()
    else:
        raise SystemExit(main())
