"""Escolhe os vídeos de um canal para estudo: os de maior desempenho e os da mediana ou abaixo."""
import json
import re
import statistics
import sys
from pathlib import Path

MIN_DURACAO_S = 360  # abaixo disso é short ou clipe, não documentário
MIN_VIEWS = 1000  # vídeo recém-publicado não diz nada sobre desempenho

_MULT = {"k": 1_000, "mil": 1_000, "m": 1_000_000, "mi": 1_000_000, "b": 1_000_000_000, "bi": 1_000_000_000}
_NUM = re.compile(r"([\d.,]+)\s*(mil|mi|bi|k|m|b)?\b", re.IGNORECASE)


def parse_views(valor):
    """'1.5K' -> 1500, '1,2 mi' -> 1200000, '1,234 views' -> 1234, 4200 -> 4200; ilegível -> None."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    m = _NUM.search(str(valor).strip())
    if not m or not re.search(r"\d", m.group(1)):
        return None
    numero, sufixo = m.group(1), (m.group(2) or "").lower()
    if sufixo:
        n = numero.replace(",", ".")
        try:
            return int(round(float(n) * _MULT[sufixo]))
        except ValueError:
            return None
    # sem sufixo: ponto ou vírgula são separadores de milhar quando seguidos de 3 dígitos
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", numero):
        return int(re.sub(r"[.,]", "", numero))
    try:
        return int(float(numero.replace(",", ".")))
    except ValueError:
        return None


def normalizar_entrada(e):
    return {
        "id": e.get("id"),
        "titulo": e.get("titulo", e.get("title", "")),
        "duracao_s": e.get("duracao_s", e.get("duration")),
        "views": parse_views(e.get("views", e.get("view_count"))),
    }


def _short(v):
    t = (v.get("titulo") or "").lower()
    return "#short" in t or (v.get("duracao_s") is not None and v["duracao_s"] < MIN_DURACAO_S)


def escolher(videos, n_melhores=2, n_base=2, min_views=MIN_VIEWS):
    """Devolve até n_melhores (maiores views) e n_base (da mediana para baixo), cada um com `grupo`."""
    vs = [normalizar_entrada(v) for v in videos]
    vs = [v for v in vs if v["id"] and v["views"] is not None and v["views"] >= min_views and not _short(v)]
    if not vs:
        return []
    vs.sort(key=lambda v: v["views"], reverse=True)
    mediana = statistics.median(v["views"] for v in vs)
    melhores = vs[:n_melhores]
    usados = {v["id"] for v in melhores}
    candidatos = [v for v in vs if v["views"] <= mediana and v["id"] not in usados]  # do mais perto da mediana ao menor
    if not candidatos:  # canal minúsculo: usa o que sobrou, de baixo para cima
        candidatos = [v for v in vs if v["id"] not in usados]
    base = []
    if candidatos and n_base > 0:
        if len(candidatos) <= n_base:
            base = candidatos
        else:  # o mais perto da mediana e o mais baixo, e os intermediários espaçados
            passo = (len(candidatos) - 1) / (n_base - 1) if n_base > 1 else 0
            base = [candidatos[round(i * passo)] for i in range(n_base)]
    return [dict(v, grupo="melhores") for v in melhores] + [dict(v, grupo="base") for v in base]


def main(argv=None):
    """estudo_amostra.py <lista.json> [saida.json]"""
    argv = argv or sys.argv[1:]
    lista = json.loads(Path(argv[0]).read_text())
    r = escolher(lista)
    texto = json.dumps(r, ensure_ascii=False, indent=1)
    if len(argv) > 1:
        Path(argv[1]).write_text(texto)
    else:
        print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
