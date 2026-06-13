"""LLM-роутер: модель сама выбирает агента, режим размышлений и поисковый запрос.
Запасной путь — простой роутер по ключевым словам (когда llama-server недоступен).
Календарный агент исключён (macOS-only).
"""
import json
import os
import re

ROUTER_SYSTEM_PROMPT = """You are the intent router of a local assistant called Bee. \
Given the conversation context and the user's current message, pick exactly one agent \
for the CURRENT message (use the context to resolve follow-ups and pronouns):

- "time" — the user asks the current time or today's date.
- "search" — the user needs fresh or external information from the internet: news, weather, prices, \
sports scores, facts about current events, specific people, places, companies or products. \
Do NOT use search for riddles, trick questions, math, logic or anything answerable by common sense \
or general knowledge — those are "chat".
- "help" — the user asks what you (Bee) can do or which agents/tools you have. \
NOT for identity questions like "who are you" or "what is your name" — those are "chat".
- "chat" — everything else: conversation, identity questions, writing, ideas, coding, \
general knowledge questions, riddles and trick questions (e.g. "what is heavier, a kg of X or a kg of Y").

Also decide if answering benefits from careful step-by-step reasoning: \
"think" is true for math, logic, puzzles, comparisons, planning, coding or tricky questions, \
and false for greetings, small talk and simple questions.

Reply with ONE line of JSON and nothing else:
{"agent": "<time|search|help|chat>", "query": "<for search only: a short, self-contained web search query in the user's language; otherwise empty string>", "think": <true|false>}"""

VALID_AGENTS = {"time", "search", "help", "chat"}

TIME_KEYWORDS = ["который час", "сколько времени", "текущее время", "what time", "current time"]
SEARCH_KEYWORDS = ["найди", "поиск", "погугли", "загугли", "новости", "узнай про", "search", "google", "news"]
HELP_KEYWORDS = ["агент", "agent", "что ты умеешь", "what can you do", "помощь", "help"]


def route_by_keywords(message: str):
    m = message.lower()
    if any(k in m for k in HELP_KEYWORDS):
        return "help", "", False
    if any(k in m for k in TIME_KEYWORDS):
        return "time", "", False
    if any(k in m for k in SEARCH_KEYWORDS):
        return "search", message, False
    return "chat", "", False


def _router_input(message: str, history: list[dict]) -> str:
    if not history:
        return message
    lines = [
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:200]}"
        for m in history[-6:]
    ]
    return "Conversation so far:\n" + "\n".join(lines) + f"\n\nCurrent user message: {message}"


def route(worker, message: str, history: list[dict]):
    """Возвращает (agent, query, think). При сбое — fallback по ключевым словам.

    BEE_LLM_ROUTER=0 — полностью пропустить вызов модели-роутера (он на слабом
    CPU — главный источник задержки: длинный системный промпт + генерация JSON).
    Тогда роутинг идёт только по ключевым словам, а размышления решает эвристика.
    """
    if os.environ.get("BEE_LLM_ROUTER") == "0":
        return route_by_keywords(message)
    try:
        raw = worker.complete(
            [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": _router_input(message, history)},
            ],
            max_tokens=64,
            temperature=0.0,
        )
        data = json.loads(re.search(r"\{.*\}", raw, re.DOTALL).group(0))
        agent = data.get("agent", "chat")
        query = (data.get("query") or "").strip()
        think = bool(data.get("think", False))
        if agent in VALID_AGENTS:
            return agent, query, think
    except Exception:
        pass
    return route_by_keywords(message)
