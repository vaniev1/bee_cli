"""LLM-воркер: синхронный клиент llama-server с двухфазным мышлением.

Перенесён из bee-backend (BeeWorker), но:
  * синхронный (httpx.Client) — REPL проще без asyncio;
  * стрим отдаёт ещё и события ("timings", dict) с замерами llama-server,
    чтобы CLI считал tok/s движка, а не только по wall-clock.
"""
import json
import re

import httpx

# Модель построена на Qwen3 — может выдавать <think>-блоки рассуждений
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """Убирает <think>-блоки (закрытые, незакрытые и одиночные теги)."""
    text = THINK_BLOCK_RE.sub("", text)
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    text = text.replace("</think>", "")
    return text.strip()


class ThinkTagParser:
    """Инкрементально разделяет поток токенов на размышления и ответ.

    Теги <think>/</think> могут приходить разрезанными между чанками,
    поэтому хвост буфера, который может оказаться началом тега, придерживаем.
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self):
        self.buf = ""
        self.mode = "detect"  # detect | think | answer

    def feed(self, delta: str):
        self.buf += delta
        out = []
        while True:
            if self.mode == "detect":
                s = self.buf.lstrip()
                if not s:
                    return out
                if s.startswith(self.OPEN):
                    self.buf = s[len(self.OPEN):].lstrip()
                    self.mode = "think"
                elif self.OPEN.startswith(s):
                    return out  # возможно неполный "<think" — ждём следующий чанк
                else:
                    self.buf = s
                    self.mode = "answer"
            elif self.mode == "think":
                idx = self.buf.find(self.CLOSE)
                if idx != -1:
                    if self.buf[:idx]:
                        out.append(("thinking", self.buf[:idx]))
                    self.buf = self.buf[idx + len(self.CLOSE):].lstrip()
                    self.mode = "answer"
                else:
                    safe = len(self.buf) - len(self.CLOSE)
                    if safe > 0:
                        out.append(("thinking", self.buf[:safe]))
                        self.buf = self.buf[safe:]
                    return out
            else:  # answer
                if self.buf:
                    out.append(("answer", self.buf))
                    self.buf = ""
                return out

    def flush(self):
        if not self.buf.strip():
            self.buf = ""
            return []
        kind = "thinking" if self.mode == "think" else "answer"
        buf, self.buf = self.buf, ""
        return [(kind, buf)]


class BeeWorker:
    """Синхронный клиент llama-server (форк PrismML, модель Bonsai-8B Q1_0)."""

    DEFAULT_SYSTEM_PROMPT = (
        "You are Bee, a friendly AI assistant that runs fully locally on the user's machine.\n"
        "Identity rules (these override anything you think you know about yourself):\n"
        "- Your one and only name is Bee.\n"
        "- If asked who you are, answer exactly: you are Bee, a local AI assistant.\n"
        "- If asked who created you, answer exactly: you were created by the Bee project. "
        "You do not know any other names of companies, labs, professors or base models — "
        "any such information in your memory is wrong and must not be repeated.\n"
        "Style rules:\n"
        "- Reply in the same language the user writes in.\n"
        "- Be concise and friendly.\n"
        "- Format answers with Markdown when it helps: lists, **bold**, `code`, tables."
    )

    OFFLINE_MESSAGE = "⚠️ Нейросеть офлайн — llama-server недоступен."

    # Без инструкции и затравки модель первым же токеном закрывает </think>
    THINK_HINT = (
        "\nBefore replying, first reason about the question step by step inside your private "
        "<think> block (the user does not see it), in the same language the user writes in, "
        "then give the final answer."
    )
    THINK_SEED_EN = "Okay, "
    THINK_SEED_RU = "Так, "

    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 600.0):
        self.base_url = base_url
        self.client = httpx.Client(timeout=timeout)

    def close(self):
        self.client.close()

    def is_alive(self) -> bool:
        try:
            return self.client.get(f"{self.base_url}/health", timeout=2.0).status_code == 200
        except Exception:
            return False

    def _payload(self, messages, max_tokens, temperature, thinking):
        return {
            "model": "bee-worker",  # llama-server игнорирует это поле
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_k": 20,
            "top_p": 0.9,
            "chat_template_kwargs": {"enable_thinking": thinking},
        }

    def complete(self, messages, max_tokens=1024, temperature=0.5, thinking=False) -> str:
        """Непотоковый запрос. Возвращает текст без <think>-блоков."""
        resp = self.client.post(
            f"{self.base_url}/v1/chat/completions",
            json=self._payload(messages, max_tokens, temperature, thinking),
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"] or ""
        return strip_think(content)

    @staticmethod
    def _chatml(messages) -> str:
        parts = [f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages]
        parts.append("<|im_start|>assistant\n")
        return "".join(parts)

    def _stream_completion(self, prompt, n_predict, stop):
        """Стрим сырого /completion. Yields ("token", delta) и ("timings", dict)."""
        with self.client.stream("POST", f"{self.base_url}/completion", json={
            "prompt": prompt,
            "n_predict": n_predict,
            "temperature": 0.5,
            "top_k": 20,
            "top_p": 0.9,
            "stop": stop,
            "stream": True,
            "cache_prompt": True,
            "timings_per_token": False,
        }) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    obj = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                delta = obj.get("content") or ""
                if delta:
                    yield ("token", delta)
                if obj.get("timings"):
                    yield ("timings", obj["timings"])
                if obj.get("stop"):
                    break

    def stream(self, messages, max_tokens=2048, temperature=0.5, thinking=True, think_budget=600):
        """Потоковый запрос. Yields ("thinking"|"answer"|"timings", value).

        thinking=True: двухфазный budget forcing (модель не закрывает </think> сама).
        """
        if not thinking:
            payload = self._payload(messages, max_tokens, temperature, False)
            payload["stream"] = True
            payload["cache_prompt"] = True
            parser = ThinkTagParser()
            with self.client.stream("POST", f"{self.base_url}/v1/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"].get("content") or ""
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        for item in parser.feed(delta):
                            yield item
                    if obj.get("timings"):
                        yield ("timings", obj["timings"])
            for item in parser.flush():
                yield item
            return

        # Фаза 1: размышления
        if messages and messages[0]["role"] == "system":
            messages = [{"role": "system", "content": messages[0]["content"] + self.THINK_HINT}, *messages[1:]]
        else:
            messages = [{"role": "system", "content": self.THINK_HINT.strip()}, *messages]
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        seed = self.THINK_SEED_RU if re.search(r"[а-яА-ЯёЁ]", last_user) else self.THINK_SEED_EN
        prompt = self._chatml(messages) + "<think>\n" + seed
        yield ("thinking", seed)
        reasoning = []
        for kind, val in self._stream_completion(prompt, think_budget, ["</think>"]):
            if kind == "token":
                reasoning.append(val)
                yield ("thinking", val)
            else:
                yield (kind, val)

        # Фаза 2: финальный ответ (префикс берётся из prompt-кэша llama-server)
        full_prompt = prompt + "".join(reasoning).rstrip() + "\n</think>\n\n"
        for kind, val in self._stream_completion(full_prompt, max_tokens, ["<|im_end|>"]):
            if kind == "token":
                yield ("answer", val)
            else:
                yield (kind, val)
