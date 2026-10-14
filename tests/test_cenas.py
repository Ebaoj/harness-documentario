import json
import re
from pathlib import Path

import pytest
from PIL import Image

from scripts import cenas

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def episodio(tmp_path):
    """Episódio mínimo: duas fotos, um documento, um clipe com quadros, uma voz e uma IA."""
    ep = tmp_path / "ep"
    (ep / "03-assets" / "clipes" / "rua").mkdir(parents=True)
    for nome, cor in (("a.jpg", 90), ("b.jpg", 140), ("doc.jpg", 200), ("ia.png", 60)):
        Image.new("RGB", (300, 380), (cor, cor, cor)).save(ep / "03-assets" / nome)
    for i in range(1, 31):
        Image.new("RGB", (640, 360), (i * 5, 80, 80)).save(ep / "03-assets" / "clipes" / "rua" / f"f{i:04d}.jpg")
    fontes = [
        {"id": "foto-a", "tipo": "foto", "arquivo": "03-assets/a.jpg", "etiquetas": ["a"]},
        {"id": "foto-b", "tipo": "foto", "arquivo": "03-assets/b.jpg", "etiquetas": ["b"]},
        {"id": "doc", "tipo": "documento", "arquivo": "03-assets/doc.jpg", "etiquetas": ["doc"]},
        {"id": "ia", "tipo": "ia", "arquivo": "03-assets/ia.png", "etiquetas": ["ia"]},
        {"id": "rua", "tipo": "clipe", "arquivo": "x.mp4", "trecho": [10.0, 11.0], "etiquetas": ["rua"],
         "origem": {"fonte": "Emissora, 1990"}},
        {"id": "voz", "tipo": "voz", "arquivo": "v.wav", "trecho": [0, 9], "etiquetas": ["v"]},
    ]
    (ep / "fontes.json").write_text(json.dumps({"fontes": fontes}))
    return ep


def _plano():
    c = lambda i, a, b, comp, **k: {"id": i, "ini": a, "fim": b, "componente": comp, **k}
    return {
        "dur": 32.0,
        "capitulos": {"lista": [["Primeiro", "1900"], ["Segundo", "1910"]], "atual": 1, "ini": 0, "fim": 32},
        "vozes": [{"fonte": "voz", "em": 12.0, "legendas": [[12.0, 14.0, "Uma legenda."]]}],
        "cenas": [
            c("L", 0, 4, "linhaVida", params={"fotos": [{"ano": 1900, "fonte": "foto-a"}, {"ano": 1910, "fonte": "foto-b"}],
                                              "anos": [[0, 1900], [2, 1910]], "faixa": [1910, 1915],
                                              "capitulo": {"numero": 2, "total": 2, "titulo": "Segundo", "periodo": "1910"}}),
            c("F", 4, 8, "foto", fonte="foto-a", params={"z0": 1.1, "z1": 1.0}),
            c("R", 8, 12, "retrato", fonte="foto-a", params={"legenda": "Pessoa, 1900", "troca": {"fonte": "foto-b", "em": 10, "legenda": "Pessoa, 1910"}}),
            c("FF", 12, 16, "fotoFato", fonte="foto-b", voz={"fonte": "voz", "em": 12.0},
              params={"legenda": "Pessoa", "fatos": [{"em": 12.5, "rotulo": "1910", "valor": "UM FATO", "top": 380}],
                      "voz_rotulo": {"texto": "A VOZ DE ALGUÉM", "cor": "ambar"}}),
            c("A", 16, 19, "arquivo", fonte="rua", clipe={"de": 10.0, "velocidade": 0.3},
              params={"rotulo": "UM LUGAR", "x": -200, "w": 1180}),
            c("M", 19, 24, "mural", fonte="foto-a", fontes_extra=["doc"],
              params={"itens": [{"fontes": ["foto-a"], "legenda": "Anuário", "em": 19, "rotulo": "ANTES", "valor": "UM HOMEM"},
                                {"fontes": ["doc"], "em": 21.5, "rotulo": "DEPOIS", "valor": "UM PAPEL",
                                 "circulos": [{"x": 150, "y": 100, "rx": 80, "ry": 20, "em": 22}]}]}),
            c("P", 24, 27, "mapa", params={"area": {"lon0": -125, "lon1": 150, "lat0": 60},
                                         "origem": {"nome": "Origem", "lon": -97.3, "lat": 37.7},
                                         "pontos": [{"nome": "Um lugar", "lon": 35.2, "lat": 38.9, "em": 25}],
                                         "titulo": "UMA VIAGEM"}),
            c("I", 27, 29, "foto", fonte="ia", rotulo_ia=True),
            c("K", 29, 32, "lista", fonte="foto-b",
              params={"legenda": "Pessoa", "titulo": "A LISTA", "itens": [{"texto": "UM ITEM", "em": 29.5}],
                      "carimbo": {"texto": "CARIMBO", "em": 30.5}, "sub": {"texto": "explicação", "em": 31}}),
        ],
    }


ESTILO = RAIZ / "canais" / "exemplo" / "estilo.json"


def test_gerar_escreve_html_com_todas_as_cenas(episodio):
    saida = cenas.gerar(episodio, _plano(), ESTILO, episodio / "04-cenas" / "parte.html")
    html = saida.read_text()
    dados = json.loads(re.search(r"window.DADOS=(\{.*?\});\n", html, re.S).group(1))
    assert [c["id"] for c in dados["cenas"]] == ["L", "F", "R", "FF", "A", "M", "P", "I", "K"]
    assert dados["cenas"][4]["clip"]["quadros"] == 30
    assert "function render" in html


def test_componente_desconhecido_e_recusado(episodio):
    p = _plano()
    p["cenas"][1]["componente"] = "explosao"
    with pytest.raises(ValueError, match="explosao"):
        cenas.gerar(episodio, p, ESTILO, episodio / "x.html")


def test_fonte_fora_do_catalogo_e_recusada(episodio):
    p = _plano()
    p["cenas"][1]["fonte"] = "nao-existe"
    with pytest.raises(ValueError, match="nao-existe"):
        cenas.gerar(episodio, p, ESTILO, episodio / "x.html")


def test_clipe_sem_quadros_extraidos_e_recusado(episodio):
    import shutil

    shutil.rmtree(episodio / "03-assets" / "clipes" / "rua")
    with pytest.raises(ValueError, match="rua"):
        cenas.gerar(episodio, _plano(), ESTILO, episodio / "x.html")


INSTANTES = [1.0, 3.0, 6.0, 11.0, 13.0, 17.5, 20.0, 23.0, 25.5, 28.0, 31.5]


def _quadros(html, instantes, erros):
    """Abre uma página NOVA e devolve os quadros nos instantes pedidos (fora de ordem de propósito)."""
    from playwright.sync_api import sync_playwright

    out = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        pg.goto(Path(html).as_uri())
        pg.wait_for_function("window.pronto === true", timeout=10000)
        for t in instantes:
            pg.evaluate(f"window.render({t})")
            pg.wait_for_function("Array.from(document.images).every(i => i.complete)", timeout=10000)
            out[t] = (pg.screenshot(), pg.evaluate("document.body.innerText"))
        b.close()
    return out


def test_duas_execucoes_geram_o_mesmo_html_e_os_mesmos_quadros(episodio):
    """Revisão T18: duas gerações e duas páginas novas, uma delas renderizando na ordem inversa."""
    a = cenas.gerar(episodio, _plano(), ESTILO, episodio / "04-cenas" / "a.html").read_bytes()
    b = cenas.gerar(episodio, _plano(), ESTILO, episodio / "04-cenas" / "b.html").read_bytes()
    assert a == b
    erros = []
    q1 = _quadros(episodio / "04-cenas" / "a.html", INSTANTES, erros)
    q2 = _quadros(episodio / "04-cenas" / "b.html", list(reversed(INSTANTES)), erros)
    for t in INSTANTES:
        assert q1[t][0] == q2[t][0], f"quadro diferente em {t} s"
        assert "NaN" not in q1[t][1] and "undefined" not in q1[t][1], t
    assert erros == []


def test_intervalo_de_tempo_vazio_nao_vira_nan(episodio):
    p = _plano()
    p["cenas"][0]["params"]["anos"] = [[1, 1900], [1, 1910]]
    p["cenas"][0]["params"]["escurece"] = [[2, 2, 0.75]]
    saida = cenas.gerar(episodio, p, ESTILO, episodio / "04-cenas" / "nan.html")
    erros = []
    q = _quadros(saida, [1.0, 2.5], erros)
    assert all("NaN" not in texto for _, texto in q.values()) and erros == []


def test_texto_do_plano_aparece_literal(episodio):
    p = _plano()
    p["cenas"][3]["params"]["fatos"][0]["valor"] = "A&E <b>2022</b>"
    saida = cenas.gerar(episodio, p, ESTILO, episodio / "04-cenas" / "esc.html")
    erros = []
    (_, texto), = _quadros(saida, [13.0], erros).values()
    assert "A&E <b>2022</b>" in texto and erros == []


@pytest.mark.parametrize("estraga,trecho", [
    (lambda p: p["cenas"][2].update(ini=8.5), "buraco"),
    (lambda p: p["capitulos"].update(atual=5), "capítulo"),
    (lambda p: p.update(dur=40), "dur"),
    (lambda p: p["cenas"][6]["params"].pop("origem"), "origem"),
    (lambda p: p["cenas"][6]["params"]["area"].update(lon1=-125), "área"),
    (lambda p: p["cenas"][0]["params"].update(anos=[]), "anos"),
    (lambda p: p["cenas"][3]["params"]["fatos"][0].update(cor="amber"), "amber"),
])
def test_plano_mal_formado_vira_erro_com_o_id_da_cena(episodio, estraga, trecho):
    p = _plano()
    estraga(p)
    with pytest.raises(ValueError, match=trecho):
        cenas.gerar(episodio, p, ESTILO, episodio / "x.html")


def test_clipe_sem_trecho_no_catalogo_vira_erro(episodio):
    f = json.loads((episodio / "fontes.json").read_text())
    for x in f["fontes"]:
        if x["id"] == "rua":
            del x["trecho"]
    (episodio / "fontes.json").write_text(json.dumps(f))
    with pytest.raises(ValueError, match="trecho"):
        cenas.gerar(episodio, _plano(), ESTILO, episodio / "x.html")


def test_biblioteca_e_gerador_nao_conhecem_nenhum_caso():
    """R14: o que é do caso mora em videos/<slug>/; a biblioteca e o gerador são genéricos.
    Os nomes proibidos são os das pessoas dos catálogos de episódios presentes (videos/*/fontes.json),
    mais nomes de exemplo usados nos testes."""
    nomes = {"fulano", "cidade-exemplo"}
    for cat in RAIZ.glob("videos/*/fontes.json"):
        for f in json.loads(cat.read_text(encoding="utf-8")).get("fontes") or []:
            for p in f.get("pessoas") or []:
                nomes |= {n for n in str(p.get("nome", "")).lower().split() if len(n) > 3}
    for arq in [RAIZ / "motion" / "componentes.js", RAIZ / "scripts" / "cenas.py"]:
        texto = arq.read_text().lower()
        assert not [n for n in nomes if n in texto], arq
