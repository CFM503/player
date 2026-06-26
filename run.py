"""启动入口：自动寻找空闲端口 + 正确处理 Ctrl+C"""
import subprocess
import sys
import os
import socket


def _find_port(start: int = 8501, end: int = 8520) -> int:
    """从 start 到 end 找第一个空闲端口"""
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start  # 全被占用时让 Streamlit 自己报错


def main():
    frontend = os.path.join(os.path.dirname(__file__), "frontend.py")
    port = _find_port()
    if port != 8501:
        print(f"[run] 端口 8501 被占用，自动切换到 {port}")
    p = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", frontend,
         "--server.port", str(port)],
        cwd=os.path.dirname(__file__),
    )
    try:
        p.wait()
    except KeyboardInterrupt:
        p.terminate()
        p.wait(timeout=5)
        sys.exit(0)


if __name__ == "__main__":
    main()
