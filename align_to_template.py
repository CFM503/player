#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
align_to_template.py
---------------------
将手填照片(手机拍摄、带透视畸变)中的表格四角，对齐到模板图片坐标系，
输出与模板画布尺寸一致、表格尽量重叠的新图片。

【票型分离】带气作业票 / 动火作业票使用独立对齐参数（取点策略、ORB、质量阈值），
禁止混用同一套默认值。可通过 --ticket-type 显式指定，或由模板文件名自动推断：
  template/dq.png → 带气作业票
  template/dh.png → 动火作业票

用法示例：

1) 带气全自动：
    python align_to_template.py --ticket-type 带气作业票 --template template/dq.png \\
        --input photo.jpg --output aligned.png

2) 动火全自动：
    python align_to_template.py --ticket-type 动火作业票 --template template/dh.png \\
        --input photo.jpg --output aligned.png

3) 手动角点：
    python align_to_template.py --template template/dq.png --input photo.jpg --output aligned.png \\
        --src-points "x1,y1 x2,y2 x3,y3 x4,y4"

4) 调试角点：
    python align_to_template.py --template template/dh.png --input photo.jpg --output aligned.png --debug
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# 票型对齐参数（完全分离：带气 ≠ 动火）
# ---------------------------------------------------------------------------
# 说明：
#   - 当前仓库模板：dq.png ≈ 1052×1487；dh.png ≈ 1000×1414（与 agent 规范画布一致）
#   - 此处参数只影响「取点 / 透视 / ORB」；业务签字 ROI 在 agent_core.TICKET_TEMPLATE_SPEC
#   - 带气 / 动火两套 profile 禁止混用
TICKET_TYPE_GAS = "带气作业票"
TICKET_TYPE_FIRE = "动火作业票"

ALIGN_PROFILES = {
    TICKET_TYPE_GAS: {
        "label": "带气",
        "template_files": ("dq.png",),
        "canvas_size": (1052, 1487),  # 与 dq.png 一致
        # 轮廓取框
        "min_area_ratio": 0.12,
        "quad_min_qscore": 0.50,
        "quad_penalty": 0.15,  # 劣质四点在排序中的降权
        # ORB
        "orb_nfeatures": 5000,
        "orb_src_max_side": 1400,
        "orb_min_matches": 20,
        "orb_min_inliers": 15,
        "orb_ratio_test": 0.70,
        "orb_ransac_thresh": 3.0,
        "orb_score_bonus": 0.02,  # 同分略偏好 ORB
        "prefer_method": "auto",  # auto | quad | orb
    },
    TICKET_TYPE_FIRE: {
        "label": "动火",
        "template_files": ("dh.png",),
        "canvas_size": (1000, 1414),  # 与当前 dh.png 一致
        # 动火表格布局独立：面积比 / ORB 与带气分离
        "min_area_ratio": 0.10,
        "quad_min_qscore": 0.45,
        "quad_penalty": 0.18,
        "orb_nfeatures": 5500,
        "orb_src_max_side": 1600,
        "orb_min_matches": 22,
        "orb_min_inliers": 16,
        "orb_ratio_test": 0.72,
        "orb_ransac_thresh": 3.5,
        "orb_score_bonus": 0.04,  # 动火歪图四点易偏，更偏好 ORB
        "prefer_method": "auto",
    },
}


def resolve_ticket_type(ticket_type: str | None, template_path: str) -> str:
    """解析票型：显式参数优先，否则按模板文件名推断。"""
    s = (ticket_type or "").strip()
    if s in ALIGN_PROFILES:
        return s
    if "动火" in s:
        return TICKET_TYPE_FIRE
    if "带气" in s:
        return TICKET_TYPE_GAS
    # 由模板路径推断
    base = os.path.basename(template_path or "").lower()
    if base == "dh.png" or "dh" == os.path.splitext(base)[0]:
        return TICKET_TYPE_FIRE
    if base == "dq.png" or "dq" == os.path.splitext(base)[0]:
        return TICKET_TYPE_GAS
    # 默认带气（历史主路径）
    return TICKET_TYPE_GAS


def get_align_profile(ticket_type: str) -> dict:
    return dict(ALIGN_PROFILES.get(ticket_type) or ALIGN_PROFILES[TICKET_TYPE_GAS])


def _force_utf8_stdio() -> None:
    """子进程被父进程管道捕获时，强制 stdout/stderr 为 UTF-8，避免 Web 日志中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _imread(path: str) -> np.ndarray:
    """支持中文路径的图片读取"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def _imwrite(path: str, img: np.ndarray) -> bool:
    """支持中文路径的图片写入"""
    ret, buf = cv2.imencode(path[path.rfind("."):], img)
    if ret:
        buf.tofile(path)
    return ret


def order_points(pts: np.ndarray) -> np.ndarray:
    """
    将 4 点排成 TL, TR, BR, BL。
    先用中心角排序，再用 sum/diff 校正，减少严重透视下的错序。
    """
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    order = np.argsort(ang)
    # 从左上开始：在角排序环上找 x+y 最小的点作为起点
    ordered = pts[order]
    start = int(np.argmin(ordered.sum(axis=1)))
    ordered = np.roll(ordered, -start, axis=0)

    # 验证是否大致为 TL,TR,BR,BL（顺时针或逆时针）
    # 若第二点在第一点左侧太多，可能逆序，反转 1..3
    if ordered[1, 0] < ordered[0, 0] and ordered[3, 0] > ordered[0, 0]:
        ordered = np.array([ordered[0], ordered[3], ordered[2], ordered[1]], dtype=np.float32)

    # 二次用经典方法 refine（对接近矩形更稳）
    s = ordered.sum(axis=1)
    d = np.diff(ordered, axis=1).reshape(-1)
    tl = ordered[np.argmin(s)]
    br = ordered[np.argmax(s)]
    tr = ordered[np.argmin(d)]
    bl = ordered[np.argmax(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def axis_aligned_quad(quad: np.ndarray) -> np.ndarray:
    """将任意四边形收成轴对齐外接矩形（用于已是正视图的模板图，避免检测抖动引入歪斜）。"""
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    x0, y0 = float(q[:, 0].min()), float(q[:, 1].min())
    x1, y1 = float(q[:, 0].max()), float(q[:, 1].max())
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)


def _rect_score(quad: np.ndarray, img_shape, target_aspect: float | None = None) -> float:
    """
    四边形质量分：越大越好。
    惩罚：过扁、非凸、面积太小、边长极不对称、顶边/底边斜率过大。
    """
    q = order_points(quad)
    h, w = img_shape[:2]
    area = cv2.contourArea(q.astype(np.float32))
    if area < 1:
        return -1e9
    area_ratio = area / float(h * w)

    # 边长
    def L(i, j):
        return float(np.linalg.norm(q[i] - q[j]))

    top, right, bot, left = L(0, 1), L(1, 2), L(2, 3), L(3, 0)
    if min(top, right, bot, left) < 10:
        return -1e9

    # 对边长度比接近 1 更好
    hr = min(top, bot) / max(top, bot)
    vr = min(left, right) / max(left, right)

    # 宽高比
    bw = (top + bot) / 2.0
    bh = (left + right) / 2.0
    aspect = bw / max(bh, 1e-6)
    asp_pen = 0.0
    if target_aspect and target_aspect > 0:
        # 票面高>宽，aspect 约 0.7
        ratio = aspect / target_aspect
        if ratio < 0.55 or ratio > 1.8:
            asp_pen = 2.0
        else:
            asp_pen = abs(np.log(ratio)) * 0.5

    # 顶边/底边应接近水平（照片里可有透视，但不能极端）
    top_slope = abs(q[1, 1] - q[0, 1]) / max(abs(q[1, 0] - q[0, 0]), 1.0)
    bot_slope = abs(q[2, 1] - q[3, 1]) / max(abs(q[2, 0] - q[3, 0]), 1.0)
    slope_pen = max(0.0, top_slope - 0.35) + max(0.0, bot_slope - 0.35)

    # 凸性
    hull = cv2.convexHull(q.reshape(-1, 1, 2))
    hull_area = cv2.contourArea(hull)
    convexity = area / max(hull_area, 1.0)

    score = (
        area_ratio * 3.0
        + hr * 1.2
        + vr * 1.2
        + convexity * 1.0
        - asp_pen
        - slope_pen * 1.5
    )
    return float(score)


def detect_quad(image: np.ndarray, min_area_ratio: float = 0.12,
                target_aspect: float | None = None):
    """
    自动检测表格/纸张四边形。多策略 + 打分选最优，避免误抓到内框或歪边。
    返回：(排序后的四点, 面积占比)；失败 (None, 0)。
    """
    h, w = image.shape[:2]
    total_area = float(h * w)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 轻度均衡，减轻阴影
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray_eq = clahe.apply(gray)

    candidates = []  # (quad, area_ratio)

    def _collect_from_binary(bin_img, dilate_k=5, dilate_iter=2):
        k = np.ones((dilate_k, dilate_k), np.uint8)
        edges = cv2.dilate(bin_img, k, iterations=dilate_iter)
        cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < total_area * min_area_ratio:
                continue
            if area > total_area * 0.98:
                continue  # 整图边框
            peri = cv2.arcLength(c, True)
            for eps in (0.015, 0.02, 0.03, 0.04, 0.055):
                approx = cv2.approxPolyDP(c, eps * peri, True)
                if len(approx) == 4:
                    q = order_points(approx.reshape(4, 2))
                    candidates.append((q, area / total_area))
                    break
            # 非严格 4 点：用最小外接矩形
            rect = cv2.minAreaRect(c)
            box = cv2.boxPoints(rect)
            q = order_points(box)
            ar = area / total_area
            if ar >= min_area_ratio:
                candidates.append((q, ar))

    # 策略1：Canny
    blur = cv2.GaussianBlur(gray_eq, (5, 5), 0)
    for lo, hi in ((30, 100), (50, 150), (80, 200)):
        edges = cv2.Canny(blur, lo, hi)
        _collect_from_binary(edges, dilate_k=5, dilate_iter=2)

    # 策略2：自适应阈值
    thr = cv2.adaptiveThreshold(
        gray_eq, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8
    )
    _collect_from_binary(thr, dilate_k=5, dilate_iter=1)

    # 策略3：Otsu
    _, otsu = cv2.threshold(gray_eq, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _collect_from_binary(otsu, dilate_k=7, dilate_iter=2)

    if not candidates:
        return None, 0.0

    best_q, best_s, best_ar = None, -1e18, 0.0
    for q, ar in candidates:
        s = _rect_score(q, image.shape, target_aspect=target_aspect)
        # 面积也略加权
        s += ar * 0.3
        if s > best_s:
            best_s, best_q, best_ar = s, q, ar

    if best_q is None or best_s < -10:
        return None, 0.0
    return order_points(best_q), float(best_ar)


def align_by_features(
    template: np.ndarray,
    src_img: np.ndarray,
    profile: dict | None = None,
) -> tuple[np.ndarray | None, dict]:
    """
    ORB 特征匹配求单应矩阵。返回 (aligned, info)。
    参数由票型 profile 控制（带气 / 动火分离）。
    """
    prof = profile or ALIGN_PROFILES[TICKET_TYPE_GAS]
    min_matches = int(prof.get("orb_min_matches", 20))
    min_inliers = int(prof.get("orb_min_inliers", 15))
    nfeatures = int(prof.get("orb_nfeatures", 5000))
    src_max_side = float(prof.get("orb_src_max_side", 1400))
    ratio_test = float(prof.get("orb_ratio_test", 0.70))
    ransac_thresh = float(prof.get("orb_ransac_thresh", 3.0))

    info = {
        "method": "orb",
        "inliers": 0,
        "good": 0,
        "ticket": prof.get("label", ""),
    }
    th, tw = template.shape[:2]
    g_tmpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    g_src = cv2.cvtColor(src_img, cv2.COLOR_BGR2GRAY)

    # 轻度均衡
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    g_tmpl = clahe.apply(g_tmpl)
    g_src = clahe.apply(g_src)

    scale = min(1.0, src_max_side / max(g_src.shape))
    if scale < 1.0:
        g_src_s = cv2.resize(g_src, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        g_src_s = g_src
        scale = 1.0

    orb = cv2.ORB_create(nfeatures=nfeatures, scaleFactor=1.2, nlevels=8)
    kp1, des1 = orb.detectAndCompute(g_tmpl, None)
    kp2, des2 = orb.detectAndCompute(g_src_s, None)

    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        print(f"[特征匹配][{prof.get('label')}] 特征点不足，无法匹配", file=sys.stderr)
        return None, info

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)
    good = []
    for pair in matches:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < ratio_test * n.distance:
            good.append(m)
    info["good"] = len(good)
    print(
        f"[特征匹配][{prof.get('label')}] 有效匹配点数: {len(good)} / {len(matches)}",
        file=sys.stderr,
    )

    if len(good) < min_matches:
        print(
            f"[特征匹配][{prof.get('label')}] 有效匹配点数({len(good)})不足 {min_matches}",
            file=sys.stderr,
        )
        return None, info

    # 取距离最好的前 N 个，减少噪声
    good = sorted(good, key=lambda m: m.distance)[: min(400, len(good))]

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good]) / scale

    H, mask = cv2.findHomography(
        pts2, pts1, cv2.RANSAC, ransacReprojThreshold=ransac_thresh, maxIters=5000
    )
    if H is None:
        print(f"[特征匹配][{prof.get('label')}] RANSAC 单应矩阵求解失败", file=sys.stderr)
        return None, info

    inliers = int(mask.sum()) if mask is not None else 0
    info["inliers"] = inliers
    print(
        f"[特征匹配][{prof.get('label')}] RANSAC 内点数: {inliers} / {len(good)}",
        file=sys.stderr,
    )
    if inliers < min_inliers:
        print(f"[特征匹配][{prof.get('label')}] 内点数不足({min_inliers})，结果不可靠", file=sys.stderr)
        return None, info

    # 单应矩阵病态检测：过大缩放/剪切
    try:
        det = abs(np.linalg.det(H[:2, :2]))
        if det < 0.05 or det > 20:
            print(f"[特征匹配][{prof.get('label')}] 单应行列式异常 det={det:.3f}，丢弃", file=sys.stderr)
            return None, info
    except Exception:
        pass

    aligned = cv2.warpPerspective(
        src_img, H, (tw, th),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return aligned, info


def edge_overlap_score(template: np.ndarray, aligned: np.ndarray) -> float:
    """模板边缘与对齐结果边缘的重合度（0~1），用于选择更好的对齐结果。"""
    g1 = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    e1 = cv2.Canny(g1, 50, 150) > 0
    e2 = cv2.Canny(g2, 50, 150) > 0
    # 膨胀后重合
    k = np.ones((3, 3), np.uint8)
    e1d = cv2.dilate(e1.astype(np.uint8), k, iterations=1).astype(bool)
    e2d = cv2.dilate(e2.astype(np.uint8), k, iterations=1).astype(bool)
    inter = np.logical_and(e1d, e2).sum()
    denom = max(int(e1.sum()), 1)
    return float(inter) / float(denom)


def parse_points(s: str) -> np.ndarray:
    pts = []
    for token in s.replace(";", " ").split():
        x_str, y_str = token.split(",")
        pts.append([float(x_str), float(y_str)])
    if len(pts) != 4:
        raise ValueError(f"需要正好4个点，实际解析到 {len(pts)} 个：{s}")
    return order_points(np.array(pts, dtype=np.float32))


def draw_quad(image: np.ndarray, quad: np.ndarray, color=(0, 0, 255)):
    out = image.copy()
    pts = quad.astype(int)
    cv2.polylines(out, [pts], True, color, max(2, image.shape[1] // 400))
    labels = ["TL", "TR", "BR", "BL"]
    for (x, y), label in zip(pts, labels):
        cv2.circle(out, (x, y), max(6, image.shape[1] // 200), (0, 255, 0), -1)
        cv2.putText(
            out, label, (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX,
            max(0.4, image.shape[1] / 1200), (255, 0, 0), max(1, image.shape[1] // 500),
        )
    return out


def warp_quad(src_img: np.ndarray, src_quad: np.ndarray, dst_quad: np.ndarray,
              out_w: int, out_h: int) -> np.ndarray:
    M = cv2.getPerspectiveTransform(
        src_quad.astype(np.float32), dst_quad.astype(np.float32)
    )
    return cv2.warpPerspective(
        src_img, M, (out_w, out_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def main():
    parser = argparse.ArgumentParser(
        description="将手填表格照片按四角对齐到模板图片（透视变换；带气/动火参数分离）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--template", required=True, help="模板图片路径（带气 dq.png / 动火 dh.png）")
    parser.add_argument("--input", required=True, help="手填照片路径")
    parser.add_argument("--output", required=True, help="输出对齐后图片路径")
    parser.add_argument(
        "--ticket-type",
        default=None,
        choices=[TICKET_TYPE_GAS, TICKET_TYPE_FIRE, "gas", "fire", "带气", "动火"],
        help="作业票类型：带气作业票 / 动火作业票（决定取点与 ORB 参数；默认识别模板文件名）",
    )
    parser.add_argument("--src-points", default=None,
                        help="手动指定照片四个角点 'x1,y1 x2,y2 x3,y3 x4,y4'")
    parser.add_argument("--dst-points", default=None,
                        help="手动指定模板四个角点（一般不必；模板会强制轴对齐）")
    parser.add_argument("--min-area-ratio", type=float, default=None,
                        help="轮廓面积占全图最小比例（默认随票型：带气 0.12 / 动火 0.10）")
    parser.add_argument("--debug", action="store_true",
                        help="保存角点调试图")
    parser.add_argument("--overlay", default=None,
                        help="输出模板边缘叠加对比图")
    parser.add_argument("--no-axis-align-template", action="store_true",
                        help="不对模板角点做轴对齐（默认会轴对齐，减少模板检测抖动导致的歪斜）")
    args = parser.parse_args()

    # ---- 票型锁定（带气 / 动火参数完全分离）----
    tt_raw = args.ticket_type
    if tt_raw in ("gas", "带气"):
        tt_raw = TICKET_TYPE_GAS
    elif tt_raw in ("fire", "动火"):
        tt_raw = TICKET_TYPE_FIRE
    ticket_type = resolve_ticket_type(tt_raw, args.template)
    profile = get_align_profile(ticket_type)
    min_area_ratio = (
        float(args.min_area_ratio)
        if args.min_area_ratio is not None
        else float(profile["min_area_ratio"])
    )
    print(
        f"[票型] {ticket_type}（{profile['label']}）| "
        f"min_area={min_area_ratio} ORB匹配≥{profile['orb_min_matches']} "
        f"内点≥{profile['orb_min_inliers']} 源图最长边≤{profile['orb_src_max_side']}"
    )

    template = _imread(args.template)
    src_img = _imread(args.input)
    if template is None:
        sys.exit(f"错误：无法读取模板图片 {args.template}")
    if src_img is None:
        sys.exit(f"错误：无法读取输入图片 {args.input}")

    th, tw = template.shape[:2]
    target_aspect = tw / float(th)  # 带气约 0.707；动火 2000/2827≈0.707
    print(f"[模板] 文件={os.path.basename(args.template)} 分辨率={tw}x{th} 宽高比={target_aspect:.3f}")

    # ---- 模板角点 ----
    if args.dst_points:
        dst_quad = parse_points(args.dst_points)
        print(f"[模板][{profile['label']}] 手动角点：\n{dst_quad}")
    else:
        dst_quad, ratio = detect_quad(template, min_area_ratio, target_aspect=target_aspect)
        if dst_quad is None:
            # 模板检测失败：使用整幅画布（模板本身即标准页）
            margin = 0
            dst_quad = np.array(
                [[margin, margin], [tw - 1 - margin, margin],
                 [tw - 1 - margin, th - 1 - margin], [margin, th - 1 - margin]],
                dtype=np.float32,
            )
            print(f"[模板][{profile['label']}] 未检出内框，使用整幅画布四角")
        else:
            print(f"[模板][{profile['label']}] 自动检出边框（面积比 {ratio:.1%}）：\n{dst_quad}")

    # 关键：模板已是正视图，强制轴对齐外接矩形，避免检测抖动导致顶边不水平→整图歪
    if not args.no_axis_align_template:
        before = dst_quad.copy()
        dst_quad = axis_aligned_quad(dst_quad)
        if not np.allclose(before, dst_quad, atol=1.5):
            print(f"[模板][{profile['label']}] 已轴对齐目标角点：\n{dst_quad}")

    # ---- 照片角点 / 特征对齐（参数随票型）----
    candidates = []  # (name, aligned_img, meta)
    prefer = str(profile.get("prefer_method") or "auto")

    src_quad = None
    if args.src_points:
        src_quad = parse_points(args.src_points)
        print(f"[照片][{profile['label']}] 手动角点：\n{src_quad}")
        aligned_q = warp_quad(src_img, src_quad, dst_quad, tw, th)
        sc = edge_overlap_score(template, aligned_q)
        candidates.append(("manual_quad", aligned_q, {"score": sc, "src_quad": src_quad}))
        print(f"[照片][{profile['label']}] 手动四点对齐 边缘重合={sc:.3f}")
    else:
        if prefer != "orb":
            src_quad, ratio = detect_quad(src_img, min_area_ratio, target_aspect=target_aspect)
            if src_quad is not None:
                qscore = _rect_score(src_quad, src_img.shape, target_aspect=target_aspect)
                print(
                    f"[照片][{profile['label']}] 自动检出边框"
                    f"（面积比 {ratio:.1%}，质量分 {qscore:.2f}）：\n{src_quad}"
                )
                aligned_q = warp_quad(src_img, src_quad, dst_quad, tw, th)
                sc = edge_overlap_score(template, aligned_q)
                candidates.append(
                    ("quad", aligned_q, {"score": sc, "qscore": qscore, "ratio": ratio})
                )
                print(f"[照片][{profile['label']}] 四点透视对齐 边缘重合={sc:.3f}")
            else:
                print(f"[照片][{profile['label']}] 四边形检测失败", file=sys.stderr)

    # ORB：与四点结果比质量（动火/带气阈值不同）
    if prefer != "quad":
        aligned_f, finfo = align_by_features(template, src_img, profile=profile)
        if aligned_f is not None:
            sc = edge_overlap_score(template, aligned_f)
            candidates.append(("orb", aligned_f, {"score": sc, **finfo}))
            print(
                f"[照片][{profile['label']}] ORB 特征对齐 "
                f"边缘重合={sc:.3f} 内点={finfo.get('inliers')}"
            )

    if not candidates:
        sys.exit(
            f"错误：[{profile['label']}] 无法对齐照片（四边形与 ORB 均失败）。\n"
            "请保证纸张四角完整入镜、背景对比明显，或使用 --src-points 手动指定四角；"
            "并确认 --ticket-type 与模板（dq=带气 / dh=动火）一致。"
        )

    # 选边缘重合最高者；票型独立的四点/ORB 加权
    quad_min_q = float(profile.get("quad_min_qscore", 0.5))
    quad_pen = float(profile.get("quad_penalty", 0.15))
    orb_bonus = float(profile.get("orb_score_bonus", 0.02))

    def rank(item):
        name, img, meta = item
        s = float(meta.get("score") or 0)
        if name == "quad" and float(meta.get("qscore") or 0) < quad_min_q:
            s -= quad_pen
        if name == "orb":
            s += orb_bonus
        return s

    best_name, aligned, best_meta = max(candidates, key=rank)
    print(
        f"[选定][{profile['label']}] 使用 {best_name} 对齐"
        f"（边缘重合={best_meta.get('score', 0):.3f}）| 票型={ticket_type}"
    )

    if args.debug:
        debug_dst = args.output + "_debug_dst.png"
        _imwrite(debug_dst, draw_quad(template, dst_quad))
        if src_quad is not None:
            debug_src = args.output + "_debug_src.png"
            _imwrite(debug_src, draw_quad(src_img, src_quad))
            print(f"[调试] 角点图: {debug_src} , {debug_dst}")
        else:
            print(f"[调试] 模板角点图: {debug_dst}")

    _imwrite(args.output, aligned)
    print(f"完成：[{profile['label']}] {args.output} （{tw}x{th}）")

    if args.overlay:
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(template_gray, 50, 150)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        overlay_img = aligned.copy()
        overlay_img[edges > 0] = (0, 0, 255)
        _imwrite(args.overlay, overlay_img)
        print(f"完成：叠加对比图 {args.overlay}")


if __name__ == "__main__":
    _force_utf8_stdio()
    main()
