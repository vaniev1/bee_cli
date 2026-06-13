"""Один ход диалога: роутинг → агент → стрим ответа, со сбором метрик.

run_turn — генератор UI-событий:
    ("agent", name)        — выбранный агент
    ("sources", {...})     — результаты поиска (для search)
    ("thinking", text)     — кусок размышлений
    ("answer", text)       — кусок ответа
    ("metrics", TurnMetrics) — финальные замеры хода
"""
import time

from metrics import RamSampler, TurnMetrics
from router import route

AGENTS_OVERVIEW = """В команде Bee — 3 агента:

- 🐝 bee_worker — локальная нейросеть: вопросы, тексты, идеи, код.
- ⏰ time_agent — текущее время и дата.
- 🌐 search_agent — поиск в интернете с пересказом и ссылками.

Оркестратор сам понимает по смыслу сообщения, какой агент нужен."""

SEARCH_SUMMARY_PROMPT = (
    "You are Bee, a friendly local AI assistant. The user asked a question and a web search "
    "was already performed for them. Using ONLY the search results below, write a helpful, "
    "coherent answer in the user's language.\n"
    "Rules:\n"
    "- Synthesize and retell the information in your own words — do NOT list the results verbatim.\n"
    "- Cite sources inline as markdown links, e.g. [источник](url), where relevant.\n"
    "- If the results don't really answer the question, say so honestly.\n\n"
    "Search results:\n{results}"
)

MAX_HISTORY_MESSAGES = 16
MAX_HISTORY_CHARS = 8000


def normalize_history(history):
    msgs = [
        {"role": m["role"] if m["role"] in ("user", "assistant") else "assistant",
         "content": m["content"].strip()}
        for m in history if m["content"].strip()
    ][-MAX_HISTORY_MESSAGES:]
    total, kept = 0, []
    for m in reversed(msgs):
        total += len(m["content"])
        if total > MAX_HISTORY_CHARS:
            break
        kept.append(m)
    return list(reversed(kept))


def _format_results_for_llm(results):
    return "\n\n".join(
        f"{i}. {r['title']}\n{r['body']}\nURL: {r['href']}"
        for i, r in enumerate(results, 1)
    )


def run_turn(worker, time_agent, search_agent, message, history, llm_pid=None,
             max_tokens=2048, think_budget=600):
    history = normalize_history(history)
    m = TurnMetrics()

    t0 = time.perf_counter()
    agent, query, think = route(worker, message, history)
    m.router_s = time.perf_counter() - t0
    m.agent = agent
    m.think = think
    yield ("agent", agent)

    char_count = 0
    first_token_at = None
    gen_start = time.perf_counter()

    def stream_llm(messages, thinking):
        nonlocal char_count, first_token_at
        m.llm_used = True
        for kind, val in worker.stream(messages, thinking=thinking,
                                       max_tokens=max_tokens, think_budget=think_budget):
            if kind == "timings":
                m.add_timings(val)
                continue
            if kind == "answer" and first_token_at is None:
                first_token_at = time.perf_counter()
            char_count += len(val)
            yield (kind, val)

    with RamSampler(llm_pid):
        try:
            if agent == "help":
                first_token_at = time.perf_counter()
                yield ("answer", AGENTS_OVERVIEW)
                char_count += len(AGENTS_OVERVIEW)

            elif agent == "time":
                first_token_at = time.perf_counter()
                text = time_agent.run(message)
                yield ("answer", text)
                char_count += len(text)

            elif agent == "search":
                q = query or message
                results = search_agent.fetch(q)
                if not results:
                    first_token_at = time.perf_counter()
                    yield ("answer", f"Ничего не нашёл по запросу «{q}». 🤷")
                else:
                    yield ("sources", {"query": q, "sources": results})
                    messages = [
                        {"role": "system", "content": SEARCH_SUMMARY_PROMPT.format(results=_format_results_for_llm(results))},
                        *history,
                        {"role": "user", "content": message},
                    ]
                    yield from stream_llm(messages, thinking=True)

            else:  # chat
                messages = [
                    {"role": "system", "content": worker.DEFAULT_SYSTEM_PROMPT},
                    *history,
                    {"role": "user", "content": message},
                ]
                yield from stream_llm(messages, thinking=think)

        except Exception as e:
            first_token_at = first_token_at or time.perf_counter()
            text = worker.OFFLINE_MESSAGE if not worker.is_alive() else f"⚠️ Ошибка агента: {e}"
            yield ("answer", text)
            char_count += len(text)

    now = time.perf_counter()
    m.total_s = now - t0
    m.ttft_s = (first_token_at - t0) if first_token_at else m.total_s
    gen_wall = now - (first_token_at or gen_start)
    m.finalize(char_count, gen_wall)
    yield ("metrics", m)
