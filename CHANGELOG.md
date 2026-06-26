# 更新日志 (CHANGELOG)

## [3.5.3] - 2026-06-26

### 新增
- **端口冲突自动检测**：`run.py` 启动时扫描 8501–8520 端口，找到首个空闲端口启动 Streamlit，被占用时自动切换并打印提示。

## [3.5.2] - 2026-06-26

### 修复
- **Streamlit ScriptRunContext 警告**：`_ProgressSim._run` 不再在后台线程调用 Streamlit 组件回调，消除 `missing ScriptRunContext` 噪音；全局日志过滤屏蔽 PaddleX/PaddlePaddle 内部线程触发的残余警告。
- **PaddleX 推理卡顿**：`_format_table_test` / `_format_table_precise` 注入 `FLAGS_use_gpu=0` 强制 CPU 推理，避免无 CUDA 环境下 GPU 初始化挂起。
- **API Key 无法保存**：侧边栏"💾 保存设置"按钮原先仅保存通知 Webhook，现同时持久化 API Key、API URL、模型名称到 `config.json`。

### 新增
- **`_Heartbeat` 推理心跳**：PaddleX 推理期间按 `HEARTBEAT_INTERVAL` 全局间隔打印存活消息（含耗时），避免长时间推理看起来像卡死；推理完成/失败打印耗时和结果数。
- **模型加载与推理分离**：`_format_table_precise` 将 `create_pipeline` 和 `list(pipe(...))` 拆分到独立 try 块，模型加载失败和推理失败分别报错并回退坐标聚类。

## [3.5.1] - 2026-06-25

### 修复
- **test/precise 模式 `progress_callback` 未传递**：`ocr_tool` 调用 `_format_table_test` 时漏传 `progress_callback`，导致内部所有进度回调和 UI 更新失效，用户看到进度条卡住不动。同时去掉 `ocr_tool` 中 `precise`/`test` 模式多余的外层 `_ProgressSim` 包装。
- **Web UI 日志面板无时间戳**：`hlog()` 函数新增 `[MM:SS]` 前缀，Web UI 日志面板和 CLI 终端同步显示计时。
- **Windows Ctrl+C 无效**：`START.bat` 改用 `run.py` 启动，通过 `subprocess.Popen` + `KeyboardInterrupt` 处理正确终止 Streamlit 进程。

### 变更
- **心跳间隔参数化**：文件头新增 `HEARTBEAT_INTERVAL = 30` 全局配置，阻塞操作期间每 N 秒打印一条存活消息，设为 0 禁用心跳。`_ProgressSim.start()` 始终启动线程，`callback=None` 时仅打印心跳不更新 UI。

## [3.5.0] - 2026-06-25

### 新增
- **测试模式高精度三步还原**：第 6 种 OCR 模式重构为独立流水线，PaddleStructure 表格识别分三步（模型加载→结构推理→LLM 高精度还原），每步独立进度模拟，LLM 调用增加 `timeout=120` 超时保护。
- **OCR 进度百分比 + 计时**：`SecurityAgent` 支持 `progress_callback` 回调，`_ProgressSim` 后台线程在阻塞操作期间模拟渐进进度，Web UI 和 CLI 终端同步显示 `[MM:SS]` 时间戳 + 百分比进度条。
- **CLI 终端日志同步**：`Cap` 类拦截的 Agent 日志同时输出到 CLI stderr，运行 `streamlit run frontend.py` 的终端可实时看到 OCR 处理进度。
- **依赖版本对照表**：`check_deps.py` 启动时打印版本对照表（当前 vs 要求），显示通过/失败状态，修复命令中 `paddlex` 显示为 `paddlex[ocr]`。
- **Python 版本前置校验**：`START.bat` 在依赖检查前校验 Python ≥ 3.13，不满足时提示当前版本号并退出。
- **国内镜像源**：PaddleX 模型下载注入百度 BOS 国内镜像环境变量（`PADDLE_PDX_SOURCE_HOME`、`PADDLEX_PDX_MODEL_SOURCE`）。
- **配置模板**：新增 `config.example.json` 配置模板文件。

### 变更
- **`_ProgressSim` 空回调安全处理**：`progress_callback=None` 时不再启动线程，`done()` 安全跳过回调调用。
- **Streamlit API 更新**：`use_container_width=True` 全部替换为 `width="stretch"`（12 处），消除弃用警告。
- **`START.bat` 错误提示优化**：表格模型下载失败时提示 `pip install "paddlex[ocr]>=3.7.1"` 安装命令。

## [3.4.2] - 2026-06-25

### 新增
- **测试模式**：新增第 6 种 OCR 表格模式 `测试模式`，复制精确表格识别逻辑，用于调试。
- **OCR 原文直显**：「📝 OCR 识别原文」模块改为显示 PaddleOCR 原始识别文本（带行号），不再做字段解析加工。

### 变更
- **OCR 截断上限提升**：`OCR_TEXT_MAX_CHARS` 从硬编码 2000 提升至 4000，定义为文件头常量，避免长文本票号安全措施被截断丢失。

## [3.4.1] - 2026-06-25

### 文档
- **README 全面更新**：版本号升至 v3.4.0，新增"软件特点"章节（自主决策、五种 OCR 模式、端到端闭环、双通道预警、启动校验、国内镜像），技术栈表格补充 PaddleStructure/SLANet_plus/PP-DocLayout-L/Pandas/双通道通知/依赖管理/推理引擎，快速启动更新为 requirements.txt + config.json 新格式，项目结构补充 check_deps.py/requirements.txt/components.py/styles.py。
- **CHANGELOG 补充**：v3.4.0 补充企业微信/钉钉推送改为 config.json 读取及异常捕获修复记录。

## [3.4.0] - 2026-06-25

### 新增
- **精确表格识别模式**：新增第 5 种 OCR 表格模式 `精确表格识别（PaddleStructure）`，基于 PaddleX `table_recognition` 流水线（PP-DocLayout-L 版面检测 + SLANet_plus 表格结构识别 + PP-OCRv4_server 文字识别），输出带 colspan/rowspan 的 HTML 后由 LLM 精排为标准 Markdown 表格，支持合并单元格、手写签名、勾选状态还原。
- **精确模式启动预检**：`check_deps.py` 新增 `paddlex`、`scikit-learn`、`tiktoken`、`sentencepiece` 依赖校验；`START.bat` 新增表格识别模型（`SLANet_plus`）缓存检查与自动下载。

### 变更
- **Streamlit API 更新**：`st.components.v1.html()` 已废弃，替换为 `st.html(unsafe_allow_javascript=True)`。

### 修复
- **企业微信/钉钉推送改为 config.json 读取**：`send_wechat_alert()` 从环境变量改为读取 `config.json`，与前端侧边栏通知设置统一。
- **企业微信/钉钉推送增加异常捕获**：网络错误时打印失败日志而非抛出异常。

## [3.3.5] - 2026-06-25

### 新增
- **启动依赖版本检查**：新增 `check_deps.py`，程序启动时强制校验 Python 3.13+ 及全部第三方依赖为最新版本，不满足则打印诊断信息并阻止启动。Streamlit 多进程通过环境变量防重复输出。
- **运行日志钉钉推送**：agent `_act()` 阶段新增钉钉 Webhook 自动推送（与企业微信并列），未配置时在运行日志窗口打印 ⚠️ 警告提示。
- **requirements.txt**：新增依赖声明文件，支持 `pip install --upgrade -r requirements.txt` 一键升级。
- **国内镜像安装**：所有 `pip install` 命令统一使用清华镜像源 `pypi.tuna.tsinghua.edu.cn`。

### 变更
- **OCR 引擎切换**：从 onnxruntime 切换为 PaddlePaddle 推理引擎，全项目 8 处更新（agent_core / check_deps / requirements / START.bat / 文档）。
- **numpy 版本锁定**：从 1.26.4 升级至 2.3.5（满足 paddlex `>=1.24,<2.4` 约束）。
- **依赖全量升级**：pydantic 2.13.4、opencv-python 4.13.0.92、openai 2.44.0、pandas 3.0.3、paddlepaddle 3.3.1、requests 2.34.2。
- **企业微信推送改为 config.json 读取**：`send_wechat_alert()` 从环境变量 `WECHAT_WEBHOOK_URL` 改为读取 `config.json` 的 `wechat_webhook` 字段，与前端侧边栏设置统一。
- **企业微信/钉钉推送增加异常捕获**：网络错误时打印失败日志而非抛出异常。

### 修复
- **PaddlePaddle PIR+OneDNN 兼容**：修复 `ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` 错误，通过强制禁用 `enable_new_ir` 并降低优化等级。
- **START.bat paddle 导入名**：`import paddlepaddle` 修正为 `import paddle`。

## [3.3.4] - 2026-06-25

### 修复
- **侧边栏折叠与展开功能兼容性修复**：
  - 修复了在 Streamlit 1.58+ 中侧边栏折叠后，左上角展开按钮不显示且无法正常展起的兼容性问题。
  - **原因**：Streamlit 1.58 把侧边栏展开按钮更名为了 `stExpandSidebarButton` 且移入了顶部工具栏 `header [data-testid="stToolbar"]`。而我们先前的 CSS 直接 `display: none` 隐藏了整个工具栏，从而让展开按钮一同被销毁了。
  - **解决**：改写 [styles.py](file:///d:/SOFT/AI/github/player/styles.py) 使工具栏框架显示并设为不阻挡页面点击的 `pointer-events: none`，利用 CSS 精准隐藏工具栏内非侧边栏控制器的多余按钮；将展开按钮 CSS 样式及 [frontend.py](file:///d:/SOFT/AI/github/player/frontend.py) 的 JS 辅助点击选择器均从 `stSidebarCollapsedControl` 升级为新的 `stExpandSidebarButton`。
- **恢复侧边栏 OCR 表格模式选择**：
  - 修复了此前在重构中意外遗失的 `📋 OCR 表格模式` 侧边栏选择器，恢复了其渲染并将选中的模式传递给 `SecurityAgent` 以保证各 OCR 识别策略正常运转。

## [3.3.3] - 2026-06-24

### 新增
- **OCR 四种表格识别模式**：侧边栏新增 `📋 OCR 表格模式` 选择器，支持四种基于 PaddleOCR 的表格处理策略：
  - **坐标聚类**（默认）：基于文字 bounding box 的 Y 间隙分行、X 排序，用 `|` 分隔列。
  - **精细网格**：X 坐标聚类自动识别列边界，按列对齐输出，适合列数较多的表格。
  - **自适应边框检测**：OpenCV 形态学运算检测表格水平/垂直线段，找到行列分割点后按单元格组织文本，适合有边框的标准表格。
  - **多方向检测**：分离水平和垂直排列的文本，分别聚类处理，适合含竖排文字的表格。

### 优化
- **OCR 表格结构化输出**：`ocr_tool` 输出格式从扁平文本升级为表格结构化文本（`|` 分隔行列），末尾附带纯文本版本供下游正则兜底匹配。
- **日志面板与进度条布局修复**：将 `status_text` 和 `progress` 移至分栏上方独立占行，解决 `.hlog` 日志面板与 `stCaptionContainer` 的视觉重叠问题。
- **OCR 引擎统一**：所有模式均基于 `PaddleOCR(lang="ch")`，使用 PaddlePaddle 推理引擎。

## [3.3.2] - 2026-06-24

### 修复
- **侧边栏展开/折叠功能修复**：
  - 修复了点击折叠侧边栏后，右上角的展开按钮消失且无法重新展开侧边栏的问题。
  - **原因**：之前的 CSS 使用了全局 `header { display: none !important; }` 隐藏顶部状态栏，导致位于 `header` 节点内部的侧边栏展开按钮一同被完全销毁。
  - **解决方法**：移除对 `header` 容器的全局隐藏样式，使 `header` 容器恢复默认可见（但背景设为 `transparent` 保持隐形）。转而使用精准的 CSS 选择器（如 `.stAppDeployButton`, `.stDeployButton`, `[data-testid="stHeaderActionElements"]`, `[data-testid="stStatusWidget"]`）仅定向隐藏主菜单、发布按钮和状态组件。这使得侧边栏展开/折叠按钮可以完全不受影响地按 Streamlit 原生层级正常渲染，完美解决了折叠后看不见或无法点击展开按钮的问题。

### 优化
- **指标卡高度对齐与自适应文本换行**：
  - 针对在多列布局（如5列）中，由于指标值（如多条浓度记录或过长票号）或指标名称长短不一导致卡片高度参差不齐的问题，为 `.kpi` 指标卡加入了 `flex` 纵向对齐布局以及 `min-height: 96px` 最小高度限制。
  - 为 `.kpi-val` 与 `.kpi-lbl` 加入了 `word-break: break-word !important;` 规则，确保超出宽度的字符能自动换行，保持整体排版整齐。
- **日志面板（Log）滚动限制**：
  - 修复了 `.hlog` 终端日志面板在日志条数变多时会无限向下延伸并撑开页面滚动的缺陷。
  - 为其限制了最大高度 `max-height: 400px !important;`，超出时自动在面板内部滚动，保持页面布局紧凑。
- **布局列（st.columns）垂直居中对齐**：
  - 移除此前为了垂直对齐而硬编码的 CSS 占位标签（如 `<div style='padding-top:18px'></div>` 与 `padding-top:35px`）。
  - 利用 Streamlit 新版原生提供的 `vertical_alignment="center"` 参数，使行内各组件（如记录折叠面板与右侧的删除 `🗑️` 按钮、搜索输入框与搜索按钮、预览缩略图与文字）实现优雅的垂直居中对齐。

### 变更
- **移除拍照（Camera）功能**：
  - 移除了首页的 **📷 拍照** 按钮，将操作按钮布局从 3 列缩减为 2 列（`上传` 和 `处理`）。
  - 删除了 `st.camera_input("拍照上传")` 相关逻辑代码及 `show_camera` 的 Session State 状态机变量。
  - 清理了 CSS 中针对 `[data-testid="stCameraInput"]` 的样式定义。
  - 更新了引导步骤说明（Guide Box）和空白状态提示（Empty State），移除了与相机拍摄相关的全部文本说明。
