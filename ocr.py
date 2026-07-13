# -*- coding: utf-8 -*-
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
import cv2
import argparse
from typing import List, Dict, Any, Optional, Tuple
import numpy as np


# ---------------------------------------------------------------------------
# 图像裁剪 / 表格格式化
# ---------------------------------------------------------------------------

def crop_image(image_path: str, x: int, y: int, w: int, h: int, save_crop_path: Optional[str] = None):
    """裁剪图片区域，可选择性保存子图。"""
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
        polys = res.get("rec_polys", []) or []
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
                    y_center = (box[0][1] + box[2][1]) / 2
                    x_left = box[0][0]
                    height = abs(box[2][1] - box[0][1])
                    width = abs(box[1][0] - box[0][0]) if len(box) >= 2 else 0
                else:
                    y_center, x_left, height, width = 0, 0, 20, 0
                entries.append({
                    "text": text, "y": y_center, "x": x_left, "h": height, "w": width,
                })

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
