# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
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
import json  # 导入 JSON 数据解析库以序列化和反序列化配置及异常数据
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


def _llm_field_text(msg, *names: str) -> str:
    """从 message 属性或 model_extra 取字符串字段。"""
    if msg is None:
        return ""
    for name in names:
        v = getattr(msg, name, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    extra = getattr(msg, "model_extra", None) or {}
    if isinstance(extra, dict):
        for name in names:
            v = extra.get(name)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def message_text_from_llm(msg) -> str:
    """从单次 completion message 取可解析文本（只读同一次响应，不二次请求）。

    优先 content 中含 JSON 的文本；content 空或无花括号时再用 reasoning_content。
    """
    if msg is None:
        return ""
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
            else:
                t = getattr(block, "text", None)
                if t:
                    parts.append(str(t))
        content = "\n".join(parts)
    content = (content or "").strip() if isinstance(content, str) else ""
    reasoning = _llm_field_text(msg, "reasoning_content", "reasoning")

    if content and "{" in content:
        return content
    if reasoning and "{" in reasoning:
        if content:
            safe_print("[LLM Log] content 无 JSON 花括号，改用同一次响应的 reasoning_content（不重发）")
        else:
            safe_print("[LLM Log] content 为空，使用同一次响应的 reasoning_content（不重发）")
        return reasoning
    return content or reasoning


def parse_llm_json_object(text: str) -> dict:
    """从模型输出中解析 JSON 对象（本地解析，不调用 LLM）。"""
    raw = clean_thinking(text or "")
    if not raw:
        raise ValueError(
            "LLM 未返回可解析的 JSON 结构（响应为空），安全审计拒绝静默兜底为空字典通过"
        )
    # 去掉 UTF-8 BOM / 全角空格
    raw = raw.lstrip("\ufeff").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception as e:
        safe_print(f"[LLM Log] JSON 直接解析失败: {e}. 尝试提取花括号段...")

    candidates = []
    m = re.search(r"(\{[\s\S]*\})", raw)
    if m:
        candidates.append(m.group(1))
    for i, ch in enumerate(raw):
        if ch == "{":
            candidates.append(raw[i:])
            if len(candidates) > 16:
                break
    for cand in candidates:
        j = cand.rfind("}")
        if j < 0:
            continue
        snippet = cand[: j + 1]
        # 常见尾随逗号修复
        fixed = re.sub(r",\s*([}\]])", r"\1", snippet)
        for trial in (snippet, fixed):
            try:
                obj = json.loads(trial)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
    head = raw[:180].replace("\n", " ")
    raise ValueError(
        "LLM 未返回可解析的 JSON 结构，安全审计拒绝静默兜底为空字典通过"
        f" | 响应片段: {head!r}"
    )


# 作业票类型（两条完全独立流水线，禁止交叉）
TICKET_TYPE_GAS = "带气作业票"
TICKET_TYPE_FIRE = "动火作业票"
SUPPORTED_TICKET_TYPES = (TICKET_TYPE_GAS, TICKET_TYPE_FIRE)
# 模板文件名 → 规范对齐尺寸 + 签字裁剪 ROI（带气 / 动火完全分离，禁止交叉）
# size: 对齐后业务画布（与 template 原图像素一致时可跳过二次缩放）
# sign_crop: (x, y, w, h) 仅用于该票型「发起人/批准人」区域裁剪 OCR
TICKET_TEMPLATE_SPEC = {
    TICKET_TYPE_GAS: {
        "file": "dq.png",
        "size": (1052, 1487),
        "label": "带气",
        # 带气 1052×1487 画布上的发起人签字区
        "sign_crop": (670, 230, 280, 170),
    },
    TICKET_TYPE_FIRE: {
        "file": "dh.png",
        "size": (1000, 1414),
        "label": "动火",
        # 动火 1000×1414：右上「发起人签字确认」合并格（勿套用带气 670,230）
        "sign_crop": (635, 165, 320, 210),
    },
}


def get_ticket_sign_crop(ticket_type: str | None) -> tuple:
    """返回票型独立的签字裁剪 ROI (x,y,w,h)。"""
    tt = (ticket_type or "").strip()
    if "动火" in tt:
        tt = TICKET_TYPE_FIRE
    elif "带气" in tt or tt not in TICKET_TEMPLATE_SPEC:
        tt = TICKET_TYPE_GAS if tt not in TICKET_TEMPLATE_SPEC else tt
    if tt not in TICKET_TEMPLATE_SPEC:
        tt = TICKET_TYPE_GAS
    spec = TICKET_TEMPLATE_SPEC[tt]
    crop = spec.get("sign_crop") or (670, 230, 280, 170)
    return tuple(int(v) for v in crop)

# HSE 标准（按票型分离）
TICKET_STANDARDS = {
    TICKET_TYPE_FIRE: {
        "standard_name": "GB 30871-2022",
        "standard_desc": "《危险化学品企业特殊作业安全规范》",
        "clear_dist_desc": "动火点10m内清除可燃物并配备合适足量的消防器材",
    },
    TICKET_TYPE_GAS: {
        "standard_name": "CJJ 51-2016",
        "standard_desc": "《城镇燃气设施运行、维护和抢修安全技术规程》",
        "clear_dist_desc": "作业区域与周边做到可靠的隔离，现场设置明显标志，夜间设置警示灯",
    },
}

# 法定安全措施（按票型分离：动火 21 条×5 列勾选；带气 25 条×5 列网格）
STANDARD_MEASURES = {
    TICKET_TYPE_FIRE: [
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
    ],
    TICKET_TYPE_GAS: [
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
        # 条文原文含「隐患」二字，与纸质票一致，供 OCR/条款对齐匹配，不作界面文案
        (25, "带气作业过程中，如有紧急或异常情况，应由现场负责人立即通知停止作业，应急处置并消除隐患后才能继续实施作业。"),
    ],
}

FIRE_MEASURE_COUNT = 21
# 动火作业等级：一级最低，二级居中，特级最高（与带气「一级最高」语义不同，禁止混用）
FIRE_WORK_GRADES = ("一级", "二级", "特级")
FIRE_WORK_GRADE_RANK = {"一级": 1, "二级": 2, "特级": 3}  # 数值越大等级越高


# 带气作业票安全措施确认列（每项固定 5 格，图例：落实√ 未落实× 不适用\）
GAS_MEASURE_ROLES = ("作业人", "施工方现场负责人", "监理", "监护人", "带气现场负责人")
# 动火措施确认 5 列（与 ocr5 FIRE_ROLES / dh.png 表头一致，禁止套用带气列名）
FIRE_MEASURE_ROLES = (
    "动火人",
    "施工方现场负责人",
    "监理员",
    "项目公司监护人",
    "动火现场负责人",
)
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
    """归一带气作业等级为 一级/二级，无法识别则返回空串。"""
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


def extract_fire_work_grade(ocr_text: str) -> str:
    """从动火作业票提取作业等级（一级/二级/特级）。

    等级高低：特级最高，二级居中，一级最低。
    """
    if not ocr_text:
        return ""
    patterns = [
        r"(特级|一级|二级)\s*动火",
        r"动火\s*等级\s*[：:]\s*(特级|一级|二级)",
        r"作业等级\s*[：:]\s*(特级|一级|二级)",
        r"[（(]\s*(特级|一级|二级)\s*[）)]",
        r"动火级别\s*[：:]\s*(特级|一级|二级)",
    ]
    for p in patterns:
        m = re.search(p, ocr_text)
        if m:
            g = m.group(1).strip()
            if g in FIRE_WORK_GRADES:
                return g
    return ""


def normalize_fire_work_grade(val) -> str:
    """归一动火作业等级为 一级/二级/特级，无法识别则返回空串。

    等级高低：特级最高，二级居中，一级最低（勿与带气一级最高混淆）。
    """
    if not val:
        return ""
    s = str(val).strip().replace(" ", "")
    if s in FIRE_WORK_GRADES:
        return s
    # 特级优先（避免「一级」子串误伤）
    if "特" in s or s in ("特级动火", "0", "特级"):
        return "特级"
    if "二级" in s or s in ("2", "2级", "二", "Ⅱ", "II") or s.startswith("二"):
        return "二级"
    if "一级" in s or s in ("1", "1级", "一", "Ⅰ", "I") or s.startswith("一"):
        return "一级"
    return ""


def fire_grade_note(grade: str) -> str:
    """动火等级旁注：特级最高 / 一级最低。"""
    g = normalize_fire_work_grade(grade) or (grade or "").strip()
    if g == "特级":
        return "（特级最高）"
    if g == "一级":
        return "（一级最低）"
    if g == "二级":
        return "（二级）"
    return ""


def normalize_ticket_type(val, default: str = TICKET_TYPE_GAS) -> str:
    """归一用户选择的作业票类型；非法值回退 default。"""
    s = (val or "").strip()
    if s in SUPPORTED_TICKET_TYPES:
        return s
    if "动火" in s:
        return TICKET_TYPE_FIRE
    if "带气" in s:
        return TICKET_TYPE_GAS
    return default if default in SUPPORTED_TICKET_TYPES else TICKET_TYPE_GAS


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


def _ocr5_result_block(ocr_text: str) -> str:
    """截取 ocr5 输出块（带气/动火共用分隔标记）。"""
    if not ocr_text:
        return ""
    m_block = re.search(
        r"---\s*纯本地 OpenCV 像素密度提取结果\s*---\s*(.*?)\s*----------------------------------",
        ocr_text,
        re.S,
    )
    return m_block.group(1) if m_block else ocr_text


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
    block = _ocr5_result_block(ocr_text)

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


def parse_fire_measure_grid(ocr_text: str) -> Dict[int, List[str]]:
    """
    从 ocr5 动火块解析 21 项 × 5 列确认标记。
    返回 {measure_id: [m1..m5]}，mark ∈ check|cross|slash|blank
    行格式：第1条: … | 动火人(✓) | 施工方现场负责人(x) | 监理员(✓) | 项目公司监护人(\\) | 动火现场负责人(-)
    与带气 parse_gas_measure_grid 分离（角色名不同）；兼容旧版单列「确认(✓)」。
    """
    result: Dict[int, List[str]] = {}
    if not ocr_text:
        return result
    block = _ocr5_result_block(ocr_text)
    row_pat = re.compile(r"第\s*(\d{1,2})\s*条\s*[:：]?\s*(.*)$", re.M)
    # 五列角色 + 旧单列「确认」兼容
    cell_pat = re.compile(
        r"(动火人|施工方现场负责人|监理员|项目公司监护人|动火现场负责人|确认|监理)\s*"
        r"[\(（]\s*([^\)）]*)\s*[\)）]"
    )
    for m in row_pat.finditer(block):
        try:
            mid = int(m.group(1))
        except ValueError:
            continue
        if mid < 1 or mid > FIRE_MEASURE_COUNT:
            continue
        rest = m.group(2)
        cells = cell_pat.findall(rest)
        if not cells:
            continue
        by_role = {}
        for role, raw_mark in cells:
            # 旧单列「确认」→ 五列同记；「监理」别名 → 监理员
            if role == "确认":
                mk = _normalize_gas_cell_mark(raw_mark)
                result[mid] = [mk] * 5
                by_role = None
                break
            rname = "监理员" if role == "监理" else role
            if rname not in by_role:
                by_role[rname] = _normalize_gas_cell_mark(raw_mark)
        if by_role is None:
            continue
        marks = [by_role.get(role, "blank") for role in FIRE_MEASURE_ROLES]
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

class HandWrittenIssue(BaseModel):  # 定义表示 HSE 作业票中具体手写或自动判定的问题项模型类
    """HSE 作业票中识别出的具体问题项"""
    item_name: str = Field(..., description="异常/检查项名称")  # 定义异常检查项的中文标题字段
    status: str = Field(..., description="状态：'异常' 或 '正常'")  # 定义该项判定的安全状态状态字，异常或正常
    raw_text: Optional[str] = Field(None, description="OCR 原文备注")  # 可选的 OCR 识别出的现场手写意见原文备注


class SafetyMeasureItem(BaseModel):  # 定义安全防范措施条款单条执行状态的模型类
    """安全措施逐项落实状态（带气=五列网格；动火=五列确认格，角色名不同）"""
    measure_id: int = Field(..., description="措施序号")  # 法定安全措施条款对应的数字序号
    description: str = Field(..., description="措施内容原文")  # 安全防范条款的具体文字内容描述说明
    implemented: bool = Field(..., description="True=已落实, False=未落实")  # 是否成功落实并在票上打勾落实的布尔标记
    # 带气：5 列 check|cross|slash|blank；动火：单元素列表 check|cross|blank（无 slash 网格）
    column_marks: List[str] = Field(default_factory=list, description="勾选标记（票型语义不同，禁止混用）")


class SecuritySheetData(BaseModel):  # 定义包含完整作业票所有要素的结构化数据主模型类
    """牡丹江中燃 HSE 作业票结构化数据（带气/动火分路，字段共用模型但流水线分离）"""
    ticket_type: str = Field(default=TICKET_TYPE_GAS, description="作业票类型：带气作业票|动火作业票")
    ticket_id: str = Field(..., description="作业票编号")  # 作业票物理编号，如 MDJ2025xxxx
    # 带气：作业单位；动火：兼容展示，优先用 fire_unit 回填
    station_name: str = Field(default="", description="带气作业单位 / 动火兼容展示单位")
    content: str = Field(default="", description="带气作业内容 / 动火内容")
    work_time: str = Field(default="", description="带气作业时间 / 动火时间")
    worker_id: str = Field(default="", description="带气作业人 / 动火人姓名及证书编号")
    check_date: str = Field(default="", description="日期 YYYY-MM-DD")
    safety_measures: List[SafetyMeasureItem] = Field(default=[], description="安全措施落实状态")
    has_abnormal: bool = Field(..., description="是否存在异常")
    issues: List[HandWrittenIssue] = Field(default=[], description="问题项明细")
    completion_time: Optional[str] = Field(None, description="完工时间/完工验收时间")
    approver_name: Optional[str] = Field(None, description="签批人/负责人姓名")
    # ---- 带气签批五列 ----
    operators: Optional[str] = Field(None, description="作业人员（仅带气）")
    construction_leader: Optional[str] = Field(None, description="施工方现场负责人（带气/动火共用名）")
    supervisor: Optional[str] = Field(None, description="监理人员（带气/动火共用名）")
    company_monitor: Optional[str] = Field(None, description="项目公司监护人/监护人员（带气/动火共用）")
    gas_leader: Optional[str] = Field(None, description="带气现场负责人（仅带气）")
    # ---- 动火专用字段（与带气表字段分离）----
    fire_unit: Optional[str] = Field(None, description="动火单位")
    fire_location: Optional[str] = Field(None, description="动火地点")
    fire_method: Optional[str] = Field(None, description="动火方式")
    sampling_result: Optional[str] = Field(None, description="采样检测")
    fire_personnel: Optional[str] = Field(None, description="动火人员")
    fire_leader_project: Optional[str] = Field(None, description="动火现场负责人(项目公司)")
    fire_leader: Optional[str] = Field(None, description="动火现场负责人")
    approval_opinion: Optional[str] = Field(None, description="自动生成的审批建议")
    # 带气：一级|二级（一级最高）；动火：一级|二级|特级（特级最高、一级最低）
    risk_level: Optional[str] = Field(None, description="作业等级/动火等级（票型语义分离）")
    approval_status: Optional[str] = Field(None, description="审批状态：自动通过/待审批/已驳回")
    approval_level: Optional[str] = Field(None, description="审批路由：自动通过/钉钉人工介入/禁止作业")


# ---- SQLite 表名：带气 / 动火物理分表（已废弃混用表 hse_fire_work_tickets）----
DB_TABLE_GAS = "hse_gas_work_tickets"
DB_TABLE_HOT = "hse_hot_work_tickets"


# ==========================================
# 2. LLM 大脑 (OpenAI 兼容 API)
# ==========================================

def normalize_api_model_name(model_name: str, base_url: str = "") -> str:
    """规范化 API 模型名：DeepSeek 官方只认 deepseek-v4-flash / deepseek-v4-pro（小写连字符）。"""
    name = (model_name or "").strip()
    if not name:
        return name
    key = name.lower().replace("_", "-")
    # 常见误写：DeepSeek-V4-Flash / deepseek-v4.flash 等
    aliases = {
        "deepseek-v4-flash": "deepseek-v4-flash",
        "deepseek-v4-pro": "deepseek-v4-pro",
        "deepseek-v4.flash": "deepseek-v4-flash",
        "deepseek-v4.pro": "deepseek-v4-pro",
        "deepseek/v4-flash": "deepseek-v4-flash",
        "deepseek/v4-pro": "deepseek-v4-pro",
    }
    if key in aliases:
        return aliases[key]
    # DeepSeek 官方域名：统一成小写连字符，避免大小写 400
    if "deepseek.com" in (base_url or "").lower() and "deepseek" in key:
        return key
    return name


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
        self.base_url = (base_url or "").strip()
        self.model_name = normalize_api_model_name(model_name, base_url)  # DeepSeek 等要求精确 model id
        self._last_extract_prompt = ""  # 最近一次结构化提取发给 LLM 的完整提示词（供归档）
        self._extract_prompt_log = []  # 本轮推理/反思全部提取调用的提示词记录（含重试）

    def _extract_sign_columns(self, ocr_text: str) -> dict:
        """基于 OCR 坐标从签批区域精准提取5列签名姓名。

        规则：
        - 列头仅允许「整词」匹配（可带冒号），禁止 startswith，避免
          「作业人员严禁…」「带气现场负责人签字」误当成列头导致 y 窗偏移串列。
        - 签名允许 1~4 个汉字（OCR 常把监理签字识成单字如「华」）。
        - 手写签名常与「已确认」粘连（如「已确认于华」）→ 剥离噪声后再取人名，
          **禁止**因含噪声整段丢弃（监理列最常见漏取根因）。
        - 按「签名 x ↔ 列头 x」距离全局贪心一对一分配，防止串列。
        - 坐标匹配缺失时，对仍空的列做表文/正则回退（仍不 LLM 编造）。
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
            # 无坐标时仍尝试纯文本回退
            return self._extract_sign_columns_text_fallback(ocr_text, result)

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
            return self._extract_sign_columns_text_fallback(ocr_text, result)

        def _header_clean(text: str) -> str:
            # 去掉冒号/空白后做整词比对；「…签字」等后缀不会等于五列列头
            return text.replace("：", "").replace(":", "").strip()

        def _name_from_ocr_cell(text: str) -> str:
            """从签批单元格 OCR 中剥离套话，抽出 1~4 汉字人名。

            典型：
              已确认于华 → 于华
              1 佛 → 佛（作业人员列手写被识成数字+字，禁止因含数字整段丢弃）
              2225193日 / 11. → 空（纯日期/数字残片）
              育，内容已确认。 → 空
            """
            if not text:
                return ""
            s = str(text).strip()
            # 整段就是列头
            if _header_clean(s) in header_kw_set:
                return ""
            # 印刷体表单句（作业人员列下方固定有「我已接受作业安全教育」）不是签名
            if re.search(r"我已接受|安全教育|安全教", s) and not re.search(
                r"已确认[\u4e00-\u9fff]{1,4}", s
            ):
                return ""

            # 冒号后优先（「理动认：于华华」→ 于华华）
            if "：" in s or ":" in s:
                tail = re.split(r"[：:]", s)[-1].strip()
                if tail and tail != s:
                    tail_name = _name_from_ocr_cell(tail)
                    if tail_name:
                        return tail_name

            # 剥离常见套话（顺序：长词优先）
            noise_phrases = (
                "我已接受作业安全教育", "我已接受作业安全教", "内容已确认",
                "已确认。", "已确认", "确认。", "确认",
                "项目公司", "负责人签字", "带气现场负责人签字",
                "签批", "完工时间", "安全教", "理动认",
            )
            for ph in noise_phrases:
                s = s.replace(ph, "")

            # 只保留汉字：去掉数字/英文/标点（手写「1 佛」「J 张三」仍可抽出）
            core = "".join(re.findall(r"[\u4e00-\u9fff]+", s))
            if not core:
                return ""
            # 日期残片：2025年10月31日 → 抽汉字只剩「年月日」→ 必须丢弃
            if re.fullmatch(r"[年月日时分秒~～至到]+", core):
                return ""
            # 混有日期字时先剥掉年月日，剩余才可能是人名
            if re.search(r"[年月日时分秒]", core):
                core = re.sub(r"[年月日时分秒~～至到]", "", core)
                if not core:
                    return ""
            if any(
                j in core
                for j in (
                    "内容", "签字", "时间", "负责人", "监护", "监理",
                    "作业人员", "施工方", "带气", "项目公司", "完工",
                )
            ):
                return ""
            # 套话碎片拼成的伪姓名（OCR 把「内容已确认」撕成「育，内请已认」）
            if core in ("育内", "育内请已", "内请已", "请已认", "已认", "此容已殊认") or re.search(
                r"育内|内请|请已|已认|此容|殊认", core
            ):
                return ""
            if len(core) > 6:
                segs = re.findall(r"[\u4e00-\u9fff]{2,3}", core)
                if not segs:
                    return ""
                name = segs[-1]
            else:
                segs = re.findall(r"[\u4e00-\u9fff]{1,4}", core)
                if not segs:
                    return ""
                segs_sorted = sorted(segs, key=lambda z: (0 if 2 <= len(z) <= 3 else 1, -len(z)))
                name = segs_sorted[0]
            if name in (
                "已", "确", "认", "内", "育", "容", "于", "和", "的", "是", "请",
                "日", "月", "年", "时", "分", "秒",
            ):
                return ""
            return name

        # 步骤1: 严格匹配5列列头（只认整词，可带冒号）
        col_positions = []  # [(field_name, header_x, header_y)]
        for text, x, y, w, h in all_items:
            clean = _header_clean(text)
            for header_kw, field_name in col_headers:
                if clean == header_kw:
                    col_positions.append((field_name, x, y))
                    break

        if len(col_positions) < 3:
            safe_print(f"[Sanitize] 签批列头匹配不足({len(col_positions)}列)，尝试文本回退")
            return self._extract_sign_columns_text_fallback(ocr_text, result)

        # 若同一 field 因重复 OCR 出现多次，取 y 最大的一组（票面底部签批行）
        best_by_field = {}
        for field, x, y in col_positions:
            prev = best_by_field.get(field)
            if prev is None or y > prev[1]:
                best_by_field[field] = (x, y)
        col_positions = [(f, xy[0], xy[1]) for f, xy in best_by_field.items()]

        # 步骤2: 签名 y 窗 = 列头下方
        # 粘连「已确认于华」框较高；带气现场负责人真名常在底部「…签字」旁（更靠下）
        header_y = min(y for _, _, y in col_positions)
        sign_y_min = header_y + 5
        sign_y_max = header_y + 280

        # 步骤3: 候选签名 —— 剥离「已确认」等噪声后再校验 1~4 汉字
        candidates = []  # [(name, x, y, raw)]
        for text, x, y, w, h in all_items:
            if not (sign_y_min <= y <= sign_y_max):
                continue
            if _header_clean(text) in header_kw_set:
                continue
            name = _name_from_ocr_cell(text)
            if not name:
                continue
            candidates.append((name, x, y, text))

        if not candidates:
            safe_print("[Sanitize] 签批区域未找到候选签名，尝试文本回退")
            return self._extract_sign_columns_text_fallback(ocr_text, result)

        # 步骤4: 全局按距离贪心一对一匹配（先最近）
        # 作业人员列下方常有印刷句「我已接受…」，真签名多在更下方 → 对 operators 偏好 y 更大
        col_x_map = {field: x for field, x, _ in col_positions}
        pairs = []
        for name, name_x, name_y, raw in candidates:
            for field, hx in col_x_map.items():
                dist = abs(name_x - hx)
                # 作业人员最左、带气现场负责人最右：x 窗宜紧，防与邻列互抢
                if field == "operators":
                    limit = 100
                elif field == "gas_leader":
                    limit = 110  # 勿用 dist=130 把监护人列「马华」抢成 gas_leader
                elif field in ("supervisor", "construction_leader"):
                    limit = 220
                else:
                    limit = 160  # company_monitor
                if dist < limit:
                    # 排序键：距离 → 双字优先 → 作业人员/带气负责人偏好更靠下
                    below_boost = 0
                    if field in ("operators", "gas_leader"):
                        below_boost = -name_y
                    prio = (dist, 0 if len(name) >= 2 else 1, below_boost)
                    pairs.append((prio, name, field, name_x, hx, raw))
        pairs.sort(key=lambda t: t[0])

        used_fields = set()
        used_names = set()  # (name, x) 防同一 OCR 块重复
        for prio, name, field, name_x, hx, raw in pairs:
            name_key = (name, name_x)
            if field in used_fields or name_key in used_names:
                continue
            used_fields.add(field)
            used_names.add(name_key)
            result[field] = name
            safe_print(
                f"[Sanitize] 签批坐标匹配: {field} = {name} "
                f"(x={name_x}, 列头x={hx}, 距离={prio[0]}, raw={raw!r})"
            )

        def _force_scan_column(field: str, max_dx: int, skip_pat: str = "") -> None:
            if field in result or field not in col_x_map:
                return
            hx = col_x_map[field]
            band = []
            for text, x, y, w, h in all_items:
                if not (sign_y_min <= y <= sign_y_max):
                    continue
                if abs(x - hx) > max_dx:
                    continue
                if _header_clean(text) in header_kw_set:
                    continue
                if "带气现场负责人签字" in text or "（项目公司）" in text or "(项目公司)" in text:
                    continue
                if skip_pat and re.search(skip_pat, text):
                    continue
                name = _name_from_ocr_cell(text)
                if name:
                    band.append((y, abs(x - hx), name, text))
            band.sort(key=lambda t: (-t[0], t[1]))
            if band:
                result[field] = band[0][2]
                safe_print(
                    f"[Sanitize] {field} 列强制扫描: {field} = {band[0][2]} (raw={band[0][3]!r})"
                )

        # 步骤5a: operators 仍空 → 列 x 带强制扫描
        _force_scan_column("operators", 120, r"我已接受|安全教")

        # 步骤5b: gas_leader 仍空 → 第5列 x 带强制扫描（跳过「（项目公司）：」印刷体）
        _force_scan_column("gas_leader", 130, r"项目公司|我已接受|安全教")

        # 步骤5c: gas_leader 仍空 → 底部「带气现场负责人签字」旁人名（票面常见二次落款）
        if "gas_leader" not in result:
            footer_labels = [
                (text, x, y, w, h)
                for text, x, y, w, h in all_items
                if "带气现场负责人签字" in text.replace(" ", "")
            ]
            if footer_labels:
                # 取最靠下的签字标签
                fl = max(footer_labels, key=lambda t: t[2])
                _, fx, fy, fw, fh = fl
                near = []
                for text, x, y, w, h in all_items:
                    if abs(y - fy) > 80:
                        continue
                    if "带气现场负责人" in text or "完工" in text:
                        continue
                    name = _name_from_ocr_cell(text)
                    if not name:
                        continue
                    # 优先标签右侧/下方的人名
                    score = abs(y - fy) * 2 + max(0, fx - x)  # 偏右更好
                    if x + w < fx - 20:
                        score += 50  # 明显在标签左侧降权
                    near.append((score, name, text, x, y))
                near.sort(key=lambda t: t[0])
                if near:
                    result["gas_leader"] = near[0][1]
                    safe_print(
                        f"[Sanitize] 带气现场负责人签字回退: gas_leader = {near[0][1]} "
                        f"(raw={near[0][2]!r})"
                    )

        # 步骤6: 仍缺的列 → 文本回退补齐
        missing = [f for _, f in col_headers if f not in result]
        if missing:
            safe_print(f"[Sanitize] 签批坐标仍缺列 {missing}，文本回退补齐")
            fb = self._extract_sign_columns_text_fallback(ocr_text, dict(result))
            for f in missing:
                if fb.get(f):
                    result[f] = fb[f]
                    safe_print(f"[Sanitize] 签批文本回退: {f} = {fb[f]}")

        safe_print(f"[Sanitize] 签批坐标提取结果: {result}")
        return result

    def _extract_sign_columns_text_fallback(self, ocr_text: str, base: dict = None) -> dict:
        """无坐标/坐标漏匹配时：从表格 OCR 行按列头关键字提取人名。

        优先匹配：
          监理人员：已确认于华
          监理人员： | 已确认于华
        不编造；抽不到则不写该键。
        """
        result = dict(base or {})
        if not ocr_text:
            return result

        # 只看 --- 之前的表格/扁平文本，避免坐标行干扰
        text_part = ocr_text
        if "\n---\n" in ocr_text:
            text_part = ocr_text.split("\n---\n")[0]
        elif "\r\n---\r\n" in ocr_text:
            text_part = ocr_text.split("\r\n---\r\n")[0]

        field_patterns = [
            ("operators", r"作业人员\s*[：:]\s*"),
            ("construction_leader", r"施工方现场负责人\s*[：:]\s*"),
            ("supervisor", r"监理人员\s*[：:]\s*"),
            ("company_monitor", r"项目公司监护人\s*[：:]\s*"),
            # 底部常见「带气现场负责人签字 | 王琳」——签字后不一定有冒号
            ("gas_leader", r"带气现场负责人(?:签字)?\s*[：:]?\s*"),
        ]

        def _clean_name_chunk(chunk: str) -> str:
            if not chunk:
                return ""
            s = chunk.strip()
            for ph in (
                "我已接受作业安全教育", "我已接受作业安全教", "内容已确认",
                "已确认。", "已确认", "确认。", "确认",
                "项目公司", "负责人签字", "（项目公司）", "(项目公司)",
            ):
                s = s.replace(ph, "")
            # 截断到下一列头或日期（保留「签字」后的人名，不再被「带气现场负责人」整段吃掉）
            s = re.split(
                r"(?:作业人员|施工方现场负责人|监理人员|项目公司监护人|"
                r"\d{4}\s*年|完工时间|签批)",
                s,
                maxsplit=1,
            )[0]
            # 去掉残留的「签字」二字
            s = s.replace("签字", "")
            s = re.sub(r"[\s：:。.，,、·\-—_（）()【】\[\]|]+", "", s)
            if re.fullmatch(r"[年月日时分秒]+", s or ""):
                return ""
            if any(j in s for j in ("内容", "时间", "负责人", "监护", "监理", "带气")):
                return ""
            m = re.search(r"[\u4e00-\u9fff]{2,4}", s)
            if m:
                return m.group(0)
            m1 = re.fullmatch(r"[\u4e00-\u9fff]", s)
            if m1 and s not in ("已", "确", "认", "内", "育", "容"):
                return s
            return ""

        for field, head_pat in field_patterns:
            if result.get(field):
                continue
            for line in text_part.split("\n"):
                if not re.search(head_pat, line):
                    continue
                after = re.split(head_pat, line, maxsplit=1)
                if len(after) < 2:
                    continue
                tail = after[1]
                for cell in re.split(r"[|｜]", tail):
                    name = _clean_name_chunk(cell)
                    if name:
                        result[field] = name
                        break
                if result.get(field):
                    break
                name = _clean_name_chunk(tail[:30])
                if name:
                    result[field] = name
                    break

        # gas_leader 专补：全文「带气现场负责人签字 … 人名」
        if not result.get("gas_leader"):
            m = re.search(
                r"带气现场负责人签字\s*[|：:\s]*([\u4e00-\u9fff]{1,4})",
                text_part,
            )
            if m:
                nm = m.group(1)
                if nm not in ("确认", "项目", "公司", "已确"):
                    result["gas_leader"] = nm

        return result

    def _sanitize_sheet_data(self, raw_dict: dict, ocr_text: str, ticket_type: str = None) -> dict:  # 使用规则引擎启发式地校验和兜底 LLM 返回的 JSON 字典数据，规避幻觉错误
        """用 Python + OCR 启发式规则兜底重构和校验 LLM 提取的结构化数据。

        ticket_type 由用户选择锁定；带气 / 动火走完全分离的措施与签批规则，禁止交叉。
        """
        # 1. 锁定作业票类型（用户选择优先，禁止用 OCR 在两票型间串改）
        locked = normalize_ticket_type(
            ticket_type
            or getattr(self, "_locked_ticket_type", None)
            or raw_dict.get("ticket_type"),
            default=TICKET_TYPE_GAS,
        )
        ticket_type = locked
        raw_dict["ticket_type"] = ticket_type
        safe_print(f"[Sanitize] 票型流水线锁定: {ticket_type}")

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

        def _ocr_field(patterns: list) -> str:
            for p in patterns:
                m = re.search(p, ocr_text)
                if m:
                    return m.group(1).strip()
            return ""

        def _clean_val(val) -> str:
            if val is None:
                return ""
            s = str(val).strip()
            if not s or s.lower() in ("null", "none", "未知", "n/a"):
                return ""
            if any(k in s for k in ("重新解析", "校验失败", "请严格")):
                return ""
            return s

        if ticket_type == TICKET_TYPE_FIRE:
            # ---- 动火表头字段（与带气单位/内容语义分离）----
            fire_unit = _clean_val(raw_dict.get("fire_unit")) or _ocr_field([
                r"(?:动火单位|作业单位)[：:\s|]*([^\n|]+)",
            ])
            fire_location = _clean_val(raw_dict.get("fire_location")) or _ocr_field([
                r"(?:动火地点|作业地点|地点)[：:\s|]*([^\n|]+)",
            ])
            content = _clean_val(raw_dict.get("content")) or _ocr_field([
                r"(?:动火内容|作业内容|内容)[：:\s|]*([^\n|]+)",
            ])
            work_time = _clean_val(raw_dict.get("work_time")) or _ocr_field([
                r"(?:动火时间|作业时间|施工时间)[：:\s|]*([^\n|]+)",
            ])
            fire_method = _clean_val(raw_dict.get("fire_method")) or _ocr_field([
                r"(?:动火方式|方式)[：:\s|]*([^\n|]+)",
            ])
            worker_id = _clean_val(raw_dict.get("worker_id")) or _ocr_field([
                r"(?:动火人姓名及证书编号|动火人|证书编号)[：:\s|]*([^\n|]+)",
            ])
            sampling = _clean_val(raw_dict.get("sampling_result")) or _ocr_field([
                r"(?:采样检测|气体检测|检测结果)[：:\s|]*([^\n|]+)",
            ])
            raw_dict["fire_unit"] = fire_unit or None
            raw_dict["fire_location"] = fire_location or None
            raw_dict["content"] = content
            raw_dict["work_time"] = work_time
            raw_dict["fire_method"] = fire_method or None
            raw_dict["worker_id"] = worker_id
            raw_dict["sampling_result"] = sampling or None
            # 兼容列表展示：单位优先动火单位
            raw_dict["station_name"] = fire_unit or fire_location or _clean_val(raw_dict.get("station_name"))
        else:
            for field in ["station_name", "content", "work_time", "worker_id"]:
                val = _clean_val(raw_dict.get(field, ""))
                if not val:
                    if field == "station_name":
                        val = _ocr_field([r"(?:地点|场站|部位|单位)[：:]?\s*([^\n]+)"])
                    elif field == "content":
                        val = _ocr_field([r"(?:内容|作业内容)[：:]?\s*([^\n]+)"])
                    elif field == "work_time":
                        val = _ocr_field([r"(?:作业时间|施工时间)[：:]?\s*([^\n]+)"])
                    elif field == "worker_id":
                        val = _ocr_field([r"(?:作业人员|作业人|证书编号)[：:]?\s*([^\n]+)"])
                raw_dict[field] = val
            # 清空动火专用字段，禁止串写
            for _ff in (
                "fire_unit", "fire_location", "fire_method", "sampling_result",
                "fire_personnel", "fire_leader_project", "fire_leader",
            ):
                raw_dict[_ff] = None

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

        # 6. 安全措施：带气 / 动火完全分路
        std_measures = STANDARD_MEASURES.get(ticket_type, [])
        sanitized_measures = []
        has_abnormal = False
        unimplemented_ids = []
        blank_measure_ids = []

        if ticket_type == TICKET_TYPE_GAS:
            # ---- 带气：ocr5 25×5 网格（✓/×/\ /空白）----
            gas_grid = parse_gas_measure_grid(ocr_text)
            safe_print(f"[Sanitize][带气] 安全措施网格解析: {len(gas_grid)}/{GAS_MEASURE_COUNT} 行")
            for mid, desc in std_measures:
                if mid not in gas_grid:
                    marks = ["blank"] * 5
                    safe_print(f"[Sanitize][带气] 第{mid}项五列网格缺失，记为漏项（禁止默认落实）")
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
                if not impl:
                    has_abnormal = True
                    unimplemented_ids.append(mid)
            if blank_measure_ids:
                safe_print(f"[Sanitize][带气] 五列空白漏项: {blank_measure_ids}")
        else:
            # ---- 动火：ocr5 21×5 确认格（√/×/\ /空白）；角色名与带气不同 ----
            fire_grid = parse_fire_measure_grid(ocr_text)
            safe_print(
                f"[Sanitize][动火] ocr5 五列确认格解析: {len(fire_grid)}/{FIRE_MEASURE_COUNT} 行"
            )
            for mid, desc in std_measures:
                if mid not in fire_grid:
                    marks = ["blank"] * 5
                    safe_print(
                        f"[Sanitize][动火] 第{mid}项五列网格缺失，记为漏项（禁止默认落实）"
                    )
                else:
                    marks = list(fire_grid[mid])
                    if len(marks) < 5:
                        marks = marks + ["blank"] * (5 - len(marks))
                    # 兼容旧单列扩成五列后的数据
                    marks = [
                        mk if mk in ("check", "cross", "slash", "blank")
                        else _normalize_gas_cell_mark(mk)
                        for mk in marks[:5]
                    ]
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
                if not impl:
                    has_abnormal = True
                    unimplemented_ids.append(mid)
            if blank_measure_ids:
                safe_print(f"[Sanitize][动火] 五列空白漏项: {blank_measure_ids}")

        raw_dict["safety_measures"] = sanitized_measures

        # 7. 气体检测浓度异常判定已移除

        # 8. 同步并整理问题项 (issues) 数组列表
        existing_issues = []
        for issue in raw_dict.get("issues", []):
            if isinstance(issue, dict):
                item_name = issue.get("item_name", "")
                if "安全措施第" in item_name:
                    continue
                existing_issues.append(issue)

        for mid in unimplemented_ids:
            desc = next(d for m_id, d in std_measures if m_id == mid)
            # 空白漏项与「叉号未落实」区分：漏填审核以 blank 为准
            if mid in blank_measure_ids:
                existing_issues.append({
                    "item_name": f"安全措施第{mid}项漏填",
                    "status": "漏填",
                    "raw_text": desc,
                })
            else:
                existing_issues.append({
                    "item_name": f"安全措施第{mid}项未落实",
                    "status": "异常",
                    "raw_text": desc,
                })

        if existing_issues:
            has_abnormal = True

        raw_dict["has_abnormal"] = has_abnormal
        raw_dict["issues"] = existing_issues

        # 完工时间
        completion = raw_dict.get("completion_time") or ""
        if not completion or str(completion).lower() in ["null", "none", "未知", ""]:
            m = re.search(r"完工时间[：:\s|]*([^\n|]+)", ocr_text)
            completion = m.group(1).strip() if m else ""
            if not completion:
                safe_print("[Sanitize] 完工时间未识别到，置空（禁止编造）")
        if completion and any(k in str(completion) for k in ("重新解析", "校验失败")):
            completion = ""
        raw_dict["completion_time"] = str(completion).strip() or None

        # 发起人/批准人签字：裁剪 OCR（票型独立 ROI，禁止带气/动火交叉）
        approver = None
        try:
            sx, sy, sw, sh = get_ticket_sign_crop(ticket_type)
            safe_print(f"[Sanitize][{ticket_type}] 签字裁剪 ROI=({sx},{sy},{sw},{sh})")
            approver = AgentTools.extract_filler_name(sx, sy, sw, sh)
        except Exception as e:
            safe_print(f"[Sanitize] 提取签字人失败（禁止 LLM 兜底）: {e}")
        if not approver or str(approver).lower() in ["null", "none", "未知", ""]:
            safe_print("[Sanitize] 发起人签字未识别到，置空（禁止 LLM 姓名兜底）")
            approver = None
        # 动火：允许 LLM 提取的批准人作补充（仅当裁剪为空时仍禁止编造，保持空）
        raw_dict["approver_name"] = approver or None

        if ticket_type == TICKET_TYPE_GAS:
            # ---- 仅带气：五列签批 + 作业等级一级/二级 ----
            sign_fields = self._extract_sign_columns(ocr_text)
            for _sf in (
                "operators",
                "construction_leader",
                "supervisor",
                "company_monitor",
                "gas_leader",
            ):
                raw_dict[_sf] = sign_fields.get(_sf) or None
            # 动火签批字段保持空
            raw_dict["fire_personnel"] = None
            raw_dict["fire_leader_project"] = None
            raw_dict["fire_leader"] = None
            grade = extract_gas_work_grade(ocr_text)
            raw_dict["risk_level"] = grade or None
            if grade:
                safe_print(f"[Sanitize][带气] 作业等级: {grade}（一级危险最高）")
            else:
                safe_print("[Sanitize][带气] 作业等级未识别到，置空（禁止编造一级/二级）")
        else:
            # ---- 仅动火：签批列（与带气 gas_leader/operators 分离）----
            raw_dict["operators"] = None
            raw_dict["gas_leader"] = None

            def _pick_sign(llm_key: str, *patterns: str):
                v = _clean_val(raw_dict.get(llm_key))
                if v:
                    return v
                for p in patterns:
                    v = _ocr_field([p])
                    if v:
                        return v
                return None

            raw_dict["fire_personnel"] = _pick_sign(
                "fire_personnel", r"(?:动火人员)[：:\s|]*([^\n|]+)",
            )
            raw_dict["construction_leader"] = _pick_sign(
                "construction_leader", r"(?:施工方现场负责人)[：:\s|]*([^\n|]+)",
            )
            raw_dict["supervisor"] = _pick_sign(
                "supervisor", r"(?:监理人员)[：:\s|]*([^\n|]+)",
            )
            raw_dict["company_monitor"] = _pick_sign(
                "company_monitor",
                r"(?:项目公司监护人员|项目公司监护人)[：:\s|]*([^\n|]+)",
            )
            raw_dict["fire_leader_project"] = _pick_sign(
                "fire_leader_project",
                r"动火现场负责人\s*[（(]项目公司[）)]\s*[：:\s|]*([^\n|]+)",
            )
            raw_dict["fire_leader"] = _pick_sign(
                "fire_leader",
                r"动火现场负责人(?!\s*[（(]项目公司)\s*[：:\s|]*([^\n|]+)",
            )

            grade = extract_fire_work_grade(ocr_text)
            if not grade:
                grade = normalize_fire_work_grade(raw_dict.get("risk_level"))
            raw_dict["risk_level"] = grade or None
            if grade:
                safe_print(f"[Sanitize][动火] 作业等级: {grade}{fire_grade_note(grade)}（特级最高·一级最低）")
            else:
                safe_print("[Sanitize][动火] 作业等级未识别到，置空（禁止编造）")
            safe_print(
                f"[Sanitize][动火] 单位={raw_dict.get('fire_unit') or '-'} "
                f"地点={raw_dict.get('fire_location') or '-'} "
                f"方式={raw_dict.get('fire_method') or '-'} "
                f"采样={raw_dict.get('sampling_result') or '-'}"
            )

        # 禁止：对 LLM/字段做 t:文本硬改、字符串替换兜底（AI 不得硬改/兜底）
        return raw_dict  # 返回整理后的新字典数据

    def _is_deepseek_backend(self) -> bool:
        base = (getattr(self, "base_url", None) or "").lower()
        model = (self.model_name or "").lower()
        return "deepseek.com" in base or model.startswith("deepseek")

    def _chat_completion(self, req: dict, prefer_json_object: bool = False):
        """统一 chat.completions：全厂商文本模式，单次请求，不使用 json_object。

        DeepSeek V4 默认 thinking=on，长 OCR 时易把 token 耗在 reasoning，
        content 为空/截断；对 DeepSeek 在同一次请求中关闭 thinking。
        prefer_json_object 保留兼容，已忽略。
        """
        payload = dict(req)
        if self._is_deepseek_backend():
            extra = dict(payload.get("extra_body") or {})
            # 官方：extra_body={"thinking": {"type": "disabled"}}
            extra["thinking"] = {"type": "disabled"}
            payload["extra_body"] = extra
            safe_print("[LLM Log] DeepSeek 关闭 thinking，单次文本输出 JSON")
        elif prefer_json_object:
            safe_print("[LLM Log] 统一文本模式输出 JSON（单次请求，不使用 json_object）")
        return self.client.chat.completions.create(**payload)

    def extract_sheet_json(self, ocr_text: str, ticket_type: str = None) -> SecuritySheetData:  # 调用大模型执行核心 OCR 文字到作业票结构化数据的语义提取提取工作
        safe_print(f"[LLM Log] 调用 API [{self.model_name}] 进行语义分析...")  # 控制台打印系统 API 正在调用提示日志
        ticket_type = normalize_ticket_type(
            ticket_type or getattr(self, "_locked_ticket_type", None),
            default=TICKET_TYPE_GAS,
        )
        self._locked_ticket_type = ticket_type
        safe_print(f"[LLM Log] 提取流水线: {ticket_type}（与另一票型提示词完全分离）")

        if ticket_type == TICKET_TYPE_FIRE:
            system_prompt = (
                "你是牡丹江中燃 HSE 管理体系的专职安全审计专家。当前任务**仅处理动火作业票**，"
                "禁止按带气作业票字段理解。将 OCR 文本提取为以下 JSON：\n"
                "{\n"
                f'  "ticket_type": "固定填“{TICKET_TYPE_FIRE}”",\n'
                '  "ticket_id": "作业票编号",\n'
                '  "fire_unit": "动火单位",\n'
                '  "fire_location": "动火地点",\n'
                '  "content": "动火内容",\n'
                '  "work_time": "动火时间",\n'
                '  "fire_method": "动火方式",\n'
                '  "worker_id": "动火人姓名及证书编号",\n'
                '  "sampling_result": "采样检测结果/记录",\n'
                '  "risk_level": "动火等级，只能填“一级”或“二级”或“特级”（特级最高，一级最低）",\n'
                '  "fire_personnel": "动火人员（签批）",\n'
                '  "construction_leader": "施工方现场负责人",\n'
                '  "supervisor": "监理人员",\n'
                '  "company_monitor": "项目公司监护人员",\n'
                '  "fire_leader_project": "动火现场负责人(项目公司)",\n'
                '  "fire_leader": "动火现场负责人",\n'
                '  "check_date": "日期 YYYY-MM-DD",\n'
                '  "completion_time": "完工时间（若有）",\n'
                '  "approver_name": "其他批准/签字人（若有）"\n'
                "}\n\n"
                "【动火票规则】不要使用 gas_leader/operators 等带气字段名；"
                "不要把动火措施当成 25×5 网格。安全措施勾选由系统本地规则解析。\n"
                "【输出要求】只输出一个合法 JSON 对象，不要 Markdown 代码块，不要解释文字。"
            )
        else:
            system_prompt = (
                "你是牡丹江中燃 HSE 管理体系的专职安全审计专家。当前任务**仅处理带气作业票**，"
                "禁止按动火作业票字段理解。将 OCR 文本提取为以下 JSON：\n"
                "{\n"
                f'  "ticket_type": "固定填“{TICKET_TYPE_GAS}”",\n'
                '  "ticket_id": "作业票编号（如 MDJZR2025011007 或 MDJZR2026004001）",\n'
                '  "station_name": "作业单位",\n'
                '  "content": "作业内容",\n'
                '  "work_time": "作业时间",\n'
                '  "worker_id": "作业人员姓名及证件号/证书编号",\n'
                '  "check_date": "日期 YYYY-MM-DD（签批区或票面签署日期）",\n'
                '  "completion_time": "完工时间（票面底部完工时间栏，如 2025年10月10日16时0分）",\n'
                '  "risk_level": "带气作业票表头作业等级，只能填“一级”或“二级”（一级危险程度最高）",\n'
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
                "【输出要求】只输出一个合法 JSON 对象，不要 Markdown 代码块，不要解释文字，不要输出思考过程。"
            )

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
        # 全厂商统一：文本模式 + 本地 JSON 解析（单次请求；DeepSeek 关 thinking）
        response = self._chat_completion(_req, prefer_json_object=True)

        if not response.choices:
            raise ValueError(f"LLM 返回空 choices，请检查 base_url 是否含 /v1 及模型是否已加载: {getattr(response, 'error', response)}")
        # 单次响应：content 优先，必要时用 reasoning_content（不重发 LLM）
        raw_content = message_text_from_llm(response.choices[0].message)
        if not (raw_content or "").strip():
            safe_print("[LLM Log] 警告：content 与 reasoning 均为空")
        try:
            raw_dict = parse_llm_json_object(raw_content)
        except ValueError:
            # 再试一次：把 content 与 reasoning 拼接后本地解析（仍不重发 LLM）
            msg = response.choices[0].message
            combo = "\n".join(
                x for x in (
                    (getattr(msg, "content", None) or ""),
                    _llm_field_text(msg, "reasoning_content", "reasoning"),
                ) if x and str(x).strip()
            )
            if combo and combo != raw_content:
                safe_print("[LLM Log] 拼接 content+reasoning 再解析（不重发请求）")
                raw_dict = parse_llm_json_object(combo)
            else:
                raise

        raw_dict["ticket_type"] = ticket_type  # 强制锁定用户选择票型，禁止 LLM 串改
        sanitized = self._sanitize_sheet_data(raw_dict, ocr_text, ticket_type=ticket_type)
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
        # 票型由用户选择锁定：只匹配对应模板，禁止带气/动火交叉试配
        locked_type = normalize_ticket_type(ticket_type, default=TICKET_TYPE_GAS)
        AgentTools._last_ticket_type = locked_type  # 供归档签字裁剪等分路使用
        spec = TICKET_TEMPLATE_SPEC[locked_type]
        want_file = spec["file"]
        target_size = spec["size"]
        type_label = spec["label"]
        safe_print(
            f"[OCR] 票型锁定={locked_type} → 仅匹配模板 {want_file}"
            f"（规范画布 {target_size[0]}x{target_size[1]}；"
            f"签字ROI={spec.get('sign_crop')}）"
        )

        template_dir = os.path.join(os.path.dirname(__file__), "template")
        templates = []
        if os.path.exists(template_dir):
            for f in os.listdir(template_dir):
                if f.lower().endswith(".png") and not f.startswith("aligned") and not f.startswith("match"):
                    # 忽略「去表格化」派生图；仅精确匹配票型模板
                    if "去表格" in f or f != want_file:
                        continue
                    templates.append(f)

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
                
                # 使用 subprocess 调用 align_to_template.py；显式传票型，带气/动火取点参数分离
                cmd = [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "align_to_template.py"),
                    "--ticket-type", locked_type,
                    "--template", t_path,
                    "--input", image_path,
                    "--output", aligned_path,
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
                            # 按票型规范尺寸缩放（带气 1052x1487 / 动火 1000x1414）
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
                                safe_print(
                                    f"[OCR][{type_label}] 启动 ocr7 去表格线"
                                    f"（票型={locked_type}，参数与另一票型分离）..."
                                )
                                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                                from ocr7 import remove_table_lines, imwrite_unicode, default_output_path
                                img_no_lines_bgr, _ = remove_table_lines(
                                    aligned_img,
                                    strength=1,
                                    ticket_type=locked_type,
                                )
                                out_path = default_output_path(aligned_path)
                                if imwrite_unicode(out_path, img_no_lines_bgr):
                                    safe_print(f"[OCR][{type_label}] 去表格化已保存: {out_path}")
                                else:
                                    safe_print(f"[OCR][{type_label}] ⚠️ 去表格化保存失败: {out_path}")
                            except Exception as e:
                                safe_print(f"[OCR][{type_label}] ⚠️ 去表格化异常: {e}")

                            safe_print(
                                f"[OCR] 模板匹配对齐完成：使用 {t_file}（{type_label}）"
                                f"→ {aligned_img.shape[1]}x{aligned_img.shape[0]}"
                            )
                            image_path = aligned_path
                            AgentTools._last_image_path = aligned_path
                            matched = True
                            matched_template_type = locked_type
                            break
                except Exception as e:
                    safe_print(f"[OCR] 对齐异常 {t_file}: {e}")
            
            if not matched:
                raise RuntimeError(
                    f"上传的照片无法匹配【{locked_type}】模板（{want_file}）。"
                    f"请确认所选票型与照片一致，且拍摄端正清晰无遮挡后重试。"
                )
        else:
            raise RuntimeError(
                f"未找到【{locked_type}】模板文件 template/{want_file}，请检查 template 目录。"
            )

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

        # 票型文字检测：仅日志/校验，不跨票型改写用户锁定类型
        import re  # 导入正则表达式模块

        ocr_type = None
        ocr_coords = None
        for line in flat_text.split("\n"):
            line_str = line.strip()
            m = re.match(r"(.+?)\s+\[(\d+),(\d+),(\d+),(\d+)\]", line_str)
            if m:
                text_part = m.group(1).strip()
                coords_val = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
                clean_txt = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text_part)
                if "带气作业票" in clean_txt or ("带气" in clean_txt and "动火" not in clean_txt):
                    ocr_type = TICKET_TYPE_GAS
                    ocr_coords = coords_val
                    break
                if "动火作业票" in clean_txt or "动火" in clean_txt:
                    ocr_type = TICKET_TYPE_FIRE
                    ocr_coords = coords_val
                    break

        # 流水线票型 = 用户锁定；OCR 仅作一致性警告
        pipeline_type = locked_type
        if ocr_type and ocr_type != locked_type:
            coords_str = (
                f" | 坐标: x={ocr_coords[0]}, y={ocr_coords[1]}, w={ocr_coords[2]}, h={ocr_coords[3]}"
                if ocr_coords else ""
            )
            safe_print(
                f"[OCR 检测] ⚠ 票面文字像【{ocr_type}】但用户选择【{locked_type}】"
                f"{coords_str} — 仍按用户选择流水线处理（不交叉切换）"
            )
        elif ocr_type or matched_template_type:
            detected = ocr_type or matched_template_type
            coords_str = (
                f" | 坐标: x={ocr_coords[0]}, y={ocr_coords[1]}, w={ocr_coords[2]}, h={ocr_coords[3]}"
                if ocr_coords else ""
            )
            safe_print(f"[OCR 检测] 流水线票型【{pipeline_type}】文字/模板一致【{detected}】{coords_str}")

        # ---- ocr5：带气 25×5 / 动火 21×5，票型参数分离，禁止混跑 ----
        if "aligned_" in os.path.basename(image_path) and pipeline_type in (
            TICKET_TYPE_GAS,
            TICKET_TYPE_FIRE,
        ):
            if pipeline_type == TICKET_TYPE_GAS:
                safe_print(
                    "[OpenCV][带气] 启用 ocr5.py 25×5 符号识别（失败即报错，禁止静默跳过）..."
                )
            else:
                safe_print(
                    "[OpenCV][动火] 启用 ocr5.py 21×5 确认格识别（√/×/\\ /空白；与带气列名分离）..."
                )
            cmd = [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "ocr5.py"),
                "--ticket-type", pipeline_type,
                "--input", image_path,
            ]
            res = run_python_script(cmd)
            if res.returncode != 0:
                err = (res.stderr or res.stdout or "").strip()
                raise RuntimeError(
                    f"ocr5[{pipeline_type}] 失败(exit={res.returncode})，禁止兜底跳过。详情: {err[:500]}"
                )
            append_text = (res.stdout or "").strip()
            if "--- 纯本地 OpenCV 像素密度提取结果 ---" not in append_text:
                raise RuntimeError(
                    f"ocr5[{pipeline_type}] 未输出有效结果块，禁止兜底继续。"
                    f"请检查对齐图尺寸与网格线检测。"
                )
            flat_text = append_text + "\n" + flat_text
            ocr_result = append_text + "\n" + ocr_result
            AgentTools._last_ocr_raw = flat_text
            safe_print(f"[OpenCV][{pipeline_type}] ocr5 结果前插融合完成")

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

            # 天气仅留痕；文案中性，不绑定单一票型（动火/带气各自业务规则在流水线内处理）
            issues = []
            if temp_c <= -5:
                issues.append(f"气温{temp_c}℃(≤-5℃)，低温警告，需加强防冻防滑措施")
            if wind_level >= 5:
                issues.append(f"风力{wind_level}级(≥5级)，禁止露天特种作业")
            if weather_code in [386, 389, 392, 395, 200]:  # 雷雨/暴雨
                issues.append(f"天气{desc}，禁止露天特种作业")
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
    def ensure_ticket_tables(conn) -> None:
        """确保带气 / 动火分表存在。

        带气表字段与业务变量一一对应：
          ticket_id 作业票编号 | station_name 作业单位 | content 作业内容
          work_time 作业时间 | worker_id 作业人姓名及证书编号 | check_date 日期
          completion_time 完工时间 | risk_level 作业等级(一级/二级)
          approver_name 发起人签字确认
          operators 作业人员 | construction_leader 施工方现场负责人
          supervisor 监理人员 | company_monitor 项目公司监护人
          gas_leader 带气现场负责人
          safety_measures_json / issues_json / 审批与归档字段

        已废弃的混用表 hse_fire_work_tickets 在此直接删除，不再迁移历史。
        """
        # 废弃旧混用表（用户重新录入，不需要历史）
        conn.execute("DROP TABLE IF EXISTS hse_fire_work_tickets")

        # ---- 带气分表（完整业务列）----
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {DB_TABLE_GAS} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL DEFAULT '',
                station_name TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                work_time TEXT,
                worker_id TEXT NOT NULL DEFAULT '',
                check_date TEXT NOT NULL DEFAULT '',
                completion_time TEXT,
                risk_level TEXT,
                approver_name TEXT,
                operators TEXT,
                construction_leader TEXT,
                supervisor TEXT,
                company_monitor TEXT,
                gas_leader TEXT,
                safety_measures_json TEXT,
                has_abnormal INTEGER NOT NULL DEFAULT 0,
                issues_json TEXT,
                approval_opinion TEXT,
                approval_status TEXT,
                approval_level TEXT,
                raw_ocr_text TEXT,
                image_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # ---- 动火分表 ----
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {DB_TABLE_HOT} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL DEFAULT '',
                fire_unit TEXT,
                fire_location TEXT,
                content TEXT NOT NULL DEFAULT '',
                work_time TEXT,
                fire_method TEXT,
                worker_id TEXT NOT NULL DEFAULT '',
                sampling_result TEXT,
                risk_level TEXT,
                fire_personnel TEXT,
                construction_leader TEXT,
                supervisor TEXT,
                company_monitor TEXT,
                fire_leader_project TEXT,
                fire_leader TEXT,
                check_date TEXT NOT NULL DEFAULT '',
                safety_measures_json TEXT,
                has_abnormal INTEGER NOT NULL DEFAULT 0,
                issues_json TEXT,
                completion_time TEXT,
                approver_name TEXT,
                approval_opinion TEXT,
                approval_status TEXT,
                approval_level TEXT,
                raw_ocr_text TEXT,
                image_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        def _ensure_cols(table: str, cols: list) -> None:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, typ in cols:
                if col not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                    safe_print(f"[Tool] 表 {table} 迁移：新增列 {col}")

        # 带气：补齐业务列（含历史库升级）
        _ensure_cols(DB_TABLE_GAS, [
            ("ticket_id", "TEXT"),
            ("station_name", "TEXT"),
            ("content", "TEXT"),
            ("work_time", "TEXT"),
            ("worker_id", "TEXT"),
            ("check_date", "TEXT"),
            ("completion_time", "TEXT"),
            ("risk_level", "TEXT"),
            ("approver_name", "TEXT"),
            ("operators", "TEXT"),
            ("construction_leader", "TEXT"),
            ("supervisor", "TEXT"),
            ("company_monitor", "TEXT"),
            ("gas_leader", "TEXT"),
            ("safety_measures_json", "TEXT"),
            ("has_abnormal", "INTEGER"),
            ("issues_json", "TEXT"),
            ("approval_opinion", "TEXT"),
            ("approval_status", "TEXT"),
            ("approval_level", "TEXT"),
            ("raw_ocr_text", "TEXT"),
            ("image_path", "TEXT"),
            # 兼容极旧数据中的浓度 JSON 列（新写入不再使用）
            ("gas_concentration_json", "TEXT"),
        ])
        # 动火：补齐业务列
        _ensure_cols(DB_TABLE_HOT, [
            ("ticket_id", "TEXT"),
            ("fire_unit", "TEXT"),
            ("fire_location", "TEXT"),
            ("content", "TEXT"),
            ("work_time", "TEXT"),
            ("fire_method", "TEXT"),
            ("worker_id", "TEXT"),
            ("sampling_result", "TEXT"),
            ("risk_level", "TEXT"),
            ("fire_personnel", "TEXT"),
            ("construction_leader", "TEXT"),
            ("supervisor", "TEXT"),
            ("company_monitor", "TEXT"),
            ("fire_leader_project", "TEXT"),
            ("fire_leader", "TEXT"),
            ("check_date", "TEXT"),
            ("safety_measures_json", "TEXT"),
            ("has_abnormal", "INTEGER"),
            ("issues_json", "TEXT"),
            ("completion_time", "TEXT"),
            ("approver_name", "TEXT"),
            ("approval_opinion", "TEXT"),
            ("approval_status", "TEXT"),
            ("approval_level", "TEXT"),
            ("raw_ocr_text", "TEXT"),
            ("image_path", "TEXT"),
        ])

    @staticmethod
    def save_to_db(data: SecuritySheetData, raw_ocr: str = "", image_path: str = "") -> bool:
        """按票型写入分表：带气 → hse_gas_work_tickets；动火 → hse_hot_work_tickets。"""
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "security_data.db")
        safe_print(f"[Tool] 写入 SQLite: {db_path}")

        conn = sqlite3.connect(db_path)
        try:
            AgentTools.ensure_ticket_tables(conn)
            tt = normalize_ticket_type(data.ticket_type, default=TICKET_TYPE_GAS)
            measures_json = json.dumps(
                [m.model_dump() for m in data.safety_measures], ensure_ascii=False
            )
            issues_json = json.dumps(
                [i.model_dump() for i in data.issues], ensure_ascii=False
            )

            if tt == TICKET_TYPE_FIRE:
                conn.execute(
                    f"INSERT INTO {DB_TABLE_HOT} ("
                    "ticket_id,fire_unit,fire_location,content,work_time,fire_method,"
                    "worker_id,sampling_result,risk_level,fire_personnel,"
                    "construction_leader,supervisor,company_monitor,"
                    "fire_leader_project,fire_leader,check_date,"
                    "safety_measures_json,has_abnormal,issues_json,completion_time,"
                    "approver_name,approval_opinion,approval_status,approval_level,"
                    "raw_ocr_text,image_path"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        data.ticket_id or "",
                        data.fire_unit,
                        data.fire_location,
                        data.content or "",
                        data.work_time,
                        data.fire_method,
                        data.worker_id or "",
                        data.sampling_result,
                        data.risk_level,
                        data.fire_personnel,
                        data.construction_leader,
                        data.supervisor,
                        data.company_monitor,
                        data.fire_leader_project,
                        data.fire_leader,
                        data.check_date or "",
                        measures_json,
                        int(data.has_abnormal),
                        issues_json,
                        data.completion_time,
                        data.approver_name,
                        data.approval_opinion,
                        data.approval_status,
                        data.approval_level,
                        raw_ocr,
                        image_path,
                    ),
                )
                table_name = DB_TABLE_HOT
            else:
                # 带气：业务变量与列一一对应写入（不再写空浓度 JSON）
                conn.execute(
                    f"INSERT INTO {DB_TABLE_GAS} ("
                    "ticket_id,station_name,content,work_time,worker_id,check_date,"
                    "completion_time,risk_level,approver_name,"
                    "operators,construction_leader,supervisor,company_monitor,gas_leader,"
                    "safety_measures_json,has_abnormal,issues_json,"
                    "approval_opinion,approval_status,approval_level,"
                    "raw_ocr_text,image_path"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        data.ticket_id or "",                    # 作业票编号
                        data.station_name or "",                 # 作业单位
                        data.content or "",                      # 作业内容
                        data.work_time or None,                  # 作业时间
                        data.worker_id or "",                    # 作业人姓名及证书编号
                        data.check_date or "",                   # 日期
                        data.completion_time or None,            # 完工时间
                        data.risk_level or None,                 # 作业等级 一级/二级
                        data.approver_name or None,              # 发起人签字确认
                        data.operators or None,                  # 作业人员
                        data.construction_leader or None,        # 施工方现场负责人
                        data.supervisor or None,                 # 监理人员
                        data.company_monitor or None,            # 项目公司监护人
                        data.gas_leader or None,                 # 带气现场负责人
                        measures_json,                           # 25×5 安全措施
                        int(data.has_abnormal),
                        issues_json,
                        data.approval_opinion or None,
                        data.approval_status or None,
                        data.approval_level or None,
                        raw_ocr or None,
                        image_path or None,
                    ),
                )
                table_name = DB_TABLE_GAS

            conn.commit()
            safe_print(f"[Tool] {tt} 票号 {data.ticket_id} 已存入表 {table_name}")
            return True
        finally:
            conn.close()

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
    def _select_dingtalk_bases(caches: list, risk_level: str) -> list:
        """按名称选择写入目标。
        当前：一律只写 test_demo_base。
        （原逻辑：二级/其它 → 仅 base；一级 → base + test_demo_base2，已临时注释。）
        """
        base1 = None
        base2 = None
        for c in caches or []:
            bn = (c.get("base_name") or "").strip()
            bn_l = bn.lower()
            if bn == "test_demo_base" or bn_l == "test_demo_base":
                base1 = c
            elif bn == "test_demo_base2" or bn_l == "test_demo_base2":
                base2 = c
        # 兼容：名称含 test_demo 且不含 2 → base1；含 base2 / 以 2 结尾 → base2
        if base1 is None or base2 is None:
            for c in caches or []:
                bn_l = (c.get("base_name") or "").lower()
                if "test_demo" not in bn_l:
                    continue
                if base2 is None and ("base2" in bn_l or bn_l.endswith("2")):
                    base2 = c
                elif base1 is None and "base2" not in bn_l and not bn_l.endswith("2"):
                    base1 = c
        targets = []
        if base1:
            targets.append(base1)
        elif caches:
            # 未匹配到标准名时退回缓存首项，避免完全写不进去
            targets.append(caches[0])
            safe_print("[Tool]   未精确匹配 test_demo_base，使用缓存首个 base")
        grade = (risk_level or "").strip()
        # --- 临时关闭：一级双写 test_demo_base2 ---
        # if grade == "一级":
        #     if base2:
        #         targets.append(base2)
        #         safe_print("[Tool]   作业等级=一级 → 双写 test_demo_base + test_demo_base2")
        #     else:
        #         safe_print("[Tool]   作业等级=一级，但未发现 test_demo_base2，仅写 base1")
        # else:
        #     safe_print(f"[Tool]   作业等级={grade or '空'} → 仅写 test_demo_base")
        safe_print(
            f"[Tool]   作业等级={grade or '空'} → 仅写 test_demo_base"
            f"（test_demo_base2 双写已注释关闭）"
        )
        return targets

    @staticmethod
    def write_dingtalk_table(ticket_id: str, image_path: str, description: str, person_name: str, risk_level: str = "") -> bool:
        """写入钉钉 AI 表格。
        ticket_id → 编号, image_path → 图片附件, description → 问题描述, person_name → 责任人, risk_level → 等级
        当前仅写 test_demo_base（test_demo_base2 双写已临时注释）。
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

        targets = AgentTools._select_dingtalk_bases(caches, risk_level)
        if not targets:
            safe_print("[Tool] 无可用钉钉 base 可写")
            return False

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
        for cache in targets:
            base_id = cache.get("base_id", "")
            table_id = cache.get("table_id", "")
            fields = cache.get("fields", {})
            base_name = cache.get("base_name", "?")
            if not base_id or not table_id or not fields:
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

        safe_print(f"[Tool] 钉钉 AI 表格写入完成: {success_count}/{len(targets)}")
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
        tt = normalize_ticket_type(getattr(self, "_ticket_type", None), default=TICKET_TYPE_GAS)
        safe_print(f"[Agent Reason] LLM 语义分析（{tt}）...")  # 打印推理阶段日志
        # 开启新一轮推理前清空提示词日志，避免与历史票据混档
        self.brain._extract_prompt_log = []
        self.brain._last_extract_prompt = ""
        self.brain._locked_ticket_type = tt
        sim = _ProgressSim(self._progress, 55, 80, "LLM 语义分析中", 2, 1.0)  # 实例化推理进度模拟器线程，进度从 55% 到 80%
        sim.start()  # 开启平滑更新进度线程
        try:  # 安全审计: 提取彻底失败不再静默造假，捕获并转成明确的高风险失败体交由反思/执行拦截
            data = self.brain.extract_sheet_json(ocr_text, ticket_type=tt)
        except Exception as e:  # LLM 返回无法解析或网络异常
            safe_print(f"[Agent Reason] LLM 提取失败，标记高风险拦截: {e}")  # 打印失败原因，不造假兜底
            mem.remember("推理", "⚠️", "LLM 提取失败", f"高风险拦截: {e}", status="error")  # 记忆体记录提取失败
            sim.done()  # 停止模拟线程
            data = SecuritySheetData(  # 构造失败体，has_abnormal=True 走漏填/人工介入分支
                ticket_type=tt,
                ticket_id="LLM提取失败",  # 占位票号，标记异常来源
                station_name="", content="", work_time="", worker_id="",  # 关键字段一律留空，绝不编造
                check_date="",  # 日期留空
                safety_measures=[], has_abnormal=True,  # 强制异常，触发下游人工介入
                issues=[{"item_name": "LLM 结构化提取失败", "status": "异常", "raw_text": str(e)}],  # 问题明细记录失败原因
            )
            return data  # 直接返回失败体，跳过后续正常路径
        sim.done()  # 停止模拟线程，进度直接推进到 80%
        summary = (f"票型={data.ticket_type} | 票号={data.ticket_id} | 场站={data.station_name} | "
                   f"措施={len(data.safety_measures)}项 | "
                   f"异常={data.has_abnormal}")
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

            tt = normalize_ticket_type(
                data.ticket_type or getattr(self, "_ticket_type", None),
                default=TICKET_TYPE_GAS,
            )
            data.ticket_type = tt  # 锁定，禁止反思过程串票型

            if tt == TICKET_TYPE_GAS:
                # ========== 带气专用：25×5 网格 + 五列签批 + 一级/二级 ==========
                expected_count = GAS_MEASURE_COUNT
                role_count = len(GAS_MEASURE_ROLES)
                std_list = STANDARD_MEASURES.get(TICKET_TYPE_GAS, [])
                std_ids = {mid for mid, _ in std_list} if std_list else set(range(1, expected_count + 1))
                measures = data.safety_measures or []
                present_ids = {m.measure_id for m in measures if m.measure_id is not None}
                missing_ids = sorted(std_ids - present_ids)

                blank_cells = []
                incomplete_rows = []
                for m in measures:
                    marks = list(getattr(m, "column_marks", None) or [])
                    if len(marks) < role_count:
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
                        "安全措施", True,
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
                    min_len = 4 if label in ("日期", "作业时间", "完工时间") else 1
                    if not cleaned or len(cleaned) < min_len:
                        missing_date_sig.append(label)
                if not missing_date_sig:
                    checks.append(("日期和签名", True, "全部填写、无漏项 OK"))
                else:
                    checks.append(("日期和签名", False, f"漏项: {', '.join(missing_date_sig)}"))

                grade = normalize_gas_work_grade(data.risk_level)
                if grade:
                    checks.append(("作业等级", True, f"{grade}" + ("（一级危险最高）" if grade == "一级" else "")))
                else:
                    checks.append(("作业等级", False, "表头「作业等级：一级/二级」未识别（禁止编造）"))

                pass_msg = "25×5无漏项 + 日期签名齐全 + 作业等级已识别，全部通过"
                hint = (
                    f"上次问题：{{failed}}。"
                    f"请严格校验：1) 带气安全措施共{expected_count}项，每项5列确认格"
                    f"（作业人/施工方现场负责人/监理/监护人/带气现场负责人）"
                    f"均须填写对号√、叉号×或斜杠\\之一，禁止空白漏项；"
                    f"2) 所有日期与签名均须填写、无漏项；"
                    f"3) 表头作业等级须为一级或二级（一级危险最高）。请重新解析。"
                )
            else:
                # ========== 动火专用：21×5 列勾选 + 核心字段 ==========
                expected_count = FIRE_MEASURE_COUNT
                std_list = STANDARD_MEASURES.get(TICKET_TYPE_FIRE, [])
                std_ids = {mid for mid, _ in std_list} if std_list else set(range(1, expected_count + 1))
                measures = data.safety_measures or []
                present_ids = {m.measure_id for m in measures if m.measure_id is not None}
                missing_ids = sorted(std_ids - present_ids)
                role_count = len(FIRE_MEASURE_ROLES)

                blank_items = []
                incomplete_cols = []
                for m in measures:
                    marks = list(getattr(m, "column_marks", None) or [])
                    if len(marks) < role_count:
                        marks = marks + ["blank"] * (role_count - len(marks))
                    marks = marks[:role_count]
                    if not marks:
                        blank_items.append(m.measure_id)
                        continue
                    any_blank = False
                    for i, mk in enumerate(marks):
                        mk_norm = mk if mk in ("check", "cross", "slash", "blank") else _normalize_gas_cell_mark(mk)
                        if mk_norm == "blank":
                            any_blank = True
                            role_name = FIRE_MEASURE_ROLES[i] if i < role_count else f"列{i+1}"
                            incomplete_cols.append(f"{m.measure_id}-{role_name}")
                    if any_blank:
                        blank_items.append(m.measure_id)

                measures_ok = (
                    len(missing_ids) == 0
                    and len(blank_items) == 0
                    and len(present_ids) >= expected_count
                )
                if measures_ok:
                    checks.append((
                        "安全措施", True,
                        f"{expected_count}条×5列全部勾选(√/×/\\)、无漏项 OK",
                    ))
                else:
                    detail_parts = []
                    if missing_ids:
                        detail_parts.append(f"缺项{missing_ids}")
                    if incomplete_cols:
                        uniq = incomplete_cols[:12]
                        detail_parts.append(
                            f"空白格{uniq}{'…' if len(incomplete_cols) > 12 else ''}"
                        )
                    if len(present_ids) < expected_count:
                        detail_parts.append(f"仅{len(present_ids)}/{expected_count}项")
                    checks.append(("安全措施", False, "；".join(detail_parts) if detail_parts else "未填写完整"))

                # 动火核心字段（表头 + 签批，与带气字段分离）
                field_specs = [
                    ("作业票编号", data.ticket_id, ["编号", "NO", "No"], 3),
                    ("动火单位", data.fire_unit, ["动火单位", "单位"], 1),
                    ("动火地点", data.fire_location, ["动火地点", "地点"], 1),
                    ("动火内容", data.content, ["动火内容", "内容"], 1),
                    ("动火时间", data.work_time, ["动火时间", "作业时间", "时间"], 4),
                    ("动火方式", data.fire_method, ["动火方式", "方式"], 1),
                    ("动火人姓名及证书编号", data.worker_id, ["动火人", "证书编号", "手写"], 1),
                    ("采样检测", data.sampling_result, ["采样检测", "检测"], 1),
                    ("动火人员", data.fire_personnel, ["动火人员", "签字", "手写"], 1),
                    ("施工方现场负责人", data.construction_leader, ["施工方现场负责人", "签字", "手写"], 1),
                    ("监理人员", data.supervisor, ["监理人员", "签字", "手写"], 1),
                    ("项目公司监护人员", data.company_monitor, ["项目公司监护人员", "监护人", "签字", "手写"], 1),
                    ("动火现场负责人(项目公司)", data.fire_leader_project, ["动火现场负责人", "项目公司", "签字", "手写"], 1),
                    ("动火现场负责人", data.fire_leader, ["动火现场负责人", "签字", "手写"], 1),
                ]
                missing_core = []
                for label, raw_val, placeholders, min_len in field_specs:
                    cleaned = clean_field(raw_val, placeholders)
                    if not cleaned or len(cleaned) < min_len:
                        missing_core.append(label)
                if not missing_core:
                    checks.append(("表头与签批", True, "动火核心字段齐全 OK"))
                else:
                    checks.append(("表头与签批", False, f"漏项: {', '.join(missing_core)}"))

                grade = normalize_fire_work_grade(data.risk_level)
                if grade:
                    checks.append((
                        "动火等级", True,
                        f"{grade}{fire_grade_note(grade)}",
                    ))
                else:
                    checks.append(("动火等级", False, "动火等级「一级/二级/特级」未识别（禁止编造；特级最高、一级最低）"))

                pass_msg = "21条单列无漏项 + 动火表头签批齐全 + 动火等级已识别，全部通过"
                hint = (
                    f"上次问题：{{failed}}。"
                    f"请严格按**动火作业票**解析：1) 安全措施共{expected_count}条，每条须有√或×勾选；"
                    f"2) 须提取：作业票编号、动火单位、动火地点、动火内容、动火时间、动火方式、"
                    f"动火人姓名及证书编号、采样检测、动火人员、施工方现场负责人、监理人员、"
                    f"项目公司监护人员、动火现场负责人(项目公司)、动火现场负责人；"
                    f"3) 动火等级须为一级/二级/特级（特级最高、一级最低）。禁止按带气字段理解。请重新解析。"
                )

            # 完整性任一项漏项 → 触发重试；禁止用默认值假装通过
            integrity_failed = [name for name, ok, _ in checks if not ok]
            all_pass = (len(integrity_failed) == 0)

            for name, ok, detail in checks:  # 迭代校验项
                safe_print(f"[Agent Reflect][{tt}]   {'OK' if ok else '!!'} {name}: {detail}")

            if all_pass:
                safe_print(f"[Agent Reflect][{tt}] 校验通过。")
                mem.remember("反思", "🔍", "校验数据完整性", pass_msg)
                return data

            failed = integrity_failed
            safe_print(f"[Agent Reflect][{tt}] 未通过({', '.join(failed)})，第{attempt}次重试...")
            mem.remember("反思", "🔍", f"第{attempt}次重试", f"未通过: {', '.join(failed)}", status="retry")
            retry_hint = hint.format(failed=", ".join(failed))
            data = self.brain.extract_sheet_json(
                f"[重试] {retry_hint}\n\n原文:\n{ocr_text}",
                ticket_type=tt,
            )

        safe_print("[Agent Reflect] 达到最大重试，标记高风险。")
        mem.remember("反思", "🔍", "最大重试", "标记高风险", status="error")  # 记忆体记录异常归档

        # 将失败的校验项记录为异常问题，防止空模版/无签字件自动通过
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
            safe_print("[Agent Reflect] 达到最大重试，已将失败的完整性校验项强行记入问题明细。")
        return data  # 返回未完全修正的数据，留待 L3 条件路由决策拦截

    @staticmethod
    def _clean_fill_field(val, placeholders: list) -> str:
        """清洗字段：空/占位/指令泄露 → 视为漏填。"""
        if not val:
            return ""
        val_str = str(val).strip()
        leak_keywords = ["重新解析", "上次问题", "按规则", "重试", "数据完整性", "校验失败", "请严格"]
        if any(k in val_str for k in leak_keywords):
            return ""
        if any(p == val_str or val_str in placeholders for p in placeholders):
            return ""
        return val_str

    def _collect_missing_fills(self, data: SecuritySheetData) -> list:
        """汇总手填漏项清单（仅空白/未识别/缺字段，不含「未落实×」业务整改建议）。

        带气 / 动火规则完全分离。
        """
        missing = []
        tt = normalize_ticket_type(data.ticket_type, default=TICKET_TYPE_GAS)
        measures = data.safety_measures or []

        if tt == TICKET_TYPE_GAS:
            role_count = len(GAS_MEASURE_ROLES)
            expected_count = GAS_MEASURE_COUNT
            std_list = STANDARD_MEASURES.get(TICKET_TYPE_GAS, [])
            std_ids = {mid for mid, _ in std_list} if std_list else set(range(1, expected_count + 1))
            present_ids = {m.measure_id for m in measures if m.measure_id is not None}
            for mid in sorted(std_ids - present_ids):
                missing.append(f"安全措施第{mid}项整行缺失")
            for m in measures:
                marks = list(getattr(m, "column_marks", None) or [])
                if len(marks) < role_count:
                    missing.append(f"安全措施第{m.measure_id}项五列未识别完整")
                    continue
                for i, mk in enumerate(marks[:role_count]):
                    mk_norm = mk if mk in ("check", "cross", "slash", "blank") else _normalize_gas_cell_mark(mk)
                    if mk_norm not in GAS_MARK_FILLED:
                        role_name = GAS_MEASURE_ROLES[i] if i < role_count else f"列{i+1}"
                        missing.append(f"安全措施第{m.measure_id}项-{role_name}空白")

            field_specs = [
                ("日期", data.check_date, ["日期", "年", "月", "日", "YYYY-MM-DD"], 4),
                ("作业时间", data.work_time, ["作业时间", "时间"], 4),
                ("完工时间", data.completion_time, ["完工时间", "时间"], 4),
                ("发起人签字", data.approver_name, ["签字", "盖章", "负责人", "手写", "发起人签字确认"], 1),
                ("作业人员签名", data.operators, ["作业人员", "签字", "手写"], 1),
                ("施工方现场负责人", data.construction_leader, ["施工方现场负责人", "签字", "手写"], 1),
                ("监理人员", data.supervisor, ["监理人员", "签字", "手写"], 1),
                ("项目公司监护人", data.company_monitor, ["项目公司监护人", "签字", "手写"], 1),
                ("带气现场负责人", data.gas_leader, ["带气现场负责人", "签字", "手写"], 1),
            ]
            for label, raw_val, placeholders, min_len in field_specs:
                cleaned = self._clean_fill_field(raw_val, placeholders)
                if not cleaned or len(cleaned) < min_len:
                    missing.append(f"{label}漏填")
            if not normalize_gas_work_grade(data.risk_level):
                missing.append("作业等级未识别（表头一级/二级）")
        else:
            # 动火：21×5 列；blank 漏填（slash=不适用视为已填）
            expected_count = FIRE_MEASURE_COUNT
            std_list = STANDARD_MEASURES.get(TICKET_TYPE_FIRE, [])
            std_ids = {mid for mid, _ in std_list} if std_list else set(range(1, expected_count + 1))
            present_ids = {m.measure_id for m in measures if m.measure_id is not None}
            role_count = len(FIRE_MEASURE_ROLES)
            for mid in sorted(std_ids - present_ids):
                missing.append(f"动火安全措施第{mid}项缺失")
            for m in measures:
                marks = list(getattr(m, "column_marks", None) or [])
                if len(marks) < role_count:
                    marks = marks + ["blank"] * (role_count - len(marks))
                marks = marks[:role_count]
                if not marks:
                    missing.append(f"动火安全措施第{m.measure_id}项未勾选")
                    continue
                for i, mk in enumerate(marks):
                    mk_norm = mk if mk in ("check", "cross", "slash", "blank") else _normalize_gas_cell_mark(mk)
                    if mk_norm == "blank":
                        role_name = FIRE_MEASURE_ROLES[i] if i < role_count else f"列{i+1}"
                        missing.append(f"动火安全措施第{m.measure_id}项-{role_name}空白")

            field_specs = [
                ("作业票编号", data.ticket_id, ["编号", "NO", "No"], 3),
                ("动火单位", data.fire_unit, ["动火单位", "单位"], 1),
                ("动火地点", data.fire_location, ["动火地点", "地点"], 1),
                ("动火内容", data.content, ["动火内容", "内容"], 1),
                ("动火时间", data.work_time, ["动火时间", "作业时间", "时间"], 4),
                ("动火方式", data.fire_method, ["动火方式", "方式"], 1),
                ("动火人姓名及证书编号", data.worker_id, ["动火人", "证书编号", "手写"], 1),
                ("采样检测", data.sampling_result, ["采样检测", "检测"], 1),
                ("动火人员", data.fire_personnel, ["动火人员", "签字", "手写"], 1),
                ("施工方现场负责人", data.construction_leader, ["施工方现场负责人", "签字", "手写"], 1),
                ("监理人员", data.supervisor, ["监理人员", "签字", "手写"], 1),
                ("项目公司监护人员", data.company_monitor, ["项目公司监护人员", "监护人", "签字", "手写"], 1),
                ("动火现场负责人(项目公司)", data.fire_leader_project, ["动火现场负责人", "项目公司", "签字", "手写"], 1),
                ("动火现场负责人", data.fire_leader, ["动火现场负责人", "签字", "手写"], 1),
            ]
            for label, raw_val, placeholders, min_len in field_specs:
                cleaned = self._clean_fill_field(raw_val, placeholders)
                if not cleaned or len(cleaned) < min_len:
                    missing.append(f"{label}漏填")
            if not normalize_fire_work_grade(data.risk_level):
                missing.append("动火等级未识别（一级/二级/特级；特级最高、一级最低）")

        for issue in data.issues or []:
            name = issue.item_name or ""
            if "未落实" in name:
                continue
            if any(k in name for k in ("数据完整性", "漏项", "漏填", "空白", "未识别", "审批建议生成失败")):
                detail = f"{name}" + (f"：{issue.raw_text}" if issue.raw_text else "")
                if detail not in missing and not any(detail.startswith(m[:8]) for m in missing):
                    missing.append(detail)
        return missing

    def _generate_approval(self, data: SecuritySheetData, weather: dict = None) -> str:
        """按漏填项生成审批建议（规则模板，不调用 LLM、不做问题整改建议）。

        - 漏填 0 项 → 直接通过说明
        - 有漏填 → 写明漏填项数与明细，需人工介入（不写驳回/异常整改）
        """
        data.risk_level = self._assess_risk_level(data)
        missing = self._collect_missing_fills(data)
        tt = normalize_ticket_type(data.ticket_type, default=TICKET_TYPE_GAS)
        if tt == TICKET_TYPE_GAS:
            grade = normalize_gas_work_grade(data.risk_level) or data.risk_level or "未识别"
        else:
            grade = normalize_fire_work_grade(data.risk_level) or data.risk_level or "未识别"
        ticket = data.ticket_id or "无"
        n = len(missing)
        self._last_approval_prompt = (
            f"mode=missing_fill_check\n"
            f"ticket_type={tt}\n"
            f"ticket={ticket}\ngrade={grade}\nmissing_count={n}\n"
            + "\n".join(f"- {m}" for m in missing)
        )
        if n == 0:
            opinion = (
                f"【填写齐全】漏填 0 项，自动通过。"
                f"{tt} 票号{ticket}，作业等级{grade}。"
            )
            safe_print(f"[Agent Act][{tt}] 审批建议(规则): 漏填0项 → 自动通过")
            return opinion
        show = missing[:12]
        detail = "；".join(show)
        if n > 12:
            detail += f"…（另有{n - 12}项）"
        opinion = (
            f"【发现漏填】共 {n} 项漏填，需人工介入审核（不驳回）。"
            f"明细：{detail}。"
            f"{tt} 票号{ticket}，作业等级{grade}。"
        )
        safe_print(f"[Agent Act][{tt}] 审批建议(规则): 漏填{n}项 → 人工介入")
        return opinion

    def _assess_risk_level(self, data: SecuritySheetData) -> str:
        """作业等级：带气=一级/二级（一级最高）；动火=一级/二级/特级（特级最高、一级最低）。禁止跨票型编造。"""
        tt = normalize_ticket_type(data.ticket_type, default=TICKET_TYPE_GAS)
        if tt == TICKET_TYPE_GAS:
            return normalize_gas_work_grade(data.risk_level) or ""
        # 动火：仅采纳表头一级/二级/特级
        return normalize_fire_work_grade(data.risk_level) or ""

    def _report_approval_failure(self, data: SecuritySheetData, reason: str) -> str:
        """审批建议链路失败时的显式报错（非通过/发现漏填业务模板，禁止兜底通过）。"""
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
            f"请修复识别/模型链路后重试，勿人工当填写齐全通过处理。"
        )

    def _act(self, data: SecuritySheetData, ocr_text: str, mem: AgentMemory, image_path: str = ""):
        safe_print("[Agent Act] ⚡ 执行漏填审核路由...")
        mem.remember("执行", "⚡", "漏填审核路由", "开始：无漏填通过 / 有漏填人工介入")

        # ---- ① 天气（仅记录，不参与驳回；本产品以手填漏项审核为主）----
        safe_print("[Agent Act] ① 天气检查（仅留痕）...")
        weather = self.tools.check_weather_tool("牡丹江")
        weather_ok = weather.get("ok", True)
        if weather_ok:
            safe_print("[Agent Act] ① 天气检查 → 正常")
            mem.remember("执行", "⛅", "天气检查", f"{weather.get('weather','未知')} → 正常（不驱动驳回）")
        else:
            issues_str = "；".join(weather.get("issues", []))
            safe_print(f"[Agent Act] ① 天气检查 → 异常(仅留痕): {issues_str}")
            mem.remember("执行", "⛅", "天气检查", f"异常仅留痕: {issues_str}", status="retry")

        # ---- ② 作业等级（展示用；带气/动火等级体系分离）----
        safe_print("[Agent Act] ② 作业等级...")
        data.risk_level = self._assess_risk_level(data)
        tt_act = normalize_ticket_type(data.ticket_type, default=TICKET_TYPE_GAS)
        if tt_act == TICKET_TYPE_GAS:
            grade = normalize_gas_work_grade(data.risk_level)
        else:
            grade = normalize_fire_work_grade(data.risk_level)
        grade_note = grade if grade else "未识别"
        safe_print(f"[Agent Act][{tt_act}] ② 作业等级 → {data.risk_level or '未识别'}（{grade_note}）")
        mem.remember("执行", "📊", "作业等级", f"{tt_act} {data.risk_level or '未识别'}（{grade_note}）")

        # ---- ③ 漏填路由：0 漏填→自动通过；有漏填→待审批(人工介入)，不驳回 ----
        safe_print("[Agent Act] ③ 漏填路由决策...")
        missing = self._collect_missing_fills(data)
        n_miss = len(missing)
        dingtalk_human = "⏳ 人工介入：MCP 推送钉钉 AI 表格"
        if n_miss == 0:
            data.approval_level = "自动通过"
            data.approval_status = "自动通过"
            route_desc = "漏填 0 项 → ✅ 自动通过"
        else:
            data.approval_level = "钉钉人工介入"
            data.approval_status = "待审批"
            # 漏填记入 issues 便于看板，但不走「已驳回」
            if not any("发现漏填" in (i.item_name or "") or "存在漏填" in (i.item_name or "") for i in (data.issues or [])):
                data.issues.append(HandWrittenIssue(
                    item_name=f"发现漏填{n_miss}项",
                    status="待人工审核",
                    raw_text="；".join(missing[:20]),
                ))
            data.has_abnormal = True  # 有待审事项
            route_desc = f"漏填 {n_miss} 项 → {dingtalk_human}（不驳回）"
        safe_print(f"[Agent Act] ③ 漏填路由 → {route_desc}")
        mem.remember("执行", "🔀", "漏填路由", route_desc)

        # ---- ④ 生成审批建议（规则模板：漏填条数与明细）----
        safe_print("[Agent Act] ④ 生成审批建议（漏填审核）...")
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
                "已驳回": "MCP 推送钉钉 AI 表格",
            }.get(ap_status, "")
            _tt = normalize_ticket_type(data.ticket_type, default=TICKET_TYPE_GAS)
            if _tt == TICKET_TYPE_FIRE:
                info_lines = [
                    f"作业票类型：{_tt} [ticket_type]",
                    f"作业票编号：{data.ticket_id or ''} [ticket_id]",
                    f"动火单位：{data.fire_unit or ''} [fire_unit]",
                    f"动火地点：{data.fire_location or ''} [fire_location]",
                    f"动火内容：{data.content or ''} [content]",
                    f"动火时间：{data.work_time or ''} [work_time]",
                    f"动火方式：{data.fire_method or ''} [fire_method]",
                    f"动火人姓名及证书编号：{data.worker_id or ''} [worker_id]",
                    f"采样检测：{data.sampling_result or ''} [sampling_result]",
                    f"动火等级：{gl}{fire_grade_note(gl)}"
                    + ("（识别失败·禁止兜底）" if not data.risk_level else "")
                    + " [risk_level]",
                    f"动火人员：{data.fire_personnel or ''} [fire_personnel]",
                    f"施工方现场负责人：{data.construction_leader or ''} [construction_leader]",
                    f"监理人员：{data.supervisor or ''} [supervisor]",
                    f"项目公司监护人员：{data.company_monitor or ''} [company_monitor]",
                    f"动火现场负责人(项目公司)：{data.fire_leader_project or ''} [fire_leader_project]",
                    f"动火现场负责人：{data.fire_leader or ''} [fire_leader]",
                    f"审批路径：{ap_path}" if ap_path else "审批路径：-",
                ]
            else:
                gl_line = (
                    f"作业等级：{gl}"
                    + ("（一级危险最高）" if gl == "一级" else "")
                    + ("（识别失败·禁止兜底）" if not data.risk_level else "")
                    + " [risk_level]"
                )
                info_lines = [
                    f"作业票类型：{_tt} [ticket_type]",
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
            
            # 钉钉双写路由：带气「一级最高」→双写；动火仅「特级最高」映射为双写，一级最低/二级→单写
            if _tt == TICKET_TYPE_GAS:
                _grade = normalize_gas_work_grade(data.risk_level) or (data.risk_level or "")
            else:
                _fg = normalize_fire_work_grade(data.risk_level)
                # 钉钉内部仍以 gas 的「一级」键触发双写；动火仅特级映射过去
                _grade = "一级" if _fg == "特级" else "二级"
            self.tools.write_dingtalk_table(
                data.ticket_id, image_path, description, filler, _grade
            )
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
                _tt_arc = normalize_ticket_type(data.ticket_type, default=TICKET_TYPE_GAS)
                ap_path = {
                    "自动通过": "系统自动通过",
                    "待审批": "人工介入：MCP 推送钉钉 AI 表格",
                    "已驳回": "MCP 推送钉钉 AI 表格",
                }.get(ap_status, "")
                if _tt_arc == TICKET_TYPE_FIRE:
                    info_lines = [
                        f"作业票类型：{_tt_arc}",
                        f"作业票编号：{data.ticket_id or ''}",
                        f"动火单位：{data.fire_unit or ''}",
                        f"动火地点：{data.fire_location or ''}",
                        f"动火内容：{data.content or ''}",
                        f"动火时间：{data.work_time or ''}",
                        f"动火方式：{data.fire_method or ''}",
                        f"动火人姓名及证书编号：{data.worker_id or ''}",
                        f"采样检测：{data.sampling_result or ''}",
                        f"动火等级：{gl}{fire_grade_note(gl)}"
                        + ("（识别失败·禁止兜底）" if not data.risk_level else ""),
                        f"动火人员：{data.fire_personnel or ''}",
                        f"施工方现场负责人：{data.construction_leader or ''}",
                        f"监理人员：{data.supervisor or ''}",
                        f"项目公司监护人员：{data.company_monitor or ''}",
                        f"动火现场负责人(项目公司)：{data.fire_leader_project or ''}",
                        f"动火现场负责人：{data.fire_leader or ''}",
                        f"审批状态：{ap_status}",
                        f"审批路径：{ap_path}" if ap_path else "审批路径：-",
                    ]
                else:
                    _gnote = "（一级危险最高）" if gl == "一级" else ""
                    info_lines = [
                        f"作业票类型：{_tt_arc}",
                        f"作业票编号：{data.ticket_id or ''}",
                        f"作业单位：{data.station_name or ''}",
                        f"作业内容：{data.content or ''}",
                        f"作业时间：{data.work_time or ''}",
                        f"作业人姓名及证书编号：{data.worker_id or ''}",
                        f"作业等级：{gl}"
                        + _gnote
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

                _header_gnote = (
                    fire_grade_note(data.risk_level or "")
                    if _tt_arc == TICKET_TYPE_FIRE
                    else ("（一级危险最高）" if data.risk_level == "一级" else "")
                )
                content = (
                    f"{ic} 审批状态：{ap_status}（{data.approval_level or ''}）\n"
                    f"票型：{_tt_arc}\n"
                    f"作业等级：{data.risk_level or '未识别'}"
                    f"{_header_gnote}\n"
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

            # 4. 签字区裁剪：按当前票型 ROI（带气≠动火），禁止写死带气坐标
            sig_dest = os.path.join(archive_dir, f"{prefix}_签字.png")
            import subprocess
            import sys
            _tt_arch = getattr(AgentTools, "_last_ticket_type", None) or getattr(
                self, "_ticket_type", TICKET_TYPE_GAS
            )
            sx, sy, sw, sh = get_ticket_sign_crop(_tt_arch)
            crop_cmd = [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "cropimage.py"),
                "--input", aligned_source,
                "--output", sig_dest,
                "-x", str(sx),
                "-y", str(sy),
                "--width", str(sw),
                "--height", str(sh),
            ]
            try:
                safe_print(
                    f"[Agent Archive][{_tt_arch}] cropimage 签字 ROI=({sx},{sy},{sw},{sh})"
                )
                subprocess.run(crop_cmd, capture_output=True, text=True, check=True)
                safe_print(f"[Agent Archive] 成功提取并保存签字区域到: {sig_dest}")
                
                # 运行 OCR 识别裁剪出的签名图片并保存提取到类变量缓存中，把所有 ocr 都移到第二阶段完成！
                crop_text = AgentTools._ocr_crop_region(
                    aligned_source, sx, sy, sw, sh, save_crop_path=None
                )
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
        """运行完整 ReAct 循环，返回 (ocr_text, structured_data)。

        ticket_type 由 UI 选择锁定，带气 / 动火走完全独立流水线。
        """
        if ocr_mode:
            self.ocr_mode = ocr_mode
        prog = progress_callback or self._progress
        mem = AgentMemory()
        t0 = time.time()
        self._ticket_type = normalize_ticket_type(ticket_type, default=TICKET_TYPE_GAS)
        if getattr(self, "brain", None) is not None:
            self.brain._locked_ticket_type = self._ticket_type
        safe_print(f"[Agent] 启动流水线: {self._ticket_type}（与另一票型完全分离）")

        if prog: prog(0, f"开始处理·{self._ticket_type}")
        self._plan(image_path, mem)
        if prog: prog(3, "感知阶段")
        ocr_text = self._perceive(image_path, mem, ticket_type=self._ticket_type)
        if prog: prog(55, "推理阶段")
        data = self._reason(ocr_text, mem)
        if prog: prog(80, "反思阶段")
        data = self._reflect(ocr_text, data, mem, image_path=image_path)
        if prog: prog(88, "执行阶段")
        self._act(data, ocr_text, mem, image_path=image_path)
        if prog: prog(96, "生成报告")

        elapsed = time.time() - t0
        safe_print(f"[Agent] 全流程耗时: {elapsed:.1f}s | 票型={self._ticket_type}")
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
    # dingtalk：优先环境变量（管理页侧栏 publish_runtime_config 会写入），便于用户页即时同步
    if os.environ.get("DINGTALK_MCP_URL"):
        cfg["dingtalk_mcp_url"] = os.environ["DINGTALK_MCP_URL"]
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
