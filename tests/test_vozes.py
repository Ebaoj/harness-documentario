import subprocess
import wave

import numpy as np
import pytest

from scripts import plano, vozes

SR = 44100


def _ler(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32768.0


@pytest.fixture(scope="module")
def doc(tmp_path_factory):
    """Trecho de 'documentário': 1 s de silêncio, a fala, 1,5 s de música (tom de 220 Hz)."""
    import shutil
    if shutil.which("say") is None:
        pytest.skip("a fala de teste é sintetizada pelo `say` do macOS")
    d = tmp_path_factory.mktemp("doc")
    subprocess.run(["say", "-v", "Samantha", "-o", str(d / "fala.aiff"),
                    "The quick brown fox jumps. Over the lazy dog, again."], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(d / "fala.aiff"), "-ar", str(SR), "-ac", "1",
                    str(d / "fala.wav")], check=True)
    fala = _ler(d / "fala.wav")
    tom = 0.2 * np.sin(2 * np.pi * 220 * np.arange(int(1.5 * SR)) / SR)
    x = np.concatenate([np.zeros(SR), fala, tom])
    with wave.open(str(d / "doc.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return {"pasta": d, "audio": d / "doc.wav", "fala_fim": 1.0 + len(fala) / SR, "total": len(x) / SR}


@pytest.mark.transcricao
def test_transcrever_da_palavras_com_tempo(doc):
    ps = vozes.transcrever(doc["audio"], "en")
    textos = [p[2].lower().strip(".,") for p in ps]
    assert "quick" in textos and "lazy" in textos
    assert all(p[0] <= p[1] for p in ps) and ps[0][0] >= 0.8  # a fala começa depois de 1 s de silêncio


@pytest.mark.transcricao
def test_cortar_confere_o_comeco_e_o_fim_pela_transcricao(doc, tmp_path):
    rel = vozes.cortar(doc["audio"], 0.8, doc["fala_fim"] + 0.1, tmp_path / "corte.wav", "en",
                       comeca_com="the quick brown", termina_com="lazy dog again")
    assert (tmp_path / "corte.wav").exists() and rel["palavras"][0][2].lower().startswith("the")


@pytest.mark.transcricao
def test_corte_que_comeca_ou_termina_errado_reprova(doc, tmp_path):
    """M12: o corte da fala começou com o narrador do documentário e terminou antes da frase."""
    with pytest.raises(ValueError, match="M12.*termina"):
        vozes.cortar(doc["audio"], 0.8, 2.3, tmp_path / "x.wav", "en", comeca_com="the quick", termina_com="again")
    with pytest.raises(ValueError, match="M12.*começa"):
        vozes.cortar(doc["audio"], 0.8, doc["fala_fim"] + 0.1, tmp_path / "x.wav", "en",
                     comeca_com="over the lazy", termina_com="again")


@pytest.mark.transcricao
def test_aparar_tira_a_musica_depois_da_ultima_palavra(doc, tmp_path):
    rel = vozes.cortar(doc["audio"], 0.8, doc["total"], tmp_path / "corte.wav", "en",
                       comeca_com="the quick", termina_com="again", aparar=True)
    dur = len(_ler(tmp_path / "corte.wav")) / SR
    fala_no_corte = doc["fala_fim"] - 0.8
    assert dur < fala_no_corte + 0.45, (dur, fala_no_corte)
    assert rel["aparado"] is True


def test_fim_da_fala_pela_energia_e_nao_pelo_fim_esticado_do_transcritor():
    x = np.concatenate([0.3 * np.sin(2 * np.pi * 300 * np.arange(SR) / SR), np.zeros(2 * SR)])
    assert abs(vozes.fim_da_fala(x, SR, 0.2, 2.9) - 1.0) < 0.06


@pytest.mark.transcricao
def test_legendas_saem_dos_tempos_das_palavras_e_passam_na_m11(doc):
    ps = vozes.transcrever(doc["audio"], "en")
    em = 50.0
    itens = vozes.legendas(ps, em, [(0, 4, "A raposa marrom rápida pula."), (5, len(ps) - 1, "Sobre o cão preguiçoso, de novo.")],
                           audio=doc["audio"])
    assert itens[0][0] == pytest.approx(ps[0][0] + em)
    ctx = {"plano": {"vozes": [{"fonte": "v", "em": em, "legendas": itens}]}, "palavras": {"v": ps}}
    assert plano.checar_legenda(ctx) == []


@pytest.mark.transcricao
def test_legenda_com_indice_fora_da_fala_reprova(doc):
    ps = vozes.transcrever(doc["audio"], "en")
    with pytest.raises(ValueError, match="palavra"):
        vozes.legendas(ps, 0.0, [(0, len(ps) + 3, "Texto.")])


def test_voz_sem_conferencia_registrada_reprova_m12():
    ok = {"id": "a", "tipo": "voz", "conferido": {"comeca_com": "he was", "termina_com": "in trouble", "quando": "2026-10-09",
                                                  "sha256": "0" * 64}}
    sem = {"id": "b", "tipo": "voz"}
    erros = vozes.checar_conferidas({"fontes": [ok, sem, {"id": "c", "tipo": "foto"}]})
    assert len(erros) == 1 and "M12" in erros[0] and "b" in erros[0]


@pytest.mark.transcricao
def test_cortar_devolve_o_registro_da_conferencia(doc, tmp_path):
    rel = vozes.cortar(doc["audio"], 0.8, doc["fala_fim"] + 0.1, tmp_path / "c.wav", "en",
                       comeca_com="the quick", termina_com="again")
    assert rel["conferido"]["comeca_com"] == "the quick" and rel["conferido"]["termina_com"] == "again"


# --- correções da revisão da T22 ---------------------------------------------


@pytest.mark.parametrize("comeca,termina", [("", "again"), ("the quick", ""), ("—", "again")])
def test_esperado_vazio_e_recusado(doc, tmp_path, comeca, termina):
    with pytest.raises(ValueError, match="M12"):
        vozes.cortar(doc["audio"], 0.8, doc["fala_fim"] + 0.1, tmp_path / "x.wav", "en", comeca, termina)


@pytest.mark.transcricao
def test_conferir_transcreve_o_proprio_arquivo_e_prende_o_registro_a_ele(doc, tmp_path):
    rel = vozes.cortar(doc["audio"], 0.8, doc["fala_fim"] + 0.1, tmp_path / "c.wav", "en", "the quick", "again")
    reg = vozes.conferir(tmp_path / "c.wav", "en", "the quick", "again")
    import hashlib
    assert reg["sha256"] == hashlib.sha256((tmp_path / "c.wav").read_bytes()).hexdigest() == rel["conferido"]["sha256"]
    with pytest.raises(ValueError, match="M12"):
        vozes.conferir(tmp_path / "c.wav", "en", "over the lazy", "again")


@pytest.mark.transcricao
def test_registro_que_nao_bate_com_o_arquivo_reprova_m12(doc, tmp_path):
    vozes.cortar(doc["audio"], 0.8, doc["fala_fim"] + 0.1, tmp_path / "c.wav", "en", "the quick", "again")
    reg = vozes.conferir(tmp_path / "c.wav", "en", "the quick", "again")
    fonte = {"id": "v", "tipo": "voz", "arquivo": "c.wav", "conferido": reg}
    assert vozes.checar_conferidas({"fontes": [fonte], "pasta": tmp_path}) == []
    (tmp_path / "c.wav").write_bytes(b"outro conteudo")
    assert any("M12" in e and "sha256" in e for e in vozes.checar_conferidas({"fontes": [fonte], "pasta": tmp_path}))


@pytest.mark.transcricao
def test_aparado_e_conferido_depois_do_fade(doc, tmp_path):
    rel = vozes.cortar(doc["audio"], 0.8, doc["total"], tmp_path / "c.wav", "en", "the quick", "again", aparar=True)
    import hashlib
    assert rel["conferido"]["sha256"] == hashlib.sha256((tmp_path / "c.wav").read_bytes()).hexdigest()
    assert not list(tmp_path.glob("*.tmp.wav"))


@pytest.mark.transcricao
def test_legendas_fora_de_ordem_ou_sobrepostas_reprovam(doc):
    ps = vozes.transcrever(doc["audio"], "en")
    with pytest.raises(ValueError, match="ordem"):
        vozes.legendas(ps, 0.0, [(5, 7, "B."), (0, 4, "A.")])
    with pytest.raises(ValueError, match="ordem"):
        vozes.legendas(ps, 0.0, [(0, 5, "A."), (5, 7, "B.")])


@pytest.mark.transcricao
def test_inicio_ajustado_nao_passa_do_fim_da_palavra(doc):
    ps = vozes.transcrever(doc["audio"], "en")
    assert all(p[0] <= p[1] for p in ps)
    assert all(a[0] <= b[0] for a, b in zip(ps, ps[1:]))


@pytest.mark.transcricao
def test_aparar_aumenta_a_folga_quando_o_fade_come_o_fim(doc, tmp_path, monkeypatch):
    """Capítulo 3: o fade comeu 'and I was in'; o aparar tenta com mais folga em vez de falhar."""
    real = vozes.conferir
    chamadas = {"n": 0}

    def exigente(arquivo, idioma, comeca, termina):
        chamadas["n"] += 1
        if chamadas["n"] == 2:  # a primeira conferência depois do fade falha
            raise ValueError("M12 o corte termina com 'the lazy dog', esperado 'again'")
        return real(arquivo, idioma, comeca, termina)

    monkeypatch.setattr(vozes, "conferir", exigente)
    rel = vozes.cortar(doc["audio"], 0.8, doc["total"], tmp_path / "c.wav", "en", "the quick", "again", aparar=True)
    assert rel["aparado"] is True and rel["folga"] > 0.15


def test_fim_da_legenda_nunca_antes_do_inicio_da_ultima_palavra():
    """Capítulo 3: 'lines,' com duração quase zero fez a legenda acabar 3 ms antes da palavra (arredondamento)."""
    ps = [[0.0, 0.5, "I"], [0.5, 3.44, "came"], [3.44, 3.48, "lines,"], [3.48, 4.0, "waited"]]
    (a, b, _), = vozes.legendas(ps, 42.233, [(0, 2, "Texto.")])
    assert b >= 3.44 + 42.233 + 0.05


def test_legenda_nao_invade_a_seguinte_quando_as_palavras_sao_coladas():
    ps = [[0.0, 0.5, "I"], [0.5, 3.44, "came"], [3.44, 3.48, "lines,"], [3.48, 4.0, "waited"], [4.0, 4.5, "there."]]
    itens = vozes.legendas(ps, 0.0, [(0, 2, "Um."), (3, 4, "dois.")])
    assert itens[0][1] <= itens[1][0]


@pytest.mark.transcricao
def test_aparar_nao_repete_o_mesmo_corte_quando_a_folga_passa_do_fim(doc, tmp_path, monkeypatch):
    """Revisão: com o corte preso no fim do arquivo, as folgas seguintes refaziam o mesmo arquivo e o whisper."""
    real = vozes.conferir
    chamadas = {"n": 0}

    def conta(arquivo, idioma, comeca, termina):
        chamadas["n"] += 1
        if chamadas["n"] > 1:
            raise ValueError("M12 o fade comeu o fim")
        return real(arquivo, idioma, comeca, termina)

    monkeypatch.setattr(vozes, "conferir", conta)
    monkeypatch.setattr(vozes, "_menor_corte", lambda *a, **k: 99.0)  # qualquer folga passa do fim
    rel = vozes.cortar(doc["audio"], 0.8, doc["total"], tmp_path / "c.wav", "en", "the quick", "again", aparar=True)
    assert chamadas["n"] == 2 and rel["aparado"] is False
    assert vozes.checar_conferidas({"fontes": [{"id": "v", "tipo": "voz", "arquivo": "c.wav", "conferido": rel["conferido"]}],
                                    "pasta": tmp_path}) == []


def test_legenda_sem_duracao_vira_erro_em_vez_de_sumir():
    """Revisão: palavras com o mesmo início faziam a legenda acabar onde começava, e ela sumia calada."""
    ps = [[1.0, 1.2, "Um"], [1.0, 1.0, "dois"], [1.0, 1.4, "três."]]
    with pytest.raises(ValueError, match="duração"):
        vozes.legendas(ps, 0.0, [(0, 0, "Um."), (1, 2, "Dois três.")])
