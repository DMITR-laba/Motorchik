import os
import sys
import time
import socket
import signal
import webbrowser
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.resolve()
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_PORT = 3000


def is_port_in_use(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def start_backend() -> subprocess.Popen:
    if not BACKEND_DIR.exists():
        print(f"[backend] Директория не найдена: {BACKEND_DIR}")
        return None
    if is_port_in_use(BACKEND_HOST, BACKEND_PORT):
        print(f"[backend] Порт {BACKEND_PORT} уже занят. Пропускаю запуск backend.")
        return None
    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", BACKEND_HOST, "--port", str(BACKEND_PORT), "--reload"]
    print(f"[backend] Запуск: {' '.join(cmd)} (cwd={BACKEND_DIR})")
    return subprocess.Popen(cmd, cwd=str(BACKEND_DIR))


def start_frontend() -> subprocess.Popen:
    if not FRONTEND_DIR.exists():
        print(f"[frontend] Директория не найдена: {FRONTEND_DIR}")
        return None
    if is_port_in_use(BACKEND_HOST, FRONTEND_PORT):
        print(f"[frontend] Порт {FRONTEND_PORT} уже занят. Пропускаю запуск frontend.")
        return None
    cmd = [sys.executable, "-m", "http.server", str(FRONTEND_PORT)]
    print(f"[frontend] Запуск: {' '.join(cmd)} (cwd={FRONTEND_DIR})")
    return subprocess.Popen(cmd, cwd=str(FRONTEND_DIR))


def open_browser():
    url = f"http://{BACKEND_HOST}:{FRONTEND_PORT}"
    try:
        webbrowser.open(url)
        print(f"[browser] Открываю {url}")
    except Exception as exc:
        print(f"[browser] Не удалось открыть браузер: {exc}")


def main():
    print("== Launcher ==")
    print(f"Проект: {PROJECT_ROOT}")

    backend_proc = start_backend()
    # Дадим бэкенду секунду на прогрев
    time.sleep(1)
    frontend_proc = start_frontend()

    # Откроем браузер, если фронт доступен
    for _ in range(20):
        if is_port_in_use(BACKEND_HOST, FRONTEND_PORT):
            open_browser()
            break
        time.sleep(0.25)

    procs = [p for p in (backend_proc, frontend_proc) if p is not None]
    if not procs:
        print("Нет запущенных сервисов. Проверьте сообщения выше.")
        return 1

    def shutdown(*_):
        print("\nОстановка сервисов...")
        for p in procs:
            try:
                if os.name == "nt":
                    p.send_signal(signal.CTRL_BREAK_EVENT) if hasattr(signal, "CTRL_BREAK_EVENT") else p.terminate()
                else:
                    p.terminate()
            except Exception:
                pass
        # Подождём корректного завершения
        deadline = time.time() + 5
        for p in procs:
            while p.poll() is None and time.time() < deadline:
                time.sleep(0.1)
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        print("Готово.")

    try:
        print("Нажмите Ctrl+C для выхода.")
        # Ожидание до прерывания
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())


