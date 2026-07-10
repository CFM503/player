# -*- coding: utf-8 -*-
"""
表格线去除工具（ocr6 第一次测试成功的算法）

算法：长横线/竖线开运算提取表格线 + inpaint 图像修复修补。
"""
import os
import sys
import argparse
import cv2
import numpy as np


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


def detect_table_lines(gray, min_h_ratio=0.12, min_v_ratio=0.08):
    """用形态学开运算提取长横线/竖线。"""
    h, w = gray.shape
    inv = 255 - gray
    _, bw = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 横线
    h_len = max(40, int(w * min_h_ratio))
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel, iterations=1)
    horiz = cv2.dilate(horiz, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

    # 竖线
    v_len = max(30, int(h * min_v_ratio))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel, iterations=1)
    vert = cv2.dilate(vert, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

    lines = cv2.bitwise_or(horiz, vert)
    return lines, horiz, vert


def remove_table_lines(img_bgr, strength=1):
    """去掉表格线，返回去线后的 BGR 图与线 mask。"""
    if img_bgr.ndim == 2:
        gray = img_bgr
        bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    else:
        bgr = img_bgr.copy()
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    min_h = 0.10 if strength <= 1 else 0.07
    min_v = 0.07 if strength <= 1 else 0.05
    lines, _, _ = detect_table_lines(gray, min_h_ratio=min_h, min_v_ratio=min_v)

    if strength >= 2:
        lines = cv2.dilate(lines, np.ones((3, 3), np.uint8), iterations=1)

    mask = (lines > 0).astype(np.uint8) * 255
    radius = 3 if max(gray.shape) < 2000 else 4
    result = cv2.inpaint(bgr, mask, inpaintRadius=radius, flags=cv2.INPAINT_TELEA)

    # 二次清洗
    g2 = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    residual, _, _ = detect_table_lines(g2, min_h_ratio=min_h + 0.02, min_v_ratio=min_v + 0.02)
    residual = cv2.bitwise_and(residual, cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1))
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

    parser = argparse.ArgumentParser(description="去掉作业票对齐图中的表格线")
    parser.add_argument("input", nargs="?", default=None)
    parser.add_argument("-i", "--input", dest="input_flag", default=None)
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--strength", type=int, choices=(1, 2), default=1)
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

    result, mask = remove_table_lines(img, strength=args.strength)

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
