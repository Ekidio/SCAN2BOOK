#!/bin/zsh
# Dupla kattintással indítható (macOS)
cd "$(dirname "$0")"
exec ./.venv/bin/python app.py
