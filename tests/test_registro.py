import json

import pytest

from scripts import registro, video


@pytest.fixture
def pasta(tmp_path):
    return video.criar_video(tmp_path, "fixture-a")


def _linhas(pasta, arquivo):
    return [json.loads(l) for l in (pasta / arquivo).read_text().splitlines()]


def test_aprovacao_registra_portao_data_e_nota(pasta):
    registro.registrar_aprovacao(pasta, "roteiro", True, "ficou claro o porque importa")
    (linha,) = _linhas(pasta, "aprovacoes.jsonl")
    assert linha["portao"] == "roteiro"
    assert linha["aprovado"] is True
    assert linha["nota"] == "ficou claro o porque importa"
    assert linha["por"] == registro.AUTOR_HUMANO
    assert linha["quando"].endswith("Z")


def test_aprovacao_exige_nota(pasta):
    with pytest.raises(ValueError):
        registro.registrar_aprovacao(pasta, "roteiro", True, "   ")
    assert _linhas(pasta, "aprovacoes.jsonl") == []


def test_portao_desconhecido_e_rejeitado(pasta):
    with pytest.raises(ValueError):
        registro.registrar_aprovacao(pasta, "inventado", True, "x")
    with pytest.raises(ValueError):
        registro.registrar_feedback(pasta, "inventado", "bom", "x")


def test_registro_so_acrescenta(pasta):
    registro.registrar_aprovacao(pasta, "roteiro", False, "falta tensao")
    registro.registrar_aprovacao(pasta, "roteiro", True, "agora sim")
    linhas = _linhas(pasta, "aprovacoes.jsonl")
    assert [l["aprovado"] for l in linhas] == [False, True]


def test_feedback_registra_o_que_o_revisor_sentiu(pasta):
    registro.registrar_feedback(pasta, "montagem", "lento", "corte demora no meio")
    (linha,) = _linhas(pasta, "feedback.jsonl")
    assert linha["portao"] == "montagem"
    assert linha["sentiu"] == "lento"
    assert linha["motivo"] == "corte demora no meio"


def test_humano_prevalece_sobre_juiz(pasta):
    # R12: o juiz reprova, o humano aprova ouvindo: vale o dele
    registro.registrar_aprovacao(pasta, "roteiro", True, "gostei ouvindo")
    d = registro.decisao_do_portao(pasta, "roteiro", veredito_juiz=False)
    assert d == {"aprovado": True, "origem": registro.AUTOR_HUMANO, "juiz_discordou": True}


def test_juiz_sozinho_nunca_aprova(pasta):
    d = registro.decisao_do_portao(pasta, "roteiro", veredito_juiz=True)
    assert d == {"aprovado": False, "origem": "pendente", "juiz_discordou": False}


def test_ultima_decisao_humana_vale(pasta):
    registro.registrar_aprovacao(pasta, "roteiro", True, "ok")
    registro.registrar_aprovacao(pasta, "roteiro", False, "reli, falta fonte")
    d = registro.decisao_do_portao(pasta, "roteiro", veredito_juiz=True)
    assert d["aprovado"] is False
    assert d["origem"] == registro.AUTOR_HUMANO
    assert d["juiz_discordou"] is True


def test_decisao_de_um_portao_nao_vaza_para_outro(pasta):
    registro.registrar_aprovacao(pasta, "roteiro", True, "ok")
    assert registro.decisao_do_portao(pasta, "narracao")["origem"] == "pendente"


def test_aprovacao_so_humana_nao_aceita_outro_autor(pasta):
    # R12: o juiz de modelo nunca grava aprovacao
    with pytest.raises(TypeError):
        registro.registrar_aprovacao(pasta, "roteiro", True, "juiz achou bom", por="juiz")


def test_linha_de_outro_autor_no_arquivo_nao_conta_como_aprovacao_humana(pasta):
    import json as _json
    linha = {"quando": "2026-10-02T00:00:00Z", "portao": "roteiro", "aprovado": True, "nota": "x", "por": "juiz"}
    (pasta / "aprovacoes.jsonl").write_text(_json.dumps(linha) + "\n")
    d = registro.decisao_do_portao(pasta, "roteiro", veredito_juiz=True)
    assert d == {"aprovado": False, "origem": "pendente", "juiz_discordou": False}


@pytest.mark.parametrize("valor", ["false", "nao", "0", 0, 1, None, "true"])
def test_aprovado_precisa_ser_bool(pasta, valor):
    with pytest.raises(TypeError):
        registro.registrar_aprovacao(pasta, "pauta", valor, "x")
    assert _linhas(pasta, "aprovacoes.jsonl") == []
