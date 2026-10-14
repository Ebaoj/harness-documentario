"""Esqueleto de pastas de um vídeo. Igual para qualquer tema (R14)."""
import re
from pathlib import Path

PASTAS = [
    "00-pauta",
    "01-fichas",
    "02-roteiro",
    "03-checagem",
    "04-narracao",
    "05-assets",
    "06-edl",
    "07-saida",
    "versoes",
]
REGISTROS = ["aprovacoes.jsonl", "feedback.jsonl", "00-custos.jsonl"]
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def criar_video(raiz, slug):
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ValueError(f"slug inválido: {slug!r} (minúsculas, números e hífen simples)")
    pasta = Path(raiz) / slug
    if pasta.exists():
        raise FileExistsError(f"já existe: {pasta}")
    pasta.mkdir(parents=True)
    for nome in PASTAS:
        (pasta / nome).mkdir()
    for nome in REGISTROS:
        (pasta / nome).write_text("")
    return pasta
