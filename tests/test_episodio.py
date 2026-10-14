import json
import subprocess
import wave

import numpy as np
import pytest

from scripts import episodio
from tests.test_cenas import ESTILO, episodio as ep_base  # noqa: F401

SR = 44100


def _wav(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return p


@pytest.fixture
def ep(ep_base):
    t = np.arange(int(SR * 20)) / SR
    _wav(ep_base / "trilha.wav", 0.4 * np.sin(2 * np.pi * 110 * t))
    _wav(ep_base / "05-som" / "voz.wav", 0.3 * np.sin(2 * np.pi * 300 * np.arange(int(SR * 3.0)) / SR))
    # catálogo completo: o orquestrador barra fonte sem origem, licença ou ano (como deve)
    o = {"fonte": "arquivo de teste", "licenca": "própria"}
    cat = [{"id": "foto-a", "tipo": "foto", "arquivo": "03-assets/a.jpg", "etiquetas": ["a"], "origem": o, "do_caso": True,
            "ano": 1990, "pessoas": []},
           {"id": "foto-b", "tipo": "foto", "arquivo": "03-assets/b.jpg", "etiquetas": ["b"], "origem": o, "do_caso": True,
            "ano": 1991, "pessoas": []},
           {"id": "ia", "tipo": "ia", "arquivo": "03-assets/ia.png", "etiquetas": ["ia"], "origem": o, "prompt": "uma sala",
            "rotulo": True, "sem_rosto_real": True}]
    (ep_base / "fontes.json").write_text(json.dumps({"fontes": cat}))
    return ep_base


def _plano(ep):
    c = lambda i, a, b, comp, **k: {"id": i, "ini": a, "fim": b, "componente": comp, **k}
    return {"dur": 6.0, "cenas": [c("A", 0, 3.0, "foto", fonte="foto-a"), c("B", 3.0, 6.0, "retrato", fonte="foto-b",
                                                                              params={"legenda": "Pessoa"})],
            "som": {"voz": [{"arquivo": "05-som/voz.wav", "em": 0.0}],
                    "trilha": {"arquivo": str(ep / "trilha.wav"), "trechos": [[0.0, None]], "curva": [[0, 1.0]]},
                    "efeitos": {"sopros": [], "impactos": [], "sopros_nos_cortes": True}}}


def test_parte_sai_de_ponta_a_ponta(ep):
    (ep / "02-plano").mkdir()
    (ep / "02-plano" / "p1.json").write_text(json.dumps(_plano(ep)))
    episodio.aprovar_plano(ep, ep / "02-plano" / "p1.json", "prancha vista pelo revisor")
    rel = episodio.produzir_parte(ep, ep / "02-plano" / "p1.json", ESTILO, "p1", fps=10)
    assert rel["video"].exists() and rel["audio"].exists()
    with wave.open(str(rel["audio"])) as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(6.0, abs=1e-3)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(rel["video"])],
                       capture_output=True, text=True, check=True)
    assert float(r.stdout.strip().split(",")[0]) == pytest.approx(6.0, abs=0.05)


def test_plano_que_quebra_regra_para_antes_de_renderizar(ep, monkeypatch):
    p = _plano(ep)
    p["cenas"][0]["fonte"] = "ia"  # IA sem rótulo: M08
    (ep / "p.json").write_text(json.dumps(p))
    chamou = []
    monkeypatch.setattr(episodio.render, "renderizar", lambda *a, **k: chamou.append(1))
    with pytest.raises(ValueError, match="M08"):
        episodio.produzir_parte(ep, ep / "p.json", ESTILO, "p1", fps=10)
    assert chamou == []


# --- correções da revisão da T24 ---------------------------------------------


def test_plano_sem_aprovacao_nao_renderiza(ep, monkeypatch):
    (ep / "p.json").write_text(json.dumps(_plano(ep)))
    chamou = []
    monkeypatch.setattr(episodio.render, "renderizar", lambda *a, **k: chamou.append(1))
    with pytest.raises(PermissionError, match="aprova"):
        episodio.produzir_parte(ep, ep / "p.json", ESTILO, "p1", fps=10)
    assert chamou == []


def test_aprovacao_vale_so_para_a_versao_aprovada_do_plano(ep, monkeypatch):
    (ep / "p.json").write_text(json.dumps(_plano(ep)))
    episodio.aprovar_plano(ep, ep / "p.json", "ok")
    p = _plano(ep)
    p["cenas"][1]["params"]["legenda"] = "Outra pessoa"
    (ep / "p.json").write_text(json.dumps(p))  # mudou depois de aprovado
    monkeypatch.setattr(episodio.render, "renderizar", lambda *a, **k: 1 / 0)
    with pytest.raises(PermissionError, match="aprova"):
        episodio.produzir_parte(ep, ep / "p.json", ESTILO, "p1", fps=10)


def test_prancha_de_previas_para_aprovar_sem_render(ep):
    (ep / "p.json").write_text(json.dumps(_plano(ep)))
    prancha = episodio.prancha(ep, ep / "p.json", ESTILO, "p1")
    assert prancha.exists() and prancha.suffix == ".jpg"


def test_plano_sem_som_e_barrado_antes_do_render(ep, monkeypatch):
    p = _plano(ep)
    del p["som"]
    (ep / "p.json").write_text(json.dumps(p))
    episodio.aprovar_plano(ep, ep / "p.json", "ok")
    monkeypatch.setattr(episodio.render, "renderizar", lambda *a, **k: 1 / 0)
    with pytest.raises(ValueError, match="som"):
        episodio.produzir_parte(ep, ep / "p.json", ESTILO, "p1", fps=10)


def test_palavras_no_formato_errado_tem_mensagem_clara(ep):
    (ep / "p.json").write_text(json.dumps(_plano(ep)))
    (ep / "pal.json").write_text(json.dumps([[0, 1, "uma"]]))
    episodio.aprovar_plano(ep, ep / "p.json", "ok")
    with pytest.raises(ValueError, match="fonte de voz"):
        episodio.produzir_parte(ep, ep / "p.json", ESTILO, "p1", fps=10, palavras_json=ep / "pal.json")


@pytest.mark.parametrize("nome", ["../fora", "a/b", ""])
def test_nome_de_parte_invalido(ep, nome):
    (ep / "p.json").write_text(json.dumps(_plano(ep)))
    with pytest.raises(ValueError, match="nome"):
        episodio.produzir_parte(ep, ep / "p.json", ESTILO, nome, fps=10)


def test_montar_confere_as_partes(ep):
    with pytest.raises(FileNotFoundError, match="nao-existe"):
        episodio.montar(ep, ["nao-existe"], "v1")


def test_mixagem_que_cobre_a_fala_barra_a_parte(ep, monkeypatch):
    """Revisão: a M32 gravava a folga, mas ninguém lia; agora a produção para nela."""
    (ep / "p.json").write_text(json.dumps(_plano(ep)))
    episodio.aprovar_plano(ep, ep / "p.json", "ok")
    monkeypatch.setattr(episodio.som, "_medir_folga", lambda *a, **k: {"alvo": 18, "pior": 6.0, "mediana": 6.0})
    with pytest.raises(ValueError, match="M32"):
        episodio.produzir_parte(ep, ep / "p.json", ESTILO, "p1", fps=10)


def test_montar_aceita_o_silencio_antes_do_encerramento(ep, monkeypatch):
    """Episódio real: a história acaba em fade e o CTA começa do zero; a M28 barrava essa emenda, que é de propósito."""
    saida = ep / "07-saida"; saida.mkdir(exist_ok=True)
    for n in ("cap1", "cap2", "encerramento"):
        (saida / f"{n}-mudo.mp4").write_bytes(b"v"); (saida / f"{n}-cru.wav").write_bytes(b"a")
    (ep / "encerramento" / "02-plano").mkdir(parents=True)
    (ep / "encerramento" / "02-plano" / "plano.json").write_text(json.dumps({"tipo": "encerramento"}))
    visto = {}
    def montar(partes, final, silencios_permitidos=()):
        visto["livres"] = list(silencios_permitidos); return {"emendas": [10.0, 20.0]}
    monkeypatch.setattr(episodio.entrega, "montar", montar)
    monkeypatch.setattr(episodio.entrega, "versionar", lambda f, p, v: p / f"{v}.mp4")
    monkeypatch.setattr(episodio.entrega, "whatsapp_partes", lambda f, s, cortes=(), **k: visto.setdefault("cortes", list(cortes)) or [s])
    episodio.montar(ep, ["cap1", "cap2", "encerramento"], "v1")
    # emenda 2 = entre a parte 2 e a 3 (o encerramento); as emendas viram pontos de corte do WhatsApp
    assert visto["livres"] == [2] and visto["cortes"] == [10.0, 20.0]
