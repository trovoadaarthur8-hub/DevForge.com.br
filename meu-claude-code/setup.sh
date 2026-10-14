#!/usr/bin/env bash
# Instalação no Linux/macOS: cria o ambiente virtual e instala as dependências.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
chmod +x run.sh
echo
echo "Pronto! Abra o arquivo .env e cole sua GEMINI_API_KEY."
echo "Depois, entre na pasta do seu projeto e rode: $(pwd)/run.sh"
