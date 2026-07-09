"""
中燃"安全数字监督员"智能体核心架构 (agent_core.py)
面向场景：巡检工人手机拍照上传 -> 自动去阴影矫正 -> 线上API语义结构化 -> 自动化闭环。

v3.12.5 变更：
  - 清理过期及不匹配的测试脚本：移除 `test_e2e.py` 与 `test_mcp.py`，更新相关文档目录树。

v3.12.4 变更：
  - 局部裁剪坐标 OCR 定向人名提取：重构并简化 `extract_filler_name()`，移除了低效的全局 OCR 坐标范围匹配和正则兜底，改为利用缓存的 `_last_image_path` 直接调用 `_ocr_crop_region` 裁剪指定区域进行定向 PaddleOCR 识别提取。

v3.12.3 变更：
  - 核心架构代码逐行中文注释：对核心引擎 `agent_core.py` 内部所有数据结构、LLM 大脑提取规整校验逻辑、Agent 执行工具（去阴影预处理、天气探针、SQLite 存储、钉钉 AI 表格 MCP 写入）及 ReAct 编排流水线的每一行代码添加了详尽的中文行级注释，实现项目 100% 逐行中文注释覆盖。

v3.12.2 变更：
  - 代码注释优化：对独立模块 `ocr.py` 内部所有函数和 CLI 执行模块的每一行代码添加了详尽的中文注释。

v3.12.1 变更：
  - 完善 `ocr.py` 的多引擎支持：正式继承“本地 PaddleOCR”与“视觉大模型 (Vision LLM)”双引擎，且在 Vision LLM 引擎下支持大模型相关参数配置。
  - 修复 PaddleOCR 3.x 版本中不支持 `use_gpu` 的问题，改用 `device`（`cpu` 或 `gpu`）。

v3.12.0 变更：
  - 解耦重构：提取 OCR 相关代码至独立的 `ocr.py` 模块。
  - `ocr_tool()` 和 `_ocr_crop_region()` 改为导入并委托 `ocr.run_ocr()` 处理，支持坐标裁剪及 Markdown 扫描结果输出，且支持选择 CPU 或 GPU 运行。

v3.11.0 变更：
  - 基于坐标的责任人定位提取：`extract_filler_name()` 升级为对特定填表坐标区域精确定位匹配。
  - OCR flat_text 输出包含 `[x,y,w,h]` 元数据。
  - 新增 `_ocr_crop_region()` 方法用于裁剪图片指定区域进行定向 OCR 识别。
  - 精简 OCR 表格模式，移除 `precise` 和 `test` 模式，前端 UI 对应优化。
  - 移除 OCR 图像去阴影兜底重试机制。

v3.10.0 变更：
  - 钉钉通知从 Webhook POST 重写为 MCP Streamable HTTP 协议写入钉钉 AI 表格（多维表）。
  - AgentTools 新增 _discover_dingtalk_fields / _load_dingtalk_cache / _save_dingtalk_cache /
    _run_async / _ping_dingtalk_mcp 五个辅助方法，write_dingtalk_table() 完全重写。
  - 移除企业微信推送（send_wechat_alert / send_dingtalk_alert Webhook 路径）。

依赖库:
pip install pydantic openai paddleocr opencv-python numpy requests mcp httpx -i https://pypi.tuna.tsinghua.edu.cn/simple
"""

import os  # 导入系统接口模块，用于处理文件路径及环境变量
import json  # 导入 JSON 数据解析库以序列化和反序列化配置及隐患数据
import time  # 导入时间时间戳模块，用于获取系统时间进行归档
import asyncio  # 导入异步 IO 协程库以异步执行数据库及网关写入等操作
import logging  # 导入日志记录模块，配置系统日志等级
logging.getLogger("streamlit").setLevel(logging.ERROR)  # 屏蔽后台线程中 Streamlit 原生的 ScriptRunContext 错误噪音以防刷屏
import warnings  # 导入警告过滤模块以屏蔽第三方库的多余警告信息
warnings.filterwarnings("ignore", category=UserWarning, module="paddle")  # 忽略 PaddlePaddle 内部关于 ccache 等非致命性用户警告
from typing import List, Dict, Any, Optional  # 从 typing 模块导入用于类型注解的容器和可选类型
from pydantic import BaseModel, Field  # 从 Pydantic 库中导入数据模型基类及字段注解定义，用于结构化作业票

# ---- 全局配置 ----
HEARTBEAT_INTERVAL = 30  # 设定阻塞操作期间后台线程打印心跳的默认间隔时长为 30 秒，设为 0 表示禁用

# ---- 全局变量 ----
# 全局坐标变量已废弃，提取操作现在使用对齐后的模板固定坐标


import re  # 导入正则匹配模块，用于清理思考文本及过滤匹配安全条款
import sys  # 导入系统工具模块，用于获取和重定向标准输入输出流

# ---- 全局常量 ----
OCR_TEXT_MAX_CHARS = 4000  # 设定发送给 LLM 的 OCR 识别文本的最大字符数上限，过长会被截断防超时


def safe_write(stream, text: str):  # 定义安全写入数据流的辅助函数，规避 Windows 终端在输出中文时的 GBK 编码异常
    # 尝试将文本写入输出流
    if not stream or not text:  # 检查目标流或要写入的文本是否为空
        return  # 直接返回，不做处理
    try:  # 开启常规写尝试
        stream.write(text)  # 直接将文本写入输出流中
        stream.flush()  # 强制刷新输出缓冲区
    except UnicodeEncodeError:  # 捕获因终端不支持当前字符集的编码异常
        encoding = getattr(stream, "encoding", "utf-8") or "utf-8"  # 获取流上配置的字符集，无则默认 UTF-8
        try:  # 开启字符替换降级写尝试
            stream.write(text.encode(encoding, errors="replace").decode(encoding))  # 将无法转换的字符替换为问号后写入
            stream.flush()  # 刷新流缓冲区
        except Exception:  # 捕获降级失败异常
            pass  # 跳过不处理
    except Exception:  # 捕获其他未知输出异常
        pass  # 忽略错误以保障程序不因打印中断


def safe_print(*args, sep=" ", end="\n", file=None, flush=False):  # 定义安全打印输出的辅助函数，支持格式化和错误容灾
    """安全打印，处理 Windows 控制台 UnicodeEncodeError。"""
    if file is None:  # 如果输出流参数为 None
        file = sys.stdout  # 默认使用系统标准输出流 sys.stdout
    text = sep.join(str(arg) for arg in args) + end  # 用分隔符将所有参数连接起来并追加换行符
    safe_write(file, text)  # 调用 safe_write 函数安全写入流中
    if flush:  # 判断是否要求立即刷新缓冲区
        try:  # 开启刷新尝试
            file.flush()  # 刷新对应的数据流
        except Exception:  # 捕获异常
            pass  # 忽略错误


def clean_thinking(text: str) -> str:  # 定义用于过滤大模型输出中包含的 <think> 思考过程标签及 markdown 标记的函数
    """过滤模型输出中的思考过程标签并清理 markdown 格式"""
    if not text:  # 检查文本是否为空
        return ""  # 空时直接返回空串
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)  # 使用正则跨行匹配删除 <think> 包裹的完整思考段
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)  # 兜底删除因截断而残存的未闭合的 <think> 标签及其后所有文本
    text = text.strip()  # 去除两侧空白字符
    if text.startswith("```json"):  # 判断是否以 markdown 代码块前缀 ```json 开头
        text = text[7:]  # 截断去掉前 7 个字符以提取 JSON 纯文本
    elif text.startswith("```"):  # 判断是否以普通代码块 ``` 开头
        text = text[3:]  # 截断去掉前 3 个字符
    if text.endswith("```"):  # 判断是否以代码块后缀 ``` 结尾
        text = text[:-3]  # 截断去掉最后 3 个字符
    return text.strip()  # 去除两侧空白后返回纯净的文本字串


# 根据国家和行业 HSE 标准配置作业票对应的法规及限值参数
TICKET_STANDARDS = {  # 定义标准比对字典
    "动火作业票": {  # 动火安全标准
        "standard_name": "GB 30871-2022",  # 法规文号
        "standard_desc": "《危险化学品企业特殊作业安全规范》",  # 法规全称
        "clear_dist_desc": "动火点10m内清除可燃物并配备合适足量的消防器材"  # 安全警戒距离说明
    },  # 结束动火
    "带气作业票": {  # 带气作业安全标准
        "standard_name": "CJJ 51-2016",  # 法规文号
        "standard_desc": "《城镇燃气设施运行、维护和抢修安全技术规程》",  # 法规全称
        "clear_dist_desc": "作业区域与周边做到可靠的隔离，现场设置明显标志，夜间设置警示灯"  # 隔离防爆标志要求说明
    }  # 结束带气
}  # 结束字典定义


# 国家及企业关于不同作业票中规定必须逐一落实的法定安全措施条款
STANDARD_MEASURES = {  # 定义法定防范措施表字典
    "动火作业票": [  # 动火作业对应的 21 条安全检查措施列表
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
        (21, "其他补充安全措施：")
    ],  # 结束动火措施列表
    "带气作业票": [  # 带气抢修对应的 25 条安全检查措施列表
        (1, "作业人具备相应的作业资格。"),
        (2, "作业人已接受作业安全教育，包括应急处置方案学习。"),
        (3, "现场人员已穿戴好安全防护用品，如防静电工作服、鞋、空气呼吸器等"),
        (4, "作业人员严禁携带各类火种、非防爆电子用品进入带气作业区域。"),
        (5, "作业现场监护人已到位。"),
        (6, "作业现场配有效、适用的气体检测仪。"),
        (7, "采用防爆工具、防爆防静电措施进行带气作业。"),
        (8, "包括照明在内的所有电器设备、线路及连接口应符合防爆要求。"),
        (9, "根据带气作业方式及带气作业环境，封堵机、夹管器、阻气袋等相应设备设施已配置齐全。"),
        (10, "PE焊接过程配备专用夹具、水平尺等工具，以便校直待连接的管材和管件，避免电熔焊过程短路燃烧和虚焊。"),
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
    ]  # 结束带气措施列表
}  # 结束字典定义


def check_measure_status_in_ocr(ocr_text: str, desc: str, ticket_type: str) -> Optional[bool]:  # 定义利用 OCR 结果启发式匹配安全措施勾选框状态的算法函数
    # 传入原始 OCR 文本和单条条款进行检查
    if not ocr_text:  # 检查 OCR 文本是否为空
        return None  # 空时无法比对，返回 None 占位



    lines = [l.strip() for l in ocr_text.split("\n") if l.strip()]  # 按行拆分 OCR 文本，去除空白并过滤空行
    norm_desc = re.sub(r"[^\w\u4e00-\u9fa5]", "", desc)  # 用正则剔除待查条款中的所有非字元符号，只留汉字字母以防干扰
    if not norm_desc:  # 检查清洗后的条款文本是否为空
        return None  # 空白则无法比对
    
    std_list = STANDARD_MEASURES.get(ticket_type, [])  # 获取该作业票类型对应的所有法定防范条款定义
    best_idx = -1  # 初始化最佳匹配在行列表中的索引位置为 -1
    
    # 优先使用最长公共子串启发式匹配，抗 OCR 识别/轻微错字能力强
    match_len = max(5, min(8, len(norm_desc)))
    for idx, line in enumerate(lines):
        norm_line = re.sub(r"[^\w\u4e00-\u9fa5]", "", line)
        if len(norm_line) >= match_len:
            has_common = False
            for i in range(len(norm_desc) - match_len + 1):
                sub = norm_desc[i:i+match_len]
                if sub in norm_line:
                    has_common = True
                    break
            if has_common:
                best_idx = idx
                break
                
    if best_idx != -1:  # 若最终定位到了条款在 OCR 原文中的具体行位置
        matched_line = lines[best_idx]
        
        # 1. 优先对齐并支持 Markdown 单元格内的符号提取
        if "|" in matched_line:
            parts = [p.strip() for p in matched_line.split("|")]
            if parts and parts[0] == "":
                parts.pop(0)
            if parts and parts[-1] == "":
                parts.pop()
            
            best_part_idx = -1
            best_match_len = 0
            for p_idx, part in enumerate(parts):
                part_norm = re.sub(r"[^\w\u4e00-\u9fa5]", "", part)
                intersection = len(set(part_norm) & set(norm_desc))
                if intersection > best_match_len:
                    best_match_len = intersection
                    best_part_idx = p_idx
            
            if best_part_idx != -1:
                check_cols = parts[best_part_idx + 1:]
                if check_cols:
                    # 检查是否全部为空白（无任何打勾、打叉、斜杠等填充符号）
                    # 剥离掉常见的空格、连字符等占位符
                    all_empty = all(re.sub(r"[\s—–\-]", "", col) == "" for col in check_cols)
                    if all_empty:
                        return False  # 全部空白视为未勾选（未落实）

                    has_neg = False
                    has_pos = False
                    for col in check_cols:
                        col_lower = col.lower()
                        col_upper = col.upper()
                        # 对于带气作业票，负向标志包含叉号及未填写/空白状态
                        neg_list = ["×", "x", "未填写", "空"] if ticket_type == "带气作业票" else ["×", "x", "未落实", "不适用", "/", "\\"]
                        if any(x in col_lower for x in neg_list):
                            has_neg = True
                        if any(x in col_upper for x in ["✓", "√", "v", "7", "1", "j", "已落实", "是"]):
                            has_pos = True
                    
                    if has_neg:
                        return False
                    if ticket_type == "带气作业票":
                        # 带气作业票只要扫描不到叉号就算落实
                        return True
                    if has_pos:
                        return True

        # 2. 对非 Markdown 表格但符号与文字处在同行的规则进行清洗后校验
        clean_desc_chars = set(norm_desc)
        line_remaining = []
        for char in matched_line:
            if char not in clean_desc_chars and char not in ["第", "条", "项"]:
                line_remaining.append(char)
        remaining_str = "".join(line_remaining).strip()
        remaining_lower = remaining_str.lower()
        remaining_upper = remaining_str.upper()
        
        # 检查是否完全没有符号内容（空白）
        if re.sub(r"[\s—–\-]", "", remaining_str) == "":
            return False  # 视为未落实

        neg_list = ["×", "x", "未填写", "空"] if ticket_type == "带气作业票" else ["×", "x", "未落实", "不适用", "/", "\\"]
        if any(x in remaining_lower for x in neg_list):
            return False
        if ticket_type == "带气作业票":
            # 同行只要没有叉号就算落实
            return True
        if any(x in remaining_upper for x in ["✓", "√", "v", "7", "1", "j", "已落实", "是"]):
            return True

        # 3. 兼容原有逻辑：向下寻找 3 行以内的数据，提取打勾/打叉/写有状态字样的勾选框行
        for offset in range(1, 4):  # 检索偏移量从 1 到 3
            if best_idx + offset < len(lines):  # 确保行号不超出 lines 数组范围
                next_line = lines[best_idx + offset]  # 获取向下偏移后的具体行内容
                # 如果这一行本身就是另外一条安全措施的主体，说明上一个措施没有独立的符号行，直接退出
                is_another_measure = False  # 初始化阶段标志
                for d_id, d_text in std_list:  # 遍历所有的防范措施
                    if d_text == desc:  # 排除自身
                        continue  # 换过自身
                    d_norm = re.sub(r"[^\w\u4e00-\u9fa5]", "", d_text)[:6]  # 归一化另外措施的前六个汉字
                    if d_norm in re.sub(r"[^\w\u4e00-\u9fa5]", "", next_line):  # 检查另外措施是否包含在这行内
                        is_another_measure = True  # 判定为触碰到下一措施的主体行
                        break  # 跳出遍历
                if is_another_measure:  # 判断如果为下一措施的主体
                    break  # 终止向下查找符号行的行为
                
                # 检查是否完全空白
                if re.sub(r"[\s—–\-]", "", next_line) == "":
                    return False  # 空白视为未落实
                
                neg_list = ["×", "x", "未填写", "空"] if ticket_type == "带气作业票" else ["×", "x", "未落实", "不适用", "/", "\\"]
                if any(x in next_line.lower() for x in neg_list):  # 匹配反向符号
                    return False  # 精准匹配成功，判定该防范项为“未落实 False”
                if ticket_type == "带气作业票":
                    # 对于带气抢修，向下查找行如果不含叉号就算落实
                    return True
                # 检查是否存在表示已落实的打勾、数字等正面肯定标志
                if any(x in next_line.upper() for x in ["✓", "√", "V", "7", "1", "J", "已落实", "是"]):  # 匹配正向符号
                    return True  # 判定该防范项为“已落实 True”
                    
        if ticket_type == "带气作业票":
            # 找到行但没匹配到任何叉号，判定为已落实 (True)
            return True
    return None  # 无匹配行或没有检测到任何符号时返回 None，交给 LLM 决定

class HandWrittenIssue(BaseModel):  # 定义表示 HSE 作业票中具体手写或自动判定的隐患项模型类
    """HSE 作业票中识别出的具体隐患项"""
    item_name: str = Field(..., description="隐患/检查项名称")  # 定义隐患检查项的中文标题字段
    status: str = Field(..., description="状态：'异常' 或 '正常'")  # 定义该项判定的安全状态状态字，异常或正常
    raw_text: Optional[str] = Field(None, description="OCR 原文备注")  # 可选的 OCR 识别出的现场手写意见原文备注


class SafetyMeasureItem(BaseModel):  # 定义安全防范措施条款单条执行状态的模型类
    """动火安全措施逐项落实状态"""
    measure_id: int = Field(..., description="措施序号")  # 法定安全措施条款对应的数字序号
    description: str = Field(..., description="措施内容原文")  # 安全防范条款的具体文字内容描述说明
    implemented: bool = Field(..., description="True=已落实, False=未落实")  # 是否成功落实并在票上打勾落实的布尔标记


class SecuritySheetData(BaseModel):  # 定义包含完整作业票所有要素的结构化数据主模型类
    """牡丹江中燃 HSE 作业票结构化数据"""
    ticket_type: str = Field(default="动火作业票", description="作业票类型，例如：动火作业票/带气作业票")  # 作业票类型分类字段
    ticket_id: str = Field(..., description="作业票编号")  # 作业票物理编号，如 MDJ2025xxxx
    station_name: str = Field(..., description="地点/场站")  # 作业现场场站或所属管理所名称
    content: str = Field(..., description="作业内容")  # 作业的具体施工内容
    work_time: str = Field(default="", description="作业时间")  # 作业执行的时段或时间范围
    worker_id: str = Field(..., description="作业人员姓名及证件号/证书编号")  # 作业班组人员证件工号
    check_date: str = Field(..., description="日期 YYYY-MM-DD")  # 表单签署并自检的年月日日期
    safety_measures: List[SafetyMeasureItem] = Field(default=[], description="安全措施落实状态")  # 包含所有法定措施项的落实列表
    has_abnormal: bool = Field(..., description="是否存在异常")  # 全票是否存在隐患或数值超标的全局判定状态
    issues: List[HandWrittenIssue] = Field(default=[], description="隐患项明细")  # 整理出的异常隐患详细分类列表
    completion_time: Optional[str] = Field(None, description="完工时间/完工验收时间")  # 作业票完工的物理签字时间
    approver_name: Optional[str] = Field(None, description="签批人/负责人姓名")  # 作业票终审的负责人姓名
    operators: Optional[str] = Field(None, description="作业人员")
    construction_leader: Optional[str] = Field(None, description="施工方现场负责人")
    supervisor: Optional[str] = Field(None, description="监理人员")
    company_monitor: Optional[str] = Field(None, description="项目公司监护人")
    gas_leader: Optional[str] = Field(None, description="带气现场负责人")
    approval_opinion: Optional[str] = Field(None, description="自动生成的审批建议")  # AI 智能建议意见文本
    risk_level: Optional[str] = Field(None, description="风险等级：重大/较大/一般/低风险")  # 智能体综合评估的风险级别
    approval_status: Optional[str] = Field(None, description="审批状态：自动通过/待审批/已驳回")  # 智能体流转的最终流转状态
    approval_level: Optional[str] = Field(None, description="审批路由级别：自动通过/主管审批/禁止作业")  # 审批路由所属层级


# ==========================================
# 2. LLM 大脑 (OpenAI 兼容 API)
# ==========================================

class LLMBrain:  # 定义大模型大脑处理类，负责远程 API 对话及启发式数据规整校验工作
    """通过 OpenAI 兼容协议调用线上大模型"""

    def __init__(self, api_key: str, base_url: str, model_name: str, proxy: str = ""):  # 构造器方法，配置密钥、接口地址、模型名及代理参数
        from openai import OpenAI  # 动态引入 OpenAI 客户端核心包
        import httpx  # 导入 httpx 异步库以定制带有代理参数的客户端
        kwargs = dict(api_key=api_key, base_url=base_url, timeout=120.0)  # 打包基础的 API 初始化键值参数
        if proxy:  # 检查是否要求使用代理服务器连接大模型 API 终点
            proxy_str = proxy.strip()
            if "://" not in proxy_str:
                proxy_str = f"http://{proxy_str}"
            kwargs["http_client"] = httpx.Client(proxy=proxy_str, timeout=120.0)  # 使用 httpx 自带代理构造同步客户端实例
        self.client = OpenAI(**kwargs)  # 实例化并缓存 OpenAI 协议客户端
        self.model_name = model_name  # 记录大模型名称，如 qwen-2.5

    def _sanitize_sheet_data(self, raw_dict: dict, ocr_text: str) -> dict:  # 使用规则引擎启发式地校验和兜底 LLM 返回的 JSON 字典数据，规避幻觉错误
        """用 Python + OCR 启发式规则兜底重构和校验 LLM 提取的结构化数据"""
        # 1. 确定作业票类型
        ticket_type = raw_dict.get("ticket_type", "动火作业票")  # 提取作业票类型，若缺省则默认为动火作业票
        if "带气" in ocr_text:  # 检查如果 OCR 文本字元中明显含有“带气”关键字
            ticket_type = "带气作业票"  # 强制纠偏为带气作业票
        elif "动火" in ocr_text:  # 检查如果含有“动火”关键字
            ticket_type = "动火作业票"  # 强制纠偏为动火作业票
        raw_dict["ticket_type"] = ticket_type  # 保存纠偏后的票类型结果

        # 2. 规范化票号 (ticket_id)
        ticket_id = raw_dict.get("ticket_id", "")  # 获取大模型提取出的票号字串
        if not ticket_id or str(ticket_id).lower() in ["null", "none", "未知", ""]:  # 判断大模型提取出的票号是否无效或未知
            found_id = None  # 初始化候选票号为空
            for line in ocr_text.split("\n"):  # 遍历 OCR 文字的每一行以正则查找特征票号
                m = re.search(r"(MDJZR\d+|MPJZR\d+|NDJZR\d+|\d+NDJZR\d+|MDJ\d+|MPJ\d+)", line, re.IGNORECASE)  # 使用特征前缀正则匹配票号
                if m:  # 若匹配成功
                    found_id = m.group(1)  # 提取捕获组得到的真实票号
                    break  # 停止遍历
            if found_id:  # 如果成功从 OCR 行中检索到了特异性票号
                ticket_id = found_id  # 赋值票号为该字串
            else:  # 若仍然缺失
                m_num = re.search(r"(?:编号|NO\.?|No\.?)[：:]?\s*([A-Za-z0-9]+)", ocr_text)  # 尝试在大范围中匹配 No 关键字后面的纯文本编号
                if m_num:  # 若匹配到
                    ticket_id = m_num.group(1)  # 提取出编号
        if ticket_id:  # 若票号字元非空
            ticket_id = re.sub(r"\s+", "", str(ticket_id))  # 使用正则剔除票号内部所有不小心的空白和换行符
        # 安全审计: 禁止造假兜底 —— 票号缺失则置空串，交由 _reflect 反思阶段复判拦截，不填假票号骗过校验
        raw_dict["ticket_id"] = ticket_id or ""  # 保存修正后票号，缺失留空由反思阶段触发重试

        # 3. 基础文本字段提取/清洗 (station_name, content, worker_id)
        # 安全审计: 禁止「未知场站/未知作业内容/未知作业人员」造假占位。OCR 抠不到则留空串，
        # 交由 _reflect 反思阶段与下游判定拦截，绝不编造内容蒙混过关。

        for field in ["station_name", "content", "work_time", "worker_id"]:  # 循环迭代这四项核心基础文本字段
            val = raw_dict.get(field, "")  # 尝试从 LLM 解析得出的字段值字典中获取该项的值
            if not val or str(val).lower() in ["null", "none", "未知", ""]:  # 判断是否属于缺失或被 LLM 写了未知的非有效内容
                if field == "station_name":  # 若场站地点字段缺失
                    m = re.search(r"(?:地点|场站|部位|单位)[：:]?\s*([^\n]+)", ocr_text)  # 从 OCR 中正则搜索地点场站关键字后面的行内容
                    val = m.group(1).strip() if m else ""  # 命中时取值，否则留空串，不填造假占位
                elif field == "content":  # 若施工作业内容字段缺失
                    m = re.search(r"(?:内容|作业内容|动火内容)[：:]?\s*([^\n]+)", ocr_text)  # 正则获取作业内容行
                    val = m.group(1).strip() if m else ""  # 命中时赋值，否则留空串，不填造假占位
                elif field == "work_time":  # 若作业时间字段缺失
                    m = re.search(r"(?:作业时间|施工时间|动火时间)[：:]?\s*([^\n]+)", ocr_text)  # 正则搜索作业时间行
                    val = m.group(1).strip() if m else ""  # 命中时取值，否则留空串，不填造假占位
                elif field == "worker_id":  # 若作业人或证书字段缺失
                    m = re.search(r"(?:作业人员|动火人|作业人|证书编号)[：:]?\s*([^\n]+)", ocr_text)  # 正则搜索作业人姓名
                    val = m.group(1).strip() if m else ""  # 命中包装，否则留空串，不填造假占位
            raw_dict[field] = str(val).strip()  # 将清洗后的文本强转为纯净的剥离空白后的字符串保存入字典

        # 4. 规范化日期 YYYY-MM-DD
        date_str = raw_dict.get("check_date", "")  # 提取日期字段
        clean_date = ""  # 初始化清洗后的日期字符串为置空
        # 尝试从输入提取
        if date_str:  # 判断 LLM 是否提取了日期字符串
            m = re.search(r"(\d{4})[-年.](\d{1,2})[-月.](\d{1,2})", str(date_str))  # 用正则匹配各种中日文字符串格式的日期形式
            if m:  # 若匹配成功
                y, m_val, d_val = m.groups()  # 解包捕获到的年、月、日数值
                clean_date = f"{y}-{int(m_val):02d}-{int(d_val):02d}"  # 强转并补零拼接为标准的 YYYY-MM-DD 国际日期格式
        # 若失败，尝试从 OCR 提取
        if not clean_date:  # 若第一轮没匹配到，则尝试在整个 OCR 文本里进行正则匹配
            m = re.search(r"(\d{4})[-年.](\d{1,2})[-月.](\d{1,2})", ocr_text)  # 使用年日月通用正则模式匹配
            if m:  # 匹配到
                y, m_val, d_val = m.groups()  # 解包年日月数据
                clean_date = f"{y}-{int(m_val):02d}-{int(d_val):02d}"  # 拼装为标准时间串
        # 安全审计: 禁止造假兜底 —— 日期缺失则置空串，交由 _reflect 与下游处理，不填默认假日期
        raw_dict["check_date"] = clean_date or ""  # 保存清洗后日期，缺失留空不作伪

        # 5. 气体检测浓度处理已移除

        # 6. 用 Python 规则全量重构并校验安全措施条款，阻断 LLM 的幻觉或刻意掩盖
        std_measures = STANDARD_MEASURES.get(ticket_type, [])  # 获取该票型对应国家标准措施配置列表
        llm_measures = {}  # 用字典暂存大模型提取所得的各条目落实状态
        for m in raw_dict.get("safety_measures", []):  # 遍历大模型返回的措施列表
            if isinstance(m, dict):  # 确保子元素是标准字典结构
                mid = m.get("measure_id")  # 获取对应的措施条目 ID 号
                impl = m.get("implemented")  # 获取其上标记的落实状态布尔值
                if mid is not None:  # ID 必须有效
                    try:  # 校验
                        llm_measures[int(mid)] = bool(impl)  # 存入字典映射关系中
                    except Exception:  # 防护
                        pass  # 跳过

        sanitized_measures = []  # 新建重组并校验后的防范措施大数组
        has_abnormal = False  # 初始化作业票总隐患状态标志为 False
        unimplemented_ids = []  # 新建待存未落实条款编号的临时列表

        for mid, desc in std_measures:  # 逐一遍历标准要求落实的每一条条款
            h_status = check_measure_status_in_ocr(ocr_text, desc, ticket_type)  # 调用 check_measure_status_in_ocr 算法在 OCR 原文深挖勾选框物理状态
            if h_status is True:  # 算法判定物理勾选为真已落实
                impl = True  # 设置状态为 True
            elif h_status is False:  # 算法判定物理状态为假未落实
                impl = False  # 设置状态为 False
            else:  # 若算法对这串文字在 OCR 中没有定位到或返回 None 悬而未决
                if ticket_type == "带气作业票":
                    # 带气作业票只要扫描不到叉号，默认为已落实
                    impl = True
                else:
                    # 安全审计: OCR 看不清且 LLM 也未明确标记时，一律判「未落实」(False)，
                    # 宁可误报隐患触发整改，绝不默认放过任一安全措施。注释掉旧的「默认 True」放权兜底。
                    if llm_measures.get(mid) is True:  # 仅当大模型明确标记「已落实」才采信 True
                        impl = True  # 采信大模型标记已落实
                    else:  # 其他全部情况（未标记 / 标记 False / OCR 丢失）
                        impl = False  # 安全审计: 默认未落实，触发隐患上报
            
            sanitized_measures.append({  # 将重组后的措施字典加入措施数组中
                "measure_id": mid,  # 措施条款编号
                "description": desc,  # 措施条款具体内容
                "implemented": impl  # 校验后的执行落实状态布尔值
            })  # 结束条目添加
            if not impl:  # 若该防范项为 False 未落实状态，说明现场存在安全隐患
                has_abnormal = True  # 触发将整张作业票的 has_abnormal 标记强制强制提升为 True
                unimplemented_ids.append(mid)  # 将当前有问题的条款 ID 号加入隐患列表

        raw_dict["safety_measures"] = sanitized_measures  # 将校验过的安全条款列表覆盖进大模型原始字典中

        # 7. 气体检测浓度异常判定已移除
        conc_abnormal = False

        # 8. 同步并整理隐患项 (issues) 数组列表
        existing_issues = []  # 初始化最终保留的问题隐患条目列表
        for issue in raw_dict.get("issues", []):  # 遍历大模型自主生成的隐患条目
            if isinstance(issue, dict):  # 确保结构为字典类型
                item_name = issue.get("item_name", "")  # 问题项中文名称
                status = issue.get("status", "")  # 问题项判定状态
                raw_t = issue.get("raw_text", "")  # 问题项的来源原文备注
                # 排除自动生成的措施（下面会通过 Python 重构统一写入规范名称）
                if "安全措施第" in item_name:  # 若含有这些特征关键字
                    continue  # 跳过不录入以防数据行重复
                existing_issues.append(issue)  # 加入最终问题容器

        for mid in unimplemented_ids:  # 将检测出的未落实条款以规范的 JSON 数据格式打包追加到问题列表中
            desc = next(d for m_id, d in std_measures if m_id == mid)  # 根据 ID 提取标准条款描述
            existing_issues.append({  # 打包加入列表
                "item_name": f"安全措施第{mid}项未落实",  # 精准定位的未落实说明
                "status": "异常",  # 标为异常状态
                "raw_text": desc  # 来源条款原文
            })  # 结束追加

        if existing_issues:  # 若发现当前至少收集到了一项隐患或异常
            has_abnormal = True  # 锁定整票隐患标记为 True

        raw_dict["has_abnormal"] = has_abnormal  # 更新 has_abnormal 标志
        raw_dict["issues"] = existing_issues  # 更新 issues 隐患列表

        # 补全完工时间、签批人、风险等级及其他签字负责人姓名
        raw_dict["completion_time"] = raw_dict.get("completion_time") or None  # 若无则设为 None
        
        # 优先使用指定坐标局部裁剪 OCR 提取签字人姓名
        approver = None
        try:
            approver = AgentTools.extract_filler_name(700, 170, 300, 170)
        except Exception as e:
            safe_print(f"[Sanitize] 提取签字人失败: {e}")
        
        # 若局部裁剪未识别到，则使用大模型从全文识别出的结果
        if not approver or str(approver).lower() in ["null", "none", "未知", ""]:
            approver = raw_dict.get("approver_name")
            
        raw_dict["approver_name"] = approver or None
        
        raw_dict["operators"] = raw_dict.get("operators") or None
        raw_dict["construction_leader"] = raw_dict.get("construction_leader") or None
        raw_dict["supervisor"] = raw_dict.get("supervisor") or None
        raw_dict["company_monitor"] = raw_dict.get("company_monitor") or None
        raw_dict["gas_leader"] = raw_dict.get("gas_leader") or None
        
        raw_dict["risk_level"] = raw_dict.get("risk_level") or None  # 若无则设为 None

        return raw_dict  # 返回整理后的新字典数据

    def extract_sheet_json(self, ocr_text: str) -> SecuritySheetData:  # 调用大模型执行核心 OCR 文字到作业票结构化数据的语义提取提取工作
        safe_print(f"[LLM Log] 调用 API [{self.model_name}] 进行语义分析...")  # 控制台打印系统 API 正在调用提示日志

        system_prompt = (  # 组织结构化大模型的 System 系统级提示词，强制规范提取的键名和返回值结构
            "你是牡丹江中燃 HSE 管理体系的专职安全审计专家。将经 OCR 识别后的文本，"
            "精准解析并提取为以下 JSON 结构：\n"
            "{\n"
            '  "ticket_type": "作业票类型，填“动火作业票”或“带气作业票”",\n'
            '  "ticket_id": "作业票编号（如 MDJZR2025011007 或 MDJZR2026004001）",\n'
            '  "station_name": "作业单位",\n'
            '  "content": "作业内容",\n'
            '  "work_time": "作业时间",\n'
            '  "worker_id": "作业人员姓名及证件号/证书编号",\n'
            '  "check_date": "日期 YYYY-MM-DD",\n'
            '  "operators": "作业人员姓名",\n'
            '  "construction_leader": "施工方现场负责人姓名",\n'
            '  "supervisor": "监理人员姓名",\n'
            '  "company_monitor": "项目公司监护人姓名",\n'
            '  "gas_leader": "带气现场负责人姓名"\n'
            "}\n"
            "直接输出 JSON 对象，不要添加任何 Markdown 标记或多余的解释。"
        )  # 结束提示词定义

        # (已按要求移除截断，让大模型读取完整文本，防止末尾追加的网格结果被切掉)

        safe_print(f"[LLM Log] 发送请求中，请等待...")  # 控制台打印请求请求发送状态
        response = self.client.chat.completions.create(  # 触发 OpenAI 协议调用模型完成接口
            model=self.model_name,  # 绑定模型具体别名
            messages=[  # 构建对话消息列表
                {"role": "system", "content": system_prompt},  # 写入系统身份词
                {"role": "user", "content": f"OCR 文本：\n{ocr_text}"},  # 写入用户文本内容，传递整理后的 OCR 字符串
            ],  # 结束消息列表
            response_format={"type": "json_object"},  # 强制要求 API 接口返回符合 JSON 协议的文本对象
            temperature=0.1,  # 温度设为低极值 0.1 保证内容可控性
            max_tokens=4000,  # 设定最大允许返回的 Token 数限制为 4000
            timeout=120,  # 设定客户端最大的网络超时响应时长为 120 秒
        )  # 结束接口调用

        raw_content = response.choices[0].message.content  # 提取模型应答得到的文本字串
        raw_content = clean_thinking(raw_content)  # 清洗掉大模型输出中多余的 think 标签及 markdown 后缀符号

        try:  # 开启反序列化捕获
            raw_dict = json.loads(raw_content)  # 尝试用系统 json 模块强转大模型返回的内容为 dict 词典对象
        except Exception as e:  # 若转换直接报错（大模型输出含有不规整前缀字符等）
            safe_print(f"[LLM Log] JSON 直接解析失败: {e}. 尝试用正则提取 JSON 结构...")  # 打印警告日志
            m = re.search(r"(\{.*\})", raw_content, re.DOTALL)  # 使用大范围匹配提取被大括号包含的完整 JSON 段
            if m:  # 若正则命中
                try:  # 开启二级转换尝试
                    raw_dict = json.loads(m.group(1))  # 转换大括号提取段
                except Exception:  # 若二级转换也失败
                    raise ValueError("LLM 返回的 JSON 结构非法，安全审计拒绝静默兜底为空字典通过")  # 安全审计: 禁止造假兜底，提取彻底失败即抛错拦截
            else:  # 若正则未命中
                raise ValueError("LLM 未返回可解析的 JSON 结构，安全审计拒绝静默兜底为空字典通过")  # 安全审计: 禁止造假兜底，提取彻底失败即抛错拦截

        sanitized = self._sanitize_sheet_data(raw_dict, ocr_text)  # 调用 _sanitize_sheet_data 使用 Python + OCR 规则进行全面的重构重构和校验
        return SecuritySheetData(**sanitized)  # 将校验规整后的字典转换为安全 Pydantic 模型 SecuritySheetData 并返回结果


# ==========================================
# 3. 工具集
# ==========================================

class AgentTools:
    """Agent 的执行工具：图像预处理、OCR、数据库、通知
    
    【开发备注】所有涉及 OCR 的新功能，必须使用 AgentTools._last_ocr_device 获取用户
    在侧边栏选择的推理设备（cpu/gpu），不得硬编码 device 值。参考 _ocr_crop_region 的写法。
    """

    @staticmethod
    def preprocess_image(image_path: str) -> str:
        """OpenCV 去阴影 + 自适应二值化"""
        import cv2
        import tempfile
        safe_print("[Tool] 图像预处理：CLAHE 去阴影 + 自适应二值化...")

        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"无法读取图片: {image_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        binary = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8
        )

        tmp = tempfile.NamedTemporaryFile(suffix="_cleaned.png", delete=False)
        cv2.imwrite(tmp.name, binary)
        return tmp.name

    @staticmethod
    def _vision_llm_ocr(image_path: str, brain) -> str:
        """视觉大模型直接读图识别表格，一步完成结构+文字+符号"""
        import base64

        # 限制图片大小（≤5MB），避免超大图片触发 token 超限或费用失控
        MAX_IMG_BYTES = 5 * 1024 * 1024
        img_size = os.path.getsize(image_path)
        if img_size > MAX_IMG_BYTES:
            safe_print(f"[Tool] Vision LLM: 图片过大 ({img_size // 1024}KB)，跳过压缩警告")

        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        prompt = (
            "请识别这张表格图片中的全部内容，输出 Markdown 表格格式。\n"
            "要求：\n"
            "1. 保留所有勾选符号（✓、×、√、X），准确填入对应单元格\n"
            "2. 合并单元格用 Markdown 标准语法表达，保持行列对齐\n"
            "3. 手写体文字标注（手写）\n"
            "4. 仅输出 Markdown，不要解释"
        )
        safe_print("[Tool] Vision LLM: 读图识别表格...")
        resp = brain.client.chat.completions.create(
            model=brain.model_name,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0.1,
            max_tokens=8192,
            timeout=120,
        )
        md = resp.choices[0].message.content.strip()
        safe_print(f"[Tool] Vision LLM done, {len(md)} chars.")
        return md

    @staticmethod
    def ocr_tool(image_path: str, mode: str = "cluster", brain=None, progress_callback=None, engine: str = "paddleocr", vision_brain=None, device: str = "gpu", ticket_type: str = None) -> str:  # 核心OCR引擎调用门面方法，支持切换本地 PaddleOCR 和 Vision LLM，device 控制推理硬件
        """调用 ocr 模块进行 OCR 识别，支持坐标聚类和自适应边框检测；可选视觉大模型"""
        AgentTools._last_image_path = image_path
        AgentTools._last_ocr_device = device  # 缓存当前推理设备选择，供 _ocr_crop_region 等静态方法复用。【注意】后续新增的 OCR 功能都应读取此变量，保持与侧边栏设置同步
        def _prog(pct, msg):  # 定义内部进度更新辅助回调
            if progress_callback:  # 如果主线程注册了进度通知函数
                progress_callback(pct, msg)  # 执行进度通知更新

        # 尝试进行模板对齐 (无论是 PaddleOCR 还是视觉大模型，优先对齐能确保裁剪坐标一致且读图质量更佳)
        template_dir = os.path.join(os.path.dirname(__file__), "template")
        # 过滤掉 aligned_result.png 和 match_debug.png 等调试输出文件，只使用真正的模板（如 dq.png, gc.png）
        templates = []
        if os.path.exists(template_dir):
            for f in os.listdir(template_dir):
                if f.lower().endswith(".png") and not f.startswith("aligned") and not f.startswith("match"):
                    if ticket_type == "带气作业票" and f != "dq.png":
                        continue
                    if ticket_type == "动火作业票" and f != "dh.png":
                        continue
                    templates.append(f)
        
        matched_template_type = None
        matched_template_type = None
        if templates:
            import subprocess
            import sys
            import cv2
            
            matched = False
            for t_file in templates:
                t_path = os.path.join(template_dir, t_file)
                _prog(12, f"匹配模板 {t_file} 中...")
                
                # 定义对齐后图像的目标保存路径
                aligned_dir = os.path.join(os.path.dirname(__file__), "uploads")
                os.makedirs(aligned_dir, exist_ok=True)
                aligned_path = os.path.join(aligned_dir, "aligned_" + os.path.basename(image_path))
                
                # 使用 subprocess 调用 align_to_template.py 脚本进行对齐
                cmd = [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "align_to_template.py"),
                    "--template", t_path,
                    "--input", image_path,
                    "--output", aligned_path
                ]
                
                try:
                    # 运行 align_to_template.py 并等待其完成
                    subprocess.run(cmd, capture_output=True, text=True, check=True)
                    
                    # 检查对齐图片是否生成成功并读取
                    if os.path.exists(aligned_path):
                        aligned_img = cv2.imread(aligned_path)
                        if aligned_img is not None:
                            # 坐标适配：为保证 codebase 原有 hardcoded 坐标（基于旧模板大小）能够完全对正，
                            # 我们需要将对齐至新模版尺寸后的图片，resize 回原代码所期待的规范尺度大小：
                            # - 带气票 (dq.png)：期待的旧尺寸为 1052x1487
                            # - 动火票 (dh.png)：期待的旧尺寸为 1000x1414
                            t_name = t_file.lower()
                            if "dq.png" in t_name:
                                aligned_img = cv2.resize(aligned_img, (1052, 1487))
                                cv2.imwrite(aligned_path, aligned_img)
                            elif "dh.png" in t_name:
                                aligned_img = cv2.resize(aligned_img, (1000, 1414))
                                cv2.imwrite(aligned_path, aligned_img)
                                
                            safe_print(f"[OCR] 模板匹配对齐完成：使用 {t_file} 模板")
                            image_path = aligned_path  # 覆盖后续全图 OCR 扫描 of 源图片路径
                            AgentTools._last_image_path = aligned_path  # 覆盖缓存路径，确保之后的裁剪操作也使用对齐图
                            matched = True
                            if t_file == "dq.png":
                                matched_template_type = "带气作业票"
                            elif t_file == "dh.png":
                                matched_template_type = "动火作业票"
                            break
                except Exception as e:
                    # 对齐失败，继续尝试下一个模板
                    safe_print(f"[OCR] 调用 align_to_template.py 失败或不匹配 {t_file}: {e}")
            
            if not matched:
                # 所有模板都无法匹配，可能是完全不同的图片
                raise RuntimeError("上传的照片无法匹配到任何已注册的作业票模板（如带气作业票），请确保照片拍摄端正且清晰无遮挡，并重新上传正确的照片！")

        # ---- 视觉大模型（无坐标） ----
        if engine == "vision":  # 如果用户指定使用视觉大模型引擎
            vb = vision_brain or brain  # 获取有效的视觉大模型实例
            if vb is None:  # 如果没有可用的模型实例
                raise RuntimeError("视觉大模型模式需要配置视觉模型 API")  # 抛出运行错误提示
            _prog(10, f"视觉大模型读图中 ({vb.model_name})...")  # 触发 10% 进度更新
            AgentTools._last_ocr_raw = ""  # 清空上一次的 OCR 缓存原文
            return AgentTools._vision_llm_ocr(image_path, vb)  # 调用 _vision_llm_ocr 读图并返回 markdown

        # ---- PaddleOCR（带坐标） ----
        from ocr import run_ocr  # 动态从独立 ocr 模块中导入核心 run_ocr 执行函数
        
        _prog(15, "启动 PaddleOCR 扫描")  # 触发 15% 进度更新
        
        sim_ocr = _ProgressSim(progress_callback, 15, 50, "OCR 文字识别中", 3, 0.6)  # 实例化后台进度模拟线程，在识别期间平滑推动进度条从 15% 到 50%
        sim_ocr.start()  # 开启模拟线程
        try:  # 开启 OCR 识别防护
            ocr_result = run_ocr(  # 调用独立 ocr 模块接口获取扫描结果
                image_path=image_path,  # 文件路径
                coords=None,  # 扫描全图
                mode=mode,  # 表格聚类模式
                device=device,  # 使用用户选择的推理设备（cpu/gpu）
                det_db_box_thresh=0.2,  # 强制调低文本检测阈值，防止细小的手写 √、× 被漏检
                drop_score=0.1  # 强制调低置信度过滤阈值，保留低置信度的手写符号
            )  # 结束调用
        finally:  # 无论识别成功失败
            sim_ocr.done()  # 必须停止进度模拟线程，直接跳进 50% 进度

        _prog(52, "表格格式化完成")  # 触发 52% 进度通知
        if not ocr_result:  # 如果返回的结果为空
            raise RuntimeError(f"OCR 未能识别任何文字: {image_path}")  # 抛出运行时错误

        # 从 ocr_result 中分离出 flat_text，用于更新 AgentTools._last_ocr_raw
        if "---" in ocr_result:  # 检查如果结果中包含隔离线
            parts = ocr_result.split("---", 1)  # 按第一条隔离线将表格 Markdown 与纯文本形式切开
            flat_text = parts[1].strip()  # 提取第二部分的纯文本 OCR 结果
        else:  # 若无隔离线
            flat_text = ocr_result  # 直接全部视作纯文本结果
        AgentTools._last_ocr_raw = flat_text  # 将提取的纯文本写入智能体临时 OCR 原文缓存中

        # 首次感知全图扫描分类检测：从识别文本中提取 3 种作业票类型并标出绝对坐标打印在日志窗口
        import re  # 导入正则表达式模块
        
        ocr_type = None
        ocr_coords = None
        for line in flat_text.split("\n"):  # 遍历扁平 OCR 文本的每一行
            line_str = line.strip()  # 去除首尾空格
            m = re.match(r"(.+?)\s+\[(\d+),(\d+),(\d+),(\d+)\]", line_str)  # 正则匹配提取文本和坐标数值
            if m:
                text_part = m.group(1).strip()
                coords_val = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
                clean_txt = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text_part)  # 清洗文本，只保留中文、英文字母及数字
                
                if "动火作业票" in clean_txt:
                    ocr_type = "动火作业票"
                    ocr_coords = coords_val
                    break
                elif "带气作业票" in clean_txt:
                    ocr_type = "带气作业票"
                    ocr_coords = coords_val
                    break
                elif "临时用电作业票" in clean_txt or "用电作业票" in clean_txt:
                    ocr_type = "临时用电作业票"
                    ocr_coords = coords_val
                    break

        detected_type = ocr_type or matched_template_type  # 优先使用 OCR 文字识别的票型进行纠偏，避免模板误匹配
        
        if detected_type:  # 若成功匹配
            coords_str = f" | 坐标: x={ocr_coords[0]}, y={ocr_coords[1]}, w={ocr_coords[2]}, h={ocr_coords[3]}" if ocr_coords else ""
            safe_print(f"[OCR 检测] 首次扫描识别到作业票类型: 【{detected_type}】{coords_str}")  # 标出坐标输出到运行日志中

        # 纯本地 OpenCV 像素密度检测（仅带气作业票 + 对齐成功时触发）
        if detected_type == "带气作业票" and "aligned_" in os.path.basename(image_path):
            try:
                safe_print("[OpenCV Fallback] 启用外部 ocr5.py 进行像素三分类定位符号...")
                cmd = [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "ocr5.py"),
                    "--input", image_path
                ]
                # 执行并捕获输出，以 utf-8 编码读取以防中文乱码
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
                append_text = res.stdout.strip()
                if "--- 纯本地 OpenCV 像素密度提取结果 ---" in append_text:
                    flat_text = append_text + "\n" + flat_text
                    ocr_result = append_text + "\n" + ocr_result
                    AgentTools._last_ocr_raw = flat_text
                    safe_print("[OpenCV Fallback] 外部 ocr5.py 像素三分类结果前插融合完成！")
            except Exception as e:
                safe_print(f"[OpenCV Fallback] 外部降级识别 ocr5.py 运行异常: {e}")

        return ocr_result

    @staticmethod
    def _ocr_crop_region(image_path: str, x: int, y: int, w: int, h: int, save_crop_path: Optional[str] = None) -> str:
        """裁剪图片指定区域做 PaddleOCR，返回识别文本"""
        from ocr import run_ocr
        _device = getattr(AgentTools, "_last_ocr_device", "cpu")  # 读取用户选择的推理设备，默认 cpu
        try:
            ocr_result = run_ocr(
                image_path=image_path,
                coords=(x, y, w, h),
                save_crop_path=save_crop_path,
                mode="cluster",
                device=_device  # 使用与全图扫描相同的推理设备
            )
            if "---" in ocr_result:
                flat_text = ocr_result.split("---", 1)[1].strip()
            else:
                flat_text = ocr_result
            
            import re
            lines = []
            for line in flat_text.split("\n"):
                m = re.match(r"(.+?)\s+\[\d+,\d+,\d+,\d+\]", line.strip())
                if m:
                    lines.append(m.group(1).strip())
                else:
                    lines.append(line.strip())
            return " ".join(lines)
        except Exception:
            return ""




    @staticmethod
    def check_weather_tool(city: str = "牡丹江") -> dict:
        """查询实时天气，判断是否符合作业条件"""
        import requests
        safe_print(f"[Tool] 查询 {city} 实时天气...")
        try:
            resp = requests.get(f"https://wttr.in/{city}?format=j1", timeout=10)
            data = resp.json()
            current = data["current_condition"][0]

            temp_c = int(current.get("temp_C", 0))
            wind_kmph = int(current.get("windspeedKmph", 0))
            wind_level = wind_kmph // 6  # 大致换算为风级
            humidity = int(current.get("humidity", 0))
            desc = current.get("lang_zh", [{}])[0].get("value", current.get("weatherDesc", [{}])[0].get("value", ""))
            weather_code = int(current.get("weather_code", 0))

            # 判断是否符合动火条件
            issues = []
            if temp_c <= -5:
                issues.append(f"气温{temp_c}℃(≤-5℃)，低温警告，需加强防冻防滑措施")
            if wind_level >= 5:
                issues.append(f"风力{wind_level}级(≥5级)，禁止露天动火")
            if weather_code in [386, 389, 392, 395, 200]:  # 雷雨/暴雨
                issues.append(f"天气{desc}，禁止动火作业")
            if temp_c >= 40:
                issues.append(f"气温{temp_c}℃(≥40℃)，需加强防暑")
            if wind_level >= 4:
                issues.append(f"风力{wind_level}级(4级)，需加强防火措施")

            ok = len(issues) == 0
            result = {
                "city": city, "temp_c": temp_c, "wind_level": wind_level,
                "humidity": humidity, "weather": desc, "ok": ok, "issues": issues,
            }
            if ok:
                safe_print(f"[Tool] 天气正常: {desc} {temp_c}℃ 风{wind_level}级")
            else:
                safe_print(f"[Tool] 天气异常: {'; '.join(issues)}")
            return result
        except Exception as e:
            safe_print(f"[Tool] 天气查询失败: {e}, 跳过天气检查")
            return {"city": city, "ok": True, "issues": [], "error": str(e)}

    @staticmethod
    def save_to_db(data: SecuritySheetData, raw_ocr: str = "", image_path: str = "") -> bool:
        """写入 SQLite，自动迁移旧表"""
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
        safe_print(f"[Tool] 写入 SQLite: {db_path}")

        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hse_fire_work_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL, station_name TEXT NOT NULL,
                content TEXT NOT NULL, work_time TEXT, worker_id TEXT NOT NULL,
                check_date TEXT NOT NULL, gas_concentration_json TEXT,
                safety_measures_json TEXT, has_abnormal INTEGER NOT NULL,
                issues_json TEXT, completion_time TEXT, approver_name TEXT,
                approval_opinion TEXT, risk_level TEXT, raw_ocr_text TEXT,
                image_path TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 自动迁移：给旧表补列
        existing = {row[1] for row in conn.execute("PRAGMA table_info(hse_fire_work_tickets)").fetchall()}
        for col, typ in [("approval_opinion", "TEXT"), ("risk_level", "TEXT"), ("image_path", "TEXT"),
                         ("approval_status", "TEXT"), ("approval_level", "TEXT"), ("work_time", "TEXT")]:
            if col not in existing:
                conn.execute(f"ALTER TABLE hse_fire_work_tickets ADD COLUMN {col} {typ}")
                safe_print(f"[Tool] 旧表迁移：新增列 {col}")

        conn.execute(
            "INSERT INTO hse_fire_work_tickets "
            "(ticket_id,station_name,content,work_time,worker_id,check_date,"
            "gas_concentration_json,safety_measures_json,has_abnormal,"
            "issues_json,completion_time,approver_name,approval_opinion,risk_level,"
            "approval_status,approval_level,raw_ocr_text,image_path) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.ticket_id, data.station_name, data.content, data.work_time, data.worker_id,
             data.check_date, json.dumps([], ensure_ascii=False),
             json.dumps([m.model_dump() for m in data.safety_measures], ensure_ascii=False),
             int(data.has_abnormal),
             json.dumps([i.model_dump() for i in data.issues], ensure_ascii=False),
             data.completion_time, data.approver_name, data.approval_opinion,
             data.risk_level, data.approval_status, data.approval_level,
             raw_ocr, image_path),
        )
        conn.commit()
        conn.close()
        safe_print(f"[Tool] 作业票 {data.ticket_id} 已存入数据库。")
        return True

    @staticmethod
    def _dingtalk_field_cache_path() -> str:
        return os.path.join(os.path.dirname(__file__), ".dingtalk_cache.json")

    @staticmethod
    def _load_dingtalk_cache() -> list:
        """加载缓存，兼容旧版 dict 格式 → 转为 list"""
        path = AgentTools._dingtalk_field_cache_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and data.get("base_id"):
                return [data]  # 旧版单 base
        return []

    @staticmethod
    def _save_dingtalk_cache(cache: dict):
        path = AgentTools._dingtalk_field_cache_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _run_async(coro):
        """同步桥接：在新线程中启动独立事件循环运行异步协程。避免与 Streamlit tornado 事件循环冲突。"""
        import concurrent.futures

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_runner)
            return future.result(timeout=30)

    @staticmethod
    def _ping_dingtalk_mcp(mcp_url: str) -> bool:
        """验证 MCP 地址是否可达"""
        import httpx
        try:
            # MCP Streamable HTTP 端点通常接受 GET
            resp = httpx.get(mcp_url, timeout=10)
            return resp.status_code < 500
        except Exception:
            return False

    @staticmethod
    def _discover_dingtalk_fields(mcp_url: str) -> list:
        """
        首次连接时自动发现所有 base / table / field 映射，写入本地缓存。
        返回 [{"base_id": "...", "table_id": "...", "fields": {...}}, ...]
        """
        safe_print("[Tool] 首次接入钉钉 AI 表格，正在自动发现表格结构...")

        def _safe_get(response, key: str, default=None):
            if not isinstance(response, dict):
                return default
            if key in response:
                return response[key]
            data = response.get("data")
            if isinstance(data, dict) and key in data:
                return data[key]
            return default

        async def _discover():
            from dingtalk_client import DingTalkAITableClient
            async with DingTalkAITableClient(mcp_url) as client:
                bases = await client.list_bases(limit=50)
                base_list = _safe_get(bases, "bases", [])
                if not base_list:
                    raise RuntimeError("未找到任何钉钉多维表 Base")

                results = []
                for b in base_list:
                    base_id = b.get("baseId") or b.get("id", "")
                    if not base_id:
                        continue
                    base_name = b.get("baseName", b.get("name", base_id))
                    # 查找含有 test_demo 或 test_demo_base 的 base
                    # 同时兼容 base_name 包含 "test_demo" 的
                    if "test_demo" not in base_name.lower():
                        continue

                    base_info = await client.get_base(base_id)
                    tables = _safe_get(base_info, "tables", [])
                    for t in tables:
                        tn = t.get("tableName", t.get("name", ""))
                        # 匹配表名：test_demo 或 数据表（在 test_demo_base 系列中）
                        if tn not in ("test_demo", "数据表"):
                            continue
                        table_id = t.get("tableId") or t.get("id", "")
                        if not table_id:
                            continue

                        table_detail = await client.get_tables(base_id, [table_id])
                        tbl_list = _safe_get(table_detail, "tables", [])
                        field_map = {}
                        for tbl in tbl_list:
                            if (tbl.get("tableId") or tbl.get("id")) == table_id:
                                for f in tbl.get("fields", []):
                                    fname = f.get("fieldName", f.get("name", ""))
                                    fid = f.get("fieldId") or f.get("id", "")
                                    if fname and fid:
                                        field_map[fname] = fid
                        if field_map:
                            # 至少有"编号"字段才算有效表
                            has_key_fields = any("编号" in k for k in field_map)
                            if not has_key_fields:
                                safe_print(f"[Tool]   {base_name}/{tn}: 缺少编号字段，跳过")
                                continue
                            results.append({
                                "base_id": base_id,
                                "base_name": base_name,
                                "table_id": table_id,
                                "table_name": tn,
                                "fields": field_map,
                            })
                            safe_print(f"[Tool]   {base_name}/{tn}: {field_map}")

                if not results:
                    raise RuntimeError("未找到 test_demo 相关表")
                return results

        result = AgentTools._run_async(_discover())
        AgentTools._save_dingtalk_cache(result)
        return result

    @staticmethod
    def write_dingtalk_table(ticket_id: str, image_path: str, description: str, person_name: str, risk_level: str = "") -> bool:
        """写入钉钉 AI 表格 test_demo 表（全自动，无需手动点击）
        ticket_id → 编号, image_path → 图片附件, description → 问题描述, person_name → 责任人, risk_level → 等级
        当等级不是"低风险"时，同时写入 base2（如果有）。
        """
        cfg = load_config()
        mcp_url = cfg.get("dingtalk_mcp_url", "")
        if not mcp_url:
            safe_print("[Tool] ⚠️⚠️⚠️ 钉钉 MCP 未配置，写入失败！")
            return False

        safe_print("[Tool] 📊 自动写入钉钉 AI 表格...")

        # 获取字段映射（缓存是 list）
        caches = AgentTools._load_dingtalk_cache()
        if not caches:
            try:
                caches = AgentTools._discover_dingtalk_fields(mcp_url)
            except Exception as e:
                safe_print(f"[Tool] 钉钉 AI 表格发现失败: {e}")
                return False

        if not caches:
            safe_print("[Tool] 钉钉 AI 表格缓存不完整。")
            return False

        # 决定写入哪些 base：base1 始终写，base2 仅在 level ≠ 低风险时写
        is_high_risk = (risk_level and risk_level != "低风险")
        if is_high_risk:
            safe_print(f"[Tool]   等级={risk_level} ≠ 低风险 → 双写 base1 + base2")

        async def _write_one(base_id, table_id, fields):
            cells = {}
            fid_attachment = None
            for fname, fid in fields.items():
                if "编号" in fname:
                    cells[fid] = ticket_id
                elif "图片" in fname or "附件" in fname:
                    fid_attachment = fid
                elif "问题描述" in fname or ("描述" in fname and "图片" not in fname):
                    cells[fid] = description
                elif "责任人" in fname:
                    cells[fid] = person_name
                elif "等级" in fname:
                    cells[fid] = risk_level

            if not cells:
                safe_print("[Tool]   未匹配到任何目标字段")
                return False

            from dingtalk_client import DingTalkAITableClient
            async with DingTalkAITableClient(mcp_url) as client:
                if fid_attachment and image_path and os.path.exists(image_path):
                    file_name = os.path.basename(image_path)
                    file_size = os.path.getsize(image_path)
                    ext = os.path.splitext(file_name)[1].lower()
                    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                                ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
                                ".pdf": "application/pdf", ".txt": "text/plain"}
                    mime_type = mime_map.get(ext, "image/jpeg")
                    upload_info = await client.prepare_attachment_upload(
                        base_id, table_id, file_name, file_size, mime_type=mime_type)
                    file_token = None
                    upload_url = None
                    if isinstance(upload_info, dict):
                        d = upload_info.get("data", {}) if "data" in upload_info else upload_info
                        file_token = d.get("fileToken") or upload_info.get("fileToken")
                        upload_url = d.get("uploadUrl") or upload_info.get("uploadUrl")
                    if file_token and upload_url:
                        import urllib.request
                        with open(image_path, "rb") as f:
                            file_bytes = f.read()
                        req = urllib.request.Request(upload_url, data=file_bytes, method="PUT")
                        req.add_header("Content-Type", mime_type)
                        try:
                            urllib.request.urlopen(req, timeout=30)
                            cells[fid_attachment] = [{"fileToken": file_token}]
                        except Exception:
                            pass
                    elif file_token:
                        cells[fid_attachment] = [{"fileToken": file_token}]

                resp = await client.create_records(base_id, table_id, [{"cells": cells}])
                return resp.get("status") == "success"

        success_count = 0
        for i, cache in enumerate(caches):
            base_id = cache.get("base_id", "")
            table_id = cache.get("table_id", "")
            fields = cache.get("fields", {})
            base_name = cache.get("base_name", f"base{i+1}")
            if not base_id or not table_id or not fields:
                continue
            # base2 仅在非低风险时写入
            if i > 0 and not is_high_risk:
                safe_print(f"[Tool]   等级=低风险，跳过 {base_name}")
                continue
            safe_print(f"[Tool]   写入 {base_name}/{cache.get('table_name', '?')}...")
            try:
                ok = AgentTools._run_async(_write_one(base_id, table_id, fields))
                if ok:
                    success_count += 1
                    safe_print(f"[Tool]   {base_name} ✅")
                else:
                    safe_print(f"[Tool]   {base_name} ❌")
            except Exception as e:
                safe_print(f"[Tool]   {base_name} ❌ {e}")

        safe_print(f"[Tool] 钉钉 AI 表格写入完成: {success_count}/{len(caches)}")
        return success_count > 0

    @staticmethod
    def extract_filler_name(tx: int, ty: int, tw: int, th: int) -> str:
        """根据指定坐标裁剪图片并运行 PaddleOCR 识别文本，提取责任人姓名"""
        image_path = getattr(AgentTools, "_last_image_path", "")
        if not image_path or not os.path.exists(image_path):
            safe_print(f"[Tool] extract_filler_name 失败: 图片路径无效或不存在: {image_path}")
            return ""  # 安全审计: 禁止「坐标识别图片未知」造假占位，留空由调用方判定
            
        # 自动生成 archives/YYYY-MM-DD 归档文件夹路径并将签字裁剪图进行物理保存
        date_dir = time.strftime("%Y-%m-%d")
        archive_dir = os.path.join(os.path.dirname(__file__), "archives", date_dir)
        os.makedirs(archive_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        crop_path = os.path.join(archive_dir, f"signature_{ts}_{tx}_{ty}.png")
        
        safe_print(f"[Tool] extract_filler_name 触发局部裁剪 OCR: x={tx}, y={ty}, w={tw}, h={th}，保存裁剪图至: {crop_path}")
        crop_text = AgentTools._ocr_crop_region(image_path, tx, ty, tw, th, save_crop_path=crop_path)
        
        if crop_text:
            _LABEL_KW = ("责任", "填表", "编号", "票号", "日期", "场站", "部位", "作业",
                         "动火", "检测", "采样", "确认", "签批", "盖章", "部门", "时间",
                         "地点", "内容", "方式", "单位", "人员", "完工", "验收")
            clean_text = crop_text
            for kw in _LABEL_KW:
                clean_text = clean_text.replace(kw, "")
            name_m = re.search(r"([一-龥]{2,4})", clean_text)
            if name_m:
                return name_m.group(1)
            return clean_text.strip()
        return ""  # 安全审计: 禁止「未知」造假占位，OCR 识别不到人名则留空串


# ==========================================
# 4. Agent 记忆系统
# ==========================================

class AgentMemory:
    def __init__(self):
        self.steps: List[Dict[str, Any]] = []

    def remember(self, step: str, emoji: str, action: str, result: str, status: str = "done"):
        self.steps.append({"step": step, "emoji": emoji, "action": action, "result": result, "status": status})

    def get_summary(self) -> str:
        return "\n".join(f"{s['emoji']} [{s['step']}] {s['action']} -> {s['result']}" for s in self.steps)


# ==========================================
# 5. Agent ReAct 编排器
# ==========================================

class _ProgressSim:
    """阻塞操作期间的模拟渐进进度（后台线程）"""
    def __init__(self, callback, start_pct, end_pct, msg, step=1, interval=0.5):
        self._cb = callback
        self._start = start_pct
        self._end = end_pct
        self._step = step
        self._interval = interval
        self._msg = msg
        self._lock = __import__('threading').Lock()
        self._stop_event = __import__('threading').Event()
        self._cur = float(start_pct)
        import threading as _th
        self._t = _th.Thread(target=self._run, daemon=True)

    def _run(self):
        import time as _t
        t0 = _t.time()
        next_hb = HEARTBEAT_INTERVAL
        while not self._stop_event.is_set() and self._cur < self._end - 1:
            with self._lock:
                self._cur = min(self._cur + self._step, self._end - 1)
                cur = self._cur
            # 不在后台线程调用 Streamlit 回调，避免 ScriptRunContext 警告；
            # 主线程 _p() 调用已提供实时进度，done() 在主线程触发最终更新。
            if HEARTBEAT_INTERVAL > 0:
                elapsed = _t.time() - t0
                if elapsed >= next_hb:
                    safe_print(f"  ... {self._msg} ({int(elapsed)}s)")
                    next_hb += HEARTBEAT_INTERVAL
            _t.sleep(self._interval)

    def start(self):
        self._t.start()

    def done(self):
        self._stop_event.set()
        with self._lock:
            self._cur = float(self._end)
        if self._cb:
            self._cb(int(self._end), self._msg)


class _Heartbeat:
    """后台线程定期打印进度点，避免长时间推理时看起来像卡死"""
    def __init__(self, label: str, interval: float = None):
        self._label = label
        self._interval = interval if interval is not None else HEARTBEAT_INTERVAL
        self._stop_event = __import__('threading').Event()
        import threading as _th
        self._t = _th.Thread(target=self._run, daemon=True)

    def _run(self):
        import time as _t
        t0 = _t.time()
        while not self._stop_event.is_set():
            self._stop_event.wait(self._interval)
            if self._stop_event.is_set():
                break
            safe_print(f"  ... {self._label} ({int(_t.time() - t0)}s)", flush=True)

    def start(self):
        self._t.start()

    def stop(self):
        self._stop_event.set()


class SecurityAgent:  # 定义安全智能体核心编排类，实现完整的 ReAct 运行循环（Plan感知、Perceive提取、Reason推理、Reflect反思、Act决策上报、Report归档）
    """
    ReAct 智能体：Plan -> Perceive -> Reason -> Reflect -> Act -> Report
    """

    MAX_REFLECT_RETRIES = 2  # 校验失败时，大模型最大反思重试修正次数设为 2 次

    def __init__(self, brain: LLMBrain, ocr_mode: str = "cluster", ocr_engine: str = "paddleocr", ocr_device: str = "cpu", progress_callback=None, vision_brain: LLMBrain = None):  # 编排器构造函数，注入大脑实例、配置参数、推理设备及进度回调函数
        self.brain = brain  # 绑定大模型推理大脑
        self.tools = AgentTools()  # 实例化本智能体持有的执行工具集类
        self.ocr_mode = ocr_mode  # 配置表格 OCR 识别模式
        self.ocr_engine = ocr_engine  # 绑定物理 OCR 识别引擎（PaddleOCR 或 Vision）
        self.ocr_device = ocr_device  # 绑定推理硬件设备类型（cpu 或 gpu）
        self._progress = progress_callback  # 绑定主线程前端进度显示回调
        self.vision_brain = vision_brain  # 绑定多模态视觉大模型大脑

    def _plan(self, image_path: str, mem: AgentMemory):  # 规划阶段：为新图片生成 ReAct 推理步骤计划并存入记忆体
        safe_print("[Agent Plan] 收到作业票照片，制定执行计划...")  # 控制台打印规划阶段日志
        steps = [  # 5 个标准步骤定义
            "① 感知：OpenCV 清洗 + PaddleOCR 提取",  # 第一步
            "② 推理：LLM 结构化为 JSON",  # 第二步
            "③ 反思：校验数据完整性",  # 第三步
            "④ 执行：自主选择工具",  # 第四步
            "⑤ 总结：输出决策链报告",  # 第五步
        ]  # 结束步骤列表
        for s in steps:  # 遍历步骤
            safe_print(f"[Agent Plan] {s}")  # 打印计划详情
        mem.remember("规划", "📋", "制定5步执行计划", f"{len(steps)}步：感知→推理→反思→执行→总结")  # 将计划写入记忆步骤中

    def _perceive(self, image_path: str, mem: AgentMemory, ticket_type: str = None) -> str:  # 感知阶段：触发 OpenCV 对比度增强和 PaddleOCR 文字扫描工作
        prog = self._progress  # 获取进度条回调函数
        if prog: prog(5, "图像预处理")  # 前端更新进度为 5%
        safe_print("[Agent Perceive] OpenCV + PaddleOCR 感知...")  # 打印感知阶段日志
        text = self.tools.ocr_tool(image_path, mode=self.ocr_mode, brain=self.brain, progress_callback=prog, engine=self.ocr_engine, vision_brain=self.vision_brain, device=self.ocr_device, ticket_type=ticket_type)  # 调用 ocr_tool 接口识别图片，传入推理设备
        n = len(text.strip().split("\n"))  # 计算识别出的文本总行数
        summary = f"提取 {n} 行文本"  # 汇总感知报告
        safe_print(f"[Agent Perceive] {summary}")  # 打印行数汇总日志
        mem.remember("感知", "👁️", "OCR 提取文字", summary)  # 将感知提取阶段写入记忆体
        return text  # 返回提取出的文字

    def _reason(self, ocr_text: str, mem: AgentMemory) -> SecuritySheetData:  # 推理阶段：调用大模型进行实体识别和关系分类，填充为 Pydantic 字典
        safe_print("[Agent Reason] LLM 语义分析...")  # 打印推理阶段日志
        sim = _ProgressSim(self._progress, 55, 80, "LLM 语义分析中", 2, 1.0)  # 实例化推理进度模拟器线程，进度从 55% 到 80%
        sim.start()  # 开启平滑更新进度线程
        try:  # 安全审计: 提取彻底失败不再静默造假，捕获并转成明确的高风险失败体交由反思/执行拦截
            data = self.brain.extract_sheet_json(ocr_text)  # 调用大模型执行 JSON 语义结构化提取
        except Exception as e:  # LLM 返回无法解析或网络异常
            safe_print(f"[Agent Reason] LLM 提取失败，标记高风险拦截: {e}")  # 打印失败原因，不造假兜底
            mem.remember("推理", "⚠️", "LLM 提取失败", f"高风险拦截: {e}", status="error")  # 记忆体记录提取失败
            sim.done()  # 停止模拟线程
            data = SecuritySheetData(  # 构造明确的高风险失败体，has_abnormal=True 强制走暂缓/拦截分支
                ticket_type="动火作业票",  # 安全审计: 失败回退默认票型仅为构造合法对象，不影响审批结果(已标异常)
                ticket_id="LLM提取失败",  # 占位票号，标记异常来源
                station_name="", content="", work_time="", worker_id="",  # 关键字段一律留空，绝不编造
                check_date="",  # 日期留空
                safety_measures=[], has_abnormal=True,  # 强制异常，触发下游暂缓
                issues=[{"item_name": "LLM 结构化提取失败", "status": "异常", "raw_text": str(e)}],  # 隐患明细记录失败原因
            )
            return data  # 直接返回失败体，跳过后续正常路径
        sim.done()  # 停止模拟线程，进度直接推进到 80%
        summary = (f"票号={data.ticket_id} | 场站={data.station_name} | "  # 汇总推理核心要素
                   f"措施={len(data.safety_measures)}项 | "  # 条款数
                   f"异常={data.has_abnormal}")  # 隐患状态
        safe_print(f"[Agent Reason] {summary}")  # 终端打印推理概要日志
        mem.remember("推理", "🤔", "LLM 结构化解析", summary)  # 将推理阶段记录进记忆体
        return data  # 返回 Pydantic 数据实例

    def _reflect(self, ocr_text: str, data: SecuritySheetData, mem: AgentMemory, image_path: str = "") -> SecuritySheetData:  # 反思阶段：核心自我修正。对模型抽取的要素进行多项逻辑一致性强校验，若不符则自动重试修改
        safe_print("[Agent Reflect] 校验数据完整性...")  # 打印反思阶段开始日志
        for attempt in range(1, self.MAX_REFLECT_RETRIES + 1):  # 开启反思纠错循环，最大重试 MAX_REFLECT_RETRIES 次
            checks = []  # 新建单轮校验结果收集列表，每个元素为 (检查项, 是否OK, 说明字串)

            # 定义防指令泄露与模板噪声数据清洗的局部辅助函数
            def clean_field(val: str, placeholders: list) -> str:
                if not val:
                    return ""
                val_str = str(val).strip()
                # 过滤重试指令泄露的提示语关键字
                leak_keywords = ["重新解析", "上次问题", "按规则", "重试", "数据完整性", "校验失败", "请严格", "数据完整性校验失败"]
                if any(k in val_str for k in leak_keywords):
                    return ""
                # 过滤模板占位符
                if any(p in val_str for p in placeholders):
                    return ""
                return val_str

            ticket_clean = clean_field(data.ticket_id, ["编号", "作业票", "年", "月", "日"])
            ticket_ok = bool(ticket_clean) and len(ticket_clean) >= 6
            checks.append(("票号", ticket_ok, f"{data.ticket_id} {'OK' if ticket_ok else '异常'}"))

            approver_clean = clean_field(data.approver_name, ["签字", "盖章", "负责人", "手写"])
            approver_ok = bool(approver_clean) and len(approver_clean.strip()) >= 2
            checks.append(("签字", approver_ok, f"{data.approver_name} {'OK' if approver_ok else '缺失'}"))

            worker_clean = clean_field(data.worker_id, ["姓名及证书", "证书编号", "证件号", "姓名及", "证书号", "手写", "填空"])
            worker_ok = bool(worker_clean) and len(worker_clean.strip()) >= 2
            checks.append(("作业人员", worker_ok, f"{data.worker_id} {'OK' if worker_ok else '缺失'}"))

            station_clean = clean_field(data.station_name, ["发起人签字确认", "签字确认", "作业单位", "盖章", "项目公司"])
            station_ok = bool(station_clean) and len(station_clean.strip()) >= 2
            checks.append(("作业单位", station_ok, f"{data.station_name} {'OK' if station_ok else '缺失'}"))

            # 浓度校验已移除

            unimpl = [m for m in data.safety_measures if not m.implemented]
            integrity_fail = not (ticket_ok and approver_ok and worker_ok and station_ok)
            should_have_abnormal = integrity_fail or bool(unimpl)

            # 规则3：has_abnormal 标记与实际是否存在异常的一致性校验
            abnormal_ok = (data.has_abnormal == should_have_abnormal)
            if not abnormal_ok:
                detail = f"实际{'有' if should_have_abnormal else '无'}缺失/未落实，但标记异常={data.has_abnormal}"
                checks.append(("异常一致", False, detail))
            else:
                if data.has_abnormal:
                    issues_ok = (len(data.issues) > 0) or integrity_fail
                    checks.append(("异常一致", issues_ok, f"异常={data.has_abnormal}, 明细={len(data.issues)}条 {'OK' if issues_ok else '缺失'}"))
                else:
                    checks.append(("异常一致", True, "无异常 一致"))

            # 规则4：安全条款本身落实状态校验
            measures_ok = (len(unimpl) == 0)
            checks.append(("安全措施", measures_ok, "全部落实 OK" if measures_ok else f"{len(unimpl)}项未落实"))

            # 只有数据完整性和异常一致性校验不通过才需要重试。安全措施未落实是业务层面的事实，不应触发解析重试。
            integrity_failed = [name for name, ok, _ in checks if not ok and name != "安全措施"]
            all_pass = (len(integrity_failed) == 0)
            
            for name, ok, detail in checks:  # 迭代校验项
                safe_print(f"[Agent Reflect]   {'OK' if ok else '!!'} {name}: {detail}")  # 控制台打印校验详情条目

            if all_pass:  # 如果所有逻辑校对全部通过，无任何一致性冲突
                safe_print("[Agent Reflect] 校验通过。")
                mem.remember("反思", "🔍", "校验数据完整性", f"{len(checks)}项全部通过")
                return data

            failed = integrity_failed  # 提取本次校验失败的规则项名称
            safe_print(f"[Agent Reflect] 未通过({', '.join(failed)})，第{attempt}次重试...")  # 打印失败警告日志及重试计数
            mem.remember("反思", "🔍", f"第{attempt}次重试", f"未通过: {', '.join(failed)}", status="retry")  # 记忆体记录重试事件
            hint = f"上次问题：{', '.join(failed)}。请严格按规则重新解析。"  # 组织引导大模型纠错的负反馈提示词
            data = self.brain.extract_sheet_json(f"[重试] {hint}\n\n原文:\n{ocr_text}")

        safe_print("[Agent Reflect] 达到最大重试，标记高风险。")
        mem.remember("反思", "🔍", "最大重试", "标记高风险", status="error")  # 记忆体记录异常归档
        
        # 将失败的校验项记录为异常隐患，防止空模版/无签字件自动通过
        failed_checks = [name for name, ok, _ in checks if not ok]
        if failed_checks:
            data.has_abnormal = True
            for name, ok, detail in checks:
                if not ok:
                    exists = any(f"数据完整性校验失败: {name}" in issue.item_name for issue in data.issues)
                    if not exists:
                        data.issues.append(HandWrittenIssue(
                            item_name=f"数据完整性校验失败: {name}",
                            status="异常",
                            raw_text=detail
                        ))
            safe_print("[Agent Reflect] 达到最大重试，已将失败的完整性校验项强行记入隐患明细。")
        return data  # 返回未完全修正的数据，留待 L3 条件路由决策拦截

    def _generate_approval(self, data: SecuritySheetData, weather: dict = None) -> str:
        """调用 LLM 生成专业审批建议，含天气和具体异常"""
        issues_desc = ""
        if data.has_abnormal:
            items = []
            for m in data.safety_measures:
                if not m.implemented:
                    items.append(f"第{m.measure_id}项「{m.description}」未落实")
            for issue in data.issues:
                items.append(f"{issue.item_name}（{issue.raw_text or '异常'}）")
            issues_desc = "\n".join(f"- {item}" for item in items[:10])

        weather_desc = ""
        if weather and not weather.get("ok"):
            weather_desc = "\n天气异常：" + "；".join(weather.get("issues", []))

        std_info = TICKET_STANDARDS.get(data.ticket_type, TICKET_STANDARDS["动火作业票"])
        std_name = std_info["standard_name"]
        std_desc = std_info["standard_desc"]
        clear_dist = std_info["clear_dist_desc"]

        prompt = (
            f"你是HSE安全审计专家，生成{data.ticket_type}审批建议。\n\n"
            "【标准依据】\n"
            f"- {std_name} {std_desc}\n"
            f"- 作业区域要求：{clear_dist}\n"
            "- 五级风及以上禁止露天作业，雷雨天气禁止作业\n\n"
            "【输出格式】\n"
            "无异常→【同意作业】+简要确认\n"
            "有异常→【暂缓作业】+逐项列出问题（简写）+风险等级\n"
            "字数100字以内\n\n"
            f"票号：{data.ticket_id} 场站：{data.station_name}\n"
            f"措施：{len(data.safety_measures)}项\n"
            f"异常：{data.has_abnormal}\n"
            f"{issues_desc}{weather_desc}"
        )

        try:
            safe_print("[Agent Act] 调用 LLM 生成审批建议...")
            response = self.brain.client.chat.completions.create(
                model=self.brain.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
                timeout=120,
            )
            raw_opinion = response.choices[0].message.content.strip()
            opinion = clean_thinking(raw_opinion)

            if data.has_abnormal:
                data.risk_level = self._assess_risk_level(data)
            else:
                data.risk_level = "低风险"

            return opinion
        except Exception as e:
            safe_print(f"[Agent Act] LLM 审批建议生成失败，使用模板: {e}")
            return self._generate_approval_template(data)

    def _assess_risk_level(self, data: SecuritySheetData) -> str:
        """根据异常严重程度评估风险等级"""
        score = 0
        unimpl = [m for m in data.safety_measures if not m.implemented]
        score += min(len(unimpl), 3)  # 每项未落实 +1，最多 +3
        
        # 统计除完整性校验之外的业务隐患
        biz_issues = [i for i in data.issues if "数据完整性校验失败" not in i.item_name]
        score += min(len(biz_issues), 2)
        
        # 针对完整性缺陷单独加分，确保无签字/空模版能被坚决拦截
        for issue in data.issues:
            if "数据完整性校验失败: 签字" in issue.item_name:
                score += 2  # 签字缺失严重，加 2 分
            elif "数据完整性校验失败: 票号" in issue.item_name:
                score += 2  # 票号缺失严重，加 2 分
            elif "数据完整性校验失败: 作业人员" in issue.item_name:
                score += 1  # 作业人缺失，加 1 分
            elif "数据完整性校验失败: 作业单位" in issue.item_name:
                score += 1  # 作业单位缺失，加 1 分

        if score >= 5:
            return "重大"
        elif score >= 3:
            return "较大"
        elif score >= 1:
            return "一般"
        return "低风险"

    def _generate_approval_template(self, data: SecuritySheetData) -> str:
        """LLM 失败时的 fallback 模板，列出具体异常"""
        std_info = TICKET_STANDARDS.get(data.ticket_type, TICKET_STANDARDS["动火作业票"])
        std_name = std_info["standard_name"]
        if not data.has_abnormal:
            return f"【同意作业】票号{data.ticket_id}，安全措施已落实。依据{std_name}批准。"
        items = []
        for m in data.safety_measures:
            if not m.implemented:
                items.append(f"第{m.measure_id}项未落实")
        for issue in data.issues:
            items.append(f"{issue.item_name}")
        detail = "；".join(items[:5]) if items else "存在异常"
        return f"【暂缓作业】{detail}。依据{std_name}，请整改后重新提交。"

    def _act(self, data: SecuritySheetData, ocr_text: str, mem: AgentMemory, image_path: str = ""):
        safe_print("[Agent Act] ⚡ 执行 L3 条件路由审批...")
        mem.remember("执行", "⚡", "L3 条件路由审批", "开始分级审核流程")

        # ---- ① 天气检查 ----
        safe_print("[Agent Act] ① 天气检查...")
        weather = self.tools.check_weather_tool("牡丹江")
        weather_ok = weather.get("ok", True)
        if weather_ok:
            safe_print("[Agent Act] ① 天气检查 → 正常")
            mem.remember("执行", "⛅", "天气检查", f"{weather.get('weather','未知')} {weather.get('temp_c','?')}℃ 风力{weather.get('wind_level','?')}级 → 正常")
        else:
            issues_str = "；".join(weather.get("issues", []))
            safe_print(f"[Agent Act] ① 天气检查 → 异常: {issues_str}")
            mem.remember("执行", "⛅", "天气检查", f"异常: {issues_str}", status="retry")

        # ---- ② 风险评估 ----
        safe_print("[Agent Act] ② 风险评估...")
        if data.has_abnormal:
            data.risk_level = self._assess_risk_level(data)
        else:
            data.risk_level = "低风险"
        unimpl_count = len([m for m in data.safety_measures if not m.implemented])
        safe_print(f"[Agent Act] ② 风险评估 → {data.risk_level} (未落实{unimpl_count}项, 隐患{len(data.issues)}条)")
        mem.remember("执行", "📊", "风险评估", f"{data.risk_level} | 未落实{unimpl_count}项 | 隐患{len(data.issues)}条")

        # ---- ③ L3 路由决策 ----
        safe_print("[Agent Act] ③ L3 路由决策...")
        weather_blocked = not weather_ok and any("禁止" in i for i in weather.get("issues", []))

        if data.risk_level == "低风险" and weather_ok:
            data.approval_level = "自动通过"
            data.approval_status = "自动通过"
            route_desc = "低风险 + 天气正常 → ✅ 自动通过"
        elif data.risk_level in ("较大", "重大") or weather_blocked:
            data.approval_level = "禁止作业"
            data.approval_status = "已驳回"
            reason = f"风险{data.risk_level}" if not weather_blocked else "天气禁止作业"
            route_desc = f"{reason} → 🚫 禁止作业，需安全负责人介入"
        else:
            data.approval_level = "主管审批"
            data.approval_status = "待审批"
            route_desc = f"风险{data.risk_level} → ⏳ 推送主管审批"
        safe_print(f"[Agent Act] ③ L3 路由决策 → {route_desc}")
        mem.remember("执行", "🔀", "L3 路由决策", route_desc)

        # ---- ④ 生成审批建议 ----
        safe_print("[Agent Act] ④ 生成审批建议...")
        data.approval_opinion = self._generate_approval(data, weather)
        safe_print(f"[Agent Act] ④ 审批建议: {data.approval_opinion[:80]}...")
        mem.remember("执行", "📝", "生成审批建议", data.approval_opinion[:60])

        # ---- ⑤ 数据入库 ----
        safe_print("[Agent Act] ⑤ 数据入库...")
        self.tools.save_to_db(data, raw_ocr=ocr_text, image_path=image_path)
        safe_print(f"[Agent Act] ⑤ 已存入 SQLite: {data.ticket_id}")
        mem.remember("执行", "💾", "数据入库", f"票号 {data.ticket_id} 已存入 SQLite")

        # ---- ⑥ 钉钉 AI 表格写入 ----
        safe_print("[Agent Act] ⑥ 钉钉 AI 表格...")
        cfg = load_config()
        # 不使用局部裁剪 OCR，直接使用识别到的发起人/负责人姓名
        filler = data.approver_name or "未知"
        if cfg.get("dingtalk_mcp_url"):
            # 问题描述：推送 stAlertContainer 的完整审批意见与核心要素内容
            ap_status = data.approval_status or "待审批"
            ic = "✅" if ap_status == "自动通过" else ("🚫" if ap_status == "已驳回" else "⏳")
            
            info_lines = [
                f"作业票编号：{data.ticket_id or ''} [ticket_id]",
                f"作业单位：{data.station_name or ''} [station_name]",
                f"作业内容：{data.content or ''} [content]",
                f"作业时间：{data.work_time or ''} [work_time]",
                f"作业人姓名及证书编号：{data.worker_id or ''} [worker_id]",
                f"发起人签字确认：{data.approver_name or ''} [approver_name]",
                f"作业人员：{data.operators or ''} [operators]",
                f"施工方现场负责人：{data.construction_leader or ''} [construction_leader]",
                f"监理人员：{data.supervisor or ''} [supervisor]",
                f"项目公司监护人：{data.company_monitor or ''} [company_monitor]",
                f"带气现场负责人：{data.gas_leader or ''} [gas_leader]"
            ]
            info_block = "\n\n".join(info_lines)
            description = f"{ic} {data.approval_opinion or ''}\n\n---\n\n{info_block}"
            
            self.tools.write_dingtalk_table(data.ticket_id, image_path, description, filler, data.risk_level or "")
            safe_print(f"[Agent Act] ⑥ 钉钉 AI 表格 → 已写入 (责任人:{filler})")
            notify_result = f"编号:{data.ticket_id} → 钉钉 AI 表格 责任人:{filler}"
        else:
            safe_print("=" * 56)
            safe_print("[Agent Act] ⚠️⚠️⚠️ 钉钉 MCP 未配置，写入失败！⚠️⚠️⚠️")
            safe_print("[Agent Act]   请在侧边栏「钉钉 MCP 地址」中配置后重试。")
            safe_print("=" * 56)
            notify_result = f"编号:{data.ticket_id} → ⚠️ 钉钉 MCP 未配置，未写入 AI 表格"
        safe_print(f"[Agent Act] ⑥ {notify_result}")
        mem.remember("执行", "📤", "钉钉 AI 表格", notify_result)

    def _report(self, mem: AgentMemory, data: SecuritySheetData = None):
        safe_print(f"[Agent Report] ===== 决策链报告 =====")
        safe_print(mem.get_summary())
        if data and data.approval_status:
            safe_print(f"[Agent Report] 🔖 最终审批: {data.approval_status} ({data.approval_level})")
        safe_print(f"[Agent Report] ===== {len(mem.steps)} 阶段完成 =====")
        mem.remember("总结", "📊", "输出决策链报告", f"{len(mem.steps)}阶段完成 | 审批: {data.approval_status if data else '-'}")

    def _archive(self, image_path: str, ocr_text: str, mem: AgentMemory) -> str:
        """数字 OCR 归档：将 OCR 原始结果保存为独立文件（文件名含票据单号）"""
        import shutil
        ts = time.strftime("%Y%m%d_%H%M%S")
        date_dir = time.strftime("%Y-%m-%d")
        archive_dir = os.path.join(os.path.dirname(__file__), "archives", date_dir)
        os.makedirs(archive_dir, exist_ok=True)

        # 从 OCR 原文中提取票据单号
        ticket_id = ""
        for line in ocr_text.split("\n"):
            m = re.search(r"(MDJZR\d+|MPJZR\d+|NDJZR\d+|\d+NDJZR\d+|MDJ\d+|MPJ\d+)", line, re.IGNORECASE)
            if m:
                ticket_id = m.group(1)
                break
        if not ticket_id:
            m = re.search(r"(?:编号|NO\.?|No\.?)[：:]?\s*([A-Za-z0-9]+)", ocr_text)
            if m:
                ticket_id = m.group(1)
        # 安全审计: 禁止「未知票号」造假兜底，缺票号则归档失败，不编造占位
        if not ticket_id:
            safe_print("[Agent Archive] 票号缺失，无法归档，跳过")
            return
        ticket_id = re.sub(r"\s+", "", ticket_id)  # 剔除票号内部空白
        # 安全审计: 禁止「未知票号」造假兜底，缺票号则归档失败，不编造占位

        prefix = f"{ticket_id}_{ts}"

        # 保存 OCR 原文
        ocr_path = os.path.join(archive_dir, f"{prefix}_ocr.txt")
        with open(ocr_path, "w", encoding="utf-8") as f:
            f.write(ocr_text)

        # 1. 保存最原始的上传图片副本
        img_ext = os.path.splitext(image_path)[1] or ".jpg"
        img_dest = os.path.join(archive_dir, f"{prefix}_原图{img_ext}")
        try:
            shutil.copy2(image_path, img_dest)
        except Exception as e:
            safe_print(f"[Agent Archive] ⚠️ 原始图复制失败: {e}")
            img_dest = ""

        # 2. 如果存在特征点匹配对齐后的处理图片，也保存一份对齐图副本供用户比对
        aligned_source = getattr(AgentTools, "_last_image_path", image_path)
        if aligned_source and aligned_source != image_path and os.path.exists(aligned_source):
            img_dest_aligned = os.path.join(archive_dir, f"{prefix}_对齐图{img_ext}")
            try:
                shutil.copy2(aligned_source, img_dest_aligned)
                safe_print(f"[Agent Archive] 成功归档对齐处理后的图片: {img_dest_aligned}")
            except Exception as e:
                safe_print(f"[Agent Archive] ⚠️ 对齐图复制失败: {e}")

        # 保存元数据
        meta = {
            "source_image": os.path.basename(image_path),
            "ocr_file": os.path.basename(ocr_path),
            "image_file": os.path.basename(img_dest) if img_dest else "",
            "ocr_engine": self.ocr_engine,
            "ocr_mode": self.ocr_mode,
            "ocr_device": self.ocr_device,
            "ocr_lines": len(ocr_text.strip().split("\n")),
            "archived_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        meta_path = os.path.join(archive_dir, f"{prefix}_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        archive_rel = os.path.relpath(archive_dir, os.path.dirname(__file__))
        summary = f"{archive_rel}/{prefix}_ocr.txt ({meta['ocr_lines']}行)"
        safe_print(f"[Agent Archive] 已归档: {summary}")
        mem.remember("归档", "📦", "数字 OCR 归档", summary)
        return ocr_path

    def run(self, image_path: str, ocr_mode: str = None, progress_callback=None, ticket_type: str = None):
        """运行完整 ReAct 循环，返回 (ocr_text, structured_data)"""
        if ocr_mode:
            self.ocr_mode = ocr_mode
        prog = progress_callback or self._progress
        mem = AgentMemory()
        t0 = time.time()

        if prog: prog(0, "开始处理")
        self._plan(image_path, mem)
        if prog: prog(3, "感知阶段")
        ocr_text = self._perceive(image_path, mem, ticket_type=ticket_type)
        if prog: prog(52, "OCR 归档")
        self._archive(image_path, ocr_text, mem)
        if prog: prog(55, "推理阶段")
        data = self._reason(ocr_text, mem)
        if prog: prog(80, "反思阶段")
        data = self._reflect(ocr_text, data, mem, image_path=image_path)
        if prog: prog(88, "执行阶段")
        self._act(data, ocr_text, mem, image_path=image_path)
        if prog: prog(96, "生成报告")

        elapsed = time.time() - t0
        safe_print(f"[Agent] 全流程耗时: {elapsed:.1f}s")
        self._report(mem, data)
        if prog: prog(100, "完成")
        return ocr_text, data


# ==========================================
# 入口
# ==========================================

def load_config() -> dict:
    """从 config.json 加载配置，若不存在或缺失字段，则返回本地 Ollama 默认值"""
    cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass

    # Set default values if not specified
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("ONLINE_API_KEY", "ollama")
    if not cfg.get("base_url"):
        cfg["base_url"] = os.environ.get("ONLINE_BASE_URL", "http://localhost:11434/v1")
    if not cfg.get("model_name"):
        cfg["model_name"] = os.environ.get("ONLINE_MODEL", "qwen3.5:0.8b")
    # dingtalk_mcp_url: no default — user must configure, or push fails

    return cfg


if __name__ == "__main__":
    cfg = load_config()
    brain = LLMBrain(
        api_key=cfg.get("api_key", os.environ.get("ONLINE_API_KEY", "")),
        base_url=cfg.get("base_url", os.environ.get("ONLINE_BASE_URL", "")),
        model_name=cfg.get("model_name", os.environ.get("ONLINE_MODEL", "")),
    )
    agent = SecurityAgent(brain=brain)
    ocr_text, result = agent.run("workspace/phone_captured_sheet.jpg")
    safe_print(f"\nOCR:\n{ocr_text}")
    safe_print(f"\nJSON:\n{result.model_dump_json(indent=2)}")
