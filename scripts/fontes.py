"""Catálogo de fontes de um episódio: cada foto, clipe, documento, voz ou imagem de IA (T16).

O catálogo é dado do episódio (`videos/<slug>/fontes.json`); este módulo só confere a forma
e as regras do modelo do canal que dependem da fonte:
  M03  real é material do caso (do_caso declarado; stock e IA nunca são do caso)
  M13  pessoa em foto, clipe, documento ou voz só com identidade confirmada
  M14  clipe classificado; reencenação sem nome de pessoa (nem nas etiquetas)
  M15  clipe e voz declaram o trecho útil (o plano não passa dele; conferido na T17)
  M16  pessoa de fora do caso, viva, com os olhos borrados
As verificações seguem o contrato do modelo: função(contexto) -> lista de erros,
com contexto["fontes"] = lista do catálogo. Elas ficam em REGRAS, que o modelo coleta.
"""
import json
from pathlib import Path

TIPOS = {"foto", "clipe", "documento", "voz", "ia", "stock", "mapa"}
TIPOS_REAIS = {"foto", "clipe", "documento"}
COM_PESSOA = {"foto", "clipe", "documento", "voz"}
COM_TRECHO = {"clipe", "voz"}
COM_ANO = {"foto", "clipe", "documento", "voz"}
NATUREZAS = {"arquivo_tv", "entrevista", "reencenacao", "filme_epoca", "local", "montagem_doc"}
PAPEIS = {"acusado", "vitima", "familia", "testemunha", "policia", "especialista", "jornalista", "publico"}
OLHOS = {"borrar", "manter"}
LICENCA_PENDENTE = ("verificar", "confirmar", "ver página", "?", "a definir", "pendente")


def carregar(pasta_video):
    return json.loads((Path(pasta_video) / "fontes.json").read_text(encoding="utf-8"))


def _lista(f, campo):
    v = f.get(campo)
    return v if isinstance(v, list) else []


def _pessoas(f):
    return [p for p in _lista(f, "pessoas") if isinstance(p, dict)]


def conta_como_real(f):
    """Entra na conta de imagem real (M02): material do caso, sem reencenação."""
    if f.get("tipo") not in TIPOS_REAIS or f.get("do_caso") is not True:
        return False
    return not (f["tipo"] == "clipe" and f.get("natureza") == "reencenacao")


def _trecho_ok(t):
    return (isinstance(t, list) and len(t) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                        for x in t) and t[1] > t[0] >= 0)


def _ano_ok(a):
    if isinstance(a, int) and not isinstance(a, bool):
        return 1800 <= a <= 2100
    return isinstance(a, str) and bool(a.strip())


def _forma(lista):
    erros, vistos = [], set()
    for f in lista:
        if not isinstance(f, dict):
            erros.append(f"fonte que não é objeto: {f!r}")
            continue
        fid = f.get("id") or "?"
        if fid in vistos:
            erros.append(f"{fid}: id repetido")
        vistos.add(fid)
        tipo = f.get("tipo")
        if tipo not in TIPOS:
            erros.append(f"{fid}: tipo {tipo!r} (válidos: {sorted(TIPOS)})")
        if not f.get("arquivo"):
            erros.append(f"{fid}: sem arquivo")
        etiquetas = f.get("etiquetas")
        if not (isinstance(etiquetas, list) and etiquetas and all(isinstance(e, str) and e.strip() for e in etiquetas)):
            erros.append(f"{fid}: etiquetas devem ser uma lista de textos (o que a fonte mostra)")
        origem = f.get("origem")
        if not isinstance(origem, dict):
            erros.append(f"{fid}: origem deve ter fonte e licenca")
            origem = {}
        for campo in ("fonte", "licenca"):
            if not str(origem.get(campo, "")).strip():
                erros.append(f"{fid}: origem sem {campo}")
        lic = str(origem.get("licenca", "")).lower()
        if any(m in lic for m in LICENCA_PENDENTE):
            erros.append(f"{fid}: licença pendente ({origem.get('licenca')!r}): confirme antes de usar")
        if "pessoas" in f and not isinstance(f["pessoas"], list):
            erros.append(f"{fid}: pessoas deve ser uma lista")
        for p in _lista(f, "pessoas"):
            if not isinstance(p, dict):
                erros.append(f"{fid}: pessoa deve ter nome, papel e olhos: {p!r}")
                continue
            if p.get("papel") not in PAPEIS:
                erros.append(f"{fid}: papel {p.get('papel')!r} de {p.get('nome')!r} (válidos: {sorted(PAPEIS)})")
            if p.get("olhos") not in OLHOS:
                erros.append(f"{fid}: olhos {p.get('olhos')!r} de {p.get('nome')!r} (borrar ou manter)")
        if "identidade" in f and f["identidade"] is not None and not isinstance(f["identidade"], dict):
            erros.append(f"{fid}: identidade deve ter verificada e como")
        if tipo in COM_TRECHO and not _trecho_ok(f.get("trecho")):
            erros.append(f"{fid}: trecho útil inválido {f.get('trecho')!r} (use [início, fim] em segundos)")
        if tipo in COM_ANO and not _ano_ok(f.get("ano")):
            erros.append(f"{fid}: sem ano (quando foi feito ou registrado)")
        if tipo == "ia":
            if f.get("rotulo") is not True:
                erros.append(f"{fid}: imagem de IA sem rótulo de reconstituição")
            if f.get("sem_rosto_real") is not True:
                erros.append(f"{fid}: imagem de IA precisa declarar sem_rosto_real (nenhum rosto de pessoa real)")
            if not f.get("prompt"):
                erros.append(f"{fid}: imagem de IA sem prompt registrado")
            if f.get("pessoas"):
                erros.append(f"{fid}: imagem de IA não pode retratar pessoa real")
    return erros


def _lista_do(contexto):
    return [f for f in (contexto.get("fontes") or []) if isinstance(f, dict)]


def checar_identidade(contexto):
    erros = []
    for f in _lista_do(contexto):
        if f.get("tipo") in COM_PESSOA and _pessoas(f):
            ident = f.get("identidade") if isinstance(f.get("identidade"), dict) else {}
            if ident.get("verificada") is not True or not str(ident.get("como", "")).strip():
                erros.append(f"M13 {f.get('id')}: pessoa sem identidade confirmada (diga como foi confirmada)")
    return erros


def checar_natureza_clipe(contexto):
    lista = _lista_do(contexto)
    nomes = {str(p.get("nome", "")).lower() for f in lista for p in _pessoas(f) if p.get("nome")}
    erros = []
    for f in lista:
        if f.get("tipo") != "clipe":
            continue
        if f.get("natureza") not in NATUREZAS:
            erros.append(f"M14 {f.get('id')}: clipe sem natureza válida {f.get('natureza')!r} ({sorted(NATUREZAS)})")
        elif f["natureza"] == "reencenacao":
            if _pessoas(f):
                erros.append(f"M14 {f.get('id')}: reencenação não pode levar nome de pessoa")
            citados = [e for e in _lista(f, "etiquetas") if isinstance(e, str) and e.lower() in nomes]
            if citados:
                erros.append(f"M14 {f.get('id')}: reencenação com nome de pessoa nas etiquetas: {citados}")
    return erros


def checar_olhos(contexto):
    """M16 (revista em 10/10/2026): quem está envolvido no caso aparece com o rosto; só pessoa de fora
    do caso (papel 'publico', ex.: advogado ao fundo, plateia) e viva precisa de olhos borrados."""
    return [f"M16 {f.get('id')}: {p.get('nome')!r} não tem relação com o caso e está viva: precisa de olhos borrados"
            for f in _lista_do(contexto) for p in _pessoas(f)
            if p.get("papel") == "publico" and p.get("olhos") != "borrar" and p.get("falecido") is not True]


def checar_do_caso(contexto):
    erros = []
    for f in _lista_do(contexto):
        if f.get("tipo") in TIPOS_REAIS and not isinstance(f.get("do_caso"), bool):
            erros.append(f"M03 {f.get('id')}: declare do_caso (true se é material do próprio caso)")
        if f.get("tipo") in ("stock", "ia") and f.get("do_caso"):
            erros.append(f"M03 {f.get('id')}: {f['tipo']} nunca é material do caso")
    return erros


# nome da função no modelo -> verificação; o modelo coleta este dicionário
REGRAS = {
    "fontes_identidade": checar_identidade,
    "fontes_natureza_clipe": checar_natureza_clipe,
    "fontes_olhos": checar_olhos,
    "fontes_do_caso": checar_do_caso,
}


def validar(catalogo):
    erros = _forma(catalogo.get("fontes") or [])
    for f in REGRAS.values():
        erros += f(catalogo)
    return erros
