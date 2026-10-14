"""Mede quao ocupado esta o espaco de documentario longo de historia/economia em PT-BR.

Funcoes puras (testadas) mais uma CLI que le paginas publicas do YouTube, sem login,
com poucas requisicoes em paralelo. Uso:
    python scripts/espaco.py coletar     # busca -> referencias/espaco-ptbr/busca.json
    python scripts/espaco.py canais      # about + videos -> canais.json
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PASTA = Path(__file__).resolve().parent.parent / "referencias" / "espaco-ptbr"
FILTROS = {"mes": "CAMSBAgEEAE%3D", "ano": "CAMSBAgDEAE%3D"}
MIN_LONGO_S = 480  # abaixo de 8 min nao conta como documentario/explicador longo
MAX_INSCRITOS = 60000
MAX_PARALELO = 8


# ---------- funcoes puras ----------

def parse_numero(texto):
    """'1.5K', '2,3 mil', '1,2 mi', '1.234 visualizações' -> numero. None se nao achar."""
    if not texto:
        return None
    t = texto.strip().lower()
    m = re.match(r"([\d.,]+)\s*(k|mil|mi|m|bi|b)?\b", t)
    if not m:
        return None
    num, suf = m.group(1), m.group(2)
    if suf:
        mult = {"k": 1e3, "mil": 1e3, "m": 1e6, "mi": 1e6, "b": 1e9, "bi": 1e9}[suf]
        return round(float(num.replace(",", ".")) * mult)
    return int(re.sub(r"[.,]", "", num))


_UNIDADES = [  # (regex, dias)
    (r"(\d+)\s*(?:anos?|years?|y)\b", 365),
    (r"(\d+)\s*(?:m[eê]s(?:es)?|months?|mo)\b", 30),
    (r"(\d+)\s*(?:semanas?|sem|weeks?|w)\b", 7),
    (r"(\d+)\s*(?:dias?|days?|d)\b", 1),
    (r"(\d+)\s*(?:horas?|hours?|h|minutos?|minutes?|min|segundos?|seconds?)\b", 0),
]


def parse_idade_dias(texto):
    """'há 6 dias', '6d ago', 'há 2 semanas' -> dias (aprox.). None se nao reconhecer."""
    if not texto:
        return None
    t = texto.lower()
    for rx, dias in _UNIDADES:
        m = re.search(rx, t)
        if m:
            return int(m.group(1)) * dias
    return None


def parse_duracao(texto):
    """'12:34' -> 754 s; '1:02:03' -> 3723 s."""
    if not texto or not re.fullmatch(r"\d+(:\d{1,2}){1,2}", texto.strip()):
        return None
    total = 0
    for p in texto.strip().split(":"):
        total = total * 60 + int(p)
    return total


def mediana(valores):
    return statistics.median(valores) if valores else 0


def ano_entrada(texto):
    m = re.search(r"(20\d{2})", texto or "")
    return int(m.group(1)) if m else None


def pequeno_e_recente(inscritos, ano):
    return inscritos is not None and ano is not None and inscritos <= MAX_INSCRITOS and ano >= 2025


def extrai_initial_data(html):
    m = re.search(r"ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _walk(o, chave):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == chave:
                yield v
            else:
                yield from _walk(v, chave)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, chave)


def videos_da_busca(dados):
    """videoRenderer -> lista de videos longos (shorts e sem duracao descartados)."""
    saida = []
    for v in _walk(dados, "videoRenderer"):
        try:
            dur = parse_duracao(v.get("lengthText", {}).get("simpleText"))
            if dur is None or dur < MIN_LONGO_S:
                continue
            run = v["ownerText"]["runs"][0]
            saida.append({
                "titulo": v["title"]["runs"][0]["text"],
                "canal": run["text"],
                "canal_id": run["navigationEndpoint"]["browseEndpoint"]["browseId"],
                "views": parse_numero(v.get("viewCountText", {}).get("simpleText")) or 0,
                "dias": parse_idade_dias(v.get("publishedTimeText", {}).get("simpleText")),
                "duracao_s": dur,
            })
        except (KeyError, IndexError, TypeError):
            continue
    return saida


def perfil_do_about(html):
    def g(p):
        m = re.search(p, html)
        return m.group(1) if m else None
    subs = g(r'"subscriberCountText":"([^"]+)"')
    ent = g(r'"joinedDateText":\{"content":"([^"]+)"')
    return {
        "inscritos": parse_numero(subs),
        "inscritos_txt": subs,
        "entrada_txt": ent,
        "ano": ano_entrada(ent),
        "pais": g(r'"country":"([^"]+)"'),
        "handle": g(r'canonicalChannelUrl":"https?://www\.youtube\.com/(@[^"]+)"'),
    }


def videos_do_canal(dados):
    """lockupViewModel -> [{titulo, views, dias}] (so itens com views e idade reconheciveis)."""
    saida = []
    for lk in _walk(dados, "lockupViewModel"):
        cs = [x for x in _walk(lk, "content") if isinstance(x, str)]
        titulo = cs[0] if cs else ""
        views = dias = None
        for c in cs[1:]:
            if views is None and re.search(r"visualiza|views", c, re.I) or (views is None and re.fullmatch(r"[\d.,]+\s*(K|M|B|mil|mi)?", c.strip(), re.I)):
                views = parse_numero(c)
            elif dias is None:
                dias = parse_idade_dias(c)
        if views is not None and dias is not None:
            saida.append({"titulo": titulo[:80], "views": views, "dias": dias})
    return saida


def resumo_canal(videos):
    vs = [v["views"] for v in videos]
    return {"n": len(vs), "mediana": mediana(vs), "minimo": min(vs) if vs else 0, "maximo": max(vs) if vs else 0}


def classe_canal(perfil):
    ins, ano = perfil.get("inscritos"), perfil.get("ano")
    if ins is None:
        return "desconhecido"
    if ins > MAX_INSCRITOS:
        return "grande"
    return "pequeno_recente" if pequeno_e_recente(ins, ano) else "pequeno_antigo"


def estatisticas_busca(busca, canais):
    """Por consulta: videos longos, fatia de videos e de views vindas de canais grandes."""
    est = {}
    for r in busca:
        e_q = est.setdefault(r["consulta"], {"videos": 0, "_g": 0, "_vg": 0, "_vt": 0})
        for v in r["videos"]:
            e_q["videos"] += 1
            e_q["_vt"] += v["views"]
            if classe_canal(canais.get(v["canal_id"], {})) == "grande":
                e_q["_g"] += 1
                e_q["_vg"] += v["views"]
    for e_q in est.values():
        n, vt = e_q["videos"], e_q.pop("_vt")
        g, vg = e_q.pop("_g"), e_q.pop("_vg")
        e_q["pct_videos_grandes"] = g / n if n else None
        e_q["pct_views_grandes"] = vg / vt if vt else None
    return est


# ---------- rede (nao testada) ----------

def _get(url, tentativas=3):
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}hl=pt-BR&gl=BR"
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
            return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            if i == tentativas - 1:
                raise
            time.sleep(2 * (i + 1))


def carregar_consultas():
    return json.loads((PASTA / "consultas.json").read_text())


def coletar():
    PASTA.mkdir(parents=True, exist_ok=True)
    tarefas = [(q, k) for q in carregar_consultas() for k in FILTROS]

    def uma(t):
        q, k = t
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}&sp={FILTROS[k]}"
        try:
            d = extrai_initial_data(_get(url))
            return {"consulta": q, "janela": k, "ok": d is not None, "videos": videos_da_busca(d) if d else []}
        except Exception as exc:  # noqa: BLE001
            return {"consulta": q, "janela": k, "ok": False, "erro": str(exc), "videos": []}

    with ThreadPoolExecutor(MAX_PARALELO) as ex:
        res = list(ex.map(uma, tarefas))
    (PASTA / "busca.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"{len(res)} buscas, {sum(r['ok'] for r in res)} ok, {sum(len(r['videos']) for r in res)} videos longos")


def canais():
    busca = json.loads((PASTA / "busca.json").read_text())
    ids = {}
    for r in busca:
        for v in r["videos"]:
            ids.setdefault(v["canal_id"], v["canal"])

    def um(cid):
        try:
            p = perfil_do_about(_get(f"https://www.youtube.com/channel/{cid}/about"))
            d = extrai_initial_data(_get(f"https://www.youtube.com/channel/{cid}/videos"))
            vs = videos_do_canal(d)[:12] if d else []
            return cid, {**p, "nome": ids[cid], "recentes": vs, **resumo_canal(vs)}
        except Exception as exc:  # noqa: BLE001
            return cid, {"nome": ids[cid], "erro": str(exc)}

    with ThreadPoolExecutor(MAX_PARALELO) as ex:
        res = dict(ex.map(um, list(ids)))
    (PASTA / "canais.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"{len(res)} canais, {sum('erro' in v for v in res.values())} com erro")


if __name__ == "__main__":
    {"coletar": coletar, "canais": canais}[sys.argv[1]]()
