"""Registro de aprovações e feedback da revisão humana, por vídeo (R12, R15).

Os arquivos são append-only: uma decisão nova não apaga a anterior.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

AUTOR_HUMANO = "humano"
PORTOES = [
    "padroes",
    "pauta",
    "fichas",
    "roteiro",
    "plano",
    "checagem",
    "narracao",
    "assets",
    "montagem",
    "verificacao",
    "publicacao",
]


def _agora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _portao_valido(portao):
    if portao not in PORTOES:
        raise ValueError(f"portão desconhecido: {portao!r} (válidos: {', '.join(PORTOES)})")


def _acrescentar(pasta, arquivo, evento):
    with open(Path(pasta) / arquivo, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def _ler(pasta, arquivo):
    caminho = Path(pasta) / arquivo
    if not caminho.exists():
        return []
    return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]


def registrar_aprovacao(pasta, portao, aprovado, nota):
    """Grava a decisão humana. Só um humano aprova: o juiz de modelo não grava aqui (R12)."""
    _portao_valido(portao)
    if not isinstance(aprovado, bool):
        raise TypeError(f"aprovado deve ser True ou False, não {aprovado!r}")
    if not (nota or "").strip():
        raise ValueError("a aprovação exige uma nota (o porquê, em uma frase)")
    _acrescentar(
        pasta,
        "aprovacoes.jsonl",
        {"quando": _agora(), "portao": portao, "aprovado": aprovado, "nota": nota.strip(), "por": AUTOR_HUMANO},
    )


def registrar_feedback(pasta, portao, sentiu, motivo):
    _portao_valido(portao)
    if not (sentiu or "").strip() or not (motivo or "").strip():
        raise ValueError("feedback exige o que o revisor sentiu e o motivo")
    _acrescentar(
        pasta,
        "feedback.jsonl",
        {"quando": _agora(), "portao": portao, "sentiu": sentiu.strip(), "motivo": motivo.strip()},
    )


def decisao_do_portao(pasta, portao, veredito_juiz=None):
    """Devolve a decisão que vale para o portão.

    A última decisão humana vence o juiz de modelo. Sem decisão humana o portão
    fica pendente: o juiz sozinho nunca aprova.
    """
    _portao_valido(portao)
    humanas = [e for e in _ler(pasta, "aprovacoes.jsonl") if e["portao"] == portao and e.get("por") == AUTOR_HUMANO]
    if not humanas:
        return {"aprovado": False, "origem": "pendente", "juiz_discordou": False}
    aprovado = humanas[-1]["aprovado"]
    discordou = veredito_juiz is not None and bool(veredito_juiz) != aprovado
    return {"aprovado": aprovado, "origem": AUTOR_HUMANO, "juiz_discordou": discordou}
