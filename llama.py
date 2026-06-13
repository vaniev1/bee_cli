"""Запуск и контроль llama-server как дочернего процесса.

CLI поднимает движок сам — так известен PID для замера RAM и его легко
погасить на выходе. Можно подключиться к уже запущенному через --llm-url
(тогда RAM меряется best-effort по имени процесса).
"""
import os
import socket
import subprocess
import time

import httpx


def free_port() -> int:
    """Свободный TCP-порт от системы (bind на :0) — чтобы не конфликтовать
    с панелью VPS и прочими сервисами, занявшими 8080."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_llama_pid():
    """Best-effort поиск PID уже запущенного llama-server (Linux, /proc)."""
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/comm") as f:
                    if f.read().strip() == "llama-server":
                        return int(entry)
            except OSError:
                continue
    except OSError:
        pass
    return None


class LlamaServer:
    def __init__(self, binary, model, host="127.0.0.1", port=None, ctx=8192,
                 threads=None, template=None, log_path=None, extra_args=None):
        port = port or free_port()
        self.binary = binary
        self.model = model
        self.host = host
        self.port = port
        self.ctx = ctx
        self.threads = threads or os.cpu_count() or 1
        self.template = template
        self.log_path = log_path
        self.extra_args = extra_args or []
        self.proc = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def pid(self):
        return self.proc.pid if self.proc else None

    def _cmd(self):
        cmd = [
            self.binary, "-m", self.model,
            "--host", self.host, "--port", str(self.port),
            "--ctx-size", str(self.ctx),
            "-t", str(self.threads),
            "--jinja",
        ]
        if self.template:
            cmd += ["--chat-template-file", self.template]
        return cmd + self.extra_args

    def start(self):
        log = open(self.log_path, "w") if self.log_path else subprocess.DEVNULL
        self.proc = subprocess.Popen(self._cmd(), stdout=log, stderr=log)

    def wait_healthy(self, timeout=300.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                return False  # процесс упал
            try:
                if httpx.get(f"{self.base_url}/health", timeout=2.0).status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(1.0)
        return False

    def stop(self):
        if not self.proc:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None
