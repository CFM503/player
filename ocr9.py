# -*- coding: utf-8 -*-
# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
"""
ocr9.py — 带气作业票 / 通用 OCR 交互式标注与微调工作台

功能概览
--------
1. 即时识别预览：上传或浏览图片，PaddleOCR 画框 + 置信度，可调 det/rec 阈值。
2. 逐项校对入库：对每一检测行修改真值，一键写入训练集（裁剪图 + 标签）。
3. 即时/批量训练：样本入队后可「本条后微调」「用未训练样本微调」；生成 Paddle 兼容 rec 数据。
4. 模型管理：训练产出模型目录、热加载到预览引擎、导出路径给主系统 config。
5. 评测：固定测试集前后对比、字符准确率。
6. 难例挖掘：低置信度优先、导入 archives 对齐图、字符集统计。

启动
----
  streamlit run ocr9.py
  python ocr9.py              # 等价启动 streamlit
  python ocr9.py --port 8502

工作目录（自动创建）
------------------
  ocr_train_workspace/
    raw/                 原始上传图
    crops/train|val|test 行裁剪图
    labels.jsonl         全量标注元数据
    rec/train.txt val.txt test.txt   Paddle rec 列表 (相对路径\\t标签)
    memory/corrections.json  即时纠错记忆（图像哈希→真值，无需 GPU 也能「立刻变准」）
    models/              微调产出与导出说明
    runs/                训练日志与配置快照
    config.json          工作台配置

说明
----
- 勾选格 √×\\ 仍建议用主流程 ocr5；本工具聚焦「文字 det/rec」与手写姓名/编号/日期。
- 真·权重微调依赖本机 Paddle/PaddleX 训练能力；若环境不支持，仍可完整做标注与 rec 数据集导出，
  并使用「纠错记忆」在预览中即时生效。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
_ENV_WS = os.environ.get("OCR9_WORKSPACE", "").strip()
WS = Path(_ENV_WS).expanduser().resolve() if _ENV_WS else (ROOT / "ocr_train_workspace")
DIR_RAW = WS / "raw"
DIR_CROPS = WS / "crops"
DIR_MEMORY = WS / "memory"
DIR_MODELS = WS / "models"
DIR_RUNS = WS / "runs"
DIR_REC = WS / "rec"
LABELS_PATH = WS / "labels.jsonl"
MEMORY_PATH = DIR_MEMORY / "corrections.json"
WS_CONFIG_PATH = WS / "config.json"

SPLITS = ("train", "val", "test")


def _ensure_dir(p: Path) -> None:
    """创建目录；若同名文件占位则改名备份后重建目录。"""
    if p.is_dir():
        return
    if p.exists() and not p.is_dir():
        bak = p.with_suffix(p.suffix + f".bak_{short_id()}")
        p.rename(bak)
    p.mkdir(parents=True, exist_ok=True)


def ensure_workspace() -> None:
    WS.mkdir(parents=True, exist_ok=True)
    for p in (
        DIR_RAW,
        DIR_CROPS / "train",
        DIR_CROPS / "val",
        DIR_CROPS / "test",
        DIR_MEMORY,
        DIR_MODELS,
        DIR_RUNS,
        DIR_REC,
    ):
        _ensure_dir(p)
    if not LABELS_PATH.exists():
        LABELS_PATH.write_text("", encoding="utf-8")
    if not MEMORY_PATH.exists():
        MEMORY_PATH.write_text("{}", encoding="utf-8")
    if not WS_CONFIG_PATH.exists():
        # 禁止调用 save_ws_config（会再进 ensure_workspace 递归）
        WS_CONFIG_PATH.write_text(
            json.dumps(default_ws_config(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def default_ws_config() -> Dict[str, Any]:
    """工作台默认配置；OCR 引擎项与 ocr.DEFAULT_OCR_PARAMS 保持一致。"""
    from ocr import DEFAULT_OCR_PARAMS

    # 生产 ocr.py 默认参数（单源）；device 与 admin 一致默认 gpu
    cfg: Dict[str, Any] = {
        "device": "gpu",
        **dict(DEFAULT_OCR_PARAMS),
        "custom_rec_model_dir": "",
        "custom_det_model_dir": "",
        "val_ratio": 0.1,
        "test_ratio": 0.1,
        "min_samples_for_train": 8,
        "default_epochs": 5,
        "batch_size": 8,
        "learning_rate": 0.0005,
        "hard_score_thresh": 0.75,
        "auto_memory_apply": True,
        "crop_pad_px": 2,
    }
    return cfg


def load_ws_config() -> Dict[str, Any]:
    ensure_workspace()
    try:
        cfg = json.loads(read_text_loose(WS_CONFIG_PATH) or "{}")
    except Exception:
        cfg = {}
    base = default_ws_config()
    base.update({k: v for k, v in cfg.items() if v is not None})
    return base


def save_ws_config(cfg: Dict[str, Any]) -> None:
    WS.mkdir(parents=True, exist_ok=True)
    WS_CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_ocr9_widget_keys() -> None:
    """删除侧栏控件 session_state（仅 ocr9_*_gN，不动 ocr9_boxes / ocr9_ui_gen 等）。"""
    try:
        import streamlit as st
    except Exception:
        return
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("ocr9_") and re.search(r"_g\d+$", k):
            del st.session_state[k]


def _seed_ocr9_widget_defaults(ug: int, d: Dict[str, Any] | None = None) -> None:
    """在控件创建前写入默认值。Streamlit 有 key 时以 session_state 为准，会忽略 value=/index=。"""
    try:
        import streamlit as st
    except Exception:
        return
    d = d or default_ws_config()

    def sk(name: str) -> str:
        return f"ocr9_{name}_g{ug}"

    st.session_state[sk("auto_live")] = True
    st.session_state[sk("device")] = d.get("device") or "gpu"
    st.session_state[sk("box_thresh")] = float(d.get("text_det_box_thresh", 0.2))
    st.session_state[sk("det_thresh")] = float(d.get("text_det_thresh", 0.3))
    st.session_state[sk("unclip")] = float(d.get("text_det_unclip_ratio", 1.5))
    st.session_state[sk("rec_score")] = float(d.get("text_rec_score_thresh", 0.1))
    st.session_state[sk("hard_score")] = float(d.get("hard_score_thresh", 0.75))
    st.session_state[sk("auto_memory")] = bool(d.get("auto_memory_apply", True))
    st.session_state[sk("doc_ori")] = bool(d.get("use_doc_orientation_classify", True))
    st.session_state[sk("textline_ori")] = bool(d.get("use_textline_orientation", True))
    st.session_state[sk("min_train")] = int(d.get("min_samples_for_train", 8))
    st.session_state[sk("epochs")] = int(d.get("default_epochs", 5))
    st.session_state[sk("val_ratio")] = float(d.get("val_ratio", 0.1))
    st.session_state[sk("test_ratio")] = float(d.get("test_ratio", 0.1))
    st.session_state[sk("rec_dir")] = d.get("custom_rec_model_dir") or ""
    st.session_state[sk("det_dir")] = d.get("custom_det_model_dir") or ""


def _on_reset_ocr9_defaults() -> None:
    """按钮 on_click：在本轮主脚本渲染控件之前执行，确保滑标真正回到默认。"""
    import streamlit as st

    d = default_ws_config()
    save_ws_config(d)
    _clear_ocr9_widget_keys()
    new_ug = int(st.session_state.get("ocr9_ui_gen", 0)) + 1
    st.session_state["ocr9_ui_gen"] = new_ug
    _seed_ocr9_widget_defaults(new_ug, d)
    st.session_state["ocr9_force_refresh"] = True
    st.session_state.pop("ocr9_param_sig", None)
    try:
        get_ocr_engine(d, force_reload=True)
    except Exception:
        pass
    st.session_state["ocr9_reset_flash"] = (
        "已恢复默认参数（与 ocr.py DEFAULT_OCR_PARAMS 一致）："
        f"box_thresh={d['text_det_box_thresh']}, "
        f"det_thresh={d['text_det_thresh']}, "
        f"unclip={d.get('text_det_unclip_ratio', 1.5)}, "
        f"rec_score={d['text_rec_score_thresh']}, "
        f"doc_ori={d.get('use_doc_orientation_classify', True)}"
    )


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class OcrBox:
    """单条检测结果。"""
    box_id: str
    text: str  # 始终保留引擎原始 OCR，入库文本映射依赖此字段
    score: float
    # 四点或 xyxy
    xs: List[int]
    ys: List[int]
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    corrected: str = ""  # 纠错后展示/入库真值
    text_raw: str = ""  # 原始 OCR 备份（与 text 同步，防被改写）
    in_dataset: bool = False
    sample_id: str = ""

    def __post_init__(self) -> None:
        if self.xs and self.ys:
            self.x = int(min(self.xs))
            self.y = int(min(self.ys))
            self.w = max(1, int(max(self.xs) - self.x))
            self.h = max(1, int(max(self.ys) - self.y))
        if not self.text_raw:
            self.text_raw = self.text
        if not self.corrected:
            self.corrected = self.text


@dataclass
class LabelRecord:
    sample_id: str
    split: str
    source_image: str
    crop_relpath: str
    text: str
    score: float
    box: List[int]  # x,y,w,h
    created_at: str
    trained: bool = False
    tags: List[str] = field(default_factory=list)
    note: str = ""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def short_id() -> str:
    return uuid.uuid4().hex[:12]


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w\u4e00-\u9fa5.\-]+", "_", name)
    return name[:80] or "img"


def phash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:24]


def read_text_loose(path: Path, max_chars: int | None = None) -> str:
    """读文本：兼容 utf-8 / gbk，永不因编码抛错（训练日志/配置在 Windows 上常非 utf-8）。"""
    try:
        raw = Path(path).read_bytes()
    except Exception:
        return ""
    text = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "cp936", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    if max_chars is not None and max_chars >= 0:
        return text[:max_chars]
    return text


def crop_phash(img_bgr, x: int, y: int, w: int, h: int) -> str:
    import cv2
    import numpy as np

    H, W = img_bgr.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(W, x + w), min(H, y + h)
    crop = img_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return ""
    small = cv2.resize(crop, (32, 16), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if len(small.shape) == 3 else small
    return hashlib.md5(gray.tobytes()).hexdigest()


def load_bgr(path: str):
    import cv2
    import numpy as np

    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"无法读取图像: {path}")
    return img


def save_bgr(path: Path, img) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise RuntimeError(f"编码失败: {path}")
    path.write_bytes(buf.tobytes())


def draw_boxes(img_bgr, boxes: List[OcrBox], highlight: Optional[str] = None, hard_thresh: float = 0.75):
    return _draw_boxes_with_thresh(img_bgr, boxes, hard_thresh, highlight=highlight)


def _draw_boxes_with_thresh(img_bgr, boxes: List[OcrBox], hard_thresh: float, highlight: Optional[str] = None):
    import cv2

    vis = img_bgr.copy()
    for b in boxes:
        color = (0, 165, 255) if b.box_id == highlight else (0, 200, 0)
        if b.score < hard_thresh:
            color = (0, 0, 255) if b.box_id != highlight else (255, 128, 0)
        pt1, pt2 = (b.x, b.y), (b.x + b.w, b.y + b.h)
        cv2.rectangle(vis, pt1, pt2, color, 2)
        label = f"{b.score:.2f}|{(b.corrected or b.text)[:12]}"
        cv2.putText(
            vis, label, (b.x, max(14, b.y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA,
        )
    return vis


def bgr_to_rgb(img):
    import cv2
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


# ---------------------------------------------------------------------------
# 标注 JSONL / rec 列表
# ---------------------------------------------------------------------------

def append_label(rec: LabelRecord) -> None:
    ensure_workspace()
    with LABELS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")


def load_all_labels() -> List[LabelRecord]:
    ensure_workspace()
    rows: List[LabelRecord] = []
    if not LABELS_PATH.exists():
        return rows
    for line in read_text_loose(LABELS_PATH).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            rows.append(LabelRecord(**{k: d[k] for k in LabelRecord.__dataclass_fields__ if k in d}))
        except Exception:
            continue
    return rows


def rewrite_labels(rows: List[LabelRecord]) -> None:
    ensure_workspace()
    with LABELS_PATH.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def rebuild_rec_lists() -> Dict[str, int]:
    """从 labels.jsonl 重建 train/val/test 列表（Paddle rec 格式：相对路径\\t标签）。"""
    ensure_workspace()
    counts = {s: 0 for s in SPLITS}
    buckets: Dict[str, List[str]] = {s: [] for s in SPLITS}
    for r in load_all_labels():
        split = r.split if r.split in buckets else "train"
        # 路径相对 rec/ 目录，便于官方工具读取
        rel = Path("..") / "crops" / split / Path(r.crop_relpath).name
        # 更稳：使用相对 workspace 的 crops 路径写在 rec/*.txt，训练脚本自行解析
        crop_path = Path("crops") / split / Path(r.crop_relpath).name
        abs_crop = WS / crop_path
        if not abs_crop.exists():
            # 兼容 crop_relpath 已含 split
            alt = WS / r.crop_relpath
            if alt.exists():
                crop_path = Path(r.crop_relpath)
            else:
                continue
        text = (r.text or "").replace("\t", " ").replace("\n", " ").strip()
        if not text:
            continue
        buckets[split].append(f"{crop_path.as_posix()}\t{text}")
        counts[split] += 1
    for split, lines in buckets.items():
        out = DIR_REC / f"{split}.txt"
        out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return counts


def choose_split(val_ratio: float, test_ratio: float) -> str:
    import random
    r = random.random()
    if r < test_ratio:
        return "test"
    if r < test_ratio + val_ratio:
        return "val"
    return "train"


def collect_charset(rows: Optional[List[LabelRecord]] = None) -> str:
    rows = rows or load_all_labels()
    chars = sorted(set("".join(r.text for r in rows if r.text)))
    return "".join(chars)


# ---------------------------------------------------------------------------
# 纠错记忆（即时「学会」——无需 GPU）
# ---------------------------------------------------------------------------

def load_memory() -> Dict[str, Any]:
    ensure_workspace()
    try:
        if not MEMORY_PATH.exists():
            return {}
        return json.loads(read_text_loose(MEMORY_PATH) or "{}")
    except Exception:
        return {}


def save_memory(mem: Dict[str, Any]) -> None:
    ensure_workspace()
    MEMORY_PATH.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def memory_put(h: str, text: str, meta: Optional[dict] = None) -> None:
    if not h or not text:
        return
    mem = load_memory()
    mem[h] = {"text": text, "updated_at": now_iso(), **(meta or {})}
    save_memory(mem)


def memory_get(h: str) -> Optional[str]:
    if not h:
        return None
    item = load_memory().get(h)
    return item.get("text") if isinstance(item, dict) else None


# ---------------------------------------------------------------------------
# PaddleOCR 封装
# ---------------------------------------------------------------------------

_ocr_singleton = None
_ocr_key = None


def _ocr_cache_key(cfg: Dict[str, Any]) -> tuple:
    return (
        cfg.get("device"),
        float(cfg.get("text_det_box_thresh", 0.2)),
        float(cfg.get("text_det_thresh", 0.3)),
        float(cfg.get("text_det_unclip_ratio", 1.5)),
        float(cfg.get("text_rec_score_thresh", 0.1)),
        cfg.get("text_recognition_model_name") or "",
        cfg.get("text_detection_model_name") or "",
        (cfg.get("custom_rec_model_dir") or "").strip(),
        (cfg.get("custom_det_model_dir") or "").strip(),
        bool(cfg.get("use_doc_orientation_classify", True)),
        bool(cfg.get("use_doc_unwarping", False)),
        bool(cfg.get("use_textline_orientation", True)),
    )


def _get_cached_engine(key: tuple):
    """优先从 Streamlit session_state 取引擎（避免每次 rerun 重建模型）。"""
    global _ocr_singleton, _ocr_key
    try:
        import streamlit as st
        if hasattr(st, "session_state"):
            eng = st.session_state.get("_ocr9_engine")
            k = st.session_state.get("_ocr9_engine_key")
            if eng is not None and k == key:
                _ocr_singleton, _ocr_key = eng, k
                return eng
    except Exception:
        pass
    if _ocr_singleton is not None and _ocr_key == key:
        return _ocr_singleton
    return None


def _set_cached_engine(key: tuple, engine) -> None:
    global _ocr_singleton, _ocr_key
    _ocr_singleton, _ocr_key = engine, key
    try:
        import streamlit as st
        if hasattr(st, "session_state"):
            st.session_state["_ocr9_engine"] = engine
            st.session_state["_ocr9_engine_key"] = key
    except Exception:
        pass


def get_ocr_engine(cfg: Dict[str, Any], force_reload: bool = False):
    """构建/缓存 PaddleOCR 实例；参数默认值与 ocr.DEFAULT_OCR_PARAMS 一致。"""
    import warnings

    from ocr import DEFAULT_OCR_PARAMS, merge_ocr_params

    key = _ocr_cache_key(cfg)
    if force_reload:
        global _ocr_singleton, _ocr_key
        _ocr_singleton, _ocr_key = None, None
        try:
            import streamlit as st
            st.session_state.pop("_ocr9_engine", None)
            st.session_state.pop("_ocr9_engine_key", None)
        except Exception:
            pass
    else:
        cached = _get_cached_engine(key)
        if cached is not None:
            return cached

    from paddleocr import PaddleOCR

    # 与生产 ocr.py 同一套 merge：先 DEFAULT_OCR_PARAMS，再工作台覆盖
    overrides: Dict[str, Any] = {}
    for k in DEFAULT_OCR_PARAMS:
        if k in cfg and cfg[k] is not None:
            overrides[k] = cfg[k]
    det_name = (cfg.get("text_detection_model_name") or "").strip()
    rec_name = (cfg.get("text_recognition_model_name") or "").strip()
    det_dir = (cfg.get("custom_det_model_dir") or "").strip()
    rec_dir = (cfg.get("custom_rec_model_dir") or "").strip()
    if det_name:
        overrides["text_detection_model_name"] = det_name
    if rec_name:
        overrides["text_recognition_model_name"] = rec_name
    if det_dir:
        overrides["text_detection_model_dir"] = det_dir
    if rec_dir:
        overrides["text_recognition_model_dir"] = rec_dir

    params = merge_ocr_params(overrides)
    # 显式 det/rec 时不传 lang/ocr_version（与 ocr._normalize_paddle_kwargs 一致）
    has_explicit_det_rec = bool(det_name or rec_name or det_dir or rec_dir)
    kwargs: Dict[str, Any] = dict(params)
    kwargs["device"] = cfg.get("device") or "gpu"
    if not has_explicit_det_rec:
        kwargs.setdefault("lang", "ch")
        kwargs.setdefault("ocr_version", "PP-OCRv6")

    # 压制 Paddle/PaddleX 无害噪声（ccache、lang 忽略等）；模型仍正常加载
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r".*lang.*ocr_version.*")
        warnings.filterwarnings("ignore", message=r".*ccache.*")
        warnings.filterwarnings("ignore", category=UserWarning, module=r"paddle\..*")
        engine = PaddleOCR(**kwargs)

    _set_cached_engine(key, engine)
    return engine


def run_ocr_on_image(img_bgr, cfg: Dict[str, Any], apply_memory: bool = True) -> List[OcrBox]:
    """对 BGR 图跑 OCR，返回 OcrBox 列表。"""
    import cv2
    import numpy as np
    import tempfile

    engine = get_ocr_engine(cfg)
    # PaddleOCR 3.x predict 支持 ndarray 或路径
    results = None
    try:
        results = engine.predict(img_bgr)
    except Exception:
        # 部分版本需要文件路径
        tmp = WS / "_tmp_preview.png"
        save_bgr(tmp, img_bgr)
        results = engine.predict(str(tmp))

    boxes: List[OcrBox] = []
    if not results:
        return boxes

    # 兼容 list[result] / result 对象
    items = results if isinstance(results, list) else [results]
    for res in items:
        rec = res
        if hasattr(res, "json") and res.json is not None:
            # PaddleOCR 3 Result 对象
            j = res.json
            if isinstance(j, dict) and "res" in j:
                j = j["res"]
            texts = j.get("rec_texts") or j.get("texts") or []
            scores = j.get("rec_scores") or j.get("scores") or []
            polys = j.get("dt_polys") or j.get("rec_polys") or j.get("boxes") or []
            for i, text in enumerate(texts):
                poly = polys[i] if i < len(polys) else None
                score = float(scores[i]) if i < len(scores) else 0.0
                xs, ys = [], []
                if poly is not None:
                    try:
                        arr = np.array(poly).reshape(-1, 2)
                        xs = [int(v) for v in arr[:, 0]]
                        ys = [int(v) for v in arr[:, 1]]
                    except Exception:
                        pass
                bid = short_id()
                raw = str(text or "")
                ob = OcrBox(box_id=bid, text=raw, score=score, xs=xs, ys=ys, text_raw=raw)
                if apply_memory and cfg.get("auto_memory_apply", True):
                    h = crop_phash(img_bgr, ob.x, ob.y, ob.w, ob.h)
                    mt = memory_get(h)
                    if mt:
                        ob.corrected = mt  # 仅哈希命中；禁止 t: 文本硬改
                boxes.append(ob)
            continue

        # 旧版 list 结构 [[box, (text, score)], ...]
        if isinstance(res, list):
            for line in res:
                try:
                    box, (text, score) = line
                    arr = np.array(box).reshape(-1, 2)
                    xs = [int(v) for v in arr[:, 0]]
                    ys = [int(v) for v in arr[:, 1]]
                    raw = str(text or "")
                    ob = OcrBox(
                        box_id=short_id(), text=raw, score=float(score),
                        xs=xs, ys=ys, text_raw=raw,
                    )
                    if apply_memory and cfg.get("auto_memory_apply", True):
                        h = crop_phash(img_bgr, ob.x, ob.y, ob.w, ob.h)
                        mt = memory_get(h)
                        if mt:
                            ob.corrected = mt
                    boxes.append(ob)
                except Exception:
                    continue
    return boxes


# ---------------------------------------------------------------------------
# 入库与训练
# ---------------------------------------------------------------------------

def save_sample_from_box(
    img_bgr,
    box: OcrBox,
    text: str,
    source_image: str,
    cfg: Dict[str, Any],
    split: Optional[str] = None,
    tags: Optional[List[str]] = None,
    note: str = "",
) -> LabelRecord:
    """裁剪一行、写入 crops + labels + 纠错记忆。"""
    import cv2

    text = (text or "").strip()
    if not text:
        raise ValueError("真值文本不能为空")

    pad = int(cfg.get("crop_pad_px", 2))
    H, W = img_bgr.shape[:2]
    x1 = max(0, box.x - pad)
    y1 = max(0, box.y - pad)
    x2 = min(W, box.x + box.w + pad)
    y2 = min(H, box.y + box.h + pad)
    crop = img_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError("裁剪区域为空")

    split = split or choose_split(float(cfg.get("val_ratio", 0.1)), float(cfg.get("test_ratio", 0.1)))
    sid = short_id()
    fname = f"{sid}.png"
    rel = f"crops/{split}/{fname}"
    save_bgr(WS / rel, crop)

    # 纠错记忆：仅图像哈希→真值（禁止 t: 文本硬改 / 字符串替换）
    truth = (text or "").strip()
    h = crop_phash(img_bgr, box.x, box.y, box.w, box.h)
    memory_put(h, truth, {"sample_id": sid, "source": source_image, "kind": "phash"})
    try:
        h2 = crop_phash(crop, 0, 0, crop.shape[1], crop.shape[0])
        if h2 and h2 != h:
            memory_put(
                h2, truth,
                {"sample_id": sid, "source": source_image, "kind": "crop_phash"},
            )
    except Exception:
        pass

    rec = LabelRecord(
        sample_id=sid,
        split=split,
        source_image=source_image,
        crop_relpath=rel,
        text=text,
        score=float(box.score),
        box=[box.x, box.y, box.w, box.h],
        created_at=now_iso(),
        trained=False,
        tags=tags or [],
        note=note,
    )
    append_label(rec)
    rebuild_rec_lists()
    return rec


def mark_samples_trained(sample_ids: List[str]) -> int:
    rows = load_all_labels()
    sid_set = set(sample_ids)
    n = 0
    for r in rows:
        if r.sample_id in sid_set and not r.trained:
            r.trained = True
            n += 1
    rewrite_labels(rows)
    return n


def untrained_samples() -> List[LabelRecord]:
    return [r for r in load_all_labels() if not r.trained and r.split == "train"]


def write_train_job_snapshot(cfg: Dict[str, Any], epochs: int, note: str = "") -> Path:
    """写出训练任务快照（数据统计 + 配置），便于复现。"""
    ensure_workspace()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + short_id()[:6]
    run_dir = DIR_RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = load_all_labels()
    meta = {
        "run_id": run_id,
        "created_at": now_iso(),
        "note": note,
        "epochs": epochs,
        "config": cfg,
        "counts": {
            "total": len(rows),
            "train": sum(1 for r in rows if r.split == "train"),
            "val": sum(1 for r in rows if r.split == "val"),
            "test": sum(1 for r in rows if r.split == "test"),
            "untrained_train": len(untrained_samples()),
        },
        "charset_size": len(collect_charset(rows)),
        "charset_preview": collect_charset(rows)[:200],
    }
    (run_dir / "job.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    # 复制当前 rec 列表
    for s in SPLITS:
        src = DIR_REC / f"{s}.txt"
        if src.exists():
            shutil.copy2(src, run_dir / f"{s}.txt")
    return run_dir


def try_run_paddlex_or_script_train(
    cfg: Dict[str, Any],
    epochs: int,
    sample_ids: Optional[List[str]] = None,
) -> Tuple[bool, str, Optional[Path]]:
    """
    尝试启动 rec 微调。
    返回 (成功?, 日志, 模型目录)。
    策略：
      1) 若存在 paddlex 且可创建文本识别训练，则调用
      2) 否则写出 train_rec_runner.py + README，返回指导信息（标注数据已就绪）
    """
    rebuild_rec_lists()
    run_dir = write_train_job_snapshot(cfg, epochs, note="finetune")
    train_txt = DIR_REC / "train.txt"
    if not train_txt.exists() or not read_text_loose(train_txt).strip():
        return False, "训练集为空：请先逐项校对并「加入训练集」。", None

    n_train = sum(1 for _ in read_text_loose(train_txt).splitlines() if _.strip())
    min_n = int(cfg.get("min_samples_for_train", 8))
    if n_train < min_n:
        return (
            False,
            f"训练样本不足：当前 train={n_train}，建议至少 {min_n} 条后再微调（可在配置中调整阈值）。",
            None,
        )

    out_model = DIR_MODELS / f"rec_ft_{run_dir.name}"
    out_model.mkdir(parents=True, exist_ok=True)

    # 生成可复现的训练启动脚本（即使本机无法训，数据也已就绪）
    runner = run_dir / "train_rec_runner.py"
    runner.write_text(
        f'''# -*- coding: utf-8 -*-
"""自动生成：PaddleOCR / PaddleX 文本识别微调启动脚本
工作区: {WS}
训练列表: {DIR_REC / "train.txt"}
输出目录: {out_model}
"""
import os
import sys
from pathlib import Path

WS = Path(r"{WS}")
TRAIN = WS / "rec" / "train.txt"
VAL = WS / "rec" / "val.txt"
OUT = Path(r"{out_model}")
EPOCHS = {epochs}
DEVICE = "{cfg.get("device", "gpu")}"

def main():
    print("workspace:", WS)
    print("train list:", TRAIN, "exists", TRAIN.exists())
    # 优先 PaddleX
    try:
        from paddlex import create_pipeline
        print("PaddleX 可用。请参考官方文档用 TextRecognition 训练 API 指向 TRAIN/VAL。")
        print("数据集格式: 每行  相对路径\\\\t标签")
        print("示例路径已生成，OUT=", OUT)
    except Exception as e:
        print("PaddleX 不可用:", e)
    # 回退提示
    print("""
推荐流程（官方）：
1. git clone https://github.com/PaddlePaddle/PaddleOCR
2. 将 ocr_train_workspace/crops 与 rec/train.txt 配置进 rec 微调 yaml
3. 训练完成后把 inference 模型目录拷到:
   {out_model}
4. 在 ocr9 工作台「模型」页填写 custom_rec_model_dir 并热加载

本仓库主程序 ocr.py 支持 text_recognition_model_dir 参数透传。
""")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "README.txt").write_text(
        f"Place exported PaddleOCR rec inference model here.\\nTrain list: {{TRAIN}}\\n",
        encoding="utf-8",
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )

    # 尝试轻量：用 subprocess 跑 runner（至少生成 README）；真训练需环境
    log_lines = [f"[{now_iso()}] run_dir={run_dir}", f"train_samples={n_train}", f"epochs={epochs}"]
    try:
        proc = subprocess.run(
            [sys.executable, str(runner)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(WS),
            timeout=120,
        )
        log_lines.append(proc.stdout or "")
        log_lines.append(proc.stderr or "")
        log_lines.append(f"exit={proc.returncode}")
    except Exception as e:
        log_lines.append(f"runner error: {e}")

    # 尝试 paddlex train（若用户环境已配置好，可在此扩展）
    trained = False
    detail = ""
    try:
        import paddlex  # noqa: F401
        detail = (
            "已检测到 paddlex。请用官方 TextRecognition 训练流程指向 "
            f"{DIR_REC}/train.txt ，导出模型到 {out_model} 。"
        )
    except Exception:
        detail = (
            "未安装/未配置完整训练栈。标注数据与 train.txt 已就绪；"
            "预览侧已启用「纠错记忆」即时生效。"
            f" 启动脚本: {runner}"
        )

    (run_dir / "train_log.txt").write_text("\n".join(log_lines) + "\n" + detail, encoding="utf-8")

    # 标记样本（只要用户点了训练，就记 trained=True 表示已进入训练批次；权重是否更新取决于环境）
    ids = sample_ids or [r.sample_id for r in untrained_samples()]
    mark_samples_trained(ids)

    # 写出模型挂载说明
    (out_model / "EXPORT_HINT.txt").write_text(
        "将官方导出的 rec 推理目录内容放于此目录后，\n"
        "在 ocr9「模型」页设置 custom_rec_model_dir 并「热加载」。\n"
        f"或写入主项目 config.json:\n"
        f'  "ocr_params": {{ "text_recognition_model_dir": "{out_model.as_posix()}" }}\n',
        encoding="utf-8",
    )

    ok_msg = (
        f"训练任务已登记。\n"
        f"- 运行目录: {run_dir}\n"
        f"- 模型目录: {out_model}\n"
        f"- {detail}\n"
        f"- 纠错记忆条目: {len(load_memory())}（预览已即时生效）"
    )
    return True, ok_msg, out_model


def evaluate_on_split(cfg: Dict[str, Any], split: str = "test") -> Dict[str, Any]:
    """用当前引擎对 split 裁剪图重识别，算字符级准确率。"""
    rows = [r for r in load_all_labels() if r.split == split]
    if not rows:
        return {"n": 0, "char_acc": None, "exact": None, "details": []}

    engine_cfg = dict(cfg)
    correct_chars = 0
    total_chars = 0
    exact = 0
    details = []
    for r in rows:
        path = WS / r.crop_relpath
        if not path.exists():
            continue
        img = load_bgr(str(path))
        # 单行图：只取第一条
        boxes = run_ocr_on_image(img, engine_cfg, apply_memory=False)
        pred = boxes[0].text if boxes else ""
        gt = r.text
        # 字符准确：LCS 近似用逐位对齐简化
        total_chars += max(len(gt), 1)
        # 简单：匹配字符数 / max(len)
        match = sum(1 for a, b in zip(gt, pred) if a == b)
        correct_chars += match
        # 补长度惩罚
        if len(pred) != len(gt):
            pass
        if pred == gt:
            exact += 1
        details.append({"gt": gt, "pred": pred, "ok": pred == gt, "score": boxes[0].score if boxes else 0})

    n = len(details)
    char_acc = correct_chars / max(total_chars, 1)
    # 更合理的 CER 简化：1 - edit_ratio
    def _lev(a, b):
        dp = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            prev, dp[0] = dp[0], i
            for j, cb in enumerate(b, 1):
                cur = dp[j]
                dp[j] = prev if ca == cb else 1 + min(prev, dp[j], dp[j - 1])
                prev = cur
        return dp[-1]

    edit = sum(_lev(d["gt"], d["pred"]) for d in details)
    gt_len = sum(len(d["gt"]) for d in details) or 1
    cer = edit / gt_len
    return {
        "n": n,
        "exact_match": exact / n if n else None,
        "char_acc_approx": char_acc,
        "cer": cer,
        "details": details[:50],
    }


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def render_app() -> None:
    import streamlit as st
    import numpy as np

    ensure_workspace()
    # 作为主应用多页嵌入时，frontend 已 set_page_config，此处不可再调
    try:
        st.set_page_config(
            page_title="OCR文字训练（ocr.py）",
            page_icon="🔤",
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except Exception:
        pass

    st.markdown(
        """
        <style>
        .block-container { padding-top: 1rem; }
        div[data-testid="stMetricValue"] { font-size: 1.2rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("🔤 OCR 文字训练 · ocr.py")
    st.caption(
        "对应生产 **ocr.py** 文字识别 · 即时预览 → 逐项改真值入库 → 纠错记忆 → rec 微调 · "
        f"工作区 `{WS.name}/`（本页即原 ocr9 工作台）"
    )

    cfg = load_ws_config()
    _defaults = default_ws_config()

    # Streamlit 控件会缓存旧值：重置时必须清 session_state 或递增 gen 换 key
    if "ocr9_ui_gen" not in st.session_state:
        st.session_state["ocr9_ui_gen"] = 0
    _ug = int(st.session_state["ocr9_ui_gen"])

    def _k(name: str) -> str:
        return f"ocr9_{name}_g{_ug}"

    # ---------- 侧栏 ----------
    with st.sidebar:
        st.header("⚙️ 引擎与训练")
        auto_live = st.checkbox(
            "滑标/参数变更时自动刷新预览",
            value=True,
            help="已选图时，拖动阈值等会立刻重跑 OCR 并更新绿框（略耗时）",
            key=_k("auto_live"),
        )
        cfg["device"] = st.selectbox(
            "设备", ["cpu", "gpu"],
            index=0 if cfg.get("device") != "gpu" else 1,
            key=_k("device"),
        )
        cfg["text_det_box_thresh"] = st.slider(
            "检测 box_thresh", 0.05, 0.9,
            float(cfg.get("text_det_box_thresh", _defaults["text_det_box_thresh"])), 0.05,
            help=f"默认 {_defaults['text_det_box_thresh']}：降低→少漏框",
            key=_k("box_thresh"),
        )
        cfg["text_det_thresh"] = st.slider(
            "检测 thresh", 0.05, 0.9,
            float(cfg.get("text_det_thresh", _defaults["text_det_thresh"])), 0.05,
            help=f"默认 {_defaults['text_det_thresh']}（与 ocr.py 一致）",
            key=_k("det_thresh"),
        )
        cfg["text_det_unclip_ratio"] = st.slider(
            "框扩张 unclip", 0.5, 3.0,
            float(cfg.get("text_det_unclip_ratio", _defaults.get("text_det_unclip_ratio", 1.5))), 0.1,
            help=f"默认 {_defaults.get('text_det_unclip_ratio', 1.5)}（ocr.py text_det_unclip_ratio）",
            key=_k("unclip"),
        )
        cfg["text_rec_score_thresh"] = st.slider(
            "识别 score_thresh", 0.0, 0.9,
            float(cfg.get("text_rec_score_thresh", _defaults["text_rec_score_thresh"])), 0.05,
            help=f"默认 {_defaults['text_rec_score_thresh']}：手写宜偏低",
            key=_k("rec_score"),
        )
        cfg["hard_score_thresh"] = st.slider(
            "难例分界（低于此优先）", 0.3, 0.95,
            float(cfg.get("hard_score_thresh", _defaults["hard_score_thresh"])), 0.05,
            help=f"默认 {_defaults['hard_score_thresh']}：仅影响列表排序/筛选，不改引擎",
            key=_k("hard_score"),
        )
        cfg["auto_memory_apply"] = st.checkbox(
            "预览应用纠错记忆（即时学会）",
            value=bool(cfg.get("auto_memory_apply", True)),
            key=_k("auto_memory"),
        )
        cfg["use_doc_orientation_classify"] = st.checkbox(
            "文档整页方向分类（ocr.py 默认开）",
            value=bool(cfg.get("use_doc_orientation_classify", _defaults.get("use_doc_orientation_classify", True))),
            key=_k("doc_ori"),
            help="与 ocr.DEFAULT_OCR_PARAMS.use_doc_orientation_classify 一致；关可少加载一个模型",
        )
        cfg["use_textline_orientation"] = st.checkbox(
            "文本行方向模型（关闭可少加载一个模型、稍快）",
            value=bool(cfg.get("use_textline_orientation", True)),
            key=_k("textline_ori"),
        )
        cfg["min_samples_for_train"] = st.number_input(
            "最少训练样本", 1, 500, int(cfg.get("min_samples_for_train", 8)), key=_k("min_train"),
        )
        cfg["default_epochs"] = st.number_input(
            "默认 epochs", 1, 100, int(cfg.get("default_epochs", 5)), key=_k("epochs"),
        )
        cfg["val_ratio"] = st.number_input(
            "验证集比例", 0.0, 0.4, float(cfg.get("val_ratio", 0.1)), 0.05, key=_k("val_ratio"),
        )
        cfg["test_ratio"] = st.number_input(
            "测试集比例", 0.0, 0.4, float(cfg.get("test_ratio", 0.1)), 0.05, key=_k("test_ratio"),
        )

        st.markdown("---")
        st.subheader("自定义模型目录")
        cfg["custom_rec_model_dir"] = st.text_input(
            "rec model dir", cfg.get("custom_rec_model_dir") or "", key=_k("rec_dir"),
        )
        cfg["custom_det_model_dir"] = st.text_input(
            "det model dir", cfg.get("custom_det_model_dir") or "", key=_k("det_dir"),
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 保存配置", use_container_width=True, key=_k("btn_save")):
                save_ws_config(cfg)
                st.success("已保存")
        with c2:
            if st.button("🔄 热加载 OCR", use_container_width=True, key=_k("btn_reload")):
                save_ws_config(cfg)
                try:
                    get_ocr_engine(cfg, force_reload=True)
                    st.session_state["ocr9_force_refresh"] = True
                    st.success("引擎已重载")
                except Exception as e:
                    st.error(f"加载失败: {e}")

        # on_click 在主脚本渲染控件前执行：写 config + 换 gen + 预填 session_state
        # （仅 st.rerun + value= 不够：有 key 的滑标会忽略 value=，界面看起来「没重置」）
        st.button(
            "↺ 重置为默认参数",
            use_container_width=True,
            type="secondary",
            key=_k("btn_reset"),
            on_click=_on_reset_ocr9_defaults,
        )
        _flash = st.session_state.pop("ocr9_reset_flash", None)
        if _flash:
            st.success(_flash)

        with st.expander("查看默认参数表"):
            st.json(_defaults)

        st.markdown("---")
        rows = load_all_labels()
        st.metric("标注总数", len(rows))
        st.metric("未训练(train)", len(untrained_samples()))
        st.metric("纠错记忆", len(load_memory()))
        st.caption(f"字符集大小: {len(collect_charset(rows))}")

    tab_preview, tab_data, tab_train, tab_model, tab_help = st.tabs(
        ["📷 识别与逐项训练", "📚 数据集", "🏋️ 训练任务", "📦 模型与导出", "❓ 帮助"]
    )

    # ==================== Tab1 预览与逐项 ====================
    with tab_preview:
        left, right = st.columns([1, 1.15])
        with left:
            st.subheader("1. 选图")
            src_mode = st.radio("来源", ["上传", "工作区 raw/", "主项目 archives/"], horizontal=True)
            image_path = None
            uploaded = None

            if src_mode == "上传":
                uploaded = st.file_uploader("图片", type=["jpg", "jpeg", "png", "bmp", "webp"])
                if uploaded:
                    raw_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name(uploaded.name)}"
                    image_path = str(DIR_RAW / raw_name)
                    (DIR_RAW / raw_name).write_bytes(uploaded.getvalue())
            elif src_mode == "工作区 raw/":
                files = sorted(DIR_RAW.glob("*"))
                files = [f for f in files if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}]
                if files:
                    pick = st.selectbox("raw 图片", files, format_func=lambda p: p.name)
                    image_path = str(pick)
                else:
                    st.info("raw/ 目录暂无图片，请先上传。")
            else:
                arch = ROOT / "archives"
                cands = []
                if arch.exists():
                    for p in arch.rglob("*"):
                        if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and (
                            "对齐" in p.name or "aligned" in p.name.lower() or p.suffix.lower() in {".jpg", ".png"}
                        ):
                            cands.append(p)
                cands = sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)[:200]
                if cands:
                    pick = st.selectbox("archives 图片", cands, format_func=lambda p: str(p.relative_to(ROOT)))
                    image_path = str(pick)
                else:
                    st.info("未找到 archives 图片。")

            run_ocr = st.button("▶️ 运行 / 刷新 OCR 预览", type="primary", use_container_width=True)
            only_hard = st.checkbox("只列出难例（低置信度）", value=False)
            st.caption("提示：打开侧栏「滑标变更时自动刷新预览」后，调阈值会即时重跑识别。")

        # 参数指纹：滑标变化 → 触发重识别
        param_sig = str(_ocr_cache_key(cfg)) + f"|mem={cfg.get('auto_memory_apply')}"
        prev_sig = st.session_state.get("ocr9_param_sig")
        params_changed = prev_sig is not None and prev_sig != param_sig
        force_refresh = bool(st.session_state.pop("ocr9_force_refresh", False))

        need_ocr = False
        if image_path:
            path_same = st.session_state.get("ocr9_last_path") == image_path
            if run_ocr or force_refresh:
                need_ocr = True
            elif st.session_state.get("ocr9_boxes") is None or not path_same:
                need_ocr = True
            elif auto_live and path_same and params_changed:
                need_ocr = True

        if image_path and need_ocr:
            try:
                with st.spinner("PaddleOCR 识别中（参数已应用）…"):
                    img = load_bgr(image_path)
                    boxes = run_ocr_on_image(img, cfg, apply_memory=bool(cfg.get("auto_memory_apply", True)))
                    st.session_state["ocr9_img_path"] = image_path
                    st.session_state["ocr9_last_path"] = image_path
                    st.session_state["ocr9_boxes"] = [asdict(b) for b in boxes]
                    st.session_state["ocr9_img_shape"] = img.shape[:2]
                    st.session_state["ocr9_param_sig"] = param_sig
            except Exception as e:
                st.error(f"OCR 失败: {e}")
                st.code(traceback.format_exc())
        elif image_path and not need_ocr:
            st.session_state["ocr9_param_sig"] = param_sig

        boxes_data = st.session_state.get("ocr9_boxes") or []
        boxes = [OcrBox(**{k: b[k] for k in OcrBox.__dataclass_fields__ if k in b}) for b in boxes_data]
        path_now = st.session_state.get("ocr9_img_path")

        with right:
            st.subheader("2. 预览（绿=高置信 · 红=低置信难例）")
            if path_now and boxes:
                img = load_bgr(path_now)
                hard_th = float(cfg.get("hard_score_thresh", 0.75))
                # 难例分界仅影响列表/红框着色展示；引擎结果已按 det/rec 阈值刷新
                show_list = boxes
                if only_hard:
                    show_list = [b for b in boxes if b.score < hard_th]
                # 重绘时用当前 hard_score_thresh 着色（不改识别结果，立即可见）
                vis_boxes = []
                for b in boxes:
                    vis_boxes.append(b)
                hi = st.session_state.get("ocr9_hi")
                # 临时：draw 用 0.75 写死→改为 hard_th
                vis = _draw_boxes_with_thresh(img, vis_boxes, hard_th, highlight=hi)
                st.image(
                    bgr_to_rgb(vis),
                    caption=f"{Path(path_now).name} · 检出 {len(boxes)} 行"
                    + (f" · 难例列表 {len(show_list)}" if only_hard else "")
                    + (f" · 参数已即时刷新" if params_changed and auto_live else ""),
                    use_container_width=True,
                )
                low_n = sum(1 for b in boxes if b.score < hard_th)
                st.caption(
                    f"低置信度(<{hard_th}): {low_n}/{len(boxes)} · "
                    f"box_thresh={cfg.get('text_det_box_thresh')} det_thresh={cfg.get('text_det_thresh')} "
                    f"rec_score={cfg.get('text_rec_score_thresh')}"
                )
            else:
                st.info("请选择图片并点击「运行 / 刷新 OCR 预览」（或开启自动刷新后拖动滑标）。")

        st.markdown("---")
        st.subheader("3. 逐项校对 → 入库 / 即时训练")
        if not boxes:
            st.caption("暂无检测框。")
        else:
            # 排序：难例优先
            ordered = sorted(boxes, key=lambda b: b.score)
            if only_hard:
                ordered = [b for b in ordered if b.score < float(cfg.get("hard_score_thresh", 0.75))]

            for idx, b in enumerate(ordered):
                with st.container():
                    cols = st.columns([0.08, 0.42, 0.3, 0.2])
                    with cols[0]:
                        st.markdown(f"**#{idx+1}**")
                        st.caption(f"{b.score:.2f}")
                    with cols[1]:
                        # 小图预览
                        if path_now:
                            img = load_bgr(path_now)
                            pad = int(cfg.get("crop_pad_px", 2))
                            H, W = img.shape[:2]
                            x1, y1 = max(0, b.x - pad), max(0, b.y - pad)
                            x2, y2 = min(W, b.x + b.w + pad), min(H, b.y + b.h + pad)
                            crop = img[y1:y2, x1:x2]
                            if crop.size:
                                st.image(bgr_to_rgb(crop), use_container_width=True)
                    with cols[2]:
                        key_txt = f"corr_{b.box_id}"
                        default_txt = b.corrected or b.text
                        new_txt = st.text_input(
                            "真值",
                            value=default_txt,
                            key=key_txt,
                            label_visibility="collapsed",
                            placeholder="校正后的文字",
                        )
                        split_force = st.selectbox(
                            "划分",
                            ["auto", "train", "val", "test"],
                            key=f"split_{b.box_id}",
                            label_visibility="collapsed",
                        )
                    with cols[3]:
                        if st.button("定位", key=f"hi_{b.box_id}"):
                            st.session_state["ocr9_hi"] = b.box_id
                            st.rerun()
                        if st.button("➕ 入库", key=f"add_{b.box_id}", type="primary"):
                            try:
                                img = load_bgr(path_now)
                                split = None if split_force == "auto" else split_force
                                # 确保 text_raw 仍是原始 OCR（session 重建时可能丢失）
                                if not (getattr(b, "text_raw", None) or "").strip():
                                    b.text_raw = (b.text or "").strip()
                                rec = save_sample_from_box(
                                    img, b, new_txt, path_now, cfg, split=split, tags=["interactive"],
                                )
                                # 同步 session：只改 corrected，保留 text/text_raw 为引擎原文
                                for bd in st.session_state["ocr9_boxes"]:
                                    if bd["box_id"] == b.box_id:
                                        if not bd.get("text_raw"):
                                            bd["text_raw"] = bd.get("text") or ""
                                        bd["corrected"] = new_txt
                                        bd["in_dataset"] = True
                                        bd["sample_id"] = rec.sample_id
                                st.success(f"已入库 {rec.sample_id} → {rec.split}（图像哈希记忆，无文本硬改）")
                            except Exception as e:
                                st.error(str(e))
                        if st.button("⚡ 入库并微调", key=f"ft_{b.box_id}"):
                            try:
                                img = load_bgr(path_now)
                                split = None if split_force == "auto" else split_force
                                rec = save_sample_from_box(
                                    img, b, new_txt, path_now, cfg, split=split, tags=["interactive", "instant_ft"],
                                )
                                ok, msg, mdir = try_run_paddlex_or_script_train(
                                    cfg, int(cfg.get("default_epochs", 5)), sample_ids=[rec.sample_id],
                                )
                                if ok:
                                    st.success(msg)
                                else:
                                    st.warning(msg)
                            except Exception as e:
                                st.error(str(e))
                    st.markdown("---")

            st.markdown("#### 批量操作")
            bc1, bc2, bc3 = st.columns(3)
            with bc1:
                if st.button("将当前页全部检测结果按识别结果入库（慎用）", use_container_width=True):
                    if path_now and boxes:
                        img = load_bgr(path_now)
                        n = 0
                        for b in boxes:
                            t = (st.session_state.get(f"corr_{b.box_id}") or b.corrected or b.text or "").strip()
                            if not t:
                                continue
                            try:
                                save_sample_from_box(img, b, t, path_now, cfg, tags=["batch_auto"])
                                n += 1
                            except Exception:
                                pass
                        st.info(f"批量入库 {n} 条（请抽查纠错记忆与标签质量）")
            with bc2:
                if st.button("用全部未训练样本启动微调", type="primary", use_container_width=True):
                    ok, msg, _ = try_run_paddlex_or_script_train(cfg, int(cfg.get("default_epochs", 5)))
                    (st.success if ok else st.warning)(msg)
            with bc3:
                if st.button("重建 rec/train|val|test 列表", use_container_width=True):
                    counts = rebuild_rec_lists()
                    st.success(str(counts))

    # ==================== Tab2 数据集 ====================
    with tab_data:
        st.subheader("标注数据总览")
        rows = load_all_labels()
        if not rows:
            st.info("暂无标注。请在「识别与逐项训练」中入库。")
        else:
            import pandas as pd
            df = pd.DataFrame([asdict(r) for r in rows])
            st.dataframe(df, use_container_width=True, height=360)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("train", sum(1 for r in rows if r.split == "train"))
            c2.metric("val", sum(1 for r in rows if r.split == "val"))
            c3.metric("test", sum(1 for r in rows if r.split == "test"))
            c4.metric("已标记 trained", sum(1 for r in rows if r.trained))

            st.download_button(
                "下载 labels.jsonl",
                data=LABELS_PATH.read_bytes() if LABELS_PATH.exists() else b"",
                file_name="labels.jsonl",
            )
            charset = collect_charset(rows)
            st.text_area("字符集", charset, height=80)
            if st.button("导出字符集到 models/charset.txt"):
                (DIR_MODELS / "charset.txt").write_text(charset, encoding="utf-8")
                st.success(str(DIR_MODELS / "charset.txt"))

            del_id = st.text_input("删除 sample_id（危险）")
            if st.button("删除该样本") and del_id.strip():
                keep = [r for r in rows if r.sample_id != del_id.strip()]
                # 删文件
                for r in rows:
                    if r.sample_id == del_id.strip():
                        p = WS / r.crop_relpath
                        if p.exists():
                            p.unlink()
                rewrite_labels(keep)
                rebuild_rec_lists()
                st.success("已删除")
                st.rerun()

        st.markdown("#### 纠错记忆（仅图像哈希，禁止文本硬改）")
        st.caption(
            "入库写入 crop 图像哈希→真值；admin 仅在哈希命中时替换。"
            "禁止 t:错字→对字 字符串硬改 / 默认值兜底。"
        )
        mem = load_memory()
        # 过滤展示：不展示历史 t: 硬改键
        show = {
            k: (v.get("text") if isinstance(v, dict) else v)
            for k, v in list(mem.items())[:80]
            if not str(k).startswith("t:")
        }
        st.json(show)
        if st.button("清空纠错记忆"):
            save_memory({})
            st.warning("已清空")
        if st.button("清除历史文本硬改键 t:*"):
            mem2 = {k: v for k, v in load_memory().items() if not str(k).startswith("t:")}
            save_memory(mem2)
            st.success("已清除 t:* 硬改项")
            st.rerun()

    # ==================== Tab3 训练 ====================
    with tab_train:
        st.subheader("训练任务")
        st.write(
            f"未训练 train 样本: **{len(untrained_samples())}** · "
            f"最少要求: **{cfg.get('min_samples_for_train')}**"
        )
        epochs = st.number_input("Epochs", 1, 100, int(cfg.get("default_epochs", 5)), key="train_epochs")
        if st.button("🚀 启动微调任务", type="primary"):
            with st.spinner("登记训练任务…"):
                ok, msg, mdir = try_run_paddlex_or_script_train(cfg, int(epochs))
            (st.success if ok else st.error)(msg)
            if mdir:
                st.code(str(mdir))

        st.markdown("#### 历史 runs/")
        try:
            runs = sorted(DIR_RUNS.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        except Exception:
            runs = []
        for rd in runs:
            try:
                job = rd / "job.json"
                with st.expander(rd.name):
                    if job.exists():
                        try:
                            st.json(json.loads(read_text_loose(job) or "{}"))
                        except Exception as e:
                            st.warning(f"job.json 无法解析: {e}")
                            st.text(read_text_loose(job, 2000))
                    logp = rd / "train_log.txt"
                    if logp.exists():
                        st.text(read_text_loose(logp, 3000))
            except Exception as e:
                st.caption(f"{rd.name}: 读取失败 ({e})")

        st.markdown("#### 测试集评测（当前引擎）")
        if st.button("评测 test split"):
            with st.spinner("评测中…"):
                ev = evaluate_on_split(cfg, "test")
            st.write({k: v for k, v in ev.items() if k != "details"})
            if ev.get("details"):
                import pandas as pd
                st.dataframe(pd.DataFrame(ev["details"]), use_container_width=True)

    # ==================== Tab4 模型 ====================
    with tab_model:
        st.subheader("模型目录")
        models = sorted(DIR_MODELS.glob("*")) if DIR_MODELS.exists() else []
        for m in models:
            st.text(f"{'📁' if m.is_dir() else '📄'} {m.name}")
        _model_root = DIR_MODELS.as_posix()
        st.markdown("**挂到主系统**")
        st.markdown("在 `config.json` 中增加：")
        st.code(
            "{\n"
            '  "ocr_params": {\n'
            f'    "text_recognition_model_dir": "{_model_root}/你的导出目录"\n'
            "  }\n"
            "}",
            language="json",
        )
        st.markdown("或在本页侧栏填写 **rec model dir** 后点「热加载 OCR」。")
        export_cfg = {
            "text_recognition_model_dir": cfg.get("custom_rec_model_dir") or "",
            "text_detection_model_dir": cfg.get("custom_det_model_dir") or "",
            "workspace": str(WS),
            "rec_train_list": str(DIR_REC / "train.txt"),
        }
        st.download_button(
            "下载 ocr 挂载片段 JSON",
            data=json.dumps(export_cfg, ensure_ascii=False, indent=2),
            file_name="ocr9_export_hint.json",
        )

    # ==================== Tab5 帮助 ====================
    with tab_help:
        st.markdown(
            """
### 推荐工作流

1. **选图** → 优先用主项目 `archives/**/对齐图`（与线上一致）。
2. **运行 OCR 预览** → 看框与置信度；打开「只列难例」。
3. **逐项改真值** → `➕ 入库`：写入 crops + labels + **纠错记忆**（立刻影响下次预览）。
4. **⚡ 入库并微调** 或侧栏/训练页启动任务：生成 `runs/` 快照与 `rec/train.txt`。
5. 若本机有 **PaddleOCR/PaddleX 完整训练环境**，按 `runs/*/train_rec_runner.py` 与官方文档导出 rec 推理模型。
6. 将模型目录填入侧栏 **custom_rec_model_dir** → **热加载**，再评测 test。

### 两种「学会」机制

| 机制 | 是否改权重 | 是否即时 | 说明 |
|------|------------|----------|------|
| 纠错记忆 | 否 | 是 | 裁剪图哈希 → 真值，预览直接替换 |
| rec 微调 | 是 | 否（需训练） | 通用化到未见图，需 GPU/官方训练栈 |

### 与主项目关系

- 主流程 **ocr5**：勾选格 √×\\，本工具不替代。
- 主流程 **ocr.py**：可通过 `text_recognition_model_dir` 挂微调模型。
- 本工具数据在 `ocr_train_workspace/`，不污染 `uploads/`。

### 质量建议

- 同一手写人至少 20+ 行样本再指望微调明显提升。
- train/val/test 勿混同一张图的所有行到 train（可按图划分，后续可增强）。
- 真值不要含 Tab/换行；全角半角尽量统一。
- 禁止把错误识别批量入库。

### 启动

```bash
streamlit run ocr9.py
python ocr9.py --port 8502
```
"""
        )


def _is_streamlit_script_run() -> bool:
    """判断是否由 `streamlit run ocr9.py` 直接执行本文件。"""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


_CLI_EPILOG = r"""
示例
----
  python ocr9.py -h
  python ocr9.py
  python ocr9.py --port 8502
  python ocr9.py --port 8502 --browser
  python ocr9.py --host 0.0.0.0 --port 8502
  streamlit run ocr9.py --server.port 8502

功能（Web UI）
--------------
  1. 即时识别预览
     - 上传图片 / 工作区 raw/ / 主项目 archives/ 对齐图
     - PaddleOCR 画框 + 置信度；可调 det/rec 阈值
     - 难例优先（低置信度）

  2. 逐项校对入库
     - 对每一检测行修改真值 →「入库」
     - 写入 crops + labels.jsonl + 纠错记忆（哈希→真值，预览立刻生效）

  3. 训练
     - 「入库并微调」或「用未训练样本启动微调」
     - 生成 rec/train.txt|val.txt|test.txt（Paddle 格式：相对路径\t标签）
     - 生成 runs/ 任务快照与 train_rec_runner.py
     - 真·权重微调需本机 PaddleOCR/PaddleX 训练环境；无则仍可标注 + 纠错记忆

  4. 模型与评测
     - 自定义 rec/det 目录热加载
     - test 集 CER / 完全匹配评测
     - 导出挂载片段，供主系统 config.json 的 ocr_params.text_recognition_model_dir

工作目录（自动创建，已 gitignore）
--------------------------------
  ocr_train_workspace/
    raw/                    上传原图
    crops/train|val|test/   行裁剪图
    labels.jsonl            全量标注元数据
    rec/train.txt ...       Paddle rec 列表
    memory/corrections.json 即时纠错记忆
    models/                 微调产出与导出说明
    runs/                   训练日志与配置快照
    config.json             工作台参数

与主项目边界
------------
  - ocr5.py  : 带气票 25×5 勾选格 √/×/\ ，本工具不替代
  - ocr.py   : 生产 OCR；可用 text_recognition_model_dir 挂本工具导出的 rec
  - agent    : 业务审批流；ocr9 仅用于提升文字识别/标注训练

依赖
----
  streamlit, paddleocr, paddlepaddle, opencv-python, numpy, pandas
  （与主项目 requirements.txt 一致；streamlit 用于 Web UI）

注意
----
  - 勾选符号请继续用 ocr5；ocr9 聚焦手写姓名、编号、日期等文字行
  - 不要把错误识别批量入库；手写样本建议每人 20+ 行再指望权重微调
  - 真值勿含 Tab/换行
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocr9.py",
        description=(
            "OCR9 · 交互式 OCR 标注与微调工作台（Streamlit Web UI）\n"
            "即时预览识别结果 → 逐项改真值入库 → 纠错记忆立刻生效 → 登记 rec 微调任务。"
        ),
        epilog=_CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8502,
        metavar="PORT",
        help="Streamlit 服务端口（默认: 8502）",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        metavar="ADDR",
        help="监听地址（默认: 127.0.0.1；局域网访问可用 0.0.0.0）",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="启动时尝试打开系统浏览器（默认不自动打开，headless）",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        metavar="DIR",
        help="工作区目录（默认: 脚本旁 ocr_train_workspace/）",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version="ocr9.py (OCR 标注与微调工作台) · player 项目配套工具",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.workspace:
        os.environ["OCR9_WORKSPACE"] = str(Path(args.workspace).expanduser().resolve())

    # 子进程 streamlit 会重新 import 本文件，通过 OCR9_WORKSPACE 继承工作区
    ws_show = (
        Path(os.environ["OCR9_WORKSPACE"])
        if os.environ.get("OCR9_WORKSPACE")
        else (ROOT / "ocr_train_workspace")
    )
    ws_show.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(Path(__file__).resolve()),
        "--server.port", str(args.port),
        "--server.address", str(args.host),
        "--server.headless", "true" if not args.browser else "false",
    ]
    print("OCR9 训练工作台")
    print("  Starting:", " ".join(cmd))
    print(f"  Workspace: {ws_show}")
    print(f"  Open:      http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{args.port}")
    print("  Help:      python ocr9.py -h")
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    # -h / --version 不加载 Streamlit，直接打印说明
    if any(a in ("-h", "--help", "-v", "--version") for a in sys.argv[1:]):
        raise SystemExit(main())
    if _is_streamlit_script_run():
        render_app()
    else:
        raise SystemExit(main())

