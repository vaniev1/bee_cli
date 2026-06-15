"""Сбор и форматирование метрик: tok/s, TTFT, время роутера, пиковая RAM.

tok/s берём из timings самого llama-server (точно, без сетевого шума);
если движок их не прислал — оцениваем по wall-clock и числу символов (помечаем ~).
"""
import os
import platform
import subprocess
import threading
import time
from dataclasses import dataclass, field


def _sysctl(key: str):
    """Значение sysctl (macOS). None, если недоступно."""
    try:
        out = subprocess.run(["sysctl", "-n", key], capture_output=True,
                             text=True, timeout=2)
        return out.stdout.strip() or None
    except Exception:
        return None


def system_info() -> dict:
    """Железо, на котором снимаются метрики (для шапки отчёта).

    Linux читает /proc и /sys без зависимостей; macOS — через sysctl;
    Windows и любые пробелы добиваем через psutil (если установлен)."""
    info = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor() or platform.machine(),
        "cores": os.cpu_count(),
        "ram_gb": None,
        "freq_mhz": None,
    }
    # Linux: /proc, /sys
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    info["ram_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except OSError:
        pass
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq") as f:
            info["freq_mhz"] = round(int(f.read().strip()) / 1000)
    except OSError:
        pass

    # macOS: sysctl
    if platform.system() == "Darwin":
        info["cpu"] = _sysctl("machdep.cpu.brand_string") or info["cpu"]
        mem = _sysctl("hw.memsize")
        if mem:
            info["ram_gb"] = round(int(mem) / 1024 ** 3, 1)

    # Кроссплатформенный fallback (в т.ч. Windows): RAM и частота через psutil
    try:
        import psutil
        if info["ram_gb"] is None:
            info["ram_gb"] = round(psutil.virtual_memory().total / 1024 ** 3, 1)
        if info["freq_mhz"] is None:
            freq = psutil.cpu_freq()
            if freq and freq.max:
                info["freq_mhz"] = round(freq.max)
    except Exception:
        pass
    return info


def _rss_mb(pid: int):
    """Резидентная память процесса в МБ. Linux: /proc; иначе psutil; иначе None."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    try:
        import psutil  # необязательная зависимость (для macOS-теста)
        return psutil.Process(pid).memory_info().rss / 1024.0 / 1024.0
    except Exception:
        return None


class RamSampler:
    """Фоновый сэмплер пиковой RSS процесса llama-server во время хода."""

    def __init__(self, pid, interval: float = 0.3):
        self.pid = pid
        self.interval = interval
        self.peak = None
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        if self.pid:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _loop(self):
        while not self._stop.is_set():
            mb = _rss_mb(self.pid)
            if mb is not None and (self.peak is None or mb > self.peak):
                self.peak = mb
            self._stop.wait(self.interval)


@dataclass
class TurnMetrics:
    agent: str = "chat"
    think: bool = False
    llm_used: bool = False        # была ли реальная генерация (не мгновенный агент)
    router_s: float = 0.0          # время решения роутера (отдельный вызов LLM)
    ttft_s: float = 0.0           # wall: от ввода до первого токена ответа
    total_s: float = 0.0          # полное время хода
    prompt_tokens: int = 0        # обработано токенов промпта (prefill)
    gen_tokens: int = 0           # сгенерировано токенов (think + answer)
    prompt_tps: float = 0.0       # tok/s prefill (движок)
    gen_tps: float = 0.0          # tok/s генерации (движок)
    ram_peak_mb: float = None
    approx: bool = False          # tok/s оценочный (движок не прислал timings)

    # внутренние аккумуляторы timings движка
    _p_n: int = field(default=0, repr=False)
    _p_ms: float = field(default=0.0, repr=False)
    _g_n: int = field(default=0, repr=False)
    _g_ms: float = field(default=0.0, repr=False)

    def add_timings(self, t: dict):
        self._p_n += int(t.get("prompt_n", 0) or 0)
        self._p_ms += float(t.get("prompt_ms", 0) or 0)
        self._g_n += int(t.get("predicted_n", 0) or 0)
        self._g_ms += float(t.get("predicted_ms", 0) or 0)

    def finalize(self, char_count: int, gen_wall_s: float):
        if not self.llm_used:
            return  # мгновенный агент (time/help) — генерации не было
        if self._g_n and self._g_ms:
            self.gen_tokens = self._g_n
            self.gen_tps = self._g_n / (self._g_ms / 1000.0)
        elif gen_wall_s > 0.05:  # движок без timings — оценка по символам и wall-clock
            self.approx = True
            self.gen_tokens = max(1, round(char_count / 4))
            self.gen_tps = self.gen_tokens / gen_wall_s
        if self._p_n and self._p_ms:
            self.prompt_tokens = self._p_n
            self.prompt_tps = self._p_n / (self._p_ms / 1000.0)


def format_line(m: TurnMetrics) -> str:
    """Компактная строка метрик под ответом."""
    parts = [f"⏱ {m.total_s:.1f}s"]
    if m.llm_used:
        a = "~" if m.approx else ""
        parts.append(f"{a}{m.gen_tps:.1f} tok/s")
        parts.append(f"TTFT {m.ttft_s:.1f}s")
        if m.router_s:
            parts.append(f"роутер {m.router_s:.1f}s")
        if m.prompt_tps:
            parts.append(f"prefill {m.prompt_tps:.0f} tok/s")
        parts.append(f"{m.gen_tokens} ток")
    else:
        if m.router_s:
            parts.append(f"роутер {m.router_s:.1f}s")
        parts.append("без генерации")
    if m.ram_peak_mb:
        parts.append(f"RAM {m.ram_peak_mb / 1024:.2f} ГБ")
    return "  ·  ".join(parts)


class Session:
    """Агрегатор метрик за сессию — для команды /stats и бенчмарка."""

    def __init__(self):
        self.turns: list[TurnMetrics] = []

    def add(self, m: TurnMetrics):
        self.turns.append(m)

    def summary_dict(self) -> dict:
        gen = [t for t in self.turns if t.gen_tokens]
        if not gen:
            return {"n": 0}
        n = len(gen)
        avg = lambda f: sum(f(t) for t in gen) / n
        ram = [t.ram_peak_mb for t in gen if t.ram_peak_mb]
        return {
            "n": n,
            "avg_tps": avg(lambda t: t.gen_tps),
            "avg_ttft": avg(lambda t: t.ttft_s),
            "avg_router": avg(lambda t: t.router_s),
            "avg_prefill": avg(lambda t: t.prompt_tps),
            "total_tokens": sum(t.gen_tokens for t in gen),
            "peak_ram_gb": (max(ram) / 1024) if ram else None,
        }

    def summary(self) -> str:
        s = self.summary_dict()
        if not s["n"]:
            return "Пока нет замеров."
        lines = [
            f"Ходов с генерацией: {s['n']}",
            f"Средний tok/s:      {s['avg_tps']:.1f}",
            f"Средний TTFT:       {s['avg_ttft']:.2f}s",
            f"Средний роутер:     {s['avg_router']:.2f}s",
            f"Средний prefill:    {s['avg_prefill']:.0f} tok/s",
            f"Всего токенов:      {s['total_tokens']}",
        ]
        if s["peak_ram_gb"]:
            lines.append(f"Пик RAM:            {s['peak_ram_gb']:.2f} ГБ")
        return "\n".join(lines)
