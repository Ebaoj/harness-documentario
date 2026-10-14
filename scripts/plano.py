"""Verificador do plano de cenas de uma parte do vídeo (T17).

O plano (`plano.json`) é dado do episódio: {"dur", "revelacao"?, "cenas": [...]}, e cada cena é
  {"id", "ini", "fim", "fonte"?, "clipe"?: {"de", "velocidade"}, "voz"?: {"fonte", "em"},
   "texto"?: [{"texto", "sobre_video", "intencional"?}], "rotulo_ia"?, "mostra"?: [...], "legendas"?: [[ini, fim, texto]]}
com tempos em segundos do vídeo e "fonte" apontando para o catálogo (scripts/fontes.py).
As verificações seguem o contrato do modelo: função(contexto) -> lista de erros, com
contexto = {"plano", "fontes" (lista do catálogo), "palavras" ({fonte de voz: [[ini, fim], ...]})}.
"""
import re
import sys
from pathlib import Path

if __package__ in (None, ""):  # rodado como `python scripts/plano.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import fontes as _fontes  # noqa: E402

CENA_MINIMA = 3.0          # M01
REAL_MINIMO = 0.51         # M02
JANELA, JANELA_MINIMA = 15.0, 0.30   # só janelas inteiras: o pedaço final menor que 15 s não é julgado sozinho
PASSO_JANELA = 0.5
TOLERANCIA_LEGENDA = 0.3   # M11
EPS = 1e-6


def _cena_ok(c):
    return (isinstance(c, dict) and c.get("id") and all(isinstance(c.get(k), (int, float)) and not isinstance(c.get(k), bool)
                                                         for k in ("ini", "fim")) and c["fim"] > c["ini"])


def _cenas(ctx):
    return sorted((c for c in (ctx.get("plano") or {}).get("cenas") or [] if _cena_ok(c)), key=lambda c: c["ini"])


def _catalogo(ctx):
    return {f["id"]: f for f in ctx.get("fontes") or [] if isinstance(f, dict) and f.get("id")}


def _ids(c):
    return [i for i in [c.get("fonte")] + list(c.get("fontes_extra") or []) if i]


def cena_real(c, cat):
    f = cat.get(c.get("fonte"))
    return bool(f) and _fontes.conta_como_real(f)


def checar_duracao(ctx):
    erros, cenas = [], _cenas(ctx)
    for i, c in enumerate(cenas):
        if c["fim"] - c["ini"] < CENA_MINIMA - EPS and i < len(cenas) - 1:
            erros.append(f"M01 {c['id']}: {c['fim'] - c['ini']:.2f} s (mínimo {CENA_MINIMA:.0f} s)")
        if i and abs(c["ini"] - cenas[i - 1]["fim"]) > EPS:
            tipo = "buraco" if c["ini"] > cenas[i - 1]["fim"] else "sobreposição"
            erros.append(f"M01 {cenas[i - 1]['id']} e {c['id']}: {tipo} de {abs(c['ini'] - cenas[i - 1]['fim']):.2f} s")
    return erros


def _uniao(intervalos):
    out = []
    for a, b in sorted(intervalos):
        if out and a <= out[-1][1] + EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


ENCERRAMENTO_MAX = 40.0      # M02: a tela de like/inscrição no fim não é conteúdo (decisão de produto)


def checar_real(ctx):
    cenas, cat = _cenas(ctx), _catalogo(ctx)
    if not cenas:
        return []
    p = ctx.get("plano") or {}
    ini, fim = cenas[0]["ini"], max(c["fim"] for c in cenas)
    total = fim - ini
    # mede o que as cenas ocupam, não o dur declarado (um dur pequeno não pode dispensar um plano longo)
    if p.get("tipo") == "encerramento" and total <= ENCERRAMENTO_MAX and not p.get("vozes"):
        return []
    if total <= EPS:
        return []
    reais = _uniao([(c["ini"], c["fim"]) for c in cenas if cena_real(c, cat)])  # sobreposição não conta em dobro

    def real(a, b):
        return sum(max(0.0, min(b, y) - max(a, x)) for x, y in reais)

    erros = []
    parte = real(ini, fim) / total
    if parte < REAL_MINIMO - EPS:
        erros.append(f"M02 imagem real em {parte:.0%} do tempo (mínimo 51%)")
    inicios, s = [], ini
    while s + JANELA <= fim + EPS:
        inicios.append(s)
        s += PASSO_JANELA
    if total >= JANELA - EPS:
        inicios.append(fim - JANELA)  # a última janela inteira sempre é julgada
    piores = [(real(s, s + JANELA) / JANELA, s) for s in inicios]
    piores = [x for x in piores if x[0] < JANELA_MINIMA - EPS]
    if piores:
        r, s = min(piores)
        erros.append(f"M02 janela de 15 s com {r:.0%} de imagem real a partir de {s:.1f} s (mínimo 30%)")
    return erros


def checar_texto(ctx):
    return [f"M04 {c['id']}: texto {t.get('texto')!r} sobre vídeo real sem intenção declarada"
            for c in _cenas(ctx) for t in c.get("texto") or []
            if isinstance(t, dict) and t.get("sobre_video") and not str(t.get("intencional", "")).strip()]


def checar_revelacao(ctx):
    rev = (ctx.get("plano") or {}).get("revelacao")
    if rev is None:
        return []
    cat, erros = _catalogo(ctx), []
    for c in _cenas(ctx):
        for i in _ids(c):
            f = cat.get(i) or {}
            if c["ini"] < rev - EPS and f.get("rosto", True) and any(isinstance(p, dict) and p.get("papel") == "acusado"
                                                                    for p in f.get("pessoas") or []):
                erros.append(f"M06 {c['id']}: rosto do acusado ({i}) em {c['ini']:.1f} s, antes da revelação em {rev:.1f} s")
    return erros


def _casa(pedido, etiqueta):
    """Palavra inteira, sem diferença de maiúsculas: 'pai' não casa com 'paisagem'."""
    return re.search(r"(?<!\w)" + re.escape(pedido.lower()) + r"(?!\w)", etiqueta.lower()) is not None


def checar_semantica(ctx):
    cat, erros = _catalogo(ctx), []
    for c in _cenas(ctx):
        pede = c.get("mostra") or []
        if not pede:
            continue
        etiquetas = [e for i in _ids(c) for e in (cat.get(i) or {}).get("etiquetas") or [] if isinstance(e, str)]
        faltam = [m for m in pede if not any(_casa(m, e) for e in etiquetas)]
        if faltam:
            erros.append(f"M07 {c['id']}: a frase pede {faltam}, a imagem mostra {etiquetas}")
    return erros


def checar_ia(ctx):
    cat = _catalogo(ctx)
    return [f"M08 {c['id']}: imagem de IA ({i}) sem o rótulo de reconstituição na tela"
            for c in _cenas(ctx) for i in _ids(c) if (cat.get(i) or {}).get("tipo") == "ia" and c.get("rotulo_ia") is not True]


def _nomes(f):
    return {str(p.get("nome", "")).strip().lower() for p in (f or {}).get("pessoas") or []
            if isinstance(p, dict) and str(p.get("nome", "")).strip()}


SINCRONIA = 0.1


def checar_entrevista(ctx):
    cat, erros = _catalogo(ctx), []
    for c in _cenas(ctx):
        f = cat.get(c.get("fonte")) or {}
        if f.get("tipo") != "clipe" or f.get("natureza") != "entrevista":
            continue
        v = c.get("voz") or {}
        voz = cat.get(v.get("fonte"))
        if not voz or not (voz["id"] == f["id"] or _nomes(voz) & _nomes(f)):
            erros.append(f"M10 {c['id']}: entrevista na tela sem a voz da própria pessoa")
            continue
        em, tv = v.get("em", 0.0), voz.get("trecho") or [0, 0]
        if em > c["ini"] + EPS or em + (tv[1] - tv[0]) < c["fim"] - EPS:
            erros.append(f"M10 {c['id']}: a voz ({em:.2f} a {em + tv[1] - tv[0]:.2f} s) não cobre a cena")
        clipe = c.get("clipe") or {}
        mesma = (voz.get("origem") or {}).get("fonte") and (voz.get("origem") or {}).get("fonte") == (f.get("origem") or {}).get("fonte")
        if mesma and "de" in clipe and abs((clipe["de"] - tv[0]) - (c["ini"] - em)) > SINCRONIA:
            erros.append(f"M10 {c['id']}: boca fora de sincronia com a voz em {(clipe['de'] - tv[0]) - (c['ini'] - em):+.2f} s")
    return erros


def checar_trecho(ctx):
    cat, erros = _catalogo(ctx), []
    for c in _cenas(ctx):
        f = cat.get(c.get("fonte")) or {}
        if f.get("tipo") != "clipe":
            continue
        a, b = f.get("trecho") or [0, 0]
        clipe = c.get("clipe") or {}
        de, vel = clipe.get("de", a), clipe.get("velocidade", 1.0)
        if not isinstance(vel, (int, float)) or vel <= 0:
            erros.append(f"M15 {c['id']}: velocidade {vel!r} inválida")
            continue
        ate = de + (c["fim"] - c["ini"]) * vel
        if de < a - EPS or ate > b + EPS:
            erros.append(f"M15 {c['id']}: usa {de:.2f} a {ate:.2f} s da fonte, trecho útil é {a:.2f} a {b:.2f} s")
    return erros


PONTUACAO = tuple(".?!,;:")


def checar_legenda(ctx):
    """M11: cada legenda começa no início de uma frase da fala (ou continua a legenda anterior sem buraco)
    e termina dentro da última palavra ou até 0,3 s depois dela."""
    erros, palavras = [], ctx.get("palavras") or {}
    for v in (ctx.get("plano") or {}).get("vozes") or []:
        itens = v.get("legendas") or []
        if not itens:
            continue
        ws = palavras.get(v.get("fonte"))
        if not ws:
            erros.append(f"M11 voz {v.get('fonte')!r}: legenda sem a transcrição palavra a palavra")
            continue
        em = v.get("em", 0.0)
        inicios_de_frase = [w[0] + em for i, w in enumerate(ws)
                            if i == 0 or (len(ws[i - 1]) > 2 and str(ws[i - 1][2]).rstrip().rstrip("\"'”»").endswith(PONTUACAO))]
        anterior = None
        for item in itens:
            if not (isinstance(item, (list, tuple)) and len(item) == 3):
                erros.append(f"M11 voz {v.get('fonte')!r}: legenda mal formada {item!r}")
                continue
            a, b, txt = item
            minuscula = txt[:1].islower() or txt[:2].lstrip("“\"")[:1].islower()
            if anterior is not None and a < anterior - EPS:
                erros.append(f"M11 legenda {txt[:40]!r} ({a:.2f} s) começa antes da anterior acabar ({anterior:.2f} s)")
                anterior = b
                continue
            emenda = anterior is not None and a - anterior <= 0.15
            # continua a anterior: começa em minúscula, ou emenda sem buraco (a pontuação do transcritor falha)
            if minuscula or emenda:
                ok_ini = anterior is not None and abs(a - anterior) <= 0.15 and any(abs(w[0] + em - a) <= TOLERANCIA_LEGENDA for w in ws)
            else:
                ok_ini = any(abs(x - a) <= TOLERANCIA_LEGENDA for x in inicios_de_frase)
            ok_fim = any(w[0] + em - EPS <= b <= w[1] + em + TOLERANCIA_LEGENDA for w in ws)
            if not ok_ini:
                erros.append(f"M11 legenda {txt[:40]!r} ({a:.2f} s) começa no meio de uma frase ou fora da fala")
            elif not ok_fim:
                erros.append(f"M11 legenda {txt[:40]!r} termina em {b:.2f} s, fora da fala")
            anterior = b
    return erros


REGRAS = {
    "plano_duracao": checar_duracao,
    "plano_real": checar_real,
    "plano_texto": checar_texto,
    "plano_revelacao": checar_revelacao,
    "plano_semantica": checar_semantica,
    "plano_ia": checar_ia,
    "plano_entrevista": checar_entrevista,
    "plano_trecho": checar_trecho,
    "plano_legenda": checar_legenda,
}


def validar(ctx):
    cat = _catalogo(ctx)
    brutas = (ctx.get("plano") or {}).get("cenas") or []
    erros_forma = [f"cena {c.get('id') if isinstance(c, dict) else c!r}: precisa de id, ini e fim numéricos com fim > ini"
                   for c in brutas if not _cena_ok(c)]
    erros = [f"{c['id']}: fonte {c['fonte']!r} não está no catálogo" for c in _cenas(ctx)
             if c.get("fonte") and c["fonte"] not in cat]
    erros += [f"{c['id']}: voz {c['voz'].get('fonte')!r} não está no catálogo" for c in _cenas(ctx)
              if c.get("voz") and c["voz"].get("fonte") not in cat]
    for f in REGRAS.values():
        erros += f(ctx)
    return erros_forma + erros


def main(argv=None):
    """Uso: python -m scripts.plano <pasta do episódio> <plano.json> [palavras.json]
    Lê o catálogo <pasta>/fontes.json e mostra cada regra que o plano quebra."""
    import argparse
    import json

    a = argparse.ArgumentParser(prog="plano")
    a.add_argument("pasta")
    a.add_argument("plano")
    a.add_argument("palavras", nargs="?")
    a = a.parse_args(argv)
    ctx = {"plano": json.loads(Path(a.plano).read_text(encoding="utf-8")),
           "fontes": json.loads((Path(a.pasta) / "fontes.json").read_text(encoding="utf-8"))["fontes"],
           "palavras": json.loads(Path(a.palavras).read_text(encoding="utf-8")) if a.palavras else {}}
    erros = validar(ctx)
    for e in erros:
        print(f"[FALHA] {e}")
    if not erros:
        cenas = ctx["plano"]["cenas"]
        print(f"plano ok: {len(cenas)} cenas, {cenas[-1]['fim'] - cenas[0]['ini']:.1f} s")
    sys.stdout.flush()
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
