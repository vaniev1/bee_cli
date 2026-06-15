# 🐝 Bee CLI

Терминальная версия локального ассистента **Bee**: та же нейросеть и логика,
что в десктопе — LLM-роутер, двухфазный режим размышлений, поиск с пересказом —
но в CLI и со **снятием метрик**: токены/сек, время до первого токена, время
роутера, пиковая RAM.

Работает локально и без GPU на любой ОС: **Linux** (в т.ч. headless-VPS),
**macOS**, **Windows**.

## Зачем

Прогнать Bonsai-8B на CPU и увидеть реальные цифры конкретного железа: сколько
tok/s выдаёт, сколько ест памяти, как быстро отвечает. Удобно сравнивать машины
и собирать наглядный HTML-отчёт.

## Установка

Любой установщик делает одно и то же: собирает `llama-server` из
[форка PrismML](https://github.com/PrismML-Eng/llama.cpp) (в нём кернелы Q1_0,
на CPU), создаёт `.venv` с зависимостями и качает модель (~1.2 ГБ).

**Linux (Debian/Ubuntu) и macOS:**

```bash
./setup.sh
```

- Linux — системные пакеты ставятся через `apt`.
- macOS — зависимости (`cmake`, `git`, `python`) ставятся через Homebrew;
  сборка идёт без OpenMP (у Apple clang его нет — llama.cpp использует свой
  threadpool). Нужны Xcode Command Line Tools (`xcode-select --install`).

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Нужны `git`, `cmake`, `python` и компилятор C++ из **Visual Studio Build Tools**
(workload «Desktop development with C++»). Установщик подскажет команды `winget`,
если чего-то не хватает.

## Запуск

**Linux / macOS:**

```bash
./run.sh                  # интерактивный чат
./run.sh bench            # бенчмарк по набору промптов → таблица + bench_result.json
./run.sh --llm-url URL    # подключиться к уже запущенному llama-server
```

**Windows:**

```powershell
.\run.ps1                 # чат   (или двойной клик по run.bat)
.\run.ps1 bench           # бенчмарк
.\run.ps1 --llm-url URL   # подключиться к запущенному llama-server
```

CLI сам поднимает `llama-server`, ждёт загрузку модели и гасит его на выходе.

### Команды в чате

```
/stats   — средние метрики за сессию
/reset   — очистить историю диалога
/quit    — выход (или Ctrl-D)
```

## Метрики

После каждого ответа — строка вида:

```
⏱ 4.1s  ·  12.3 tok/s  ·  TTFT 1.4s  ·  роутер 0.5s  ·  prefill 48 tok/s  ·  168 ток  ·  RAM 1.42 ГБ
```

| Метрика | Что значит |
|---|---|
| `tok/s` | скорость генерации (из timings llama-server; `~` — оценка) |
| `TTFT` | время до первого токена ответа (включая роутер и фазу размышлений) |
| `роутер` | время решения LLM-роутера (отдельный вызов модели) |
| `prefill` | скорость обработки промпта |
| `RAM` | пик резидентной памяти llama-server за ход |

`bench` пишет сырые замеры в `bench_result.json` и сразу генерит самодостаточный
**`report.html`** — шапка о железе, карточки средних, гистограмма tok/s и
таблица. Открой его двойным кликом.

Если бенчмарк гонялся на удалённом сервере — сначала забери отчёт:

```bash
scp user@server:~/bee_cli/report.html .
```

Перегенерить отчёт из готового JSON отдельно: `python report.py bench_result.json`.

## Конфигурация (env)

| Переменная | По умолчанию |
|---|---|
| `BEE_LLAMA_SERVER` | `vendor/llama.cpp/build/bin/llama-server` (Windows: `…/build/bin/Release/llama-server.exe`) |
| `BEE_MODEL` | `models/Bonsai-8B-Q1_0.gguf` |
| `BEE_CTX` | `8192` |
| `BEE_THREADS` | число ядер |

Путь к бинарю определяется автоматически под ОС; задавай `BEE_LLAMA_SERVER`
только если бинарь лежит нестандартно.

## Требования

- **RAM:** 4 ГБ комфортно (модель ~1.2 ГБ + контекст + процессы). На 2 ГБ — впритык.
- **CPU:** скорость генерации почти линейно зависит от частоты ядра.
- **Диск:** ~3 ГБ под модель и сборку llama.cpp.

## Структура

```
bee_cli/
├── bee.py          # точка входа: чат / bench, спавн llama-server
├── worker.py       # клиент llama-server + двухфазное мышление
├── router.py       # LLM-роутер (+ fallback по ключевым словам)
├── agents.py       # time + search
├── pipeline.py     # один ход диалога со сбором метрик
├── metrics.py      # tok/s, TTFT, RAM, агрегаты сессии
├── llama.py        # запуск/контроль llama-server (кроссплатформенно)
├── ui.py           # терминальный REPL (rich)
├── setup.sh        # установка: Linux + macOS
├── setup.ps1       # установка: Windows
├── run.sh          # запуск: Linux + macOS
├── run.ps1         # запуск: Windows (PowerShell)
└── run.bat         # запуск: Windows (cmd / двойной клик)
```

## Заметки

- Календарный агент опущен (он macOS-only).
- Поиск ходит в DuckDuckGo — единственный исходящий трафик, только когда
  роутер выбрал агента поиска.
- Кастомный jinja-шаблон не нужен: режим размышлений реализован поверх
  сырого `/completion`, а роутер/обычный чат используют вшитый в GGUF шаблон.
```
