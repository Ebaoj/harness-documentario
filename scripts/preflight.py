"""Confere o ambiente antes de qualquer etapa que gaste tempo ou dinheiro."""
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):  # rodado como `python scripts/preflight.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BINARIOS = ["ffmpeg", "ffprobe", "whisper-cli"]
RAIZ_VIDEOS = Path(__file__).resolve().parent.parent / "videos"
YTDLP_MINIMO = "2026.08.01"


def _como_tupla(versao):
    try:
        return tuple(int(x) for x in versao.split(".")[:3])
    except (ValueError, AttributeError):
        return None


def _versao_ytdlp():
    try:
        from yt_dlp.version import __version__
    except ImportError:
        return None
    return __version__


def _versao_python():
    return tuple(sys.version_info[:3])


def _na_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def checar():
    resultados = []

    v = _versao_python()
    resultados.append({"nome": "python==3.12", "ok": v[:2] == (3, 12), "detalhe": ".".join(map(str, v))})
    resultados.append(
        {
            "nome": "venv",
            "ok": _na_venv(),
            "detalhe": sys.prefix if _na_venv() else "fora da .venv (use .venv/bin/python)",
        }
    )

    for nome in BINARIOS:
        caminho = shutil.which(nome)
        resultados.append({"nome": nome, "ok": caminho is not None, "detalhe": caminho or "não encontrado"})

    yt = _versao_ytdlp()
    ok = _como_tupla(yt) is not None and _como_tupla(yt) >= _como_tupla(YTDLP_MINIMO)
    resultados.append(
        {
            "nome": f"yt-dlp>={YTDLP_MINIMO}",
            "ok": ok,
            "detalhe": yt or "não instalado na venv (pip install -r requirements.txt)",
        }
    )
    from scripts import vozes

    resultados.append({"nome": f"modelo whisper {vozes.MODELO.name}", "ok": vozes.MODELO.is_file(),
                       "detalhe": str(vozes.MODELO) if vozes.MODELO.is_file() else f"faltando: {vozes.MODELO} (ou defina WHISPER_MODELO)"})
    caminho = _chromium()
    resultados.append({"nome": "chromium (playwright)", "ok": caminho is not None,
                       "detalhe": caminho or "não instalado: .venv/bin/python -m playwright install chromium"})
    from scripts import narracao

    gastos = narracao.checar_custos_dos_episodios(RAIZ_VIDEOS)
    resultados.append({"nome": "custos aprovados (M24)", "ok": not gastos, "detalhe": "; ".join(gastos) or "ok"})
    resultados.extend(_checar_modelos())
    return resultados


def _chromium():
    """Caminho do navegador que o render usa; None se a biblioteca ou o navegador faltam."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            caminho = pw.chromium.executable_path
    except Exception:
        return None
    return caminho if Path(caminho).exists() else None


def _checar_modelos():
    """Cada canal tem um modelo de regras válido e sem feedback aberto (T15)."""
    from scripts import modelo

    saida = []
    for pasta in sorted(modelo.RAIZ_CANAIS.glob("*/modelo")):
        erros = modelo.validar(pasta)
        detalhe = "; ".join(erros) if erros else f"v{modelo.versao(pasta)}, {len(modelo.checklist(pasta))} regras no checklist humano"
        saida.append({"nome": f"modelo {pasta.parent.name}", "ok": not erros, "detalhe": detalhe})
    return saida


def main():
    falhas = 0
    for r in checar():
        marca = "ok " if r["ok"] else "FALHA"
        print(f"[{marca}] {r['nome']}: {r['detalhe']}")
        falhas += 0 if r["ok"] else 1
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
