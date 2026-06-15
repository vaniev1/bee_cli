# Запуск Bee CLI на Windows (CLI сам поднимает llama-server).
#   .\run.ps1            — чат
#   .\run.ps1 bench      — бенчмарк
#   .\run.ps1 --llm-url http://127.0.0.1:8080   — подключиться к запущенному движку
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py   = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

# Роутер через LLM — отдельный inference-вызов, на слабом CPU висит секунды.
# Включи BEE_LLM_ROUTER=1, если нужен умный роутинг и железо позволяет.
if (-not $env:BEE_LLM_ROUTER) { $env:BEE_LLM_ROUTER = "0" }

& $Py (Join-Path $Root "bee.py") @args
