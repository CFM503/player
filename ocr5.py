# -*- coding: utf-8 -*-
"""
作业票安全措施勾选格识别（OpenCV + skimage）

【票型永远分离】
  - 带气作业票：25 项 × 5 列（作业人/施工方/监理/监护人/带气现场负责人）
  - 动火作业票：21 项 × 1 列（确认）
  共用四分类 classify_mark（√ / × / \\ / 空白），网格几何与条款表各自独立。

合法填写符号（票面图例）：
  落实 √  |  未落实 ×  |  不适用 \\
空白格子不得记为叉号，否则完整性校验无法发现漏项。

用法：
  # 带气（默认，兼容旧调用）
  python ocr5.py -i aligned_gas.jpg
  python ocr5.py -i aligned_gas.jpg --ticket-type 带气作业票

  # 动火（须显式或按图宽高推断；规范画布 1000×1414）
  python ocr5.py -i aligned_fire.jpg --ticket-type 动火作业票
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

def _load_mark_train_overrides():
    """
    加载 ocr10 导出的训练参数/模型（可选）。
    查找顺序：环境变量 OCR5_MARK_PARAMS → 项目根 ocr5_mark_params.json
              → ocr_mark_workspace/models/active_mark_params.json
    模型：ocr5_mark_model.pkl 或 active_mark_model.pkl
    """
    import json as _json
    from pathlib import Path as _Path
    root = _Path(__file__).resolve().parent
    candidates = []
    env_p = os.environ.get("OCR5_MARK_PARAMS", "").strip()
    if env_p:
        candidates.append(_Path(env_p))
    candidates.extend([
        root / "ocr5_mark_params.json",
        root / "ocr_mark_workspace" / "models" / "active_mark_params.json",
    ])
    params = {}
    for p in candidates:
        try:
            if p.is_file():
                params = _json.loads(p.read_text(encoding="utf-8"))
                break
        except Exception:
            continue

    model_path = None
    for mp in (
        root / "ocr5_mark_model.pkl",
        root / "ocr_mark_workspace" / "models" / "active_mark_model.pkl",
    ):
        if mp.is_file():
            model_path = mp
            break
    return params or {}, model_path


_MARK_PARAMS_CACHE = None
_MARK_MODEL_CACHE = None


def _get_mark_overrides():
    global _MARK_PARAMS_CACHE, _MARK_MODEL_CACHE
    if _MARK_PARAMS_CACHE is None:
        params, mpath = _load_mark_train_overrides()
        _MARK_PARAMS_CACHE = params
        if mpath is not None:
            try:
                import pickle
                with mpath.open("rb") as f:
                    _MARK_MODEL_CACHE = pickle.load(f)
            except Exception as e:
                logger.warning("加载 ocr10 标记模型失败: %s", e)
                _MARK_MODEL_CACHE = None
        else:
            _MARK_MODEL_CACHE = None
    return _MARK_PARAMS_CACHE, _MARK_MODEL_CACHE


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
        label: 'blank' | 'stroke' | 'cross' | 'slash'
    """
    # ocr10 训练覆盖（未导出时 params 为空，行为与原来一致）
    tr_params, tr_model = _get_mark_overrides()
    if tr_params:
        if "ink_ratio_thresh" in tr_params:
            ink_ratio_thresh = float(tr_params["ink_ratio_thresh"])
        if "min_component_area" in tr_params:
            min_component_area = int(tr_params["min_component_area"])
        if "inset" in tr_params:
            inset = int(tr_params["inset"])

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

    ep_min = int(tr_params.get("cross_endpoint_min", 3)) if tr_params else 3
    ep_max = int(tr_params.get("cross_endpoint_max", 5)) if tr_params else 5
    spur_th = float(tr_params.get("cross_min_spur_dist", 3)) if tr_params else 3
    slash_rms_th = float(tr_params.get("slash_line_rms", 1.2)) if tr_params else 1.2

    # 判定规则：存在分支点 + 端点数范围 + 骨架整体连通(=1块) + 最小分支距离
    is_cross = (
        n_branch > 0
        and ep_min <= n_endpoint <= ep_max
        and n_skel_cc == 1
        and min_spur_dist > spur_th
    )

    if is_cross:
        label = 'cross'
    else:
        # stroke：区分对勾(✓) 与 斜杠(\)
        label = 'stroke'
        if n_endpoint == 2 and n_branch == 0 and n_skel_px >= 4:
            coords = np.argwhere(skel)
            if len(coords) >= 4:
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
                if seg_len >= 4:
                    cross = np.abs((xs - p1[1]) * seg[0] - (ys - p1[0]) * seg[1])
                    rms = float(np.sqrt(np.mean((cross / seg_len) ** 2)))
                    debug['line_rms'] = round(rms, 3)
                    debug['seg_len'] = round(seg_len, 1)
                    if rms < slash_rms_th:
                        label = 'slash'

    # ocr10 sklearn 模型覆盖（特征分类）
    if tr_model is not None and isinstance(tr_model, dict) and "clf" in tr_model:
        try:
            keys = tr_model.get("feature_keys") or [
                "ink_ratio", "n_branch_px", "n_endpoint", "n_skel_px",
                "n_skel_components", "min_spur_dist", "line_rms", "aspect", "fill_area",
            ]
            feat = {
                "ink_ratio": float(debug.get("ink_ratio") or 0),
                "n_branch_px": float(n_branch),
                "n_endpoint": float(n_endpoint),
                "n_skel_px": float(n_skel_px),
                "n_skel_components": float(n_skel_cc),
                "min_spur_dist": float(min_spur_dist if min_spur_dist is not None else 999),
                "line_rms": float(debug.get("line_rms") if debug.get("line_rms") is not None else 99),
                "aspect": float(w) / max(float(h), 1.0),
                "fill_area": float(h * w),
            }
            x = [[float(feat.get(k, 0)) for k in keys]]
            ml = str(tr_model["clf"].predict(x)[0])
            # 模型标签 check→stroke 与 ocr5 输出对齐
            _map = {"check": "stroke", "cross": "cross", "slash": "slash", "blank": "blank"}
            if ml in _map:
                debug["ml_pred"] = ml
                debug["rule_pred"] = label
                label = _map[ml]
        except Exception as e:
            logger.debug("ML 覆盖失败，沿用规则: %s", e)

    logger.debug("classify_mark → %s", label)
    return label, debug


# ---------------------------------------------------------------------------
# 票型 profile（带气 / 动火永远分离）
# ---------------------------------------------------------------------------
TICKET_GAS = "带气作业票"
TICKET_FIRE = "动火作业票"

# 25 条带气作业标准安全措施
GAS_MEASURES = [
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
    (25, "带气作业过程中，如有紧急或异常情况，应由现场负责人立即通知停止作业，应急处置并消除隐患后才能继续实施作业。"),
]

# 21 条动火作业标准安全措施（与 agent_core STANDARD_MEASURES 动火表一致）
FIRE_MEASURES = [
    (1, "动火人已接受作业安全教育。"),
    (2, "实际动火人与作业票上的动火人相符，持有效证件。"),
    (3, "监护人已到位。"),
    (4, "作业机具经过检验合格。"),
    (5, "动火作业使用的脚手架、吊篮经检查合格。"),
    (6, "所有与动火设备相连的设备、管线加盲板/堵头等有效隔断，连通作业段的阀门处于关闭状态。不得以水封或仅关闭阀门代替盲板隔断。"),
    (7, "动火管线、设备内部清理干净，吹扫合格，达到动火条件。"),
    (8, "动火点15米内无可燃物，下水井、地漏、地沟覆盖严密。"),
    (9, "动火点15米内无可燃液体排放，30米内无可燃气体排放。"),
    (10, "同一动火区域内无可燃溶剂清洗、喷漆及刷油漆作业。"),
    (11, "五级风及以上天气，禁止露天动火作业，确需动火，应升级管理。"),
    (12, "乙炔气瓶应立放、安装阻火器，乙炔瓶和氧气瓶无泄漏，与火源的距离大于10米，要有防晒、防倾倒措施。"),
    (13, "特级动火作业应全过程作业影像，且作业现场使用的摄录设备为防爆型."),
    (14, "实际动火部位、内容、时间与动火作业票相符。"),
    (15, "已对相关人员进行安全交底。"),
    (16, "采样检测结果符合动火条件。每日动火作业前必须进行检测，检测后超过30分钟未动火，复测合格后方可动火。特级、一级动火作业中断时间超过30分钟，二级动火作业中断时间超过60分钟，必须重新检测合格后方可动火。特级动火作业期间必须连续进行监测。"),
    (17, "现场所有人员按规范穿戴个人防护用品。"),
    (18, "高处动火作业应采取防火花飞溅措施。"),
    (19, "紧急疏散通道与消防通道保持畅通。"),
    (20, "动火点配备合适的消防器材，现场配备消防水带（0）根，灭火器（/）台，灭火毯（）块。"),
    (21, "其他补充安全措施："),
]

# 带气：标准对齐图 dq / align 输出 1052×1487
GAS_REF_W, GAS_REF_H = 1052, 1487
GAS_REF_Y_LINES = [  # 26 条水平线 → 25 行
    459, 483, 507, 531, 555, 579, 603, 627, 653, 699,
    745, 775, 802, 846, 872, 899, 926, 972, 1001, 1025,
    1071, 1097, 1126, 1155, 1184, 1228,
]
GAS_REF_X_BOUNDS = [675, 715, 791, 829, 890, 951]  # 5 列
GAS_ROLES = ["作业人", "施工方现场负责人", "监理", "监护人", "带气现场负责人"]
GAS_N_ROWS = 25
GAS_N_HLINES = 26  # = N_ROWS + 1

# 动火：标准对齐图 dh / align 输出 1000×1414（与当前 template/dh.png 一致）
# 22 条水平线 → 21 行；单列「确认」在票面右侧（dh.png 投影标定）
FIRE_REF_W, FIRE_REF_H = 1000, 1414
FIRE_REF_Y_LINES = [
    404, 426, 448, 470, 492, 514,
    561, 583, 607, 630, 654, 678,
    721, 751, 777, 804, 830, 858,
    902, 940, 964, 988,
]
FIRE_REF_X_BOUNDS = [872, 954]  # 单列确认格
FIRE_ROLES = ["确认"]
FIRE_N_ROWS = 21
FIRE_N_HLINES = 22

# 兼容旧名
MEASURES = GAS_MEASURES
REF_W, REF_H = GAS_REF_W, GAS_REF_H
REF_Y_LINES = GAS_REF_Y_LINES
REF_X_BOUNDS = GAS_REF_X_BOUNDS


def resolve_ticket_type(ticket_type: str | None, img_w: int = 0, img_h: int = 0) -> str:
    """解析票型；未指定时按画布尺寸粗推断（1000×1414→动火，1052×1487→带气）。"""
    s = (ticket_type or "").strip()
    if s in (TICKET_GAS, TICKET_FIRE):
        return s
    if "动火" in s or s.lower() in ("fire", "hot", "dh"):
        return TICKET_FIRE
    if "带气" in s or s.lower() in ("gas", "dq"):
        return TICKET_GAS
    if img_w and img_h:
        # 接近动火规范画布
        if abs(img_w - FIRE_REF_W) <= 40 and abs(img_h - FIRE_REF_H) <= 60:
            return TICKET_FIRE
        if abs(img_w - GAS_REF_W) <= 40 and abs(img_h - GAS_REF_H) <= 60:
            return TICKET_GAS
    return TICKET_GAS


def get_ticket_profile(ticket_type: str) -> dict:
    """返回票型独立几何/条款（禁止混用）。"""
    if ticket_type == TICKET_FIRE:
        return {
            "ticket_type": TICKET_FIRE,
            "label": "动火",
            "measures": FIRE_MEASURES,
            "roles": FIRE_ROLES,
            "ref_w": FIRE_REF_W,
            "ref_h": FIRE_REF_H,
            "ref_y_lines": FIRE_REF_Y_LINES,
            "ref_x_bounds": FIRE_REF_X_BOUNDS,
            "n_rows": FIRE_N_ROWS,
            "n_hlines": FIRE_N_HLINES,
            "detect_x0_ref": 860,
            "detect_x1_ref": 980,
            "detect_y0_ref": 360,
            "detect_y1_ref": 1050,
        }
    return {
        "ticket_type": TICKET_GAS,
        "label": "带气",
        "measures": GAS_MEASURES,
        "roles": GAS_ROLES,
        "ref_w": GAS_REF_W,
        "ref_h": GAS_REF_H,
        "ref_y_lines": GAS_REF_Y_LINES,
        "ref_x_bounds": GAS_REF_X_BOUNDS,
        "n_rows": GAS_N_ROWS,
        "n_hlines": GAS_N_HLINES,
        "detect_x0_ref": 675,
        "detect_x1_ref": 951,
        "detect_y0_ref": 350,
        "detect_y1_ref": 1250,
    }


def get_x_bounds(img_w: int, profile: dict | None = None):
    """按图像宽度比例缩放确认格 x 边界。"""
    prof = profile or get_ticket_profile(TICKET_GAS)
    sx = float(img_w) / float(prof["ref_w"])
    return [int(round(x * sx)) for x in prof["ref_x_bounds"]]


def _scale_ref_y_lines(img_h: int, profile: dict | None = None):
    prof = profile or get_ticket_profile(TICKET_GAS)
    sy = float(img_h) / float(prof["ref_h"])
    return [int(round(y * sy)) for y in prof["ref_y_lines"]]


def _detect_h_peaks(row_sums, y0, y1, width_ref, ratio_thresh, nms=3):
    """在 row_sums[y0:y1] 上找水平线峰。"""
    lines_y = []
    thr = ratio_thresh * width_ref
    y1 = min(y1, len(row_sums) - 1)
    y0 = max(0, y0)
    for y in range(y0, y1):
        if row_sums[y] <= thr:
            continue
        is_max = True
        for dy in range(-nms, nms + 1):
            yy = y + dy
            if yy < 0 or yy >= len(row_sums):
                continue
            if row_sums[yy] > row_sums[y]:
                is_max = False
                break
            if row_sums[yy] == row_sums[y] and dy < 0:
                is_max = False
                break
        if is_max:
            lines_y.append(y)
    return lines_y


def _merge_nearby_lines(lines, min_gap=6):
    """合并过近的峰，避免双线。"""
    if not lines:
        return []
    lines = sorted(lines)
    out = [lines[0]]
    for y in lines[1:]:
        if y - out[-1] < min_gap:
            # 保留 ink 更强的需外部；此处取中点
            out[-1] = (out[-1] + y) // 2
        else:
            out.append(y)
    return out


def _median_ref_gap(img_h: int, profile: dict | None = None) -> float:
    ref = _scale_ref_y_lines(img_h, profile)
    gaps = [ref[i + 1] - ref[i] for i in range(len(ref) - 1)]
    return float(np.median(gaps)) if gaps else 24.0


def _ref_match_score(peaks, img_h: int, profile: dict | None = None) -> float:
    """
    候选峰与 REF 网格的贴合分（越小越好）。
    不只看数量是否=N，避免「漏掉首线」被当成最优。
    """
    prof = profile or get_ticket_profile(TICKET_GAS)
    n_hlines = int(prof["n_hlines"])
    if not peaks:
        return 1e12
    ref = _scale_ref_y_lines(img_h, prof)
    peaks = sorted(int(y) for y in peaks)
    med = _median_ref_gap(img_h, prof)
    total = 0.0
    for ry in ref:
        total += min(abs(ry - cy) for cy in peaks)
    total += abs(len(peaks) - n_hlines) * med * 0.35
    return total


def _pick_n_from_candidates(cands, img_h, profile: dict | None = None):
    """
    以票型 REF 几何为锚，在候选峰中「单调、就近」吸附为 n_hlines 条。

    关键：旧逻辑 max_d 过大，首条漏检会把第 2 条线错配给第 1 行。
    """
    prof = profile or get_ticket_profile(TICKET_GAS)
    ref = _scale_ref_y_lines(img_h, prof)
    n_hlines = int(prof["n_hlines"])
    if not cands:
        return list(ref)
    cands = sorted(set(int(y) for y in cands))
    med_gap = _median_ref_gap(img_h, prof)
    max_d = max(8, int(round(0.4 * med_gap)))

    chosen = []
    used = set()
    for ry in ref:
        best_i, best_d = None, 1e9
        for i, cy in enumerate(cands):
            if i in used:
                continue
            if chosen and cy <= chosen[-1]:
                continue
            d = abs(cy - ry)
            if d < best_d:
                best_d, best_i = d, i
        if best_i is not None and best_d <= max_d:
            used.add(best_i)
            chosen.append(cands[best_i])
        else:
            y = int(ry)
            if chosen and y <= chosen[-1]:
                y = chosen[-1] + max(1, int(round(med_gap)))
            chosen.append(y)
    # 保证条数
    while len(chosen) < n_hlines:
        chosen.append(chosen[-1] + max(1, int(round(med_gap))))
    return chosen[:n_hlines]


def _pick_26_from_candidates(cands, img_h):
    """兼容旧接口：默认带气 26 条。"""
    return _pick_n_from_candidates(cands, img_h, get_ticket_profile(TICKET_GAS))


def get_y_lines(img_g, profile: dict | None = None):
    """
    检测安全措施区水平网格线（条数随票型：带气 26 / 动火 22）。

    重要：必须在「仍含表格线」的灰度图上调用。
    """
    if img_g is None or img_g.size == 0:
        raise RuntimeError("get_y_lines: 输入灰度图为空")

    prof = profile or get_ticket_profile(TICKET_GAS)
    n_hlines = int(prof["n_hlines"])
    label = prof.get("label", "")
    ref_w, ref_h = int(prof["ref_w"]), int(prof["ref_h"])

    h, w = img_g.shape[:2]
    sx = w / float(ref_w)
    sy = h / float(ref_h)
    x0 = max(0, int(round(prof["detect_x0_ref"] * sx)))
    x1 = min(w, int(round(prof["detect_x1_ref"] * sx)))
    if x1 - x0 < 20:
        x0, x1 = int(w * 0.60), w - 2
    y0 = max(0, int(round(prof["detect_y0_ref"] * sy)))
    y1 = min(h - 1, int(round(prof["detect_y1_ref"] * sy)))
    band_w = max(1, x1 - x0)

    best = []
    best_score = 1e12
    min_peaks_for_adsorb = max(8, n_hlines // 2)

    def _consider(peaks, tag=""):
        nonlocal best, best_score
        if not peaks:
            return
        score = _ref_match_score(peaks, h, prof)
        if score < best_score:
            best_score = score
            best = peaks

    for thr_gray in (50, 70, 80, 100, 120, 140, 160):
        binary = img_g < thr_gray
        row_sums = np.sum(binary[:, x0:x1], axis=1).astype(np.float64)
        for ratio in (0.25, 0.35, 0.45, 0.55, 0.65, 0.75):
            peaks = _detect_h_peaks(row_sums, y0, y1, band_w, ratio, nms=3)
            peaks = _merge_nearby_lines(peaks, min_gap=max(4, int(8 * sy)))
            _consider(peaks)

    try:
        inv = 255 - img_g
        _, bw = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        klen = max(15, int(band_w * 0.35))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (klen, 1))
        morph = cv2.morphologyEx(bw[:, x0:x1], cv2.MORPH_OPEN, kernel)
        full_sums = np.sum((morph > 0), axis=1).astype(np.float64)
        for ratio in (0.25, 0.4, 0.55):
            peaks = _detect_h_peaks(full_sums, y0, y1, band_w, ratio, nms=2)
            peaks = _merge_nearby_lines(peaks, min_gap=max(4, int(8 * sy)))
            _consider(peaks)
    except Exception as e:
        logger.debug("形态学检线失败: %s", e)

    if len(best) >= min_peaks_for_adsorb:
        picked = _pick_n_from_candidates(best, h, prof)
        if len(picked) == n_hlines:
            ref = _scale_ref_y_lines(h, prof)
            med = _median_ref_gap(h, prof)
            mad = float(np.mean([abs(a - b) for a, b in zip(picked, ref)]))
            if mad <= med * 0.75:
                logger.info(
                    "get_y_lines[%s]: 峰 %d → REF 吸附 %d 条 (mad=%.1f, size=%dx%d) first=%s",
                    label, len(best), n_hlines, mad, w, h, picked[:3],
                )
                return picked
            logger.warning(
                "get_y_lines[%s]: 吸附偏离 REF 过大 (mad=%.1f > %.1f)，改用比例网格",
                label, mad, med * 0.75,
            )

    if w >= 700 and h >= 900:
        scaled = _scale_ref_y_lines(h, prof)
        logger.warning(
            "get_y_lines[%s]: 动态检测失败(best=%d, size=%dx%d)。"
            "使用标准对齐票比例网格（REF %dx%d 按高度缩放）。",
            label, len(best), w, h, ref_w, ref_h,
        )
        return scaled

    raise RuntimeError(
        f"[{label}] 安全措施网格水平线异常: 检测到 {len(best)} 条，需要 {n_hlines} 条；"
        f"图像 {w}x{h}。请使用模板对齐后的{label}作业票（约 {ref_w}x{ref_h}），"
        f"且必须在去表格线之前检测网格。"
        f" best_lines={best[:12]}{'...' if len(best) > 12 else ''}"
    )


def run_mark_grid(img_bgr, profile: dict, image_path: str = "") -> str:
    """
    按票型 profile 检测网格并四分类输出。
    带气：25×5；动火：21×1。classify_mark 共用，几何/条款分离。
    """
    label = profile.get("label", "")
    measures = profile["measures"]
    roles = profile["roles"]
    n_cols = len(roles)
    n_rows = int(profile["n_rows"])
    n_hlines = int(profile["n_hlines"])

    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # 必须在去表格线之前检水平线
    x_bounds = get_x_bounds(img_bgr.shape[1], profile)
    y_lines = get_y_lines(img_gray, profile)
    logger.info(
        "[%s] 网格线=%d (期望 %d)  x_bounds=%s  roles=%s",
        label, len(y_lines), n_hlines, x_bounds, roles,
    )
    if len(y_lines) < n_hlines:
        raise RuntimeError(
            f"[{label}] 水平线不足: {len(y_lines)} < {n_hlines}，无法构成 {n_rows} 行"
        )

    logger.info("[%s] 开始去表格线（仅用于格内分类；ocr7 票型参数分离）...", label)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ocr7 import remove_table_lines, imwrite_unicode, default_output_path

    img_no_lines_bgr, _ = remove_table_lines(
        img_bgr,
        strength=1,
        ticket_type=profile.get("ticket_type"),
    )
    if image_path:
        out_path = default_output_path(image_path)
        if imwrite_unicode(out_path, img_no_lines_bgr):
            logger.info("[%s] 去表格化图像已保存: %s", label, out_path)
        else:
            logger.error("[%s] 去表格化图像保存失败: %s", label, out_path)

    img_gray = cv2.cvtColor(img_no_lines_bgr, cv2.COLOR_BGR2GRAY)

    grid_md = []
    _sym = {"stroke": "✓", "slash": "\\", "cross": "x", "blank": "-"}
    for idx, desc in measures:
        r = idx - 1
        y1, y2 = y_lines[r], y_lines[r + 1]
        row_labels = []
        for i in range(n_cols):
            pad_x = min(6, max(1, (x_bounds[i + 1] - x_bounds[i]) // 3))
            pad_y = min(3, max(1, (y2 - y1) // 3))
            cell_x1 = x_bounds[i] + pad_x
            cell_x2 = x_bounds[i + 1] - pad_x
            cell_y1 = y1 + pad_y
            cell_y2 = y2 - pad_y
            cell_gray = img_gray[cell_y1:cell_y2, cell_x1:cell_x2]
            mark_label, _dbg = classify_mark(cell_gray, inset=0, min_component_area=12)
            logger.debug(
                "[%s] 第%d条 列%d [%s] %s", label, idx, i + 1, roles[i], mark_label
            )
            row_labels.append(mark_label)

        status = [
            f"{roles[i]}({_sym.get(row_labels[i], '-')})" for i in range(n_cols)
        ]
        col_str = " | ".join(status)
        logger.info("[%s] 第%d条: %s", label, idx, col_str)
        grid_md.append(f"第{idx}条: {desc} | " + col_str)

    if not grid_md:
        raise RuntimeError(f"[{label}] 安全措施网格结果为空，禁止兜底输出")
    if len(grid_md) != n_rows:
        logger.warning("[%s] 输出行数 %d ≠ 期望 %d", label, len(grid_md), n_rows)

    header = (
        f"\n\n--- 纯本地 OpenCV 像素密度提取结果 ---\n"
        f"ticket_type={profile['ticket_type']}\n"
    )
    return header + "\n".join(grid_md) + "\n----------------------------------\n"


def main():
    # 先将 stdout/stderr 设为 utf-8，防止中文乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description=(
            "作业票安全措施勾选识别 (OpenCV + skimage)\n"
            "带气 25×5 / 动火 21×1 完全分离；四分类：✓ / x / \\ / -"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="对齐后的作业票图像（带气约 1052×1487；动火约 1000×1414）",
    )
    parser.add_argument(
        "--ticket-type",
        default=None,
        choices=[
            TICKET_GAS, TICKET_FIRE,
            "gas", "fire", "带气", "动火",
        ],
        help="票型：带气作业票 / 动火作业票（默认按图尺寸推断，优先显式指定）",
    )
    parser.add_argument(
        "--crop",
        default=None,
        metavar="X,Y,W,H",
        help="可选局部裁剪 x,y,w,h",
    )
    args = parser.parse_args()

    image_path = args.input
    if not os.path.exists(image_path):
        logger.error("输入的图像文件不存在: %s", image_path)
        sys.exit(1)

    logger.info("加载图像: %s", image_path)
    img_bgr = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img_bgr is None:
        logger.error("图像解码失败: %s", image_path)
        sys.exit(1)
    h, w = img_bgr.shape[:2]
    logger.info("图像尺寸: %dx%d", w, h)

    if args.crop:
        try:
            cx, cy, cw, ch = map(int, args.crop.split(","))
            img_bgr = img_bgr[cy : cy + ch, cx : cx + cw]
            if img_bgr.size == 0:
                print("Error: --crop 参数导致裁剪区域为空", file=sys.stderr)
                sys.exit(1)
            h, w = img_bgr.shape[:2]
        except ValueError:
            print("Error: --crop 格式错误，应为 x,y,w,h", file=sys.stderr)
            sys.exit(1)

    tt_raw = args.ticket_type
    if tt_raw in ("gas", "带气"):
        tt_raw = TICKET_GAS
    elif tt_raw in ("fire", "动火"):
        tt_raw = TICKET_FIRE
    ticket_type = resolve_ticket_type(tt_raw, w, h)
    profile = get_ticket_profile(ticket_type)
    logger.info(
        "票型锁定=%s（%s）| 条款 %d 行 × %d 列 | REF %dx%d",
        ticket_type,
        profile["label"],
        profile["n_rows"],
        len(profile["roles"]),
        profile["ref_w"],
        profile["ref_h"],
    )

    output_text = run_mark_grid(img_bgr, profile, image_path=image_path)
    print(output_text)


if __name__ == "__main__":
    main()
