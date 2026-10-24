#!/usr/bin/env python3
"""Dobra qualquer vídeo em inglês para português.

Fluxo: descarregar -> transcrever (Whisper) -> traduzir (Google) -> sintetizar voz (Edge TTS)
-> MP4 com áudio PT (o original fica baixinho por baixo), faixa EN original e legendas PT/EN.

Uso:
  ./traduzir.py URL_OU_FICHEIRO [--nome aula1] [--voz pt-PT-DuarteNeural] [--modelo small.en]

URL_OU_FICHEIRO pode ser: YouTube/Vimeo/etc. (tudo o que o yt-dlp suporta), um link .m3u8/.mp4 direto
(ex.: o src do player Mux numa página Whop) ou um ficheiro local.
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

# corre sempre com o Python do projeto (.venv), mesmo que seja chamado com outro
_VENV_PY = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if _VENV_PY.exists() and Path(sys.prefix).resolve() != _VENV_PY.parent.parent.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

import numpy as np

ROOT = Path(__file__).resolve().parent
# o download do modelo Whisper pela via "xet" pode ficar pendurado sem timeout em redes instáveis
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
SR = 24000  # sample rate da faixa dobrada


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def log(msg):
    print(f"\033[36m[traduzir]\033[0m {msg}", flush=True)


def fmt_ts(t):
    s, ms = divmod(round(t * 1000), 1000)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(path, segs, key):
    with open(path, "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{fmt_ts(s['start'])} --> {fmt_ts(s['end'])}\n{s[key]}\n\n")


# ---------------------------------------------------------------- 0. páginas Whop
WHOP_LESSON = re.compile(r"https?://(?:www\.)?whop\.com/.*/lessons/(lesn_\w+)")
WHOP_QUERY = """query CoreFetchLesson($id: ID!) { retrieveCourseLesson(id: $id) {
  id title embedType embedId muxAsset { playbackId signedPlaybackId signedVideoPlaybackToken } } }"""
EMBEDS = {"youtube": "https://www.youtube.com/watch?v={}", "vimeo": "https://vimeo.com/{}",
          "loom": "https://www.loom.com/share/{}", "wistia": "https://fast.wistia.net/embed/iframe/{}"}


def chrome_profiles():
    """Perfis do Chrome, começando pelo último usado."""
    try:
        state = json.loads((Path.home() / ".config/google-chrome/Local State").read_text())["profile"]
        last = state.get("last_used", "Default")
        return [last] + sorted(p for p in state.get("info_cache", {}) if p != last)
    except (OSError, KeyError, ValueError):
        return ["Default"]


def whop_cookie(profile):
    """Cookies whop.com do perfil, ou None se não houver sessão iniciada."""
    from yt_dlp.cookies import extract_cookies_from_browser

    try:
        jar = extract_cookies_from_browser("chrome", profile, keyring="GNOMEKEYRING")
    except Exception:
        return None
    cookies = {c.name: c.value for c in jar
               if c.value and (c.domain.lstrip(".") == "whop.com" or c.domain.endswith(".whop.com"))}
    if not cookies.get("whop-core.refresh-token"):
        return None
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def resolve_whop(url, profile):
    """Página de aula Whop -> (URL do vídeo, título), usando a sessão do Chrome."""
    import urllib.request

    lesson_id = WHOP_LESSON.match(url).group(1)
    lesson, errors = None, []
    for prof in [profile] if profile else chrome_profiles():
        cookie = whop_cookie(prof)
        if not cookie:
            continue
        log(f"a obter o vídeo da aula Whop {lesson_id} (sessão do Chrome, perfil '{prof}')…")
        req = urllib.request.Request(
            "https://whop.com/api/graphql/CoreFetchLesson",
            data=json.dumps({"query": WHOP_QUERY, "variables": {"id": lesson_id},
                             "operationName": "CoreFetchLesson"}).encode(),
            headers={"content-type": "application/json", "x-whop-app-name": "web", "cookie": cookie,
                     "origin": "https://whop.com", "referer": url,
                     "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/140.0 Safari/537.36"})
        res = json.loads(urllib.request.urlopen(req, timeout=30).read())
        lesson = (res.get("data") or {}).get("retrieveCourseLesson")
        if lesson:
            break
        errors.append(f"{prof}: {(res.get('errors') or [{}])[0].get('message', res)}")
    if not lesson:
        sys.exit("Não consegui aceder à aula com nenhum perfil do Chrome.\n"
                 + "\n".join(errors or ["Nenhum perfil tem sessão Whop iniciada."])
                 + "\nInicia sessão no Whop no Chrome (ou indica o perfil com --perfil-chrome).")
    mux = lesson.get("muxAsset") or {}
    if mux.get("signedPlaybackId"):
        media = f"https://stream.mux.com/{mux['signedPlaybackId']}.m3u8?token={mux['signedVideoPlaybackToken']}"
    elif mux.get("playbackId"):
        media = f"https://stream.mux.com/{mux['playbackId']}.m3u8"
    elif lesson.get("embedType") in EMBEDS and lesson.get("embedId"):
        media = EMBEDS[lesson["embedType"]].format(lesson["embedId"])
    else:
        sys.exit(f"A aula '{lesson['title']}' não tem vídeo reconhecido (embedType={lesson.get('embedType')}).")
    return media, lesson["title"]


# ---------------------------------------------------------------- 1. download
def download(src, work):
    out = work / "original.mp4"
    if out.exists():
        return out
    if Path(src).exists():
        run(["ffmpeg", "-y", "-i", src, "-c", "copy", str(out)])
        return out
    log("a descarregar o vídeo…")
    subprocess.run([str(ROOT / ".venv/bin/yt-dlp"), "-q", "--progress",
                    "-f", "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
                    # rede instável: insiste em vez de deixar buracos no vídeo
                    "--retries", "infinite", "--fragment-retries", "infinite",
                    "--retry-sleep", "exp=1:30", "--socket-timeout", "30",
                    "--abort-on-unavailable-fragments", "-N", "4",
                    "--merge-output-format", "mp4", "-o", str(work / "original.%(ext)s"), src], check=True)
    return out


# ---------------------------------------------------------------- 2. transcrição
def transcribe(video, work, model_name):
    cache = work / "segmentos_en.json"
    if cache.exists():
        return json.loads(cache.read_text())
    from faster_whisper import WhisperModel

    log(f"a transcrever com Whisper '{model_name}' (CPU, pode demorar)…")
    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         cpu_threads=max(4, (os.cpu_count() or 4) - 2))
    raw, info = model.transcribe(str(video), language="en", vad_filter=True,
                                 word_timestamps=True, beam_size=1)
    words = []
    for seg in raw:
        print(f"\r  {fmt_ts(seg.end)[:8]} / {fmt_ts(info.duration)[:8]}", end="", flush=True)
        words += [{"w": w.word, "s": w.start, "e": w.end} for w in seg.words]
    print()

    segs = group_sentences(words)
    cache.write_text(json.dumps(segs, ensure_ascii=False, indent=1))
    return segs


def group_sentences(words):
    """Junta palavras em frases (cortes em . ? ! ou pausas), máx ~12 s por bloco."""
    segs, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        dur = w["e"] - cur[0]["s"]
        end_sent = re.search(r"[.?!]$", w["w"].strip())
        pause = nxt and nxt["s"] - w["e"] > 0.8
        if not nxt or (end_sent and dur > 2.5) or pause or dur > 12:
            text = "".join(x["w"] for x in cur).strip()
            if text:
                segs.append({"start": cur[0]["s"], "end": w["e"], "en": text})
            cur = []
    return segs


# ---------------------------------------------------------------- 3. tradução
LOCAL_MODEL = ROOT / "modelos" / "en_pt"  # modelo Argos EN->PT (CTranslate2 + SentencePiece)


def translate_local(texts):
    import ctranslate2
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor(model_file=str(LOCAL_MODEL / "sentencepiece.model"))
    tr = ctranslate2.Translator(str(LOCAL_MODEL / "model"), device="cpu", compute_type="int8")
    res = tr.translate_batch([sp.encode(t, out_type=str) for t in texts], beam_size=4, max_batch_size=16)
    return ["".join(r.hypotheses[0]).replace("▁", " ").strip() for r in res]


def translate(segs, work, engine):
    cache = work / "segmentos_pt.json"
    if cache.exists():
        return json.loads(cache.read_text())

    log(f"a traduzir {len(segs)} frases…")
    if engine == "google":
        try:
            out = translate_google(segs)
        except Exception as e:
            if not LOCAL_MODEL.exists():
                raise
            why = "pede captcha" if isinstance(e, GoogleBlocked) else type(e).__name__
            log(f"Google indisponível ({why}); a usar o tradutor local")
            engine = "local"
    if engine == "local":
        out = [{**s, "pt": pt} for s, pt in zip(segs, translate_local([s["en"] for s in segs]))]
    (work / "tradutor_usado.txt").write_text(engine)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


# --- Google Tradutor com as cookies do Chrome (para aproveitar o captcha resolvido no navegador)
GOOGLE_TEST_URL = "https://translate.google.com/m?sl=en&tl=pt&hl=pt&q=hello"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


class GoogleBlocked(Exception):
    """O Google respondeu com a página de verificação (captcha)."""


def google_cookie():
    """Cookies google.com do Chrome; prefere o perfil onde o captcha foi resolvido."""
    from yt_dlp.cookies import extract_cookies_from_browser

    best = None
    for prof in chrome_profiles():
        try:
            jar = extract_cookies_from_browser("chrome", prof, keyring="GNOMEKEYRING")
        except Exception:
            continue
        cookies = {c.name: c.value for c in jar if c.value and
                   (c.domain.lstrip(".") in ("google.com", "translate.google.com"))}
        if "GOOGLE_ABUSE_EXEMPTION" in cookies:
            return "; ".join(f"{k}={v}" for k, v in cookies.items())
        best = best or cookies
    return "; ".join(f"{k}={v}" for k, v in (best or {}).items())


def google_translate_text(text, cookie):
    import html
    import urllib.parse
    import urllib.request

    url = "https://translate.google.com/m?" + urllib.parse.urlencode(
        {"sl": "en", "tl": "pt", "hl": "pt", "q": text})
    req = urllib.request.Request(url, headers={"user-agent": UA, "cookie": cookie})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            final, page = r.geturl(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 429 or "/sorry/" in (e.headers.get("location") or e.geturl() or ""):
            raise GoogleBlocked() from e
        raise
    if "/sorry/" in final:
        raise GoogleBlocked()
    m = re.search(r'<div class="result-container">(.*?)</div>', page, re.S)
    if not m:
        raise RuntimeError("resposta do Google sem tradução")
    return html.unescape(m.group(1))


def google_status():
    """Usado pelo painel: imprime {"estado": "ok"|"captcha"|"erro", ...}."""
    try:
        txt = google_translate_text("hello", google_cookie())
        print(json.dumps({"estado": "ok", "teste": txt}))
    except GoogleBlocked:
        print(json.dumps({"estado": "captcha", "url": GOOGLE_TEST_URL}))
    except Exception as e:
        print(json.dumps({"estado": "erro", "erro": f"{type(e).__name__}: {e}"[:200]}))


def translate_google(segs):
    cookie = google_cookie()
    # envia em lotes separados por linha para poupar pedidos
    batch, out = [], []

    def call(text):
        # o Google limita pedidos por segundo: espaça e, se falhar, espera um pouco mais;
        # captcha não se resolve a esperar, por isso desiste logo
        for attempt in range(3):
            time.sleep(1)
            try:
                return google_translate_text(text, cookie)
            except GoogleBlocked:
                raise
            except Exception as e:
                if attempt == 2:
                    raise
                log(f"Google falhou ({type(e).__name__}); nova tentativa em {10 * (attempt + 1)}s…")
                time.sleep(10 * (attempt + 1))

    def flush():
        if not batch:
            return
        lines = call("\n".join(s["en"] for s in batch)).split("\n")
        if len(lines) != len(batch):  # o tradutor juntou/partiu linhas: traduz uma a uma
            lines = [call(s["en"]) for s in batch]
        for s, l in zip(batch, lines):
            out.append({**s, "pt": l.strip()})
        batch.clear()

    size = 0
    for s in segs:
        if size + len(s["en"]) > 1500:
            flush()
            size = 0
        batch.append(s)
        size += len(s["en"]) + 1
    flush()
    return out


# ---------------------------------------------------------------- 4. voz
async def _tts_all(segs, tts_dir, voice, rate):
    import edge_tts

    sem = asyncio.Semaphore(6)

    async def one(i, s):
        mp3 = tts_dir / f"{i:05}.mp3"
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        async with sem:
            for attempt in range(4):
                try:
                    await edge_tts.Communicate(s["pt"], voice, rate=rate).save(str(mp3))
                    return
                except Exception as e:  # rede instável: tenta outra vez
                    if attempt == 3:
                        raise
                    await asyncio.sleep(2 * (attempt + 1))

    await asyncio.gather(*(one(i, s) for i, s in enumerate(segs)))


def load_wav(path, tempo=1.0):
    """Converte para wav mono 24 kHz (acelerando com atempo se preciso) e devolve float32."""
    tmp = path.with_suffix(".wav")
    af = ["-filter:a", f"atempo={tempo:.3f}"] if tempo > 1.01 else []
    run(["ffmpeg", "-y", "-i", str(path), *af, "-ac", "1", "-ar", str(SR), str(tmp)])
    with wave.open(str(tmp)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    tmp.unlink()
    return data.astype(np.float32) / 32768


def fit(segs, i, cursor, n, track_len):
    """Onde começa a fala i (em amostras) e quanto acelerá-la para caber até à frase seguinte.

    Nunca começa antes do fim da fala anterior (cursor); se não cabe, acelera até 1.5x."""
    start = max(int(segs[i]["start"] * SR), cursor)
    nxt = int(segs[i + 1]["start"] * SR) if i + 1 < len(segs) else track_len
    slot = max(nxt - start, int(0.5 * SR))
    return start, (min(n / slot, 1.5) if n > slot else 1.0)


def synthesize(segs, work, voice, rate, total_dur):
    out = work / "dobragem_pt.wav"
    if out.exists():
        return out
    tts_dir = work / "tts"
    tts_dir.mkdir(exist_ok=True)
    log(f"a gerar voz PT ({voice}) para {len(segs)} frases…")
    asyncio.run(_tts_all(segs, tts_dir, voice, rate))

    log("a alinhar a voz com o vídeo…")
    track = np.zeros(int((total_dur + 5) * SR), dtype=np.float32)
    cursor = 0  # fim da última fala colocada (evita sobreposições)
    for i, s in enumerate(segs):
        audio = load_wav(tts_dir / f"{i:05}.mp3")
        start, tempo = fit(segs, i, cursor, len(audio), len(track))
        if tempo > 1:
            audio = load_wav(tts_dir / f"{i:05}.mp3", tempo=tempo)
        end = min(start + len(audio), len(track))
        track[start:end] += audio[: end - start]
        cursor = end
    track = np.clip(track, -1, 1)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((track * 32767).astype(np.int16).tobytes())
    return out


# ---------------------------------------------------------------- 5. montagem
def mux(video, dub, srt_pt, srt_en, final, bg_volume):
    log("a montar o MP4 final…")
    run(["ffmpeg", "-y", "-i", str(video), "-i", str(dub), "-i", str(srt_pt), "-i", str(srt_en),
         "-filter_complex",
         f"[0:a]volume={bg_volume}[bg];[1:a]volume=1.6[v];[bg][v]amix=inputs=2:duration=first:normalize=0[pt]",
         "-map", "0:v", "-map", "[pt]", "-map", "0:a", "-map", "2", "-map", "3",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text",
         "-metadata:s:a:0", "language=por", "-metadata:s:a:0", "title=Português (dobrado)",
         "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=English (original)",
         "-metadata:s:s:0", "language=por", "-metadata:s:s:1", "language=eng",
         "-disposition:a:0", "default", "-disposition:a:1", "0",
         "-disposition:s:0", "0", "-disposition:s:1", "0", str(final)])


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="URL (YouTube, .m3u8, …) ou ficheiro local")
    ap.add_argument("--nome", default=None, help="nome da pasta de saída em videos/")
    ap.add_argument("--voz", default="pt-BR-AntonioNeural",
                    help="voz Edge TTS (ex.: pt-BR-FranciscaNeural, pt-PT-DuarteNeural, pt-PT-RaquelNeural)")
    ap.add_argument("--velocidade", default="+10%", help="ritmo base da voz (ex.: +0%%, +15%%)")
    ap.add_argument("--modelo", default="small.en", help="modelo Whisper: base.en, small.en, medium.en")
    ap.add_argument("--fundo", type=float, default=0.12, help="volume do áudio original por baixo (0 = mudo)")
    ap.add_argument("--tradutor", choices=["google", "local"], default="google",
                    help="google (online; se recusar, passa ao local) ou local (offline, modelos/en_pt)")
    ap.add_argument("--perfil-chrome", default=None,
                    help="perfil do Chrome com sessão Whop (por omissão o último usado)")
    a = ap.parse_args()

    src, title = a.src, Path(a.src.split("?")[0]).stem
    already = a.nome and (ROOT / "videos" / a.nome / "original.mp4").exists()
    if WHOP_LESSON.match(src) and not already:
        src, title = resolve_whop(src, a.perfil_chrome)
    name = a.nome or re.sub(r"[^\w-]+", "_", title).strip("_")[:40] or "video"
    work = ROOT / "videos" / name
    work.mkdir(parents=True, exist_ok=True)

    video = download(src, work)
    segs = translate(transcribe(video, work, a.modelo), work, a.tradutor)
    srt_pt, srt_en = work / "legendas_pt.srt", work / "legendas_en.srt"
    write_srt(srt_pt, segs, "pt")
    write_srt(srt_en, segs, "en")
    dub = synthesize(segs, work, a.voz, a.velocidade, duration(video))
    final = work / f"{name}_PT.mp4"
    mux(video, dub, srt_pt, srt_en, final, a.fundo)
    log(f"pronto: {final}")
    log(f"ver:   vlc '{final}'   (Áudio > Faixa para trocar PT/EN; Legendas > Faixa)")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"erro em {e.cmd[0]}: {(e.stderr or b'').decode()[-800:]}")
