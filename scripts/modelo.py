"""O modelo do canal: as regras aprendidas com o feedback da revisão humana, versionadas (T15).

Cada regra guarda de onde veio (data, citação, vídeo, minuto) e como é verificada:
  auto      uma função de um módulo de MODULOS_DE_REGRAS confere sozinha;
  planejada vai virar automática na tarefa indicada;
  manual    entra no checklist da revisão humana.
Todo feedback entra aberto em feedback.jsonl e só fecha como regra nova, ajuste de
regra ou caso único justificado. Feedback aberto reprova a validação: nada se perde.
Os arquivos são do canal (dados); este módulo não conhece nenhum caso (R14).
"""
import importlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ_CANAIS = Path(__file__).resolve().parent.parent / "canais"
VERIFICACOES = {"auto", "manual", "planejada"}
DESTINOS = {"regra_nova", "ajuste", "caso_unico"}
_MINUTO = re.compile(r"^(\d+):([0-5]\d)(\.\d+)?$")

# Verificações automáticas: cada módulo listado exporta REGRAS = {nome: função(contexto) -> erros}.
# contexto é um dict com o que a verificação precisa ("fontes", "plano", ...).

MODULOS_DE_REGRAS = ["scripts.fontes", "scripts.plano", "scripts.entrega", "scripts.vozes", "scripts.narracao", "scripts.som"]


def funcoes_registradas():
    funcoes = {}
    for nome in MODULOS_DE_REGRAS:
        for chave, f in importlib.import_module(nome).REGRAS.items():
            if chave in funcoes:
                raise ValueError(f"função de regra {chave!r} definida em dois módulos")
            funcoes[chave] = f
    return funcoes


def _agora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _arquivo(pasta):
    return Path(pasta) / "regras.json"


def _acrescentar(pasta, nome, evento):
    with open(Path(pasta) / nome, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def _ler_jsonl(pasta, nome):
    caminho = Path(pasta) / nome
    if not caminho.exists():
        return []
    return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]


def criar(pasta):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    if _arquivo(pasta).exists():
        raise FileExistsError(f"já existe: {_arquivo(pasta)}")
    _gravar(pasta, {"versao": 1, "regras": []})
    for nome in ("historico.jsonl", "feedback.jsonl"):
        (pasta / nome).touch()


def carregar(pasta):
    return json.loads(_arquivo(pasta).read_text(encoding="utf-8"))


def _gravar(pasta, m):
    _arquivo(pasta).write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _checar_regra(r):
    for campo in ("id", "titulo", "texto", "verificacao"):
        if not str(r.get(campo, "")).strip():
            raise ValueError(f"regra sem {campo}: {r.get('id')!r}")
    origem = r.get("origem") or {}
    if not (str(origem.get("data", "")).strip() and str(origem.get("citacao", "")).strip()):
        raise ValueError(f"regra {r['id']} sem origem (data e citação do feedback)")
    if r["verificacao"] not in VERIFICACOES:
        raise ValueError(f"regra {r['id']}: verificação {r['verificacao']!r} (válidas: {sorted(VERIFICACOES)})")
    if r["verificacao"] == "auto" and not (r.get("funcao") or r.get("funcoes")):
        raise ValueError(f"regra {r['id']} automática sem funcao (ou funcoes)")
    if r["verificacao"] == "planejada" and not r.get("tarefa"):
        raise ValueError(f"regra {r['id']} planejada sem tarefa")


def adicionar_regra(pasta, regra, feedback=None):
    _checar_regra(regra)
    m = carregar(pasta)
    if any(r["id"] == regra["id"] for r in m["regras"]):
        raise ValueError(f"regra {regra['id']} já existe; use ajustar_regra")
    if feedback:
        regra = {**regra, "origem": {**regra["origem"], "feedback": feedback}}
    m["regras"].append(regra)
    m["versao"] += 1
    _gravar(pasta, m)
    _acrescentar(pasta, "historico.jsonl",
                 {"quando": _agora(), "versao": m["versao"], "acao": "nova", "regra": regra["id"], "feedback": feedback})
    return m["versao"]


def ajustar_regra(pasta, id_, mudancas, feedback):
    m = carregar(pasta)
    regra = next((r for r in m["regras"] if r["id"] == id_), None)
    if regra is None:
        raise ValueError(f"regra {id_} não existe")
    if "id" in mudancas:
        raise ValueError("o id de uma regra não muda")
    antes = {k: regra.get(k) for k in mudancas}
    novo = {**regra, **mudancas}
    _checar_regra(novo)
    regra.update(mudancas)
    m["versao"] += 1
    _gravar(pasta, m)
    _acrescentar(pasta, "historico.jsonl", {"quando": _agora(), "versao": m["versao"], "acao": "ajuste",
                                            "regra": id_, "feedback": feedback, "antes": antes})
    return m["versao"]


def feedbacks(pasta):
    """Estado atual de cada feedback, reconstruído do log (só acrescenta)."""
    estado = {}
    for ev in _ler_jsonl(pasta, "feedback.jsonl"):
        if ev["evento"] == "novo":
            estado[ev["id"]] = {**ev, "estado": "aberto"}
        elif ev["evento"] == "fechado":
            if ev["id"] not in estado:
                estado[ev["id"]] = {"id": ev["id"], "texto": "", "orfao": True}
            estado[ev["id"]].update(estado="fechado", destino=ev["destino"], regra=ev.get("regra"),
                                    justificativa=ev.get("justificativa"))
    return estado


def registrar_feedback(pasta, texto, video=None, minuto=None, quadro=None, data=None, retroativo=False):
    """Registra o feedback como chegou. Feedback antigo entra com retroativo=True e só a data (sem horário inventado)."""
    if not (texto or "").strip():
        raise ValueError("feedback vazio")
    if minuto is not None and not _MINUTO.match(minuto):
        raise ValueError(f"minuto inválido: {minuto!r} (use m:ss)")
    fid = f"F{len(feedbacks(pasta)) + 1:03d}"
    if retroativo and not data:
        raise ValueError("feedback retroativo exige a data em que foi dado")
    _acrescentar(pasta, "feedback.jsonl", {"evento": "novo", "id": fid, "quando": data if retroativo else _agora(),
                                           "retroativo": bool(retroativo), "texto": texto.strip(), "video": video,
                                           "minuto": minuto, "quadro": quadro})
    return fid


def fechar_feedback(pasta, fid, destino, regra=None, justificativa=None):
    if destino not in DESTINOS:
        raise ValueError(f"destino {destino!r} (válidos: {sorted(DESTINOS)})")
    atual = feedbacks(pasta).get(fid)
    if atual is None:
        raise ValueError(f"feedback {fid} não existe")
    if atual["estado"] == "fechado":
        raise ValueError(f"feedback {fid} já está fechado ({atual['destino']})")
    if destino in ("regra_nova", "ajuste"):
        acao = "nova" if destino == "regra_nova" else "ajuste"
        feito = any(h.get("regra") == regra and h.get("acao") == acao and h.get("feedback") == fid
                    for h in _ler_jsonl(pasta, "historico.jsonl"))
        if not feito:
            raise ValueError(f"nenhuma {'regra nova' if acao == 'nova' else 'mudança'} {regra} registrada com "
                             f"o feedback {fid}: use adicionar_regra/ajustar_regra(..., feedback='{fid}') antes")
    elif not (justificativa or "").strip():
        raise ValueError("caso único exige justificativa")
    _acrescentar(pasta, "feedback.jsonl", {"evento": "fechado", "id": fid, "quando": _agora(), "destino": destino,
                                           "regra": regra, "justificativa": justificativa})


def validar(pasta, funcoes=None):
    """Lista de problemas do modelo; vazia quando está tudo certo."""
    funcoes = funcoes_registradas() if funcoes is None else funcoes
    erros = []
    ids = set()
    try:
        regras = carregar(pasta)["regras"]
    except (OSError, ValueError, KeyError) as e:
        return [f"modelo ilegível em {pasta}: {e}"]
    for r in regras:
        try:
            _checar_regra(r)
        except ValueError as e:
            erros.append(str(e))
            continue
        if r["id"] in ids:
            erros.append(f"regra {r['id']} repetida")
        ids.add(r["id"])
        if r["verificacao"] == "auto":
            for nome in [r["funcao"]] if r.get("funcao") else r["funcoes"]:
                if nome not in funcoes:
                    erros.append(f"regra {r['id']}: função automática {nome!r} não registrada")
    for fid, f in feedbacks(pasta).items():
        if f.get("orfao"):
            erros.append(f"feedback {fid} fechado sem ter sido registrado")
        elif f["estado"] == "aberto":
            erros.append(f"feedback {fid} aberto: {f['texto'][:60]!r}")
    return erros


def checklist(pasta):
    """Regras que a revisão humana confere: as manuais e as planejadas que ainda não viraram automáticas."""
    return [r for r in carregar(pasta)["regras"] if r["verificacao"] in ("manual", "planejada")]


def versao(pasta):
    return carregar(pasta)["versao"]


def carimbar_video(pasta_video, pasta_modelo):
    """Grava no vídeo com qual versão do modelo ele foi feito."""
    carimbo = {"modelo": str(pasta_modelo), "versao": versao(pasta_modelo), "quando": _agora()}
    (Path(pasta_video) / "modelo.json").write_text(json.dumps(carimbo, ensure_ascii=False, indent=1) + "\n",
                                                   encoding="utf-8")
    return carimbo


def _segundos(minuto):
    m = _MINUTO.match(minuto or "")
    if not m:
        raise ValueError(f"minuto inválido: {minuto!r} (use m:ss)")
    return int(m.group(1)) * 60 + int(m.group(2)) + float(m.group(3) or 0)


def extrair_quadro(video, minuto, saida):
    """Guarda o quadro do minuto citado no feedback, para a regra ter evidência visual."""
    t = _segundos(minuto)
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                    "-q:v", "3", str(saida)], check=True)
    return saida


def main(argv=None):
    """Uso:
      python -m scripts.modelo feedback <pasta> "texto" [--video V] [--minuto m:ss]
      python -m scripts.modelo fechar <pasta> F001 regra_nova|ajuste|caso_unico [--regra M01] [--justificativa J]
      python -m scripts.modelo validar <pasta>
    """
    import argparse

    p = argparse.ArgumentParser(prog="modelo")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("feedback")
    f.add_argument("pasta")
    f.add_argument("texto")
    f.add_argument("--video")
    f.add_argument("--minuto")
    c = sub.add_parser("fechar")
    c.add_argument("pasta")
    c.add_argument("id")
    c.add_argument("destino", choices=sorted(DESTINOS))
    c.add_argument("--regra")
    c.add_argument("--justificativa")
    v = sub.add_parser("validar")
    v.add_argument("pasta")
    a = p.parse_args(argv)
    if a.cmd == "feedback" and bool(a.video) != bool(a.minuto):
        p.error("--video e --minuto vão juntos (o quadro do minuto vira evidência)")

    if a.cmd == "feedback":
        quadro = None
        if a.video and a.minuto:
            fid_prox = f"F{len(feedbacks(a.pasta)) + 1:03d}"
            quadro = str(extrair_quadro(a.video, a.minuto, Path(a.pasta) / "quadros" / f"{fid_prox}.jpg"))
        fid = registrar_feedback(a.pasta, a.texto, video=a.video, minuto=a.minuto, quadro=quadro)
        print(f"{fid} aberto. Feche como regra nova, ajuste ou caso único.")
        return 0
    if a.cmd == "fechar":
        fechar_feedback(a.pasta, a.id, a.destino, regra=a.regra, justificativa=a.justificativa)
        print(f"{a.id} fechado ({a.destino}).")
        return 0
    erros = validar(a.pasta)
    for e in erros:
        print(f"[FALHA] {e}")
    if not erros:
        print(f"modelo v{carregar(a.pasta)['versao']} ok")
    return 1 if erros else 0


if __name__ == "__main__":
    if __package__ in (None, ""):  # rodado como `python scripts/modelo.py`
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(main())
