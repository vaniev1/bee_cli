#!/usr/bin/env bash
# Установка Bee CLI на Linux (Debian/Ubuntu) и macOS:
#   1) системные зависимости
#   2) сборка llama-server из форка PrismML (CPU)
#   3) python-venv + зависимости
#   4) скачивание модели Bonsai-8B
# Windows: используй setup.ps1
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FORK_URL="https://github.com/PrismML-Eng/llama.cpp"
MODEL_URL="https://huggingface.co/prism-ml/Bonsai-8B-gguf/resolve/main/Bonsai-8B-Q1_0.gguf"

OS="$(uname -s)"
case "$OS" in
  Darwin)
    NPROC="$(sysctl -n hw.ncpu 2>/dev/null || echo 2)"
    # У Apple clang нет OpenMP-рантайма; llama.cpp прекрасно работает на своём
    # threadpool, поэтому на macOS собираем без OpenMP (иначе cmake падает).
    OPENMP="OFF"
    ;;
  *)
    NPROC="$(nproc 2>/dev/null || echo 2)"
    OPENMP="ON"
    ;;
esac

echo "==> 1/4 Системные зависимости"
if [[ "$OS" == "Darwin" ]]; then
  if command -v brew >/dev/null; then
    brew install cmake git curl python >/dev/null 2>&1 || true
  else
    echo "   ⚠️  Homebrew не найден — поставь его (https://brew.sh)"
    echo "       или зависимости вручную: cmake git python3 (+ Xcode Command Line Tools)"
  fi
elif command -v apt-get >/dev/null; then
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
  -DGGML_OPENMP="$OPENMP" \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF
cmake --build "$ROOT/vendor/llama.cpp/build" --config Release --target llama-server -j "$NPROC"

echo "==> 3/4 Python-окружение"
PY="python3"
command -v python3 >/dev/null || PY="python"
"$PY" -m venv "$ROOT/.venv"
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
