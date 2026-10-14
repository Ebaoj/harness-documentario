import json
import wave
from pathlib import Path

import numpy as np
import pytest

from scripts import entrega, som

SR = 44100
RAIZ = Path(__file__).resolve().parent.parent
ESTILO = RAIZ / "canais" / "exemplo" / "estilo.json"


def _wav(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return p


def _seno(f, dur, amp=0.3):
    return amp * np.sin(2 * np.pi * f * np.arange(int(SR * dur)) / SR)


def _ler(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels())[:, 0] / 32768.0


def _banda(x, a, b, f):
    """Energia (dB) perto da frequência f no trecho [a, b] s."""
    s = x[int(a * SR):int(b * SR)]
    esp = np.abs(np.fft.rfft(s * np.hanning(len(s))))
    fr = np.fft.rfftfreq(len(s), 1 / SR)
    return 20 * np.log10(esp[(fr > f * .9) & (fr < f * 1.1)].max() + 1e-12)


@pytest.fixture
def ep(tmp_path):
    """Voz (1 kHz) de 2 a 5 s, sendo de 3,5 a 5 s voz real; trilha (110 Hz) de 30 s."""
    voz = np.zeros(int(SR * 6))
    voz[int(2 * SR):int(5 * SR)] = _seno(1000, 3.0)
    _wav(tmp_path / "05-som" / "voz.wav", voz)
    _wav(tmp_path / "trilha.wav", _seno(110, 30.0, 0.5))
    fontes = [{"id": "voz-real", "tipo": "voz", "trecho": [0.0, 1.5], "etiquetas": ["x"]}]
    (tmp_path / "fontes.json").write_text(json.dumps({"fontes": fontes}))
    return tmp_path


def _plano(ep, **som_extra):
    s = {"voz": [{"arquivo": "05-som/voz.wav", "em": 0.0}],
         "trilha": {"arquivo": str(ep / "trilha.wav"), "trechos": [[10.0, 14.0], [2.0, None]], "curva": [[0, 1.0]]},
         "efeitos": {"impactos": [], "sopros": [], "sopros_nos_cortes": False}}
    s.update(som_extra)
    return {"dur": 8.0, "cenas": [{"id": "A", "ini": 0, "fim": 8}],
            "vozes": [{"fonte": "voz-real", "em": 3.5, "legendas": []}], "som": s}


def test_mixagem_tem_a_duracao_exata_da_parte(ep):
    saida = som.mixar(ep, _plano(ep), ESTILO, ep / "mix.wav")
    assert len(_ler(saida)) == int(round(8.0 * SR))


def test_trilha_abaixa_sob_a_voz_e_mais_sob_a_voz_real(ep):
    x = _ler(som.mixar(ep, _plano(ep), ESTILO, ep / "mix.wav"))
    sem_voz, narracao, real = _banda(x, 0.5, 1.5, 110), _banda(x, 2.3, 3.3, 110), _banda(x, 3.8, 4.8, 110)
    assert narracao < sem_voz - 3, (sem_voz, narracao)
    assert real < narracao - 3, (narracao, real)


def test_trechos_da_trilha_emendam_sem_silencio(ep):
    """Sem voz: só a trilha, com o primeiro trecho de 7 s cruzando 5 s com o segundo (2 a 7 s da parte)."""
    _wav(ep / "05-som" / "muda.wav", np.zeros(int(SR * 8)))
    p = _plano(ep)
    p["som"]["voz"] = [{"arquivo": "05-som/muda.wav", "em": 0.0}]
    p["som"]["trilha"]["trechos"] = [[10.0, 17.0], [2.0, None]]
    p["vozes"] = []
    x = _ler(som.mixar(ep, p, ESTILO, ep / "mix.wav"))
    assert entrega.menor_nivel(x[int(0.5 * SR):int(7.5 * SR)], SR) > -35


def test_curva_de_volume_da_trilha(ep):
    p = _plano(ep)
    p["som"]["trilha"]["curva"] = [[0, 1.35], [1.0, 0.5]]
    x = _ler(som.mixar(ep, p, ESTILO, ep / "mix.wav"))
    assert _banda(x, 0.0, 0.3, 110) > _banda(x, 1.3, 1.6, 110) + 4  # janelas do mesmo tamanho


def test_impacto_e_sopros_entram_nos_tempos_pedidos(ep):
    p = _plano(ep, efeitos={"impactos": [[6.0, 1.0, 44]], "sopros": [], "sopros_nos_cortes": False})
    x = _ler(som.mixar(ep, p, ESTILO, ep / "mix.wav"))
    assert _banda(x, 6.0, 6.6, 44) > _banda(x, 5.0, 5.6, 44) + 15


def test_mixagem_e_deterministica(ep):
    a = som.mixar(ep, _plano(ep), ESTILO, ep / "a.wav").read_bytes()
    b = som.mixar(ep, _plano(ep), ESTILO, ep / "b.wav").read_bytes()
    assert a == b


def test_arquivo_de_voz_inexistente_vira_erro(ep):
    p = _plano(ep)
    p["som"]["voz"][0]["arquivo"] = "05-som/nao-existe.wav"
    with pytest.raises(ValueError, match="nao-existe"):
        som.mixar(ep, p, ESTILO, ep / "x.wav")


def test_padroes_da_mixagem_aprovada_vem_do_estilo_do_canal():
    s = json.loads(ESTILO.read_text())["som"]
    assert s["trilha_db"] == -15 and s["sob_voz_real"] == 0.4 and s["efeitos_db"] == -9


# --- correções da revisão da T21 ---------------------------------------------


def test_parte_sem_voz_mantem_a_trilha_no_volume_certo(ep):
    """Revisão T21: sem voz, a trilha ocupava o lugar da voz e saía a -9 dB."""
    p = _plano(ep)
    p["som"]["voz"] = []
    p["vozes"] = []
    x = _ler(som.mixar(ep, p, ESTILO, ep / "mix.wav"))
    nivel = 20 * np.log10(np.sqrt(np.mean(x[int(SR):int(2 * SR)] ** 2)))
    assert -26 < nivel < -22, nivel  # seno de amplitude 0,5 tem RMS de -9 dB; com -15 dB, cerca de -24 dB


def test_trilha_mais_curta_que_a_parte_vira_erro(ep):
    p = _plano(ep)
    p["som"]["trilha"]["trechos"] = [[24.0, None]]  # arquivo de 30 s: sobram 6 s para uma parte de 8 s
    with pytest.raises(ValueError, match="trilha"):
        som.mixar(ep, p, ESTILO, ep / "x.wav")


def test_sopro_no_comeco_da_parte_nao_some(ep):
    p = _plano(ep, efeitos={"impactos": [], "sopros": [[0.1, 1.0, 0.9]], "sopros_nos_cortes": False})
    e = som.efeitos(p, json.loads(ESTILO.read_text())["som"], 8.0)
    assert np.abs(e[:int(0.6 * SR)]).max() > 0.1


def test_nao_sobra_arquivo_de_efeitos(ep):
    som.mixar(ep, _plano(ep), ESTILO, ep / "mix.wav")
    assert not list(ep.glob("*efeitos*"))


def test_trilha_relativa_a_pasta_de_musicas(ep, tmp_path, monkeypatch):
    e = json.loads(ESTILO.read_text())
    e["som"]["pasta_musicas"] = str(ep)
    estilo = tmp_path / "estilo.json"
    estilo.write_text(json.dumps(e))
    p = _plano(ep)
    p["som"]["trilha"]["arquivo"] = "trilha.wav"
    assert som.mixar(ep, p, estilo, ep / "mix.wav").exists()


def test_pasta_de_musicas_relativa_ao_estilo_e_variavel_de_ambiente(ep, tmp_path, monkeypatch):
    """pasta_musicas relativa vale a partir da pasta do estilo.json; HARNESS_MUSICAS vence o estilo."""
    canal = tmp_path / "canal"
    (canal / "musicas").mkdir(parents=True)
    (canal / "musicas" / "trilha.wav").write_bytes((ep / "trilha.wav").read_bytes())
    e = json.loads(ESTILO.read_text())
    e["som"]["pasta_musicas"] = "musicas"
    estilo = canal / "estilo.json"
    estilo.write_text(json.dumps(e))
    p = _plano(ep)
    p["som"]["trilha"]["arquivo"] = "trilha.wav"
    monkeypatch.delenv("HARNESS_MUSICAS", raising=False)
    assert som.mixar(ep, p, estilo, ep / "mix.wav").exists()
    monkeypatch.setenv("HARNESS_MUSICAS", str(tmp_path / "nao-existe"))
    with pytest.raises(ValueError, match="trilha"):
        som.mixar(ep, p, estilo, ep / "mix2.wav")


def test_curva_com_dois_tempos_iguais_vira_degrau():
    assert "1.0" in som._curva([[0, 1.35], [2, 1.35], [2, 1.0]])


def test_intervalo_da_voz_real_pode_vir_do_plano(ep):
    p = _plano(ep)
    p["vozes"][0]["dur"] = 0.5  # só de 3,5 a 4,0 s
    x = _ler(som.mixar(ep, p, ESTILO, ep / "mix.wav"))
    assert _banda(x, 4.3, 4.7, 110) > _banda(x, 3.55, 3.95, 110) + 3  # janelas iguais: depois do intervalo a trilha sobe


# --- música alta sob a narração (feedback de revisão, 09/10/2026) ---------------


def _rms_db(x, a, b):
    s = x[int(a * SR):int(b * SR)]
    return 20 * np.log10(np.sqrt(np.mean(s ** 2)) + 1e-12)


@pytest.mark.parametrize("amp", [0.3, 0.02])
def test_musica_fica_abaixo_da_fala_pela_folga_do_estilo_mesmo_com_narracao_baixa(ep, amp):
    """'não dá pra ouvir a minha narração por causa da música alta': o compressor de limite fixo quase não
    agia na narração baixa do capítulo 2 (folga mediana 9,7 dB)."""
    voz = np.zeros(int(SR * 6))
    voz[int(2 * SR):int(5 * SR)] = _seno(1000, 3.0, amp)
    _wav(ep / "05-som" / "voz.wav", voz)
    x = _ler(som.mixar(ep, _plano(ep), ESTILO, ep / "mix.wav"))
    folga = json.loads(ESTILO.read_text())["som"]["folga_sob_voz_db"]
    assert folga >= 18
    assert _banda(x, 2.3, 3.3, 1000) - _banda(x, 2.3, 3.3, 110) >= folga - 1


def test_musica_desce_antes_da_primeira_palavra_e_volta_depois_da_fala(ep):
    x = _ler(som.mixar(ep, _plano(ep), ESTILO, ep / "mix.wav"))
    assert _banda(x, 1.95, 2.05, 1000) - _banda(x, 1.95, 2.05, 110) >= 10  # já baixa quando a voz entra
    assert abs(_banda(x, 6.5, 7.5, 110) - _banda(x, 0.5, 1.5, 110)) < 1  # depois da fala volta ao nível de antes


def test_mixagem_grava_a_folga_medida_e_a_regra_reprova_folga_curta(ep):
    saida = som.mixar(ep, _plano(ep), ESTILO, ep / "mix.wav")
    rel = json.loads(saida.with_suffix(".folga.json").read_text())
    assert rel["pior"] >= rel["alvo"] - 1
    assert som.checar_folga({"folgas": [rel]}) == []
    erros = som.checar_folga({"folgas": [{**rel, "pior": rel["alvo"] - 8, "arquivo": "cap2"}]})
    assert len(erros) == 1 and "M32" in erros[0]


def test_juntar_faixas_serve_para_mixagem_feita_fora_do_plano(tmp_path):
    """A abertura e o capítulo 1 foram mixados por scripts próprios: a mesma regra de folga vale para eles."""
    voz = np.zeros(SR * 4)
    voz[SR:3 * SR] = _seno(1000, 2.0, 0.02)
    mus, sfx = _seno(110, 4.0, 0.3), np.zeros(SR * 4)
    est = json.loads(ESTILO.read_text())["som"]
    x, rel = som.juntar(voz, mus, sfx, [(2.0, 3.0)], est)
    assert _banda(x, 1.3, 1.9, 1000) - _banda(x, 1.3, 1.9, 110) >= est["folga_sob_voz_db"] - 1
    assert _banda(x, 2.3, 2.9, 110) < _banda(x, 1.3, 1.9, 110) - 3  # mais baixa ainda sob a voz real
    assert rel["pior"] >= rel["alvo"] - 1


def test_impacto_sobre_a_fala_nao_cobre_a_palavra(tmp_path):
    """Capítulo 3: o impacto do fim saía no volume do 'B. T. K.' sussurrado (folga de -5 dB)."""
    voz = np.zeros(SR * 4)
    voz[SR:3 * SR] = _seno(1000, 2.0, 0.02)
    sfx = np.zeros(SR * 4)
    sfx[int(1.5 * SR):int(2.5 * SR)] = _seno(60, 1.0, 0.3)
    sfx[int(3.2 * SR):int(3.8 * SR)] = _seno(60, 0.6, 0.3)  # fora da fala: fica como está
    est = json.loads(ESTILO.read_text())["som"]
    x, _ = som.juntar(voz, np.zeros(SR * 4), sfx, [], est)
    assert est["efeitos_folga_db"] >= 10
    assert _banda(x, 1.7, 2.3, 1000) - _banda(x, 1.7, 2.3, 60) >= est["efeitos_folga_db"] - 1
    assert abs(_rms_db(x, 3.4, 3.7) - _rms_db(sfx, 3.4, 3.7)) < 1


# --- música constante sob a fala (feedback de revisão, 10/10/2026) --------------


def _fala_com_pausas(dur):
    """Frases com pausas curtas (0,5 s) e uma pausa longa (2,5 s), palavras em volumes diferentes."""
    voz = np.zeros(int(SR * dur))
    for a, b, amp in ((1.0, 2.0, .3), (2.5, 3.5, .08), (4.0, 5.0, .2), (7.5, 9.0, .15)):
        voz[int(a * SR):int(b * SR)] = _seno(1000, b - a, amp)
    return voz


def test_musica_fica_parada_nas_pausas_da_fala():
    """'a música fica oscilando quando entra a fala': nas pausas curtas ela não sobe e desce."""
    est = json.loads(ESTILO.read_text())["som"]
    voz = _fala_com_pausas(11.0)
    x, _ = som.juntar(voz, _seno(110, 11.0, 0.3), np.zeros(len(voz)), [], est)
    niveis = [_banda(x, a, a + .4, 110) for a in (1.3, 2.05, 2.8, 3.55, 4.3)]  # fala, pausa, fala baixa, pausa, fala
    assert max(niveis) - min(niveis) < 1.0, niveis


def test_musica_sobe_so_no_silencio_de_verdade():
    est = json.loads(ESTILO.read_text())["som"]
    assert est["silencio_minimo_s"] >= 1.5
    voz = _fala_com_pausas(11.0)
    x, _ = som.juntar(voz, _seno(110, 11.0, 0.3), np.zeros(len(voz)), [], est)
    assert _banda(x, 6.0, 6.6, 110) > _banda(x, 1.3, 1.7, 110) + 6  # pausa de 2,5 s: sobe
    assert _banda(x, 7.3, 7.5, 110) < _banda(x, 6.0, 6.6, 110) - 6  # e já desceu quando a fala volta


def test_musica_nao_some_sob_a_fala_fica_na_folga_tipica():
    """10/10: comparando o trecho mais baixo da voz com o pico da música, a trilha caía a -68 dB (muda)."""
    est = json.loads(ESTILO.read_text())["som"]
    rng = np.random.default_rng(1)
    voz = np.zeros(SR * 8)
    for a in np.arange(1.0, 7.0, 0.5):  # palavras de 0,35 s com volumes variados
        w = _seno(1000, .35, rng.uniform(.05, .3))
        voz[int(a * SR):int(a * SR) + len(w)] = w
    mus = _seno(110, 8.0, 0.3) * (1 + 0.9 * np.sin(2 * np.pi * 0.5 * np.arange(SR * 8) / SR))  # música com picos
    x, rel = som.juntar(voz, mus, np.zeros(len(voz)), [], est)
    musf = x - voz
    n = int(SR * .05)
    vdb, mdb = som._janelas_db(voz, n), som._janelas_db(musf, n)
    fala = (np.arange(len(vdb)) * .05 > 1.2) & (np.arange(len(vdb)) * .05 < 6.5)
    distancia = np.median(vdb[fala & (vdb > -50)]) - np.median(mdb[fala])
    assert est["folga_sob_voz_db"] - 2 <= distancia <= est["folga_sob_voz_db"] + 4, distancia


# --- correções da revisão (10/10/2026) ----------------------------------------


def test_ler_float_ignora_metadado_com_a_palavra_data(tmp_path):
    """Revisão: um título 'big data story' no chunk LIST fazia a busca por b'data' ler lixo."""
    import struct
    amostras = np.array([0.1, -0.2, 0.3, -0.4], dtype="<f4").tobytes()
    fmt = struct.pack("<HHIIHH", 3, 1, SR, SR * 4, 4, 32)
    info = b"INFO" + b"INAM" + struct.pack("<I", 15) + b"big data story\0" + b"\0"
    corpo = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"LIST" + struct.pack("<I", len(info)) + info \
        + b"data" + struct.pack("<I", len(amostras)) + amostras + b"lixo"
    (tmp_path / "x.wav").write_bytes(b"RIFF" + struct.pack("<I", len(corpo)) + corpo)
    assert np.allclose(som._ler_float(tmp_path / "x.wav"), [0.1, -0.2, 0.3, -0.4], atol=1e-6)


def _fala_continua(dur, amp=0.1):
    voz = np.zeros(int(SR * dur))
    for a in np.arange(0.5, dur - 0.5, 0.6):  # palavras com pausas curtas: um trecho de fala só
        w = _seno(1000, .45, amp)
        voz[int(a * SR):int(a * SR) + len(w)] = w
    return voz


def test_crescendo_da_trilha_nao_cobre_a_fala():
    """Revisão: com ganho constante pela mediana, um trecho 10 dB mais alto da trilha chegava a 8 dB da fala."""
    est = json.loads(ESTILO.read_text())["som"]
    voz = _fala_continua(12.0)
    mus = _seno(110, 12.0, 0.1)
    mus[int(8 * SR):int(10 * SR)] *= 10 ** (10 / 20)
    x, rel = som.juntar(voz, mus, np.zeros(len(voz)), [], est)
    fala = 20 * np.log10(0.1 / np.sqrt(2))  # nível típico das palavras
    assert fala - _rms_db(x - voz, 8.2, 9.8) >= est["folga_sob_voz_db"] - 6 - 1
    assert rel["pior"] >= rel["alvo"] - 1


def test_m32_mede_o_pico_e_nao_so_a_mediana():
    """Revisão: a medida reusava a mediana que montou o ganho e passava sempre."""
    est = json.loads(ESTILO.read_text())["som"]
    voz = _fala_continua(12.0)
    musf = _seno(110, 12.0, 0.1) * 10 ** (-20 / 20)  # mediana 20 dB abaixo da fala: passa pela mediana
    musf[int(8 * SR):int(10 * SR)] *= 10 ** (14 / 20)  # mas um pico 14 dB acima
    rel = som._medir_folga(voz, musf, est["folga_sob_voz_db"], silencio_minimo=est["silencio_minimo_s"])
    assert som.checar_folga({"folgas": [rel]}), rel


def test_parte_curta_com_voz_real_nao_quebra():
    est = json.loads(ESTILO.read_text())["som"]
    n = 100
    x, _ = som.juntar(np.zeros(n), np.zeros(n), np.zeros(n), [(0.0, 0.001)], est)
    assert len(x) == n


def test_descida_e_rampa_que_termina_na_primeira_palavra():
    """Revisão: a descida caía 19 dB em 50 ms e chegava ao piso 0,35 s antes da fala."""
    est = json.loads(ESTILO.read_text())["som"]
    voz = np.zeros(SR * 6)
    voz[3 * SR:5 * SR] = _seno(1000, 2.0, 0.1)
    g = som.ganho_sob_voz(voz, _seno(110, 6.0, 0.3), est["folga_sob_voz_db"], silencio_minimo=1.5)
    db = 20 * np.log10(g)
    piso = db[int(3.5 * SR)]
    assert db[int(2.5 * SR)] > piso / 2 - 1  # meio segundo antes ainda está no começo da rampa
    assert db[int(2.75 * SR)] > piso + 3  # 0,25 s antes ainda não chegou ao piso
    assert db[int(2.98 * SR)] < piso + 2  # chega ao piso quando a fala começa


def test_queda_sob_voz_real_ja_esta_completa_quando_a_voz_entra():
    est = json.loads(ESTILO.read_text())["som"]
    n = SR * 4
    x, _ = som.juntar(np.zeros(n), np.ones(n) * 0.1, np.zeros(n), [(2.0, 3.0)], est)
    assert x[int(2.0 * SR)] == pytest.approx(0.1 * est["sob_voz_real"], rel=0.02)
