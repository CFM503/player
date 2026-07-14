# 安全数字监督员 — 项目说明

## 一、项目功能清单

### 核心功能

| 功能 | 说明 | 实现模块 |
|------|------|---------|
| 手机拍照上传 | 支持手机端调用摄像头拍照，PC端选择文件 | `frontend.py` st.camera_input / st.file_uploader |
| 上传进度条 | 选择文件后 0%→100% 进度动画，完成后处理按钮才可用 | `frontend.py` |
| 图像预处理 | OpenCV CLAHE 去阴影 + 自适应二值化，适配一线光照条件 | `agent_core.py` AgentTools.preprocess_image |
| OCR 文字识别 | PaddleOCR 3.7.0 (PaddlePaddle) 识别中文手写/打印体 | `agent_core.py` AgentTools.ocr_tool |
| LLM 语义结构化 | 调用 mimo-v2.5-pro 将 OCR 文本解析为 Pydantic JSON（21个字段） | `agent_core.py` LLMBrain.extract_sheet_json |
| ReAct Agent 决策链 | 6阶段自主决策：规划→感知→推理→反思→执行→总结 | `agent_core.py` SecurityAgent |
| 反思校验+自动重试 | 校验票号/浓度/措施一致性，不通过自动让LLM重试（最多2次） | `agent_core.py` SecurityAgent._reflect |
| 审批建议生成 | LLM 生成专业审批建议，引用 GB 30871-2022 等安全标准条文 | `agent_core.py` SecurityAgent._generate_approval |
| 四级风险评估 | 重大🔴/较大🟡/一般🟡/低风险🟢，综合浓度+措施+问题评分 | `agent_core.py` SecurityAgent._assess_risk_level |
| SQLite 数据沉淀 | 结构化数据+OCR原文+审批建议+图片路径，自动迁移旧表 | `agent_core.py` AgentTools.save_to_db |
| 钉钉 AI 表格 | 检测到异常自动写入钉钉多维表 `test_demo` | `agent_core.py` AgentTools.write_dingtalk_table |

### 前端功能

| 功能 | 说明 |
|------|------|
| 三按钮上传区 | 📤上传 / 📷拍照 / ⚙️处理，统一蓝色风格 |
| 上传进度条 | 选择文件后 0%→100% 动画，完成后处理按钮亮起 |
| 黑客风格日志面板 | 绿色终端字体实时展示 Agent 思考过程 |
| 处理进度条 | 按 规划/感知/推理/反思/执行/总结 各阶段推进 |
| 预览图自动收起 | 处理完成后预览图折叠，展示结果 |
| 结果指标卡 | 票号/状态/措施/风险/浓度 5列紧凑 KPI 卡片 |
| OCR 原文表格 | OCR 结果解析为 字段/值 两列表格展示 |
| AI 数据看板 | 总票数/异常/正常/异常率 统计 + 高频问题 Top5 |
| 密码保护删除 | 删除记录需输入密码，弹窗居中显示 |
| 查看原图 | 每条记录展开后可弹窗查看原始上传照片 |
| 上次结果保持 | 刷新页面不丢失处理结果（session_state） |

---

## 二、赛道三合规性

### 赛道三原文

> 参赛团队需围绕**燃气行业或中国燃气实际业务场景**，选择具有创新性且可落地的 **AI 龙虾**应用方向，方案应聚焦**真实业务痛点**，展示 **AI 技术赋能业务**的独特思路。

### 逐条对照

| 要求 | 本项目情况 | 结论 |
|------|-----------|------|
| 燃气行业实际业务场景 | 牡丹江中燃 HSE 动火/带气/临时用电作业票巡检 | ✅ |
| 聚焦真实业务痛点 | 手制单人工录入慢(10min/张)、漏检、审批无标准 | ✅ |
| 创新性 | ReAct Agent 6阶段自主决策 + 反思校验自动重试 | ✅ |
| 可落地 | 7张真实作业票测试通过，Streamlit 一键启动 | ✅ |
| AI 技术赋能 | PaddleOCR + LLM 语义理解 + 自动化工具链 | ✅ |
| 非结构化输入→表单 | 手机照片→JSON→SQLite→钉钉，全自动 | ✅ |
| 自动生成审批意见 | LLM 生成，引用 GB 30871-2022 / AQ 3022 标准条文 | ✅ |
| 辅助决策建议 | 四级风险评估 + 高频问题排名 + 异常率统计 | ✅ |
| 降本提效 | 10分钟/张→15秒/张，效率提升40倍 | ✅ |
| 轻量化可用 | Streamlit 一键启动，手机浏览器直接用 | ✅ |
| 单人成队 | 项目为单人开发 | ✅ |

### 补充规则：开源自主智能体

> 开源自主智能体工具，可自主拆解任务，全自动执行完整业务流程的工具。

| 要求 | 本项目情况 | 结论 |
|------|-----------|------|
| 开源 | GitHub 公开仓库 | ✅ |
| 自主智能体 | ReAct Agent 6阶段决策循环 | ✅ |
| 自主拆解任务 | 自动规划5步计划，无需人工干预 | ✅ |
| 全自动执行 | 用户点1次"处理"，其余全自动 | ✅ |
| 完整业务流程 | 拍照→识别→结构化→校验→审批→预警→入库 | ✅ |

### 选题方向匹配

本项目对应赛道三 **"流程自动化与审批助手"** 方向：

> "利用 AI 龙虾理解业务场景，自动生成审批意见、辅助决策建议，或将**非结构化输入自动填入流程表单**，实现半自动化处理。"

---

## 三、依赖安装

### Python 版本

- Python 3.13+

### 必装依赖

```bash
pip install pydantic openai paddleocr opencv-python numpy requests streamlit pandas paddlepaddle -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 依赖说明

| 包名 | 版本 | 用途 |
|------|------|------|
| `pydantic` | ≥2.0 | Schema 数据校验（SecuritySheetData） |
| `openai` | ≥1.0 | LLM API 调用（OpenAI 兼容协议） |
| `paddleocr` | ≥3.7 | OCR 文字识别（中文手写/打印体） |
| `opencv-python` | ≥4.0 | 图像预处理（CLAHE 去阴影+二值化） |
| `numpy` | ≥1.0 | OpenCV 依赖 |
| `requests` | ≥2.0 | 钉钉 Webhook 推送 |
| `streamlit` | ≥1.33 | Web UI 前端框架 |
| `pandas` | ≥1.0 | 数据表格展示 |
| `paddlepaddle` | ≥3.3 | PaddleOCR 推理引擎 |

### 一键安装

```bash
pip install pydantic openai paddleocr opencv-python numpy requests streamlit pandas paddlepaddle -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 配置

编辑 `config.json`：

```json
{
  "api_key": "你的 API Key",
  "base_url": "https://api.example.com/v1",
  "model_name": "你的模型名称",
  "delete_password": "123"
}
```

### 启动

```bash
START.bat
# 或
streamlit run frontend.py
```

手机端浏览器访问 Streamlit 地址即可拍照使用。
