#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
print "Demo iDeb Verify — buka http://127.0.0.1:4173"
print "Tekan Ctrl+C untuk menghentikan server."
node server.mjs
