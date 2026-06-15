#!/usr/bin/env python3
"""Bee CLI — точка входа.

Запуск:
    python bee.py                 # чат (поднимает свой llama-server)
    python bee.py --llm-url URL    # подключиться к запущенному llama-server
    python bee.py bench            # бенчмарк по фиксированным промптам

Конфиг через env (или дефолты рядом с проектом):
    BEE_LLAMA_SERVER  путь к бинарю llama-server (форк PrismML)
    BEE_MODEL         путь к Bonsai-8B-Q1_0.gguf
    BEE_CTX           размер контекста (по умолчанию 8192)
    BEE_THREADS       число потоков (по умолчанию = ядрам)
"""
import argparse
import json
import os
import sys
import time

import agents
import report
import ui
from llama import LlamaServer, default_binary, find_llama_pid
from metrics import Session, system_info
from pipeline import run_turn
from worker import BeeWorker

ROOT = os.path.dirname(os.path.abspath(__file__))


def _cfg(name, default):
    return os.environ.get(name, default)


def bench(worker, time_agent, search_agent, llm_pid, config, max_tokens, think_budget):
    """Прогон фиксированных промптов: метрики, JSON с железом и HTML-отчёт."""
    path = os.path.join(ROOT, "bench_prompts.json")
    with open(path, encoding="utf-8") as f:
        prompts = json.load(f)

    session = Session()
    labels = []
    ui.line("\n🐝 Бенчмарк Bee CLI\n", style="bold yellow")
    for i, p in enumerate(prompts, 1):
        ui.line(f"[{i}/{len(prompts)}] {p['label']}", style="dim")
        labels.append(p["label"])
        metric = None
        for kind, val in run_turn(worker, time_agent, search_agent, p["message"], [], llm_pid,
                                  max_tokens=max_tokens, think_budget=think_budget):
            if kind == "metrics":
                session.add(val)
                metric = val
        if metric:
            ui.line(f"    {metric.gen_tps:.1f} tok/s · TTFT {metric.ttft_s:.2f}s · "
                    f"роутер {metric.router_s:.2f}s · {metric.gen_tokens} ток", style="dim")

    ui.rule("Итоги")
    ui.line(session.summary())

    data = {
        "system": system_info(),
        "config": config,
        "summary": session.summary_dict(),
        "labels": labels,
        "turns": [vars(t) for t in session.turns],
    }
    out = os.path.join(ROOT, "bench_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    html_path = os.path.join(ROOT, "report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(report.build_html(data))
    ui.line(f"\n📄 Данные:  {out}", style="dim")
    ui.line(f"📊 Отчёт:   {html_path}  ← скачай и открой в браузере", style="dim")


def repl(worker, time_agent, search_agent, llm_pid, max_tokens, think_budget):
    session = Session()
    history = []
    while True:
        try:
            text = ui.prompt().strip()
        except (EOFError, KeyboardInterrupt):
            ui.line("\nПока! 🐝")
            break
        if not text:
            continue
        if text in ("/quit", "/exit", "/q"):
            ui.line("Пока! 🐝")
            break
        if text == "/reset":
            history = []
            ui.line("История очищена.", style="dim")
            continue
        if text == "/stats":
            ui.rule("Метрики сессии")
            ui.line(session.summary())
            ui.line("")
            continue
        if text == "/help":
            ui.line("Команды: /stats · /reset · /help · /quit. Просто пиши сообщение для чата.", style="dim")
            continue

        events = run_turn(worker, time_agent, search_agent, text, history, llm_pid,
                          max_tokens=max_tokens, think_budget=think_budget)
        answer = ui.render_turn(events, session.add)
        if answer:
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": answer})


def main():
    ap = argparse.ArgumentParser(prog="bee", description="Bee CLI — локальный ассистент со сбором метрик")
    ap.add_argument("mode", nargs="?", default="chat", choices=["chat", "bench"])
    ap.add_argument("--llm-url", help="подключиться к запущенному llama-server (не спавнить свой)")
    ap.add_argument("--ctx", type=int, default=int(_cfg("BEE_CTX", "4096")))
    ap.add_argument("--threads", type=int, default=int(_cfg("BEE_THREADS", str(os.cpu_count() or 1))))
    ap.add_argument("--max-tokens", type=int, default=int(_cfg("BEE_MAX_TOKENS", "2048")),
                    help="лимит токенов ответа (на слабом CPU ставь 96–128)")
    ap.add_argument("--think-budget", type=int, default=int(_cfg("BEE_THINK_BUDGET", "600")))
    args = ap.parse_args()

    llama = None
    llm_pid = None

    if args.llm_url:
        worker = BeeWorker(base_url=args.llm_url)
        if not worker.is_alive():
            ui.line(f"⚠️ llama-server недоступен на {args.llm_url}", style="bold red")
            sys.exit(1)
        llm_pid = find_llama_pid()
        info = (args.llm_url, "внешний")
    else:
        binary = _cfg("BEE_LLAMA_SERVER", default_binary(ROOT))
        model = _cfg("BEE_MODEL", os.path.join(ROOT, "models", "Bonsai-8B-Q1_0.gguf"))
        setup_hint = ".\\setup.ps1" if os.name == "nt" else "./setup.sh"
        for label, path in [("llama-server", binary), ("модель", model)]:
            if not os.path.exists(path):
                ui.line(f"⚠️ Не найден {label}: {path}\n   Запусти {setup_hint} или задай env BEE_*", style="bold red")
                sys.exit(1)
        llama = LlamaServer(
            binary=binary, model=model, ctx=args.ctx, threads=args.threads,
            log_path=os.path.join(ROOT, "llama-server.log"),
        )
        ui.line("⏳ Поднимаю llama-server и гружу модель…", style="dim")
        t0 = time.perf_counter()
        llama.start()
        if not llama.wait_healthy():
            ui.line("⚠️ llama-server не поднялся. Логи: llama-server.log", style="bold red")
            llama.stop()
            sys.exit(1)
        ui.line(f"✅ Модель готова за {time.perf_counter() - t0:.1f}s", style="dim")
        worker = BeeWorker(base_url=llama.base_url)
        llm_pid = llama.pid
        info = (llama.base_url, model)

    ui.banner(model=os.path.basename(info[1]), ctx=args.ctx, threads=args.threads,
              url=info[0], alive=worker.is_alive())

    time_agent = agents.TimeAgent()
    search_agent = agents.SearchAgent()
    config = {"model": os.path.basename(info[1]), "ctx": args.ctx, "threads": args.threads}
    try:
        if args.mode == "bench":
            bench(worker, time_agent, search_agent, llm_pid, config, args.max_tokens, args.think_budget)
        else:
            repl(worker, time_agent, search_agent, llm_pid, args.max_tokens, args.think_budget)
    finally:
        worker.close()
        if llama:
            llama.stop()


if __name__ == "__main__":
    main()
