# -*- coding: utf-8 -*-
# 【规范】AI模型禁止使用硬改逻辑与兜底逻辑：不得用字符串替换/规则捏造/默认值填充掩盖识别失败；须以模型或算法真实输出为准，识别不到应为空或漏填，禁止编造。
import json  # 导入 JSON 数据编解码模块，用于序列化和反序列化多维表交互的载荷数据
import logging  # 导入系统日志记录模块，用于输出客户端的初始化及调用状态调试信息
from typing import Dict, List, Any, Optional  # 从 typing 导入类型提示注解，提供更健全的方法开发签名说明
import httpx  # 导入异步 HTTP 请求库 httpx，作为与 MCP 后台服务通信的连接池基础
from mcp import ClientSession  # 从 MCP 标准库导入客户端会话管理类，管理工具接口通信生命周期
from mcp.client.streamable_http import streamable_http_client  # 从 MCP 客户端导入 HTTP 协议流适配器，建立通道

logger = logging.getLogger("dingtalk_ai_table_client")  # 初始化获取模块专用的 logger 实例，方便在终端进行输出跟踪

class DingTalkAITableClient:  # 定义钉钉多维表 MCP 服务的通用异步客户端封装类
    """
    DingTalk AI Table (Multi-dimensional Table) MCP Client Wrapper.
    Simplifies interactions with the DingTalk AI Table MCP Server using standard python methods.
    """
    def __init__(self, server_url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0):  # 类的构造器，初始化连接基地址、认证头及超时时长
        self.server_url = server_url  # 缓存保存钉钉 AI 表格多维表 MCP 服务的 API 服务终点 URL 路径
        self.headers = headers or {}  # 缓存并设置默认的网络通信头部信息字典（若无则置空字典）
        self.timeout = timeout  # 缓存接口调用的网络超时界限阈值参数（默认 30 秒）
        
        self._http_client = None  # 初始化底层异步 HTTP 客户端变量为空，将在上下文初始化时建立
        self._client_ctx = None  # 初始化 MCP 底层通信上下文变量为空
        self._read_stream = None  # 初始化流式读取管道变量为空
        self._write_stream = None  # 初始化流式写入管道变量为空
        self.session: Optional[ClientSession] = None  # 初始化标准 MCP 会话通道变量为空

    async def __aenter__(self):  # 定义异步上下文管理器入口方法以开启连接
        """Asynchronously connect to the Streamable HTTP endpoint and initialize MCP session."""
        logger.info(f"Connecting to DingTalk AI Table MCP Server at: {self.server_url}")  # 输出连接日志，指明正在尝试连入的目标服务器路径
        
        self._http_client = httpx.AsyncClient(headers=self.headers, timeout=self.timeout)  # 实例化一个新的异步 HTTP 通信客户端并指定请求头
        await self._http_client.__aenter__()  # 调用异步 HTTP 客户端的进入方法，将其放入异步就绪状态
        
        self._client_ctx = streamable_http_client(  # 构造 streamable_http_client 适配器上下文
            url=self.server_url,   # 指定接入的物理接口终点 URL
            http_client=self._http_client  # 绑定刚才创建的异步 httpx 客户端实例
        )  # 结束适配器实例化
        self._read_stream, self._write_stream, _ = await self._client_ctx.__aenter__()  # 进入通信上下文，解包获取底层的双向流读写管道
        
        self.session = ClientSession(self._read_stream, self._write_stream)  # 基于提取的读写双向流管道，构造客户端会话管理器
        await self.session.__aenter__()  # 进入会话管理器上下文环境
        
        logger.info("Initializing MCP Session...")  # 日志打印声明，准备触发初始化协议交互
        await self.session.initialize()  # 向多维表 MCP Server 发送初始化协议握手数据包并等待确认完成
        logger.info("MCP Session initialized successfully.")  # 日志打印，说明智能体与多维表 MCP 握手通道成功开启
        return self  # 返回客户端类自身对象，供 as 语句接收变量引用

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # 定义异步上下文管理器出口方法，安全回收网络及通信信道资源
        """Clean up session and connections."""
        logger.info("Closing MCP Client Session...")  # 打印日志指出正在优雅关闭会话通道
        if self.session:  # 检查会话管理器实例是否存在
            await self.session.__aexit__(exc_type, exc_val, exc_tb)  # 调用并退出会话管理器上下文，清理资源
        if self._client_ctx:  # 检查底层适配器上下文是否存在
            await self._client_ctx.__aexit__(exc_type, exc_val, exc_tb)  # 退出适配器上下文，切断读写流管道
        if self._http_client:  # 检查异步 HTTP 客户端实例是否存在
            await self._http_client.__aexit__(exc_type, exc_val, exc_tb)  # 安全注销异步 HTTP 连接池客户端
        logger.info("Connection closed.")  # 打印日志说明网络退出清理工作已完全结束

    def _parse_response(self, result) -> Any:  # 定义对 MCP Server 返回的消息进行清洗和解析的内部辅助函数
        """
        Parses the JSON response from the MCP server.
        DingTalk AI Table returns JSON formatted strings inside TextContent.
        """
        if not result or not hasattr(result, "content"):  # 判断返回结构是否为空或其中是否缺失了 content 结果数组
            return result  # 若结构异常，则原样返回原始信息不做任何二次解析
        
        texts = []  # 初始化文本块缓冲区列表
        for block in result.content:  # 遍历 content 数组中的每一项数据块 block
            if hasattr(block, "text"):  # 如果该块是一个包含了 text 属性的对象（例如 TextContent 实例）
                texts.append(block.text)  # 将该文字属性追加到文本块缓冲区中
            elif isinstance(block, dict) and "text" in block:  # 若该块表现为一个字典结构且其中含有键名为 "text" 的单元
                texts.append(block["text"])  # 提取对应键值文本并追加到缓冲区
                
        if not texts:  # 如果遍历结束后缓冲区为空说明没有提取到任何有效识别字串
            return None  # 提前返回 None 空对象
            
        full_text = "".join(texts)  # 用空字符串将所有的零散文本块串联起来，还原为大 JSON/纯文本文本
        try:  # 开启反序列化测试
            return json.loads(full_text)  # 尝试将大文本串强转为 Python 内部的字典或列表结构并返回
        except json.JSONDecodeError:  # 若该文字不属于 JSON 结构
            return full_text  # 直接将原文纯文本返回，供调用者识别

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:  # 定义触发底层 MCP 会话接口的通用方法
        """Generic method to call any tool on the MCP server."""
        if not self.session:  # 检查会话通道是否尚未成功建立连接
            raise RuntimeError("Client is not connected. Use 'async with' context manager.")  # 抛出运行时异常，提醒必须使用 context 守护
        
        args = arguments or {}  # 准备最终要打包发送的参数字典，防 None 报错
        logger.debug(f"Calling tool '{tool_name}' with args: {args}")  # 打印调试级别的日志，说明当前调用的工具名及传参详情
        raw_result = await self.session.call_tool(tool_name, args)  # 通过异步会话向远端 MCP 服务发起工具调用并等待返回
        return self._parse_response(raw_result)  # 调用 parse_response 方法清洗提取的原始响应数据并返回

    # ==========================================
    # Base Management APIs (表格/多维表底座管理接口)
    # ==========================================
    async def list_bases(self, limit: int = 10, cursor: Optional[str] = None) -> Dict[str, Any]:  # 定义批量列举当前名下所有多维表空间的函数
        """List all accessible bases."""
        args = {"limit": limit}  # 构建传参，限制获取的记录最大数量
        if cursor:  # 判断是否含有上一次查询翻页的游标位置偏移
            args["cursor"] = cursor  # 将分页游标参数放入参数列表中
        return await self.call_tool("list_bases", args)  # 调用 list_bases 接口并返回解析结果

    async def search_bases(self, query: str, cursor: Optional[str] = None) -> Dict[str, Any]:  # 定义按关键词搜索名下多维表空间的函数
        """Search bases by name."""
        args = {"query": query}  # 构建传参字典以传递查询过滤关键词词串
        if cursor:  # 判断翻页偏移游标是否生效
            args["cursor"] = cursor  # 补充写入分页游标参数
        return await self.call_tool("search_bases", args)  # 触发搜索调用并返回接口数据

    async def get_base(self, base_id: str) -> Dict[str, Any]:  # 定义根据多维表空间主键 ID 查询结构和表简表目录的函数
        """Get directory information (tables / dashboards summary) for a base."""
        return await self.call_tool("get_base", {"baseId": base_id})  # 发起 get_base 调用并返回解析后的基础数据

    async def create_base(self, base_name: str, template_id: Optional[str] = None) -> Dict[str, Any]:  # 定义创建多维表空间主键底座的函数
        """Create a new Base."""
        args = {"baseName": base_name}  # 配置多维表的显示空间名称
        if template_id:  # 判断是否选择以特定模板创建表
            args["templateId"] = template_id  # 补充写入模板 ID 参数
        return await self.call_tool("create_base", args)  # 触发创建动作并返回远端新建结果

    async def update_base(self, base_id: str, new_base_name: str, description: Optional[str] = None) -> Dict[str, Any]:  # 定义重命名或修改底座描述的函数
        """Update Base name and/or description."""
        args = {"baseId": base_id, "newBaseName": new_base_name}  # 配置空间主键 ID 以及新名字参数
        if description:  # 判断是否需要修改备注文本
            args["description"] = description  # 补充写入新的描述文本参数
        return await self.call_tool("update_base", args)  # 发起更新动作并返回更新后的详情

    async def delete_base(self, base_id: str, reason: Optional[str] = None) -> Dict[str, Any]:  # 定义删除指定多维表空间主键底座的危险删除函数
        """Delete a Base (High Risk)."""
        args = {"baseId": base_id}  # 封装要注销的空间主键 ID
        if reason:  # 判断是否补充说明删除理由
            args["reason"] = reason  # 补充写入删除归档原因文本
        return await self.call_tool("delete_base", args)  # 发起删除操作并返回远端返回结果

    async def search_templates(self, query: str, limit: int = 10, cursor: Optional[str] = None) -> Dict[str, Any]:  # 定义在系统内搜索多维表模板的接口函数
        """Search base templates."""
        args = {"query": query, "limit": limit}  # 封装检索词限制词和最大行数
        if cursor:  # 判断是否含有翻页游标位置
            args["cursor"] = cursor  # 追加注入游标参数
        return await self.call_tool("search_templates", args)  # 执行并返回结果数据

    # ==========================================
    # Table Management APIs (空间内子数据表管理接口)
    # ==========================================
    async def get_tables(self, base_id: str, table_ids: List[str]) -> Dict[str, Any]:  # 定义批量查询子表结构及字段配置的函数
        """Batch retrieve table schemas and fields summary."""
        return await self.call_tool("get_tables", {"baseId": base_id, "tableIds": table_ids})  # 封装参数批量提交并返回表格结构

    async def create_table(self, base_id: str, table_name: str, fields: List[Dict[str, Any]]) -> Dict[str, Any]:  # 定义在底座空间内新建数据表的函数
        """
        Create a new Table with initial fields (up to 15 fields).
        fields format: [{"fieldName": "Name", "type": "text"}, ...]
        """
        args = {"baseId": base_id, "tableName": table_name, "fields": fields}  # 封装空间 ID、新表名及列字段属性配置数组
        return await self.call_tool("create_table", args)  # 调用 create_table 接口并返回建表后的结构对象

    async def update_table(self, base_id: str, table_id: str, new_table_name: str) -> Dict[str, Any]:  # 定义修改数据表名称的函数
        """Rename a Table."""
        args = {"baseId": base_id, "tableId": table_id, "newTableName": new_table_name}  # 配置对应位置参数以及新表名
        return await self.call_tool("update_table", args)  # 触发更新调用并返回结果

    async def delete_table(self, base_id: str, table_id: str) -> Dict[str, Any]:  # 定义删除指定子数据表的函数
        """Delete a Table."""
        args = {"baseId": base_id, "tableId": table_id}  # 整合表空间及数据表的主键 ID 参数
        return await self.call_tool("delete_table", args)  # 执行删除命令并返回接口应答数据

    # ==========================================
    # Field Management APIs (数据表单列字段字段管理接口)
    # ==========================================
    async def get_fields(self, base_id: str, table_id: str, field_ids: List[str]) -> Dict[str, Any]:  # 定义查询表格内指定字段配置细节的函数
        """Get full details of specified fields."""
        return await self.call_tool("get_fields", {"baseId": base_id, "tableId": table_id, "fieldIds": field_ids})  # 执行查询并返回字段的详细参数

    async def create_fields(self, base_id: str, table_id: str, fields: List[Dict[str, Any]]) -> Dict[str, Any]:  # 定义在特定数据表内批量新建字段列的函数
        """Batch create fields in a table."""
        args = {"baseId": base_id, "tableId": table_id, "fields": fields}  # 打包各级 ID 及列属性列表
        return await self.call_tool("create_fields", args)  # 调用 create_fields 并返回增加字段列后的结果

    async def update_field(self, base_id: str, table_id: str, field_id: str, new_field_name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:  # 定义修改单列配置属性或重命名的函数
        """Update a field's name or configuration."""
        args = {"baseId": base_id, "tableId": table_id, "fieldId": field_id}  # 缓存定位 ID
        if new_field_name:  # 检查是否要修改列显示名
            args["newFieldName"] = new_field_name  # 补充写入新名字参数
        if config:  # 检查是否修改了选择项等配置属性
            args["config"] = config  # 补充写入具体的选项参数字典
        return await self.call_tool("update_field", args)  # 执行字段更新动作

    async def delete_field(self, base_id: str, table_id: str, field_id: str) -> Dict[str, Any]:  # 定义删除指定字段列列名空间的函数
        """Delete a field from a table."""
        args = {"baseId": base_id, "tableId": table_id, "fieldId": field_id}  # 打包路径主键
        return await self.call_tool("delete_field", args)  # 触发删除并返回删除成功的状态

    # ==========================================
    # Record Management APIs (数据行增删改查管理接口)
    # ==========================================
    async def query_records(  # 定义查询和筛选具体数据记录列表的通用方法
        self, 
        base_id: str, 
        table_id: str, 
        limit: int = 100, 
        record_ids: Optional[List[str]] = None,
        search_word: Optional[str] = None,
        filter_query: Optional[str] = None,
        sort: Optional[List[Dict[str, Any]]] = None,
        cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query records in a table.
        Allows sorting, searching, and filtering.
        """
        args = {  # 构建通用的参数骨架
            "baseId": base_id,  # 多维表底座 ID
            "tableId": table_id,  # 目标数据子表 ID
            "limit": limit  # 限制最多获取的数据条数
        }  # 结束字典创建
        if record_ids:  # 判断是否只过滤获取特定的几行记录 ID
            args["recordIds"] = record_ids  # 补充过滤数组
        if search_word:  # 检查是否开启全局全文分词检索
            args["searchWord"] = search_word  # 补充检索内容
        if filter_query:  # 判断是否含有 DSL 高级条件筛选串语句
            args["filterQuery"] = filter_query  # 补充写入过滤条件
        if sort:  # 检查是否定义了按指定列进行排序的参数规则
            args["sort"] = sort  # 写入排序规则数组，格式如 [{"fieldId": "fld_xxx", "order": "asc"}]
        if cursor:  # 判断是否需要提取上一页的翻页指针
            args["cursor"] = cursor  # 补充游标参数
            
        return await self.call_tool("query_records", args)  # 提交请求并返回符合条件的数据记录集

    async def create_records(self, base_id: str, table_id: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:  # 定义批量新建数据记录的函数
        """
        Batch create records.
        records format: [{"cells": {"fld_xxx": "Value"}}, ...]
        """
        args = {"baseId": base_id, "tableId": table_id, "records": records}  # 整合表格 ID 以及带单元格键值对的记录列表
        return await self.call_tool("create_records", args)  # 触发创建并在远端生成物理新数据行

    async def update_records(self, base_id: str, table_id: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:  # 定义批量修改指定数据记录的函数
        """
        Batch update records.
        records format: [{"recordId": "rec_xxx", "cells": {"fld_xxx": "New Value"}}, ...]
        """
        args = {"baseId": base_id, "tableId": table_id, "records": records}  # 整合包含主键记录 ID 及其要覆盖单元格内容的参数字典
        return await self.call_tool("update_records", args)  # 触发批量覆盖更新操作

    async def delete_records(self, base_id: str, table_id: str, record_ids: List[str]) -> Dict[str, Any]:  # 定义批量删除数据行的接口函数
        """Batch delete records."""
        args = {"baseId": base_id, "tableId": table_id, "recordIds": record_ids}  # 打包数据行 recordIds 的字符串数组
        return await self.call_tool("delete_records", args)  # 执行删除指令，物理移除多维表中的对应行数据

    # ==========================================
    # Attachment Upload API (附件及多媒体流上传上传授权接口)
    # ==========================================
    async def prepare_attachment_upload(self, base_id: str, table_id: str, file_name: str, file_size: int, mime_type: Optional[str] = None) -> Dict[str, Any]:  # 定义申请多维表附件字段的 OSS 临时授权上传路径的接口函数
        """Request OSS upload authorization for attachment field."""
        args = {  # 封装上传所需的元数据结构
            "baseId": base_id,  # 多维表底座 ID
            "tableId": table_id,  # 数据子表 ID
            "fileName": file_name,  # 文件名称包含后缀
            "fileSize": file_size  # 文件体积字节数（单位：bytes）
        }  # 结束元数据字典
        if mime_type:  # 判断是否传入文件特异性的 MIME 类型属性
            args["mimeType"] = mime_type  # 补充写入 MIME 文件分类标志参数
        return await self.call_tool("prepare_attachment_upload", args)  # 调用 prepare_attachment_upload 获取 OSS 预上传网关参数及秘钥
