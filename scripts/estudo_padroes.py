"""Junta as fichas, promove padrões que aparecem em pelo menos 3 vídeos e compara melhores x mediana/abaixo.

A biblioteca guarda o padrão e a evidência (canal, vídeo, minutagem), nunca o texto da narração, nem tradução ou
resumo de conteúdo: por isso as notas e as descrições livres das fichas ficam fora dela. Quem quiser ver o que o padrão
faz no vídeo assiste ao trecho na minutagem da evidência.
Marcas: so_nos_melhores, nos_dois_grupos, so_na_mediana. Padrão presente em todos os vídeos não explica desempenho.
"""
import json
import statistics
import sys
from pathlib import Path

MINIMO_VIDEOS = 3
LIMITE_TENDENCIA = 0.25  # diferença de taxa (melhores menos base) a partir da qual há tendência
CAMPOS_EVIDENCIA = {"video_id", "inicio_s", "fim_s"}
LIMITE_AMPLA_S = 180  # evidência com janela maior que isto não prova "o melhor trecho": fica marcada


def _numero(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _checar_evidencia(ev, video_id):
    """Revalida a evidência na hora de agregar: uma ficha.json editada à mão não entra na biblioteca."""
    if not isinstance(ev, dict):
        raise ValueError("padrão sem evidência")
    extra = set(ev) - CAMPOS_EVIDENCIA
    if extra:
        raise ValueError(f"evidência com campo que pode carregar texto da narração: {sorted(extra)}")
    if set(ev) != CAMPOS_EVIDENCIA:
        raise ValueError("evidência incompleta (precisa de video_id, inicio_s e fim_s)")
    if ev["video_id"] != video_id:
        raise ValueError(f"evidência com video_id {ev['video_id']!r} dentro da ficha de {video_id!r}")
    a, b = ev["inicio_s"], ev["fim_s"]
    if not (_numero(a) and _numero(b) and 0 <= a <= b):
        raise ValueError(f"evidência com minutagem inválida ({a!r} a {b!r})")


def agregar(entradas, minimo=MINIMO_VIDEOS):
    """entradas: [{"canal", "grupo": "melhores"|"base", "ficha": {...}}]. Devolve uma lista ordenada por força."""
    totais = {"melhores": 0, "base": 0}
    por_canal_total = {}
    padroes = {}
    for e in entradas:
        canal, grupo, ficha = e["canal"], e["grupo"], e["ficha"]
        totais[grupo] += 1
        por_canal_total.setdefault(canal, {"melhores": 0, "base": 0})[grupo] += 1
        vistos = set()
        for p in ficha["padroes"]:
            _checar_evidencia(p.get("evidencia"), ficha["video_id"])
            reg = padroes.setdefault(p["id"], {"id": p["id"], "evid": [], "videos": {}})
            reg["videos"][ficha["video_id"]] = (canal, grupo)
            if (p["id"], ficha["video_id"]) in vistos:
                continue
            vistos.add((p["id"], ficha["video_id"]))
            reg["evid"].append({"canal": canal, "video_id": ficha["video_id"], "grupo": grupo,
                                "inicio_s": p["evidencia"]["inicio_s"], "fim_s": p["evidencia"]["fim_s"],
                                "ampla": p["evidencia"]["fim_s"] - p["evidencia"]["inicio_s"] > LIMITE_AMPLA_S})
    total_videos = totais["melhores"] + totais["base"]
    saida = []
    for pid, reg in padroes.items():
        n_melhores = sum(1 for c, g in reg["videos"].values() if g == "melhores")
        n_base = len(reg["videos"]) - n_melhores
        canais = sorted({c for c, _ in reg["videos"].values()})
        if n_base == 0:
            grupo = "so_nos_melhores"
        elif n_melhores == 0:
            grupo = "so_na_mediana"
        else:
            grupo = "nos_dois_grupos"
        taxa_m = n_melhores / totais["melhores"] if totais["melhores"] else 0.0
        taxa_b = n_base / totais["base"] if totais["base"] else 0.0
        dif = round(taxa_m - taxa_b, 2)
        por_canal = {}
        for canal, tot in sorted(por_canal_total.items()):
            m = sum(1 for c, g in reg["videos"].values() if c == canal and g == "melhores")
            b = sum(1 for c, g in reg["videos"].values() if c == canal and g == "base")
            por_canal[canal] = {"melhores": f"{m}/{tot['melhores']}", "base": f"{b}/{tot['base']}"}
        saida.append({
            "id": pid,
            "videos": len(reg["videos"]),
            "canais": canais,
            "multicanal": len(canais) > 1,
            "promovido": len(reg["videos"]) >= minimo,
            "grupo": grupo,
            "diferenca_taxa": dif,
            "tendencia": ("mais_nos_melhores" if dif >= LIMITE_TENDENCIA
                          else "mais_na_mediana" if dif <= -LIMITE_TENDENCIA else "sem_diferenca"),
            "aparece_em_todos": len(reg["videos"]) == total_videos,
            "melhores": f"{n_melhores}/{totais['melhores']}",
            "base": f"{n_base}/{totais['base']}",
            "por_canal": por_canal,
            "evidencias": sorted(reg["evid"], key=lambda x: (x["canal"], x["video_id"], x["inicio_s"])),
        })
    saida.sort(key=lambda r: (not r["promovido"], -r["videos"], r["id"]))
    return saida


def estrutura_comparada(entradas):
    """Números simples da estrutura de cada ficha (gancho, atos, voltas, reviravoltas), por grupo."""
    grupos = {}
    for e in entradas:
        f = e["ficha"]
        g = grupos.setdefault(e["grupo"], {"gancho": [], "atos": [], "rev": [], "ret": [], "ab": 0, "fe": 0})
        g["gancho"].append(f["gancho"]["fim_s"])
        g["atos"].append(len(f["atos"]))
        g["rev"].append(len(f["reviravoltas"]))
        g["ret"].append(len(f["retencao"]))
        for v in f["voltas"]:
            g["ab" if v.get("fechada_s") is None else "fe"] += 1
    saida = {}
    for nome, g in grupos.items():
        total = g["ab"] + g["fe"]
        saida[nome] = {
            "videos": len(g["gancho"]),
            "gancho_fim_s_mediana": statistics.median(g["gancho"]),
            "atos_mediana": statistics.median(g["atos"]),
            "reviravoltas_mediana": statistics.median(g["rev"]),
            "recursos_retencao_mediana": statistics.median(g["ret"]),
            "voltas_fechadas_percentual": round(100 * g["fe"] / total, 1) if total else 0.0,
        }
    return saida


def escrever_biblioteca(padroes, destino, descricoes=None):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    descricoes = descricoes or {}
    indice = []
    for r in padroes:
        r = dict(r, descricao=descricoes.get(r["id"], ""))
        (destino / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        indice.append({k: r[k] for k in ("id", "videos", "multicanal", "promovido", "grupo", "tendencia", "diferenca_taxa", "aparece_em_todos")})
    (destino / "indice.json").write_text(json.dumps({"padroes": indice}, ensure_ascii=False, indent=1))


def carregar_entradas(raiz):
    """Lê referencias/<canal>/amostra.json e <canal>/<id>/ficha.json."""
    raiz = Path(raiz)
    entradas = []
    for amostra in sorted(raiz.glob("*/amostra.json")):
        canal = amostra.parent.name
        for v in json.loads(amostra.read_text()):
            f = amostra.parent / v["id"] / "ficha.json"
            if f.exists():
                ficha = json.loads(f.read_text())
                if ficha.get("video_id") != v["id"]:
                    raise ValueError(f"ficha de {canal}/{v['id']} traz video_id {ficha.get('video_id')!r}")
                entradas.append({"canal": canal, "grupo": v["grupo"], "ficha": ficha})
    return entradas


def main(argv=None):
    from scripts.estudo_ficha import TAXONOMIA

    raiz = Path(__file__).resolve().parent.parent / "referencias"
    entradas = carregar_entradas(raiz)
    padroes = agregar(entradas)
    escrever_biblioteca(padroes, raiz / "padroes", TAXONOMIA)
    por_canal = {}
    for e in entradas:
        por_canal.setdefault(e["canal"], []).append(e)
    comparada = {"geral": estrutura_comparada(entradas),
                 "por_canal": {c: estrutura_comparada(es) for c, es in sorted(por_canal.items())}}
    (raiz / "padroes" / "estrutura-comparada.json").write_text(json.dumps(comparada, ensure_ascii=False, indent=1))
    print(f"{len(entradas)} fichas, {sum(p['promovido'] for p in padroes)} padrões promovidos de {len(padroes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
