#!/usr/bin/env bash
# Запуск Bee CLI (CLI сам поднимает llama-server).
#   ./run.sh            — чат
#   ./run.sh bench      — бенчмарк
#   ./run.sh --llm-url http://127.0.0.1:8080   — подключиться к запущенному движку
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

# Роутер через LLM — отдельный inference-вызов, на слабом CPU висит секунды.
# Включи BEE_LLM_ROUTER=1 если нужен умный роутинг и железо позволяет.
export BEE_LLM_ROUTER="${BEE_LLM_ROUTER:-0}"

exec "$PY" "$ROOT/bee.py" "$@"
