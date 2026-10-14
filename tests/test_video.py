import json

import pytest

from scripts import video


def test_criar_video_cria_pastas_e_registros(tmp_path):
    pasta = video.criar_video(tmp_path, "plano-real")
    assert pasta == tmp_path / "plano-real"
    for nome in video.PASTAS:
        assert (pasta / nome).is_dir(), nome
    for arq in ("aprovacoes.jsonl", "feedback.jsonl", "00-custos.jsonl"):
        assert (pasta / arq).is_file(), arq
        assert (pasta / arq).read_text() == ""


@pytest.mark.parametrize("slug", ["Plano-Real", "plano real", "../fora", "", "-x", "x-", "a--b", "plano_real", "plano-real\n", "plano-real ", None])
def test_slug_invalido_e_rejeitado(tmp_path, slug):
    with pytest.raises(ValueError):
        video.criar_video(tmp_path, slug)
    assert list(tmp_path.iterdir()) == []


def test_criar_video_que_ja_existe_falha_sem_apagar(tmp_path):
    pasta = video.criar_video(tmp_path, "plano-real")
    (pasta / "02-roteiro" / "roteiro.md").write_text("conteudo")
    with pytest.raises(FileExistsError):
        video.criar_video(tmp_path, "plano-real")
    assert (pasta / "02-roteiro" / "roteiro.md").read_text() == "conteudo"


def test_esqueleto_de_pastas_e_o_combinado():
    assert video.PASTAS == [
        "00-pauta", "01-fichas", "02-roteiro", "03-checagem", "04-narracao",
        "05-assets", "06-edl", "07-saida", "versoes",
    ]


TEMAS_PROIBIDOS_NO_CODIGO = ["plano real", "plano-real", "inflação", "inflacao", "cruzado", "urv", "hiperinflação"]


def test_scripts_nao_citam_tema_de_video():
    # R14: nada em scripts/ conhece o tema de um vídeo; o tema mora em videos/<slug>/
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent / "scripts"
    achados = []
    for arq in sorted(raiz.glob("*.py")):
        texto = arq.read_text(encoding="utf-8").lower()
        for termo in TEMAS_PROIBIDOS_NO_CODIGO:
            if _cita(termo, texto):
                achados.append(f"{arq.name}: {termo}")
    assert achados == []


def _cita(termo, texto):
    """Palavra inteira: a sigla 'urv' não pode acusar a palavra 'curva'."""
    import re

    return re.search(r"(?<!\w)" + re.escape(termo) + r"(?!\w)", texto) is not None


def test_varredura_de_tema_pega_palavra_inteira_e_ignora_pedaco():
    assert _cita("urv", "a urv de 1994")
    assert not _cita("urv", "a curva de volume")
