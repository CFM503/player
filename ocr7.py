# -*- coding: utf-8 -*-
"""
表格线去除工具（ocr7 优化版）

算法：局部自适应阈值分割 + 交叉膨胀处理轻微倾斜 + 形态学开运算提取表格线 + inpaint 图像修补。
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


def detect_table_lines(gray, min_h_ratio=0.12, min_v_ratio=0.08, C_val=3):
    """自适应阈值分割 + 交叉膨胀处理倾斜线，提取长横线/竖线。"""
    h, w = gray.shape

    # 1. 局部自适应阈值，有效应对阴影与纸面光照不均
    bw = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=51,
        C=C_val
    )

    # 2. 动态内核计算
    h_len = max(40, int(w * min_h_ratio))
    v_len = max(30, int(h * min_v_ratio))

    # 3. 提取横线：利用垂直核预膨胀应对线条微倾斜，水平核桥接间隙，然后开运算提取
    thicken_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 3))
    bridge_h = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1))
    
    bw_h = cv2.dilate(bw, thicken_v, iterations=1)
    bw_h = cv2.dilate(bw_h, bridge_h, iterations=1)
    
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    horiz = cv2.morphologyEx(bw_h, cv2.MORPH_OPEN, h_kernel, iterations=1)
    horiz = cv2.erode(horiz, thicken_v, iterations=1)
    horiz = cv2.dilate(horiz, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

    # 4. 提取竖线：利用水平核预膨胀应对线条微倾斜，垂直核桥接间隙，然后开运算提取
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


def remove_table_lines(img_bgr, strength=1):
    """去掉表格线，返回去线后的 BGR 图与线 mask。"""
    if img_bgr.ndim == 2:
        gray = img_bgr
        bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    else:
        bgr = img_bgr.copy()
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    min_h = 0.10 if strength <= 1 else 0.08
    min_v = 0.07 if strength <= 1 else 0.06
    c_val = 3 if strength <= 1 else 2
    
    lines, _, _ = detect_table_lines(gray, min_h_ratio=min_h, min_v_ratio=min_v, C_val=c_val)

    mask = (lines > 0).astype(np.uint8) * 255
    radius = 3 if max(gray.shape) < 2000 else 4
    result = cv2.inpaint(bgr, mask, inpaintRadius=radius, flags=cv2.INPAINT_TELEA)

    # 二次清洗：微调参数擦除残留细表线
    g2 = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    c_val2 = 5 if strength <= 1 else 4
    lines2, _, _ = detect_table_lines(g2, min_h_ratio=min_h, min_v_ratio=min_v, C_val=c_val2)
    residual = (lines2 > 0).astype(np.uint8) * 255
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
