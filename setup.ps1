#Requires -Version 5.0
# Установка Bee CLI на Windows:
#   1) проверка зависимостей (git, cmake, python; компилятор C++ из Visual Studio)
#   2) сборка llama-server из форка PrismML (CPU, MSVC Release)
#   3) python venv + зависимости
#   4) скачивание модели Bonsai-8B
#
# Запуск (из PowerShell в папке проекта):
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"

$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$ForkUrl  = "https://github.com/PrismML-Eng/llama.cpp"
$ModelUrl = "https://huggingface.co/prism-ml/Bonsai-8B-gguf/resolve/main/Bonsai-8B-Q1_0.gguf"

function Need-Cmd($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
    Write-Host "   ✗ не найден '$cmd' — $hint" -ForegroundColor Red
    exit 1
  }
}

Write-Host "==> 1/4 Проверка зависимостей"
Need-Cmd git   "поставь Git: winget install Git.Git  (или https://git-scm.com/download/win)"
Need-Cmd cmake "поставь CMake: winget install Kitware.CMake  (или https://cmake.org/download)"
$Py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
Need-Cmd $Py   "поставь Python 3: winget install Python.Python.3.12  (или https://python.org)"
Write-Host "   ℹ Для сборки нужен компилятор C++: Visual Studio Build Tools" -ForegroundColor DarkGray
Write-Host "     (workload 'Desktop development with C++'):" -ForegroundColor DarkGray
Write-Host "     winget install Microsoft.VisualStudio.2022.BuildTools" -ForegroundColor DarkGray

Write-Host "==> 2/4 Сборка llama-server (форк PrismML, CPU)"
$Vendor = Join-Path $Root "vendor\llama.cpp"
if (-not (Test-Path $Vendor)) {
  git clone --depth 1 $ForkUrl $Vendor
}
$Build = Join-Path $Vendor "build"
cmake -S $Vendor -B $Build `
  -DCMAKE_BUILD_TYPE=Release `
  -DLLAMA_CURL=OFF `
  -DGGML_NATIVE=ON `
  -DGGML_OPENMP=ON `
  -DLLAMA_BUILD_TESTS=OFF `
  -DLLAMA_BUILD_EXAMPLES=OFF
cmake --build $Build --config Release --target llama-server

Write-Host "==> 3/4 Python-окружение"
$Venv   = Join-Path $Root ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
& $Py -m venv $Venv
& $VenvPy -m pip install -q --upgrade pip
& $VenvPy -m pip install -q -r (Join-Path $Root "requirements.txt")

Write-Host "==> 4/4 Модель Bonsai-8B (~1.2 ГБ)"
$Models = Join-Path $Root "models"
New-Item -ItemType Directory -Force -Path $Models | Out-Null
$Model = Join-Path $Models "Bonsai-8B-Q1_0.gguf"
if (-not (Test-Path $Model)) {
  # curl.exe есть в Windows 10/11 из коробки; даёт прогресс и докачку
  curl.exe -L --fail -o $Model $ModelUrl
} else {
  Write-Host "   модель уже на месте"
}

Write-Host ""
Write-Host "✅ Готово. Запуск:  .\run.ps1           (чат)" -ForegroundColor Green
Write-Host "                    .\run.ps1 bench     (бенчмарк)"
