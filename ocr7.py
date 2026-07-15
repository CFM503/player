# -*- coding: utf-8 -*-
# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
"""
表格线去除工具（ocr7）

算法：局部自适应阈值分割 + 交叉膨胀处理轻微倾斜 + 形态学开运算提取表格线 + inpaint 图像修补。

【票型永远分离】
  - 带气作业票：画布约 1052×1487，25×5 确认格更密 → 去线参数偏强、内核比例按带气标定
  - 动火作业票：画布约 1000×1414，21 条单列确认 → 独立参数，避免与带气共用导致过擦/欠擦
  禁止混用一套默认阈值。

用法：
  python ocr7.py -i aligned_gas.png --ticket-type 带气作业票
  python ocr7.py -i aligned_fire.png --ticket-type 动火作业票
"""
import os
import sys
import argparse
import cv2
import numpy as np

# ---------------------------------------------------------------------------
# 票型 profile（带气 / 动火分离）
# ---------------------------------------------------------------------------
TICKET_GAS = "带气作业票"
TICKET_FIRE = "动火作业票"

# strength=1 / strength=2 两档；动火表格线更密时略调 C 与比例
LINE_PROFILES = {
    TICKET_GAS: {
        "label": "带气",
        "ref_size": (1052, 1487),
        # strength 1
        "min_h_ratio_1": 0.10,
        "min_v_ratio_1": 0.07,
        "c_val_1": 3,
        "c_val2_1": 5,
        # strength 2（更激进）
        "min_h_ratio_2": 0.08,
        "min_v_ratio_2": 0.06,
        "c_val_2": 2,
        "c_val2_2": 4,
        "block_size": 51,
        "inpaint_radius_small": 3,
        "inpaint_radius_large": 4,
        "size_large_thresh": 2000,
        "residual_dilate": 5,
    },
    TICKET_FIRE: {
        "label": "动火",
        "ref_size": (1000, 1414),
        # 动火 1000 宽、线网与带气不同：横线内核略短、竖线比例略高，减少擦掉勾选笔画
        "min_h_ratio_1": 0.11,
        "min_v_ratio_1": 0.08,
        "c_val_1": 4,
        "c_val2_1": 6,
        "min_h_ratio_2": 0.09,
        "min_v_ratio_2": 0.07,
        "c_val_2": 3,
        "c_val2_2": 5,
        "block_size": 45,
        "inpaint_radius_small": 2,
        "inpaint_radius_large": 3,
        "size_large_thresh": 1600,
        "residual_dilate": 4,
    },
}


def resolve_ticket_type(ticket_type=None, img_w=0, img_h=0, path=""):
    """解析票型：显式 > 路径关键字 > 画布尺寸推断 > 默认带气。"""
    s = (ticket_type or "").strip()
    if s in LINE_PROFILES:
        return s
    if "动火" in s or s.lower() in ("fire", "hot", "dh"):
        return TICKET_FIRE
    if "带气" in s or s.lower() in ("gas", "dq"):
        return TICKET_GAS
    base = os.path.basename(path or "").lower()
    if "dh" in base or "动火" in base:
        return TICKET_FIRE
    if "dq" in base or "带气" in base:
        return TICKET_GAS
    if img_w and img_h:
        if abs(img_w - 1000) <= 40 and abs(img_h - 1414) <= 60:
            return TICKET_FIRE
        if abs(img_w - 1052) <= 40 and abs(img_h - 1487) <= 60:
            return TICKET_GAS
    return TICKET_GAS


def get_line_profile(ticket_type):
    tt = resolve_ticket_type(ticket_type)
    return dict(LINE_PROFILES.get(tt) or LINE_PROFILES[TICKET_GAS])


def imread_unicode(path, flags=cv2.IMREAD_COLOR):
    """支持中文路径的 imread。"""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite_unicode(path, img):
    """支持中文路径的 imwrite。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    buf.tofile(path)
    return True


def detect_table_lines(
    gray,
    min_h_ratio=0.12,
    min_v_ratio=0.08,
    C_val=3,
    block_size=51,
):
    """自适应阈值分割 + 交叉膨胀处理倾斜线，提取长横线/竖线。"""
    h, w = gray.shape

    # blockSize 须为奇数且 >=3
    bs = int(block_size) if block_size and int(block_size) >= 3 else 51
    if bs % 2 == 0:
        bs += 1

    # 1. 局部自适应阈值，有效应对阴影与纸面光照不均
    bw = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=bs,
        C=C_val,
    )

    # 2. 动态内核计算
    h_len = max(40, int(w * min_h_ratio))
    v_len = max(30, int(h * min_v_ratio))

    # 3. 提取横线
    thicken_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 3))
    bridge_h = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1))

    bw_h = cv2.dilate(bw, thicken_v, iterations=1)
    bw_h = cv2.dilate(bw_h, bridge_h, iterations=1)

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    horiz = cv2.morphologyEx(bw_h, cv2.MORPH_OPEN, h_kernel, iterations=1)
    horiz = cv2.erode(horiz, thicken_v, iterations=1)
    horiz = cv2.dilate(horiz, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

    # 4. 提取竖线
    thicken_h = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
    bridge_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5))

    bw_v = cv2.dilate(bw, thicken_h, iterations=1)
    bw_v = cv2.dilate(bw_v, bridge_v, iterations=1)

    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    vert = cv2.morphologyEx(bw_v, cv2.MORPH_OPEN, v_kernel, iterations=1)
    vert = cv2.erode(vert, thicken_h, iterations=1)
    vert = cv2.dilate(vert, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

    lines = cv2.bitwise_or(horiz, vert)
    return lines, horiz, vert


def remove_table_lines(img_bgr, strength=1, ticket_type=None):
    """去掉表格线，返回去线后的 BGR 图与线 mask。

    ticket_type: 带气作业票 / 动火作业票；未指定时按图像尺寸推断。
    带气、动火使用独立 LINE_PROFILES，禁止混参。
    """
    if img_bgr.ndim == 2:
        gray = img_bgr
        bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    else:
        bgr = img_bgr.copy()
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    h, w = gray.shape[:2]
    tt = resolve_ticket_type(ticket_type, w, h)
    prof = get_line_profile(tt)
    strength = 1 if strength is None else int(strength)
    skey = "1" if strength <= 1 else "2"

    min_h = float(prof[f"min_h_ratio_{skey}"])
    min_v = float(prof[f"min_v_ratio_{skey}"])
    c_val = int(prof[f"c_val_{skey}"])
    c_val2 = int(prof[f"c_val2_{skey}"])
    block_size = int(prof.get("block_size", 51))
    dil_k = int(prof.get("residual_dilate", 5))

    lines, _, _ = detect_table_lines(
        gray,
        min_h_ratio=min_h,
        min_v_ratio=min_v,
        C_val=c_val,
        block_size=block_size,
    )

    mask = (lines > 0).astype(np.uint8) * 255
    thr = int(prof.get("size_large_thresh", 2000))
    radius = (
        int(prof.get("inpaint_radius_large", 4))
        if max(gray.shape) >= thr
        else int(prof.get("inpaint_radius_small", 3))
    )
    result = cv2.inpaint(bgr, mask, inpaintRadius=radius, flags=cv2.INPAINT_TELEA)

    # 二次清洗：微调参数擦除残留细表线
    g2 = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    lines2, _, _ = detect_table_lines(
        g2,
        min_h_ratio=min_h,
        min_v_ratio=min_v,
        C_val=c_val2,
        block_size=block_size,
    )
    residual = (lines2 > 0).astype(np.uint8) * 255
    residual = cv2.bitwise_and(
        residual,
        cv2.dilate(mask, np.ones((dil_k, dil_k), np.uint8), iterations=1),
    )

    result[residual > 0] = (255, 255, 255)

    return result, mask


def default_output_path(input_path):
    root, _ = os.path.splitext(input_path)
    return root + "去表格化.png"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="去掉作业票对齐图中的表格线（带气/动火参数分离）"
    )
    parser.add_argument("input", nargs="?", default=None)
    parser.add_argument("-i", "--input", dest="input_flag", default=None)
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--strength", type=int, choices=(1, 2), default=1)
    parser.add_argument(
        "--ticket-type",
        default=None,
        choices=[
            TICKET_GAS, TICKET_FIRE,
            "gas", "fire", "带气", "动火",
        ],
        help="票型：带气作业票 / 动火作业票（决定去线参数；默认识别图尺寸）",
    )
    args = parser.parse_args()

    image_path = args.input_flag or args.input
    if not image_path:
        parser.error("请提供输入图像路径")

    if not os.path.isfile(image_path):
        print(f"Error: 文件不存在: {image_path}", file=sys.stderr)
        sys.exit(1)

    img = imread_unicode(image_path, cv2.IMREAD_COLOR)
    if img is None:
        print(f"Error: 无法读取图像: {image_path}", file=sys.stderr)
        sys.exit(1)

    h, w = img.shape[:2]
    tt_raw = args.ticket_type
    if tt_raw in ("gas", "带气"):
        tt_raw = TICKET_GAS
    elif tt_raw in ("fire", "动火"):
        tt_raw = TICKET_FIRE
    ticket_type = resolve_ticket_type(tt_raw, w, h, image_path)
    prof = get_line_profile(ticket_type)
    print(
        f"[票型] {ticket_type}（{prof['label']}）| 画布 {w}x{h} | "
        f"strength={args.strength} | 去线参数独立于另一票型"
    )

    result, mask = remove_table_lines(
        img, strength=args.strength, ticket_type=ticket_type
    )

    out_path = args.output or default_output_path(image_path)
    if not imwrite_unicode(out_path, result):
        print(f"Error: 写入失败: {out_path}", file=sys.stderr)
        sys.exit(1)

    line_px = int((mask > 0).sum())
    print(f"输入: {image_path}")
    print(f"输出: {out_path}")
    print(f"表格线擦除像素数: {line_px}")


if __name__ == "__main__":
    main()
