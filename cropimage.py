# -*- coding: utf-8 -*-
# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
"""
图片裁剪工具 (cropimage.py)
支持命令行运行：python cropimage.py -i <input> -o <output> -x <x> -y <y> -w <width> --height <height>
"""
import os
import sys
import argparse
import cv2
import numpy as np

# === 全局变量与常量声明 / Global Variables and Constants Declarations ===
OPENCV_READ_FLAGS = cv2.IMREAD_COLOR   # OpenCV 图像读取模式（彩色模式） / OpenCV flag specifying the color type of a loaded image (Color)
DEFAULT_SAVE_FORMAT = ".png"           # 默认图片保存后缀 / Default file extension used when saving cropped images

def imread_unicode(path, flags=OPENCV_READ_FLAGS):
    """支持中文路径的图片读取"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, flags)
    except Exception:
        return None

def imwrite_unicode(path, img):
    """支持中文路径的图片保存"""
    try:
        ext = os.path.splitext(path)[1] or DEFAULT_SAVE_FORMAT
        ok, buf = cv2.imencode(ext, img)
        if not ok:
            return False
        buf.tofile(path)
        return True
    except Exception:
        return False

def main():
    parser = argparse.ArgumentParser(description="中燃安全数字监督员图片裁剪工具")
    parser.add_argument("-i", "--input", required=True, help="输入图片路径")
    parser.add_argument("-o", "--output", required=True, help="裁剪后图片保存路径")
    parser.add_argument("-x", type=int, required=True, help="裁剪区域的左上角 X 坐标")
    parser.add_argument("-y", type=int, required=True, help="裁剪区域的左上角 Y 坐标")
    parser.add_argument("-w", "--width", type=int, required=True, help="裁剪宽度")
    parser.add_argument("--height", type=int, required=True, help="裁剪高度")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误: 输入图片文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    img = imread_unicode(args.input)
    if img is None:
        print(f"错误: 无法解码读取图片: {args.input}", file=sys.stderr)
        sys.exit(1)

    h_img, w_img = img.shape[:2]
    x, y, w, h = args.x, args.y, args.width, args.height

    # 边界限制安全检查
    x1 = max(0, min(w_img, x))
    y1 = max(0, min(h_img, y))
    x2 = max(0, min(w_img, x + w))
    y2 = max(0, min(h_img, y + h))

    if x2 <= x1 or y2 <= y1:
        print(f"错误: 裁剪坐标超出合理范围或大小为 0 (图片大小: {w_img}x{h_img})", file=sys.stderr)
        sys.exit(1)

    crop = img[y1:y2, x1:x2]

    # 保存裁剪图片
    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if imwrite_unicode(args.output, crop):
        print(f"成功: 裁剪图已保存至 {args.output}")
        sys.exit(0)
    else:
        print(f"错误: 写入裁剪图片失败: {args.output}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
