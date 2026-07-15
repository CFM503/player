# -*- coding: utf-8 -*-
# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
"""共享：运行时配置、构建 Agent、保存上传文件。"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Optional, Tuple


RUNTIME_CFG_KEY = "admin_runtime_cfg"


def apply_config_env(cfg: dict) -> None:
    """把配置同步到环境变量，供 Agent 内 load_config / 工具链读取。"""
    if cfg.get("api_key"):
        os.environ["ONLINE_API_KEY"] = str(cfg["api_key"])
    if cfg.get("base_url"):
        os.environ["ONLINE_BASE_URL"] = str(cfg["base_url"])
    if cfg.get("model_name"):
        os.environ["ONLINE_MODEL"] = str(cfg["model_name"])
    # 钉钉：管理页侧栏即时同步，无需先点保存
    if "dingtalk_mcp_url" in cfg:
        url = (cfg.get("dingtalk_mcp_url") or "").strip()
        if url:
            os.environ["DINGTALK_MCP_URL"] = url
        else:
            os.environ.pop("DINGTALK_MCP_URL", None)


def publish_runtime_config(cfg: dict) -> None:
    """管理页写入会话级运行时配置，用户页优先使用（与侧栏当前参数一致）。"""
    try:
        import streamlit as st
        st.session_state[RUNTIME_CFG_KEY] = dict(cfg)
    except Exception:
        pass
    apply_config_env(cfg)


def get_effective_config() -> dict:
    """
    有效参数优先级：
    1. 本会话管理页侧栏当前值（admin_runtime_cfg）
    2. config.json + 环境变量（load_config）
    """
    from agent_core import load_config

    cfg = dict(load_config() or {})
    try:
        import streamlit as st
        runtime = st.session_state.get(RUNTIME_CFG_KEY)
        if isinstance(runtime, dict) and runtime:
            cfg.update({k: v for k, v in runtime.items() if v is not None})
    except Exception:
        pass
    apply_config_env(cfg)
    return cfg


def build_agent_from_config(cfg: dict | None = None, ocr_params: dict | None = None):
    """按有效配置构建 SecurityAgent（用户页/管理页共用）。"""
    from agent_core import SecurityAgent, LLMBrain
    from ocr import merge_ocr_params

    if cfg is None:
        cfg = get_effective_config()
    else:
        apply_config_env(cfg)

    api_key = cfg.get("api_key", "")
    base_url = cfg.get("base_url", "")
    model_name = cfg.get("model_name", "")
    proxy = cfg.get("proxy", "") or ""
    ocr_engine = cfg.get("ocr_engine", "paddleocr")
    ocr_device = cfg.get("ocr_device", "gpu")
    ocr_mode = cfg.get("ocr_mode", "cluster") or "cluster"
    params = merge_ocr_params(
        ocr_params if isinstance(ocr_params, dict) else cfg.get("ocr_params")
    )

    # GPU 不可用时与管理页一致自动回退
    if ocr_device == "gpu":
        try:
            import paddle as _pd
            if not _pd.device.is_compiled_with_cuda():
                ocr_device = "cpu"
        except Exception:
            pass

    brain = LLMBrain(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        proxy=proxy,
    )
    vision_brain = None
    if ocr_engine == "vision":
        vk = cfg.get("vision_api_key") or api_key
        vu = cfg.get("vision_base_url") or base_url
        vm = cfg.get("vision_model_name") or ""
        if not vm:
            raise ValueError("视觉大模型引擎需要配置视觉模型名称（请在管理测试页配置并保存）")
        vision_brain = LLMBrain(api_key=vk, base_url=vu, model_name=vm, proxy=proxy)

    return SecurityAgent(
        brain=brain,
        ocr_mode=ocr_mode,
        ocr_engine=ocr_engine,
        ocr_device=ocr_device,
        vision_brain=vision_brain,
        ocr_params=params,
    )


def save_uploaded_bytes(file_name: str, data: bytes, upload_dir: str | None = None) -> str:
    """将上传字节写入 uploads/，返回路径。"""
    if upload_dir is None:
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    suffix = os.path.splitext(file_name)[1] or ".jpg"
    path = os.path.join(upload_dir, f"{int(time.time())}_0{suffix}")
    with open(path, "wb") as fp:
        fp.write(data)
    return path


def run_ticket(
    agent,
    image_path: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    ticket_type: str = "带气作业票",
) -> Tuple[Any, Any]:
    """执行单票分析，返回 (ocr_text, structured_data)。"""
    return agent.run(
        image_path,
        progress_callback=progress_callback,
        ticket_type=ticket_type,
    )


def config_ready(cfg: dict | None = None) -> bool:
    """是否具备跑票所需的最低配置。"""
    c = cfg if cfg is not None else get_effective_config()
    return bool(c.get("api_key"))
