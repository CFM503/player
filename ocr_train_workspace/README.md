# 文字 OCR 训练数据（ocr9）

本目录用于 **家里 / 单位多机协同** 标注与训练文字识别（姓名、日期、编号等）。

## 会进 Git 的内容

| 路径 | 说明 |
|------|------|
| `labels.jsonl` | 全部文字行标注 |
| `crops/train\|val\|test/` | 行裁剪图（相对小，可同步） |
| `rec/train.txt` 等 | Paddle rec 列表（`路径\t标签`） |
| `config.json` | ocr9 侧栏参数 |
| `memory/corrections.json` | 纠错记忆（ocr9 预览即时用） |
| `models/` | 导出 rec 模型说明/目录（若有推理模型请一并提交） |

## 不进 Git（体积大）

- `raw/` — 上传的整张票图  
- `runs/` — 训练运行日志  
- `_tmp_preview.png` — 临时预览  

## 多机流程

**机器 A**

1. `git pull`  
2. `python ocr9.py` → 预览 → 改真值 → 入库  
3. （可选）训练任务 / 导出 rec 模型到 `models/`  
4. ```bash
   git add ocr_train_workspace
   git status   # 确认 raw/ runs/ 未加入
   git commit -m "chore: sync ocr9 text training data"
   git push
   ```

**机器 B**

1. `git pull`  
2. 继续 `python ocr9.py`  

### 主程序要用上文字模型

纠错记忆 **只作用于 ocr9 预览**。  
主程序变准需要：把 rec 推理模型目录配进 `config.json` 的 `ocr_params.text_recognition_model_dir`（见 `OCR训练说明.md`）。

## 与 ocr10 分工

| 工具 | 目录 | 对象 |
|------|------|------|
| ocr9 | `ocr_train_workspace/` | 文字 |
| ocr10 | `ocr_mark_workspace/` + `ocr5_mark_params.json` | 勾选格 |
