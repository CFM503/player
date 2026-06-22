"""
端到端测试：upload 目录所有图片 → OCR → LLM → 反思 → 执行
"""
import os, sys, time, glob

os.environ["PYTHONIOENCODING"] = "utf-8"

from agent_core import SecurityAgentOrchestrator, LocalGgufBrain, SecurityAgentTools

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "upload")
images = sorted(glob.glob(os.path.join(UPLOAD_DIR, "*.png")) + glob.glob(os.path.join(UPLOAD_DIR, "*.jpg")))

print(f"=== 安全哨兵 Agent 端到端测试 ===")
print(f"共发现 {len(images)} 张图片\n")

# Step 1: 测试全部图片 OCR
print("=" * 60)
print("阶段 1: OCR 识别测试")
print("=" * 60)
ocr_results = {}
for i, img in enumerate(images):
    name = os.path.basename(img)
    print(f"\n[{i+1}/{len(images)}] {name}")
    t0 = time.time()
    try:
        text = SecurityAgentTools.local_ocr_tool(img)
        dt = time.time() - t0
        lines = text.strip().split("\n")
        ocr_results[name] = text
        print(f"  OK: {len(lines)} 行, {dt:.1f}s")
        # 打印前3行预览
        for line in lines[:3]:
            print(f"  > {line[:60]}")
    except Exception as e:
        print(f"  FAIL: {e}")
        ocr_results[name] = None

# Step 2: 完整 Pipeline 测试 (用第一张图)
print("\n" + "=" * 60)
print("阶段 2: 完整 Pipeline 测试 (OCR -> LLM -> 反思 -> 执行)")
print("=" * 60)

test_image = images[0]
print(f"\n测试图片: {os.path.basename(test_image)}")

try:
    brain = LocalGgufBrain(
        model_path=os.path.join(os.path.dirname(__file__), "models", "qwen2.5-3b-instruct-q4_k_m.gguf")
    )
    agent = SecurityAgentOrchestrator(brain=brain)

    t0 = time.time()
    ocr_text, result = agent.run_pipeline(test_image)
    dt = time.time() - t0

    print(f"\n{'=' * 60}")
    print(f"Pipeline 结果 ({dt:.1f}s)")
    print(f"{'=' * 60}")
    print(f"  ticket_id:       {result.ticket_id}")
    print(f"  station_name:    {result.station_name}")
    print(f"  content:         {result.content}")
    print(f"  worker_id:       {result.worker_id}")
    print(f"  check_date:      {result.check_date}")
    print(f"  gas_concentration: {result.gas_concentration}")
    print(f"  safety_measures: {len(result.safety_measures)} 项")
    print(f"  has_abnormal:    {result.has_abnormal}")
    print(f"  issues:          {len(result.issues)} 条")
    print(f"  completion_time: {result.completion_time}")
    print(f"  approver_name:   {result.approver_name}")
    print(f"\n  [PASS] 完整 Pipeline 测试通过")
except Exception as e:
    print(f"\n  [FAIL] Pipeline 测试失败: {e}")
    import traceback
    traceback.print_exc()

print(f"\n=== 测试完成 ===")
