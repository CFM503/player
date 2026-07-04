# -*- coding: utf-8 -*-
# 警告：永远不要修改这个文件！ (WARNING: NEVER MODIFY THIS FILE!)
"""
中燃"安全数字监督员" OCR 处理器模块 (ocr.py)
面向场景：支持全图扫描/指定坐标区域裁剪扫描，保存裁剪子图及 Markdown 文本结果，支持指定使用 CPU 或 GPU，以及选择不同的 OCR 引擎（本地 PaddleOCR 或 视觉大模型）。
可用作 Python 模块导入，亦可独立在命令行运行。
"""

import os  # 导入系统接口模块，用于处理文件路径及目录创建等操作
import cv2  # 导入 OpenCV 计算机视觉库，用于图像读取、裁剪及图像形态学处理
import argparse  # 导入命令行参数解析模块，用于处理终端命令行参数输入
from typing import List, Dict, Any, Optional  # 从 typing 模块导入用于类型注解的容器和可选类型

def crop_image(image_path: str, x: int, y: int, w: int, h: int, save_crop_path: Optional[str] = None):  # 定义裁剪图片区域的函数，可选择性保存子图
    # 获取输入参数以裁剪图像
    img = cv2.imread(image_path)  # 使用 OpenCV 根据指定的文件路径读取图片
    if img is None:  # 判断读取的图片是否为空，若为空则说明路径无效或文件损坏
        raise FileNotFoundError(f"无法读取图片: {image_path}")  # 抛出文件未找到的异常并给出路径提示
    img_h, img_w = img.shape[:2]  # 获取读取图片的原始高度 and 宽度尺寸
    x1, y1 = max(0, x), max(0, y)  # 计算并限制裁剪起始点 x1 和 y1 的坐标，确保不小于 0 越界
    x2, y2 = min(img_w, x + w), min(img_h, y + h)  # 计算并限制裁剪结束点 x2 和 y2 的坐标，确保不超过原图尺寸
    if x2 <= x1 or y2 <= y1:  # 判断裁剪的宽度或高度是否无效（即起始点在结束点右下方）
        raise ValueError(f"无效的裁剪区域: x1={x1}, y1={y1}, x2={x2}, y2={y2}")  # 抛出值错误异常，指出不合法的裁剪边界
    
    crop = img[y1:y2, x1:x2]  # 使用 NumPy 切片根据坐标范围裁剪子图像区域
    if save_crop_path:  # 判断是否指定了保存裁剪子图的目标文件路径
        os.makedirs(os.path.dirname(os.path.abspath(save_crop_path)), exist_ok=True)  # 递归创建保存子图所需的父级目录结构
        cv2.imwrite(save_crop_path, crop)  # 调用 OpenCV 的 imwrite 函数将裁剪出的子图保存为图像文件
        print(f"[OCR] 已保存裁剪图片到: {save_crop_path}")  # 打印提示信息，说明子图保存成功及路径
    return crop  # 返回裁剪后的 NumPy 图像数组对象

def format_table_cluster(entries: List[Dict[str, Any]]) -> str:  # 定义基于坐标聚类的表格格式化函数，将识别项转为 Markdown 表格
    # 开始进行聚类格式化
    if not entries:  # 判断传入的识别项 entries 列表是否为空
        return ""  # 若列表为空，则直接返回空字符串
    # 按 y_center 排序，检测行间间隙分行
    entries_sorted = sorted(entries, key=lambda e: e["y"])  # 根据文本块中心的 Y 轴坐标对所有识别项进行升序排序
    rows = []  # 初始化外层行容器列表，用于存放分组后的每一行文本块
    current_row = [entries_sorted[0]]  # 将排序后的第一个文本块作为当前行的起始文本块
    for prev, cur in zip(entries_sorted, entries_sorted[1:]):  # 遍历相邻的文本块以判断是否换行
        gap = cur["y"] - prev["y"]  # 计算相邻两个文本块在 Y 轴中心坐标上的垂直差距
        row_h = max(prev["h"], cur["h"])  # 获取两相邻文本块高度的最大值，作为基准高度
        if gap > row_h * 0.6:  # 如果两块的垂直间距超过了其高度的 60%，判定为换行
            rows.append(current_row)  # 将累积的当前行文本块列表保存到外层行容器中
            current_row = [cur]  # 重置当前行容器，并将当前循环文本块作为新行的起点
        else:  # 若间距在阈值范围内，判定为同一行文本
            current_row.append(cur)  # 将当前循环文本块追加到当前行容器中
    rows.append(current_row)  # 将最后一行的所有文本块列表保存到外层行容器中
    
    lines = []  # 初始化字符串行列表，用于保存拼接后的每行文本字符串
    for row in rows:  # 遍历分行后的每一行文本块列表
        row.sort(key=lambda e: e["x"])  # 在每一行内部，按照 X 轴坐标对文本块进行从左到右排序
        line = " | ".join(e["text"] for e in row)  # 用竖线 " | " 将同一行内的各文本块内容拼接起来
        lines.append(line)  # 将拼接好的一行字符串添加到行列表中
    return "\n".join(lines)  # 用换行符连接各行字符串，并返回最终结构化的多行表格字符串


_ocr_cache = {}  # 初始化全局 OCR 缓存字典，键为 device 类型，值为初始化好的 PaddleOCR 实例对象

def get_ocr_instance(device: str = "cpu", det_db_box_thresh: Optional[float] = None, drop_score: Optional[float] = None):  # 定义获取或缓存 PaddleOCR 实例单例的函数
    # 保证同一个计算设备下的模型只被初始化和加载一次
    global _ocr_cache  # 声明全局变量以在函数内部修改 _ocr_cache 字典
    if device not in _ocr_cache:  # 检测请求的设备对应的 OCR 实例是否尚未加载在缓存中
        # 避免 Paddle Inference 兼容性报错
        import paddle.inference as _pi  # 临时导入 Paddle Inference 推理底层库
        if not getattr(_pi.Config, "_patched_for_onednn", False):  # 检查是否尚未应用针对 Intel CPU 的 OneDNN 补丁
            try:  # 开启异常防护
                _orig_new_ir = _pi.Config.enable_new_ir  # 保存原始的 enable_new_ir 函数引用
                _pi.Config.enable_new_ir = lambda self, v=True: _orig_new_ir(self, False)  # 重写 enable_new_ir，强制关闭 PIR 以防止属性转换异常
                _orig_opt = _pi.Config.set_optimization_level  # 保存原始的 set_optimization_level 函数引用
                _pi.Config.set_optimization_level = lambda self, lv: _orig_opt(self, 0)  # 重写优化级别设置，强制设置为最低级别 0 保证稳定性
                _pi.Config._patched_for_onednn = True  # 在底层类上标记已打好补丁，避免被二次修改重写
            except AttributeError:  # 若当前底层库版本不支持这些方法，捕获属性错误
                pass  # 安全跳过补丁应用流程
        
        # 强制设置环境变量以使 PaddlePaddle 选择对应设备类型
        if device == "cpu":  # 判断选择运行的硬件设备是否为 CPU 处理器
            os.environ["CUDA_VISIBLE_DEVICES"] = ""  # 强制清除系统可见的 CUDA 显卡，使底层框架降级走 CPU 进行模型运算
        else:  # 若选择 GPU 进行加速推理
            if "CUDA_VISIBLE_DEVICES" in os.environ:  # 检查系统环境变量中是否已定义了禁用的显卡设备
                del os.environ["CUDA_VISIBLE_DEVICES"]  # 从系统环境变量中删除禁用项，使显卡在 runtime 下可见
            
        from paddleocr import PaddleOCR  # 导入官方 PaddleOCR 核心包
        kwargs = {"lang": "ch", "device": device}
        if det_db_box_thresh is not None:
            kwargs["text_det_box_thresh"] = det_db_box_thresh
        if drop_score is not None:
            kwargs["text_rec_score_thresh"] = drop_score
        _ocr_cache[device] = PaddleOCR(**kwargs)  # 实例化支持中文识别的本地模型，动态传入参数
        
    return _ocr_cache[device]  # 返回缓存字典中获取到的 PaddleOCR 实例对象

def run_vision_ocr(image_path: str, api_key: str, base_url: str, model_name: str) -> str:  # 定义调用 OpenAI 接口通过视觉大模型进行表格识别的函数
    # 读图并编码为 base64 发送给 LLM
    import base64  # 导入 base64 编码解码库，用于转换图片数据格式
    from openai import OpenAI  # 导入标准的 OpenAI 客户端类，用于进行对话服务通信
    
    if not api_key:  # 检查传入的大模型 API 鉴权秘钥是否为空
        raise ValueError("API key must be provided for vision engine.")  # 若秘钥为空，抛出值错误，提示必须输入 API Key
        
    client = OpenAI(api_key=api_key, base_url=base_url)  # 使用传入的 API Key 和 Base URL 构建 OpenAI 客户端实例
    
    with open(image_path, "rb") as f:  # 以二进制只读方式打开指定的源图像文件
        b64 = base64.b64encode(f.read()).decode()  # 读取全部文件字节、进行 base64 编码并解码为 UTF-8 文本串格式
        
    prompt = (  # 定义发送给视觉大模型的提示词要求
        "请识别这张表格图片中的全部内容，输出 Markdown 表格格式。\n"  # 告知主要识别和输出格式要求
        "要求：\n"  # 列举大模型的详细执行指标约束
        "1. 保留所有勾选符号（✓、×、√、X），准确填入对应单元格\n"  # 规定对于特殊打勾打叉等确认符号在网格内的精准位置定位要求
        "2. 合并单元格用 Markdown 标准语法表达，保持行列对齐\n"  # 规定合并单元格的处理方式
        "3. 手写体文字标注（手写）\n"  # 规定对于手写签批文字需要添加特定的后缀标注
        "4. 仅输出 Markdown，不要解释"  # 约束输出结果的纯净性，防止大模型带有冗长的前导后尾解释语
    )  # 结束提示词定义
    
    resp = client.chat.completions.create(  # 调用大模型对话完成（Chat Completions）接口，提交大图及识别提示词
        model=model_name,  # 指定调用接口的模型名称，如硅基流动或 OpenAI 对应的视觉端模型
        messages=[{  # 填充聊天消息内容
            "role": "user",  # 设置发送者角色为普通用户 user
            "content": [  # 发送多模态混合内容
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},  # 将 base64 图像以 data URI 格式传递给模型
                {"type": "text", "text": prompt},  # 将多模态文字识别提示词指令传递给大模型
            ],  # 结束多模态消息数组定义
        }],  # 结束消息列表定义
        temperature=0.1,  # 设定模型采样温度值为低随机的 0.1，以最大限度减少幻觉保证识别准确率
        max_tokens=8192,  # 设定最大生成 Token 数量上限限制为 8192
        timeout=120,  # 设定接口调用最大允许超时时间为 120 秒
    )  # 结束接口调用定义
    return resp.choices[0].message.content.strip()  # 提取获取的响应内容，并去除头部尾部所有的空白符后返回结果

def align_to_template(photo_path: str, template_path: str) -> tuple:  # 用 ORB 特征点匹配将实拍照片对齐到模板尺寸
    """
    用 ORB 特征点匹配将实拍照片对齐到模板尺寸
    返回: (aligned_image, is_aligned)
    """
    import numpy as np  # 导入 NumPy
    try:
        tmpl = cv2.imread(template_path)  # 读取模板图
        photo = cv2.imread(photo_path)  # 读取照片图
        if tmpl is None or photo is None:  # 如果任意图片读取失败
            return photo, False
            
        th, tw = tmpl.shape[:2]  # 获取模板的尺寸
        
        # 转灰度
        gray_tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
        gray_photo = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
        
        # ORB 特征检测
        orb = cv2.ORB_create(nfeatures=5000)
        kp1, des1 = orb.detectAndCompute(gray_tmpl, None)
        kp2, des2 = orb.detectAndCompute(gray_photo, None)
        
        if des1 is None or des2 is None:  # 如果没有检测到特征点
            return photo, False
            
        # BFMatcher 匹配
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        matches = bf.knnMatch(des1, des2, k=2)
        
        # Lowe's ratio test 筛选匹配点
        good = []
        for m, n in matches:
            if m.distance < 0.75 * n.distance:
                good.append(m)
                
        if len(good) < 15:  # 如果好匹配点太少，说明并非同一种表格模板，不进行对齐
            return photo, False
            
        # 计算单应性矩阵 (Homography)
        pts_tmpl = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        pts_photo = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(pts_photo, pts_tmpl, cv2.RANSAC, 5.0)
        
        if H is None:  # 如果无法计算单应性矩阵
            return photo, False
            
        # 进行透视变换
        aligned = cv2.warpPerspective(photo, H, (tw, th))
        return aligned, True
    except Exception as e:
        print(f"[OCR] 模板匹配对齐失败: {e}")
        return None, False

def run_ocr(  # 定义 OCR 扫描最核心的总控制运行调度函数
    image_path: str,  # 参数一：输入待扫描的主图片文件路径
    coords: Optional[tuple] = None,  # 参数二：可选的裁剪区域坐标元组 (x, y, w, h)，默认为 None 扫描全图
    save_crop_path: Optional[str] = None,  # 参数三：可选的裁剪出的子图像保存路径，默认不保存
    save_markdown_path: Optional[str] = None,  # 参数四：可选的扫描完成后的 Markdown 文本文件保存目标路径
    mode: str = "cluster",  # 参数五：已废弃，保留用于兼容性
    device: str = "cpu",  # 参数六：本地 OCR 执行所选的硬件计算设备 (cpu 或 gpu)
    engine: str = "paddleocr",  # 参数七：核心检测引擎种类类型 ('paddleocr' 本地，或 'vision' 云端大模型)
    api_key: Optional[str] = None,  # 参数八：视觉大模型鉴权 Key，仅在 engine='vision' 下有效
    base_url: Optional[str] = None,  # 参数九：视觉大模型接口的基础基地址域名路径
    model_name: Optional[str] = None,  # 参数十：所选取的具体云端大模型工程别名
    det_db_box_thresh: Optional[float] = None,  # 参数十一：文本框检测阈值，为空则使用原生默认值
    drop_score: Optional[float] = None  # 参数十二：识别文本输出的置信度丢弃阈值，为空则使用原生默认值
) -> str:  # 表明函数最终返回为扫描出的字符串内容结果
    # 1. 运行视觉大模型（不需要裁剪和 PaddleOCR 识别）
    if engine == "vision":  # 检查设置的核心引擎是否选择为视觉大模型模式
        print(f"[OCR] Running Vision LLM OCR: {image_path} (model: {model_name})")  # 控制台打印运行状态，说明正在执行 Vision OCR 及其模型名
        ocr_result = run_vision_ocr(image_path, api_key or "", base_url or "", model_name or "")  # 执行 Vision API 请求，并保存获取到的 Markdown 结果
        
        # 保存为 markdown 结果
        if save_markdown_path:  # 如果用户提供了 markdown 输出的持久化保存路径
            os.makedirs(os.path.dirname(os.path.abspath(save_markdown_path)), exist_ok=True)  # 自动创建目标 Markdown 文件所需的各级父目录
            with open(save_markdown_path, "w", encoding="utf-8") as f:  # 以 UTF-8 编码新建并只写打开该目标 Markdown 文件
                f.write(ocr_result)  # 将大模型处理返回的表格及内容数据直接写入到文件中
            print(f"[OCR] Saved scan result in Markdown format to: {save_markdown_path}")  # 终端打印文件存储成功的状态和保存的真实物理路径
        return ocr_result  # 执行完成后提前返回大模型的识别结果，跳过后续本地处理流程

    # 2. 本地 PaddleOCR 流程：读取/裁剪图片
    if coords:  # 若局部裁剪元组参数有效
        x, y, w, h = coords  # 解包四元组元数据，提取坐标起点 x, y 以及宽度 w，高度 h
        print(f"[OCR] 区域裁剪 OCR: x={x}, y={y}, w={w}, h={h} (使用设备: {device})")  # 控制台打印开始局部裁剪识别的信息和设备选项
        img_for_ocr = crop_image(image_path, x, y, w, h, save_crop_path)  # 调用 crop_image 裁剪图片，并返回局部内存图像数组
        x_offset, y_offset = x, y  # 将全局坐标偏移值设置为裁剪起点的 x 和 y
    else:  # 若没有传入裁剪参数，则默认处理全图
        print(f"[OCR] 默认扫描全图 OCR: {image_path} (使用设备: {device})")  # 控制台打印扫描全图状态和设备选项
        img_for_ocr = cv2.imread(image_path)  # 直接读取全图以做处理
        if img_for_ocr is None:  # 判断读取是否返回空
            raise FileNotFoundError(f"无法读取图片: {image_path}")  # 抛出异常指出图片加载失败
        x_offset, y_offset = 0, 0  # 偏移值设为 0，因为图像就是原始图像，坐标无需修正偏移量

    # 3. 获取 PaddleOCR 实例并运行识别
    ocr = get_ocr_instance(device=device, det_db_box_thresh=det_db_box_thresh, drop_score=drop_score)  # 从单例方法中获取该设备对应的 PaddleOCR 实例对象
    result = ocr.predict(img_for_ocr)  # 运行 PaddleOCR 模型，预测得出图片中文字的包围框及文本内容结果
    
    entries = []  # 初始化临时识别条目列表
    if result and hasattr(result[0], 'json'):  # 判断返回结构是否有效并且包含 JSON 属性字段信息
        res = result[0].json.get('res', {})  # 提取结构化识别节点 res 字典
        texts = res.get('rec_texts', [])  # 获取识别出的所有非空文本数组
        polys = res.get('rec_polys', [])  # 获取每一个文本行对应的包围框多边形顶点数组坐标
        if texts:  # 若识别出至少一行文本内容
            for i, text in enumerate(texts):  # 迭代每一行文本，并追踪索引序号 i
                box = polys[i] if i < len(polys) else []  # 提取该行文本对应的多边形顶点框
                if len(box) >= 3:  # 如果顶点框至少含有三个坐标顶点，说明其为合法的多边形
                    y_center = (box[0][1] + box[2][1]) / 2  # 计算计算多边形顶点中心线处的垂直 Y 轴中值坐标
                    x_left = box[0][0]  # 获取多边形包围框最左端的起始 X 轴顶点坐标
                    height = abs(box[2][1] - box[0][1])  # 计算估算文本行的大致高度
                    width = abs(box[1][0] - box[0][0]) if len(box) >= 2 else 0  # 计算估算文本行的大致宽度
                else:  # 若框不完整或格式异常
                    y_center, x_left, height, width = 0, 0, 20, 0  # 降级退回使用安全的默认定位数据值
                entries.append({"text": text, "y": y_center, "x": x_left, "h": height, "w": width})  # 将该条目的定位和内容存入条目列表

    print(f"[OCR] OCR 识别完成，共 {len(entries)} 个文本块")  # 控制台打印输出成功提取了多少个文字块
    if not entries:  # 如果没有识别到任何文本内容（例如全白或全黑图片）
        ocr_result = ""  # 初始化结果为空字符串
    else:  # 若有文本识别成功
        # 4. 表格结构化
        table_text = format_table_cluster(entries)  # 执行基于行高度落差聚类还原算法，格式化获取表格文本
            
        # 5. 输出绝对坐标（基于原始大图的绝对坐标）
        flat_text = "\n".join(  # 用换行符将所有的详细文字坐标块串联拼接起来
            f"{e['text']}  [{int(e['x'] + x_offset)},{int(e['y'] + y_offset)},{int(e['w'])},{int(e['h'])}]"  # 每行附带绝对 X, Y 轴坐标（融合了局部偏移值）
            for e in sorted(entries, key=lambda e: (e["y"] // 15, e["x"]))  # 对各文本行先进行大段垂直间距排序，再在横向排序以保证正常人类阅读顺序
        )  # 结束扁平文本的构建
        ocr_result = f"{table_text}\n---\n{flat_text}"  # 拼接结构化表格结果与扁平详细坐标原文结果，用三横线做明确分界

    # 6. 保存为 markdown 结果
    if save_markdown_path:  # 如果用户传入了有效的目标输出 Markdown 文件保存路径
        os.makedirs(os.path.dirname(os.path.abspath(save_markdown_path)), exist_ok=True)  # 新建并自动打通所需要的文件目录架构路径
        with open(save_markdown_path, "w", encoding="utf-8") as f:  # 新建并以 UTF-8 只写格式打开该目标文件
            f.write(ocr_result)  # 写入拼接后的 Markdown 字符串文本数据
        print(f"[OCR] 已将扫描结果以 Markdown 格式保存至: {save_markdown_path}")  # 输出控制台日志，说明结果保存完毕及其文件绝对物理地址

    return ocr_result  # 函数返回最终的 OCR 结果文本字符串

if __name__ == "__main__":  # 判断当前是否为终端直接执行该脚本的独立进程状态
    parser = argparse.ArgumentParser(description="OCR Processor Command Line Interface")  # 构建并定义命令参数解析器的描述头部对象
    parser.add_argument("image", help="Path to the input image file")  # 添加位置参数：传入输入图片的物理文件路径（必填项）
    parser.add_argument("--coord", help="Crop coordinates in format x,y,w,h (e.g. 300,80,200,100). Default is scanning the entire image.")  # 添加局部裁剪坐标参数，用于定位填表人等位置
    parser.add_argument("--save-crop", help="File path to save the cropped region image")  # 添加保存裁剪的局部子图像图片的路径参数
    parser.add_argument("--save-markdown", help="File path to save the OCR scanned Markdown result")  # 添加保存识别出来的 markdown 文本路径参数
    parser.add_argument("--device", choices=["cpu", "gpu"], default="cpu", help="Running device type: cpu (default) or gpu")  # 添加运行硬件设备 CPU / GPU 的枚举配置参数
    parser.add_argument("--engine", choices=["paddleocr", "vision"], default="paddleocr", help="OCR engine type: paddleocr (default) or vision (Vision LLM)")  # 添加引擎的参数配置
    parser.add_argument("--api-key", help="API key for Vision LLM (required if engine is vision)")  # 添加 Vision API 鉴权所需的 API 密码参数
    parser.add_argument("--base-url", default="https://api.siliconflow.cn/v1", help="API base URL for Vision LLM")  # 添加 Vision 大模型的默认基地址参数（默认使用硅基流动）
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-7B-Instruct", help="Model name for Vision LLM")  # 添加 Vision 大模型默认的模型名称（默认使用 Qwen）
    parser.add_argument("--det-thresh", type=float, default=None, help="Detection threshold for DB box (det_db_box_thresh)")
    parser.add_argument("--drop-score", type=float, default=None, help="Drop score for text recognition")
    
    args = parser.parse_args()  # 触发解析，捕获并保存命令行中所有的输入参数属性
    
    coords = None  # 初始化裁剪坐标元组为空，作为默认值
    if args.coord:  # 检测用户在命令行中是否定义了 `--coord` 输入参数
        try:  # 开启参数转换的异常处理快
            parts = [int(p.strip()) for p in args.coord.split(",")]  # 以逗号为界分割参数文本并逐一剥离空格、强转为整数
            if len(parts) != 4:  # 判断解析出来的数值个数是否不等于要求的 4 个（x, y, w, h）
                raise ValueError("Coordinates must consist of 4 integers: x,y,w,h")  # 抛出非法长度的值错误异常
            coords = tuple(parts)  # 转换为不可变的坐标元组以匹配后面的函数签名要求
        except Exception as e:  # 捕获以上转换及校验过程中的全部异常情况
            parser.error(f"Invalid format for --coord: {e}. Please use x,y,w,h format.")  # 直接调用解析器抛出错误详情，并退出进程

    try:  # 启动主流程执行防护
        res = run_ocr(  # 核心运行 run_ocr 接口，传递命令行中的对应参数
            image_path=args.image,  # 传入解析得到的输入图片物理地址
            coords=coords,  # 传入裁剪坐标元组或默认的 None值
            save_crop_path=args.save_crop,  # 传入裁剪出的子图保存路径或者默认的 None 值
            save_markdown_path=args.save_markdown,  # 传入保存文本的 markdown 路径
            device=args.device,  # 传入指定的 CPU 或 GPU 计算设备
            engine=args.engine,  # 传入选定的本地或大模型检测引擎
            api_key=args.api_key if hasattr(args, "api_key") else getattr(args, "api_key", None),  # 传入 API Key，不存在时返回 None
            base_url=args.base_url,  # 传入基地址参数
            model_name=args.model_name,  # 传入模型具体名称参数
            det_db_box_thresh=args.det_thresh,  # 传入文本框检测阈值
            drop_score=args.drop_score  # 传入识别结果置信度阈值
        )  # 结束 run_ocr 主控运行调用
        print("\n=== OCR Scanned Result ===")  # 终端打印输出结果展示头部装饰线
        print(res)  # 打印输出最终的识别文本表格及原文坐标详情信息结果
    except Exception as e:  # 捕获在 run_ocr 执行流程中抛出的任何系统异常
        print(f"[OCR] Execution error: {e}")  # 终端输出 OCR 模块最终的报错指示原因信息，以供调试排查
