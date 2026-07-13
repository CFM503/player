# OCR9 / OCR10 使用说明

面向《带气作业票》识别提升的两个独立工作台：

| 工具 | 训练对象 | 影响主程序的方式 |
|------|----------|------------------|
| **ocr9.py** | 文字行（姓名、日期、编号、正文等） | 纠错记忆仅 ocr9 内生效；真·改权重需微调 rec 并配置模型路径 |
| **ocr10.py** | 勾选格 √ / × / \\ / 空白（ocr5 的 25×5） | 导出参数/模型后，**ocr5 自动加载**，主程序即可用 |

二者互不替代：文字用 ocr9，勾选格用 ocr10。

---

## 一、ocr9.py（文字 OCR 标注与训练）

### 1.1 启动

```bash
cd D:\SOFT\ai\github\player
python ocr9.py -h                 # 查看命令行帮助
python ocr9.py                    # 默认端口 8502
python ocr9.py --port 8502 --browser
```

浏览器打开：`http://127.0.0.1:8502`  
工作区：`ocr_train_workspace/`（自动创建，已 gitignore）

### 1.2 侧栏参数

| 操作 | 说明 |
|------|------|
| 滑标/阈值 | 检测 box_thresh、det_thresh、识别 score_thresh、难例分界等 |
| **滑标变更时自动刷新预览** | 建议开启：调参后立刻重跑识别、更新绿/红框 |
| **↺ 重置为默认参数** | 恢复初始值并刷新滑标（调乱了就点这个） |
| 查看默认参数表 | 对照默认值 |
| 保存配置 / 热加载 OCR | 写入工作区 config；重载 Paddle 引擎 |

**默认参考值（与主项目生产侧对齐）：**

- `text_det_box_thresh` = **0.2**
- `text_det_thresh` = **0.3**
- `text_rec_score_thresh` = **0.1**
- `hard_score_thresh` = **0.75**（仅影响难例列表/着色）

### 1.3 日常用法（推荐）

1. **选图**  
   - 优先：`archives/**/对齐图`（与主流程一致，约 1052×1487）  
   - 或：上传 / 工作区 `raw/`

2. **运行 / 刷新 OCR 预览**  
   - 绿框：检出且置信度较高  
   - 红框：低置信度难例  
   - 框上：`置信度|识别文字前缀`  
   - **有框 ≠ 一定认对**；没框也可能有漏检

3. **逐项校对 → 入库**  
   - 在「真值」框改成正确文字  
   - 点 **➕ 入库**  
   - 可选划分：auto / train / val / test（一般 auto）  
   - **⚡ 入库并微调**：入库 + 登记训练任务  

4. **入库后立刻发生什么**  
   - 写入 `crops/` + `labels.jsonl`（训练样本）  
   - 写入 **纠错记忆**（区域哈希 → 真值）  
   - 在 **ocr9 内**再预览同区域：开着「应用纠错记忆」会**马上显示你改过的字**

5. **难例**  
   - 勾选「只列出难例」，优先改红框/低分行

### 1.4 「训练任务」页怎么用

| 按钮/功能 | 实际效果 |
|-----------|----------|
| 启动微调 / 用未训练样本微调 | 检查样本数 → 写 `runs/` 快照与 `train_rec_runner.py` → 标记样本批次；**纠错记忆仍即时可用** |
| 评测 test | 对 test 划分裁剪图重识别，看 CER / 完全匹配 |

说明：

- 若本机没有完整 **PaddleX / PaddleOCR 训练环境**，点训练 = **数据与任务已备好**，不会自动改主程序权重。  
- 真·权重微调：按 `runs/*/train_rec_runner.py` 与官方文档训出 **rec 推理模型**，再：  
  - ocr9 侧栏填 **rec model dir** → **热加载**，或  
  - 主程序 `config.json`：

```json
{
  "ocr_params": {
    "text_recognition_model_dir": "D:/SOFT/ai/github/player/ocr_train_workspace/models/你的导出目录"
  }
}
```

### 1.5 和主程序的关系（务必读）

| 你在 ocr9 做的 | 主程序 Agent 会不会变准 |
|----------------|-------------------------|
| 只入库 | ❌ 不会 |
| 只开纠错记忆 | ❌ 只作用于 ocr9 预览 |
| 训好 rec 并配置 `text_recognition_model_dir` | ✅ 会 |

**勾选格 √×\ 不要用 ocr9**，请用 ocr10。

### 1.6 工作区结构

```text
ocr_train_workspace/
  raw/                      上传原图
  crops/train|val|test/     行裁剪图
  labels.jsonl              全部标注
  rec/train.txt ...         Paddle 格式列表（路径\t标签）
  memory/corrections.json   纠错记忆（ocr9 即时用）
  models/                   预留给导出模型
  runs/                     训练任务记录
  config.json               侧栏参数
```

### 1.7 建议样本量

- 纠错记忆：改几条就立刻改善 **ocr9 内** 同图/同区域预览  
- 真·rec 微调：同一类手写建议 **几十行以上** 再指望明显泛化  

---

## 二、ocr10.py（勾选格 √ / × / \\ / 空白）

### 2.1 启动

```bash
cd D:\SOFT\ai\github\player
python ocr10.py -h                 # 查看命令行帮助
python ocr10.py                    # 默认端口 8503
python ocr10.py --port 8503 --browser
```

浏览器打开：`http://127.0.0.1:8503`  
工作区：`ocr_mark_workspace/`（自动创建，已 gitignore）

### 2.2 侧栏参数

| 参数 | 默认 | 含义 |
|------|------|------|
| 空白 ink 阈值 | 0.008 | 低于此 → 判空白 |
| 最小连通域 | 12 | 去噪 |
| 斜杠直线 RMS 上限 | 1.2 | 越小越严才判 \\ |
| 叉号 min_spur_dist / 端点 min~max | 3 / 3~5 | 叉号拓扑 |
| 去表格线后再分类 | 开 | 只影响格内像素，**检线在原图** |
| 滑标变更时自动刷新预览 | 建议开 | 调参即时重画色框 |
| **↺ 重置为默认参数** | — | 恢复默认并刷新滑标 |

### 2.3 颜色图例（预览框）

| 颜色 | 预测 |
|------|------|
| 绿 | 对号 ✓ |
| 红 | 叉号 × |
| 蓝/橙 | 斜杠 \\ |
| 灰 | 空白 - |
| 黄粗框 | 当前「定位」格 |

### 2.4 日常用法（推荐）

1. **选图**  
   - 必须用 **模板对齐后的带气票**（约 1052×1487）  
   - 优先：`archives/**/对齐图.jpg`  
   - 不要用：手机原图、签字小图、未对齐图  

2. **运行 / 刷新网格预览**  
   - 画出 25 行 × 5 列确认格  
   - 每格显示预测：✓ / × / \\ / -  

3. **逐格改真值 → 入库**  
   - 下拉选：**对号✓ / 叉号× / 斜杠\\ / 空白-**  
   - **空白必须标 blank**，不要标成叉号  
   - 点 **➕ 入库**  
   - **⚡ 入库并导出参数**：入库 + 写出给 ocr5 用的参数  

4. **训练页**  
   - **用当前参数评测标注集**：看规则在已标注样本上的准确率  
   - **规则参数网格搜索（推荐）**：自动搜 ink/RMS/叉号阈值，写出最优参数  
   - **训练 sklearn 特征分类器（可选）**：需 `scikit-learn`，样本建议 ≥8～更多  

5. **导出到 ocr5**  
   - 写出：  
     - `ocr_mark_workspace/models/active_mark_params.json`  
     - 项目根 **`ocr5_mark_params.json`**（ocr5 启动时自动读）  
     - 若训了分类器：`ocr5_mark_model.pkl`  

### 2.5 和主程序的关系

| 你在 ocr10 做的 | 主程序 / ocr5 |
|-----------------|---------------|
| 只入库 | ❌ 尚未改变生产识别 |
| **导出参数** / 规则搜索后自动导出 | ✅ **ocr5 自动加载**，主流程带气 25×5 会用新参数 |
| 导出 sklearn 模型 | ✅ 若存在 pkl，ocr5 会尝试 ML 覆盖 |

主流程调用：对齐图 `uploads/aligned_*.jpg` → `python ocr5.py --input 对齐图`。

### 2.6 工作区结构

```text
ocr_mark_workspace/
  raw/                              上传原图
  cells/check|cross|slash|blank/    单格裁剪
  labels.jsonl                      标注元数据
  memory/corrections.json           纠错记忆（ocr10 预览即时用）
  models/active_mark_params.json    当前导出参数
  models/active_mark_model.pkl      可选分类器
  config.json                       侧栏参数
```

项目根同步（供 ocr5 发现）：

- `ocr5_mark_params.json`  
- `ocr5_mark_model.pkl`（若有）  

### 2.7 检线说明（避免 0 条水平线）

- 水平网格线必须在 **仍含表格线的对齐图** 上检测  
- ocr10 / ocr5 已改为：**先检线，再去表格线做格内分类**  
- 若仍失败：确认是 **对齐图** 尺寸合理（宽≥约 700、高≥约 1000）  

---

## 三、对照速查

| 问题 | ocr9 | ocr10 |
|------|------|-------|
| 启动 | `python ocr9.py` 端口 8502 | `python ocr10.py` 端口 8503 |
| 训练什么 | 文字 det/rec | 勾选格四分类 |
| 入库立刻 | ocr9 预览变对（记忆） | ocr10 预览可变对（记忆） |
| 主程序立刻 | 否 | 否（需 **导出**） |
| 主程序最终 | 配 rec 模型路径 | 导出 `ocr5_mark_params.json` |
| 重置参数 | 侧栏 ↺ 重置 | 侧栏 ↺ 重置 |
| 调参即时预览 | 侧栏勾选自动刷新 | 侧栏勾选自动刷新 |

---

## 四、建议整体工作流

```text
【文字认错】
  ocr9 → 对齐图预览 → 改真值入库 →（可选）攒样本训 rec → 配置主程序模型

【勾选格认错】
  ocr10 → 对齐图预览 → 改 √×\空白 入库 → 规则搜索 / 导出
  → 主程序再跑票（ocr5 自动读参数）

【主程序跑票】
  上传 → 对齐 aligned_* → PaddleOCR 文字 + ocr5 勾选格 → Agent 反思/审批
```

---

## 五、命令行帮助

```bash
python ocr9.py -h
python ocr10.py -h
```

完整参数、工作区说明、与主项目边界均在 `-h` 输出中。

---

## 六、注意

1. 两个工具都请优先用 **对齐图**，不要用未对齐原图练网格/认字。  
2. **不要把错误识别批量入库**。  
3. ocr9 真值不要含 Tab/换行。  
4. ocr10 **空白必须标 blank**，禁止把空白标成叉号。  
5. 工作区目录默认 gitignore，勿依赖仓库内自动同步训练数据。  

---

## 七、多机协同训练（家里 + 单位）

勾选格训练数据已纳入版本库约定（见 `ocr_mark_workspace/README.md`）。

### 会提交到 Git 的文件

| 文件/目录 | 作用 |
|-----------|------|
| `ocr5_mark_params.json` | ocr10 导出的规则参数，**ocr5 自动加载** |
| `ocr5_mark_model.pkl` | 可选分类器，有则提交 |
| `ocr_mark_workspace/labels.jsonl` | 标注记录 |
| `ocr_mark_workspace/cells/**` | 单格裁剪样本 |
| `ocr_mark_workspace/config.json` | ocr10 参数 |
| `ocr_mark_workspace/memory/` | 纠错记忆 |
| `ocr_mark_workspace/models/` | active 导出副本 |

### 不提交（体积大）

- `ocr_mark_workspace/raw/`（整张图）  
- `ocr_mark_workspace/runs/`（日志）  
- `ocr_train_workspace/`（ocr9 文字训练，仍默认本地）  

### 同步步骤

```bash
# 上班/在家训练完后
git pull
# … ocr10 入库、导出 …
git add ocr5_mark_params.json ocr5_mark_model.pkl ocr_mark_workspace
git status   # 确认 raw/ runs/ 未被加入
git commit -m "chore: sync ocr10 mark training data"
git push

# 另一台电脑
git pull
python ocr10.py    # 继续训练
# 主程序直接跑票即可使用已提交的 ocr5_mark_params.json
```

版本与实现细节以代码及 `CHANGELOG.md` 为准。
