# ocr9 训练完后，主程序怎么用（简化步骤）

> 目标：让主程序（数字化安全监督员 / `run.py` / Streamlit）用上你在 ocr9 里训好的**文字识别模型**。

---

## 先分清两件事

| 你在 ocr9 做了什么 | 主程序能不能直接变准 |
|--------------------|----------------------|
| 只「入库」、改对了字 | ❌ 不会（纠错记忆只在 ocr9 里有效） |
| 训练后得到了 **rec 推理模型目录** | ✅ 按下面步骤配置即可 |

主程序只认一种东西：  
**一个可加载的 PaddleOCR 识别模型目录**（`text_recognition_model_dir`）。

---

## 步骤一：确认模型目录在不在

打开文件夹，看有没有类似路径：

```text
ocr_train_workspace/models/某次训练导出目录/
```

目录里通常要有推理模型文件（随 PaddleOCR/PaddleX 版本不同，常见为推理配置 + 权重，不是只有 `README.txt`）。

- **有完整推理目录** → 进入步骤二  
- **只有 `README.txt` / 空目录** → 说明还没真正导出模型，主程序用不了；需先用官方训练栈按 `runs/*/train_rec_runner.py` 导出 rec，再回来做步骤二  

---

## 步骤二：写入主程序配置

编辑项目根目录的 **`config.json`**（没有就从 `config.example.json` 复制一份）。

在配置里加上（或改）`ocr_params` 中的识别模型路径：

```json
{
  "ocr_params": {
    "text_recognition_model_name": "PP-OCRv6_medium_rec",
    "text_recognition_model_dir": "D:/SOFT/ai/github/player/ocr_train_workspace/models/你的导出目录",
    "text_det_box_thresh": 0.2,
    "text_det_thresh": 0.3,
    "text_rec_score_thresh": 0.1
  }
}
```

说明：

1. 路径改成**你机器上真实的绝对路径**（家里、单位路径可以不同）。  
2. 用正斜杠 `/` 或双反斜杠 `\\` 均可。  
3. 其它 `ocr_params` 可保留原有检测/方向等设置。  
4. **不要把 API Key 提交到 Git**（`config.json` 默认在 gitignore 里）。

---

## 步骤三：重启主程序

1. 关掉正在跑的 Streamlit / 主程序窗口。  
2. 重新启动，例如：

```bash
cd D:\SOFT\ai\github\player
python run.py
```

或你平时用的 `START.bat`。

3. 侧栏若有「保存设置」，确认配置已加载（以 `config.json` 为准时，重启即可）。

---

## 步骤四：用票验证

1. 上传一张**带气作业票**（建议用对齐效果正常的图）。  
2. 点 **处理**。  
3. 看识别出的文字（姓名、日期、编号等）是否比以前更好。  

勾选格 √×\ 仍由 **ocr5** 负责，与 ocr9 无关（勾选用 ocr10 导出）。

---

## 可选：在 ocr9 里先自测模型

主程序配置前，可在 ocr9 验证模型是否可用：

1. 打开 `python ocr9.py`  
2. 侧栏 **rec model dir** 填同一导出目录  
3. 点 **热加载 OCR**  
4. 再跑预览，看文字是否改善  

自测 OK 再配进主程序 `config.json`。

---

## 家里 / 单位换电脑时

| 内容 | 建议 |
|------|------|
| 标注样本 `ocr_train_workspace/crops`、`labels.jsonl` | `git pull` 已可同步 |
| 推理模型目录（体积可能较大） | 用 U 盘拷，或也放进 `ocr_train_workspace/models/` 再提交（注意体积） |
| `config.json` 里的路径 | **每台电脑改成自己的绝对路径** |

---

## 最短清单（复制照做）

```text
1. 确认有：ocr_train_workspace/models/xxx/（完整 rec 推理模型）
2. 编辑 config.json → ocr_params.text_recognition_model_dir = 该目录
3. 重启主程序（run.py / START.bat）
4. 上传作业票点「处理」验证
```

---

## 常见问题

**Q：入库很多了，主程序怎么还是旧结果？**  
A：入库 ≠ 挂模型。必须有 rec 目录 + `text_recognition_model_dir`。

**Q：配置了路径仍报错 / 没变化？**  
A：检查路径是否存在、是否为推理导出目录；重启主程序；路径不要用错到 `runs/` 或只有 README 的空目录。

**Q：勾选格还是错的？**  
A：用 **ocr10** 训练并导出 `ocr5_mark_params.json`，不是 ocr9。

更细的标注/训练说明见：`OCR训练说明.md`。
