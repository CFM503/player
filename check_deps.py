"""
启动依赖版本检查 — 强制要求 Python 3.13+ 及所有第三方依赖为最新版本。
在 frontend.py 顶部 import 即可生效。
"""

import os
import sys
import importlib.metadata as _meta

# ---- Python 版本要求 ----
_PY_MIN = (3, 13, 0)

# ---- 第三方依赖: (pip包名, import名, 最低版本) ----
# 版本号 = PyPI 上 Python 3.13 最新稳定版 (2026-06-25 查询)
_DEPS = [
    ("pydantic",       "pydantic",       "2.13.4"),
    ("streamlit",      "streamlit",      "1.58.0"),
    ("opencv-python",  "cv2",            "4.13.0.92"),
    ("paddleocr",      "paddleocr",      "3.7.0"),
    ("openai",         "openai",         "2.44.0"),
    ("numpy",          "numpy",          "2.3.5"),
    ("pandas",         "pandas",         "3.0.3"),
    ("paddlepaddle",   "paddle",         "3.3.1"),
    ("requests",       "requests",       "2.34.2"),
    # paddlex[ocr] 精确表格识别依赖
    ("paddlex",        "paddlex",        "3.7.1"),
    ("scikit-learn",   "sklearn",        "1.9.0"),
    ("tiktoken",       "tiktoken",       "0.13.0"),
    ("sentencepiece",  "sentencepiece",  "0.2.1"),
]


def _ver_tuple(v: str) -> tuple:
    """'2.13.4' -> (2, 13, 4)，忽略后缀如 .dev0 / rc1"""
    parts = []
    for p in v.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_dependencies():
    """检查所有依赖版本，不满足则打印诊断并强制退出。"""

    errors: list[str] = []

    # 1) Python 版本
    if sys.version_info < _PY_MIN:
        cur = ".".join(map(str, sys.version_info[:3]))
        need = ".".join(map(str, _PY_MIN))
        errors.append(f"Python {need}+ required, got {cur}")

    # 2) 第三方包
    for pip_name, import_name, min_ver in _DEPS:
        try:
            installed = _meta.version(pip_name)
        except _meta.PackageNotFoundError:
            errors.append(f"{pip_name} not installed (need >= {min_ver})")
            continue
        if _ver_tuple(installed) < _ver_tuple(min_ver):
            errors.append(
                f"{pip_name} {installed} is outdated (need >= {min_ver})"
            )

    if not errors:
        return  # 全部通过

    # ---- 打印诊断信息 ----
    print()
    print("=" * 56)
    print("  Dependency check FAILED")
    print("=" * 56)
    for e in errors:
        print(f"  [X] {e}")
    print()
    _MIRROR = "-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
    print("  Fix with:")
    print(f"    pip install --upgrade {_MIRROR} \\")
    pkgs = [f"      {d[0]}>={d[2]}" for d in _DEPS]
    print(" \\\n".join(pkgs))
    print()
    print("  Or run:")
    print(f"    pip install --upgrade {_MIRROR} -r requirements.txt")
    print("=" * 56)
    print()
    sys.exit(1)


# 导入即执行（环境变量防重复：Streamlit 多进程共享同一标记）
if not os.environ.get("_CHECK_DEPS_DONE"):
    check_dependencies()
    os.environ["_CHECK_DEPS_DONE"] = "1"
