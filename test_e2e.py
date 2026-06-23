"""
端到端测试：upload 目录所有图片 -> OCR -> LLM -> 反思 -> 执行
"""
import os, sys, time, glob

os.environ["PYTHONIOENCODING"] = "utf-8"

from agent_core import SecurityAgent, LLMBrain, AgentTools

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "upload")
images = sorted(glob.glob(os.path.join(UPLOAD_DIR, "*.png")) + glob.glob(os.path.join(UPLOAD_DIR, "*.jpg")))

print(f"=== 安全数字监督员 Agent 端到端测试 ===")
print(f"共发现 {len(images)} 张图片\n")

# 阶段 1: OCR 测试
print("=" * 50)
print("阶段 1: OCR 识别测试")
print("=" * 50)
for i, img in enumerate(images):
    name = os.path.basename(img)
    print(f"\n[{i+1}/{len(images)}] {name}")
    t0 = time.time()
    try:
        text = AgentTools.ocr_tool(img)
        dt = time.time() - t0
        lines = text.strip().split("\n")
        print(f"  OK: {len(lines)} 行, {dt:.1f}s")
        for line in lines[:3]:
            print(f"  > {line[:60]}")
    except Exception as e:
        print(f"  FAIL: {e}")

# 阶段 2: 完整 Pipeline
print("\n" + "=" * 50)
print("阶段 2: 完整 Pipeline 测试")
print("=" * 50)

test_image = images[0]
print(f"测试图片: {os.path.basename(test_image)}")

try:
    brain = LLMBrain(
        api_key=os.environ.get("ONLINE_API_KEY", "test"),
        base_url=os.environ.get("ONLINE_BASE_URL", "https://api.siliconflow.cn/v1"),
        model_name=os.environ.get("ONLINE_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
    )
    agent = SecurityAgent(brain=brain)
    t0 = time.time()
    ocr_text, result = agent.run(test_image)
    dt = time.time() - t0

    print(f"\n=== Pipeline PASS ({dt:.1f}s) ===")
    print(f"  ticket_id:    {result.ticket_id}")
    print(f"  station_name: {result.station_name}")
    print(f"  worker_id:    {result.worker_id}")
    print(f"  check_date:   {result.check_date}")
    print(f"  gas_conc:     {result.gas_concentration}")
    print(f"  measures:     {len(result.safety_measures)} items")
    print(f"  has_abnormal: {result.has_abnormal}")
    print(f"  issues:       {len(result.issues)} items")
    print(f"  approver:     {result.approver_name}")
except Exception as e:
    print(f"\n=== Pipeline FAIL ===")
    import traceback
    traceback.print_exc()

print(f"\n=== 测试完成 ===")
