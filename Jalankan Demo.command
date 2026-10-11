#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  print "Jalankan npm run setup terlebih dahulu (Python 3.11/3.12 diperlukan)."
  exit 1
fi
print "Buka http://127.0.0.1:4173 — Ctrl+C untuk menghentikan server."
npm start
