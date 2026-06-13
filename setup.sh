#!/usr/bin/env bash
# Установка Bee CLI на Linux-сервер (Debian/Ubuntu):
#   1) системные зависимости
#   2) сборка llama-server из форка PrismML (CPU)
#   3) python-venv + зависимости
#   4) скачивание модели Bonsai-8B
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FORK_URL="https://github.com/PrismML-Eng/llama.cpp"
MODEL_URL="https://huggingface.co/prism-ml/Bonsai-8B-gguf/resolve/main/Bonsai-8B-Q1_0.gguf"
NPROC="$(nproc 2>/dev/null || echo 2)"

echo "==> 1/4 Системные зависимости"
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq build-essential cmake git curl python3 python3-venv python3-pip
else
  echo "   ⚠️  не Debian/Ubuntu — поставь вручную: build-essential cmake git curl python3-venv"
fi

echo "==> 2/4 Сборка llama-server (форк PrismML, CPU)"
if [[ ! -d "$ROOT/vendor/llama.cpp" ]]; then
  git clone --depth 1 "$FORK_URL" "$ROOT/vendor/llama.cpp"
fi
cmake -S "$ROOT/vendor/llama.cpp" -B "$ROOT/vendor/llama.cpp/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLAMA_CURL=OFF \
  -DGGML_NATIVE=ON \
  -DGGML_OPENMP=ON \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF
cmake --build "$ROOT/vendor/llama.cpp/build" --config Release --target llama-server -j "$NPROC"

echo "==> 3/4 Python-окружение"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"

echo "==> 4/4 Модель Bonsai-8B (~1.2 ГБ)"
mkdir -p "$ROOT/models"
if [[ ! -f "$ROOT/models/Bonsai-8B-Q1_0.gguf" ]]; then
  curl -L --fail -o "$ROOT/models/Bonsai-8B-Q1_0.gguf" "$MODEL_URL"
else
  echo "   модель уже на месте"
fi

echo ""
echo "✅ Готово. Запуск:  ./run.sh           (чат)"
echo "                    ./run.sh bench     (бенчмарк)"
