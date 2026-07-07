# -*- coding: utf-8 -*-
"""
新模板网格线坐标检测与提取工具 (Image Analysis Algorithm for Grid Detection)
用途: 自动分析指定的作业票模板图片（如 dq.png），识别勾选区列边界 X 坐标以及 25 项安全措施行水平分割线 Y 坐标。
"""

import cv2
import numpy as np
import os
import sys

def main():
    # 默认检测的模板图片路径
    template_path = r"template/dq.png"
    if len(sys.argv) > 1:
        template_path = sys.argv[1] # 支持通过命令行参数传入其它模板图路径

    if not os.path.exists(template_path):
        print(f"【错误】找不到模板图片文件: {template_path}")
        return

    # 1. 读取模板图片并转换为灰度图
    img = cv2.imread(template_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    print(f"--- 开始分析模板: {template_path} ---")
    print(f"模板图片分辨率: {w}x{h} 像素")

    # 2. 图像二值化处理 (反色：使黑色表格框线变为白色 255，白色背景变为黑色 0，方便求和投影)
    # 使用阈值 180 可以很好地捕获浅灰色或较细的网格框线
    _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)

    # 3. 寻找垂直框线 X 轴坐标 (X-Bounds)
    # 我们限制扫描区间在 Y = [500, 1200]（即表格主体所在的高度范围），只计算此高度内的列像素投影和
    # 这能彻底避开表格上方页眉与下方页脚的垂直文字干扰，获取最纯净的列网格线
    col_sums_in_table = np.sum(binary[500:1200, :] > 0, axis=0)
    table_h = 1200 - 500
    
    x_candidates = []
    # 表格勾选框一般分布在右侧 X = [600, 1000] 之间
    for x in range(600, 1000):
        # 如果当前列中黑色像素的比例超过 40%，则视为一条潜在的垂直框线
        if col_sums_in_table[x] > 0.4 * table_h:
            # 局部最大值过滤：确保在邻域 ±4 像素内，该列的像素密度最高，以此精确定位线条中心
            is_max = True
            for dx in range(-4, 5):
                if col_sums_in_table[x + dx] > col_sums_in_table[x]:
                    is_max = False
                    break
                elif col_sums_in_table[x + dx] == col_sums_in_table[x] and dx < 0:
                    is_max = False
                    break
            if is_max:
                x_candidates.append(x)
                
    print(f"检测到的垂直网格线 X 坐标: {x_candidates}")
    
    # 4. 寻找水平框线 Y 轴坐标 (Y-Lines)
    # 我们以检测到的列线两端 (即勾选区总宽度范围) 作为水平投影的宽度区间，检测横向的网格线
    # 默认以 675 到 951 像素宽度为检测视窗
    x_start = x_candidates[0] if len(x_candidates) >= 2 else 675
    x_end = x_candidates[-1] if len(x_candidates) >= 2 else 951
    width = x_end - x_start
    
    # 计算每一行在该水平宽度范围内的白色像素投影和
    row_sums = np.sum(binary[:, x_start:x_end] > 0, axis=1)
    
    y_lines = []
    # 在 Y = [300, 图片底部-50] 区间内扫描水平线
    for y in range(300, h - 50):
        # 如果当前行在勾选框总宽度内有超过 70% 的像素是黑色的，则视为横线
        if row_sums[y] > 0.7 * width:
            # 局部最大值过滤：在上下 ±3 像素内寻找投影峰值，以确定横线中心高度
            is_max = True
            for dy in range(-3, 4):
                if row_sums[y + dy] > row_sums[y]:
                    is_max = False
                    break
                elif row_sums[y + dy] == row_sums[y] and dy < 0:
                    is_max = False
                    break
            if is_max:
                y_lines.append(y)
                
    # 筛选出真正属于安全措施 25 行表格内部的水平线 (表格首行一般在 450 之后，末行在 1240 之前)
    table_y_lines = [y for y in y_lines if 450 <= y <= 1240]
    print(f"检测到表格行水平线 Y 坐标 (共 {len(table_y_lines)} 条): {table_y_lines}")

    # 5. 绘制可视化调试图片并保存
    debug_img = img.copy()
    
    # 画红色垂直列线并标注 X 坐标
    for x in x_candidates:
        cv2.line(debug_img, (x, 0), (x, h), (0, 0, 255), 2)
        cv2.putText(debug_img, str(x), (x - 15, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        
    # 画绿色水平行线并标注 Y 坐标
    for y in table_y_lines:
        cv2.line(debug_img, (0, y), (w, y), (0, 255, 0), 2)
        cv2.putText(debug_img, str(y), (10, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        
    # 将高亮网格渲染图保存到本地
    out_debug_path = "template_grid_debug.png"
    cv2.imwrite(out_debug_path, debug_img)
    print(f"分析完毕！网格线高亮核对图已成功保存至: {out_debug_path}")
    print("=" * 40)

if __name__ == "__main__":
    main()
