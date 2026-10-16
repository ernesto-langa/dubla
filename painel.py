#!/usr/bin/env python3
"""Dubla — painel web local para gerir as traduções: dubla (ou ./painel.py) -> http://localhost:8765"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
VIDEOS = ROOT / "videos"
LIVE_PID = ROOT / "ao_vivo" / ".pid"
PORT = int(os.environ.get("PAINEL_PORTA", 8765))
NAME_RE = re.compile(r"^[\w-]{1,60}$")

STEPS = [  # (texto no log, etapa, peso acumulado até ao início desta etapa)
    ("a obter o vídeo", "A obter link", 0),
    ("a descarregar", "A descarregar", 2),
    ("a transcrever", "A transcrever", 15),
    ("a traduzir", "A traduzir", 75),
    ("a gerar voz", "A gerar voz", 80),
    ("a alinhar", "A alinhar voz", 93),
    ("a montar", "A montar MP4", 96),
    ("pronto:", "Pronto", 100),
]


# ---------------------------------------------------------------- processos
def alive(pid, needle):
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        return needle in cmd
    except (OSError, ValueError):
        return False


def job_file(name):
    return VIDEOS / name / "job.json"


def read_job(name):
    try:
        return json.loads(job_file(name).read_text())
    except (OSError, ValueError):
        return {}


def start_job(name, url, voz, tradutor):
    (VIDEOS / name).mkdir(parents=True, exist_ok=True)
    args = [str(ROOT / "traduzir.py"), url, "--nome", name, "--voz", voz, "--tradutor", tradutor]
    log = open(VIDEOS / f"{name}.log", "a")
    log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} início ===\n")
    log.flush()
    env = {**os.environ, "PYTHONWARNINGS": "ignore"}
    p = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True, env=env)  # sobrevive ao fecho do painel
    job = {**read_job(name), "url": url, "voz": voz, "tradutor": tradutor, "pid": p.pid,
           "iniciado": time.time()}
    job.setdefault("criado", time.time())
    job_file(name).write_text(json.dumps(job, indent=1))


def log_tail(name, size=6000):
    try:
        with open(VIDEOS / f"{name}.log", "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - size))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text).replace("\r", "\n")
    return text.split("=== ")[-1]  # só a última execução


def to_s(hms):
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


def status(name):
    d = VIDEOS / name
    job = read_job(name)
    final = d / f"{name}_PT.mp4"
    running = bool(job.get("pid")) and alive(job["pid"], "traduzir.py")
    tail = log_tail(name)
    lines = [l.strip() for l in tail.splitlines() if l.strip()]

    step, pct = "Por iniciar", 0
    for key, label, base in STEPS:
        if any(key in l for l in lines):
            step, pct = label, base
    # progresso fino dentro do download / transcrição
    if step == "A descarregar":
        m = re.findall(r"\[download\]\s+([\d.]+)%", tail)
        if m:
            pct = 2 + float(m[-1]) * 0.13
    elif step == "A transcrever":
        m = re.findall(r"(\d\d:\d\d:\d\d) / (\d\d:\d\d:\d\d)", tail)
        if m and to_s(m[-1][1]):
            pct = 15 + 60 * to_s(m[-1][0]) / to_s(m[-1][1])
    elif step == "A gerar voz" and (d / "segmentos_pt.json").exists():
        try:
            total = len(json.loads((d / "segmentos_pt.json").read_text()))
            done = sum(1 for f in (d / "tts").glob("*.mp3") if f.stat().st_size > 0)
            pct = 80 + 13 * done / max(total, 1)
        except (OSError, ValueError):
            pass

    error = None
    if final.exists() and not running:
        state, step, pct = "pronto", "Pronto", 100
    elif running:
        state = "a_processar"
    else:
        err = [l for l in lines if l.startswith(("erro", "Não consegui", "Whop recusou")) or "Error" in l]
        if err:
            state, error = "erro", err[-1][:300]
        else:
            state = "interrompido" if lines or (d / "original.mp4").exists() else "por_iniciar"

    used = d / "tradutor_usado.txt"
    info = {"tradutor_usado": used.read_text().strip() if used.exists() else
            ("local" if (d / "segmentos_pt.json").exists() else None)}  # aulas antigas: foram todas offline
    info |= {"nome": name, "estado": state, "etapa": step, "progresso": round(min(pct, 100), 1),
            "erro": error, "url": job.get("url"), "voz": job.get("voz"), "tradutor": job.get("tradutor"),
            "titulo": job.get("titulo"), "criado": job.get("criado") or d.stat().st_mtime,
            "ultima_linha": lines[-1][:200] if lines else ""}
    if final.exists():
        info["tamanho_mb"] = round(final.stat().st_size / 1e6, 1)
        info["atualizado"] = final.stat().st_mtime
        dur = job.get("duracao")
        if not dur:
            try:
                dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                            "-of", "csv=p=0", str(final)], capture_output=True,
                                           text=True, timeout=10).stdout)
                job["duracao"] = dur
                job_file(name).write_text(json.dumps(job, indent=1))
            except (ValueError, subprocess.SubprocessError, OSError):
                dur = None
        info["duracao"] = dur
    return info


def list_videos():
    if not VIDEOS.exists():
        return []
    out = [status(d.name) for d in VIDEOS.iterdir() if d.is_dir() and NAME_RE.match(d.name)]
    return sorted(out, key=lambda v: v["nome"])


def next_name():
    nums = [int(m.group(1)) for d in VIDEOS.glob("aula*") if (m := re.match(r"aula(\d+)$", d.name))]
    return f"aula{(max(nums) + 1 if nums else 1):02}"


def live_status():
    try:
        pid = int(LIVE_PID.read_text())
        return pid if alive(pid, "legendas_ao_vivo.py") else None
    except (OSError, ValueError):
        return None


def srt_to_vtt(srt):
    return "WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", srt)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def name_from(self, parts, i):
        name = parts[i] if len(parts) > i else ""
        if not NAME_RE.match(name) or not (VIDEOS / name).is_dir():
            self.send(404, {"erro": "vídeo não encontrado"})
            return None
        return name

    # ---------- GET
    def do_GET(self):
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if path == "/":
            return self.send(200, (ROOT / "painel.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/google":
            try:
                r = subprocess.run([str(ROOT / ".venv/bin/python"), "-W", "ignore", "-c",
                                    "import traduzir; traduzir.google_status()"],
                                   cwd=ROOT, capture_output=True, text=True, timeout=60)
                return self.send(200, json.loads(r.stdout.strip().splitlines()[-1]))
            except (subprocess.SubprocessError, ValueError, IndexError) as e:
                return self.send(200, {"estado": "erro", "erro": str(e)[:200]})
        if path == "/api/videos":
            return self.send(200, {"videos": list_videos(), "ao_vivo": bool(live_status()),
                                   "proximo_nome": next_name()})
        if len(parts) >= 3 and parts[:2] == ["api", "videos"]:
            name = self.name_from(parts, 2)
            if not name:
                return
            what = parts[3] if len(parts) > 3 else ""
            if what == "log":
                return self.send(200, log_tail(name, 20000), "text/plain; charset=utf-8")
            if what == "transcricao":
                f = VIDEOS / name / "segmentos_pt.json"
                segs = json.loads(f.read_text()) if f.exists() else []
                return self.send(200, segs)
            if what in ("pt.vtt", "en.vtt"):
                f = VIDEOS / name / f"legendas_{what[:2]}.srt"
                if not f.exists():
                    return self.send(404, "")
                return self.send(200, srt_to_vtt(f.read_text(encoding="utf-8")), "text/vtt; charset=utf-8")
            if what == "video.mp4":
                return self.stream(VIDEOS / name / f"{name}_PT.mp4")
            return self.send(200, status(name))
        self.send(404, {"erro": "não existe"})

    do_HEAD = do_GET

    def stream(self, f):
        """Serve o MP4 com suporte a Range (para o player poder saltar no vídeo)."""
        if not f.exists():
            return self.send(404, "")
        size = f.stat().st_size
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m:
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = size - int(m.group(2))
            end = min(end, size - 1)
        length = end - start + 1
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if m:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(f, "rb") as fh:
                fh.seek(start)
                while length > 0:
                    chunk = fh.read(min(1 << 20, length))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    length -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- POST
    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if parts == ["api", "videos"]:
            b = self.body()
            url = (b.get("url") or "").strip()
            if not url.startswith(("http://", "https://")) and not Path(url).exists():
                return self.send(400, {"erro": "Cola um link (http…) ou o caminho de um ficheiro."})
            key = url.split("?")[0].rstrip("/")
            for d in VIDEOS.iterdir() if VIDEOS.exists() else []:
                if d.is_dir() and (read_job(d.name).get("url") or "").split("?")[0].rstrip("/") == key:
                    return self.send(409, {"erro": f"Esta aula já foi traduzida: está em '{d.name}'.",
                                           "nome": d.name})
            name = (b.get("nome") or "").strip() or next_name()
            if not NAME_RE.match(name):
                return self.send(400, {"erro": "Nome só pode ter letras, números, - e _."})
            if (VIDEOS / name).exists() and read_job(name).get("pid") and alive(read_job(name)["pid"], "traduzir.py"):
                return self.send(409, {"erro": f"'{name}' já está a ser processado."})
            if (VIDEOS / name / f"{name}_PT.mp4").exists():
                return self.send(409, {"erro": f"Já existe '{name}'. Escolhe outro nome."})
            start_job(name, url, b.get("voz") or "pt-BR-AntonioNeural", b.get("tradutor") or "google")
            return self.send(200, status(name))

        if parts == ["api", "ao-vivo"]:
            b = self.body()
            pid = live_status()
            if b.get("ligar") and not pid:
                (ROOT / "ao_vivo").mkdir(exist_ok=True)
                args = [str(ROOT / "legendas_ao_vivo.py"), "--modelo", b.get("modelo") or "base.en"]
                if b.get("sem_ingles"):
                    args.append("--sem-ingles")
                if b.get("voz"):
                    args += ["--voz", b["voz"]]
                p = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True, env={**os.environ, "PYTHONWARNINGS": "ignore"})
                LIVE_PID.write_text(str(p.pid))
            elif not b.get("ligar") and pid:
                os.killpg(pid, signal.SIGTERM)
            time.sleep(0.3)
            return self.send(200, {"ao_vivo": bool(live_status())})

        if len(parts) == 4 and parts[:2] == ["api", "videos"]:
            name = self.name_from(parts, 2)
            if not name:
                return
            action, job = parts[3], read_job(name)
            if action == "retomar":
                if not job.get("url"):
                    return self.send(400, {"erro": "Não sei o link original deste vídeo."})
                if job.get("pid") and alive(job["pid"], "traduzir.py"):
                    return self.send(409, {"erro": "Já está a correr."})
                start_job(name, job["url"], job.get("voz") or "pt-BR-AntonioNeural", job.get("tradutor") or "google")
                return self.send(200, status(name))
            if action == "parar":
                if job.get("pid") and alive(job["pid"], "traduzir.py"):
                    os.killpg(job["pid"], signal.SIGTERM)
                    time.sleep(0.5)
                return self.send(200, status(name))
            if action == "refazer-voz":
                b = self.body()
                if job.get("pid") and alive(job["pid"], "traduzir.py"):
                    return self.send(409, {"erro": "Espera que termine."})
                shutil.rmtree(VIDEOS / name / "tts", ignore_errors=True)
                for f in ("dobragem_pt.wav", f"{name}_PT.mp4"):
                    (VIDEOS / name / f).unlink(missing_ok=True)
                start_job(name, job.get("url") or str(VIDEOS / name / "original.mp4"),
                          b.get("voz") or job.get("voz") or "pt-BR-AntonioNeural", job.get("tradutor") or "google")
                return self.send(200, status(name))
            if action == "retraduzir":
                if job.get("pid") and alive(job["pid"], "traduzir.py"):
                    return self.send(409, {"erro": "Espera que termine."})
                d = VIDEOS / name
                shutil.rmtree(d / "tts", ignore_errors=True)
                for f in ("segmentos_pt.json", "tradutor_usado.txt", "legendas_pt.srt", "legendas_en.srt",
                          "dobragem_pt.wav", f"{name}_PT.mp4"):
                    (d / f).unlink(missing_ok=True)
                start_job(name, job.get("url") or str(d / "original.mp4"),
                          job.get("voz") or "pt-BR-AntonioNeural", "google")
                return self.send(200, status(name))
            if action == "vlc":
                f = VIDEOS / name / f"{name}_PT.mp4"
                subprocess.Popen(["vlc", str(f)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                return self.send(200, {"ok": True})
            if action == "pasta":
                subprocess.Popen(["xdg-open", str(VIDEOS / name)], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return self.send(200, {"ok": True})
        self.send(404, {"erro": "não existe"})

    # ---------- DELETE
    def do_DELETE(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) == 3 and parts[:2] == ["api", "videos"]:
            name = self.name_from(parts, 2)
            if not name:
                return
            job = read_job(name)
            if job.get("pid") and alive(job["pid"], "traduzir.py"):
                os.killpg(job["pid"], signal.SIGTERM)
            shutil.rmtree(VIDEOS / name)
            for ext in (".log", ".pid"):
                (VIDEOS / f"{name}{ext}").unlink(missing_ok=True)
            return self.send(200, {"ok": True})
        self.send(404, {"erro": "não existe"})


def main():
    VIDEOS.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Dubla em {url}  (Ctrl+C para fechar; as traduções em curso continuam)", flush=True)
    if "--sem-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
