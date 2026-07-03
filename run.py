# -*- coding: utf-8 -*-
"""启动入口：自动寻找空闲端口 + 正确处理 Ctrl+C"""
import subprocess  # 导入子进程管理模块，用于异步启动 Streamlit 进程
import sys  # 导入系统接口模块，用于获取 Python 解释器路径等
import os  # 导入文件系统接口模块，用于路径拼接操作
import socket  # 导入套接字通信模块，用于检测端口是否被占用


def _find_port(start: int = 8501, end: int = 8520) -> int:  # 定义自动探测并获取可用端口的函数
    """从 start 到 end 找第一个空闲端口"""
    for port in range(start, end + 1):  # 遍历从起始端口到结束端口的区间
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # 创建 IPv4 TCP 协议的套接字连接对象
            if s.connect_ex(("127.0.0.1", port)) != 0:  # 尝试连接本机的当前端口，若返回非 0 说明端口空闲
                return port  # 成功找到空闲端口，直接返回当前端口号
    return start  # 若全部端口均被占用，退回返回默认的起始端口号，由 Streamlit 自身抛出冲突异常


def main():  # 定义主运行控制函数
    frontend = os.path.join(os.path.dirname(__file__), "frontend.py")  # 计算并获取前端界面脚本 frontend.py 的绝对物理路径
    port = _find_port()  # 调用端口检测函数，获取第一个空闲可用的服务端口
    if port != 8501:  # 如果获取到的空闲端口不是 Streamlit 默认的 8501
        print(f"[run] 端口 8501 被占用，自动切换到 {port}")  # 控制台打印输出警告，说明发生了端口自动漂移
    p = subprocess.Popen(  # 启动后台子进程来执行 Streamlit Web 前端服务
        [sys.executable, "-m", "streamlit", "run", frontend,  # 使用当前 Python 解释器在终端中执行 streamlit run frontend.py
         "--server.port", str(port)],  # 传入自定义参数指定 Streamlit 监听刚才寻找到的空闲端口号
        cwd=os.path.dirname(__file__),  # 设置子进程的工作目录为当前启动文件所在的物理文件夹
    )  # 结束子进程初始化
    try:  # 开启异常监视保护
        p.wait()  # 阻塞当前线程，等待 Streamlit 前端子进程运行结束或关闭
    except KeyboardInterrupt:  # 捕获用户在终端按下 Ctrl+C 触发的中断退出信号
        p.terminate()  # 向 Streamlit 子进程发送安全退出指令 (SIGTERM)
        p.wait(timeout=5)  # 阻塞等待最多 5 秒，以允许子进程完成资源清理工作
        sys.exit(0)  # 主进程退出，返回状态码 0，完成优雅停机


if __name__ == "__main__":  # 判断当前脚本是否直接由解释器执行
    main()  # 执行入口函数
