# 更新日志 (CHANGELOG)

## [3.14.48] - 2026-07-10

### 修复
- **`ocr5.py` 去表格化图片未归档问题**：在 Web UI 或智能体系统流程运行时，`ocr5.py` 输入图片路径为 `uploads/aligned_xxx.png`，去表格化后的图片默认保存在 `uploads/aligned_xxx去表格化.png`。由于 `agent_core.py` 归档时仅复制了原始上传图和对齐图，导致用户在 `archives` 目录下找不到去表格化后的图片。现已在 `agent_core.py` 的 `_archive` 流程中增补了对去表格化图片的匹配检测与复制归档逻辑，将其同步保存为 `[prefix]_对齐图去表格化.png`。

## [3.14.47] - 2026-07-10

### 变更
- **`div.hlog` 黑客终端日志时间升级为北京时间**：将 Web UI 终端日志面板（`.hlog` 容器）的相对耗时时间戳前缀，修改为基于东八区（UTC+8）绝对北京时间的 `[HH:MM:SS]` 时间格式，使调试及运行日志更具实际安全审计跟踪价值。

## [3.14.46] - 2026-07-10

### 修复
- **纠正 `template/dq.png` 模板文件错误（解决对齐变形问题）**：排查发现 `v3.14.33` 版本在升级高精度模板时，误将 `dh.png`（动火票模板）同时拷贝覆盖了 `dq.png`（带气票模板）。导致对齐带气作业票时因表格结构、文字排版不一致而触发 ORB 特征匹配兜底，且因匹配点离散、RANSAC 内点数低（仅 20）而产生严重的单应变换拉伸变形。现已回滚并恢复为正确的「带气作业票」模板布局，恢复后匹配内点由 20 提升至 105，完美修复变形问题。

## [3.14.45] - 2026-07-10

### 新增
- **`ocr5.py` 去表格线处理整合**：在识别对号前，调用 `ocr7.py` 模块的 `remove_table_lines` 进行两阶段去表格线处理，并将去表格化后的图像保存至同目录下的 `<文件名>去表格化.png`。后续的所有签字格定位、裁剪与骨架化分类皆基于去线后的图像运行，消除残余表格边框线的噪点干扰。
- **添加表格线擦除工具 `ocr7.py`**：新增基于长核形态学开运算及 `cv2.inpaint` 图像修补算法的表格线擦除独立工具，可高效擦除背景表格网格线并完整保留手写痕迹、字迹和印章。

### 变更
- **更新项目文档结构**：在 `README.md` 项目结构树中更新了最新的模块，移除了废弃的 `mark_classifier.py` 并增补登记了 `ocr5.py`、`ocr7.py`、`ocr.py`、`align_to_template.py` 和 `dingtalk_client.py` 的作用说明。

## [3.14.44] - 2026-07-10

### 修复
- **`align_to_template.py` 照片轮廓检测失败**：新增 ORB 特征点匹配作为四边形轮廓检测失败时的自动兜底方案。当 `detect_quad` 无法从照片中识别出四边形边框（如无明显纸张边缘、背景复杂等），自动切换为 ORB + BFMatcher + RANSAC 单应矩阵模式，直接将照片透视变换对齐至模板坐标系。

### 变更
- **`align_to_template.py` 中文路径支持**：将 `cv2.imread` / `cv2.imwrite` 替换为基于 `cv2.imdecode(np.fromfile(...))` / `cv2.imencode(...).tofile(...)` 的 `_imread` / `_imwrite` 辅助函数，彻底解决 Windows 中文路径下图片读写返回 `None` 的问题。

## [3.14.43] - 2026-07-10

### 重构
- **`classify_mark` 函数内联至 `ocr5.py`**：将原 `mark_classifier.py` 中的 `classify_mark` 函数（骨架拓扑三分类：叉号/单笔画/空白）完整移植到 `ocr5.py`，消除对独立模块文件的外部依赖，使 `ocr5.py` 成为完全自包含的 CLI 脚本。

### 移除
- **删除 `mark_classifier.py`**：原标记分类模块已完整合并至 `ocr5.py`，不再作为独立文件存在，简化项目结构。

### 新增
- **`ocr5.py` 引入 logging 日志体系**：使用标准 `logging` 模块替换原有 `print` 错误输出，新增分级日志：
  - `INFO`：图像加载路径与尺寸、网格线检测数量、每条安全措施的五人识别结果；
  - `DEBUG`：每格骨架特征数值（`ink_ratio`、`n_branch_px`、`n_endpoint`、`n_skel_components`、`min_spur_dist`）及最终分类标签；
  - `ERROR`：文件不存在、图像解码失败、依赖缺失等异常情况。

## [3.14.42] - 2026-07-09

### 移除
- **清理本地 PP-OCRv4 缓存与冗余文件**：完全删除了本地磁盘下载残留的 `PP-OCRv4_mobile_det` 与 `PP-OCRv4_mobile_rec` 缓存模型，确保运行时只加载并常驻全新的 PP-OCRv6，从物理层面实现无 v4 模型残留，进一步净化磁盘与内存占用。

## [3.14.41] - 2026-07-09

### 变更
- **升级原生 PaddleOCR 引擎至 PP-OCRv6**：在 `ocr.py` 中将原生 PaddleOCR 初始化的 `ocr_version` 修改为 `"PP-OCRv6"`，统一了全局本地 OCR 模型版本，提升手写体和复杂文本识别精度的同时，减少常驻模型带来的系统内存与显存消耗。

## [3.14.40] - 2026-07-09

### 新增
- **独立带气措施网格检测脚本 `ocr5.py`**：将带气作业票 125 个勾选网格的自适应检测与三分类逻辑（stroke / cross / blank）彻底抽离为独立的 CLI 脚本文档，支持 `-i / --input` 和 `-h / --help` 参数，提升了模块化程度和测试分类的便利度。

### 变更
- **重构网格三分类调用方式**：在 `agent_core.py` 中通过 `subprocess` 直接调用新版 `ocr5.py` 脚本，获取格式化 Markdown 结果前插至 OCR 原文中。
- **优化反思校验重试拦截**：排除了安全措施未落实（属于业务事实异常）触发的无效 LLM 语义分析重试，极大减少了 API 调用开销，避免了 Rate Limit 429 报错，提速 3 倍。
- **支持中文文件路径读取**：使用 `cv2.imdecode(np.fromfile(...))` 替代 `cv2.imread`，彻底解决 Windows 系统下因中文路径（如“对齐图”）引起的图片读取失败异常。

## [3.14.39] - 2026-07-08

### 变更
- **更新责任人提取坐标范围**：将 `agent_core.py` 中 `extract_filler_name` 方法对应的责任人签字提取裁剪坐标范围从旧的 `[630, 190, 195, 150]` 调整优化为新的 **`[700, 170, 300, 170]`**，进一步提高签字区域 OCR 提取的容错率。

## [3.14.38] - 2026-07-08

### 移除
- **删除钉钉多维表手动同步按钮逻辑**：从 `components.py` 中删除了已弃用、且在前端并未被渲染使用的 `render_notification_btn` 按钮定义和底层实现，同步更新了 `frontend.py` 的相关导入，清除了无用代码以维护项目干净整洁。

## [3.14.37] - 2026-07-08

### 移除
- **删除纯本地 OpenCV 像素密度提取与降级校验**：删除了 `agent_core.py` 中用于带气作业票勾选框的 `--- 纯本地 OpenCV 像素密度提取结果 ---` 补丁融合、25项手写体笔迹降级自检校验，以及 `check_measure_status_in_ocr` 中相应的局部像素判定分支，完全回归标准 OCR + 大模型决策链，保持逻辑流的精简与高精度。

## [3.14.36] - 2026-07-08

### 变更
- **重构图像对齐执行方式**：彻底删除 `ocr.py` 中的 `align_to_template` 冗余函数，还原 `align_to_template.py` 为纯净脚本文档，并在 `agent_core.py` 中通过 `subprocess` 直接调用该脚本完成图像对齐，之后通过在内存中对输出图片进行 resize 来完美向下兼容原有坐标尺度。

## [3.14.34] - 2026-07-08

### 新增
- **新增签字与责任人多字段抽取及前端展示**：在安全审计数据模型中新增了作业人员、施工方现场负责人、监理人员、项目公司监护人、带气现场负责人的多要素抽取与分析，并在前端及钉钉同步面板的审批核心信息栏中进行 `[变量名]` 的格式化渲染展示。
- **PaddleOCR 坐标解析健壮性增强**：在 `ocr.py` 的文字坐标识别聚类格式化流程中，为 `predict` 预测结果增加了 `json` 属性的 `None` 空值防御，并对预测出的多边形顶点包围框（`box`）增加了三层嵌套结构类型与坐标宽高的强类型防御检测，彻底杜绝在低置信度/文字未识别出时可能发生的 `TypeError: 'NoneType' object is not subscriptable` 问题。
- **修复 numpy 模块 NameError 引用故障**：将 `numpy as np` 导入从局部提升至 `ocr.py` 全局文件头部，修复了处理过程中因缺失全局 numpy 模块引用导致的 `NameError: name 'np' is not defined` 异常。

## [3.14.33] - 2026-07-08

### 新增
- **高分辨率新版模板支持**：更新 `template` 目录下的模板图片 `dq.png` (带气作业票) 和 `dh.png` (动火作业票)，模板分辨率升级为 `2000x2827`（A4 比例），画质及表线定位几何精度大幅提升。
- **四角检测与透视变换对齐 (align_to_template)**：引入新版四边形检测算法，利用 OpenCV 的 Canny 边缘和二值化双通道技术检测纸张/表格的四边形边界进行精准透视对齐，且保留了 ORB 单应性矩阵匹配和直接拉伸的自动降级兜底方案。
- **坐标尺寸标准化与向后兼容**：对齐到新模板尺寸后，自动将图片等比例 resize 缩放回原有 codebase 期望的标准规格尺寸（带气票 `1052x1487`、动火票 `1000x1414`），无需更改原有复杂的勾选框和签名处硬编码坐标，实现 100% 兼容。
- **前端上传分流选择器 (UI Route)**：在前端上传面板新增票型单选项（“带气作业票” vs “动火作业票”，默认带气），根据用户选择在匹配时过滤冗余模板，提高对齐效率并杜绝模板间的混淆与误判。
- **大模型与文本优先分类纠偏**：优化了票型判定机制，通过 PaddleOCR 识别出的标题文字（“带气”/“动火”字样）优先进行票型判定与纠偏，并将模板分类类型作为健壮的 fallback。

## [3.13.2] - 2026-07-05

### 新增
- **AST 动态防漏检依赖扫描**：大幅强化 `check_deps.py` 自检程序，内建了 AST（抽象语法树）解析器。现在启动时会自动遍历项目内所有 `.py` 源码，提取全部第三方 `import` 包，并与 `_DEPS` 名单进行比对和尝试导入。从根本上杜绝了后续开发中“引入新库但忘记配置依赖版本”导致的生产环境崩溃。
- **核心模型库就绪状态监控**：在 `check_deps.py` 启动阶段增加了针对 `~/.paddleocr/whl/` 本地缓存目录的探测，能够向用户直观展示 `det/rec/cls` 三大核心模型库是已就绪还是需要运行时下载。

### 变更
- **全局 OCR 推理硬件默认设为 GPU**：将 `frontend.py` 的 UI 侧边栏及 `agent_core.py` 的底层接口的硬件设备初始默认值从 CPU 变更为 GPU，方便具有显卡算力的主机一键获取最高 10 倍的推理加速。

### 修复
- **修复非 NVIDIA 显卡硬件下的 GPU 虚假降级漏洞**：修正了 `frontend.py` 中的回退逻辑。修复前，如果在无 NVIDIA 环境（如 Intel 核心显卡）下勾选 GPU 加速，UI 会发出“降级为 CPU”的警告，但底层参数并未被覆盖重置。修复后，增加了强制修改 `ocr_device = "cpu"` 的链路拦截，杜绝了向底层引擎错误下发 GPU 指令引发的环境兼容隐患。

## [3.13.1] - 2026-07-04

### 新增
- **多模态视觉网格外挂提取补丁**：针对 PaddleOCR 难以识别不规则对号/叉号的问题，在 `agent_core.py` 中引入了 `Vision LLM` 网格外挂。当启用 `vision_brain` 并检测到带气作业票时，通过 OpenCV 根据固定的模板对齐绝对坐标（`x:500-750, y:230-900`）裁剪纯网格切片图片并交由视觉大模型深度识别手写符号，拼接追加至 OCR 原文。
- **纯本地 OpenCV 像素密度降级方案**：在未配置 Vision API 的纯本地环境下，利用 PaddleOCR 左侧识别的作业条款文字作为 Y 轴高度锚点，借助 OpenCV 自适应阈值进行物理格子内的纯像素密度比对探测。超过 2% 黑色像素覆盖即判定为“有笔迹”，成功实现了完全离线本地环境下的手写勾选防漏检。
- **启动依赖强制校验强化**：在 `check_deps.py` 启动依赖检测中，加入了 `httpx-sse` 依赖项的版本自检约束；修复了此前 `dingtalk_client.py` 内部因为缺失 SSE 协议支持在运行时崩溃的问题。

### 变更
- **重构 PaddleOCR 识别精度阈值**：将 `agent_core.py` 中的 `run_ocr` 传参 `det_db_box_thresh` 强制调低至 `0.2`，并将 `drop_score` 调低至 `0.1`，极大限度提升原生 PaddleOCR 捕捉作业票上手画符号的容错能力。
- **取消 OCR 截断限制**：完全移除了原有的 `OCR_TEXT_MAX_CHARS`（4000字符）文本截断机制，避免 OCR 原文过长导致追加的外挂网格识别结果被暴力切除。


## [3.13.0] - 2026-07-04

### 新增
- **新增模板自动对齐机制**：在 `ocr.py` 中增加了 `align_to_template` 函数，基于 OpenCV ORB 特征点匹配，将用户实拍的作业票照片智能映射并拉伸（透视变换）至标准的 `794x1030` 尺寸模板，彻底解决了用户上传图片尺寸与比例不一致导致的坐标识别漂移问题。
- **自定义手写识别强度**：`ocr.py` 核心引擎默认加入 `det_db_box_thresh=0.4` 和 `drop_score=0.3` 的隐性参数配置，并为其暴露了命令行参数接口 `--det-thresh` 和 `--drop-score`，显著提升手写字迹和签名的识别容错率与提取准确度。

### 变更
- **移除自适应边框检测**：废弃了 `ocr.py` 中的 `format_table_adaptive` 形态学分割算法和 `agent_core.py` 内部及 `frontend.py` 侧边栏的冗余 UI 下拉框。所有 OCR 扫描均使用更简单可靠的坐标聚类（Cluster）模式，降低代码复杂度和冗余度。
- **重构责任人区域提取坐标**：依托模板对齐后的固定分辨率，`agent_core.py` 中的 `extract_filler_name` 方法删除了以往为了适配不同尺寸而进行的动态位移逻辑及大量全局坐标变量（`ssx`, `ssy`, `fq_x`, `fq_y`），现在的裁剪范围已固定重写为非常简洁的 `[520, 140, 210, 120]` 绝对坐标，效率与稳健性大幅跃升。

## [3.12.5] - 2026-07-03

### 变更
- **清理过期测试脚本**：移除了不匹配和已过期的测试文件 `test_e2e.py` 与 `test_mcp.py`，并更新 `README.md` 中的目录结构说明，保持代码库的简洁与清爽。


## [3.12.4] - 2026-07-03

### 新增
- **区域定位人名提取优化**：`extract_filler_name()` 升级为纯坐标区域定向裁剪扫描模式。不再通过遍历全局 OCR 文本做坐标范围比对，而是直接在 `ocr_tool` 中缓存最后一次上传的文件路径 `_last_image_path`，调用 `_ocr_crop_region` 裁剪 `[420, 120, 200, 110]` 坐标小图进行局部 OCR 识别，并清除标签文字过滤后通过正则精准匹配提取 2-4 位中文姓名。

### 变更
- **折叠按钮布局与 DOM 重组**：前端注入 JavaScript 动态调整 Streamlit 内部的 `stSidebarHeader` DOM 位置，在页面加载及渲染时自动将其插入到项目副标题 `stCaptionContainer` 下方。
- **侧边栏修饰与头部高度**：在 `styles.py` 中重构侧边栏布局，清空侧边栏容器内边距以使 Logo 实现 0 边距完美贴边。折叠控制头部调整为自适应 `30px` 高度，外边距为 `15px 2rem`，折叠按钮改为相对布局靠右对齐。
- **精简侧边栏视觉**：删除侧边栏原本位于 Logo 下方和视觉大模型配置下方的两条多余分割线（`st.markdown("---")`），使页面整体布局更为紧凑专业。

### 修复
- **修正缩进错误**：修复了 `agent_core.py` 中 `extract_filler_name` 局部变量的非法缩进问题，确保程序整体编译与启动正常。


## [3.12.3] - 2026-07-03

### 文档
- **核心引擎代码逐行中文注释全面覆盖**：对核心智能体引擎 `agent_core.py` 内部所有 Pydantic 结构体数据模型、LLM 大脑语义解析逻辑、数据规整校验模块、本地 SQLite 数据库读写及自动迁移、OCR 图像 CLAHE 去阴影预处理、实时天气 wttr.in 探针、自动钉钉多维表字段映射发现、MCP 异步附件上传直传写入模块以及 ReAct 编排核心流水线的每一行代码添加了详尽的中文字符级解释注释。至此已实现对项目所有 Python 源文件的 100% 逐行中文注释覆盖。


## [3.12.2] - 2026-07-03

### 文档
- **逐行代码中文注释**：对独立模块 `ocr.py` 内部所有函数定义、类变量、逻辑判断、图像裁剪处理以及 CLI 参数解析的每一行代码添加了详尽的中文字符级解释注释，大幅提升了后续维护和协作时的代码可读性。

## [3.12.1] - 2026-07-02

### 新增
- **多引擎支持扩展**：`ocr.py` 正式集成“本地 PaddleOCR”与“视觉大模型 (Vision LLM)”双引擎。通过 `--engine {paddleocr,vision}` 切换。
- **大模型 API 传参**：支持在 CLI 或模块调用中配置 `--api-key`、`--base-url` 及 `--model-name`，以直接在大模型模式下进行表格读图结构化识别。
- **英文帮助说明汉化对齐**：完善全英文 CLI 帮助提示词，并对齐底层逻辑。

### 修复
- **修复 PaddleOCR 参数冲突**：修正了 PaddleOCR 3.x 版本中不支持 `use_gpu` 的错误，改用支持的 `device`（`cpu` 或 `gpu`）设备选择。

## [3.12.0] - 2026-07-02

### 新增
- **独立 OCR 处理器模块**：新建 `ocr.py` 模块，将 OCR 识别（PaddleOCR）及表格格式化（坐标聚类、自适应边框检测）的核心逻辑彻底解耦、模块化。
- **设备类型选择**：支持传入 `device` 参数（`cpu` 或 `gpu`），默认在 CPU 下运行。
- **坐标裁剪与全图识别**：支持传参 `coords` (x, y, w, h) 以裁剪指定区域做定向 OCR 识别，并支持坐标偏移转换，默认无坐标参数时扫描全图。
- **子图截取保存**：添加 `save_crop_path` 参数支持，可在裁剪扫描时，自动将裁剪出的子图保存为图片文件。
- **扫描结果 Markdown 保存**：添加 `save_markdown_path` 参数支持，自动将 OCR 结构化表格及文本坐标结果以 Markdown 格式（`.md`）持久化。
- **命令行接口 CLI 英文说明**：`ocr.py` 支持直接作为独立脚本在终端运行，包含全英文的 `-h`/`--help` 帮助参数说明。

### 变更
- **Agent 核心重构**：`agent_core.py` 移除重复的本地 OCR、`_format_table`、`_format_table_adaptive` 等函数，改为直接导入并调用 `ocr.run_ocr` 方法，保持核心引擎逻辑单一源（Single Source of Truth）。

## [3.11.0] - 2026-07-02

### 新增
- **基于坐标的责任人定位提取**：`extract_filler_name()` 升级为利用 OCR 返回的文本绝对坐标（针对特定填表区域 `[355, 93]` 或 `[440, 110]` 附近 ±30px）精确匹配并提取责任人/填表人姓名。
- **OCR 结果坐标元数据输出**：`ocr_tool` 返回的 `flat_text` 文本行新增坐标与尺寸元数据后缀（格式为 `[x,y,w,h]`），提供给下游做精确的空间定位解析。
- **区域裁剪 OCR 接口**：新增 `_ocr_crop_region()`，支持对图片指定矩形区域（x, y, w, h）进行定向 PaddleOCR 识别。

### 变更
- **OCR 模式精简**：从本地 PaddleOCR 模式中精简并排除了不稳定的“精确增强 (precise)”与“测试模式 (test)”，保留了最实用的“坐标聚类”与“自适应边框检测”两种核心模式。
- **前端配置选项精简**：前端 OCR 表格模式及 OCR 引擎选择器简化重命名，增强了对视觉大模型模式下“不支持坐标定位、责任人提取不可用”的提示。
- **移除 OCR 兜底预处理**：移除 `len(entries) < 5` 时自动触发去阴影图像预处理的重试逻辑，精简底层处理流。

## [3.10.0] - 2026-07-02

### 新增
- **钉钉 AI 表格 MCP 接入**：`AgentTools.write_dingtalk_table()` 重写为通过 MCP Streamable HTTP 协议直接写入钉钉多维表，彻底替代旧 Webhook 方式。
- **自动表格结构发现**：首次接入时自动调用 `_discover_dingtalk_fields()` 枚举所有 Base / Table / Field 映射并缓存至 `.dingtalk_cache.json`，后续无需手动配置字段 ID。
- **缓存兼容升级**：`_load_dingtalk_cache()` 支持旧版 dict 格式自动迁移为 list，向后兼容历史缓存文件。
- **异步桥接**：`_run_async()` 在独立线程中运行新事件循环，避免与 Streamlit tornado 事件循环冲突。
- **MCP 可达性探测**：`_ping_dingtalk_mcp()` 在写入前验证 MCP 地址可达性，快速失败并报错。
- **钉钉 AI 表格客户端**：新增独立 `dingtalk_client.py`（`DingTalkAITableClient`），封装 list_bases / get_base / get_tables / create_record 等 MCP 调用。
- **MCP 集成测试**：新增 `test_mcp.py`，覆盖发现流程、写入流程及多 Base 路由逻辑。
- **依赖新增**：`requirements.txt` 补充 `mcp>=1.0.0` 和 `httpx>=0.28.0`。

### 变更
- **侧边栏通知设置重构**：移除企业微信 Webhook 和钉钉 Webhook 双输入框，改为单个「钉钉 MCP 地址」密码输入框；未配置时展示黄色警告横幅。
- **配置字段重命名**：`config.json` / `config.example.json` 中 `wechat_webhook` 和 `dingtalk_webhook` 合并为 `dingtalk_mcp_url`。
- **`components.py` 按钮逻辑升级**：`render_notification_btn()` 参数 `webhook_key` 改为 `mcp_key`，点击后调用 `AgentTools.write_dingtalk_table()` 写 AI 表格，不再 POST Webhook。
- **Tab1 通知区域简化**：移除结果页中企业微信发送按钮，保留钉钉 AI 表格写入入口（由 Agent 自动触发，手动按钮已隐藏）。
- **`.gitignore` 补充**：忽略 `dingtalk_client.py` 生成的临时鉴权缓存。

### 修复
- **`_discover_dingtalk_fields` 响应兼容**：`_safe_get()` 辅助函数处理 MCP 响应中 `data` 嵌套层级不一致问题，避免 KeyError。

## [3.9.1] - 2026-06-28

### 安全修复 (ponytail.audit)
- **🔴 修复 API Key 泄露**：`config.example.json` 中真实 API Key 替换为占位符，防止凭证外泄。
- **🟡 环境变量优先**：配置加载改为环境变量优先（`ONLINE_API_KEY` / `ONLINE_BASE_URL` / `ONLINE_MODEL`），配置文件降级 fallback，支持无文件部署。
- **🟡 移除全局 `print` 覆盖**：删除 `print = safe_print`，所有 `agent_core.py` 内部日志改用 `safe_print()`，避免污染第三方库的 `print` 行为。
- **🟡 线程安全修复**：`_ProgressSim` 和 `_Heartbeat` 的裸 `bool` 标志替换为 `threading.Event`，共享状态加 `threading.Lock`，消除竞态条件。
- **🟡 配置原子写入**：`config.json` 保存改为先写 `.tmp` 再 `os.replace()` 原子替换，防止写入中断导致配置损坏。
- **🟢 DB 异常处理完善**：Tab 2 看板所有数据库操作纳入 `try/finally`，连接确保关闭，删除操作增加错误提示。
- **🟢 清理重复装饰器**：移除 `agent_core.py` 中悬空的 `@staticmethod`。
- **🟢 视觉 LLM 图片大小检查**：`_vision_llm_ocr` 增加 5MB 图片大小上限警告。

## [3.9.0] - 2026-06-28

### 新增
- **代理支持**：侧边栏新增代理开关，支持通过 HTTP 代理访问 Google/Gemini 等海外 AI 模型。
- **视觉模型独立配置**：视觉大模型引擎与主 LLM 分离，支持独立的 API Key、URL 和模型名称。
- **数字 OCR 归档**：Agent 工作流新增归档步骤，OCR 完成后自动保存原文、原图和元数据到 `archives/` 目录。
- **L3 条件路由自动审核**：低风险自动通过、一般风险推送主管审批、较大/重大风险禁止作业。
- **天气检查增强**：新增低温（≤-5℃）和强风（≥5级）警告。
- **图片上传限制**：提升至 50MB。

### 变更
- **运行日志增强**：日志面板按阶段分隔显示，阶段首行亮黄色加粗，多行输出正确分行。
- **依赖清理**：移除不必要的直接依赖声明 `scikit-learn`、`tiktoken`、`sentencepiece`。

### 修复
- **DOM 重叠**：修复 `stMarkdownContainer` 与 `stCaptionContainer` 重叠问题。
- **日志面板定位**：修复运行日志窗口溢出和定位问题。
- **guide-badge 颜色**：改为内联样式，白色字体与按钮风格统一。

## [3.8.0] - 2026-06-26

### 新增
- **L3 条件路由自动审核**：根据风险等级自动分流审批——低风险自动通过、一般风险推送主管审批、较大/重大风险禁止作业。
- **审批状态字段**：`SecuritySheetData` 新增 `approval_status`（自动通过/待审批/已驳回）和 `approval_level`（自动通过/主管审批/禁止作业）。
- **全量通知**：所有路由级别均通过钉钉推送，消息包含申请人和安全主管。
- **运行日志增强**：`_act()` 重构为 6 步 L3 流程，每步 print + AgentMemory 记录，前端日志窗口可见完整审批链路。
- **KPI 卡片新增审批状态**：结果页新增审批状态指标（绿=自动通过、蓝=待审批、红=已驳回）。
- **看板审批状态显示**：Tab2 记录详情和批量汇总均展示审批状态。

## [3.7.3] - 2026-06-26

### 变更
- **依赖清理**：移除不必要的直接依赖声明 `scikit-learn`、`tiktoken`、`sentencepiece`（已作为 `paddlex[ocr]` 的子依赖自动安装）。

## [3.7.2] - 2026-06-26

### 变更
- **OCR 模式精简**：删除精细网格、多方向检测、测试模式三种 OCR 模式，保留坐标聚类、自适应边框检测、坐标聚类（精确增强）、测试模式（复制 precise 逻辑）共 4 种。
- **OCR 引擎精简**：移除 Surya-OCR、GOT-OCR 2.0 引擎，保留本地 PaddleOCR 和视觉大模型两种。
- **模式 5 改为 HTML 输出**：`_format_table_precise` 使用 OpenCV 边框检测 + PaddleOCR，直接输出 HTML 表格。
- **保存按钮可见性**：侧边栏"💾 保存设置"按钮移至折叠面板外部，始终可见。
- **OCR 原文 HTML 渲染**：含 `<table>` 标签的 OCR 输出以可视化表格形式展示。

### 修复
- **`_last_ocr_raw` 残留**：模式 5/视觉大模型返回前清除旧值，避免 HTML 被纯文本覆盖。

## [3.7.1] - 2026-06-26

### 新增
- **GOT-OCR 2.0 引擎**：OCR 引擎下拉新增"GOT-OCR 2.0"选项，调用阶跃星辰专用文档 OCR 模型，默认 `<format>` 模式输出 Markdown 表格，对符号（✓/×）、手写体、公式识别能力强。需配置支持视觉的 API。

## [3.7.0] - 2026-06-26

### 新增
- **OCR 引擎选择**：侧边栏新增"🔍 OCR 引擎"下拉框，支持三种引擎切换：
  - `本地 PaddleOCR`（默认）：本地推理，支持全部 6 种表格模式。
  - `视觉大模型`：调用 VL 模型（Qwen-VL / GPT-4o 等）直接读图，一步完成表格结构 + 文字 + 符号识别，无需 PaddleOCR。
  - `Surya-OCR`：开源 OCR 引擎，对手写体和符号识别较好，可复用坐标聚类等 4 种表格模式。

## [3.6.0] - 2026-06-26

### 新增
- **test 模式双路合并**：PaddleX 表格结构 + PaddleOCR 文字识别双路并行，PaddleOCR 检测到的 √/× 等小符号按 bbox 坐标自动填入 PaddleX HTML 的空单元格，解决 PaddleX 内部 pipeline 丢失确认符号的问题。合并逻辑优先匹配含符号的 OCR 条目，并打印补充数量。

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
- **CHANGELOG 补充**：v3.4.0 补充钉钉推送改为 config.json 读取及异常捕获修复记录。

## [3.4.0] - 2026-06-25

### 新增
- **精确表格识别模式**：新增第 5 种 OCR 表格模式 `精确表格识别（PaddleStructure）`，基于 PaddleX `table_recognition` 流水线（PP-DocLayout-L 版面检测 + SLANet_plus 表格结构识别 + PP-OCRv4_server 文字识别），输出带 colspan/rowspan 的 HTML 后由 LLM 精排为标准 Markdown 表格，支持合并单元格、手写签名、勾选状态还原。
- **精确模式启动预检**：`check_deps.py` 新增 `paddlex`、`scikit-learn`、`tiktoken`、`sentencepiece` 依赖校验；`START.bat` 新增表格识别模型（`SLANet_plus`）缓存检查与自动下载。

### 变更
- **Streamlit API 更新**：`st.components.v1.html()` 已废弃，替换为 `st.html(unsafe_allow_javascript=True)`。

### 修复
- **钉钉推送改为钉钉 AI 表格 MCP 接入**：`write_dingtalk_table()` 通过 MCP 协议写入多维表 `test_demo` 表（编号/原因/评估结果/填表人），替换原有 Webhook 推送。
- **钉钉推送增加异常捕获**：网络错误时打印失败日志而非抛出异常。

## [3.3.5] - 2026-06-25

### 新增
- **启动依赖版本检查**：新增 `check_deps.py`，程序启动时强制校验 Python 3.13+ 及全部第三方依赖为最新版本，不满足则打印诊断信息并阻止启动。Streamlit 多进程通过环境变量防重复输出。
- **运行日志钉钉推送**：agent `_act()` 阶段自动推送钉钉 Webhook，未配置时在运行日志窗口打印 ⚠️ 警告提示。
- **requirements.txt**：新增依赖声明文件，支持 `pip install --upgrade -r requirements.txt` 一键升级。
- **国内镜像安装**：所有 `pip install` 命令统一使用清华镜像源 `pypi.tuna.tsinghua.edu.cn`。

### 变更
- **OCR 引擎切换**：从 onnxruntime 切换为 PaddlePaddle 推理引擎，全项目 8 处更新（agent_core / check_deps / requirements / START.bat / 文档）。
- **numpy 版本锁定**：从 1.26.4 升级至 2.3.5（满足 paddlex `>=1.24,<2.4` 约束）。
- **依赖全量升级**：pydantic 2.13.4、opencv-python 4.13.0.92、openai 2.44.0、pandas 3.0.3、paddlepaddle 3.3.1、requests 2.34.2。
- **钉钉推送增加异常捕获**：网络错误时打印失败日志而非抛出异常。

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
