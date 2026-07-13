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


def _decode_subprocess_bytes(data: bytes | None) -> str:
    """
    解码子进程 stdout/stderr。
    Windows 中文环境子进程常以 GBK/CP936 写中文，父进程若强制 UTF-8 会在 Web 日志里显示为 。
    优先 UTF-8，失败或大量替换符时回退 GBK。
    """
    if not data:
        return ""
    # 1) 纯 UTF-8
    try:
        text = data.decode("utf-8")
        if "\ufffd" not in text:
            return text
    except UnicodeDecodeError:
        text = None
    # 2) GBK / CP936（中文 Windows 控制台默认）
    for enc in ("gbk", "cp936", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # 3) 带替换的 UTF-8
    if text is not None:
        return text
    return data.decode("utf-8", errors="replace")


def run_python_script(cmd: list, **kwargs):
    """
    运行本仓库 Python 子脚本，强制 UTF-8 IO，并对输出做稳健解码。
    返回与 subprocess.CompletedProcess 兼容的对象（stdout/stderr 为 str）。
    """
    import subprocess

    env = kwargs.pop("env", None)
    if env is None:
        env = os.environ.copy()
    else:
        env = dict(env)
    # 让子进程 print 使用 UTF-8，避免管道上的 GBK 乱码
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    # 二进制捕获，自行解码（兼容未设 PYTHONUTF8 的旧环境）
    kwargs.pop("text", None)
    kwargs.pop("encoding", None)
    kwargs.pop("errors", None)
    proc = subprocess.run(cmd, capture_output=True, env=env, **kwargs)
    proc.stdout = _decode_subprocess_bytes(proc.stdout)
    proc.stderr = _decode_subprocess_bytes(proc.stderr)
    return proc


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


# 带气作业票 HSE 标准（本系统仅支持带气作业票，已移除动火作业票）
TICKET_STANDARDS = {
    "带气作业票": {
        "standard_name": "CJJ 51-2016",
        "standard_desc": "《城镇燃气设施运行、维护和抢修安全技术规程》",
        "clear_dist_desc": "作业区域与周边做到可靠的隔离，现场设置明显标志，夜间设置警示灯",
    }
}

# 带气作业票 25 条法定安全措施
STANDARD_MEASURES = {
    "带气作业票": [
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
    ]
}


# 带气作业票安全措施确认列（每项固定 5 格，图例：落实√ 未落实× 不适用\）
GAS_MEASURE_ROLES = ("作业人", "施工方现场负责人", "监理", "监护人", "带气现场负责人")
GAS_MEASURE_COUNT = 25
GAS_MARK_FILLED = frozenset({"check", "cross", "slash"})  # 合法已填：对号/叉号/斜杠
GAS_MARK_EMPTY = frozenset({"blank", "", "-"})
# 带气作业票表头「作业等级」：一级危险程度最高，二级次之（不作 重大/较大/一般/低风险 混用）
GAS_WORK_GRADES = ("一级", "二级")


def extract_gas_work_grade(ocr_text: str) -> str:
    """
    从带气作业票表头提取作业等级（一级/二级）。
    典型 OCR：《牡丹江中燃带气作业票》（作业等级：二级）
    一级危险程度最高。
    """
    if not ocr_text:
        return ""
    patterns = [
        r"作业等级\s*[：:]\s*([一二])\s*级",
        r"作业等级\s*[：:]\s*([12])\s*级",
        r"[（(]\s*作业等级\s*[：:]\s*([一二12])\s*级",
        r"作业等级\s*[：:]\s*(一级|二级)",
    ]
    for p in patterns:
        m = re.search(p, ocr_text)
        if not m:
            continue
        g = m.group(1).strip()
        if g in ("1", "一", "一级"):
            return "一级"
        if g in ("2", "二", "二级"):
            return "二级"
    return ""


def normalize_gas_work_grade(val) -> str:
    """归一作业等级为 一级/二级，无法识别则返回空串。"""
    if not val:
        return ""
    s = str(val).strip().replace(" ", "")
    if s in GAS_WORK_GRADES:
        return s
    if s in ("1", "1级", "一", "Ⅰ", "I", "level1", "Level1"):
        return "一级"
    if s in ("2", "2级", "二", "Ⅱ", "II", "level2", "Level2"):
        return "二级"
    if "一级" in s or s.startswith("一"):
        return "一级"
    if "二级" in s or s.startswith("二"):
        return "二级"
    return ""


def _normalize_gas_cell_mark(token: str) -> str:
    """将单元格内符号归一为 check / cross / slash / blank。"""
    if token is None:
        return "blank"
    t = str(token).strip().lower()
    t = re.sub(r"[\s　]", "", t)
    if not t or t in ("-", "—", "–", "空", "空白", "未填写", "none", "null"):
        return "blank"
    # 叉号（未落实）
    if any(x in t for x in ("×", "✗", "x", "叉", "未落实")):
        return "cross"
    # 斜杠（不适用）——须先于对号判断，避免 "\\" 被误伤
    if any(x in t for x in ("\\", "／", "不适用", "n/a", "na")):
        # 单独的 "/" 在 OCR 中也可能是斜杠；"✓" 不含 /
        if "✓" not in t and "√" not in t and "已落实" not in t:
            if "\\" in t or "／" in t or "不适用" in t or t in ("/", "\\", "／"):
                return "slash"
    if t in ("/", "\\", "／"):
        return "slash"
    # 对号（落实）
    if any(x in t for x in ("✓", "√", "✔", "对", "已落实", "v", "j")):
        return "check"
    # OCR 常把对勾识成 1、7 等（仍属可映射的明确符号）
    if t in ("1", "7", "y", "l"):
        return "check"
    # 【禁止兜底】无法映射到 √/×/\ 的残留字符 → 一律 blank（漏项），报错由完整性校验拦截，禁止当对号放过
    # 若现场出现新符号形态，应改识别规则，不要在此默认成 check。
    return "blank"


def parse_gas_measure_grid(ocr_text: str) -> Dict[int, List[str]]:
    """
    从 OCR（优先 ocr5 网格块）解析带气 25 项 × 5 列标记。
    返回 {measure_id: [mark, mark, mark, mark, mark]}，mark ∈ check|cross|slash|blank
    行格式示例：
      第1条: … | 作业人(✓) | 施工方现场负责人(x) | 监理(✓) | 监护人(\\) | 带气现场负责人(-)
    """
    result: Dict[int, List[str]] = {}
    if not ocr_text:
        return result

    # 优先截取 ocr5 结果块，避免正文噪声干扰
    block = ocr_text
    m_block = re.search(
        r"---\s*纯本地 OpenCV 像素密度提取结果\s*---\s*(.*?)\s*----------------------------------",
        ocr_text,
        re.S,
    )
    if m_block:
        block = m_block.group(1)

    # 第N条: desc | 角色(符号) | ...
    row_pat = re.compile(
        r"第\s*(\d{1,2})\s*条\s*[:：]?\s*(.*)$",
        re.M,
    )
    cell_pat = re.compile(
        r"(作业人|施工方现场负责人|监理|监护人|带气现场负责人)\s*[\(（]\s*([^\)）]*)\s*[\)）]"
    )

    for m in row_pat.finditer(block):
        try:
            mid = int(m.group(1))
        except ValueError:
            continue
        if mid < 1 or mid > GAS_MEASURE_COUNT:
            continue
        rest = m.group(2)
        cells = cell_pat.findall(rest)
        if not cells:
            continue
        # 按标准五列顺序对齐；同角色多次取首次
        by_role = {}
        for role, raw_mark in cells:
            if role not in by_role:
                by_role[role] = _normalize_gas_cell_mark(raw_mark)
        marks = [by_role.get(role, "blank") for role in GAS_MEASURE_ROLES]
        result[mid] = marks

    return result


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
                    if has_pos:
                        return True
                    # 【禁止兜底】带气须走 ocr5 25×5 网格；此处无法判定则返回 None，禁止「无叉号即落实」
                    return None

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

        neg_list = ["×", "x", "未填写", "空", "未落实", "不适用", "/", "\\"]
        if any(x in remaining_lower for x in neg_list):
            return False
        if any(x in remaining_upper for x in ["✓", "√", "v", "7", "1", "j", "已落实", "是"]):
            return True
        # 【禁止兜底】无法明确判定时返回 None，禁止默认 True

        # 3. 向下寻找 3 行以内的勾选符号（非带气主路径；带气以 ocr5 为准）
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
                
                neg_list = ["×", "x", "未填写", "空", "未落实", "不适用", "/", "\\"]
                if any(x in next_line.lower() for x in neg_list):  # 匹配反向符号
                    return False  # 精准匹配成功，判定该防范项为“未落实 False”
                # 检查是否存在表示已落实的打勾、数字等正面肯定标志
                if any(x in next_line.upper() for x in ["✓", "√", "V", "7", "1", "J", "已落实", "是"]):  # 匹配正向符号
                    return True  # 判定该防范项为“已落实 True”
                # 【禁止兜底】本行仍无法判定 → 继续找下一行，最终返回 None

    # 【禁止兜底】无匹配/无明确符号 → None（调用方必须记异常或留空，禁止默认落实）
    return None

class HandWrittenIssue(BaseModel):  # 定义表示 HSE 作业票中具体手写或自动判定的隐患项模型类
    """HSE 作业票中识别出的具体隐患项"""
    item_name: str = Field(..., description="隐患/检查项名称")  # 定义隐患检查项的中文标题字段
    status: str = Field(..., description="状态：'异常' 或 '正常'")  # 定义该项判定的安全状态状态字，异常或正常
    raw_text: Optional[str] = Field(None, description="OCR 原文备注")  # 可选的 OCR 识别出的现场手写意见原文备注


class SafetyMeasureItem(BaseModel):  # 定义安全防范措施条款单条执行状态的模型类
    """带气安全措施逐项落实状态"""
    measure_id: int = Field(..., description="措施序号")  # 法定安全措施条款对应的数字序号
    description: str = Field(..., description="措施内容原文")  # 安全防范条款的具体文字内容描述说明
    implemented: bool = Field(..., description="True=已落实, False=未落实")  # 是否成功落实并在票上打勾落实的布尔标记
    # 带气票：每项 5 列确认格标记 check=√ / cross=× / slash=\ / blank=空白漏项
    column_marks: List[str] = Field(default_factory=list, description="带气五列标记 check|cross|slash|blank")


class SecuritySheetData(BaseModel):  # 定义包含完整作业票所有要素的结构化数据主模型类
    """牡丹江中燃 HSE 带气作业票结构化数据"""
    ticket_type: str = Field(default="带气作业票", description="作业票类型（仅支持带气作业票）")
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
    # 带气作业票：表头「作业等级」一级/二级（一级危险最高）
    risk_level: Optional[str] = Field(None, description="作业等级：一级|二级")
    # 待审批/已驳回：人工介入 = 经 MCP 推送钉钉 AI 表格
    approval_status: Optional[str] = Field(None, description="审批状态：自动通过/待审批/已驳回")
    approval_level: Optional[str] = Field(None, description="审批路由：自动通过/钉钉人工介入/禁止作业")


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
        self._last_extract_prompt = ""  # 最近一次结构化提取发给 LLM 的完整提示词（供归档）
        self._extract_prompt_log = []  # 本轮推理/反思全部提取调用的提示词记录（含重试）
        # None=未知；True=支持 json_object；False=不支持（LM Studio 等）。进程内记忆，避免每次先 400 再降级双发
        self._json_object_supported = None

    def _extract_sign_columns(self, ocr_text: str) -> dict:
        """基于 OCR 坐标从签批区域精准提取5列签名姓名。

        规则：
        - 列头仅允许「整词」匹配（可带冒号），禁止 startswith，避免
          「作业人员严禁…」「带气现场负责人签字」误当成列头导致 y 窗偏移串列。
        - 签名允许 1~4 个汉字（OCR 常把监理签字识成单字如「华」）。
        - 按「签名 x ↔ 列头 x」距离全局贪心一对一分配，防止串列。
        - 不在此做 LLM 兜底；识别不到的列返回缺失（None 由调用方写入）。
        """
        result = {}
        col_headers = [
            ("作业人员", "operators"),
            ("施工方现场负责人", "construction_leader"),
            ("监理人员", "supervisor"),
            ("项目公司监护人", "company_monitor"),
            ("带气现场负责人", "gas_leader"),
        ]
        header_kw_set = {kw for kw, _ in col_headers}

        # 从 OCR 坐标段（--- 分隔符之后）解析所有带坐标的文本片段
        coord_section = ""
        if "\n---\n" in ocr_text:
            coord_section = ocr_text.split("\n---\n")[-1]
        elif "\r\n---\r\n" in ocr_text:
            coord_section = ocr_text.split("\r\n---\r\n")[-1]
        if not coord_section:
            return result

        coord_pattern = re.compile(r"^(.+?)\s+\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\s*$")
        all_items = []  # [(text, x, y, w, h), ...]
        for line in coord_section.strip().split("\n"):
            line = line.strip()
            m = coord_pattern.match(line)
            if m:
                text = m.group(1).strip()
                x, y, w, h = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
                all_items.append((text, x, y, w, h))

        if not all_items:
            return result

        def _header_clean(text: str) -> str:
            # 去掉冒号/空白后做整词比对；「…签字」等后缀不会等于五列列头
            return text.replace("：", "").replace(":", "").strip()

        # 步骤1: 严格匹配5列列头（只认整词，可带冒号）
        col_positions = []  # [(field_name, header_x, header_y)]
        for text, x, y, w, h in all_items:
            clean = _header_clean(text)
            for header_kw, field_name in col_headers:
                if clean == header_kw:
                    col_positions.append((field_name, x, y))
                    break

        if len(col_positions) < 3:
            safe_print(f"[Sanitize] 签批列头匹配不足({len(col_positions)}列)，跳过坐标提取")
            return result

        # 若同一 field 因重复 OCR 出现多次，取 y 最大的一组（票面底部签批行）
        best_by_field = {}
        for field, x, y in col_positions:
            prev = best_by_field.get(field)
            if prev is None or y > prev[1]:
                best_by_field[field] = (x, y)
        col_positions = [(f, xy[0], xy[1]) for f, xy in best_by_field.items()]

        # 步骤2: 签名 y 窗 = 列头下方（单字签名框可能较高，放宽到 +150）
        header_y = min(y for _, _, y in col_positions)
        sign_y_min = header_y + 10
        sign_y_max = header_y + 150

        # 步骤3: 候选签名 —— 整段清洗后仅为 1~4 个汉字（保留「华」等单字）
        _NOISE_SUB = (
            "已确认", "确认", "项目公司", "我已接受", "安全教", "签批",
            "内认", "完工", "时间", "负责人签字",
        )
        candidates = []  # [(name, x, y)]
        for text, x, y, w, h in all_items:
            if not (sign_y_min <= y <= sign_y_max):
                continue
            if any(kw in text for kw in _NOISE_SUB):
                continue
            # 列头自身不算签名
            if _header_clean(text) in header_kw_set:
                continue
            core = re.sub(r"[\s：:。.，,、·\-—_（）()【】\[\]]+", "", text)
            if not re.fullmatch(r"[\u4e00-\u9fff]{1,4}", core):
                continue
            candidates.append((core, x, y))

        if not candidates:
            safe_print("[Sanitize] 签批区域未找到候选签名，跳过坐标提取")
            return result

        # 步骤4: 全局按距离贪心一对一匹配（先最近，列/签名各用一次）→ 单字「华」归监理列不串位
        col_x_map = {field: x for field, x, _ in col_positions}
        pairs = []
        for name, name_x, name_y in candidates:
            for field, hx in col_x_map.items():
                dist = abs(name_x - hx)
                if dist < 200:
                    pairs.append((dist, name_y, name, field, name_x, hx))
        pairs.sort(key=lambda t: (t[0], t[1]))  # 距离优先，其次更靠上

        used_fields = set()
        used_names = set()  # (name, x) 防同一 OCR 块重复
        for dist, name_y, name, field, name_x, hx in pairs:
            name_key = (name, name_x)
            if field in used_fields or name_key in used_names:
                continue
            used_fields.add(field)
            used_names.add(name_key)
            result[field] = name
            safe_print(
                f"[Sanitize] 签批坐标匹配: {field} = {name} "
                f"(x={name_x}, 列头x={hx}, 距离={dist})"
            )

        safe_print(f"[Sanitize] 签批坐标提取结果: {result}")
        return result

    def _sanitize_sheet_data(self, raw_dict: dict, ocr_text: str) -> dict:  # 使用规则引擎启发式地校验和兜底 LLM 返回的 JSON 字典数据，规避幻觉错误
        """用 Python + OCR 启发式规则兜底重构和校验 LLM 提取的结构化数据"""
        # 1. 确定作业票类型
        # 本系统仅支持带气作业票
        ticket_type = "带气作业票"
        raw_dict["ticket_type"] = ticket_type

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
                    m = re.search(r"(?:内容|作业内容)[：:]?\s*([^\n]+)", ocr_text)  # 正则获取作业内容行
                    val = m.group(1).strip() if m else ""  # 命中时赋值，否则留空串，不填造假占位
                elif field == "work_time":  # 若作业时间字段缺失
                    m = re.search(r"(?:作业时间|施工时间)[：:]?\s*([^\n]+)", ocr_text)  # 正则搜索作业时间行
                    val = m.group(1).strip() if m else ""  # 命中时取值，否则留空串，不填造假占位
                elif field == "worker_id":  # 若作业人或证书字段缺失
                    m = re.search(r"(?:作业人员|作业人|证书编号)[：:]?\s*([^\n]+)", ocr_text)  # 正则搜索作业人姓名
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
        blank_measure_ids = []  # 带气：五列存在空白漏项的措施序号

        # 带气票：优先解析 ocr5 的 25×5 网格（✓/×/\ /空白）
        gas_grid = parse_gas_measure_grid(ocr_text)
        safe_print(f"[Sanitize] 带气安全措施网格解析: {len(gas_grid)}/{GAS_MEASURE_COUNT} 行")

        for mid, desc in std_measures:  # 逐一遍历标准要求落实的每一条条款
            # 带气：每项 5 列，合法填写为 对号√ / 叉号× / 斜杠\；空白=漏项
            # 【禁止兜底】网格未解析到该行时五列全 blank 并记漏项，禁止默认「已落实」
            if mid not in gas_grid:
                marks = ["blank"] * 5
                safe_print(f"[Sanitize] 第{mid}项五列网格缺失，记为漏项（禁止默认落实）")
            else:
                marks = list(gas_grid[mid])
                if len(marks) < 5:
                    marks = marks + ["blank"] * (5 - len(marks))
            column_marks = marks[:5]
            has_blank = any(mk in GAS_MARK_EMPTY or mk == "blank" for mk in column_marks)
            has_cross = any(mk == "cross" for mk in column_marks)
            impl = (not has_cross) and (not has_blank)
            if has_blank:
                blank_measure_ids.append(mid)

            sanitized_measures.append({
                "measure_id": mid,
                "description": desc,
                "implemented": impl,
                "column_marks": column_marks,
            })
            if not impl:  # 若该防范项为 False 未落实状态，说明现场存在安全隐患
                has_abnormal = True  # 触发将整张作业票的 has_abnormal 标记强制强制提升为 True
                unimplemented_ids.append(mid)  # 将当前有问题的条款 ID 号加入隐患列表

        if blank_measure_ids:
            safe_print(f"[Sanitize] 带气五列存在空白漏项的措施: {blank_measure_ids}")

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

        # 完工时间：LLM 结果 + 票面 OCR 原文匹配（均为真实读取，非编造）
        # 【禁止兜底】两者都没有则置空，由反思校验报漏项，禁止填假时间
        completion = raw_dict.get("completion_time") or ""
        if not completion or str(completion).lower() in ["null", "none", "未知", ""]:
            m = re.search(r"完工时间[：:\s|]*([^\n|]+)", ocr_text)
            completion = m.group(1).strip() if m else ""
            if not completion:
                safe_print("[Sanitize] 完工时间未识别到，置空（禁止编造）")
        if completion and any(k in str(completion) for k in ("重新解析", "校验失败")):
            completion = ""
        raw_dict["completion_time"] = str(completion).strip() or None

        # 发起人签字：仅第二阶段裁剪 OCR；【禁止兜底】失败置空，禁止再用 LLM 全文猜名
        approver = None
        try:
            approver = AgentTools.extract_filler_name(670, 230, 280, 170)  # 1052px 对齐图签字区
        except Exception as e:
            safe_print(f"[Sanitize] 提取签字人失败（禁止 LLM 兜底）: {e}")
        if not approver or str(approver).lower() in ["null", "none", "未知", ""]:
            # 【禁止兜底】此处曾用 raw_dict["approver_name"](LLM) 回填；现禁止，漏项交反思报错
            safe_print("[Sanitize] 发起人签字未识别到，置空（禁止 LLM 姓名兜底）")
            approver = None
        raw_dict["approver_name"] = approver or None
        
        # ---- 签批区域5列签名：仅坐标提取；【禁止 LLM 兜底】识别不到则空，交反思报漏项 ----
        sign_fields = self._extract_sign_columns(ocr_text)
        for _sf in (
            "operators",
            "construction_leader",
            "supervisor",
            "company_monitor",
            "gas_leader",
        ):
            raw_dict[_sf] = sign_fields.get(_sf) or None
        
        # 作业等级 = 表头 OCR「作业等级」一级/二级（一级危险最高）
        # 【禁止兜底】禁止用 LLM 猜测；提不到就空，交路由/完整性报错
        grade = extract_gas_work_grade(ocr_text)
        raw_dict["risk_level"] = grade or None
        if grade:
            safe_print(f"[Sanitize] 带气作业等级: {grade}（一级危险最高）")
        else:
            safe_print("[Sanitize] 带气作业等级未识别到，置空（禁止编造一级/二级）")

        return raw_dict  # 返回整理后的新字典数据

    def _chat_completion(self, req: dict, prefer_json_object: bool = False):
        """统一 chat.completions 调用：记忆后端是否支持 json_object，避免每次 400 后双发。"""
        use_json = prefer_json_object and self._json_object_supported is not False
        if use_json:
            try:
                resp = self.client.chat.completions.create(
                    **req, response_format={"type": "json_object"}
                )
                self._json_object_supported = True
                return resp
            except Exception as e:
                err = str(e)
                if "response_format" in err or "json_object" in err or "json_schema" in err:
                    self._json_object_supported = False
                    safe_print(f"[LLM Log] 后端不支持 json_object，后续仅发文本模式: {e}")
                    return self.client.chat.completions.create(**req)
                raise
        if prefer_json_object and self._json_object_supported is False:
            safe_print("[LLM Log] 使用已缓存的文本模式（跳过 json_object）")
        return self.client.chat.completions.create(**req)

    def extract_sheet_json(self, ocr_text: str) -> SecuritySheetData:  # 调用大模型执行核心 OCR 文字到作业票结构化数据的语义提取提取工作
        safe_print(f"[LLM Log] 调用 API [{self.model_name}] 进行语义分析...")  # 控制台打印系统 API 正在调用提示日志

        system_prompt = (  # 组织结构化大模型的 System 系统级提示词，强制规范提取的键名和返回值结构
            "你是牡丹江中燃 HSE 管理体系的专职安全审计专家。将经 OCR 识别后的文本，"
            "精准解析并提取为以下 JSON 结构：\n"
            "{\n"
            '  "ticket_type": "作业票类型，固定填“带气作业票”",\n'
            '  "ticket_id": "作业票编号（如 MDJZR2025011007 或 MDJZR2026004001）",\n'
            '  "station_name": "作业单位",\n'
            '  "content": "作业内容",\n'
            '  "work_time": "作业时间",\n'
            '  "worker_id": "作业人员姓名及证件号/证书编号",\n'
            '  "check_date": "日期 YYYY-MM-DD（签批区或票面签署日期）",\n'
            '  "completion_time": "完工时间（票面底部完工时间栏，如 2025年10月10日16时0分）",\n'
            '  "risk_level": "带气作业票表头作业等级，只能填“一级”或“二级”（一级危险程度最高；标题如《…带气作业票》（作业等级：二级））",\n'
            '  "operators": "签批区域第1列：作业人员的手写签名姓名",\n'
            '  "construction_leader": "签批区域第2列：施工方现场负责人的手写签名姓名",\n'
            '  "supervisor": "签批区域第3列：监理人员的手写签名姓名",\n'
            '  "company_monitor": "签批区域第4列：项目公司监护人的手写签名姓名",\n'
            '  "gas_leader": "签批区域第5列：带气现场负责人的手写签名姓名"\n'
            "}\n\n"
            "【重要：签批区域提取规则】\n"
            "票面底部「签批」区域有5列，列头从左到右依次为：\n"
            "  第1列=作业人员 -> operators\n"
            "  第2列=施工方现场负责人 -> construction_leader\n"
            "  第3列=监理人员 -> supervisor\n"
            "  第4列=项目公司监护人 -> company_monitor\n"
            "  第5列=带气现场负责人 -> gas_leader\n"
            "列头下方紧跟的手写签名就是对应人员的姓名。"
            "请严格按列的位置顺序一一对应提取，不要混淆列之间的姓名。\n"
            "OCR文本中签批区域的列头行格式通常为：「作业人员：  施工方现场负责人：  监理人员：  项目公司监护人：  带气现场负责人」，"
            "紧接着下一行或几行的手写文字就是各列对应的签名姓名，按从左到右的顺序依次对应上面5个字段。\n\n"
            "直接输出 JSON 对象，不要添加任何 Markdown 标记或多余的解释。"
        )  # 结束提示词定义

        # (已按要求移除截断，让大模型读取完整文本，防止末尾追加的网格结果被切掉)

        user_content = f"OCR 文本：\n{ocr_text}"  # 用户侧消息：携带完整 OCR 文本
        # 缓存本轮发给 LLM 的完整提示词（system + user），供后续归档审计
        prompt_record = (
            f"model: {self.model_name}\n"
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"\n{'=' * 50}\n"
            f"role: system\n"
            f"{'=' * 50}\n\n"
            f"{system_prompt}\n"
            f"\n{'=' * 50}\n"
            f"role: user\n"
            f"{'=' * 50}\n\n"
            f"{user_content}\n"
        )
        self._last_extract_prompt = prompt_record
        if not isinstance(getattr(self, "_extract_prompt_log", None), list):
            self._extract_prompt_log = []
        self._extract_prompt_log.append(prompt_record)

        safe_print(f"[LLM Log] 发送请求中，请等待...")  # 控制台打印请求请求发送状态
        _req = dict(
            model=self.model_name,  # 绑定模型具体别名
            messages=[  # 构建对话消息列表
                {"role": "system", "content": system_prompt},  # 写入系统身份词
                {"role": "user", "content": user_content},  # 写入用户文本内容，传递整理后的 OCR 字符串
            ],  # 结束消息列表
            temperature=0.1,  # 温度设为低极值 0.1 保证内容可控性
            max_tokens=4000,  # 设定最大允许返回的 Token 数限制为 4000
            timeout=120,  # 设定客户端最大的网络超时响应时长为 120 秒
        )
        response = self._chat_completion(_req, prefer_json_object=True)

        if not response.choices:
            raise ValueError(f"LLM 返回空 choices，请检查 base_url 是否含 /v1 及模型是否已加载: {getattr(response, 'error', response)}")
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

    # === 类属性变量声明 / Class Attribute Declarations ===
    _last_image_path = ""        # 缓存最后处理对齐后的图片路径 / Cached path of the last aligned image
    _last_ocr_device = "cpu"     # 缓存最后一次 OCR 推理使用的计算硬件设备 / Cached device (CPU/GPU) for the last OCR run
    _last_ocr_params = None      # 缓存侧边栏/config 中的 PaddleOCR 四模型参数
    _last_ocr_raw = ""           # 缓存全图 OCR 识别提取得到的原始纯文本 / Cached raw text output from full-image OCR scanning
    _last_approver_name = ""     # 缓存第二阶段预提取并清洗的发起人签字姓名 / Cached hand-written name of the approver pre-extracted in phase 2

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
    def ocr_tool(image_path: str, mode: str = "cluster", brain=None, progress_callback=None, engine: str = "paddleocr", vision_brain=None, device: str = "gpu", ticket_type: str = None, ocr_params: dict = None) -> str:  # 核心OCR引擎调用门面方法，支持切换本地 PaddleOCR 和 Vision LLM，device 控制推理硬件
        """调用 ocr 模块进行 OCR 识别，支持坐标聚类和自适应边框检测；可选视觉大模型"""
        AgentTools._last_image_path = image_path
        AgentTools._last_ocr_device = device  # 缓存当前推理设备选择，供 _ocr_crop_region 等静态方法复用。【注意】后续新增的 OCR 功能都应读取此变量，保持与侧边栏设置同步
        if ocr_params is not None:
            AgentTools._last_ocr_params = ocr_params
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
                    # 仅带气模板 dq.png
                    if f != "dq.png":
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
                    # 运行 align_to_template.py（UTF-8 IO + 稳健解码，避免 Web 日志中文乱码）
                    proc = run_python_script(cmd)
                    if proc.returncode != 0:
                        err = (proc.stderr or proc.stdout or "").strip()
                        safe_print(f"[OCR] 对齐脚本失败 {t_file}: {err[:300]}")
                        continue
                    if proc.stderr:
                        # 透出对齐方法选择日志，便于排查歪图
                        for line in (proc.stderr or "").splitlines()[-6:]:
                            if line.strip():
                                safe_print(f"[Align] {line.strip()}")

                    # 检查对齐图片是否生成成功并读取（支持中文路径）
                    if os.path.exists(aligned_path):
                        import numpy as np
                        aligned_img = cv2.imdecode(
                            np.fromfile(aligned_path, dtype=np.uint8), cv2.IMREAD_COLOR
                        )
                        if aligned_img is not None:
                            # 规范尺寸：带气票 1052x1487（ocr5/签字坐标兼容）
                            # 模板 dq 本身已是该尺寸时跳过 resize，避免二次插值发虚
                            target_size = (1052, 1487)
                            if (
                                aligned_img.shape[1] != target_size[0]
                                or aligned_img.shape[0] != target_size[1]
                            ):
                                aligned_img = cv2.resize(
                                    aligned_img, target_size, interpolation=cv2.INTER_AREA
                                    if aligned_img.shape[1] > target_size[0]
                                    else cv2.INTER_LINEAR,
                                )
                                ext = os.path.splitext(aligned_path)[1] or ".png"
                                ok, buf = cv2.imencode(ext, aligned_img)
                                if ok:
                                    buf.tofile(aligned_path)

                            try:
                                safe_print(f"[OCR] 启动 ocr7.py 对对齐图片进行去表格线处理...")
                                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                                from ocr7 import remove_table_lines, imwrite_unicode, default_output_path
                                img_no_lines_bgr, _ = remove_table_lines(aligned_img, strength=1)
                                out_path = default_output_path(aligned_path)
                                if imwrite_unicode(out_path, img_no_lines_bgr):
                                    safe_print(f"[OCR] 去表格化图像已成功保存至: {out_path}")
                                else:
                                    safe_print(f"[OCR] ⚠️ 去表格化图像保存失败: {out_path}")
                            except Exception as e:
                                safe_print(f"[OCR] ⚠️ 去表格化处理异常: {e}")

                            safe_print(f"[OCR] 模板匹配对齐完成：使用 {t_file}（带气）→ {aligned_img.shape[1]}x{aligned_img.shape[0]}")
                            image_path = aligned_path
                            AgentTools._last_image_path = aligned_path
                            matched = True
                            matched_template_type = "带气作业票"
                            break
                except Exception as e:
                    safe_print(f"[OCR] 对齐异常 {t_file}: {e}")
                    # 对齐失败，继续尝试下一个模板                    safe_print(f"[OCR] 调用 align_to_template.py 失败或不匹配 {t_file}: {e}")
            
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
        from ocr import run_ocr, merge_ocr_params  # 动态从独立 ocr 模块中导入核心 run_ocr 执行函数
        
        _prog(15, "启动 PaddleOCR 扫描")  # 触发 15% 进度更新
        
        # 合并侧边栏/config 中的四模型参数；未传入时用默认（含 box_thresh=0.2, score=0.1）
        _paddle_kwargs = merge_ocr_params(
            ocr_params if ocr_params is not None else getattr(AgentTools, "_last_ocr_params", None)
        )
        AgentTools._last_ocr_params = _paddle_kwargs

        sim_ocr = _ProgressSim(progress_callback, 15, 50, "OCR 文字识别中", 3, 0.6)  # 实例化后台进度模拟线程，在识别期间平滑推动进度条从 15% 到 50%
        sim_ocr.start()  # 开启模拟线程
        try:  # 开启 OCR 识别防护
            ocr_result = run_ocr(  # 调用独立 ocr 模块接口获取扫描结果
                image_path=image_path,  # 文件路径
                coords=None,  # 扫描全图
                mode=mode,  # 表格聚类模式
                device=device,  # 使用用户选择的推理设备（cpu/gpu）
                **_paddle_kwargs,  # 四模型参数：det/rec/行方向/页方向等
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
                
                if "带气作业票" in clean_txt or "带气" in clean_txt:
                    ocr_type = "带气作业票"
                    ocr_coords = coords_val
                    break

        detected_type = ocr_type or matched_template_type  # 优先使用 OCR 文字识别的票型进行纠偏，避免模板误匹配
        
        if detected_type:  # 若成功匹配
            coords_str = f" | 坐标: x={ocr_coords[0]}, y={ocr_coords[1]}, w={ocr_coords[2]}, h={ocr_coords[3]}" if ocr_coords else ""
            safe_print(f"[OCR 检测] 首次扫描识别到作业票类型: 【{detected_type}】{coords_str}")  # 标出坐标输出到运行日志中

        # 纯本地 OpenCV 网格符号检测（仅带气作业票 + 对齐成功时触发）
        # 【禁止兜底】ocr5 失败必须暴露问题：抛错中断，禁止静默跳过导致 25×5 全 blank 仍继续“像正常票”
        if detected_type == "带气作业票" and "aligned_" in os.path.basename(image_path):
            safe_print("[OpenCV] 启用 ocr5.py 进行 25×5 符号识别（失败即报错，禁止静默跳过）...")
            cmd = [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "ocr5.py"),
                "--input", image_path
            ]
            res = run_python_script(cmd)
            if res.returncode != 0:
                err = (res.stderr or res.stdout or "").strip()
                raise RuntimeError(
                    f"ocr5 25×5 网格识别失败(exit={res.returncode})，禁止兜底跳过。详情: {err[:500]}"
                )
            append_text = (res.stdout or "").strip()
            if "--- 纯本地 OpenCV 像素密度提取结果 ---" not in append_text:
                raise RuntimeError(
                    "ocr5 未输出有效 25×5 结果块，禁止兜底继续。请检查对齐图尺寸与网格线检测。"
                )
            flat_text = append_text + "\n" + flat_text
            ocr_result = append_text + "\n" + ocr_result
            AgentTools._last_ocr_raw = flat_text
            safe_print("[OpenCV] ocr5.py 25×5 结果前插融合完成")

        return ocr_result

    @staticmethod
    def _ocr_crop_region(image_path: str, x: int, y: int, w: int, h: int, save_crop_path: Optional[str] = None) -> str:
        """裁剪图片指定区域做 PaddleOCR，返回识别文本"""
        from ocr import run_ocr, merge_ocr_params
        _device = getattr(AgentTools, "_last_ocr_device", "cpu")  # 读取用户选择的推理设备，默认 cpu
        _paddle_kwargs = merge_ocr_params(getattr(AgentTools, "_last_ocr_params", None))
        try:
            ocr_result = run_ocr(
                image_path=image_path,
                coords=(x, y, w, h),
                save_crop_path=save_crop_path,
                mode="cluster",
                device=_device,  # 使用与全图扫描相同的推理设备
                **_paddle_kwargs,
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

            # 判断是否符合带气作业条件
            issues = []
            if temp_c <= -5:
                issues.append(f"气温{temp_c}℃(≤-5℃)，低温警告，需加强防冻防滑措施")
            if wind_level >= 5:
                issues.append(f"风力{wind_level}级(≥5级)，禁止露天带气作业")
            if weather_code in [386, 389, 392, 395, 200]:  # 雷雨/暴雨
                issues.append(f"天气{desc}，禁止带气作业")
            if temp_c >= 40:
                issues.append(f"气温{temp_c}℃(≥40℃)，需加强防暑")
            if wind_level >= 4:
                issues.append(f"风力{wind_level}级(4级)，需加强现场防护措施")

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
        带气作业等级为「一级」时同时写入 base2（如果有）；禁止把未识别当成低风险跳过。
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

        # 决定写入哪些 base：base1 始终写；高风险双写 base2
        # 带气：仅明确「一级」双写；【禁止兜底】未识别/空等级不当低风险跳过，也不当一级误双写
        is_high_risk = (risk_level == "一级") or (risk_level in ("重大", "较大"))
        if is_high_risk:
            safe_print(f"[Tool]   等级={risk_level} 高风险 → 双写 base1 + base2")
        elif not risk_level or risk_level in ("未识别", "未填"):
            safe_print(f"[Tool]   等级={risk_level or '空'} 未明确（禁止按低风险/二级假设）→ 仅写 base1")

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
            # base2 仅作业等级「一级」等高风险写入
            if i > 0 and not is_high_risk:
                safe_print(f"[Tool]   等级={risk_level or '非一级'}，跳过双写 {base_name}")
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
        """从第二阶段已缓存的变量中读取责任人姓名，避免在第三阶段执行任何图片裁剪或 OCR 动作"""
        approver = getattr(AgentTools, "_last_approver_name", "")
        safe_print(f"[Tool] extract_filler_name 读取第二阶段预提取并缓存的签字人姓名: 【{approver}】")
        return approver


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

    def __init__(self, brain: LLMBrain, ocr_mode: str = "cluster", ocr_engine: str = "paddleocr", ocr_device: str = "cpu", progress_callback=None, vision_brain: LLMBrain = None, ocr_params: dict = None):  # 编排器构造函数，注入大脑实例、配置参数、推理设备及进度回调函数
        self.brain = brain  # 绑定大模型推理大脑
        self.tools = AgentTools()  # 实例化本智能体持有的执行工具集类
        self.ocr_mode = ocr_mode  # 配置表格 OCR 识别模式
        self.ocr_engine = ocr_engine  # 绑定物理 OCR 识别引擎（PaddleOCR 或 Vision）
        self.ocr_device = ocr_device  # 绑定推理硬件设备类型（cpu 或 gpu）
        self.ocr_params = ocr_params  # 侧边栏/config 中的 PaddleOCR 四模型参数
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
        text = self.tools.ocr_tool(
            image_path,
            mode=self.ocr_mode,
            brain=self.brain,
            progress_callback=prog,
            engine=self.ocr_engine,
            vision_brain=self.vision_brain,
            device=self.ocr_device,
            ticket_type=ticket_type,
            ocr_params=self.ocr_params,
        )  # 调用 ocr_tool 接口识别图片，传入推理设备与四模型参数
        n = len(text.strip().split("\n"))  # 计算识别出的文本总行数
        summary = f"提取 {n} 行文本"  # 汇总感知报告
        safe_print(f"[Agent Perceive] {summary}")  # 打印行数汇总日志
        mem.remember("感知", "👁️", "OCR 提取文字", summary)  # 将感知提取阶段写入记忆体
        
        # 方案 A：感知阶段直接将保存原图、保存对齐图、保存对齐去网格图的事情做好（物理归档）
        if prog: prog(52, "OCR 归档")
        self._archive(image_path, text, mem)
        
        return text  # 返回提取出的文字

    def _reason(self, ocr_text: str, mem: AgentMemory) -> SecuritySheetData:  # 推理阶段：调用大模型进行实体识别和关系分类，填充为 Pydantic 字典
        safe_print("[Agent Reason] LLM 语义分析...")  # 打印推理阶段日志
        # 开启新一轮推理前清空提示词日志，避免与历史票据混档
        self.brain._extract_prompt_log = []
        self.brain._last_extract_prompt = ""
        sim = _ProgressSim(self._progress, 55, 80, "LLM 语义分析中", 2, 1.0)  # 实例化推理进度模拟器线程，进度从 55% 到 80%
        sim.start()  # 开启平滑更新进度线程
        try:  # 安全审计: 提取彻底失败不再静默造假，捕获并转成明确的高风险失败体交由反思/执行拦截
            data = self.brain.extract_sheet_json(ocr_text)  # 调用大模型执行 JSON 语义结构化提取
        except Exception as e:  # LLM 返回无法解析或网络异常
            safe_print(f"[Agent Reason] LLM 提取失败，标记高风险拦截: {e}")  # 打印失败原因，不造假兜底
            mem.remember("推理", "⚠️", "LLM 提取失败", f"高风险拦截: {e}", status="error")  # 记忆体记录提取失败
            sim.done()  # 停止模拟线程
            data = SecuritySheetData(  # 构造明确的高风险失败体，has_abnormal=True 强制走暂缓/拦截分支
                ticket_type="带气作业票",
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

    def _reflect(self, ocr_text: str, data: SecuritySheetData, mem: AgentMemory, image_path: str = "") -> SecuritySheetData:  # 反思阶段：核心自我修正。对模型抽取的要素进行数据完整性强校验，若不符则自动重试修改
        safe_print("[Agent Reflect] 校验数据完整性...")  # 打印反思阶段开始日志
        for attempt in range(1, self.MAX_REFLECT_RETRIES + 1):  # 开启反思纠错循环，最大重试 MAX_REFLECT_RETRIES 次
            checks = []  # 新建单轮校验结果收集列表，每个元素为 (检查项, 是否OK, 说明字串)

            # 定义防指令泄露与模板噪声数据清洗的局部辅助函数
            def clean_field(val, placeholders: list) -> str:
                if not val:
                    return ""
                val_str = str(val).strip()
                # 过滤重试指令泄露的提示语关键字
                leak_keywords = ["重新解析", "上次问题", "按规则", "重试", "数据完整性", "校验失败", "请严格", "数据完整性校验失败"]
                if any(k in val_str for k in leak_keywords):
                    return ""
                # 过滤模板占位符（整段等于占位词，或明显未填写）
                if any(p == val_str or val_str in placeholders for p in placeholders):
                    return ""
                return val_str

            # ========== 带气作业票数据完整性校验 ==========
            # 规则1：25 项安全措施 × 每项 5 列确认格；每格须填 对号√ / 叉号× / 斜杠\ 之一，空白=漏项
            # 图例：确认（落实√ 未落实× 不适用\）
            expected_count = GAS_MEASURE_COUNT  # 25
            role_count = len(GAS_MEASURE_ROLES)  # 5
            std_list = STANDARD_MEASURES.get("带气作业票", [])
            std_ids = {mid for mid, _ in std_list} if std_list else set(range(1, expected_count + 1))
            measures = data.safety_measures or []
            present_ids = {m.measure_id for m in measures if m.measure_id is not None}
            missing_ids = sorted(std_ids - present_ids)

            # 逐项检查五列：✓/×/\ 均算已填写；blank 或列数不足算漏项
            blank_cells = []  # e.g. "第3项-监理"
            incomplete_rows = []  # 无 column_marks 或不足 5 列
            for m in measures:
                marks = list(getattr(m, "column_marks", None) or [])
                if len(marks) < role_count:
                    # 尝试从 ocr 网格补解析（反思重试后 data 可能已有 marks）
                    incomplete_rows.append(m.measure_id)
                    continue
                for i, mk in enumerate(marks[:role_count]):
                    mk_norm = mk if mk in ("check", "cross", "slash", "blank") else _normalize_gas_cell_mark(mk)
                    if mk_norm not in GAS_MARK_FILLED:
                        role_name = GAS_MEASURE_ROLES[i] if i < role_count else f"列{i+1}"
                        blank_cells.append(f"第{m.measure_id}项-{role_name}")

            measures_ok = (
                len(missing_ids) == 0
                and len(blank_cells) == 0
                and len(incomplete_rows) == 0
                and len(present_ids) >= expected_count
            )
            if measures_ok:
                checks.append((
                    "安全措施",
                    True,
                    f"{expected_count}项×{role_count}列全部填写(√/×/\\)、无漏项 OK",
                ))
            else:
                detail_parts = []
                if missing_ids:
                    detail_parts.append(f"缺项{missing_ids}")
                if incomplete_rows:
                    uniq = sorted(set(incomplete_rows))
                    detail_parts.append(f"五列未识别完整{uniq[:8]}{'…' if len(uniq) > 8 else ''}")
                if blank_cells:
                    detail_parts.append(
                        f"空白格{blank_cells[:10]}{'…' if len(blank_cells) > 10 else ''}"
                        f"（共{len(blank_cells)}格）"
                    )
                if len(present_ids) < expected_count:
                    detail_parts.append(f"仅{len(present_ids)}/{expected_count}项")
                checks.append(("安全措施", False, "；".join(detail_parts) if detail_parts else "未填写完整"))

            # 规则2：所有日期和签名都有填写，没有漏项（带气签批五列 + 发起人 + 日期类）
            date_specs = [
                ("日期", data.check_date, ["日期", "年", "月", "日", "YYYY-MM-DD"]),
                ("作业时间", data.work_time, ["作业时间", "时间"]),
                ("完工时间", data.completion_time, ["完工时间", "时间"]),
            ]
            sig_specs = [
                ("发起人签字", data.approver_name, ["签字", "盖章", "负责人", "手写", "发起人签字确认"]),
                ("作业人员签名", data.operators, ["作业人员", "签字", "手写"]),
                ("施工方现场负责人", data.construction_leader, ["施工方现场负责人", "签字", "手写"]),
                ("监理人员", data.supervisor, ["监理人员", "签字", "手写"]),
                ("项目公司监护人", data.company_monitor, ["项目公司监护人", "签字", "手写"]),
                ("带气现场负责人", data.gas_leader, ["带气现场负责人", "签字", "手写"]),
            ]

            missing_date_sig = []
            for label, raw_val, placeholders in date_specs + sig_specs:
                cleaned = clean_field(raw_val, placeholders)
                # 日期/时间至少 4 字符（如 2025…）；签名至少 1 个汉字/字符（允许 OCR 单字）
                min_len = 4 if label in ("日期", "作业时间", "完工时间") else 1
                if not cleaned or len(cleaned) < min_len:
                    missing_date_sig.append(label)

            date_sig_ok = (len(missing_date_sig) == 0)
            if date_sig_ok:
                checks.append(("日期和签名", True, "全部填写、无漏项 OK"))
            else:
                checks.append(("日期和签名", False, f"漏项: {', '.join(missing_date_sig)}"))

            # 规则3：表头作业等级一级/二级必须识别到（禁止空等级兜底放行）
            grade = normalize_gas_work_grade(data.risk_level)
            if grade:
                checks.append(("作业等级", True, f"{grade}" + ("（一级危险最高）" if grade == "一级" else "")))
            else:
                # 【禁止兜底】未识别记失败，暴露问题
                checks.append(("作业等级", False, "表头「作业等级：一级/二级」未识别（禁止编造）"))

            # 完整性任一项漏项 → 触发重试；禁止用默认值假装通过
            integrity_failed = [name for name, ok, _ in checks if not ok]
            all_pass = (len(integrity_failed) == 0)

            for name, ok, detail in checks:  # 迭代校验项
                safe_print(f"[Agent Reflect]   {'OK' if ok else '!!'} {name}: {detail}")  # 控制台打印校验详情条目

            if all_pass:  # 安全措施齐全 + 日期签名齐全 → 完整性通过
                safe_print("[Agent Reflect] 校验通过。")
                mem.remember(
                    "反思", "🔍", "校验数据完整性",
                    "25×5无漏项 + 日期签名齐全 + 作业等级已识别，全部通过",
                )
                return data

            failed = integrity_failed  # 提取本次校验失败的规则项名称
            safe_print(f"[Agent Reflect] 未通过({', '.join(failed)})，第{attempt}次重试...")  # 打印失败警告日志及重试计数
            mem.remember("反思", "🔍", f"第{attempt}次重试", f"未通过: {', '.join(failed)}", status="retry")  # 记忆体记录重试事件
            hint = (
                f"上次问题：{', '.join(failed)}。"
                f"请严格校验：1) 带气安全措施共{expected_count}项，每项5列确认格"
                f"（作业人/施工方现场负责人/监理/监护人/带气现场负责人）"
                f"均须填写对号√、叉号×或斜杠\\之一，禁止空白漏项；"
                f"2) 所有日期与签名均须填写、无漏项；"
                f"3) 表头作业等级须为一级或二级（一级危险最高）。请重新解析。"
            )
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

        std_info = TICKET_STANDARDS.get(data.ticket_type, TICKET_STANDARDS["带气作业票"])
        std_name = std_info["standard_name"]
        std_desc = std_info["standard_desc"]
        clear_dist = std_info["clear_dist_desc"]

        # 带气：风险等级写表头作业等级（一级危险最高）；不写 重大/较大/一般/低风险
        grade = ""
        grade_hint = ""
        if data.ticket_type == "带气作业票":
            grade = normalize_gas_work_grade(data.risk_level) or ""
            # 【禁止兜底】未识别如实写「未识别」，禁止填二级/低风险
            grade_disp = grade if grade else "未识别（禁止兜底）"
            grade_hint = (
                f"作业等级：{grade_disp}"
                + ("（一级危险程度最高）" if grade == "一级" else "")
                + "\n"
            )

        prompt = (
            f"你是HSE安全审计专家，生成{data.ticket_type}审批建议。\n\n"
            "【标准依据】\n"
            f"- {std_name} {std_desc}\n"
            f"- 作业区域要求：{clear_dist}\n"
            "- 五级风及以上禁止露天作业，雷雨天气禁止作业\n\n"
            "【输出格式】\n"
            "无异常→【同意作业】+简要确认+写明作业等级（一级/二级）\n"
            "有异常→【暂缓作业】+逐项列出问题（简写）+写明作业等级（一级/二级，一级危险最高）\n"
            "注意：带气作业票作业等级只能写「一级」或「二级」，禁止写重大/较大/一般/低风险\n"
            "字数100字以内\n\n"
            f"票号：{data.ticket_id} 场站：{data.station_name}\n"
            f"{grade_hint}"
            f"措施：{len(data.safety_measures)}项\n"
            f"异常：{data.has_abnormal}\n"
            f"{issues_desc}{weather_desc}"
        )
        self._last_approval_prompt = prompt  # 缓存发给 LLM 的提示词，供归档使用

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
            # 带气：保持表头作业等级；禁止被「低风险/重大」覆盖
            data.risk_level = self._assess_risk_level(data)
            if not opinion:
                # 【禁止兜底】LLM 空响应/被 think 洗空 → 直接报错文案，禁止模板假通过
                safe_print("[Agent Act] LLM 审批建议为空，禁止模板兜底，记入异常")
                data.has_abnormal = True
                return self._report_approval_failure(data, "LLM 审批建议为空或被 <think> 洗空")
            return opinion
        except Exception as e:
            # 【禁止兜底】API 失败 → 报错暴露问题，禁止模板生成「同意作业」
            safe_print(f"[Agent Act] LLM 审批建议生成失败，禁止模板兜底: {e}")
            data.has_abnormal = True
            return self._report_approval_failure(data, f"LLM 审批建议生成失败: {e}")

    def _assess_risk_level(self, data: SecuritySheetData) -> str:
        """风险等级：带气仅表头作业等级一级/二级；提不到返回空（禁止编造）。"""
        if data.ticket_type == "带气作业票":
            grade = normalize_gas_work_grade(data.risk_level)
            # 【禁止兜底】识别不到不写「未填」冒充等级，返回空串由路由按异常处理
            return grade or ""

        # 非带气：本流水线不交叉；保留评分仅作兼容，禁止默认「低风险」放行
        score = 0
        unimpl = [m for m in data.safety_measures if not m.implemented]
        score += min(len(unimpl), 3)
        biz_issues = [i for i in data.issues if "数据完整性校验失败" not in i.item_name]
        score += min(len(biz_issues), 2)
        for issue in data.issues:
            if "数据完整性校验失败" in issue.item_name:
                score += 2
        if score >= 5:
            return "重大"
        if score >= 3:
            return "较大"
        if score >= 1:
            return "一般"
        # 【禁止兜底】无计分也不返回「低风险」放行标签；空表示未评估
        return ""

    def _report_approval_failure(self, data: SecuritySheetData, reason: str) -> str:
        """审批建议链路失败时的显式报错（非同意/暂缓业务模板，禁止兜底通过）。"""
        grade = normalize_gas_work_grade(data.risk_level) or data.risk_level or "未识别"
        exists = any("审批建议生成失败" in (i.item_name or "") for i in (data.issues or []))
        if not exists:
            data.issues.append(HandWrittenIssue(
                item_name="审批建议生成失败",
                status="异常",
                raw_text=reason,
            ))
        return (
            f"【系统报错·禁止兜底通过】{reason}。"
            f"票号{data.ticket_id or '无'}，作业等级{grade}。"
            f"请修复识别/模型链路后重试，勿人工当同意作业处理。"
        )

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

        # ---- ② 作业等级 ----
        safe_print("[Agent Act] ② 作业等级...")
        data.risk_level = self._assess_risk_level(data)
        unimpl_count = len([m for m in data.safety_measures if not m.implemented])
        grade = normalize_gas_work_grade(data.risk_level)
        if grade == "一级":
            grade_note = "一级危险最高"
        elif grade == "二级":
            grade_note = "二级"
        else:
            # 【禁止兜底】未识别不按二级处理
            grade_note = "未识别（禁止当二级放过）"
            safe_print("[Agent Act] ② 作业等级未识别，将按异常拦截（禁止兜底）")
        safe_print(
            f"[Agent Act] ② 作业等级 → {data.risk_level or '未识别'}（{grade_note}）"
            f" | 未落实{unimpl_count}项, 隐患{len(data.issues)}条"
        )
        mem.remember(
            "执行", "📊", "作业等级",
            f"{data.risk_level or '未识别'}（{grade_note}）| 未落实{unimpl_count}项 | 隐患{len(data.issues)}条",
        )

        # ---- ③ L3 路由决策 ----
        # 人工介入 = 经 MCP 推送钉钉 AI 表格，由主管在钉钉侧处理（非系统内另设人工台）
        safe_print("[Agent Act] ③ L3 路由决策...")
        weather_blocked = not weather_ok and any("禁止" in i for i in weather.get("issues", []))
        dingtalk_human = "⏳ 人工介入：MCP 推送钉钉 AI 表格"
        dingtalk_block = "🚫 禁止放行：MCP 推送钉钉 AI 表格"

        if weather_blocked:
            data.approval_level = "禁止作业"
            data.approval_status = "已驳回"
            route_desc = f"天气禁止作业 → {dingtalk_block}"
        elif data.has_abnormal:
            data.approval_level = "禁止作业"
            data.approval_status = "已驳回"
            route_desc = f"存在隐患 + 作业等级{grade or '未识别'} → {dingtalk_block}"
        elif not grade:
            # 【禁止兜底】表头作业等级未识别 → 禁止作业，禁止按二级自动通过
            data.approval_level = "禁止作业"
            data.approval_status = "已驳回"
            data.has_abnormal = True
            if not any("作业等级未识别" in (i.item_name or "") for i in data.issues):
                data.issues.append(HandWrittenIssue(
                    item_name="作业等级未识别",
                    status="异常",
                    raw_text="表头「作业等级：一级/二级」未识别到，禁止兜底按二级放行",
                ))
            route_desc = f"作业等级未识别 → {dingtalk_block}（禁止兜底为二级）"
        elif grade == "一级" and weather_ok:
            data.approval_level = "钉钉人工介入"
            data.approval_status = "待审批"
            route_desc = f"作业等级一级（危险最高）+ 天气正常 → {dingtalk_human}"
        elif grade == "二级" and weather_ok:
            data.approval_level = "自动通过"
            data.approval_status = "自动通过"
            route_desc = "作业等级二级 + 无隐患 + 天气正常 → ✅ 自动通过"
        else:
            data.approval_level = "钉钉人工介入"
            data.approval_status = "待审批"
            route_desc = f"作业等级{grade} + 天气异常 → {dingtalk_human}"
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
        # 【禁止兜底】责任人未识别则写「未识别」，禁止用「未知」冒充已识别人名
        filler = data.approver_name or "未识别"
        if cfg.get("dingtalk_mcp_url"):
            # 问题描述：推送 stAlertContainer 的完整审批意见与核心要素内容
            ap_status = data.approval_status or "待审批"
            ic = "✅" if ap_status == "自动通过" else ("🚫" if ap_status == "已驳回" else "⏳")
            
            gl = data.risk_level or "未识别"
            ap_path = {
                "自动通过": "系统自动通过",
                "待审批": "人工介入：MCP 推送钉钉 AI 表格",
                "已驳回": "禁止放行：MCP 推送钉钉 AI 表格",
            }.get(ap_status, "")
            gl_line = (
                f"作业等级：{gl}"
                + ("（一级危险最高）" if gl == "一级" else "")
                + ("（识别失败·禁止兜底）" if not data.risk_level else "")
                + " [risk_level]"
            )
            info_lines = [
                f"作业票编号：{data.ticket_id or ''} [ticket_id]",
                f"作业单位：{data.station_name or ''} [station_name]",
                f"作业内容：{data.content or ''} [content]",
                f"作业时间：{data.work_time or ''} [work_time]",
                f"作业人姓名及证书编号：{data.worker_id or ''} [worker_id]",
                gl_line,
                f"审批路径：{ap_path}" if ap_path else "审批路径：-",
                f"发起人签字确认：{data.approver_name or ''} [approver_name]",
                f"作业人员：{data.operators or ''} [operators]",
                f"施工方现场负责人：{data.construction_leader or ''} [construction_leader]",
                f"监理人员：{data.supervisor or ''} [supervisor]",
                f"项目公司监护人：{data.company_monitor or ''} [company_monitor]",
                f"带气现场负责人：{data.gas_leader or ''} [gas_leader]",
            ]
            info_block = "\n\n".join(info_lines)
            description = f"{ic} {data.approval_opinion or ''}\n\n---\n\n{info_block}"
            
            self.tools.write_dingtalk_table(data.ticket_id, image_path, description, filler, data.risk_level or "")
            path_note = "人工介入已推送" if ap_status != "自动通过" else "自动通过已推送"
            safe_print(f"[Agent Act] ⑥ 钉钉 AI 表格 → {path_note} (责任人:{filler})")
            notify_result = f"编号:{data.ticket_id} → 钉钉 AI 表格（{path_note}）责任人:{filler}"
        else:
            safe_print("=" * 56)
            safe_print("[Agent Act] ⚠️⚠️⚠️ 钉钉 MCP 未配置，写入失败！⚠️⚠️⚠️")
            safe_print("[Agent Act]   人工介入依赖 MCP 推送钉钉 AI 表格，请在侧边栏配置后重试。")
            safe_print("=" * 56)
            notify_result = f"编号:{data.ticket_id} → ⚠️ 钉钉 MCP 未配置，人工介入链路不可用"
        safe_print(f"[Agent Act] ⑥ {notify_result}")
        mem.remember("执行", "📤", "钉钉 AI 表格", notify_result)

        # ---- ⑦ 审批建议归档 ----
        safe_print("[Agent Act] ⑦ 审批建议归档...")
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            date_dir = time.strftime("%Y-%m-%d")
            archive_dir = os.path.join(os.path.dirname(__file__), "archives", date_dir)
            os.makedirs(archive_dir, exist_ok=True)
            ticket_id_clean = re.sub(r"\s+", "", data.ticket_id or "")
            if ticket_id_clean:
                prefix = f"{ticket_id_clean}_{ts}"
                approval_path = os.path.join(archive_dir, f"{prefix}_审批建议.txt")
                ap_status = data.approval_status or "待审批"
                ic = "✅" if ap_status == "自动通过" else ("🚫" if ap_status == "已驳回" else "⏳")
                # 组装完整的审批建议归档内容
                gl = data.risk_level or "未识别"
                ap_path = {
                    "自动通过": "系统自动通过",
                    "待审批": "人工介入：MCP 推送钉钉 AI 表格",
                    "已驳回": "禁止放行：MCP 推送钉钉 AI 表格",
                }.get(ap_status, "")
                info_lines = [
                    f"作业票编号：{data.ticket_id or ''}",
                    f"作业单位：{data.station_name or ''}",
                    f"作业内容：{data.content or ''}",
                    f"作业时间：{data.work_time or ''}",
                    f"作业人姓名及证书编号：{data.worker_id or ''}",
                    f"作业等级：{gl}"
                    + ("（一级危险最高）" if gl == "一级" else "")
                    + ("（识别失败·禁止兜底）" if not data.risk_level else ""),
                    f"审批状态：{ap_status}",
                    f"审批路径：{ap_path}" if ap_path else "审批路径：-",
                    f"发起人签字确认：{data.approver_name or ''}",
                    f"作业人员：{data.operators or ''}",
                    f"施工方现场负责人：{data.construction_leader or ''}",
                    f"监理人员：{data.supervisor or ''}",
                    f"项目公司监护人：{data.company_monitor or ''}",
                    f"带气现场负责人：{data.gas_leader or ''}",
                ]
                # 读取本轮缓存的全部 LLM 提示词（结构化提取 + 审批建议）
                approval_prompt = getattr(self, "_last_approval_prompt", "") or ""
                extract_log = getattr(self.brain, "_extract_prompt_log", None) or []
                if not extract_log:
                    last_extract = getattr(self.brain, "_last_extract_prompt", "") or ""
                    extract_log = [last_extract] if last_extract else []
                extract_prompt_block = ""
                if extract_log:
                    parts = []
                    for i, p in enumerate(extract_log, 1):
                        parts.append(f"----- 提取调用 #{i} / 共{len(extract_log)} 次 -----\n\n{p}")
                    extract_prompt_block = "\n\n".join(parts)

                content = (
                    f"{ic} 审批状态：{ap_status}（{data.approval_level or ''}）\n"
                    f"作业等级：{data.risk_level or '未识别'}"
                    f"{'（一级危险最高）' if data.risk_level == '一级' else ''}\n"
                    f"审批路径：{ap_path or '-'}\n"
                    f"归档时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"\n{'='*50}\n"
                    f"审批建议\n"
                    f"{'='*50}\n\n"
                    f"{data.approval_opinion or ''}\n"
                    f"\n{'-'*50}\n"
                    f"核心要素\n"
                    f"{'-'*50}\n\n"
                    + "\n".join(info_lines) + "\n"
                )
                if extract_prompt_block:
                    content += (
                        f"\n{'='*50}\n"
                        f"结构化提取 LLM 提示词\n"
                        f"{'='*50}\n\n"
                        f"{extract_prompt_block}\n"
                    )
                if approval_prompt:
                    content += (
                        f"\n{'='*50}\n"
                        f"审批建议 LLM 提示词\n"
                        f"{'='*50}\n\n"
                        f"{approval_prompt}\n"
                    )
                with open(approval_path, "w", encoding="utf-8") as f:
                    f.write(content)
                safe_print(f"[Agent Act] ⑦ 审批建议已归档: {os.path.basename(approval_path)}")

                # 另存独立的 LLM 提示词文件，便于单独查阅审计
                prompt_path = os.path.join(archive_dir, f"{prefix}_LLM提示词.txt")
                prompt_file = (
                    f"票号：{data.ticket_id or ''}\n"
                    f"模型：{getattr(self.brain, 'model_name', '')}\n"
                    f"归档时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
                if extract_prompt_block:
                    prompt_file += (
                        f"\n{'='*50}\n"
                        f"1. 结构化提取（extract_sheet_json）\n"
                        f"{'='*50}\n\n"
                        f"{extract_prompt_block}\n"
                    )
                if approval_prompt:
                    prompt_file += (
                        f"\n{'='*50}\n"
                        f"2. 审批建议（_generate_approval）\n"
                        f"{'='*50}\n\n"
                        f"{approval_prompt}\n"
                    )
                with open(prompt_path, "w", encoding="utf-8") as f:
                    f.write(prompt_file)
                safe_print(f"[Agent Act] ⑦ LLM 提示词已归档: {os.path.basename(prompt_path)}")
                mem.remember("执行", "📋", "审批建议归档", f"{os.path.basename(approval_path)}; {os.path.basename(prompt_path)}")
            else:
                safe_print("[Agent Act] ⑦ 票号缺失，跳过审批建议归档")
                mem.remember("执行", "📋", "审批建议归档", "票号缺失，跳过")
        except Exception as e:
            safe_print(f"[Agent Act] ⑦ ⚠️ 审批建议归档失败: {e}")
            mem.remember("执行", "📋", "审批建议归档", f"失败: {e}", status="error")

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

            # 3. 如果存在去表格化处理后的图片，也保存一份副本供用户比对
            no_lines_source = os.path.splitext(aligned_source)[0] + "去表格化.png"
            if os.path.exists(no_lines_source):
                img_dest_no_lines = os.path.join(archive_dir, f"{prefix}_对齐图去表格化.png")
                try:
                    shutil.copy2(no_lines_source, img_dest_no_lines)
                    safe_print(f"[Agent Archive] 成功归档去表格化处理后的图片: {img_dest_no_lines}")
                except Exception as e:
                    safe_print(f"[Agent Archive] ⚠️ 去表格化图复制失败: {e}")

            # 4. 在第二阶段（归档处理中）使用 cropimage.py 裁剪提取出“发起人签字确认”区域并保存
            sig_dest = os.path.join(archive_dir, f"{prefix}_签字.png")
            import subprocess
            import sys
            crop_cmd = [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "cropimage.py"),
                "--input", aligned_source,
                "--output", sig_dest,
                "-x", "670",
                "-y", "230",
                "--width", "280",
                "--height", "170"
            ]
            try:
                safe_print(f"[Agent Archive] 正在调用 cropimage.py 裁剪签字区域: {' '.join(crop_cmd)}")
                subprocess.run(crop_cmd, capture_output=True, text=True, check=True)
                safe_print(f"[Agent Archive] 成功提取并保存签字区域到: {sig_dest}")
                
                # 运行 OCR 识别裁剪出的签名图片并保存提取到类变量缓存中，把所有 ocr 都移到第二阶段完成！
                crop_text = AgentTools._ocr_crop_region(aligned_source, 670, 230, 280, 170, save_crop_path=None)
                approver_name = ""
                if crop_text:
                    _LABEL_KW = ("责任", "填表", "编号", "票号", "日期", "场站", "部位", "作业",
                                 "检测", "采样", "确认", "签批", "盖章", "部门", "时间",
                                 "地点", "内容", "方式", "单位", "人员", "完工", "验收")
                    clean_text = crop_text
                    for kw in _LABEL_KW:
                        clean_text = clean_text.replace(kw, "")
                    name_m = re.search(r"([一-龥]{2,4})", clean_text)
                    if name_m:
                        approver_name = name_m.group(1)
                    else:
                        approver_name = clean_text.strip()
                AgentTools._last_approver_name = approver_name
                safe_print(f"[Agent Archive] 第二阶段已完成签字区域 OCR 识别并缓存: 【{approver_name}】")
            except Exception as e:
                safe_print(f"[Agent Archive] ⚠️ 裁剪签字区域失败: {e}")

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
