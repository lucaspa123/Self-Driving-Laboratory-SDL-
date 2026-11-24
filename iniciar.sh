#!/bin/sh
# Abre el programa del SDL en Linux o macOS. La primera vez instala lo necesario.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python iniciar.py "$@"
