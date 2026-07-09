# -*- coding: utf-8 -*-
"""
带气作业票 25项安全措施网格物理三分类识别工具 (OpenCV + skimage)
"""
import os
import sys
import argparse
import cv2
import numpy as np

# 将当前文件所在目录加入 sys.path 以防 mark_classifier 导入失败
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mark_classifier import classify_mark

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
    """动态检测水平网格线，或使用默认坐标兜底"""
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
                
    if len(lines_y) == 26:
        return lines_y
    else:
        # 默认网格线定位（对应标准 1052x1487 尺寸对齐图）
        return [459, 483, 507, 531, 555, 579, 603, 627, 653, 699, 745, 775, 802, 846, 872, 899, 926, 972, 1001, 1025, 1071, 1097, 1126, 1155, 1184, 1228]

def main():
    parser = argparse.ArgumentParser(description="带气作业票 25项安全措施网格物理三分类识别工具 (OpenCV + skimage)")
    parser.add_argument("-i", "--input", required=True, help="对齐后的带气作业票图像路径 (标准尺寸 1052x1487)")
    args = parser.parse_args()

    image_path = args.input
    if not os.path.exists(image_path):
        print(f"Error: 输入的图像文件不存在: {image_path}", file=sys.stderr)
        sys.exit(1)

    # 支持中文文件路径
    img_bgr = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img_bgr is None:
        print(f"Error: 图像解码失败: {image_path}", file=sys.stderr)
        sys.exit(1)

    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    x_bounds = [675, 715, 791, 829, 890, 951]
    roles = ["作业人", "施工方现场负责人", "监理", "监护人", "带气现场负责人"]
    y_lines = get_y_lines(img_gray)

    fallback_md = []
    for idx, desc in MEASURES:
        r = idx - 1  # 0-based grid row index
        y1, y2 = y_lines[r], y_lines[r+1]
        
        row_labels = []
        for i in range(5):
            pad_x = min(6, (x_bounds[i+1] - x_bounds[i]) // 3)
            pad_y = min(3, (y2 - y1) // 3)
            cell_x1 = x_bounds[i] + pad_x
            cell_x2 = x_bounds[i+1] - pad_x
            cell_y1 = y1 + pad_y
            cell_y2 = y2 - pad_y
            
            cell_gray = img_gray[cell_y1:cell_y2, cell_x1:cell_x2]
            label, dbg = classify_mark(cell_gray, inset=0, min_component_area=12)
            row_labels.append(label)
            
        status = []
        for i in range(5):
            label = row_labels[i]
            role = roles[i]
            if label == 'cross':
                status.append(f"{role}(x)")
            elif label == 'stroke':
                status.append(f"{role}(✓)")
            else:
                status.append(f"{role}(未填写)")
        
        col_str = " | ".join(status)
        fallback_md.append(f"第{idx}条: {desc} | " + col_str)

    # 设置 stdout 输出编码为 utf-8 以支持中文
    sys.stdout.reconfigure(encoding='utf-8')

    if fallback_md:
        output_text = f"\n\n--- 纯本地 OpenCV 像素密度提取结果 ---\n" + "\n".join(fallback_md) + "\n----------------------------------\n"
        print(output_text)

if __name__ == '__main__':
    main()
