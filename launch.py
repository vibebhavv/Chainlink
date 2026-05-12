import os
import subprocess
import time
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

BACKEND_DIR = ROOT_DIR
FRONTEND_DIR = ROOT_DIR / "frontend"

BACKEND_CMD = [
    "uvicorn",
    "backend.app:app",
    "--reload"
]

FRONTEND_CMD = [
    "python3",
    "-m",
    "http.server",
    "5500"
]


def start_backend():
    print("[+] Starting FastAPI backend...")

    return subprocess.Popen(
        BACKEND_CMD,
        cwd=BACKEND_DIR,
        shell=False  # Fixed: shell=False with a list works correctly on Linux
    )


def start_frontend():
    print("[+] Starting frontend server...")

    return subprocess.Popen(
        FRONTEND_CMD,
        cwd=FRONTEND_DIR,
        shell=False  # Fixed: shell=False with a list works correctly on Linux
    )


def main():

    print("=" * 60)
    print("CHAINLINK LAUNCHER")
    print("=" * 60)

    if not FRONTEND_DIR.exists():
        print(f"[!] Frontend folder not found: {FRONTEND_DIR}")
        return

    backend_process = start_backend()

    time.sleep(3)

    frontend_process = start_frontend()

    time.sleep(2)

    print("\n[+] Opening browser...")

    webbrowser.open("http://127.0.0.1:5500")

    print("\n[+] Services running")
    print("    Backend : http://127.0.0.1:8000")
    print("    Frontend: http://127.0.0.1:5500")
    print("\n[CTRL + C] to stop everything\n")

    try:
        backend_process.wait()
        frontend_process.wait()

    except KeyboardInterrupt:

        print("\n[!] Shutting down...")

        backend_process.terminate()
        frontend_process.terminate()

        print("[+] Stopped")


if __name__ == "__main__":
    main()
