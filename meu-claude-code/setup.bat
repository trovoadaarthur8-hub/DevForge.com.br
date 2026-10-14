@echo off
REM Instalacao no Windows: cria o ambiente virtual e instala as dependencias.
cd /d %~dp0
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Pronto! Abra o arquivo .env e cole sua GEMINI_API_KEY.
echo Depois, entre na pasta do seu projeto e rode: %~dp0run.bat
