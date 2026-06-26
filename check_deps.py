"""
启动依赖版本检查 — 强制要求 Python 3.13+ 及所有第三方依赖为指定最低版本。
在 frontend.py 顶部 import 即可生效。
"""

import os
import sys
import importlib.metadata as _meta

# ---- Python 版本要求 ----
_PY_MIN = (3, 13, 0)

# ---- 第三方依赖: (pip包名, import名, 最低版本, 安装名) ----
_DEPS = [
    ("pydantic",       "pydantic",       "2.13.4",       "pydantic"),
    ("streamlit",      "streamlit",      "1.58.0",       "streamlit"),
    ("opencv-python",  "cv2",            "4.13.0.92",    "opencv-python"),
    ("paddleocr",      "paddleocr",      "3.7.0",        "paddleocr"),
    ("openai",         "openai",         "2.44.0",       "openai"),
    ("numpy",          "numpy",          "2.3.5",        "numpy"),
    ("pandas",         "pandas",         "3.0.3",        "pandas"),
    ("paddlepaddle",   "paddle",         "3.3.1",        "paddlepaddle"),
    ("requests",       "requests",       "2.34.2",       "requests"),
    # paddlex[ocr] 精确表格识别依赖
    ("paddlex",        "paddlex",        "3.7.1",        "paddlex[ocr]"),
]


def _ver_tuple(v: str) -> tuple:
    """'2.13.4' -> (2, 13, 4)，忽略后缀如 .dev0 / rc1"""
    parts = []
    for p in v.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _ver_str(t: tuple) -> str:
    """(3, 13, 0) -> '3.13.0'"""
    return ".".join(map(str, t[:3]))


def check_dependencies():
    """检查所有依赖版本，不满足则打印诊断并强制退出。"""

    errors: list[str] = []
    details: list[tuple[str, str, str, bool]] = []  # (name, installed, required, ok)

    # 1) Python 版本
    py_cur = sys.version_info[:3]
    py_ok = py_cur >= _PY_MIN
    details.append((
        "Python",
        _ver_str(py_cur),
        _ver_str(_PY_MIN),
        py_ok,
    ))
    if not py_ok:
        errors.append(f"Python {_ver_str(_PY_MIN)}+ required, got {_ver_str(py_cur)}")

    # 2) 第三方包
    for pip_name, import_name, min_ver, install_name in _DEPS:
        try:
            installed = _meta.version(pip_name)
        except _meta.PackageNotFoundError:
            details.append((install_name, "未安装", min_ver, False))
            errors.append(f"{install_name} not installed (need >= {min_ver})")
            continue
        ok = _ver_tuple(installed) >= _ver_tuple(min_ver)
        details.append((install_name, installed, min_ver, ok))
        if not ok:
            errors.append(f"{install_name} {installed} is outdated (need >= {min_ver})")

    # ---- 打印版本对照表 ----
    print()
    print("=" * 60)
    print("  Security Supervisor - Startup Check")
    print("=" * 60)
    print()
    print(f"  {'项目':<20} {'当前版本':<16} {'要求版本':<12} {'状态'}")
    print(f"  {'─' * 20} {'─' * 16} {'─' * 12} {'─' * 6}")
    for name, installed, required, ok in details:
        status = "OK" if ok else "FAIL"
        print(f"  {name:<20} {installed:<16} {required:<12} {status}")
    print()

    if not errors:
        print("  All checks passed.")
        print("=" * 60)
        print()
        return  # 全部通过

    # ---- 打印诊断信息 ----
    failed = len(errors)
    passed = len(details) - failed
    print(f"  Result: {passed}/{len(details)} passed, {failed} FAILED")
    print("=" * 60)
    print()
    _MIRROR = "-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
    print("  Fix with:")
    print(f"    pip install --upgrade {_MIRROR} \\")
    pkgs = [f"      {d[3]}>={d[2]}" for d in _DEPS]
    print(" \\\n".join(pkgs))
    print()
    print("  Or run:")
    print(f"    pip install --upgrade {_MIRROR} -r requirements.txt")
    print("=" * 60)
    print()
    sys.exit(1)


# 导入即执行（环境变量防重复：Streamlit 多进程共享同一标记）
if not os.environ.get("_CHECK_DEPS_DONE"):
    check_dependencies()
    os.environ["_CHECK_DEPS_DONE"] = "1"
