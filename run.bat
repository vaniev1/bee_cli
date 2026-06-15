@echo off
rem Запуск Bee CLI на Windows (двойной клик или из cmd).
rem   run.bat            — чат
rem   run.bat bench      — бенчмарк
rem   run.bat --llm-url http://127.0.0.1:8080
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem Роутер через LLM висит секунды на слабом CPU — по умолчанию выключен.
if not defined BEE_LLM_ROUTER set "BEE_LLM_ROUTER=0"

"%PY%" "%ROOT%bee.py" %*
