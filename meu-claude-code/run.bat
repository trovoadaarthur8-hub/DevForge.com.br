@echo off
REM Roda o agente na pasta ATUAL do terminal (a pasta do seu projeto).
"%~dp0.venv\Scripts\python.exe" "%~dp0agent.py" %*
