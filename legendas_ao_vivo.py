#!/usr/bin/env python3
"""Legendas PT em tempo real para qualquer áudio em inglês que esteja a tocar no computador.

Captura o som de saída (o que ouves nas colunas/auscultadores), transcreve com Whisper,
traduz offline e mostra as legendas numa faixa por cima de todas as janelas.

Uso:
  ./legendas_ao_vivo.py                 # PT grande + EN pequeno por baixo
  ./legendas_ao_vivo.py --sem-ingles    # só PT
  ./legendas_ao_vivo.py --modelo small.en  # mais preciso, mas com mais atraso
  ./legendas_ao_vivo.py --voz              # também lê a tradução em voz alta (pt-BR-AntonioNeural)
  ./legendas_ao_vivo.py --voz pt-PT-RaquelNeural --volume-original 0.15

Com --voz, o som dos vídeos passa por uma saída virtual ("Tradução EN"): é dali que se capta o inglês,
que continua a ouvir-se baixinho; a voz PT vai direta às colunas e por isso não é captada de novo.
Ao fechar, tudo volta à saída normal.

Na faixa: arrastar com o rato para mover, roda do rato para mudar o tamanho da letra,
Esc ou duplo clique para fechar.
"""
import argparse
import asyncio
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

# corre sempre com o Python do projeto (.venv), mesmo que seja chamado com outro
_VENV_PY = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if _VENV_PY.exists() and Path(sys.prefix).resolve() != _VENV_PY.parent.parent.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

import numpy as np

ROOT = Path(__file__).resolve().parent
SR = 16000
STOP = threading.Event()  # pedido de paragem (Ctrl+C / painel); a janela fecha-se no próximo ciclo
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


# ---------------------------------------------------------------- captura de áudio
def default_monitor():
    sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True).stdout.strip()
    return f"{sink}.monitor"


def pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True).stdout.strip()


class AudioRouter:
    """Desvia o som das aplicações para uma saída virtual, captável sem apanhar a nossa voz."""

    SINK = "traducao_ingles"

    def __init__(self, original_volume):
        self.cleanup_leftovers()
        self.real = pactl("get-default-sink")
        self.null_mod = pactl("load-module", "module-null-sink", f"sink_name={self.SINK}",
                              "sink_properties=device.description=Traducao_EN")
        self.loop_mod = pactl("load-module", "module-loopback", f"source={self.SINK}.monitor",
                              f"sink={self.real}", "latency_msec=60")
        for line in pactl("list", "short", "sink-inputs").splitlines():
            idx, _sink, owner = line.split("\t")[:3]
            if owner == self.loop_mod:  # o inglês original continua audível, mas baixinho
                pactl("set-sink-input-volume", idx, f"{int(original_volume * 100)}%")
            else:                       # o que já está a tocar passa para a saída virtual
                pactl("move-sink-input", idx, self.SINK)
        pactl("set-default-sink", self.SINK)
        self.monitor = f"{self.SINK}.monitor"

    @classmethod
    def cleanup_leftovers(cls):
        """Se uma execução anterior caiu sem limpar, repõe a saída normal."""
        sinks = dict(l.split("\t")[1::-1][:2] for l in pactl("list", "short", "sinks").splitlines())
        if cls.SINK not in sinks:
            return
        real = next((n for n in sinks if n != cls.SINK), None)
        if real and pactl("get-default-sink") == cls.SINK:
            pactl("set-default-sink", real)
        for line in pactl("list", "short", "modules").splitlines():
            if cls.SINK in line:
                pactl("unload-module", line.split("\t")[0])

    def close(self):
        pactl("set-default-sink", self.real)
        sinks = {l.split("\t")[1]: l.split("\t")[0] for l in pactl("list", "short", "sinks").splitlines()}
        null_idx = sinks.get(self.SINK)
        for line in pactl("list", "short", "sink-inputs").splitlines():
            idx, sink, owner = line.split("\t")[:3]
            if sink == null_idx and owner != self.loop_mod:
                pactl("move-sink-input", idx, self.real)
        pactl("unload-module", self.loop_mod)
        pactl("unload-module", self.null_mod)


class Speaker:
    """Lê as frases traduzidas com Edge TTS, direto nas colunas reais.

    Sintetiza a frase seguinte enquanto toca a atual; se ficar para trás, fala mais depressa
    e, em último caso, salta frases antigas para não perder a sincronia com o vídeo.
    """

    def __init__(self, voice, sink):
        self.voice, self.sink = voice, sink
        self.texts = queue.Queue()
        self.audio = queue.Queue(maxsize=2)
        threading.Thread(target=self.synth_loop, daemon=True).start()
        threading.Thread(target=self.play_loop, daemon=True).start()

    def say(self, text):
        self.texts.put(text)

    def synth_loop(self):
        import edge_tts

        async def synth(text, rate):
            data = b""
            async for chunk in edge_tts.Communicate(text, self.voice, rate=rate).stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return data

        while True:
            text = self.texts.get()
            while self.texts.qsize() > 2:  # muito atrasado: salta para as frases recentes
                text = self.texts.get()
            backlog = self.texts.qsize() + self.audio.qsize()
            rate = f"+{10 + 15 * min(backlog, 3)}%"
            try:
                self.audio.put(asyncio.run(synth(text, rate)))
            except Exception as e:
                print(f"voz falhou: {e}", file=sys.stderr, flush=True)

    def play_loop(self):
        while True:
            mp3 = self.audio.get()
            dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                                    "-ar", "24000", "pipe:1"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            play = subprocess.Popen(["pacat", f"--device={self.sink}", "--format=s16le", "--rate=24000",
                                     "--channels=1", "--client-name=traducao-voz"], stdin=dec.stdout)
            dec.stdout.close()
            dec.communicate(mp3)
            play.wait()


class Capture(threading.Thread):
    """Lê o som de saída do sistema (16 kHz mono) para um buffer partilhado."""

    def __init__(self, source):
        super().__init__(daemon=True)
        self.proc = subprocess.Popen(
            ["parec", f"--device={source}", "--format=s16le", f"--rate={SR}", "--channels=1",
             "--latency-msec=100"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.lock = threading.Lock()
        self.buf = np.zeros(0, dtype=np.float32)

    def run(self):
        while True:
            data = self.proc.stdout.read(SR // 10 * 2)  # 100 ms
            if not data:
                break
            chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
            with self.lock:
                self.buf = np.concatenate([self.buf, chunk])

    def peek(self):
        with self.lock:
            return self.buf.copy()

    def drop(self, n):
        with self.lock:
            self.buf = self.buf[n:]

    def stop(self):
        self.proc.terminate()


# ---------------------------------------------------------------- transcrição + tradução
class Translator:
    def __init__(self):
        import ctranslate2
        import sentencepiece as spm

        model = ROOT / "modelos" / "en_pt"
        self.sp = spm.SentencePieceProcessor(model_file=str(model / "sentencepiece.model"))
        self.tr = ctranslate2.Translator(str(model / "model"), device="cpu", compute_type="int8",
                                         inter_threads=1, intra_threads=2)
        self.cache = {}

    def __call__(self, text):
        if text not in self.cache:
            res = self.tr.translate_batch([self.sp.encode(text, out_type=str)], beam_size=2)
            self.cache[text] = "".join(res[0].hypotheses[0]).replace("▁", " ").strip()
            if len(self.cache) > 200:
                self.cache.clear()
        return self.cache[text]


class Worker(threading.Thread):
    """Transcreve o áudio pendente a cada ~1 s; fecha a frase numa pausa ou quando fica longa."""

    MAX_SECONDS = 6       # acima disto, fecha os segmentos completos e continua
    PAUSE = 0.6           # segundos de silêncio que fecham uma frase
    SILENCE_RMS = 0.006   # abaixo disto conta como silêncio

    def __init__(self, cap, out, model_name, log_path, on_final=None):
        super().__init__(daemon=True)
        from faster_whisper import WhisperModel

        self.cap, self.out, self.log_path, self.on_final = cap, out, log_path, on_final
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8",
                                  cpu_threads=max(4, (os.cpu_count() or 4) - 4))
        self.translate = Translator()
        self.context = ""

    def transcribe(self, audio):
        segs, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                        condition_on_previous_text=False,
                                        initial_prompt=self.context[-200:] or None)
        return [(s.start, s.end, s.text.strip()) for s in segs
                if s.no_speech_prob < 0.6 and s.text.strip()]

    def commit(self, text):
        pt = self.translate(text)
        self.out.put(("final", text, pt))
        if self.on_final:
            self.on_final(pt)
        self.context = (self.context + " " + text)[-400:]
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {text}\n           {pt}\n")

    def run(self):
        last_len = 0
        while True:
            audio = self.cap.peek()
            dur = len(audio) / SR
            # só volta a transcrever quando entrou áudio novo suficiente (cada passagem custa ~1 s de CPU)
            if dur < 0.8 or len(audio) - last_len < 0.7 * SR:
                time.sleep(0.2)
                continue
            last_len = len(audio)
            rms = lambda a: float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0
            if rms(audio) < self.SILENCE_RMS:          # só silêncio: descarta
                self.cap.drop(len(audio))
                last_len = 0
                continue
            paused = rms(audio[-int(self.PAUSE * SR):]) < self.SILENCE_RMS
            segs = self.transcribe(audio)
            if not segs:
                if dur > self.MAX_SECONDS:
                    self.cap.drop(len(audio))
                    last_len = 0
                continue
            if paused:                                  # fim de frase: fixa tudo
                self.commit(" ".join(s[2] for s in segs))
                self.cap.drop(len(audio))
                last_len = 0
            elif dur > self.MAX_SECONDS and len(segs) == 1:  # frase longa sem corte: fixa inteira
                self.commit(segs[0][2])
                self.cap.drop(len(audio))
                last_len = 0
            elif dur > self.MAX_SECONDS and len(segs) > 1:  # fala contínua: fixa o que já fechou
                self.commit(" ".join(s[2] for s in segs[:-1]))
                self.cap.drop(int(segs[-1][0] * SR))
                last_len = 0
            else:                                       # frase a decorrer: legenda provisória
                text = " ".join(s[2] for s in segs)
                self.out.put(("partial", text, self.translate(text)))


# ---------------------------------------------------------------- faixa de legendas
class Overlay:
    def __init__(self, out, show_en, font_size):
        self.out, self.show_en, self.size = out, show_en, font_size
        self.root = root = tk.Tk()
        root.title("Legendas ao vivo")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.85)
        root.configure(bg="black")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.w = int(sw * 0.8)
        root.geometry(f"{self.w}x10+{(sw - self.w) // 2}+{int(sh * 0.78)}")

        self.prev = tk.Label(root, fg="#9a9a9a", bg="black", justify="center")
        self.pt = tk.Label(root, fg="white", bg="black", justify="center")
        self.en = tk.Label(root, fg="#c8c8a0", bg="black", justify="center")
        for lbl in (self.prev, self.pt, self.en):
            lbl.pack(fill="x", padx=16)
        self.apply_font()
        self.pt.config(text="A ouvir… põe um vídeo em inglês a tocar.")

        self.last_final_pt = ""
        for w in (root, self.prev, self.pt, self.en):
            w.bind("<ButtonPress-1>", self.start_drag)
            w.bind("<B1-Motion>", self.drag)
            w.bind("<Double-Button-1>", lambda e: self.close())
            w.bind("<Button-4>", lambda e: self.resize(+2))
            w.bind("<Button-5>", lambda e: self.resize(-2))
        root.bind("<Escape>", lambda e: self.close())
        root.after(100, self.poll)

    def apply_font(self):
        wrap = self.w - 40
        self.prev.config(font=("DejaVu Sans", max(10, self.size - 8)), wraplength=wrap)
        self.pt.config(font=("DejaVu Sans", self.size, "bold"), wraplength=wrap)
        self.en.config(font=("DejaVu Sans", max(10, self.size - 10)), wraplength=wrap)

    def resize(self, delta):
        self.size = min(60, max(14, self.size + delta))
        self.apply_font()

    def start_drag(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def drag(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def poll(self):
        if STOP.is_set():
            return self.close()
        try:
            while True:
                kind, en, pt = self.out.get_nowait()
                if kind == "final":
                    self.prev.config(text=self.last_final_pt if self.last_final_pt != pt else "")
                    self.last_final_pt = pt
                    self.pt.config(text=pt, fg="white")
                else:
                    self.prev.config(text=self.last_final_pt)
                    self.pt.config(text=pt, fg="#e8e8e8")
                self.en.config(text=en if self.show_en else "")
        except queue.Empty:
            pass
        self.root.update_idletasks()
        self.root.geometry(f"{self.w}x{self.root.winfo_reqheight() + 8}")
        self.root.after(150, self.poll)

    def close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", default="base.en", help="base.en (rápido, por omissão) ou small.en (mais preciso, mais atraso)")
    ap.add_argument("--sem-ingles", action="store_true", help="não mostrar o texto original")
    ap.add_argument("--letra", type=int, default=26, help="tamanho da letra")
    ap.add_argument("--fonte", default=None, help="fonte de áudio PulseAudio (por omissão: monitor da saída)")
    ap.add_argument("--voz", nargs="?", const="pt-BR-AntonioNeural", default=None,
                    help="ler a tradução em voz alta (opcional: nome da voz, ex. pt-PT-DuarteNeural)")
    ap.add_argument("--volume-original", type=float, default=0.25,
                    help="com --voz: volume do inglês original (0 a 1)")
    a = ap.parse_args()

    log_dir = ROOT / "ao_vivo"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{datetime.now():%Y-%m-%d_%H%M}.txt"

    # o painel desliga com SIGTERM; uma exceção dentro do Tk seria engolida, por isso só se marca o pedido
    # e a janela fecha-se sozinha, deixando o finally repor o áudio
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())

    print("a carregar modelos…", flush=True)
    router = speaker = None
    AudioRouter.cleanup_leftovers()
    try:
        if a.voz:
            router = AudioRouter(a.volume_original)
            speaker = Speaker(a.voz, router.real)
        cap = Capture(a.fonte or (router.monitor if router else default_monitor()))
        out = queue.Queue()
        worker = Worker(cap, out, a.modelo, log_path, on_final=speaker.say if speaker else None)
        cap.start()
        worker.start()
        print(f"a ouvir{' (com voz ' + a.voz + ')' if a.voz else ''}. Transcrição guardada em {log_path}",
              flush=True)
        try:
            Overlay(out, not a.sem_ingles, a.letra).run()
        finally:
            cap.stop()
    except KeyboardInterrupt:
        pass
    finally:
        if router:
            router.close()


if __name__ == "__main__":
    sys.exit(main())
