# -*- coding: utf-8 -*-
"""
端到端测试：upload 目录所有图片 -> OCR -> LLM -> 反思 -> 执行
"""
import os  # 导入系统接口模块，用于路径处理及读取环境变量
import sys  # 导入系统工具模块，用于进程参数控制
import time  # 导入时间模块，用于计算每个阶段的耗时
import glob  # 导入文件模式匹配库，用于扫描文件夹下的所有图片文件

os.environ["PYTHONIOENCODING"] = "utf-8"  # 强制将 Python 进程的标准输入输出编码设置为 UTF-8，防止中文乱码

from agent_core import SecurityAgent, LLMBrain, AgentTools  # 从智能体核心库导入智能代理、大模型大脑与核心工具包

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")  # 获取当前测试文件同级目录下的 uploads 文件夹绝对路径
images = sorted(glob.glob(os.path.join(UPLOAD_DIR, "*.png")) + glob.glob(os.path.join(UPLOAD_DIR, "*.jpg")))  # 扫描并获取该文件夹下所有 PNG 和 JPG 图片，按文件名排序

print(f"=== 安全数字监督员 Agent 端到端测试 ===")  # 终端打印输出端到端测试的开始装饰头部
print(f"共发现 {len(images)} 张图片\n")  # 终端打印输出发现的待测测试图片文件总数

# 阶段 1: OCR 测试
print("=" * 50)  # 打印阶段一分隔线
print("阶段 1: OCR 识别测试")  # 打印说明信息
print("=" * 50)  # 打印阶段一分隔底部线
for i, img in enumerate(images):  # 循环遍历待测试图片文件列表并附带索引 i
    name = os.path.basename(img)  # 提取该图片的文件基础名称
    print(f"\n[{i+1}/{len(images)}] {name}")  # 终端打印输出当前测试图片所处的文件进度提示信息
    t0 = time.time()  # 记录当前测试开始的时间戳点
    try:  # 开启当前图片测试过程的异常防护
        text = AgentTools.ocr_tool(img)  # 调用智能代理核心工具中的 OCR 方法执行图片文字提取识别
        dt = time.time() - t0  # 计算当前测试所耗费的时间间隔秒数
        lines = text.strip().split("\n")  # 清理尾部空格并按照换行符对识别文本进行分割，获得行列表
        print(f"  OK: {len(lines)} 行, {dt:.1f}s")  # 打印识别成功的状态信息，包括识别出的总行数以及识别所用秒数
        for line in lines[:3]:  # 遍历只截取提取出的前三行文字进行展示以防刷屏
            print(f"  > {line[:60]}")  # 打印这行文字的前 60 个字符内容
    except Exception as e:  # 捕获当前图片测试抛出的报错异常情况
        print(f"  FAIL: {e}")  # 打印该图片识别失败的详情消息提示

# 阶段 2: 完整 Pipeline
print("\n" + "=" * 50)  # 打印阶段二顶部隔离空行及分隔线
print("阶段 2: 完整 Pipeline 测试")  # 打印说明文字
print("=" * 50)  # 打印阶段二底部隔离线

test_image = images[0]  # 选取待测图片列表中的第一张图片作为全流水线测试的主源文件
print(f"测试图片: {os.path.basename(test_image)}")  # 打印即将进行 Pipeline 测试的文件名提示

try:  # 开启 Pipeline 级别的异常防护
    brain = LLMBrain(  # 实例化大模型大脑组件
        api_key=os.environ.get("ONLINE_API_KEY", "test"),  # 从环境变量获取 API Key，无则使用 test
        base_url=os.environ.get("ONLINE_BASE_URL", "https://api.siliconflow.cn/v1"),  # 从环境变量获取大模型接口地址
        model_name=os.environ.get("ONLINE_MODEL", "Qwen/Qwen2.5-7B-Instruct"),  # 从环境变量获取待调用的模型名
    )  # 结束大模型大脑配置定义
    agent = SecurityAgent(brain=brain)  # 绑定大脑以实例化智能监督员代理 SecurityAgent 对象
    t0 = time.time()  # 记录 Pipeline 开始的基准时间戳
    ocr_text, result = agent.run(test_image)  # 执行代理的 run 主流程方法，进行 OCR、大模型评估与安全合规反思
    dt = time.time() - t0  # 计算 Pipeline 最终执行时间间隔

    print(f"\n=== Pipeline PASS ({dt:.1f}s) ===")  # 打印 Pipeline 通过并通过所费秒数提示
    print(f"  ticket_id:    {result.ticket_id}")  # 打印输出识别所得的作业票唯一票号 ID
    print(f"  station_name: {result.station_name}")  # 打印输出识别所得的作业场站名称
    print(f"  worker_id:    {result.worker_id}")  # 打印输出填报人的姓名/工号信息
    print(f"  check_date:   {result.check_date}")  # 打印输出填报时的自检日期数据
    print(f"  gas_conc:     {result.gas_concentration}")  # 打印输出气体检测浓度值数组数据
    print(f"  measures:     {len(result.safety_measures)} items")  # 打印输出检测出的安全防护措施检查项条数
    print(f"  has_abnormal: {result.has_abnormal}")  # 打印输出是否存在异常隐患的布尔评定值
    print(f"  issues:       {len(result.issues)} items")  # 打印输出整理整理出的异常隐患详细条目列表条数
    print(f"  approver:     {result.approver_name}")  # 打印智能推荐的终审领导审批人姓名
except Exception as e:  # 捕获 Pipeline 测试中的崩溃异常情况
    print(f"\n=== Pipeline FAIL ===")  # 打印 Pipeline 运行失败的装饰头部提示
    import traceback  # 导入堆栈追踪调试模块
    traceback.print_exc()  # 向标准错误流输出该异常详细的行数及代码回溯调用调用堆栈以供排查

print(f"\n=== 测试完成 ===")  # 打印测试结束的指示标签
