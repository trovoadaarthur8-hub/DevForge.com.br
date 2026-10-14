#!/usr/bin/env bash
# Roda o agente na pasta ATUAL do terminal (a pasta do seu projeto).
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec "$DIR/.venv/bin/python" "$DIR/agent.py" "$@"
