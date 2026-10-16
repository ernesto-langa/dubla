#!/usr/bin/env bash
# Prepara o Dubla depois de clonar: ambiente Python, dependências, modelo de tradução offline e comando `dubla`.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

say() { printf '\033[36m[instalar]\033[0m %s\n' "$*"; }
falta=()
for cmd in python3 ffmpeg ffprobe curl pactl parec pacat; do command -v "$cmd" > /dev/null || falta+=("$cmd"); done
if ((${#falta[@]})); then
  echo "Faltam programas: ${falta[*]}"
  echo "Em Ubuntu/Debian: sudo apt install python3 python3-venv python3-tk ffmpeg curl pulseaudio-utils"
  exit 1
fi

# 1. ambiente Python (.venv)
if [ ! -x .venv/bin/python ]; then
  say "a criar o ambiente Python (.venv)…"
  if command -v uv > /dev/null; then
    uv venv -q .venv
  elif ! python3 -m venv .venv 2> /dev/null; then
    rm -rf .venv
    echo "Não consegui criar o .venv. Instala o python3-venv (sudo apt install python3-venv) ou o uv."
    exit 1
  fi
fi

# 2. dependências
say "a instalar dependências…"
if command -v uv > /dev/null; then
  uv pip install -q --python .venv/bin/python -r requirements.txt
else
  .venv/bin/python -m pip install -q -U pip
  .venv/bin/python -m pip install -q -r requirements.txt
fi

# 3. modelo de tradução offline EN->PT (Argos, ~65 MB)
if [ ! -f modelos/en_pt/model/model.bin ]; then
  say "a descarregar o modelo de tradução offline…"
  mkdir -p modelos
  tmp="$(mktemp -d)"
  curl -fL --retry 10 --retry-all-errors --retry-delay 3 -o "$tmp/en_pt.argosmodel" \
    https://argos-net.com/v1/translate-en_pt-1_9.argosmodel
  .venv/bin/python -I -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
    "$tmp/en_pt.argosmodel" "$tmp"
  rm -rf modelos/en_pt
  mv "$tmp/translate-en_pt-1_9" modelos/en_pt
  rm -rf "$tmp"
fi

# 4. comando `dubla`
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/dubla" "$HOME/.local/bin/dubla"
chmod +x dubla traduzir.py legendas_ao_vivo.py painel.py
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "Aviso: ~/.local/bin não está no PATH; acrescenta-o para usar o comando 'dubla'." ;;
esac

say "pronto. Corre: dubla"
say "(o modelo de transcrição Whisper, ~480 MB, descarrega-se sozinho na primeira tradução)"
