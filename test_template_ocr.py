# -*- coding: utf-8 -*-
# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
"""
模板匹配对齐 + OCR 测试脚本
用 dq.png 模板对齐实拍带气作业票照片，然后 OCR 扫描，输出识别结果
"""
import sys, os, time
sys.path.insert(0, r"d:\SOFT\ai\github\player")

import cv2
import numpy as np

TEMPLATE = r"d:\SOFT\ai\github\player\template\dq.png"
PHOTO    = r"d:\SOFT\ai\github\player\uploads\1783172113_0.png"
OUT_DIR  = r"d:\SOFT\ai\github\player\template"

def align_to_template(photo_path, template_path, debug_dir=None):
    """用 ORB 特征点匹配将实拍照片对齐到模板尺寸"""
    t0 = time.perf_counter()
    
    tmpl = cv2.imread(template_path)
    photo = cv2.imread(photo_path)
    th, tw = tmpl.shape[:2]
    ph, pw = photo.shape[:2]
    print(f"模板尺寸: {tw}x{th}")
    print(f"照片尺寸: {pw}x{ph}")
    
    # 转灰度
    gray_tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
    gray_photo = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    
    # ORB 特征检测
    orb = cv2.ORB_create(nfeatures=5000)
    kp1, des1 = orb.detectAndCompute(gray_tmpl, None)
    kp2, des2 = orb.detectAndCompute(gray_photo, None)
    print(f"模板特征点: {len(kp1)}, 照片特征点: {len(kp2)}")
    
    # BFMatcher 匹配
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)
    
    # Lowe's ratio test 筛选好匹配
    good = []
    for m, n in matches:
        if m.distance < 0.75 * n.distance:
            good.append(m)
    print(f"匹配点: {len(matches)}, 好匹配: {len(good)}")
    
    if len(good) < 10:
        print("⚠️ 好匹配点太少，无法可靠对齐！直接 resize 兜底")
        return cv2.resize(photo, (tw, th))
    
    # 计算 Homography
    pts_tmpl = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    pts_photo = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(pts_photo, pts_tmpl, cv2.RANSAC, 5.0)
    inliers = mask.ravel().sum()
    print(f"Homography 内点: {inliers}/{len(good)}")
    
    # 透视变换对齐
    aligned = cv2.warpPerspective(photo, H, (tw, th))
    
    elapsed = time.perf_counter() - t0
    print(f"对齐耗时: {elapsed:.2f}s")
    
    # 保存对齐结果和调试图
    if debug_dir:
        cv2.imwrite(os.path.join(debug_dir, "aligned_result.png"), aligned)
        print(f"已保存对齐结果: aligned_result.png")
        
        # 画匹配对比图
        match_img = cv2.drawMatches(tmpl, kp1, photo, kp2, good[:50], None, 
                                     flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
        cv2.imwrite(os.path.join(debug_dir, "match_debug.png"), match_img)
        print(f"已保存匹配调试图: match_debug.png")
    
    return aligned


def run_ocr_on_aligned(aligned_img):
    """对对齐后的图片做 OCR，返回结构化结果"""
    from ocr import get_ocr_instance
    
    print("\n" + "=" * 60)
    print("OCR 扫描对齐后的图片")
    print("=" * 60)
    
    t0 = time.perf_counter()
    ocr = get_ocr_instance("gpu")
    t_init = time.perf_counter() - t0
    print(f"OCR 初始化: {t_init:.2f}s")
    
    t1 = time.perf_counter()
    result = ocr.predict(aligned_img)
    t_pred = time.perf_counter() - t1
    
    entries = []
    if result and hasattr(result[0], 'json'):
        res = result[0].json.get('res', {})
        texts = res.get('rec_texts', [])
        polys = res.get('rec_polys', [])
        scores = res.get('rec_scores', [])
        for i, text in enumerate(texts):
            box = polys[i] if i < len(polys) else []
            score = scores[i] if i < len(scores) else 0
            if len(box) >= 3:
                y_center = (box[0][1] + box[2][1]) / 2
                x_left = box[0][0]
                height = abs(box[2][1] - box[0][1])
                width = abs(box[1][0] - box[0][0]) if len(box) >= 2 else 0
            else:
                y_center, x_left, height, width = 0, 0, 20, 0
            entries.append({
                "text": text, 
                "x": int(x_left), 
                "y": int(y_center), 
                "w": int(width), 
                "h": int(height),
                "score": round(score, 3)
            })
    
    print(f"OCR 推理: {t_pred:.2f}s, 识别 {len(entries)} 个文本块")
    print()
    
    # 按 y 坐标排序，模拟从上到下阅读顺序
    entries.sort(key=lambda e: (e["y"] // 12, e["x"]))
    
    print(f"{'序号':>4} | {'文本':<30} | {'坐标 [x,y]':>12} | {'尺寸 [w×h]':>10} | {'置信度':>6}")
    print("-" * 80)
    for i, e in enumerate(entries, 1):
        print(f"{i:>4} | {e['text']:<30} | [{e['x']:>4},{e['y']:>4}] | {e['w']:>3}×{e['h']:<3} | {e['score']:.3f}")
    
    return entries


if __name__ == "__main__":
    print("=" * 60)
    print("模板匹配对齐测试")
    print("=" * 60)
    
    # 1. 对齐
    aligned = align_to_template(PHOTO, TEMPLATE, debug_dir=OUT_DIR)
    
    # 2. OCR
    entries = run_ocr_on_aligned(aligned)
    
    print(f"\n总计识别 {len(entries)} 个文本块")
