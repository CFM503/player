"""启动入口：正确处理 Ctrl+C，避免 Windows 批处理信号拦截问题"""
import subprocess
import sys
import os

def main():
    frontend = os.path.join(os.path.dirname(__file__), "frontend.py")
    p = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", frontend],
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
