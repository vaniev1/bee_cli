"""Терминальный интерфейс: REPL со стримингом, размышлениями и метриками.

rich не обязателен: если его нет, откатываемся на обычный stdout с ANSI.
"""
import sys

try:
    from rich.console import Console
    _console = Console(highlight=False)
    _RICH = True
except ImportError:  # pragma: no cover
    _console = None
    _RICH = False

from metrics import format_line

AGENT_LABEL = {
    "chat": "🐝 bee worker",
    "search": "🌐 search",
    "time": "⏰ time",
    "help": "🐝 orchestrator",
}


def _emit(text, style=None):
    if _RICH:
        _console.print(text, end="", style=style, markup=False, soft_wrap=True)
    else:
        if style == "dim":
            sys.stdout.write(f"\033[2m{text}\033[0m")
        elif style:
            sys.stdout.write(f"\033[33m{text}\033[0m")
        else:
            sys.stdout.write(text)
    sys.stdout.flush()


def line(text="", style=None):
    if _RICH:
        _console.print(text, style=style, markup=False, highlight=False)
    else:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def rule(title=""):
    if _RICH:
        _console.rule(title, style="grey30")
    else:
        line("─" * 60)


def banner(model, ctx, threads, url, alive):
    bee = "🐝"
    status = "[green]online[/]" if alive else "[red]offline[/]"
    if _RICH:
        _console.print(f"\n{bee} [bold yellow]Bee CLI[/] — локальный ассистент со сбором метрик\n", markup=True)
        _console.print(f"   модель   [dim]{model}[/]", markup=True)
        _console.print(f"   контекст [dim]{ctx} ток · {threads} потоков[/]", markup=True)
        _console.print(f"   движок   [dim]{url}[/] · {status}\n", markup=True)
        _console.print("[dim]Команды: /stats · /reset · /help · /quit (или Ctrl-D)[/]\n", markup=True)
    else:
        line(f"\n{bee} Bee CLI — локальный ассистент со сбором метрик\n")
        line(f"   модель: {model}")
        line(f"   контекст: {ctx} ток, {threads} потоков")
        line(f"   движок: {url} ({'online' if alive else 'offline'})\n")
        line("Команды: /stats /reset /help /quit\n")


def prompt() -> str:
    if _RICH:
        _console.print("[bold yellow]›[/] ", end="", markup=True)
        return input()
    return input("› ")


def render_turn(events, on_metrics):
    """Печатает события одного хода. Возвращает текст ответа (для истории)."""
    answer_parts = []
    thinking_open = False
    answer_started = False

    for kind, val in events:
        if kind == "agent":
            line(f"{AGENT_LABEL.get(val, val)}", style="dim")

        elif kind == "sources":
            line(f"🔎 нашёл {len(val['sources'])} источников по «{val['query']}»", style="dim")
            for s in val["sources"]:
                line(f"   • {s['title']}  [{s['href']}]", style="dim")

        elif kind == "thinking":
            if not thinking_open:
                _emit("💭 ", style="dim")
                thinking_open = True
            _emit(val, style="dim")

        elif kind == "answer":
            if thinking_open and not answer_started:
                line("")  # перенос после размышлений
            answer_started = True
            answer_parts.append(val)
            _emit(val)

        elif kind == "metrics":
            line("")
            line(format_line(val), style="dim")
            line("")
            on_metrics(val)

    return "".join(answer_parts).strip()
