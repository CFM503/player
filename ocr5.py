# -*- coding: utf-8 -*-
"""
带气作业票 25项安全措施网格对号识别工具 (OpenCV + skimage)

每项安全措施有 5 列确认格，合法填写符号（票面图例）：
  落实 √  |  未落实 ×  |  不适用 \\
空白格子不得记为叉号，否则完整性校验无法发现漏项。

识别策略（四类）：
  - 对号 / 对勾 (stroke 弯曲) → 输出 (✓)
  - 斜杠 (stroke 近似直线)   → 输出 (\\)
  - 叉号 (cross)             → 输出 (x)
  - 空白 (blank)             → 输出 (-)

用法：
  python ocr5.py -i aligned.jpg
  python ocr5.py -i aligned.jpg --crop 0,450,1052,800
"""
import os
import sys
import argparse
import logging
import cv2
import numpy as np
from skimage.morphology import skeletonize
from scipy.ndimage import label as cc_label

# ---------------------------------------------------------------------------
# 日志配置：控制台输出 INFO 及以上；详细调试信息使用 DEBUG 级别
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stderr),
    ]
)
logger = logging.getLogger("ocr5")

# 第三方库可用性检查（运行时给出友好提示）
try:
    from skimage.morphology import skeletonize as _sk_check  # noqa: F401
except ImportError:
    logger.error("缺少依赖 scikit-image，请运行: pip install scikit-image")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 表格签字格标记分类：区分 叉号(X) / 单笔画(对勾√ 或 斜杠/) / 空白
#
# 核心原理（拓扑特征）：
#   - 叉号 X：骨架化后存在分支点(>=3个骨架邻居)，端点数约为 4。
#   - 对勾√ / 斜杠 /：骨架上每个像素最多连接2个邻居，端点数为 2。
#   - 依赖 scikit-image 的 skeletonize，比单纯统计墨迹密度占比稳健。
# ---------------------------------------------------------------------------

def classify_mark(cell_gray, inset=4, ink_ratio_thresh=0.008, min_component_area=15):
    """
    对单个格子(签字/确认列的一个单元格)判断其中的标记类型。

    参数:
        cell_gray: 该格子裁剪出来的灰度图 (uint8, 0-255)
        inset: 内缩像素数，用于排除格子四周的边框线残留
        ink_ratio_thresh: 判定"完全空白"的墨迹占比下限
        min_component_area: 小于此像素面积的连通域视为噪点/边框残留

    返回:
        (label, debug_info)
        label: 'blank' | 'stroke' | 'cross'
    """
    h, w = cell_gray.shape
    y0, y1 = inset, max(inset + 1, h - inset)
    x0, x1 = inset, max(inset + 1, w - inset)
    roi = cell_gray[y0:y1, x0:x1]
    if roi.size == 0:
        logger.debug("classify_mark: roi 为空，判定 blank")
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
        logger.debug("classify_mark: ink_ratio=%.4f < thresh=%.4f → blank",
                     ink_ratio, ink_ratio_thresh)
        return 'blank', {'ink_ratio': round(float(ink_ratio), 4)}

    # 骨架化，把笔画细化成单像素宽的"线条图"
    skel = skeletonize(clean)

    # 计算每个骨架像素的8邻域内骨架邻居数量
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    neighbor_count = cv2.filter2D(skel.astype(np.uint8), -1, kernel,
                                   borderType=cv2.BORDER_CONSTANT)
    skel_neighbors = neighbor_count[skel]

    n_branch   = int((skel_neighbors >= 3).sum())  # 分支点(交叉点)像素数
    n_endpoint = int((skel_neighbors == 1).sum())  # 端点(线头)像素数
    n_skel_px  = int(skel.sum())

    # 骨架连通块数：真正的X是"一个整体"，噪声/断裂划痕常常是多个碎片
    _, n_skel_cc = cc_label(skel, structure=np.ones((3, 3)))

    # 计算分支点到最近端点的最小曼哈顿距离，过滤伪分支
    min_spur_dist = 999
    if n_branch > 0 and n_endpoint > 0:
        skel_coords    = np.argwhere(skel)
        branch_coords  = skel_coords[skel_neighbors >= 3]
        endpoint_coords = skel_coords[skel_neighbors == 1]
        for b in branch_coords:
            for e in endpoint_coords:
                dist = np.abs(b[0] - e[0]) + np.abs(b[1] - e[1])
                if dist < min_spur_dist:
                    min_spur_dist = dist

    debug = {
        'ink_ratio':        round(float(ink_ratio), 4),
        'n_branch_px':      n_branch,
        'n_endpoint':       n_endpoint,
        'n_skel_px':        n_skel_px,
        'n_skel_components': int(n_skel_cc),
        'min_spur_dist':    min_spur_dist,
    }
    logger.debug("classify_mark debug: %s", debug)

    # 判定规则：存在分支点 + 端点数3~5 + 骨架整体连通(=1块) + 最小分支距离>3px
    is_cross = (
        n_branch > 0
        and 3 <= n_endpoint <= 5
        and n_skel_cc == 1
        and min_spur_dist > 3
    )

    if is_cross:
        label = 'cross'
    else:
        # stroke：区分对勾(✓) 与 斜杠(\)
        # 斜杠近似单一直线（骨架端点=2、无分支、骨架点近似共线）；对勾有明显折角
        label = 'stroke'
        if n_endpoint == 2 and n_branch == 0 and n_skel_px >= 4:
            coords = np.argwhere(skel)
            if len(coords) >= 4:
                # 用首末端点拟合直线，残差小 → 斜杠
                ys = coords[:, 0].astype(np.float64)
                xs = coords[:, 1].astype(np.float64)
                # 端点取 y 最小/最大两点近似
                i_min, i_max = int(np.argmin(ys)), int(np.argmax(ys))
                p1 = coords[i_min].astype(np.float64)
                p2 = coords[i_max].astype(np.float64)
                # 若几乎水平则改用 x 极值
                if abs(p2[0] - p1[0]) < 2 and abs(p2[1] - p1[1]) < 2:
                    i_min, i_max = int(np.argmin(xs)), int(np.argmax(xs))
                    p1 = coords[i_min].astype(np.float64)
                    p2 = coords[i_max].astype(np.float64)
                seg = p2 - p1
                seg_len = float(np.linalg.norm(seg))
                if seg_len >= 4:
                    # 点到线段距离的 RMS
                    # cross((p-p1), seg) / |seg|
                    cross = np.abs((xs - p1[1]) * seg[0] - (ys - p1[0]) * seg[1])
                    rms = float(np.sqrt(np.mean((cross / seg_len) ** 2)))
                    debug['line_rms'] = round(rms, 3)
                    debug['seg_len'] = round(seg_len, 1)
                    # 阈值：格子很小，直线残差通常 < 1.2px
                    if rms < 1.2:
                        label = 'slash'
    logger.debug("classify_mark → %s", label)
    return label, debug


# 25条带气作业标准安全措施
MEASURES = [
    (1, "作业人具备相应的作业资格。"),
    (2, "作业人已接受作业安全教育，包括应急处置方案学习。"),
    (3, "现场人员已穿戴好安全防护用品，如防静电工作服、鞋、空气呼吸器等"),
    (4, "作业人员严禁携带各类火种、非防爆电子用品进入带气作业区域。"),
    (5, "作业现场监护人已到位。"),
    (6, "作业现场配有效、适用的气体检测仪。"),
    (7, "采用防爆工具、防爆防静电措施进行带气作业。"),
    (8, "包括照明在内的所有电器设备、线路及连接口应符合防爆要求。"),
    (9, "根据带气作业方式及带气作业环境，封堵机、夹管器、阻气袋等相应设备设施已配置齐全。"),
    (10, "PE焊接过程配备专用夹具、水平尺等工具，以便校直待连接的管材和管件，避免电熔焊过程短路燃烧 and 虚焊。"),
    (11, "检查确认待连接的新投运管网密封完好、无漏点。"),
    (12, "移动、更换的设备属于在政府部门登记的压力容器，已完成申报手续。"),
    (13, "作业区域与周边应做到可靠的隔离，现场设置明显标志，夜间应设置安全警示灯，隔离区域内严禁出现无关人员和任何形式的点火源。"),
    (14, "清除作业区域内的易燃、易爆物品。"),
    (15, "作业区域保持空气流通，调压室内等作业时应打开门窗，防止燃气积聚。"),
    (16, "作业前确认作业点周围环境可燃气体浓度不超过爆炸下限的20%。"),
    (17, "作业过程中应每隔2小时检测气体浓度，发现超过爆炸下限的50%，应立即停止作业，排查原因，满足安全条件后方可恢复作业。"),
    (18, "PE管焊接时，环境温度低于-5℃或风力大于5级，应采取防风保温措施。"),
    (19, "如需降低压力，降压过程中应严格控制降压速度，严禁系统内产生负压。"),
    (20, "地下管线放散过程，放散管必须有阀门控制，放散点周围设专人监护，必要时应进行放散燃烧。"),
    (21, "PE管同一位置最多只能使用夹管器夹一次。"),
    (22, "若涉及停、送气，则停、送气前须告知受影响的用户并做安全提示。"),
    (23, "已根据不同带气作业场景制定现场处置方案。"),
    (24, "作业现场已配备有效、适用 and 足量的灭火器材。"),
    (25, "带气作业过程中，如有紧急或异常情况，应由现场负责人立即通知停止作业，应急处置并消除隐患后才能继续实施作业。")
]


def get_y_lines(img_g):
    """
    动态检测水平网格线（25 行需 26 条线）。
    【禁止兜底】检测不到恰好 26 条时直接报错，禁止用默认坐标表硬套（会导致错行/假识别）。
    若失败：检查对齐尺寸是否为 1052x1487、表格线是否清晰。
    """
    binary_img = img_g < 80
    width = 951 - 675
    row_sums = np.sum(binary_img[:, 675:951], axis=1)
    lines_y = []
    for y in range(350, 1250):
        if row_sums[y] > 0.6 * width:
            is_max = True
            for dy in range(-3, 4):
                if row_sums[y + dy] > row_sums[y]:
                    is_max = False
                    break
                elif row_sums[y + dy] == row_sums[y] and dy < 0:
                    is_max = False
                    break
            if is_max:
                lines_y.append(y)

    if len(lines_y) != 26:
        # 曾用默认 [459,483,...1228] 兜底；已删除。出现问题请修检测/对齐，不要恢复硬编码线。
        raise RuntimeError(
            f"安全措施网格水平线数量异常: 检测到 {len(lines_y)} 条，需要恰好 26 条。"
            f"禁止使用默认坐标兜底。lines={lines_y[:8]}{'...' if len(lines_y) > 8 else ''}"
        )
    return lines_y


def main():
    # 先将 stdout/stderr 设为 utf-8，防止中文乱码
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(
        description=(
            "带气作业票 25项安全措施对号识别工具 (OpenCV + skimage)\n"
            "四分类：对号(✓) / 叉号(x) / 斜杠(\\) / 空白(-)；空白不得记为叉号"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="必填。对齐后的带气作业票图像路径 (标准尺寸 1052x1487)"
    )
    parser.add_argument(
        "--crop",
        default=None,
        metavar="X,Y,W,H",
        help="可选。局部裁剪区域，格式为 x,y,w,h (像素坐标)，默认不裁剪。示例: --crop 0,450,1052,800"
    )
    args = parser.parse_args()

    image_path = args.input
    if not os.path.exists(image_path):
        logger.error("输入的图像文件不存在: %s", image_path)
        sys.exit(1)

    logger.info("加载图像: %s", image_path)
    # 支持中文文件路径
    img_bgr = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img_bgr is None:
        logger.error("图像解码失败: %s", image_path)
        sys.exit(1)
    logger.info("图像尺寸: %dx%d", img_bgr.shape[1], img_bgr.shape[0])

    # 可选局部裁剪（在灰度转换之前）
    if args.crop:
        try:
            cx, cy, cw, ch = map(int, args.crop.split(','))
            img_bgr = img_bgr[cy:cy + ch, cx:cx + cw]
            if img_bgr.size == 0:
                print("Error: --crop 参数导致裁剪区域为空，请检查坐标值。", file=sys.stderr)
                sys.exit(1)
        except ValueError:
            print("Error: --crop 格式错误，应为 \"x,y,w,h\"，例如 --crop 0,450,1052,800", file=sys.stderr)
            sys.exit(1)

    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    x_bounds = [675, 715, 791, 829, 890, 951]
    roles = ["作业人", "施工方现场负责人", "监理", "监护人", "带气现场负责人"]
    y_lines = get_y_lines(img_gray)
    logger.info("检测到网格线数量: %d", len(y_lines))

    # 去表格化处理并保存图片
    logger.info("开始对图像进行去表格线处理...")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ocr7 import remove_table_lines, imwrite_unicode, default_output_path
    
    img_no_lines_bgr, _ = remove_table_lines(img_bgr, strength=1)
    out_path = default_output_path(image_path)
    if imwrite_unicode(out_path, img_no_lines_bgr):
        logger.info("去表格化图像已成功保存至: %s", out_path)
    else:
        logger.error("去表格化图像保存失败: %s", out_path)
        
    # 将去表格化后的图像灰度图作为后续特征提取的基础
    img_gray = cv2.cvtColor(img_no_lines_bgr, cv2.COLOR_BGR2GRAY)

    grid_md = []
    for idx, desc in MEASURES:
        r = idx - 1  # 0-based grid row index
        y1, y2 = y_lines[r], y_lines[r + 1]

        row_labels = []
        for i in range(5):
            pad_x = min(6, (x_bounds[i + 1] - x_bounds[i]) // 3)
            pad_y = min(3, (y2 - y1) // 3)
            cell_x1 = x_bounds[i] + pad_x
            cell_x2 = x_bounds[i + 1] - pad_x
            cell_y1 = y1 + pad_y
            cell_y2 = y2 - pad_y

            cell_gray = img_gray[cell_y1:cell_y2, cell_x1:cell_x2]
            label, dbg = classify_mark(cell_gray, inset=0, min_component_area=12)
            logger.debug("第%d条 列%d [%s] %s", idx, i + 1, roles[i], label)
            row_labels.append(label)

        # 四分类输出：✓ 落实 / x 未落实 / \ 不适用 / - 空白(漏项)
        # 注意：空白必须输出 (-)，不可写成 (x)，否则下游完整性校验无法发现漏填
        _sym = {'stroke': '✓', 'slash': '\\', 'cross': 'x', 'blank': '-'}
        status = []
        for i in range(5):
            label = row_labels[i]
            role = roles[i]
            status.append(f"{role}({_sym.get(label, '-')})")

        col_str = " | ".join(status)
        logger.info("第%d条: %s", idx, col_str)
        grid_md.append(f"第{idx}条: {desc} | " + col_str)

    if not grid_md:
        # 【禁止兜底】无输出行则失败退出，禁止打印空成功
        raise RuntimeError("25 项安全措施网格结果为空，禁止兜底输出")
    output_text = (
        "\n\n--- 纯本地 OpenCV 像素密度提取结果 ---\n"
        + "\n".join(grid_md)
        + "\n----------------------------------\n"
    )
    print(output_text)


if __name__ == '__main__':
    main()
