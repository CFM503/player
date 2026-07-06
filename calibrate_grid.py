# -*- coding: utf-8 -*-
"""交互式标定确认矩阵红框坐标。在模板图上点选左上角→右下角。
使用 tkinter + PIL，不依赖 OpenCV highgui。"""
import json
import os
import sys
from PIL import Image, ImageTk
import tkinter as tk

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "template", "dq.png")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

if not os.path.exists(TEMPLATE_PATH):
    print(f"ERROR: 模板图不存在: {TEMPLATE_PATH}")
    sys.exit(1)

root = tk.Tk()
root.title("标定确认矩阵红框 — 点选 左上角 → 右下角")

img = Image.open(TEMPLATE_PATH)
w, h = img.size

# 缩放显示（太大了缩到屏幕合适）
scale = 1.0
if h > 850:
    scale = 850 / h
display_w, display_h = int(w * scale), int(h * scale)
img_display = img.resize((display_w, display_h), Image.LANCZOS)
photo = ImageTk.PhotoImage(img_display)

canvas = tk.Canvas(root, width=display_w, height=display_h, cursor="crosshair")
canvas.pack()

# 保留原始大小图片引用
img_orig = img  # PIL Image 原始大小

canvas.create_image(0, 0, anchor=tk.NW, image=photo)

points = []  # 存储原始坐标 [ (x1,y1), (x2,y2) ]
rect_id = None
text_id = None

status = tk.Label(root, text="请点击确认矩阵的 左上角", font=("Microsoft YaHei", 11))
status.pack(pady=5)

def to_original(canvas_x, canvas_y):
    """canvas 坐标 → 原始模板坐标"""
    return int(canvas_x / scale), int(canvas_y / scale)

def redraw_rect():
    global rect_id, text_id
    if rect_id:
        canvas.delete(rect_id)
    if text_id:
        canvas.delete(text_id)
    if len(points) == 2:
        x1, y1 = int(points[0][0] * scale), int(points[0][1] * scale)
        x2, y2 = int(points[1][0] * scale), int(points[1][1] * scale)
        rect_id = canvas.create_rectangle(x1, y1, x2, y2, outline="#00FF00", width=2)
        # 文本（用原始坐标）
        ox1, oy1 = points[0]
        ox2, oy2 = points[1]
        rx, ry = min(ox1, ox2), min(oy1, oy2)
        rw, rh = abs(ox2 - ox1), abs(oy2 - oy1)
        text_id = canvas.create_text(x1 + 5, y1 + 16, anchor=tk.NW,
                                     text=f"x={rx} y={ry} w={rw} h={rh}",
                                     fill="#00FF00", font=("Consolas", 10))

def on_click(event):
    ox, oy = to_original(event.x, event.y)
    if len(points) < 2:
        points.append((ox, oy))
        # 画十字标记
        cx, cy = event.x, event.y
        canvas.create_line(cx - 8, cy, cx + 8, cy, fill="#FF0000", width=2)
        canvas.create_line(cx, cy - 8, cx, cy + 8, fill="#FF0000", width=2)
        if len(points) == 1:
            status.config(text=f"左上角: ({ox}, {oy}) — 请点击 右下角")
        else:
            redraw_rect()
            x1, y1, x2, y2 = points[0][0], points[0][1], points[1][0], points[1][1]
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)
            status.config(text=f"区域: x={rx} y={ry} w={rw} h={rh} — 按 S 保存 / R 重选 / Q 退出")

def on_key(event):
    if event.keysym.lower() in ('q', 'escape'):
        print("退出，未保存")
        root.destroy()
    elif event.keysym.lower() == 'r':
        points.clear()
        canvas.delete("all")
        canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        global rect_id, text_id
        rect_id, text_id = None, None
        status.config(text="重选 — 请点击 左上角")
    elif event.keysym.lower() == 's':
        if len(points) < 2:
            status.config(text="请先点击至少两个点！")
            return
        x1, y1, x2, y2 = points[0][0], points[0][1], points[1][0], points[1][1]
        rx, ry = min(x1, x2), min(y1, y2)
        rw, rh = abs(x2 - x1), abs(y2 - y1)
        grid = {"x": rx, "y": ry, "w": rw, "h": rh}
        print(f"\n保存 checklist_grid: {grid}")

        cfg = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["checklist_grid"] = grid
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        status.config(text=f"已保存! {grid}")
        print(f"已写入 {CONFIG_PATH}")
        # 不退出，允许继续微调

canvas.bind("<Button-1>", on_click)
root.bind("<Key>", on_key)
root.focus_set()

print(f"模板: {TEMPLATE_PATH} ({w}x{h}), 缩放 {scale:.2f}")
print("操作: 鼠标左键点选 → S 保存 → R 重选 → Q/ESC 退出")
print("请点击确认矩阵红框的 左上角...")

root.mainloop()
