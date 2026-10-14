import json
import shutil
import subprocess

import pytest

from scripts import estudo_metricas as m


def test_le_json3(tmp_path):
    f = tmp_path / "a.hi.json3"
    f.write_text(json.dumps({"events": [
        {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "olá "}, {"utf8": "mundo"}]},
        {"tStartMs": 3000, "dDurationMs": 500, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 5000, "dDurationMs": 1000, "segs": [{"utf8": "outra frase aqui"}]},
    ]}))
    segs = m.ler_legenda(f)
    assert segs == [
        {"inicio_s": 1.0, "fim_s": 3.0, "texto": "olá mundo"},
        {"inicio_s": 5.0, "fim_s": 6.0, "texto": "outra frase aqui"},
    ]


def test_le_vtt_e_remove_repeticao_de_legenda_automatica(tmp_path):
    f = tmp_path / "a.en.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000 align:start position:0%\n"
        "hello<00:00:01.500><c> there</c>\n\n"
        "00:00:03.000 --> 00:00:05.000 align:start position:0%\n"
        "hello there\n"
        "general kenobi\n\n"
    )
    segs = m.ler_legenda(f)
    textos = [s["texto"] for s in segs]
    assert textos == ["hello there", "general kenobi"]


def test_palavras_por_minuto():
    segs = [{"inicio_s": 0, "fim_s": 30, "texto": " ".join(["p"] * 60)},
            {"inicio_s": 30, "fim_s": 60, "texto": " ".join(["p"] * 60)}]
    r = m.metricas_fala(segs, duracao_s=120)
    assert r["palavras"] == 120
    assert r["ppm_total"] == 60.0
    assert r["ppm_fala"] == 120.0  # 120 palavras em 1 min de fala


def test_mapa_de_falas_e_pausas():
    segs = [{"inicio_s": 0, "fim_s": 10, "texto": "a"},
            {"inicio_s": 10.2, "fim_s": 20, "texto": "b"},
            {"inicio_s": 22, "fim_s": 30, "texto": "c"}]
    r = m.metricas_fala(segs, duracao_s=40)
    assert r["blocos_fala"] == [[0, 20], [22, 30]]
    assert r["pausas"] == [[20, 22]]
    assert r["pausa_mediana_s"] == 2.0


def test_metricas_fala_sem_legenda_nao_quebra():
    assert m.metricas_fala([], duracao_s=60)["palavras"] == 0


def test_ppm_do_primeiro_minuto():
    segs = [{"inicio_s": 0, "fim_s": 60, "texto": " ".join(["p"] * 150)},
            {"inicio_s": 60, "fim_s": 120, "texto": " ".join(["p"] * 50)}]
    assert m.metricas_fala(segs, 120)["ppm_primeiro_minuto"] == 150.0


def test_comando_de_cena_usa_select_e_showinfo():
    cmd = m.comando_cenas("v.mp4", 0.31)
    junto = " ".join(cmd)
    assert "select='gt(scene,0.31)'" in junto and "showinfo" in junto
    assert cmd[0] == "ffmpeg"


def test_parse_showinfo():
    err = ("[Parsed_showinfo_2 @ 0x1] n:   0 pts:  50 pts_time:2.5 duration: 1 fmt:yuv420p\n"
           "lixo\n"
           "[Parsed_showinfo_2 @ 0x1] n:   1 pts: 100 pts_time:4 duration: 1\n")
    assert m.parse_showinfo(err) == [2.5, 4.0]


def test_estatisticas_de_cortes():
    r = m.estatisticas_cortes([10, 20, 30], duracao_s=60)
    assert r["cortes"] == 3 and r["cortes_por_min"] == 3.0
    assert r["plano_mediano_s"] == 10.0  # planos: 10, 10, 10 e 30
    assert r["cortes_primeiro_minuto"] == 3


def test_estatisticas_sem_cortes():
    r = m.estatisticas_cortes([], duracao_s=60)
    assert r["cortes"] == 0 and r["plano_mediano_s"] == 60.0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_detecta_cortes_em_video_sintetico(tmp_path):
    v = tmp_path / "s.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=160x90:d=2:r=25",
         "-f", "lavfi", "-i", "color=blue:s=160x90:d=2:r=25", "-f", "lavfi", "-i", "testsrc=s=160x90:d=2:r=25",
         "-filter_complex", "[0][1][2]concat=n=3:v=1[o]", "-map", "[o]", "-pix_fmt", "yuv420p", str(v)],
        check=True)
    assert m.duracao_video(v) == pytest.approx(6.0, abs=0.2)
    tempos = m.detectar_cenas(v, 0.3)
    assert len(tempos) == 2
    assert tempos[0] == pytest.approx(2.0, abs=0.1) and tempos[1] == pytest.approx(4.0, abs=0.1)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_folha_de_contato_gera_png(tmp_path):
    v = tmp_path / "s.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=160x90:d=6:r=25", "-pix_fmt", "yuv420p", str(v)],
        check=True)
    out = tmp_path / "folha.png"
    m.folha_de_contato(v, out, cada_s=1, colunas=3)
    assert out.exists() and out.stat().st_size > 0


def test_parse_pontuacao_e_filtro_por_limiar():
    saida = ("frame:0    pts:50      pts_time:2.5\nlavfi.scene_score=0.512\n"
             "frame:1    pts:100     pts_time:4\nlavfi.scene_score=0.120\n")
    pts = m.parse_pontuacao(saida)
    assert pts == [(2.5, 0.512), (4.0, 0.12)]
    assert m.filtrar_por_limiar(pts, 0.3) == [2.5]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_pontuacao_em_uma_passada_equivale_a_deteccao(tmp_path):
    v = tmp_path / "s.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=160x90:d=2:r=25",
         "-f", "lavfi", "-i", "color=blue:s=160x90:d=2:r=25",
         "-filter_complex", "[0][1]concat=n=2:v=1[o]", "-map", "[o]", "-pix_fmt", "yuv420p", str(v)], check=True)
    assert m.filtrar_por_limiar(m.pontuar_cenas(v), 0.3) == m.detectar_cenas(v, 0.3)


def test_limiar_de_cena_de_producao_e_030_e_e_o_default_de_analisar():
    import inspect

    from scripts import estudo_metricas as m

    assert m.LIMIAR_CENA == 0.30
    assert inspect.signature(m.analisar).parameters["limiar"].default == m.LIMIAR_CENA
    assert inspect.signature(m.detectar_cenas).parameters["limiar"].default == m.LIMIAR_CENA


def test_nota_exatamente_no_limiar_nao_conta_como_corte():
    from scripts import estudo_metricas as m

    pont = [(1.0, 0.29), (2.0, 0.30), (3.0, 0.31)]
    assert m.filtrar_por_limiar(pont, 0.30) == [3.0]
