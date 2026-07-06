# -*- coding: utf-8 -*-
"""
启动依赖版本检查 — 强制要求 Python 3.13+ 及所有第三方依赖为指定最低版本。
在 frontend.py 顶部 import 即可生效。
"""

import os  # 导入系统模块以操作系统环境变量
import sys  # 导入系统工具模块以获取 Python 版本及控制进程退出
import importlib.metadata as _meta  # 导入安装包元数据模块以获取第三方依赖的已安装版本号

# ---- Python 版本要求 ----
_PY_MIN = (3, 13, 0)  # 定义元组表示要求的 Python 最低版本为 3.13.0

# ---- 第三方依赖: (pip包名, import名, 最低版本, 安装名) ----
_DEPS = [  # 构建要求校验的依赖包元数据列表
    ("pydantic",       "pydantic",       "2.13.4",       "pydantic"),  # Pydantic 数据验证库版本控制
    ("streamlit",      "streamlit",      "1.58.0",       "streamlit"),  # Streamlit 前端交互框架版本控制
    ("opencv-python",  "cv2",            "4.13.0.92",    "opencv-python"),  # OpenCV 图像库版本控制
    ("paddleocr",      "paddleocr",      "3.7.0",        "paddleocr"),  # PaddleOCR 识别库版本控制
    ("openai",         "openai",         "2.44.0",       "openai"),  # OpenAI 客户端库版本控制
    ("numpy",          "numpy",          "2.3.5",        "numpy"),  # NumPy 矩阵计算库版本控制
    ("pandas",         "pandas",         "3.0.3",        "pandas"),  # Pandas 表格分析库版本控制
    ("requests",       "requests",       "2.34.2",       "requests"),  # HTTP 网络请求库版本控制
    ("mcp",            "mcp",            "1.0.0",        "mcp"),  # Model Context Protocol 协议库版本控制
    ("httpx",          "httpx",          "0.28.0",       "httpx"),  # HTTPX 客户端库版本控制
    ("httpx-sse",      "httpx_sse",      "0.4.0",        "httpx-sse"),  # HTTPX SSE 客户端库版本控制 (dingtalk_client 依赖)
    # paddlex[ocr] 精确表格识别依赖
    ("paddlex",        "paddlex",        "3.7.1",        "paddlex[ocr]"),  # PaddleX 开发套件包及其依赖控制
    # 签字格标记分类依赖
    ("scikit-image",   "skimage",        "0.22.0",       "scikit-image"),  # skimage 用于骨架化分类
    ("scipy",          "scipy",          "1.15.0",       "scipy"),         # scipy 用于连通域标记
]  # 结束列表定义

# paddlepaddle 支持 CPU 版 (paddlepaddle) 和 GPU 版 (paddlepaddle-gpu) 两种安装方式
_PADDLE_MIN_VER = "3.3.1"  # 要求的 PaddlePaddle 最低版本号
_PADDLE_PKGS = ["paddlepaddle-gpu", "paddlepaddle"]  # GPU 版优先检测，其次 CPU 版


def _ver_tuple(v: str) -> tuple:  # 将版本号字符串拆解为可对比的数字元组，如 '2.13.4' -> (2, 13, 4)
    """'2.13.4' -> (2, 13, 4)，忽略后缀如 .dev0 / rc1"""
    parts = []  # 初始化行部分数字列表
    for p in v.split("."):  # 按照版本中的点号 "." 进行分割
        digits = "".join(c for c in p if c.isdigit())  # 剥离去除包含 dev/rc 等非数字字符，只保留数字
        parts.append(int(digits) if digits else 0)  # 如果存在数字，强转为整型放入列表，否则放 0
    return tuple(parts)  # 转换为只读的元组格式并返回，方便直接对比大小


def _ver_str(t: tuple) -> str:  # 将版本元组还原为展示性的点分隔字符串格式
    """(3, 13, 0) -> '3.13.0'"""
    return ".".join(map(str, t[:3]))  # 截取元组前三项并将其转为字符，最后使用点号 "." 进行拼接返回


def check_dependencies():  # 核心依赖检查与报错诊断主函数
    """检查所有依赖版本，不满足则打印诊断并强制退出。"""

    errors: list[str] = []  # 初始化错误诊断消息列表，用于暂存不合规项
    details: list[tuple[str, str, str, bool]] = []  # 初始化详细诊断列表，格式为 (依赖名, 已安装版本, 目标版本, 是否OK)

    # 1) Python 版本
    py_cur = sys.version_info[:3]  # 获取当前解释器环境的主版本、次版本和修订版号元组
    py_ok = py_cur >= _PY_MIN  # 比较判断当前 Python 版本是否达到或超过设定的最低主版本要求
    details.append((  # 将 Python 校验详情保存到详细诊断容器中
        "Python",  # 第一项：依赖名称
        _ver_str(py_cur),  # 第二项：当前已安装的版本
        _ver_str(_PY_MIN),  # 第三项：系统要求的版本
        py_ok,  # 第四项：判定状态
    ))  # 结束添加元组
    if not py_ok:  # 如果 Python 版本不符合要求
        errors.append(f"Python {_ver_str(_PY_MIN)}+ required, got {_ver_str(py_cur)}")  # 记录当前 Python 版本冲突错误消息

    # 2) 第三方包
    for pip_name, import_name, min_ver, install_name in _DEPS:  # 循环迭代校验配置包元数据列表
        try:  # 开启检查保护
            installed = _meta.version(pip_name)  # 使用 importlib 元数据读取模块尝试读取该第三方包的已安装版本号
        except _meta.PackageNotFoundError:  # 捕获包未安装的报错异常
            details.append((install_name, "未安装", min_ver, False))  # 保存该依赖为未安装状态的对照条目
            errors.append(f"{install_name} not installed (need >= {min_ver})")  # 记录包缺失对应的错误诊断信息
            continue  # 跳过当前包的后续对比，进入下一个依赖校验
        ok = _ver_tuple(installed) >= _ver_tuple(min_ver)  # 转换并比较数字元组，得出版本大小是否合格的布尔状态
        details.append((install_name, installed, min_ver, ok))  # 保存该第三方包的详细版本状态对照条目
        if not ok:  # 如果发现版本太低落后于要求
            errors.append(f"{install_name} {installed} is outdated (need >= {min_ver})")  # 记录该包需要升级的错误诊断信息

    # 3) PaddlePaddle 特殊校验：支持 paddlepaddle (CPU) 或 paddlepaddle-gpu (GPU)
    paddle_installed = None  # 初始化已安装的 PaddlePaddle 版本为空
    paddle_variant = None  # 初始化已安装的包名变体为空
    for pkg in _PADDLE_PKGS:  # 按优先级依次检测 GPU 版和 CPU 版
        try:  # 尝试读取包版本
            paddle_installed = _meta.version(pkg)  # 获取该变体的已安装版本号
            paddle_variant = pkg  # 记录检测到的包名
            break  # 找到即停止
        except _meta.PackageNotFoundError:  # 若该变体未安装
            continue  # 继续检测下一个变体
    if paddle_installed:  # 若检测到已安装的 PaddlePaddle
        paddle_ok = _ver_tuple(paddle_installed) >= _ver_tuple(_PADDLE_MIN_VER)  # 对比版本号是否达标
        paddle_label = f"{paddle_variant} ({'GPU' if 'gpu' in paddle_variant else 'CPU'})"  # 构建显示标签，标注 GPU/CPU 变体
        details.append((paddle_label, paddle_installed, _PADDLE_MIN_VER, paddle_ok))  # 保存校验详情
        if not paddle_ok:  # 若版本过低
            errors.append(f"{paddle_variant} {paddle_installed} is outdated (need >= {_PADDLE_MIN_VER})")  # 记录错误
    else:  # 若两种变体均未安装
        details.append(("paddlepaddle", "未安装", _PADDLE_MIN_VER, False))  # 标记未安装
        errors.append(f"paddlepaddle not installed (need >= {_PADDLE_MIN_VER}), install paddlepaddle or paddlepaddle-gpu")  # 记录缺失

    # 4) 动态扫描本程序所有 .py 文件引用的依赖，进行全量防漏检检查
    import ast
    import glob
    import importlib

    project_dir = os.path.dirname(os.path.abspath(__file__))
    local_py_files = glob.glob(os.path.join(project_dir, "*.py"))
    local_modules = {os.path.splitext(os.path.basename(f))[0] for f in local_py_files}

    known_import_names = {d[1] for d in _DEPS}
    known_import_names.add("paddle")
    known_import_names.add("importlib")

    dynamic_imports = set()
    for py_file in local_py_files:
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=py_file)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        dynamic_imports.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        dynamic_imports.add(node.module.split('.')[0])
        except Exception:
            pass

    stdlib = sys.stdlib_module_names if hasattr(sys, "stdlib_module_names") else set()
    unknown_imports = dynamic_imports - stdlib - local_modules - known_import_names

    for mod_name in unknown_imports:
        try:
            importlib.import_module(mod_name)
            details.append((f"{mod_name} (动态扫描)", "已安装", "动态发现", True))
        except ImportError:
            details.append((f"{mod_name} (动态扫描)", "未安装", "动态发现", False))
            errors.append(f"Dynamic dependency '{mod_name}' is imported in code but not installed.")
            
    # 5) 检查需要用到的核心模型库 (PaddleOCR Models)
    model_dir = os.path.join(os.path.expanduser("~"), ".paddleocr", "whl")
    for m_type in ["det", "rec", "cls"]:
        m_path = os.path.join(model_dir, m_type)
        m_label = f"OCR Model ({m_type})"
        if os.path.exists(m_path) and os.listdir(m_path):
            details.append((m_label, "已就绪", "本地缓存", True))
        else:
            # 模型库缺失不作为致命错误（会在运行时自动下载），但会在列表提示
            details.append((m_label, "待下载", "运行时下载", True))

    # ---- 打印版本对照表 ----
    print()  # 打印空行以对齐排版
    print("=" * 60)  # 打印上边框分隔符
    print("  Security Supervisor - Startup Check")  # 打印启动依赖自检程序的说明标题
    print("=" * 60)  # 打印内部线分隔符
    print()  # 打印空行
    print(f"  {'项目':<20} {'当前版本':<16} {'要求版本':<12} {'状态'}")  # 打印展示对照表的头部标题栏
    print(f"  {'─' * 20} {'─' * 16} {'─' * 12} {'─' * 6}")  # 打印表头底部分隔横线
    for name, installed, required, ok in details:  # 迭代所有采集的校验结果详情
        status = "OK" if ok else "FAIL"  # 确定在表格中的状态标签是绿色的 OK 还是红色的 FAIL
        print(f"  {name:<20} {installed:<16} {required:<12} {status}")  # 打印单行依赖的版本与判定对照数据结果
    print()  # 打印底部空行

    if not errors:  # 如果没有收集到任何不合规的错误信息
        print("  All checks passed.")  # 打印检测全部合格通过的提示语
        print("=" * 60)  # 打印底部线分隔符
        print()  # 打印空行以隔离输出
        return  # 直接返回，允许应用正常启动流程

    # ---- 打印诊断信息 ----
    failed = len(errors)  # 统计发生错误的依赖项目数量
    passed = len(details) - failed  # 统计检测通过的依赖项目数量
    print(f"  Result: {passed}/{len(details)} passed, {failed} FAILED")  # 输出总体的通过和失败率统计信息
    print("=" * 60)  # 打印诊断头部线
    print()  # 打印隔离空行
    _MIRROR = "-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"  # 设置默认的清华大源镜像地址与受信地址参数
    print("  Fix with:")  # 打印指导修复命令行头部
    print(f"    pip install --upgrade {_MIRROR} \\")  # 打印建议的升级命令主体及镜像源配置
    pkgs = [f"      {d[3]}>={d[2]}" for d in _DEPS]  # 拼接构建升级具体的包及其指定最低版本号列表
    print(" \\\n".join(pkgs))  # 将包数组以换行符和反斜杠续行连接拼接打印在终端上
    print()  # 打印空行
    print("  Or run:")  # 打印第二种一键升级的引导方法标题
    print(f"    pip install --upgrade {_MIRROR} -r requirements.txt")  # 打印一键从要求依赖文件 requirements.txt 进行镜像升级的命令
    print("=" * 60)  # 打印诊断程序底部装饰线
    print()  # 打印隔离空行
    sys.exit(1)  # 阻断阻止后续主程序的加载启动，强行抛出退出状态码为 1


# 导入即执行（环境变量防重复：Streamlit 多进程共享同一标记）
if not os.environ.get("_CHECK_DEPS_DONE"):  # 检测环境变量中是否尚未含有已校验通过的标记
    check_dependencies()  # 若没有标记，则首次执行依赖校验流程并检查各个版本号
    os.environ["_CHECK_DEPS_DONE"] = "1"  # 校验通过且成功后，将环境变量标记设置为 "1" 避免二次重复校验输出
