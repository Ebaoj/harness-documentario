"""Gera o HTML de uma parte do vídeo a partir do plano de cenas (T18).

Entrada: a pasta do episódio (com fontes.json), o plano (scripts/plano.py), o estilo do canal
(canais/<canal>/estilo.json). Saída: um HTML autocontido que expõe window.render(T) e window.pronto,
com a biblioteca motion/componentes.js embutida. Nada aqui conhece um caso (R14).
"""
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # rodado como `python scripts/cenas.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RAIZ = Path(__file__).resolve().parent.parent
BIBLIOTECA = RAIZ / "motion" / "componentes.js"
TERRA = RAIZ / "motion" / "dados" / "ne_110m_land.geojson"  # Natural Earth 110m, domínio público
COMPONENTES = {"foto", "retrato", "fotoFato", "arquivo", "mural", "mapa", "linhaVida", "lista", "chamada"}
CORES = {"papel", "ambar", "vermelho", "apagado", "tinta"}
EPS = 1e-6

MOLDE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html,body{margin:0;padding:0;background:%(fundo)s;overflow:hidden}
  #stage{position:relative;width:1920px;height:1080px;overflow:hidden;background:%(fundo)s;font-family:%(display)s;color:%(papel)s}
  #cam{position:absolute;inset:0}
  .abs{position:absolute;text-shadow:0 2px 14px rgba(0,0,0,.85),0 0 2px rgba(0,0,0,.6)}
  .tw{font-family:%(maquina)s}
  .serif{font-family:%(serifa)s}
  #grain{position:absolute;inset:0;width:1920px;height:1080px;opacity:%(grao)s;mix-blend-mode:screen;image-rendering:pixelated}
  #vig{position:absolute;inset:0;background:radial-gradient(ellipse at 50%% 50%%,rgba(0,0,0,0) 45%%,rgba(0,0,0,.75) 100%%)}
</style></head>
<body>
<div id="stage"><div id="cam"></div><canvas id="grain" width="480" height="270"></canvas><div id="vig"></div></div>
<script>
window.DADOS=%(dados)s;
</script>
<script>
%(biblioteca)s
</script>
</body></html>
"""


def _rel(alvo, saida):
    return os.path.relpath(alvo, Path(saida).parent).replace(os.sep, "/")


def _projetar_mapa(params):
    """Contorno de terra e pontos projetados (retangular) na área pedida: lon0..lon1, lat0 no topo."""
    a = params.get("area") or {}
    L0, L1, T0 = a.get("lon0", -180), a.get("lon1", 180), a.get("lat0", 80)
    S = 1760 / (L1 - L0)

    def P(lo, la):
        return round(80 + (lo - L0) * S, 1), round(300 + (T0 - la) * S, 1)

    caminhos = []
    for f in json.loads(TERRA.read_text())["features"]:
        g = f["geometry"]
        for poly in g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]:
            anel = poly[0]
            if all(lo < L0 - 5 or lo > L1 + 5 for lo, _ in anel):
                continue
            caminhos.append("M" + " L".join("%.1f,%.1f" % P(lo, la) for lo, la in anel) + "Z")

    def ponto(q):
        x, y = P(q["lon"], q["lat"])
        return {**q, "x": x, "y": y}

    return {"terra": " ".join(caminhos), "origem": ponto(params["origem"]),
            "pontos": [ponto(q) for q in params.get("pontos", [])]}


def _fontes_da_cena(c):
    o = c.get("params") or {}
    ids = [c.get("fonte")] + list(c.get("fontes_extra") or [])
    ids += [f.get("fonte") for f in o.get("fotos") or []]
    ids += [(o.get("troca") or {}).get("fonte")]
    ids += [i for it in o.get("itens") or [] for i in it.get("fontes") or []]
    return [i for i in ids if i]


def _cores_da_cena(c):
    o = c.get("params") or {}
    for f in (o.get("fatos") or []) + (o.get("textos") or []) + [o.get("voz_rotulo") or {}]:
        if isinstance(f, dict) and "cor" in f:
            yield f["cor"]


def validar(plano, cat):
    """Erros de forma que quebrariam a cena na tela; cada um nomeia a cena."""
    cenas = sorted(plano["cenas"], key=lambda x: x["ini"])
    for a, b in zip(cenas, cenas[1:]):
        if abs(b["ini"] - a["fim"]) > EPS:
            tipo = "buraco" if b["ini"] > a["fim"] else "sobreposição"
            raise ValueError(f"cenas {a['id']} e {b['id']}: {tipo} de {abs(b['ini'] - a['fim']):.2f} s")
    if plano.get("dur") is not None and abs(plano["dur"] - cenas[-1]["fim"]) > EPS:
        raise ValueError(f"dur {plano['dur']} diferente do fim da última cena ({cenas[-1]['fim']})")
    cap = plano.get("capitulos")
    if cap and not 1 <= cap.get("atual", 0) <= len(cap.get("lista") or []):
        raise ValueError(f"capítulo atual {cap.get('atual')} fora da lista de {len(cap.get('lista') or [])}")
    for c in cenas:
        o = c.get("params") or {}
        for cor in _cores_da_cena(c):
            if cor not in CORES:
                raise ValueError(f"cena {c['id']}: cor {cor!r} (válidas: {sorted(CORES)})")
        if c.get("componente") == "linhaVida" and "anos" in o and not (
                isinstance(o["anos"], list) and o["anos"] and all(isinstance(x, list) and len(x) == 2 for x in o["anos"])):
            raise ValueError(f"cena {c['id']}: anos deve ser uma lista de [tempo, ano]")
        if c.get("componente") == "mapa":
            if not o.get("origem"):
                raise ValueError(f"cena {c['id']}: mapa sem origem")
            a = o.get("area") or {}
            if a.get("lon1", 180) <= a.get("lon0", -180):
                raise ValueError(f"cena {c['id']}: área do mapa com lon1 <= lon0")
        if c.get("componente") == "arquivo":
            f = cat.get(c.get("fonte")) or {}
            if f.get("tipo") != "clipe" or not isinstance(f.get("trecho"), list) or len(f["trecho"]) != 2:
                raise ValueError(f"cena {c['id']}: janela de arquivo precisa de uma fonte clipe com trecho no catálogo")


def gerar(pasta_ep, plano, estilo, saida):
    pasta_ep, saida = Path(pasta_ep), Path(saida)
    estilo = json.loads(Path(estilo).read_text(encoding="utf-8"))
    cat = {f["id"]: f for f in json.loads((pasta_ep / "fontes.json").read_text(encoding="utf-8"))["fontes"]}
    recursos, cenas = {}, []
    for c in plano["cenas"]:
        for i in _fontes_da_cena(c):
            if i not in cat:
                raise ValueError(f"cena {c['id']}: fonte {i!r} não está no catálogo")
    validar(plano, cat)
    for c in sorted(plano["cenas"], key=lambda x: x["ini"]):
        comp = c.get("componente")
        if comp not in COMPONENTES:
            raise ValueError(f"cena {c['id']}: componente {comp!r} não existe (há: {sorted(COMPONENTES)})")
        c = json.loads(json.dumps(c))
        for i in _fontes_da_cena(c):
            if i not in cat:
                raise ValueError(f"cena {c['id']}: fonte {i!r} não está no catálogo")
            f = cat[i]
            if f.get("tipo") != "clipe":
                recursos[i] = _rel(pasta_ep / f["arquivo"], saida)
        if comp == "arquivo":
            f = cat[c["fonte"]]
            d = pasta_ep / "03-assets" / "clipes" / c["fonte"]
            quadros = len(list(d.glob("f*.jpg"))) if d.is_dir() else 0
            if not quadros:
                raise ValueError(f"cena {c['id']}: clipe {c['fonte']!r} sem quadros extraídos em {d}")
            cl = c.get("clipe") or {}
            c["clip"] = {"dir": _rel(d, saida), "quadros": quadros, "trecho0": f["trecho"][0],
                         "de": cl.get("de", f["trecho"][0]), "velocidade": cl.get("velocidade", 1.0),
                         "fonte_texto": str((f.get("origem") or {}).get("fonte", "")).upper()}
        if comp == "mapa":
            c["mapa"] = _projetar_mapa(c.get("params") or {})
        cenas.append(c)
    dados = {"estilo": estilo, "cenas": cenas, "vozes": plano.get("vozes") or [], "recursos": recursos,
             "capitulos": plano.get("capitulos"), "dur": plano.get("dur")}
    f = estilo["fontes"]
    html = MOLDE % {"fundo": estilo["cores"]["fundo"], "papel": estilo["cores"]["papel"], "display": f["display"],
                    "maquina": f["maquina"], "serifa": f["serifa"], "grao": estilo.get("grao", .1),
                    "dados": json.dumps(dados, ensure_ascii=False).replace("<", "\\u003c"),
                    "biblioteca": BIBLIOTECA.read_text(encoding="utf-8")}
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(html, encoding="utf-8")
    return saida


def main(argv=None):
    """Uso: python -m scripts.cenas <pasta do episódio> <plano.json> <estilo.json> <saida.html>"""
    a = argv if argv is not None else sys.argv[1:]
    if len(a) != 4:
        print(main.__doc__)
        return 2
    plano = json.loads(Path(a[1]).read_text(encoding="utf-8"))
    print(gerar(a[0], plano, a[2], a[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
