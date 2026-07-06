# -*- coding: utf-8 -*-
"""
表格签字格标记分类：区分 叉号(X) / 单笔画(对勾√ 或 斜杠/) / 空白

核心原理（拓扑特征，已在真实样本上验证）：
  - 叉号 X：两条线在中心交叉 -> 骨架化后存在一个"分支点"
            (该像素的8邻域里同时有 >=3 个骨架邻居)，且整体是
            一条连通的骨架，端点数约为 4。
  - 对勾√ / 斜杠 /：本质是一条不间断的折线 -> 骨架上每个像素
            最多连接2个邻居（无分支），端点数为 2。
  - 依赖 scikit-image 的 skeletonize，比单纯统计"墨迹像素密度占比"
    稳健得多——密度阈值法在窄格子里极易被表格边框线本身的密度
    干扰，导致空白格也被判定为"有笔迹"。

依赖: opencv-python(-headless), numpy, scikit-image, scipy
    pip install opencv-python-headless numpy scikit-image scipy --break-system-packages
"""

import cv2
import numpy as np
from skimage.morphology import skeletonize
from scipy.ndimage import label as cc_label


def classify_mark(cell_gray, inset=4, ink_ratio_thresh=0.008, min_component_area=15):
    """
    对单个格子(签字/确认列的一个单元格)判断其中的标记类型。

    参数:
        cell_gray: 该格子裁剪出来的灰度图 (uint8, 0-255)，
                   建议裁剪时比实际格子边界稍微放宽 2~3px，
                   函数内部会再做 inset 内缩以避开表格边框线。
        inset: 内缩像素数，用于排除格子四周的边框线残留。
        ink_ratio_thresh: 判定"完全空白"的墨迹占比下限。
        min_component_area: 小于此像素面积的连通域视为噪点/边框残留，直接丢弃。

    返回:
        (label, debug_info)
        label: 'blank' | 'stroke' | 'cross'
               'blank'  = 空白，未填写
               'stroke' = 有笔迹，但只是单笔画（对勾/斜杠/短划线等）
               'cross'  = 判定为叉号 X
        debug_info: dict，包含判定依据的关键数值，便于调试和人工复核
    """
    h, w = cell_gray.shape
    y0, y1 = inset, max(inset + 1, h - inset)
    x0, x1 = inset, max(inset + 1, w - inset)
    roi = cell_gray[y0:y1, x0:x1]
    if roi.size == 0:
        return 'blank', {}

    # 二值化：取墨迹（背景是纸张白色，墨迹/印刷线是深色）
    inv = 255 - roi
    _, bw = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw_bool = bw > 0

    # 去掉小噪点连通域（扫描噪声、纸张纹理、边框残留碎片）
    labeled, n = cc_label(bw_bool)
    clean = np.zeros_like(bw_bool)
    for i in range(1, n + 1):
        if (labeled == i).sum() >= min_component_area:
            clean |= (labeled == i)

    ink_ratio = clean.sum() / clean.size
    if ink_ratio < ink_ratio_thresh:
        return 'blank', {'ink_ratio': round(float(ink_ratio), 4)}

    # 骨架化，把笔画细化成单像素宽的"线条图"
    skel = skeletonize(clean)

    # 计算每个骨架像素的8邻域内骨架邻居数量
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    neighbor_count = cv2.filter2D(skel.astype(np.uint8), -1, kernel,
                                   borderType=cv2.BORDER_CONSTANT)
    skel_neighbors = neighbor_count[skel]

    n_branch = int((skel_neighbors >= 3).sum())   # 分支点(交叉点)像素数
    n_endpoint = int((skel_neighbors == 1).sum())  # 端点(线头)像素数
    n_skel_px = int(skel.sum())

    # 骨架连通块数：真正的X是"一个整体"，噪声/断裂划痕常常是多个碎片
    _, n_skel_cc = cc_label(skel, structure=np.ones((3, 3)))

    # 计算分支点到最近端点的最小曼哈顿距离，过滤由于拐角/边缘毛刺产生的伪分支
    min_spur_dist = 999
    if n_branch > 0 and n_endpoint > 0:
        skel_coords = np.argwhere(skel)
        branch_coords = skel_coords[skel_neighbors >= 3]
        endpoint_coords = skel_coords[skel_neighbors == 1]
        for b in branch_coords:
            for e in endpoint_coords:
                dist = np.abs(b[0] - e[0]) + np.abs(b[1] - e[1])
                if dist < min_spur_dist:
                    min_spur_dist = dist

    debug = {
        'ink_ratio': round(float(ink_ratio), 4),
        'n_branch_px': n_branch,
        'n_endpoint': n_endpoint,
        'n_skel_px': n_skel_px,
        'n_skel_components': int(n_skel_cc),
        'min_spur_dist': min_spur_dist
    }

    # 判定规则：必须同时满足 —— 存在分支点 + 端点数落在3~5 + 骨架整体连通(=1块) + 最小分支距离大于3像素
    is_cross = False
    if n_branch > 0 and 3 <= n_endpoint <= 5 and n_skel_cc == 1:
        if min_spur_dist > 3:
            is_cross = True

    if is_cross:
        return 'cross', debug
    else:
        return 'stroke', debug


if __name__ == '__main__':
    # 用法示例：对整张表按已知的列坐标(x_bounds)和行坐标(row_lines)逐格分类
    img = cv2.imread('your_image.png')
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    x_bounds = [523, 551, 608, 636, 682, 760]  # 5列的列边界(需按实际模板标定)
    roles = ['作业人', '施工方现场负责人', '监理人员', '项目公司监护人', '带气现场负责人']
    row_lines = [307, 325, 343, 360, 378]  # 行边界(建议用形态学检测横线自动获取,而非手写)

    for r in range(len(row_lines) - 1):
        y0, y1 = row_lines[r], row_lines[r + 1]
        row_result = []
        for c in range(5):
            cx0, cx1 = x_bounds[c], x_bounds[c + 1]
            cell = gray[y0:y1, cx0:cx1]
            label, dbg = classify_mark(cell)
            row_result.append(f'{roles[c]}:{label}')
        print(f'第{r+1}条:', row_result)
