import io
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from scripts import narracao

SR = 44100
RAIZ = Path(__file__).resolve().parent.parent
ESTILO = RAIZ / "canais" / "exemplo" / "estilo.json"


def _wav(p, x):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return p


def _ler(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32768.0


def _fala(dur, f=300, amp=0.3):
    return amp * np.sin(2 * np.pi * f * np.arange(int(SR * dur)) / SR)


# --- custo e aprovação --------------------------------------------------------


def test_estimativa_de_creditos_pelo_tamanho_do_texto():
    est = narracao.estimar("[pause] Uma frase de teste.", ESTILO)
    assert est["caracteres"] == len("[pause] Uma frase de teste.")
    assert est["creditos"] == pytest.approx(est["caracteres"] * 0.06, abs=1)


class _Resp:
    def __init__(self, corpo, custo):
        self._c, self.headers = corpo, {"character-cost": str(custo)}
        self.status = 200

    def read(self):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_gerar_sem_aprovacao_e_recusado(tmp_path, monkeypatch):
    chamou = []
    monkeypatch.setattr(narracao, "_post", lambda *a, **k: chamou.append(1))
    with pytest.raises(PermissionError, match="aprova"):
        narracao.gerar("Texto.", tmp_path / "n.mp3", ESTILO, tmp_path / "custos.jsonl", aprovado_por="", chave=lambda: "x",
                       creditos_aprovados=10)
    assert chamou == []


def test_gerar_grava_audio_e_registra_o_custo_real(tmp_path, monkeypatch):
    pedidos = []

    def falso(url, corpo, cabecalhos):
        pedidos.append((url, json.loads(corpo), cabecalhos))
        return _Resp(b"ID3fake-mp3", 7)

    monkeypatch.setattr(narracao, "_post", falso)
    rel = narracao.gerar("[slowly] Texto.", tmp_path / "n.mp3", ESTILO, tmp_path / "custos.jsonl",
                         aprovado_por='revisor ("sim")', chave=lambda: "segredo", item="teste", creditos_aprovados=10)
    assert (tmp_path / "n.mp3").read_bytes() == b"ID3fake-mp3"
    (url, corpo, cab), = pedidos
    estilo = json.loads(ESTILO.read_text())["narracao"]
    assert estilo["voz"] in url and corpo["model_id"] == estilo["modelo"] and corpo["language_code"] == "pt"
    assert cab["xi-api-key"] == "segredo"
    linhas = [json.loads(l) for l in (tmp_path / "custos.jsonl").read_text().splitlines()]
    assert [l["evento"] for l in linhas] == ["tentativa", "concluido"]
    reg = linhas[-1]
    assert reg["creditos"] == 7 and reg["aprovado_por"] == 'revisor ("sim")' and "segredo" not in json.dumps(linhas)
    assert rel["creditos"] == 7


def test_chave_vem_do_ambiente_ou_do_gerenciador_de_segredos(tmp_path, monkeypatch):
    import sys
    monkeypatch.setenv("CHAVE_DE_TESTE", "valor-do-ambiente")
    assert narracao._chave_do_ambiente("CHAVE_DE_TESTE") == "valor-do-ambiente"
    monkeypatch.delenv("CHAVE_DE_TESTE")
    helper = tmp_path / "helper.py"
    helper.write_text("import sys; print('valor-do-helper-' + sys.argv[1])")
    monkeypatch.setenv("HARNESS_SECRET_CMD", f"{sys.executable} {helper}")
    assert narracao._chave_do_ambiente("CHAVE_DE_TESTE") == "valor-do-helper-CHAVE_DE_TESTE"
    monkeypatch.delenv("HARNESS_SECRET_CMD")
    with pytest.raises(RuntimeError, match="CHAVE_DE_TESTE"):
        narracao._chave_do_ambiente("CHAVE_DE_TESTE")


def test_chave_nunca_aparece_no_log_nem_no_erro(tmp_path, monkeypatch):
    def falha(url, corpo, cabecalhos):
        raise RuntimeError("HTTP 401")

    monkeypatch.setattr(narracao, "_post", falha)
    with pytest.raises(RuntimeError) as e:
        narracao.gerar("Texto.", tmp_path / "n.mp3", ESTILO, tmp_path / "custos.jsonl", aprovado_por="revisor",
                       chave=lambda: "segredo-muito-secreto", creditos_aprovados=10)
    assert "segredo-muito-secreto" not in str(e.value)
    linhas = [json.loads(l) for l in (tmp_path / "custos.jsonl").read_text().splitlines()]
    assert [l["evento"] for l in linhas] == ["tentativa"]  # a tentativa fica: a cobrança pode ter acontecido
    assert not (tmp_path / "n.mp3").exists()


def test_regra_m24_reprova_gasto_sem_aprovacao():
    ok = {"servico": "elevenlabs", "creditos": 5, "aprovado_por": "revisor"}
    sem = {"servico": "elevenlabs", "creditos": 9}
    erros = narracao.checar_custos({"custos": [ok, sem, {"servico": "outro"}]})
    assert len(erros) == 1 and "M24" in erros[0]


# --- montagem da faixa de voz -------------------------------------------------


@pytest.fixture
def faixas(tmp_path):
    # narração: fala 0-2 s, silêncio 2-2.4, fala 2.4-4 s
    narr = np.concatenate([_fala(2.0), np.zeros(int(0.4 * SR)), _fala(1.6)])
    voz = _fala(1.5, f=500, amp=0.1)  # voz real 9,5 dB mais baixa (dentro do teto de 12 dB): tem de ser nivelada
    return {"narr": _wav(tmp_path / "narr.wav", narr), "voz": _wav(tmp_path / "voz.wav", voz), "pasta": tmp_path}


def test_montar_insere_a_voz_real_no_silencio_mais_proximo(faixas):
    rel = narracao.montar(faixas["narr"], [{"perto_de": 2.1, "arquivo": faixas["voz"], "antes": 0.5, "depois": 0.5}],
                          [], faixas["pasta"] / "faixa.wav")
    segs = rel["segmentos"]
    assert [s["tipo"] for s in segs] == ["narr", "nat", "narr"]
    assert 2.0 <= rel["cortes"][0] <= 2.4  # cortou dentro do silêncio, não no meio da fala
    assert segs[1]["ini"] == pytest.approx(rel["cortes"][0] + 0.5, abs=0.01)
    assert segs[1]["fim"] - segs[1]["ini"] == pytest.approx(1.5, abs=0.01)
    x = _ler(faixas["pasta"] / "faixa.wav")
    assert len(x) / SR == pytest.approx(4.0 + 0.5 + 1.5 + 0.5, abs=0.02)


def test_voz_real_sai_nivelada_com_a_narracao(faixas):
    rel = narracao.montar(faixas["narr"], [{"perto_de": 2.1, "arquivo": faixas["voz"], "antes": 0.5, "depois": 0.5}],
                          [], faixas["pasta"] / "faixa.wav")
    x = _ler(faixas["pasta"] / "faixa.wav")
    s = rel["segmentos"]
    rms = lambda a, b: np.sqrt(np.mean(x[int(a * SR):int(b * SR)] ** 2))
    assert abs(20 * np.log10(rms(s[1]["ini"] + .1, s[1]["fim"] - .1) / rms(.1, 1.9))) < 1.5


def test_pausa_dramatica_entra_no_ponto_exato_sem_regerar(faixas):
    """M23: a pausa é silêncio inserido na faixa, no ponto pedido."""
    rel = narracao.montar(faixas["narr"], [], [{"em": 1.0, "dur": 0.8}], faixas["pasta"] / "faixa.wav")
    x = _ler(faixas["pasta"] / "faixa.wav")
    assert len(x) / SR == pytest.approx(4.0 + 0.8, abs=0.02)
    assert np.max(np.abs(x[int(1.05 * SR):int(1.75 * SR)])) < 0.01
    assert rel["pausas"][0]["em"] == pytest.approx(1.0, abs=0.01)


def test_ponto_de_corte_longe_de_qualquer_silencio_reprova(faixas):
    with pytest.raises(ValueError, match="silêncio"):
        narracao.montar(faixas["narr"], [{"perto_de": 1.0, "arquivo": faixas["voz"]}], [], faixas["pasta"] / "f.wav")


# --- correções da revisão da T23 ---------------------------------------------


def test_aprovacao_nula_reprova_m24():
    assert narracao.checar_custos({"custos": [{"servico": "elevenlabs", "creditos": 3, "aprovado_por": None}]})


def test_aprovacao_vale_para_o_valor_aprovado(tmp_path, monkeypatch):
    monkeypatch.setattr(narracao, "_post", lambda *a: _Resp(b"x", 1))
    with pytest.raises(PermissionError, match="créditos"):
        narracao.gerar("x" * 1000, tmp_path / "n.mp3", ESTILO, tmp_path / "c.jsonl", aprovado_por="revisor",
                       chave=lambda: "k", creditos_aprovados=10)


def test_sem_custo_real_na_resposta_fica_marcado(tmp_path, monkeypatch):
    class R(_Resp):
        def __init__(self):
            super().__init__(b"x", 0)
            self.headers = {}
    monkeypatch.setattr(narracao, "_post", lambda *a: R())
    narracao.gerar("Texto.", tmp_path / "n.mp3", ESTILO, tmp_path / "c.jsonl", aprovado_por="revisor",
                   chave=lambda: "k", creditos_aprovados=10)
    reg = json.loads((tmp_path / "c.jsonl").read_text().splitlines()[-1])
    assert reg["custo_real_ausente"] is True and reg["creditos_estimados"] >= 1


@pytest.mark.parametrize("ins,pausa", [([{"perto_de": 9.0}], []), ([], [{"em": -1.0, "dur": 0.5}]), ([], [{"em": 9.0, "dur": 0.5}])])
def test_pontos_fora_da_faixa_reprovam(faixas, ins, pausa):
    for i in ins:
        i["arquivo"] = faixas["voz"]
    with pytest.raises(ValueError, match="fora"):
        narracao.montar(faixas["narr"], ins, pausa, faixas["pasta"] / "f.wav")


def test_voz_real_muda_reprova_e_ganho_tem_teto(faixas, tmp_path):
    muda = _wav(tmp_path / "muda.wav", np.zeros(SR))
    with pytest.raises(ValueError, match="voz"):
        narracao.montar(faixas["narr"], [{"perto_de": 2.1, "arquivo": muda}], [], tmp_path / "f.wav")
    baixa = _wav(tmp_path / "baixa.wav", _fala(1.0, amp=0.002))  # 43 dB abaixo: subiria demais
    narracao.montar(faixas["narr"], [{"perto_de": 2.1, "arquivo": baixa, "antes": 0, "depois": 0}], [], tmp_path / "f.wav")
    x = _ler(tmp_path / "f.wav")
    assert np.max(np.abs(x[int(2.25 * SR):int(3.0 * SR)])) < 0.01  # subiu no máximo 12 dB


def test_pico_da_voz_real_nao_abaixa_a_narracao(faixas, tmp_path):
    alta = _wav(tmp_path / "alta.wav", np.concatenate([_fala(1.0, amp=0.3), np.ones(50) * 0.999]))
    narracao.montar(faixas["narr"], [{"perto_de": 2.1, "arquivo": alta, "antes": 0, "depois": 0}], [], tmp_path / "f.wav")
    x = _ler(tmp_path / "f.wav")
    assert np.max(np.abs(x[int(0.1 * SR):int(1.9 * SR)])) == pytest.approx(0.3, abs=0.02)


@pytest.mark.transcricao
def test_conferir_narracao_pega_frase_pulada(tmp_path):
    import subprocess
    subprocess.run(["say", "-v", "Samantha", "-o", str(tmp_path / "n.aiff"), "The quick brown fox jumps over the lazy dog."],
                   check=True)
    roteiro = "[slowly] The quick brown fox jumps over the lazy dog."
    assert narracao.conferir_narracao(tmp_path / "n.aiff", roteiro, "en")["semelhanca"] > 0.85
    with pytest.raises(ValueError, match="roteiro"):
        narracao.conferir_narracao(tmp_path / "n.aiff", roteiro + " [pause] And then a whole sentence went missing here.", "en")


def test_montar_devolve_os_deslocamentos_para_o_esqueleto(faixas):
    from scripts import roteiro
    rel = narracao.montar(faixas["narr"], [{"perto_de": 2.1, "arquivo": faixas["voz"], "antes": 0.5, "depois": 0.5}],
                          [{"em": 3.0, "dur": 0.4}], faixas["pasta"] / "f.wav")
    assert [d["dur"] for d in rel["deslocamentos"]] == pytest.approx([2.5, 0.4], abs=0.01)
    assert roteiro.tempo_na_faixa(3.5, rel) == pytest.approx(3.5 + 2.5 + 0.4, abs=0.01)
