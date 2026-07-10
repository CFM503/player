#!/usr/bin/env python3
"""
align_to_template.py
---------------------
将手填照片(如手机拍摄、带透视畸变)中的表格四角，对齐到模板图片中表格的四角，
输出一张与模板画布尺寸完全一致、表格可以完全重叠的新图片。

用法示例：

1) 全自动模式（脚本自动检测两张图里最大的矩形/表格轮廓作为四个角点）：
    python3 align_to_template.py \
        --template dq123.png \
        --input 4455667788.jpg \
        --output aligned.png

2) 手动指定角点模式（当自动检测不准确时，可以手动提供四个角点坐标）：
    自己在图片查看器里读出四个角点像素坐标，顺序不限（脚本会自动按 左上/右上/右下/左下 排序）
    python3 align_to_template.py \
        --template dq123.png \
        --input 4455667788.jpg \
        --output aligned.png \
        --src-points "563,684 435,3631 2584,3586 2498,755" \
        --dst-points "42,216 1933,216 1933,2754 42,2754"

3) 调试模式：额外输出角点标注图，方便肉眼核对检测是否准确
    python3 align_to_template.py --template dq123.png --input 4455667788.jpg --output aligned.png --debug

4) 输出叠加对比图（半透明叠加模板和对齐后的照片，方便验证是否重叠）：
    python3 align_to_template.py --template dq123.png --input 4455667788.jpg --output aligned.png --overlay overlay.png
"""

import argparse
import sys

import cv2
import numpy as np


def _imread(path: str) -> np.ndarray:
    """支持中文路径的图片读取（cv2.imread 在 Windows 中文路径下会返回 None）"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def _imwrite(path: str, img: np.ndarray) -> bool:
    """支持中文路径的图片写入"""
    ret, buf = cv2.imencode(path[path.rfind('.'):], img)
    if ret:
        buf.tofile(path)
    return ret


def order_points(pts: np.ndarray) -> np.ndarray:
    """将任意顺序的4个点，按照 左上、右上、右下、左下 的顺序重新排列。"""
    pts = pts.astype("float32")
    rect = np.zeros((4, 2), dtype="float32")

    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # top-left：x+y 最小
    rect[2] = pts[np.argmax(s)]  # bottom-right：x+y 最大

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right：x-y 最小
    rect[3] = pts[np.argmax(diff)]  # bottom-left：x-y 最大
    return rect


def detect_quad(image: np.ndarray, min_area_ratio: float = 0.15):
    """
    自动检测图片中面积最大的四边形轮廓（用于定位表格/纸张边框）。
    同时尝试两种策略：
      1) Canny 边缘检测：适合手机拍照场景（纸张与背景有明显对比）
      2) 二值化阈值：适合扫描件/生成模板（表格黑色边框线）
    返回：排序后的四个角点 (4,2) ndarray，以及该轮廓占图片总面积的比例。
    若未找到合适的四边形，返回 (None, 0)。
    """
    h, w = image.shape[:2]
    total_area = h * w
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    candidate_contours = []

    # 策略一：Canny 边缘
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidate_contours.extend(cnts)

    # 策略二：二值化阈值（找深色边框线）
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    thresh = cv2.dilate(thresh, np.ones((7, 7), np.uint8), iterations=2)
    cnts2, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidate_contours.extend(cnts2)

    best_quad = None
    best_area = 0
    for c in candidate_contours:
        area = cv2.contourArea(c)
        if area < total_area * min_area_ratio:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and area > best_area:
            best_quad = approx.reshape(4, 2)
            best_area = area

    if best_quad is None:
        return None, 0.0

    return order_points(best_quad), best_area / total_area


def align_by_features(template: np.ndarray, src_img: np.ndarray,
                      min_matches: int = 15) -> np.ndarray | None:
    """
    当四边形轮廓检测失败时，使用 ORB 特征点匹配求单应矩阵，
    直接将 src_img 透视变换到 template 坐标空间。
    返回对齐后的图像，若特征匹配不足则返回 None。
    """
    th, tw = template.shape[:2]
    g_tmpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    g_src  = cv2.cvtColor(src_img,  cv2.COLOR_BGR2GRAY)

    # 缩放到同等分辨率，加快特征提取
    scale  = min(1.0, 1200 / max(g_src.shape))
    if scale < 1.0:
        g_src_s = cv2.resize(g_src, None, fx=scale, fy=scale)
    else:
        g_src_s = g_src
        scale   = 1.0

    orb = cv2.ORB_create(nfeatures=3000)
    kp1, des1 = orb.detectAndCompute(g_tmpl, None)
    kp2, des2 = orb.detectAndCompute(g_src_s, None)

    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        print("[特征匹配] 特征点不足，无法匹配", file=sys.stderr)
        return None

    bf      = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    # Lowe's ratio test
    good = [m for m, n in matches if m.distance < 0.75 * n.distance]
    print(f"[特征匹配] 有效匹配点数: {len(good)} / {len(matches)}", file=sys.stderr)

    if len(good) < min_matches:
        print(f"[特征匹配] 有效匹配点数({len(good)})不足 {min_matches}，匹配失败", file=sys.stderr)
        return None

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good]) / scale  # 还原到原始尺寸

    H, mask = cv2.findHomography(pts2, pts1, cv2.RANSAC, 5.0)
    if H is None:
        print("[特征匹配] RANSAC 单应矩阵求解失败", file=sys.stderr)
        return None

    inliers = int(mask.sum()) if mask is not None else 0
    print(f"[特征匹配] RANSAC 内点数: {inliers} / {len(good)}", file=sys.stderr)
    if inliers < 8:
        print("[特征匹配] 内点数不足，结果不可靠", file=sys.stderr)
        return None

    aligned = cv2.warpPerspective(
        src_img, H, (tw, th),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return aligned


def parse_points(s: str) -> np.ndarray:
    """解析形如 'x1,y1 x2,y2 x3,y3 x4,y4' 的字符串为 (4,2) ndarray"""
    pts = []
    for token in s.replace(";", " ").split():
        x_str, y_str = token.split(",")
        pts.append([float(x_str), float(y_str)])
    if len(pts) != 4:
        raise ValueError(f"需要正好4个点，实际解析到 {len(pts)} 个：{s}")
    return order_points(np.array(pts, dtype="float32"))


def draw_quad(image: np.ndarray, quad: np.ndarray, color=(0, 0, 255)):
    out = image.copy()
    pts = quad.astype(int)
    cv2.polylines(out, [pts], True, color, max(2, image.shape[1] // 400))
    labels = ["TL", "TR", "BR", "BL"]
    for (x, y), label in zip(pts, labels):
        cv2.circle(out, (x, y), max(6, image.shape[1] // 200), (0, 255, 0), -1)
        cv2.putText(out, label, (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX,
                    image.shape[1] / 1000, (255, 0, 0), max(2, image.shape[1] // 500))
    return out


def main():
    parser = argparse.ArgumentParser(
        description="将手填表格照片按四角对齐到模板图片（透视变换）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--template", required=True, help="模板图片路径（如 dq123.png）")
    parser.add_argument("--input", required=True, help="手填照片路径（如 4455667788.jpg）")
    parser.add_argument("--output", required=True, help="输出对齐后图片路径")
    parser.add_argument("--src-points", default=None,
                        help="手动指定照片中表格四个角点，格式 'x1,y1 x2,y2 x3,y3 x4,y4'")
    parser.add_argument("--dst-points", default=None,
                        help="手动指定模板中表格四个角点，格式同上")
    parser.add_argument("--min-area-ratio", type=float, default=0.15,
                        help="自动检测时，轮廓面积占图片总面积的最小比例阈值，默认0.15")
    parser.add_argument("--debug", action="store_true",
                        help="额外保存角点标注图（<output>_debug_src.png / _debug_dst.png），用于人工核对")
    parser.add_argument("--overlay", default=None,
                        help="额外输出一张模板与对齐结果的半透明叠加对比图路径")
    args = parser.parse_args()

    template = _imread(args.template)
    src_img  = _imread(args.input)

    if template is None:
        sys.exit(f"错误：无法读取模板图片 {args.template}")
    if src_img is None:
        sys.exit(f"错误：无法读取输入图片 {args.input}")

    th, tw = template.shape[:2]

    # ---- 获取模板中表格的四个角点 ----
    if args.dst_points:
        dst_quad = parse_points(args.dst_points)
        print(f"[模板] 使用手动指定的角点：\n{dst_quad}")
    else:
        dst_quad, ratio = detect_quad(template, args.min_area_ratio)
        if dst_quad is None:
            sys.exit(
                "错误：未能在模板图片中自动检测到表格边框。\n"
                "请使用 --dst-points 手动指定四个角点坐标，例如：\n"
                '  --dst-points "42,216 1933,216 1933,2754 42,2754"'
            )
        print(f"[模板] 自动检测到表格边框（占图片面积 {ratio:.1%}）：\n{dst_quad}")

    # ---- 获取照片中表格的四个角点 ----
    feature_fallback = False
    if args.src_points:
        src_quad = parse_points(args.src_points)
        print(f"[照片] 使用手动指定的角点：\n{src_quad}")
    else:
        src_quad, ratio = detect_quad(src_img, args.min_area_ratio)
        if src_quad is None:
            print(
                "[照片] 四边形轮廓检测失败，尝试 ORB 特征点匹配兜底...",
                file=sys.stderr
            )
            feature_fallback = True
        else:
            print(f"[照片] 自动检测到表格边框（占图片面积 {ratio:.1%}）：\n{src_quad}")

    if args.debug:
        debug_src_path = args.output + "_debug_src.png"
        debug_dst_path = args.output + "_debug_dst.png"
        if not feature_fallback:
            _imwrite(debug_src_path, draw_quad(src_img, src_quad))
        _imwrite(debug_dst_path, draw_quad(template, dst_quad))
        print(f"[调试] 已保存角点标注图：{debug_src_path} , {debug_dst_path}")
        print("       请打开查看红框绿点是否准确落在表格四角，若不准确请改用 --src-points/--dst-points 手动指定")

    # ---- 计算透视变换矩阵，并将照片warp到模板画布大小 ----
    if feature_fallback:
        # 使用特征匹配直接求单应矩阵
        aligned = align_by_features(template, src_img)
        if aligned is None:
            sys.exit(
                "错误：ORB 特征匹配也失败，无法对齐照片。\n"
                "请使用 --src-points 手动指定照片中表格的四个角点坐标。"
            )
        print("[照片] 特征匹配对齐成功")
    else:
        M = cv2.getPerspectiveTransform(src_quad, dst_quad)
        aligned = cv2.warpPerspective(
            src_img, M, (tw, th),
            flags=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )

    _imwrite(args.output, aligned)
    print(f"完成：已生成对齐后的图片 -> {args.output} （尺寸与模板一致：{tw}x{th}）")

    if args.overlay:
        # 半透明叠加：模板轮廓线（红）叠加在对齐后的照片上，便于肉眼核对是否完全重叠
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(template_gray, 50, 150)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        overlay_img = aligned.copy()
        overlay_img[edges > 0] = (0, 0, 255)  # 模板边线标红，叠加在对齐后的照片上
        _imwrite(args.overlay, overlay_img)
        print(f"完成：已生成叠加对比图 -> {args.overlay}")


if __name__ == "__main__":
    main()
