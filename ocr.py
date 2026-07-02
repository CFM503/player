"""
中燃"安全数字监督员" OCR 处理器模块 (ocr.py)
面向场景：支持全图扫描/指定坐标区域裁剪扫描，保存裁剪子图及 Markdown 文本结果，支持指定使用 CPU 或 GPU。
可用作 Python 模块导入，亦可独立在命令行运行。
"""

import os
import cv2
import argparse
from typing import List, Dict, Any, Optional

def crop_image(image_path: str, x: int, y: int, w: int, h: int, save_crop_path: Optional[str] = None):
    """
    根据坐标和尺寸裁剪图片，并可选保存裁剪后的图片。
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"无法读取图片: {image_path}")
    img_h, img_w = img.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(img_w, x + w), min(img_h, y + h)
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"无效的裁剪区域: x1={x1}, y1={y1}, x2={x2}, y2={y2}")
    
    crop = img[y1:y2, x1:x2]
    if save_crop_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_crop_path)), exist_ok=True)
        cv2.imwrite(save_crop_path, crop)
        print(f"[OCR] 已保存裁剪图片到: {save_crop_path}")
    return crop

def format_table_cluster(entries: List[Dict[str, Any]]) -> str:
    """
    坐标聚类：根据 Y 轴坐标聚类分行，每行内按 X 轴排序，列间用 | 分隔
    """
    if not entries:
        return ""
    # 按 y_center 排序，检测行间间隙分行
    entries_sorted = sorted(entries, key=lambda e: e["y"])
    rows = []
    current_row = [entries_sorted[0]]
    for prev, cur in zip(entries_sorted, entries_sorted[1:]):
        gap = cur["y"] - prev["y"]
        row_h = max(prev["h"], cur["h"])
        if gap > row_h * 0.6:
            rows.append(current_row)
            current_row = [cur]
        else:
            current_row.append(cur)
    rows.append(current_row)
    
    lines = []
    for row in rows:
        row.sort(key=lambda e: e["x"])
        line = " | ".join(e["text"] for e in row)
        lines.append(line)
    return "\n".join(lines)

def format_table_adaptive(img: Any, entries: List[Dict[str, Any]]) -> str:
    """
    自适应边框检测：利用 OpenCV 形态学操作提取表格分割线，将文本映射到单元格
    """
    import numpy as np
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bw = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
        h, w = bw.shape
        
        # 水平与垂直结构元素提取
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 30, 1), 1))
        h_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)
        h_lines = cv2.dilate(h_lines, h_kernel, iterations=1)
        
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 30, 1)))
        v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)
        v_lines = cv2.dilate(v_lines, v_kernel, iterations=1)
        
        h_proj = np.sum(h_lines, axis=1)
        v_proj = np.sum(v_lines, axis=0)
        h_thresh = w * 128 * 0.3
        v_thresh = h * 128 * 0.3
        row_splits = [i for i in range(len(h_proj)) if h_proj[i] > h_thresh]
        col_splits = [i for i in range(len(v_proj)) if v_proj[i] > v_thresh]
        
        def merge_splits(splits, min_gap=10):
            if not splits:
                return []
            groups = [[splits[0]]]
            for s in splits[1:]:
                if s - groups[-1][-1] < min_gap:
                    groups[-1].append(s)
                else:
                    groups.append([s])
            return [int(np.mean(g)) for g in groups]
            
        row_splits = merge_splits(row_splits)
        col_splits = merge_splits(col_splits)
        
        if len(row_splits) < 2 or len(col_splits) < 2:
            return format_table_cluster(entries)
            
        def find_cell(pos, splits):
            for i in range(len(splits) - 1):
                if splits[i] <= pos <= splits[i + 1]:
                    return i
            return 0 if pos < splits[0] else len(splits) - 2
            
        grid = {}
        for e in entries:
            row_idx = find_cell(e["y"], row_splits)
            col_idx = find_cell(e["x"], col_splits)
            key = (row_idx, col_idx)
            grid[key] = grid.get(key, "") + " " + e["text"] if key in grid else e["text"]
            
        if not grid:
            return format_table_cluster(entries)
            
        max_r = max(k[0] for k in grid)
        max_c = max(k[1] for k in grid)
        lines = []
        for r in range(max_r + 1):
            cells = [grid.get((r, c), "").strip() for c in range(max_c + 1)]
            if any(cells):
                lines.append(" | ".join(cells))
        print(f"[OCR] 自适应边框检测：{len(row_splits)}行 x {len(col_splits)}列")
        return "\n".join(lines) if lines else format_table_cluster(entries)
    except Exception as ex:
        print(f"[OCR] 边框检测失败: {ex}，回退至坐标聚类")
        return format_table_cluster(entries)

_ocr_cache = {}

def get_ocr_instance(device: str = "cpu"):
    """获取并缓存 PaddleOCR 单例，避免重复加载模型文件。支持 'cpu' 和 'gpu' 设备类型。"""
    global _ocr_cache
    if device not in _ocr_cache:
        # 避免 Paddle Inference 兼容性报错
        import paddle.inference as _pi
        if not getattr(_pi.Config, "_patched_for_onednn", False):
            try:
                _orig_new_ir = _pi.Config.enable_new_ir
                _pi.Config.enable_new_ir = lambda self, v=True: _orig_new_ir(self, False)
                _orig_opt = _pi.Config.set_optimization_level
                _pi.Config.set_optimization_level = lambda self, lv: _orig_opt(self, 0)
                _pi.Config._patched_for_onednn = True
            except AttributeError:
                pass
        
        # 强制设置环境变量以使 PaddlePaddle 选择对应设备类型
        if device == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        else:
            if "CUDA_VISIBLE_DEVICES" in os.environ:
                del os.environ["CUDA_VISIBLE_DEVICES"]
            
        from paddleocr import PaddleOCR
        # 初始化 PaddleOCR 实例并缓存在 _ocr_cache 字典中
        _ocr_cache[device] = PaddleOCR(lang="ch", device=device)
        
    return _ocr_cache[device]

def run_ocr(
    image_path: str,
    coords: Optional[tuple] = None,
    save_crop_path: Optional[str] = None,
    save_markdown_path: Optional[str] = None,
    mode: str = "cluster",
    device: str = "cpu"
) -> str:
    """
    执行 OCR 扫描核心流程。
    
    :param image_path: 图片路径
    :param coords: (x, y, w, h) 裁剪区域元组，若为 None 则扫描全图
    :param save_crop_path: 若指定且 coords 有效，保存裁剪后的子图到该文件路径
    :param save_markdown_path: 若指定，将 OCR 结果以 markdown 文件形式保存
    :param mode: 格式化表格模式 ('cluster' 为坐标聚类, 'adaptive' 为自适应边框检测)
    :param device: 使用设备 ('cpu' 或 'gpu'，默认为 'cpu')
    :return: 扫描结果的 markdown/文本字符串 (表数据 + 原文坐标元数据)
    """
    # 1. 读取/裁剪图片
    if coords:
        x, y, w, h = coords
        print(f"[OCR] 区域裁剪 OCR: x={x}, y={y}, w={w}, h={h} (使用设备: {device})")
        img_for_ocr = crop_image(image_path, x, y, w, h, save_crop_path)
        x_offset, y_offset = x, y
    else:
        print(f"[OCR] 默认扫描全图 OCR: {image_path} (使用设备: {device})")
        img_for_ocr = cv2.imread(image_path)
        if img_for_ocr is None:
            raise FileNotFoundError(f"无法读取图片: {image_path}")
        x_offset, y_offset = 0, 0

    # 2. 获取 PaddleOCR 实例并运行识别
    ocr = get_ocr_instance(device=device)
    result = ocr.predict(img_for_ocr)
    
    entries = []
    if result and hasattr(result[0], 'json'):
        res = result[0].json.get('res', {})
        texts = res.get('rec_texts', [])
        polys = res.get('rec_polys', [])
        if texts:
            for i, text in enumerate(texts):
                box = polys[i] if i < len(polys) else []
                if len(box) >= 3:
                    y_center = (box[0][1] + box[2][1]) / 2
                    x_left = box[0][0]
                    height = abs(box[2][1] - box[0][1])
                    width = abs(box[1][0] - box[0][0]) if len(box) >= 2 else 0
                else:
                    y_center, x_left, height, width = 0, 0, 20, 0
                entries.append({"text": text, "y": y_center, "x": x_left, "h": height, "w": width})

    print(f"[OCR] OCR 识别完成，共 {len(entries)} 个文本块")
    if not entries:
        ocr_result = ""
    else:
        # 3. 表格结构化
        if mode == "adaptive":
            table_text = format_table_adaptive(img_for_ocr, entries)
        else:
            table_text = format_table_cluster(entries)
            
        # 4. 输出绝对坐标（基于原始大图的绝对坐标）
        flat_text = "\n".join(
            f"{e['text']}  [{int(e['x'] + x_offset)},{int(e['y'] + y_offset)},{int(e['w'])},{int(e['h'])}]"
            for e in sorted(entries, key=lambda e: (e["y"] // 15, e["x"]))
        )
        ocr_result = f"{table_text}\n---\n{flat_text}"

    # 5. 保存为 markdown 结果
    if save_markdown_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_markdown_path)), exist_ok=True)
        with open(save_markdown_path, "w", encoding="utf-8") as f:
            f.write(ocr_result)
        print(f"[OCR] 已将扫描结果以 Markdown 格式保存至: {save_markdown_path}")

    return ocr_result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OCR Processor Command Line Interface")
    parser.add_argument("image", help="Path to the input image file")
    parser.add_argument("--coord", help="Crop coordinates in format x,y,w,h (e.g. 300,80,200,100). Default is scanning the entire image.")
    parser.add_argument("--save-crop", help="File path to save the cropped region image")
    parser.add_argument("--save-markdown", help="File path to save the OCR scanned Markdown result")
    parser.add_argument("--mode", choices=["cluster", "adaptive"], default="cluster", help="Formatting table mode: cluster (coordinate clustering, default) or adaptive (adaptive border detection)")
    parser.add_argument("--device", choices=["cpu", "gpu"], default="cpu", help="Running device type: cpu (default) or gpu")
    
    args = parser.parse_args()
    
    coords = None
    if args.coord:
        try:
            parts = [int(p.strip()) for p in args.coord.split(",")]
            if len(parts) != 4:
                raise ValueError("Coordinates must consist of 4 integers: x,y,w,h")
            coords = tuple(parts)
        except Exception as e:
            parser.error(f"Invalid format for --coord: {e}. Please use x,y,w,h format.")

    try:
        res = run_ocr(
            image_path=args.image,
            coords=coords,
            save_crop_path=args.save_crop,
            save_markdown_path=args.save_markdown,
            mode=args.mode,
            device=args.device
        )
        print("\n=== OCR Scanned Result ===")
        print(res)
    except Exception as e:
        print(f"[OCR] Execution error: {e}")
