# -*- coding: utf-8 -*-
"""
数字化安全监督员 — 入口路由
- /user  用户页：极简提交（默认）
- /admin 管理测试页：完整配置 / 日志 / 看板

启动: streamlit run frontend.py
     或 python run.py / START.bat
"""

import os
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="paddle")

import check_deps  # noqa: F401  # 启动依赖自检
import streamlit as st

st.set_page_config(
    page_title="数字化安全监督员",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Logo 固定在侧栏/应用最上方（导航页切换也保留）
_logo = os.path.join(os.path.dirname(__file__), "logo.png")
if os.path.exists(_logo):
    try:
        st.logo(_logo, size="large")
    except TypeError:
        st.logo(_logo)
    except Exception:
        # 旧版 Streamlit 无 st.logo 时，侧栏顶部仍可显示
        with st.sidebar:
            st.image(_logo, use_container_width=True)

user_page = st.Page(
    "user_ui.py",
    title="提交作业票",
    icon="📷",
    url_path="user",
    default=True,
)
admin_page = st.Page(
    "admin_ui.py",
    title="管理测试",
    icon="⚙️",
    url_path="admin",
)
# ocr9 → 服务生产 ocr.py 文字识别；ocr10 → 服务生产 ocr5 勾选格
train_ocr_page = st.Page(
    "train_ocr_ui.py",
    title="OCR文字训练",
    icon="🔤",
    url_path="train-ocr",
)
train_ocr5_page = st.Page(
    "train_ocr5_ui.py",
    title="OCR5勾选训练",
    icon="☑️",
    url_path="train-ocr5",
)

pg = st.navigation(
    {
        "业务": [user_page, admin_page],
        "模型训练": [train_ocr_page, train_ocr5_page],
    },
    position="sidebar",
)
pg.run()
