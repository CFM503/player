# ocr9 训练模型使用手册

> **路径 B**：把「入库」的纠错样本变成可挂到 **管理测试 / 提交作业票** 的 rec 识别模型。  
> 适用：侧栏入口 **OCR文字训练**（`ocr9` / `train_ocr_ui.py`）。  
> 勾选格 √×\ 请用 **ocr10**，见 `OCR训练说明.md`，本手册不涉及。

---

## 0. 先分清三件事

| 你做了什么 | ocr9 预览 | 管理测试 / 用户页 |
|------------|-----------|-------------------|
| 只改真值并 **➕ 入库** | 纠错记忆可立刻变对 | **不会**自动变对 |
| 入库 → **🚀 一键同步纠错到管理测试** | 同上 | **自动套用纠错表**（推荐，无需 inference.yml） |
| 入库 → **微调** → 导出推理模型 → admin **选用并保存** | 可用新权重 | **权重级**泛化（需完整训练栈） |

- **纠错记忆 / 一键同步**：裁剪图哈希 → 真值；写出项目根 `ocr9_corrections.json`，`ocr.py` 识别后自动替换。  
- **rec 微调**：改识别权重；生产通过 `ocr_params.text_recognition_model_dir` 挂载（需 `inference.yml`）。

### 推荐快路径（入库后立刻给 admin 用）

```
改真值 → ➕ 入库（可多条）
        ↓
点「🚀 一键同步纠错到管理测试」
        ↓
项目根生成 ocr9_corrections.json
        ↓
管理测试 / 用户页上传跑票 → 自动命中纠错
```

### 真·权重路径（样本多、要泛化）

```
入库 → 重建列表 → 启动微调 → models/ 有 inference.yml
        ↓
管理测试「识别模型来源」选 ocr9 · 目录 → 💾 保存设置
```

---

## 1. 前置条件

1. 主程序可启动：`streamlit run frontend.py` 或 `START.bat`。  
2. 打开 **OCR文字训练** 页。  
3. 建议侧栏 **设备 = gpu**（无 GPU 时用 cpu，训练更慢）。  
4. 本机若要做**真·权重训练**，需可用的 **PaddleOCR / PaddleX 训练栈**；否则「启动微调」可能只生成脚本与说明，需在训练环境按脚本跑完。

---

## 2. 准备样本（入库）

### 2.1 选图并识别

1. Tab：**📷 识别与逐项训练**  
2. 选图来源（推荐与线上一致）：  
   - **archives** 中带「对齐」的图  
   - 或 **上传** / **工作区 raw/**  
3. 点 **▶️ 运行 / 刷新 OCR 预览**  
4. 右侧绿框=高置信，红框=低置信难例；可勾选 **只列出难例**。

### 2.2 改真值并入库

对每一行错字：

1. 对照预览框，在列表里找到该行（可点 **定位** 高亮）。  
2. 在 **真值** 输入框改成正确文字（可改整行）。  
3. **划分** 保持 **`auto`** 即可（按侧栏 val/test 比例随机分 train/val/test）；重要样本可强制 **train**。  
4. 点 **➕ 入库**，成功提示类似：`已入库 xxxxx → train`。

说明：

- 入库会写：`crops/`、`labels.jsonl`、**纠错记忆**。  
- 日常纠错点 **➕ 入库** 即可；**⚡ 入库并微调** 适合单条后立刻开训（样本少时效果有限）。  
- **禁止**把错误识别批量入库。

### 2.3 样本数量建议

| 阶段 | 建议 |
|------|------|
| 侧栏「最少训练样本」 | 默认约 **8** 条 train 才允许开训 |
| 手写姓名/编号想明显提升 | 同一风格最好 **20+ 行** 再训 |
| 查看进度 | Tab **📚 数据集**：看 train / val / test 条数 |

不够就继续换图、改字、入库。

---

## 2.5 一键同步到管理测试（入库后优先做）

在 **📷 识别与逐项训练** 底部，或 **📦 模型与导出** Tab：

1. 确认已有入库样本  
2. 点 **🚀 一键同步纠错到管理测试**  
3. 成功后项目根出现：  
   - `ocr9_corrections.json` — 纠错表  
   - `ocr9_admin_export.json` — 导出元信息  

效果：

- **管理测试 / 提交作业票** 跑本地 PaddleOCR 时，会按区域哈希替换为你入库的真值  
- **不需要** `inference.yml`，也**不必**改「识别模型来源」  
- 与「原生 / ocr9 权重」可同时存在：先识别，再套纠错  

局限：

- 主要覆盖**已入库相似裁剪**（同票/同位置最稳）  
- 全新版式、完全不同手写，仍可能不命中 → 继续入库再同步，或走真·微调  

关闭（调试用）：环境变量 `OCR9_CORRECTIONS_DISABLE=1`

---

## 3. 重建训练列表

样本够之后：

1. 仍在 **📷 识别与逐项训练** 底部，或数据集相关操作中  
2. 点 **「重建 rec/train|val|test 列表」**

会更新：

```
ocr_train_workspace/rec/train.txt
ocr_train_workspace/rec/val.txt
ocr_train_workspace/rec/test.txt
```

格式为：相对路径 + Tab + 标签文本（Paddle rec 列表习惯）。

---

## 4. 真· rec 微调并导出

任选其一：

| 入口 | 操作 |
|------|------|
| 识别页底部 | **🚀 真·rec微调并导出（给admin）** |
| Tab **🏋️ 训练任务** | 设置 **Epochs** → **🚀 真·rec微调并导出** |

ocr9 内自动完成：准备数据集 → PP-OCRv6 预训练微调 → 导出推理模型。

成功时目录**根下**应有：

```
ocr_train_workspace/models/rec_ft_<时间戳>/
  inference.yml
  inference.pdiparams
  inference.json
  EXPORT_OK.txt
  train_output/          # 权重与 train_direct.log
```

### 4.1 环境依赖（本机配一次）

```bat
python -m paddlex --install PaddleOCR --no_deps -y
pip install albumentations rapidfuzz lmdb
set HTTP_PROXY=http://127.0.0.1:9192
set HTTPS_PROXY=http://127.0.0.1:9192
```

### 4.2 失败时

| 现象 | 处理 |
|------|------|
| 只有 EXPORT_HINT，无 inference.yml | 看 `train_output/train_direct.log` |
| 缺 albumentations / lmdb | 按上表 pip 安装 |
| 找不到 PaddleOCR 仓库 | `paddlex --install PaddleOCR --no_deps` |
| 预训练下载失败 | 配置代理 `127.0.0.1:9192` 后重试 |

**可用标准：** 目录根有 **`inference.yml`**（admin 只认就绪目录）。

---

## 5. 在 ocr9 内自测（推荐）

1. 侧栏 **rec model dir** 填该模型目录的**绝对路径**  
2. 点 **🔄 热加载 OCR**（有 `key` 的引擎会缓存，换目录必须热加载）  
3. 再 **运行 / 刷新 OCR 预览**，看错字是否改善  
4. Tab **🏋️ 训练任务** → **评测 test split**（有 test 样本时）

侧栏勾选 **预览应用纠错记忆** 时，记忆会盖住部分结果；评「模型本身」时可暂时关闭记忆再评。

---

## 6. 挂到管理测试（生产）

1. 打开侧栏 **管理测试**  
2. 找到 **🔤 PaddleOCR 四模型参数** 上方的 **「识别模型来源」**  
3. 选择：  
   - **原生模型（PaddleOCR 内置 rec）** — 不用本地微调  
   - **ocr9 · &lt;目录名&gt;** — 使用 `ocr_train_workspace/models/` 下对应目录  
4. 悬停路径旁文字或标签 **?** 可看**绝对路径**  
5. 点 **💾 保存设置**  

写入 `config.json` 示例字段：

```json
"ocr_params": {
  "text_recognition_model_name": "PP-OCRv6_medium_rec",
  "text_recognition_model_dir": "D:/SOFT/ai/github/player/ocr_train_workspace/models/rec_ft_xxxx"
}
```

- 选 **原生** 并保存：会去掉本地 `text_recognition_model_dir`，回到内置 rec。  
- 列表为空：说明 `models/` 下还没有子目录；先完成第 4 步导出/拷贝。

也可在 ocr9 Tab **📦 模型与导出** 下载挂载片段 JSON，对照写入配置。

---

## 7. 用户页（提交作业票）

用户页**没有**单独的模型下拉，与管理页共用配置：

| 优先级 | 来源 |
|--------|------|
| 1 | 本会话管理页侧栏当前值（含识别模型来源） |
| 2 | `config.json`（点过保存才持久） |

建议：在管理页选好 ocr9 模型并 **保存** → 再打开 **提交作业票** 上传验证。

---

## 8. 操作检查清单（可打印）

- [ ] 难例已改真值并 **➕ 入库**（数据集 train 条数够）  
- [ ] **重建 rec/train|val|test 列表**  
- [ ] **启动微调**（或按 runner 在训练环境跑完）  
- [ ] `models/rec_ft_*/` 内有**完整推理模型**（非仅说明文件）  
- [ ] ocr9：**rec model dir** + **热加载**，预览/评测 OK  
- [ ] 管理测试：**识别模型来源** = 对应 ocr9 目录  
- [ ] **💾 保存设置**  
- [ ] 管理测试 / 用户页上传同风格票，确认文字识别已变  

---

## 9. 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 入库后 admin 仍错 | 未微调挂载；admin 不读 ocr9 纠错记忆 |
| 微调后 admin 仍错 | 未在「识别模型来源」选 ocr9 或未保存；或目录无有效权重 |
| **`No such file …/inference.yml`** | 目录是**占位**（只有 EXPORT_HINT/README），**没有真正导出推理模型**。请改回 **原生模型** 并保存；要挂 ocr9 须先按 `runs/*/train_rec_runner.py` 完成训练导出，目录内出现 `inference.yml` 等再选 |
| 下拉没有 ocr9 项 | `models/` 下无**就绪**目录（缺 inference.yml 的会被排除）；刷新页面 |
| 热加载失败 | 路径错或不是 Paddle rec 推理目录结构 |
| 预览对、关记忆又错 | 当前靠记忆；权重未训好或未热加载新目录 |
| 与勾选对错无关 | 勾选走 **ocr10 → 导出 ocr5**；文字才走本手册 |

---

## 10. 目录速查

```
ocr_train_workspace/
  raw/                 上传/导入原图
  crops/train|val|test 行裁剪图
  labels.jsonl         全量标注
  rec/*.txt            Paddle 列表
  memory/corrections.json   纠错记忆（仅 ocr9）
  runs/                训练任务快照与脚本
  models/              导出/放置 rec 推理模型（admin 扫描此处）
  config.json          ocr9 工作台参数（含 device 等）
```

主程序相关：

- 文字生产：`ocr.py`（`text_recognition_model_dir`）  
- 管理页：`admin_ui.py` → 识别模型来源  
- 用户页：`user_ui.py` → `get_effective_config()` 同步 admin / config  

---

## 11. 质量建议

1. 真值不要含 Tab、换行；全角半角尽量统一。  
2. 优先标**线上会错**的字，不要灌垃圾样本。  
3. 同一手写人/同一票据版式多采几张，比单张狂标更稳。  
4. train/val/test 不要全挤在 train；`auto` 划分一般够用。  
5. 换模型后若结果异常，先切回 **原生模型** 对比，再查路径与热加载。

---

## 12. 相关文档

| 文档 | 内容 |
|------|------|
| `OCR训练说明.md` | ocr9 / ocr10 总览与参数 |
| `ocr9主程序使用步骤.md` | 其它使用步骤 |
| 本手册 | **入库 → 训练 → 挂 admin/用户页** 专用 |

版本说明：与主程序侧栏「识别模型来源」、会话同步用户页的行为一致；若界面文案有微调，以当前 `admin_ui.py` / `ocr9.py` 为准。
