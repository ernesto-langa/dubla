import traduzir
from traduzir import SR, fit, fmt_ts, group_sentences, write_srt


def words(*spec):
    """spec: (palavra, início, fim) — o Whisper devolve as palavras com espaço à frente."""
    return [{"w": f" {w}", "s": s, "e": e} for w, s, e in spec]


# ---------------------------------------------------------------- frases
def test_corta_no_ponto_final_depois_de_2_5_s():
    ws = words(("Hello", 0, 0.5), ("there,", 0.6, 1.0), ("my", 1.1, 1.5), ("friend.", 1.6, 3.0),
               ("Next", 3.2, 3.6), ("one.", 3.7, 4.0))
    assert group_sentences(ws) == [
        {"start": 0, "end": 3.0, "en": "Hello there, my friend."},
        {"start": 3.2, "end": 4.0, "en": "Next one."},
    ]


def test_nao_corta_frase_curta_no_ponto():
    ws = words(("Yes.", 0, 0.4), ("I", 0.5, 0.6), ("agree.", 0.7, 1.0))
    assert [s["en"] for s in group_sentences(ws)] == ["Yes. I agree."]


def test_corta_em_pausa_maior_que_0_8_s():
    ws = words(("so", 0, 0.3), ("then", 0.4, 0.7), ("we", 1.6, 1.8), ("go", 1.9, 2.1))
    assert [s["en"] for s in group_sentences(ws)] == ["so then", "we go"]


def test_pausa_de_0_8_s_exatos_nao_corta():
    ws = words(("a", 0, 0.2), ("b", 1.0, 1.2))
    assert len(group_sentences(ws)) == 1


def test_bloco_sem_pontuacao_nao_passa_de_12_s():
    ws = words(*[(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(60)])  # 30 s sem pausas
    segs = group_sentences(ws)
    assert len(segs) > 1
    assert all(s["end"] - s["start"] <= 12.5 for s in segs)
    assert " ".join(s["en"] for s in segs) == " ".join(f"w{i}" for i in range(60))


def test_sem_palavras():
    assert group_sentences([]) == []


def test_ignora_blocos_so_com_espacos():
    ws = [{"w": " ", "s": 0, "e": 0.1}, {"w": " ", "s": 2, "e": 2.1}]
    assert group_sentences(ws) == []


# ---------------------------------------------------------------- encaixe da voz
def segs_at(*starts):
    return [{"start": s} for s in starts]


def test_cabe_no_espaco_ate_a_frase_seguinte():
    assert fit(segs_at(1, 5), 0, 0, 2 * SR, 100 * SR) == (1 * SR, 1.0)


def test_nao_cabe_acelera_o_necessario():
    start, tempo = fit(segs_at(0, 4), 0, 0, 5 * SR, 100 * SR)
    assert start == 0
    assert tempo == 1.25


def test_aceleracao_maxima_e_1_5x():
    assert fit(segs_at(0, 2), 0, 0, 10 * SR, 100 * SR)[1] == 1.5


def test_nao_sobrepoe_a_fala_anterior():
    # a fala anterior acabou aos 3 s; esta devia começar aos 2 s
    start, tempo = fit(segs_at(0, 2, 6), 1, 3 * SR, 2 * SR, 100 * SR)
    assert start == 3 * SR
    assert tempo == 1.0


def test_espaco_minimo_de_meio_segundo():
    # a fala anterior já invadiu o espaço desta: conta pelo menos 0,5 s
    start, tempo = fit(segs_at(0, 2), 0, int(1.9 * SR), int(0.6 * SR), 100 * SR)
    assert start == int(1.9 * SR)
    assert tempo == 0.6 / 0.5


def test_ultima_frase_vai_ate_ao_fim_da_faixa():
    assert fit(segs_at(0, 10), 1, 0, 4 * SR, 15 * SR) == (10 * SR, 1.0)
    assert fit(segs_at(0, 10), 1, 0, 6 * SR, 15 * SR)[1] == 1.2


# ---------------------------------------------------------------- legendas
def test_fmt_ts():
    assert fmt_ts(0) == "00:00:00,000"
    assert fmt_ts(3725.5) == "01:02:05,500"
    assert fmt_ts(1.0004) == "00:00:01,000"
    assert fmt_ts(59.9996) == "00:01:00,000"  # arredondar os ms não pode recuar quase 1 s
    assert fmt_ts(3599.9999) == "01:00:00,000"


def test_write_srt(tmp_path):
    path = tmp_path / "x.srt"
    write_srt(path, [{"start": 0, "end": 1.5, "pt": "Olá"}, {"start": 2, "end": 3, "pt": "Adeus"}], "pt")
    assert path.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,500\nOlá\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nAdeus\n\n")


def test_link_whop():
    m = traduzir.WHOP_LESSON.match("https://whop.com/joined/curso/app/lessons/lesn_AbC123/")
    assert m and m.group(1) == "lesn_AbC123"
    assert not traduzir.WHOP_LESSON.match("https://youtube.com/watch?v=x")
