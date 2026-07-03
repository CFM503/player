# -*- coding: utf-8 -*-
"""独立测试钉钉 MCP 连接"""
import asyncio  # 导入异步 IO 框架以驱动协程的执行
import json  # 导入 JSON 编解码工具用于格式化打印调试数据
import os  # 导入系统路径模块
import sys  # 导入系统控制模块
import io  # 导入数据流操作模块用于对齐控制台编码
import time  # 导入时间时间戳模块

# 修复 Windows GBK 编码引发的控制台输出报错问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')  # 强行重置终端输出的编解码，替换无法转化的字符

sys.path.insert(0, os.path.dirname(__file__))  # 将本测试脚本的父路径动态插入模块寻找路径中，确保正确导入本地模块

from dingtalk_client import DingTalkAITableClient  # 从本地导入刚才中文注释的多维表客户端

# 测试所用钉钉多维表的官方 MCP 网关连接基地址及对应的 Key 秘钥
MCP_URL = "https://mcp-gw.dingtalk.com/server/7b66d4decd453295b36a2d80a1022efc0dad1451e1efc965d8bd34c7a9e8bd37?key=e1b6a11f594a5b37dd2621023d0a8fbe"

async def main():  # 定义测试主协程逻辑函数
    print("=" * 56)  # 打印连接测试上装饰线
    print("钉钉 AI 表格 MCP 连接测试")  # 打印测试说明信息
    print("=" * 56)  # 打印连接测试下装饰线

    async with DingTalkAITableClient(MCP_URL) as client:  # 开启客户端连接上下文，自动完成流管道握手初始化
        print("连接成功")  # 终端打印输出已经成功连入 MCP 服务的提示信息

        # 1. 获取 base
        bases = await client.list_bases(limit=10)  # 向远端获取前 10 个数据底座空间
        base_list = bases.get("data", {}).get("bases", [])  # 解包获取数据列表中的底座bases数组列表
        b = base_list[0]  # 抽取第一个数据底座作为测试目标底座
        base_id = b.get("baseId", "")  # 获取该底座唯一主键 ID
        print(f"base_id: {base_id}")  # 打印底座 ID 调试数据

        # 2. 获取 table
        info = await client.get_base(base_id)  # 查询该底座下的所有表格结构详情
        tables = info.get("data", {}).get("tables", [])  # 从返回的数据中拆解出表格列表数据
        table_id = None  # 初始化目标子表 ID 变量为空
        for t in tables:  # 遍历底座下的每一个表格元素对象
            if t.get("tableName") == "test_demo":  # 寻找名为 test_demo 的特定数据表
                table_id = t.get("tableId")  # 命中后保存该表的主键 ID 值
                break  # 停止循环
        print(f"table_id: {table_id}")  # 打印被定位的目标子表 ID

        # 3. 获取字段（确认责任人现在是 text）
        print("\n--- 字段信息 ---")  # 打印列字段详情阶段说明
        tbl_info = await client.get_tables(base_id, [table_id])  # 批量拉取该表格对应列结构的元数据详情信息
        tbl_list = tbl_info.get("data", {}).get("tables", [])  # 从结构包中拆出子表配置详情数组
        fields = {}  # 初始化空字典，存储中文列名到 fieldId 的对应关系
        for tbl in tbl_list:  # 迭代子表配置详情数组
            if tbl.get("tableId") == table_id:  # 找到当前测试所用的这个表格对应的配置
                for f in tbl.get("fields", []):  # 迭代当前表格内的每一个定义字段列 f
                    fn = f.get("fieldName", "")  # 获取当前列的显示中文名称
                    fi = f.get("fieldId", "")  # 获取当前列的多维表字段唯一标识 ID
                    ft = f.get("type", "")  # 获取当前列在多维表中的数据格式类型，如 text/attachment 等
                    if fn and fi:  # 若中文名和字段 ID 双重有效
                        fields[fn] = fi  # 将此键值关系保存进映射映射字典中
                    print(f"  {fn}: type={ft}, fieldId={fi}")  # 终端输出该字段列名及它的物理类型
        print(f"字段映射: {fields}")  # 打印统计出来的有效字段映射字典结构数据

        # 4. 上传附件（先 PUT 到 OSS）
        print("\n--- 附件上传 ---")  # 打印附件模拟上传阶段头部
        ts = int(time.time())  # 获取当前十位秒级时间戳
        test_file = os.path.join(os.path.dirname(__file__), "_test_upload.txt")  # 获取准备作为附件上传的测试临时文本文本路径
        with open(test_file, "w", encoding="utf-8") as f:  # 以写写模式新建打开该文件文件
            f.write(f"MCP attachment test {ts}")  # 在文件中写入包含时间戳的特定标志句
        fsize = os.path.getsize(test_file)  # 获取该临时文件的物理字节数体积大小，供 OSS 预校验

        # 步骤1: 申请上传地址（必须带 mimeType）
        upload_info = await client.prepare_attachment_upload(  # 向 MCP 表格申请获取带有签名鉴权的临时 OSS 网关上传地址
            base_id, table_id, "_test_upload.txt", fsize, mime_type="text/plain"  # 传入各级主键，文件名、体积大小及 MIME 类型
        )  # 结束申请调用
        d = upload_info.get("data", {})  # 提取返回的 data 核心字典
        upload_url = d.get("uploadUrl", "")  # 获取带有阿里云 OSS 签名的上传直传 URL 地址
        file_token = d.get("fileToken", "")  # 获取完成上传后的唯一附件调用凭据 fileToken
        print(f"fileToken: {file_token}")  # 打印 fileToken 凭证信息以做记录

        file_token_ok = None  # 初始化确认上传成功的 fileToken 容器为 None
        if upload_url and file_token:  # 判断申请获取的上传地址与调用凭据均有效
            with open(test_file, "rb") as f:  # 以二进制制度方式打开刚才生成的临时测试文件
                file_bytes = f.read()  # 读取全部文件字节数组数据
            # 步骤2: PUT 文件到 OSS（必须带 Content-Type）
            import urllib.request  # 导入自带的 urllib 请求库来进行直传以减少三方依赖
            req = urllib.request.Request(upload_url, data=file_bytes, method="PUT")  # 构造上传请求，显式指定上传动作方式为 PUT 模式
            req.add_header("Content-Type", "text/plain")  # 添加 Content-Type 头并指定值为 plain 格式
            try:  # 开启上传直传捕获防崩溃
                put_resp = urllib.request.urlopen(req, timeout=30)  # 使用直连方式将二进制数据 PUT 发送并写入到 OSS 节点中
                print(f"PUT status: {put_resp.status}")  # 终端打印输出上传返回的状态码（通常为 200 或 204 说明成功）
                if put_resp.status in (200, 204):  # 若状态码被返回为成功接收
                    file_token_ok = file_token  # 将该 fileToken 升级为已验证通过的合格凭据
                    print("✅ 附件上传成功")  # 打印成功的状态表情
                else:  # 若状态码异常
                    print(f"PUT 失败: {put_resp.read()[:200]}")  # 打印失败反馈细节
            except urllib.error.HTTPError as e:  # 捕获 HTTP 级别的上传网络异常
                print(f"PUT HTTP {e.code}: {e.read()[:300]}")  # 输出错误代码及远端异常细节提示
            except Exception as e:  # 捕获其它的系统直传崩溃
                print(f"PUT 异常: {e}")  # 打印异常详情
        os.remove(test_file)  # 清理并从本地磁盘上彻底删除刚才测试时新建的临时附件文件

        # 5. 写入五字段（含等级）
        print("\n--- 写入记录 ---")  # 打印写入记录阶段头部
        cells = {}  # 初始化这行记录要填充字段和对应的值字典，键是 fieldId
        for fname, fid in fields.items():  # 遍历先前检测出的中文字段列到列主键映射
            if "编号" in fname:  # 如果包含编号列（如作业票编号）
                cells[fid] = f"TEST_{ts}"  # 使用随机生成的测试时间戳填入该标识栏
            elif "问题描述" in fname:  # 如果是用于存储隐患内容的“问题描述”列
                cells[fid] = json.dumps({"test": "五字段测试", "time": ts}, ensure_ascii=False)  # 格式化填入包含隐患详情的 JSON 序列化字串
            elif "责任人" in fname:  # 如果是表格中负责整改的“责任人”列
                cells[fid] = "测试员_张三"  # 填入指定的整改责任人名字字符串
            elif "等级" in fname:  # 如果是表格中的“风险/隐患等级”字段列
                cells[fid] = "重大"  # 直接填入代表风险等级的文字
            elif "图片" in fname or "附件" in fname:  # 如果是用于存储附图证据的附件列
                if file_token_ok:  # 如果先前上传的附件凭证有效
                    cells[fid] = [{"fileToken": file_token_ok}]  # 构造多维表附件字段要求的多图/多附件数组结构并写入该单元格

        print(f"cells: {json.dumps(cells, ensure_ascii=False)}")  # 打印即将提交写入的数据行结构详情以供核对

        resp = await client.create_records(base_id, table_id, [{"cells": cells}])  # 触发创建，写入这行测试行至多维表数据库中
        print(f"响应: {json.dumps(resp, ensure_ascii=False, indent=2)[:800]}")  # 终端打印输出多维表反馈的结果前 800 字
        if resp.get("status") == "success":  # 判断远端反馈的写入状态是否属于成功标志值
            print("✅✅✅ 五字段全部写入成功！")  # 终端打印大对勾提示写入测试成功
        else:  # 若创建失败
            print(f"❌ 失败: {resp.get('error', {}).get('message', '')}")  # 输出失败的具体报错日志

if __name__ == "__main__":  # 判断是否终端脚本独立进程启动运行
    asyncio.run(main())  # 调用 asyncio.run 开启事件循环执行主测试协程
