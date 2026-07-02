"""独立测试钉钉 MCP 连接"""
import asyncio
import json
import os
import sys
import io
import time

# 修复 Windows GBK 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))

from dingtalk_client import DingTalkAITableClient

MCP_URL = "https://mcp-gw.dingtalk.com/server/7b66d4decd453295b36a2d80a1022efc0dad1451e1efc965d8bd34c7a9e8bd37?key=e1b6a11f594a5b37dd2621023d0a8fbe"

async def main():
    print("=" * 56)
    print("钉钉 AI 表格 MCP 连接测试")
    print("=" * 56)

    async with DingTalkAITableClient(MCP_URL) as client:
        print("连接成功")

        # 1. 获取 base
        bases = await client.list_bases(limit=10)
        base_list = bases.get("data", {}).get("bases", [])
        b = base_list[0]
        base_id = b.get("baseId", "")
        print(f"base_id: {base_id}")

        # 2. 获取 table
        info = await client.get_base(base_id)
        tables = info.get("data", {}).get("tables", [])
        table_id = None
        for t in tables:
            if t.get("tableName") == "test_demo":
                table_id = t.get("tableId")
                break
        print(f"table_id: {table_id}")

        # 3. 获取字段（确认责任人现在是 text）
        print("\n--- 字段信息 ---")
        tbl_info = await client.get_tables(base_id, [table_id])
        tbl_list = tbl_info.get("data", {}).get("tables", [])
        fields = {}
        for tbl in tbl_list:
            if tbl.get("tableId") == table_id:
                for f in tbl.get("fields", []):
                    fn = f.get("fieldName", "")
                    fi = f.get("fieldId", "")
                    ft = f.get("type", "")
                    if fn and fi:
                        fields[fn] = fi
                    print(f"  {fn}: type={ft}, fieldId={fi}")
        print(f"字段映射: {fields}")

        # 4. 上传附件（先 PUT 到 OSS）
        print("\n--- 附件上传 ---")
        ts = int(time.time())
        test_file = os.path.join(os.path.dirname(__file__), "_test_upload.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(f"MCP attachment test {ts}")
        fsize = os.path.getsize(test_file)

        # 步骤1: 申请上传地址（必须带 mimeType）
        upload_info = await client.prepare_attachment_upload(
            base_id, table_id, "_test_upload.txt", fsize, mime_type="text/plain"
        )
        d = upload_info.get("data", {})
        upload_url = d.get("uploadUrl", "")
        file_token = d.get("fileToken", "")
        print(f"fileToken: {file_token}")

        file_token_ok = None
        if upload_url and file_token:
            with open(test_file, "rb") as f:
                file_bytes = f.read()
            # 步骤2: PUT 文件到 OSS（必须带 Content-Type）
            import urllib.request
            req = urllib.request.Request(upload_url, data=file_bytes, method="PUT")
            req.add_header("Content-Type", "text/plain")
            try:
                put_resp = urllib.request.urlopen(req, timeout=30)
                print(f"PUT status: {put_resp.status}")
                if put_resp.status in (200, 204):
                    file_token_ok = file_token
                    print("✅ 附件上传成功")
                else:
                    print(f"PUT 失败: {put_resp.read()[:200]}")
            except urllib.error.HTTPError as e:
                print(f"PUT HTTP {e.code}: {e.read()[:300]}")
            except Exception as e:
                print(f"PUT 异常: {e}")
        os.remove(test_file)

        # 5. 写入五字段（含等级）
        print("\n--- 写入记录 ---")
        cells = {}
        for fname, fid in fields.items():
            if "编号" in fname:
                cells[fid] = f"TEST_{ts}"
            elif "问题描述" in fname:
                cells[fid] = json.dumps({"test": "五字段测试", "time": ts}, ensure_ascii=False)
            elif "责任人" in fname:
                cells[fid] = "测试员_张三"
            elif "等级" in fname:
                cells[fid] = "重大"  # 等级(text)
            elif "图片" in fname or "附件" in fname:
                if file_token_ok:
                    cells[fid] = [{"fileToken": file_token_ok}]

        print(f"cells: {json.dumps(cells, ensure_ascii=False)}")

        resp = await client.create_records(base_id, table_id, [{"cells": cells}])
        print(f"响应: {json.dumps(resp, ensure_ascii=False, indent=2)[:800]}")
        if resp.get("status") == "success":
            print("✅✅✅ 五字段全部写入成功！")
        else:
            print(f"❌ 失败: {resp.get('error', {}).get('message', '')}")

if __name__ == "__main__":
    asyncio.run(main())
