"""Marcas de ambiente dos testes.

@pytest.mark.transcricao: o teste precisa de transcrição local de verdade, ou seja, whisper-cli no PATH,
o modelo em WHISPER_MODELO (padrão: modelos/ggml-small.bin) e o comando `say` do macOS para sintetizar a fala
de teste. Sem isso o teste é pulado com o motivo, em vez de falhar.
"""
import shutil

import pytest


def _faltando_para_transcrever():
    from scripts import vozes

    faltam = [b for b in ("whisper-cli", "say") if shutil.which(b) is None]
    if not vozes.MODELO.is_file():
        faltam.append(f"modelo whisper em {vozes.MODELO} (ou defina WHISPER_MODELO)")
    return faltam


def pytest_configure(config):
    config.addinivalue_line("markers", "transcricao: precisa de whisper-cli, do modelo whisper e do `say` do macOS")


def pytest_collection_modifyitems(config, items):
    faltam = _faltando_para_transcrever()
    if not faltam:
        return
    pula = pytest.mark.skip(reason="sem transcrição local: falta " + ", ".join(faltam))
    for item in items:
        if "transcricao" in item.keywords:
            item.add_marker(pula)
