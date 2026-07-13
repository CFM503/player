# 勾选格训练数据（ocr10）

本目录用于 **家里 / 单位多机协同** 训练 ocr5 的 √ / × / \\ / 空白 分类。

## 会进 Git 的内容

| 路径 | 说明 |
|------|------|
| `labels.jsonl` | 全部标注记录 |
| `cells/check\|cross\|slash\|blank/` | 单格裁剪图（训练样本） |
| `config.json` | ocr10 侧栏参数 |
| `memory/corrections.json` | 纠错记忆（预览即时用） |
| `models/` | active 参数/模型副本 |

项目根目录同步（ocr5 自动读取）：

- `ocr5_mark_params.json` — **请提交**
- `ocr5_mark_model.pkl` — 若训练了 sklearn，**请提交**

## 不进 Git（体积大）

- `raw/` — 上传的整张对齐图  
- `runs/` — 训练运行日志  

## 多机流程

**机器 A（单位）**

1. `git pull`
2. `python ocr10.py` → 校对入库 → 规则搜索/导出  
3. `git add ocr_mark_workspace ocr5_mark_params.json ocr5_mark_model.pkl`（有则加）  
4. `git commit` + `git push`

**机器 B（家里）**

1. `git pull`  
2. 继续 `python ocr10.py` 标注/训练  
3. 再 push  

主程序跑票时：只要根目录有 `ocr5_mark_params.json`，ocr5 会自动加载。
