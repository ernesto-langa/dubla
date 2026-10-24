import json

import pytest

import painel


@pytest.fixture
def videos(tmp_path, monkeypatch):
    monkeypatch.setattr(painel, "VIDEOS", tmp_path)
    return tmp_path


def make(videos, name, log="", job=None, files=()):
    d = videos / name
    d.mkdir()
    (videos / f"{name}.log").write_text(log)
    (d / "job.json").write_text(json.dumps(job or {}))
    for f in files:
        (d / f).write_bytes(b"x")
    return d


# ---------------------------------------------------------------- progresso
def test_por_iniciar(videos):
    make(videos, "aula01")
    s = painel.status("aula01")
    assert (s["estado"], s["etapa"], s["progresso"]) == ("por_iniciar", "Por iniciar", 0)


def test_etapa_e_a_ultima_que_aparece_no_log(videos):
    make(videos, "aula01", "[traduzir] a descarregar…\n[traduzir] a transcrever com Whisper…\n")
    s = painel.status("aula01")
    assert (s["etapa"], s["progresso"]) == ("A transcrever", 15)


def test_progresso_do_download(videos):
    make(videos, "aula01", "[traduzir] a descarregar…\n[download]  10.0% of 1GiB\r[download]  50.0% of 1GiB\n")
    assert painel.status("aula01")["progresso"] == 2 + 50 * 0.13


def test_progresso_da_transcricao(videos):
    make(videos, "aula01", "a transcrever\n\r  00:05:00 / 00:20:00\r  00:10:00 / 00:20:00")
    assert painel.status("aula01")["progresso"] == 15 + 60 * 0.5


def test_progresso_da_voz(videos):
    d = make(videos, "aula01", "a gerar voz PT para 4 frases…\n", files=["segmentos_pt.json"])
    (d / "segmentos_pt.json").write_text(json.dumps([{}] * 4))
    (d / "tts").mkdir()
    (d / "tts" / "00000.mp3").write_bytes(b"x")
    (d / "tts" / "00001.mp3").write_bytes(b"")  # vazio: ainda não conta
    assert painel.status("aula01")["progresso"] == round(80 + 13 * 1 / 4, 1)


def test_so_conta_a_ultima_execucao(videos):
    make(videos, "aula01", "=== 2026-10-01 início ===\na traduzir\nerro: falhou\n"
                           "=== 2026-10-02 início ===\na descarregar\n")
    s = painel.status("aula01")
    assert s["etapa"] == "A descarregar"
    assert s["erro"] is None


# ---------------------------------------------------------------- estados
def test_pronto_quando_existe_o_mp4(videos):
    make(videos, "aula01", "a montar\n", job={"duracao": 60}, files=["aula01_PT.mp4"])
    s = painel.status("aula01")
    assert (s["estado"], s["etapa"], s["progresso"], s["duracao"]) == ("pronto", "Pronto", 100, 60)


def test_erro_mostra_a_ultima_linha_de_erro(videos):
    make(videos, "aula01", "a descarregar\nerro em yt-dlp: 403\n")
    s = painel.status("aula01")
    assert (s["estado"], s["erro"]) == ("erro", "erro em yt-dlp: 403")


def test_interrompido(videos):
    make(videos, "aula01", "a transcrever\n")
    assert painel.status("aula01")["estado"] == "interrompido"


def test_a_processar_com_o_processo_vivo(videos, monkeypatch):
    make(videos, "aula01", "a traduzir\n", job={"pid": 123})
    monkeypatch.setattr(painel, "alive", lambda pid, needle: pid == 123 and needle == "traduzir.py")
    assert painel.status("aula01")["estado"] == "a_processar"


def test_tradutor_usado(videos):
    make(videos, "nova", files=["tradutor_usado.txt"])
    (videos / "nova" / "tradutor_usado.txt").write_text("google\n")
    make(videos, "antiga", files=["segmentos_pt.json"])
    assert painel.status("nova")["tradutor_usado"] == "google"
    assert painel.status("antiga")["tradutor_usado"] == "local"


# ---------------------------------------------------------------- utilitários
def test_proximo_nome(videos):
    assert painel.next_name() == "aula01"
    for n in ("aula01", "aula07", "aula7x", "outra"):
        (videos / n).mkdir()
    assert painel.next_name() == "aula08"


def test_lista_ignora_nomes_invalidos(videos):
    make(videos, "aula02")
    make(videos, "aula01")
    (videos / "com espaço").mkdir()
    assert [v["nome"] for v in painel.list_videos()] == ["aula01", "aula02"]


@pytest.mark.parametrize("name,ok", [("aula01", True), ("a-b_c", True), ("../etc", False),
                                     ("a b", False), ("", False), ("x" * 61, False)])
def test_nomes_validos(name, ok):
    assert bool(painel.NAME_RE.match(name)) is ok


def test_srt_para_vtt():
    srt = "1\n00:00:01,500 --> 00:00:02,000\nOlá\n"
    assert painel.srt_to_vtt(srt) == "WEBVTT\n\n1\n00:00:01.500 --> 00:00:02.000\nOlá\n"


def test_to_s():
    assert painel.to_s("01:02:03") == 3723
