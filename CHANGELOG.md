# 更新日志 (CHANGELOG)

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
