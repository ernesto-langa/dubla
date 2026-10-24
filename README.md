# Dubla

**English** · [Português](README.pt.md)

Watch English videos in Portuguese: PT voice dubbing, subtitles and real-time translation.
Runs locally with Whisper.

```bash
dubla                         # open the dashboard in the browser (starts it if needed)
dubla "LINK" --nome aula08    # translate a video straight from the terminal
dubla aovivo --voz            # live subtitles + PT voice
dubla ajuda                   # help
```

> The interface and command-line options are in Portuguese (`--nome` = name, `--voz` = voice,
> `aovivo` = live, `ajuda` = help).

## Features

- **Full dubbing**: turns a video into an MP4 with a Portuguese voice track, the original English track and PT/EN subtitles.
- **Live subtitles**: translates whatever audio is playing on the computer (any website or app), with optional PT voice.
- **Local web dashboard**: manage translations, watch the videos, read the EN/PT transcript side by side.
- **Whop lessons**: accepts the lesson page link and uses your Chrome session to get the video.
- **Offline translation**: if Google Translate is unavailable, falls back to a local model.

## Install

Linux with PulseAudio (tested on Ubuntu 22.04). Requires `python3` (≥ 3.10, with `tkinter`), `ffmpeg`,
`curl` and `pulseaudio-utils`; [`uv`](https://github.com/astral-sh/uv) is optional but speeds up installation.

```bash
git clone https://github.com/ernesto-langa/dubla.git && cd dubla
./instalar.sh
```

`instalar.sh` creates `.venv`, installs the dependencies, downloads the offline translation model (`modelos/en_pt`)
and puts the `dubla` command in `~/.local/bin`. The Whisper transcription model (~480 MB) downloads automatically on
the first translation. If you move the folder, delete `.venv` and run `./instalar.sh` again.

## Dashboard (the easiest way)

```bash
dubla        # or ./painel.py — opens http://localhost:8765
```

- paste the lesson link, pick the voice and translator and click **Traduzir** (a name like `aulaNN` is suggested);
- list of lessons with live status and progress: **Ver** (player with PT/EN subtitles), **VLC** (to switch to the
  English audio), **Transcrição** (EN and PT side by side, searchable), **Mudar voz** (change voice), **Retomar**
  (resume), **Parar** (stop), **Registo** (log), **Pasta** (folder), **Apagar** (delete, asks for a second click);
- turn **live subtitles** on and off, with or without voice.

**Google Translate blocked (captcha):** the dashboard shows Google's status at the top. If it asks for verification,
click **Abrir captcha**, solve it in Chrome, wait ~30 s and click **Verificar outra vez**: the script uses Chrome's
cookies, so it reuses the authorization. Lessons translated offline get a **Retraduzir com Google** button (redoes
only the translation, voice and MP4).

Translations run independently: closing the dashboard (Ctrl+C) or the browser does not stop them.
The dashboard only accepts connections from this computer.

## Live subtitles

```bash
dubla aovivo
```

Opens a subtitle bar on top of all windows and translates **whatever audio is playing on the computer**
(Whop, YouTube, VLC, a call…). Shows the PT text prominently, the previous sentence in grey and the English below.
Subtitles appear while the person speaks and become final ~2–4 s after the sentence ends.

- drag with the mouse: move · mouse wheel: font size · Esc or double-click: close
- `--sem-ingles` hides the original text; `--letra 32` sets the initial font size
- `--modelo small.en` is more accurate but slower (default `base.en`)
- everything subtitled is saved to `ao_vivo/<date>.txt`
- transcription and translation are offline (no Google needed)

### With PT voice

```bash
dubla aovivo --voz                                   # pt-BR-AntonioNeural
dubla aovivo --voz pt-PT-RaquelNeural --volume-original 0.15
```

While it is on, application audio goes through a virtual output "Traducao_EN": the English is captured there and
still plays quietly (`--volume-original`, 25% by default); the PT voice goes straight to the speakers, so it is not
captured again. When you turn it off, everything goes back to the normal output.

The voice uses Edge TTS (needs internet) and speaks each sentence ~3–5 s after the English. If it falls behind, it
speaks faster and, if needed, skips old sentences to stay in sync.

## Full dubbing (MP4 with PT voice)

```bash
dubla "URL" --nome aula02
vlc videos/aula02/aula02_PT.mp4
```

The MP4 contains:
- **Portuguese dubbed** audio (default track; the original English plays quietly underneath);
- the **original English** track;
- **PT** and **EN** subtitles (also as separate `.srt` files).

Everything goes to `videos/<name>/`. If the process is interrupted, running it again resumes from the last step.

The `URL` can be:
- **a Whop lesson page** (`https://whop.com/.../lessons/lesn_...`): the script uses your Chrome session to ask Whop
  for the video link (it tries Chrome profiles until it finds one that is signed in). Without `--nome`, it uses the
  lesson title;
- YouTube, Vimeo, etc. (anything `yt-dlp` supports);
- a local file;
- a direct `.m3u8`/`.mp4` link.

### Options

| option | default | notes |
|---|---|---|
| `--nome` | title / file name | output folder inside `videos/` |
| `--voz` | `pt-BR-AntonioNeural` | `pt-BR-FranciscaNeural`, `pt-PT-DuarteNeural`, `pt-PT-RaquelNeural` |
| `--velocidade` | `+10%` | base speech rate |
| `--modelo` | `small.en` | `base.en` (faster), `medium.en` (more accurate, slower) |
| `--fundo` | `0.12` | volume of the English under the dub; `0` to mute |
| `--tradutor` | `google` | `google` (falls back to offline on failure) or `local` |
| `--perfil-chrome` | all, starting with the last used | Chrome profile signed in to Whop |

### Alternative: bookmarklet to copy the video link

Useful for other sites with a Mux player. Create a Chrome bookmark and paste this into the URL field:

```
javascript:(()=>{const v=document.querySelector('mux-player,mux-video,video');const s=v&&(v.getAttribute('src')||v.src);if(!s||s.startsWith('blob:')){alert('Vídeo não encontrado (espera que o player carregue)');return}navigator.clipboard.writeText(s).then(()=>alert('Link do vídeo copiado'))})()
```

Open the lesson, click the bookmark, then run `dubla "<paste>" --nome aulaXX`. The link contains a token that
expires, so use it right away.

## How it works

yt-dlp (download) → faster-whisper on CPU (word-timestamped transcription, grouped into sentences) →
Google Translate (with Chrome's cookies) or offline Argos/CTranslate2 model → Edge TTS (neural voice) →
each sentence is placed at the moment it is spoken and sped up to 1.5x if it does not fit → ffmpeg muxes everything.

## Tests

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt   # or .venv/bin/pip install -r …
.venv/bin/python -m pytest
```

## Privacy and use

- Videos, translations and lesson links are stored in `videos/`, which `.gitignore` excludes. They are course
  content: use them for personal purposes only and do not share them.
- Chrome cookies are read locally (via the GNOME keyring) and only sent to their own site (whop.com, google.com).
- The dashboard only listens on `127.0.0.1`.
