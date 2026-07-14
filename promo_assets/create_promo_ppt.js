/**
 * 数字化安全监督员 · 宣传自动播放 PPT
 * Visual language inspired by Grok 4.5 promo video:
 * - Off-white minimal canvas
 * - Sparse punchy headlines
 * - Geometric square + thin line constellation
 * - Floating soft-shadow product cards
 * - Pill "prompt bar" motif
 * - Soft blue data accents
 */
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const OUT = path.join(__dirname, "..", "数字化安全监督员_宣传.pptx");
const ADVANCE_MS = 4200; // per-slide dwell; last slide holds (no loop)

// Palette (Grok-ad inspired)
const C = {
  bg: "F5F5F7",
  white: "FFFFFF",
  ink: "111111",
  ink2: "3A3A3C",
  muted: "8E8E93",
  faint: "C7C7CC",
  line: "E5E5EA",
  blue: "5B8DEF",
  blueSoft: "A8C5F5",
  blueDeep: "2F6FED",
  green: "34C759",
  greenSoft: "D1F2D9",
  red: "FF3B30",
  orange: "FF9F0A",
  cardShadow: { type: "outer", color: "000000", blur: 24, offset: 6, angle: 135, opacity: 0.08 },
  softShadow: { type: "outer", color: "000000", blur: 18, offset: 4, angle: 135, opacity: 0.06 },
};

function makeShadow(kind = "card") {
  return kind === "card"
    ? { type: "outer", color: "000000", blur: 24, offset: 6, angle: 135, opacity: 0.08 }
    : { type: "outer", color: "000000", blur: 18, offset: 4, angle: 135, opacity: 0.06 };
}

/** LINE shapes must never have negative w/h — PowerPoint rejects the package. */
function addLine(slide, x1, y1, x2, y2, lineOpts) {
  const x = Math.min(x1, x2);
  const y = Math.min(y1, y2);
  const w = Math.abs(x2 - x1) || 0.001;
  const h = Math.abs(y2 - y1); // 0 is ok for pure horizontal
  // pptxgen draws line from (x,y) to (x+w, y+h); flip via flipH/flipV when needed
  const flipH = x1 > x2;
  const flipV = y1 > y2;
  slide.addShape(pres.shapes.LINE, {
    x, y, w, h,
    line: lineOpts,
    flipH: flipH || undefined,
    flipV: flipV || undefined,
  });
}

/** Scattered square constellation (Grok motif) */
function addConstellation(slide, pts, color = C.faint) {
  for (const p of pts) {
    const s = p.s || 0.08;
    slide.addShape(pres.shapes.RECTANGLE, {
      x: p.x, y: p.y, w: s, h: s,
      fill: { color: p.c || color },
      line: { color: p.c || color, width: 0 },
    });
    if (p.lx != null) {
      addLine(
        slide,
        p.x + s / 2, p.y + s / 2,
        p.lx, p.ly,
        { color: p.lc || C.line, width: 0.75, transparency: 30 }
      );
    }
  }
}

let pres;

async function main() {
  pres = new pptxgen();
  pres.defineLayout({ name: "WIDE_16x9", width: 10, height: 5.625 });
  pres.layout = "WIDE_16x9";
  pres.author = "数字化安全监督员";
  pres.title = "数字化安全监督员 · 宣传";
  pres.subject = "燃气 HSE 带气作业票 AI 审批助手";

  // ───────── 1. Title ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    addConstellation(s, [
      { x: 1.2, y: 1.1, s: 0.07, c: "D1D1D6" },
      { x: 2.4, y: 0.7, s: 0.06, c: "E5E5EA" },
      { x: 7.8, y: 1.3, s: 0.08, c: "D1D1D6" },
      { x: 8.6, y: 0.9, s: 0.05, c: "E5E5EA" },
      { x: 1.8, y: 4.4, s: 0.06, c: "E5E5EA" },
      { x: 8.2, y: 4.6, s: 0.07, c: "D1D1D6" },
      { x: 0.8, y: 3.2, s: 0.05, c: "E5E5EA" },
      { x: 9.0, y: 3.5, s: 0.06, c: "D1D1D6" },
    ]);
    s.addText("数字化安全监督员", {
      x: 0.5, y: 1.95, w: 9, h: 0.55,
      fontSize: 36, fontFace: "Arial", bold: true,
      color: C.ink, align: "center", margin: 0,
    });
    // thin guide under title (Grok-style geometric motif)
    addLine(s, 3.2, 2.65, 6.8, 2.65, { color: C.line, width: 1 });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 3.12, y: 2.61, w: 0.08, h: 0.08,
      fill: { color: C.muted }, line: { color: C.muted, width: 0 },
    });
    s.addText("A powerful HSE compliance agent", {
      x: 0.5, y: 2.85, w: 9, h: 0.35,
      fontSize: 16, fontFace: "Arial",
      color: C.muted, align: "center", margin: 0,
    });
    s.addText("v3.15  ·  中燃集团 AI 创新创意大赛 · 赛道三", {
      x: 0.5, y: 5.15, w: 9, h: 0.25,
      fontSize: 11, fontFace: "Arial",
      color: C.faint, align: "center", margin: 0,
    });
  }

  // ───────── 2. Value prop headline + constellation ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    // constellation around text
    const nodes = [
      { x: 1.0, y: 1.6, s: 0.09, c: "8E8E93" },
      { x: 2.2, y: 1.2, s: 0.07, c: "C7C7CC" },
      { x: 3.0, y: 2.0, s: 0.06, c: "AEAEB2" },
      { x: 7.0, y: 1.5, s: 0.08, c: "8E8E93" },
      { x: 8.1, y: 1.9, s: 0.06, c: "C7C7CC" },
      { x: 8.8, y: 1.1, s: 0.07, c: "AEAEB2" },
      { x: 1.5, y: 3.8, s: 0.07, c: "C7C7CC" },
      { x: 2.8, y: 4.2, s: 0.05, c: "D1D1D6" },
      { x: 7.5, y: 3.9, s: 0.08, c: "8E8E93" },
      { x: 8.6, y: 4.3, s: 0.06, c: "C7C7CC" },
    ];
    // connecting lines
    const lines = [
      [0, 1], [1, 2], [0, 2], [3, 4], [4, 5], [3, 5], [6, 7], [8, 9],
    ];
    for (const [a, b] of lines) {
      const p = nodes[a], q = nodes[b];
      addLine(
        s,
        p.x + 0.04, p.y + 0.04,
        q.x + 0.04, q.y + 0.04,
        { color: C.line, width: 0.75 }
      );
    }
    for (const n of nodes) {
      s.addShape(pres.shapes.RECTANGLE, {
        x: n.x, y: n.y, w: n.s, h: n.s,
        fill: { color: n.c }, line: { color: n.c, width: 0 },
      });
    }
    s.addText("拍照一张带气作业票", {
      x: 0.8, y: 2.25, w: 8.4, h: 0.45,
      fontSize: 28, fontFace: "Arial", bold: true,
      color: C.ink, align: "center", margin: 0,
    });
    s.addText("15 秒完成识别 · 校验 · 审批建议", {
      x: 0.8, y: 2.85, w: 8.4, h: 0.4,
      fontSize: 22, fontFace: "Arial",
      color: C.ink2, align: "center", margin: 0,
    });
  }

  // ───────── 3. Pain → Solution sparse ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    s.addText("一线痛点。", {
      x: 0.7, y: 0.55, w: 8.5, h: 0.45,
      fontSize: 28, fontFace: "Arial", bold: true,
      color: C.ink, margin: 0,
    });

    const pains = [
      { t: "10 分钟", d: "单票人工传递" },
      { t: "易漏检", d: "25 项措施 × 5 列确认" },
      { t: "人工审核", d: "审批凭人工经验，\n自动化审核更规范" },
      { t: "数据沉睡", d: "纸质归档，无法统计隐患" },
    ];
    pains.forEach((p, i) => {
      const x = 0.7 + i * 2.3;
      s.addShape(pres.shapes.RECTANGLE, {
        x, y: 1.5, w: 2.05, h: 2.4,
        fill: { color: C.white },
        shadow: makeShadow("soft"),
        line: { color: C.white, width: 0 },
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: x + 0.18, y: 1.75, w: 0.12, h: 0.12,
        fill: { color: i === 0 ? C.blue : C.faint },
        line: { color: i === 0 ? C.blue : C.faint, width: 0 },
      });
      s.addText(p.t, {
        x: x + 0.18, y: 2.15, w: 1.7, h: 0.5,
        fontSize: 20, fontFace: "Arial", bold: true,
        color: C.ink, margin: 0,
      });
      s.addText(p.d, {
        x: x + 0.18, y: 2.75, w: 1.7, h: 0.8,
        fontSize: 13, fontFace: "Arial",
        color: C.muted, margin: 0,
      });
    });
  }

  // ───────── 4. Prompt bar motif (signature Grok element) ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    s.addText("一句话，跑通全流程。", {
      x: 0.7, y: 1.35, w: 8.6, h: 0.45,
      fontSize: 26, fontFace: "Arial", bold: true,
      color: C.ink, align: "center", margin: 0,
    });

    // Pill prompt bar
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 1.3, y: 2.45, w: 7.4, h: 0.72,
      fill: { color: C.white },
      rectRadius: 0.36,
      shadow: makeShadow("card"),
      line: { color: "EBEBEB", width: 1 },
    });
    s.addText([
      { text: "+  ", options: { color: C.muted, fontSize: 18 } },
      { text: "拍一张带气作业票，自动审批", options: { color: C.ink, fontSize: 15 } },
    ], {
      x: 1.55, y: 2.55, w: 5.2, h: 0.52,
      fontFace: "Arial", valign: "middle", margin: 0,
    });
    s.addText("安全监督员", {
      x: 6.6, y: 2.55, w: 1.2, h: 0.52,
      fontSize: 12, fontFace: "Arial", color: C.muted,
      valign: "middle", align: "right", margin: 0,
    });
    // black send circle
    s.addShape(pres.shapes.OVAL, {
      x: 8.05, y: 2.57, w: 0.48, h: 0.48,
      fill: { color: C.ink }, line: { color: C.ink, width: 0 },
    });
    s.addText("↑", {
      x: 8.05, y: 2.57, w: 0.48, h: 0.48,
      fontSize: 16, fontFace: "Arial", color: C.white,
      align: "center", valign: "middle", margin: 0, bold: true,
    });

    s.addText("感知 → 推理 → 反思 → 执行 → 总结（审批结果）", {
      x: 0.7, y: 3.6, w: 8.6, h: 0.35,
      fontSize: 14, fontFace: "Arial",
      color: C.muted, align: "center", margin: 0,
    });
  }

  // ───────── 5. Floating product result mockup ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };

    // Main floating card
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 1.0, y: 0.7, w: 8.0, h: 3.55,
      fill: { color: C.white },
      rectRadius: 0.16,
      shadow: makeShadow("card"),
      line: { color: C.white, width: 0 },
    });

    // KPI row
    const kpis = [
      { l: "票号", v: "MDJZR…1007", c: C.ink },
      { l: "作业等级", v: "二级", c: C.blueDeep },
      { l: "措施", v: "25×5 齐全", c: C.green },
      { l: "决策", v: "自动通过", c: C.green },
    ];
    kpis.forEach((k, i) => {
      const x = 1.3 + i * 1.9;
      s.addText(k.l, {
        x, y: 0.95, w: 1.7, h: 0.28,
        fontSize: 11, fontFace: "Arial", color: C.muted, margin: 0,
      });
      s.addText(k.v, {
        x, y: 1.25, w: 1.7, h: 0.38,
        fontSize: 16, fontFace: "Arial", bold: true, color: k.c, margin: 0,
      });
    });

    // divider
    addLine(s, 1.3, 1.8, 8.7, 1.8, { color: C.line, width: 1 });

    // mini chart area (line sparkline-ish with shapes)
    s.addText("安全措施落实", {
      x: 1.3, y: 2.0, w: 3, h: 0.28,
      fontSize: 12, fontFace: "Arial", color: C.muted, margin: 0,
    });
    // 10 small blue bars
    for (let i = 0; i < 12; i++) {
      const h = 0.35 + (i % 4) * 0.12 + (i > 8 ? 0.25 : 0);
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
        x: 1.35 + i * 0.28, y: 3.35 - h, w: 0.18, h,
        fill: { color: i < 10 ? C.blue : C.blueSoft },
        rectRadius: 0.03,
        line: { color: i < 10 ? C.blue : C.blueSoft, width: 0 },
      });
    }

    // status chips right
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 5.3, y: 2.15, w: 3.3, h: 1.7,
      fill: { color: "F8FAFC" },
      rectRadius: 0.1,
      line: { color: C.line, width: 1 },
    });
    s.addText("审批建议", {
      x: 5.5, y: 2.3, w: 2.9, h: 0.28,
      fontSize: 12, fontFace: "Arial", color: C.muted, margin: 0,
    });
    s.addText("同意作业\n通过审批 · 天气正常", {
      x: 5.5, y: 2.65, w: 2.9, h: 1.0,
      fontSize: 13, fontFace: "Arial", color: C.ink2, margin: 0,
    });

    // prompt bar under
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 1.8, y: 4.6, w: 6.4, h: 0.58,
      fill: { color: C.white },
      rectRadius: 0.29,
      shadow: makeShadow("soft"),
      line: { color: "EBEBEB", width: 1 },
    });
    s.addText("+  处理这张带气作业票", {
      x: 2.05, y: 4.68, w: 4.2, h: 0.42,
      fontSize: 13, fontFace: "Arial", color: C.ink, valign: "middle", margin: 0,
    });
    s.addShape(pres.shapes.OVAL, {
      x: 7.55, y: 4.7, w: 0.38, h: 0.38,
      fill: { color: C.ink }, line: { color: C.ink, width: 0 },
    });
    s.addText("↑", {
      x: 7.55, y: 4.7, w: 0.38, h: 0.38,
      fontSize: 13, fontFace: "Arial", color: C.white,
      align: "center", valign: "middle", margin: 0, bold: true,
    });
  }

  // ───────── 6. High-speed performance (chart like Grok) ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    s.addText("High-speed\nperformance.", {
      x: 0.7, y: 0.55, w: 4.5, h: 1.3,
      fontSize: 32, fontFace: "Arial", bold: true,
      color: C.ink, margin: 0,
    });
    s.addText("从人工传递、人工审核，到 15 秒闭环。", {
      x: 0.7, y: 2.0, w: 4.5, h: 0.5,
      fontSize: 15, fontFace: "Arial", color: C.muted, margin: 0,
    });

    // descending blue square dots (Grok chart motif) — representing time cost collapsing
    const bars = [
      { h: 2.6, c: "5B8DEF", l: "手填" },
      { h: 2.3, c: "5B8DEF" },
      { h: 2.0, c: "6B98F0" },
      { h: 1.7, c: "7BA3F2" },
      { h: 1.4, c: "8BAEF3" },
      { h: 1.1, c: "9BB9F5" },
      { h: 0.85, c: "ABC4F6" },
      { h: 0.6, c: "BBCFF8" },
      { h: 0.4, c: "CBDAF9" },
      { h: 0.28, c: "D1D1D6", l: "AI" },
    ];
    const baseY = 4.7;
    const startX = 5.2;
    bars.forEach((b, i) => {
      const x = startX + i * 0.42;
      // stem (pure vertical: tiny positive w)
      addLine(s, x + 0.07, baseY - b.h, x + 0.07, baseY, {
        color: b.c, width: 1.5, transparency: 40,
      });
      // square
      s.addShape(pres.shapes.RECTANGLE, {
        x, y: baseY - b.h - 0.06, w: 0.14, h: 0.14,
        fill: { color: b.c }, line: { color: b.c, width: 0 },
      });
    });
    s.addText("10 min", {
      x: 5.0, y: 1.85, w: 0.9, h: 0.25,
      fontSize: 10, fontFace: "Arial", color: C.blueDeep, margin: 0,
    });
    s.addText("15 s", {
      x: 8.7, y: 4.2, w: 0.7, h: 0.25,
      fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0,
    });
  }

  // ───────── 7. Built for HSE pipeline（五阶段，风格统一）─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    s.addText("Built for 合规校验、可审计闭环。", {
      x: 0.5, y: 0.45, w: 9, h: 0.45,
      fontSize: 22, fontFace: "Arial", bold: true,
      color: C.ink, margin: 0,
    });
    s.addText("五个阶段 · 总结输出审批结果", {
      x: 0.5, y: 0.95, w: 9, h: 0.3,
      fontSize: 13, fontFace: "Arial",
      color: C.muted, margin: 0,
    });

    // 产品五阶段：感知 → 推理 → 反思 → 执行 → 总结（审批结果）
    const steps = [
      { n: "01", t: "感知", d: "模板对齐 + OCR\n勾选格物理识别" },
      { n: "02", t: "推理", d: "LLM 结构化字段\n票号 / 等级 / 签批" },
      { n: "03", t: "反思", d: "25×5 规则校验\n失败自动重试" },
      { n: "04", t: "执行", d: "分级路由\n钉钉 + 本地入库" },
      { n: "05", t: "总结", d: "审批结果输出\n决策链可审计" },
    ];
    const cardW = 1.72;
    const gap = 0.14;
    const startX = 0.5;
    steps.forEach((st, i) => {
      const x = startX + i * (cardW + gap);
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
        x, y: 1.45, w: cardW, h: 3.4,
        fill: { color: C.white },
        rectRadius: 0.12,
        shadow: makeShadow("soft"),
        line: { color: C.white, width: 0 },
      });
      s.addText(st.n, {
        x: x + 0.14, y: 1.65, w: cardW - 0.28, h: 0.32,
        fontSize: 11, fontFace: "Arial",
        color: C.blue, bold: true, margin: 0,
      });
      s.addText(st.t, {
        x: x + 0.14, y: 2.1, w: cardW - 0.28, h: 0.42,
        fontSize: 20, fontFace: "Arial", bold: true, color: C.ink, margin: 0,
      });
      s.addText(st.d, {
        x: x + 0.14, y: 2.7, w: cardW - 0.28, h: 1.2,
        fontSize: 12, fontFace: "Arial", color: C.muted, margin: 0,
      });
    });
  }

  // ───────── 8. Feature glass cards ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    s.addText("端到端，数据不出企。", {
      x: 0.7, y: 0.45, w: 8.6, h: 0.45,
      fontSize: 26, fontFace: "Arial", bold: true,
      color: C.ink, margin: 0,
    });

    const feats = [
      { t: "WebUI 即用", d: "手机浏览器拍照上传\n无需专用客户端" },
      { t: "本地 OCR + LLM", d: "PaddleOCR 私有化\n企业大模型可接入" },
      { t: "禁止静默兜底", d: "识别不到不编造\n漏项即阻断放行" },
      { t: "钉钉 AI 表格", d: "自动通过 / 人工介入\n消息触达主管" },
      { t: "决策链日志", d: "每步可审计追溯\n支撑复盘与合规" },
      { t: "L3 条件路由", d: "二级无隐患自动过\n一级推送人工介入" },
    ];
    feats.forEach((f, i) => {
      const col = i % 3;
      const row = Math.floor(i / 3);
      const x = 0.7 + col * 3.05;
      const y = 1.2 + row * 1.95;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
        x, y, w: 2.9, h: 1.75,
        fill: { color: C.white },
        rectRadius: 0.12,
        shadow: makeShadow("soft"),
        line: { color: C.white, width: 0 },
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: x + 0.22, y: y + 0.28, w: 0.12, h: 0.12,
        fill: { color: C.blue },
        line: { color: C.blue, width: 0 },
      });
      s.addText(f.t, {
        x: x + 0.22, y: y + 0.55, w: 2.45, h: 0.35,
        fontSize: 16, fontFace: "Arial", bold: true, color: C.ink, margin: 0,
      });
      s.addText(f.d, {
        x: x + 0.22, y: y + 1.0, w: 2.45, h: 0.55,
        fontSize: 12, fontFace: "Arial", color: C.muted, margin: 0,
      });
    });
  }

  // ───────── 9. Compliance check highlight ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    s.addText("规则清晰。放行有据。", {
      x: 0.7, y: 0.5, w: 8.6, h: 0.45,
      fontSize: 26, fontFace: "Arial", bold: true,
      color: C.ink, margin: 0,
    });

    const rows = [
      { k: "安全措施", v: "25 项 × 5 列，√ / × / \\ 全覆盖" },
      { k: "作业等级", v: "一级 / 二级识别，一级最高危" },
      { k: "日期签名", v: "作业时间、完工、签批五列齐全" },
      { k: "隐患处置", v: "× 与空白记隐患，推送钉钉介入" },
      { k: "识别失败", v: "不编造字段，禁止兜底通过" },
    ];
    rows.forEach((r, i) => {
      const y = 1.2 + i * 0.72;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
        x: 0.7, y, w: 8.6, h: 0.62,
        fill: { color: C.white },
        rectRadius: 0.08,
        shadow: makeShadow("soft"),
        line: { color: C.white, width: 0 },
      });
      s.addShape(pres.shapes.RECTANGLE, {
        x: 0.7, y, w: 0.08, h: 0.62,
        fill: { color: i % 2 === 0 ? C.blue : C.blueSoft },
        line: { color: i % 2 === 0 ? C.blue : C.blueSoft, width: 0 },
      });
      s.addText(r.k, {
        x: 1.05, y: y + 0.12, w: 2.0, h: 0.38,
        fontSize: 15, fontFace: "Arial", bold: true, color: C.ink,
        valign: "middle", margin: 0,
      });
      s.addText(r.v, {
        x: 3.2, y: y + 0.12, w: 5.8, h: 0.38,
        fontSize: 14, fontFace: "Arial", color: C.ink2,
        valign: "middle", margin: 0,
      });
    });
  }

  // ───────── 10. Closing brand ─────────
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    addConstellation(s, [
      { x: 1.5, y: 1.0, s: 0.06, c: "D1D1D6" },
      { x: 8.2, y: 1.2, s: 0.07, c: "C7C7CC" },
      { x: 2.0, y: 4.5, s: 0.05, c: "E5E5EA" },
      { x: 8.0, y: 4.4, s: 0.06, c: "D1D1D6" },
    ]);
    s.addText("数字化安全监督员", {
      x: 0.5, y: 2.0, w: 9, h: 0.55,
      fontSize: 34, fontFace: "Arial", bold: true,
      color: C.ink, align: "center", margin: 0,
    });
    s.addText("让每一张作业票，都经得起检查。", {
      x: 0.5, y: 2.7, w: 9, h: 0.4,
      fontSize: 18, fontFace: "Arial",
      color: C.muted, align: "center", margin: 0,
    });
    // thin accent line
    addLine(s, 4.0, 3.35, 6.0, 3.35, { color: C.blue, width: 2 });
    s.addText("拍照  ·  识别  ·  校验  ·  审批  ·  留痕", {
      x: 0.5, y: 3.6, w: 9, h: 0.35,
      fontSize: 13, fontFace: "Arial",
      color: C.faint, align: "center", margin: 0,
    });
    s.addText("中燃集团 AI 创新创意大赛  ·  流程自动化与审批助手", {
      x: 0.5, y: 5.1, w: 9, h: 0.28,
      fontSize: 11, fontFace: "Arial",
      color: C.faint, align: "center", margin: 0,
    });
  }

  // Write a clean pptxgenjs file first (do not re-zip in JS — Office is picky)
  const cleanPath = path.join(__dirname, "_clean_promo.pptx");
  await pres.writeFile({ fileName: cleanPath });
  console.log("Wrote clean deck");

  // Inject auto-advance (no loop; last slide holds until Esc)
  const { execFileSync } = require("child_process");
  execFileSync(
    "python",
    [path.join(__dirname, "inject_autoplay.py"), cleanPath, OUT, String(ADVANCE_MS)],
    { stdio: "inherit" }
  );
  // English alias + remove intermediate clean file
  fs.copyFileSync(OUT, path.join(__dirname, "promo.pptx"));
  try { fs.unlinkSync(cleanPath); } catch (_) {}
  console.log(`Auto-play: ${ADVANCE_MS}ms/slide, stop on last page → ${OUT}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
