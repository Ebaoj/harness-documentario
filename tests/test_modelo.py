import json
import subprocess

import pytest

from scripts import modelo


@pytest.fixture
def pasta(tmp_path):
    modelo.criar(tmp_path)
    return tmp_path


def _regra(id_="M01", verificacao="manual", **extra):
    r = {
        "id": id_,
        "titulo": "cena dura pelo menos 3 s",
        "texto": "Nenhuma cena com menos de 3 s.",
        "origem": {"data": "2026-10-08", "citacao": "são rápidos demais"},
        "verificacao": verificacao,
    }
    r.update(extra)
    return r


# --- regras -----------------------------------------------------------------


def test_criar_comeca_na_versao_1_sem_regras(pasta):
    m = modelo.carregar(pasta)
    assert m["versao"] == 1
    assert m["regras"] == []
    assert modelo.validar(pasta) == []


def test_adicionar_regra_sobe_a_versao_e_registra_historico(pasta):
    modelo.adicionar_regra(pasta, _regra())
    m = modelo.carregar(pasta)
    assert m["versao"] == 2
    assert [r["id"] for r in m["regras"]] == ["M01"]
    (h,) = [json.loads(l) for l in (pasta / "historico.jsonl").read_text().splitlines()]
    assert h["versao"] == 2 and h["regra"] == "M01" and h["acao"] == "nova"


def test_regra_sem_origem_e_recusada(pasta):
    r = _regra()
    del r["origem"]
    with pytest.raises(ValueError, match="origem"):
        modelo.adicionar_regra(pasta, r)


def test_regra_com_id_repetido_e_recusada(pasta):
    modelo.adicionar_regra(pasta, _regra())
    with pytest.raises(ValueError, match="M01"):
        modelo.adicionar_regra(pasta, _regra())


def test_regra_automatica_sem_funcao_registrada_reprova(pasta):
    modelo.adicionar_regra(pasta, _regra(verificacao="auto", funcao="nao_existe"))
    erros = modelo.validar(pasta, funcoes={})
    assert any("M01" in e and "nao_existe" in e for e in erros)


def test_regra_automatica_com_funcao_registrada_passa(pasta):
    modelo.adicionar_regra(pasta, _regra(verificacao="auto", funcao="duracao_minima"))
    assert modelo.validar(pasta, funcoes={"duracao_minima": lambda *a: []}) == []


def test_regra_planejada_exige_tarefa(pasta):
    with pytest.raises(ValueError, match="tarefa"):
        modelo.adicionar_regra(pasta, _regra(verificacao="planejada"))
    modelo.adicionar_regra(pasta, _regra(verificacao="planejada", tarefa="T17"))


def test_ajustar_regra_sobe_versao_e_guarda_o_texto_anterior(pasta):
    modelo.adicionar_regra(pasta, _regra())
    modelo.ajustar_regra(pasta, "M01", {"texto": "Nenhuma cena com menos de 3 s, salvo a cartela final."}, "F002")
    m = modelo.carregar(pasta)
    assert m["versao"] == 3
    assert m["regras"][0]["texto"].endswith("cartela final.")
    h = [json.loads(l) for l in (pasta / "historico.jsonl").read_text().splitlines()][-1]
    assert h["acao"] == "ajuste" and h["feedback"] == "F002"
    assert h["antes"]["texto"] == "Nenhuma cena com menos de 3 s."


# --- feedback ---------------------------------------------------------------


def test_feedback_novo_fica_aberto_e_reprova_a_validacao(pasta):
    fid = modelo.registrar_feedback(pasta, "a cena não faz sentido", video="cap1-v2b.mp4", minuto="2:22")
    assert fid == "F001"
    erros = modelo.validar(pasta)
    assert any("F001" in e and "aberto" in e for e in erros)


def test_feedback_exige_texto(pasta):
    with pytest.raises(ValueError):
        modelo.registrar_feedback(pasta, "  ")


def test_fechar_feedback_como_regra_nova_exige_regra_existente(pasta):
    fid = modelo.registrar_feedback(pasta, "rápido demais")
    with pytest.raises(ValueError, match="M09"):
        modelo.fechar_feedback(pasta, fid, "regra_nova", regra="M09")
    modelo.adicionar_regra(pasta, _regra("M09"), feedback=fid)
    modelo.fechar_feedback(pasta, fid, "regra_nova", regra="M09")
    assert modelo.validar(pasta) == []


def test_fechar_como_caso_unico_exige_justificativa(pasta):
    fid = modelo.registrar_feedback(pasta, "troca a foto do minuto 3")
    with pytest.raises(ValueError, match="justificativa"):
        modelo.fechar_feedback(pasta, fid, "caso_unico")
    modelo.fechar_feedback(pasta, fid, "caso_unico", justificativa="foto específica deste episódio")
    assert modelo.validar(pasta) == []


def test_destino_desconhecido_e_recusado(pasta):
    fid = modelo.registrar_feedback(pasta, "x")
    with pytest.raises(ValueError):
        modelo.fechar_feedback(pasta, fid, "ignorar")


def test_feedback_so_acrescenta(pasta):
    fid = modelo.registrar_feedback(pasta, "x")
    modelo.fechar_feedback(pasta, fid, "caso_unico", justificativa="y")
    linhas = (pasta / "feedback.jsonl").read_text().splitlines()
    assert len(linhas) == 2
    assert modelo.feedbacks(pasta)[fid]["estado"] == "fechado"


def test_extrair_quadro_do_minuto_citado(tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=4", str(video)],
        check=True,
    )
    saida = modelo.extrair_quadro(video, "0:02", tmp_path / "q.jpg")
    assert saida.exists() and saida.stat().st_size > 0


def test_minuto_invalido_e_recusado(tmp_path):
    with pytest.raises(ValueError):
        modelo.extrair_quadro(tmp_path / "v.mp4", "dois minutos", tmp_path / "q.jpg")


# --- o modelo do canal ------------------------------------------------------


def test_modelo_do_canal_e_valido():
    """O modelo real do canal valida, com as funções automáticas já existentes."""
    from scripts import modelo as m

    pasta = m.RAIZ_CANAIS / "exemplo" / "modelo"
    assert m.validar(pasta, funcoes=m.funcoes_registradas()) == []
    regras = m.carregar(pasta)["regras"]
    assert len(regras) >= 20
    for r in regras:
        assert r["origem"]["citacao"].strip(), r["id"]


def test_cli_registra_e_fecha_feedback(pasta, capsys):
    assert modelo.main(["feedback", str(pasta), "legenda atrasada"]) == 0
    assert "F001" in capsys.readouterr().out
    assert modelo.main(["validar", str(pasta)]) == 1
    assert modelo.main(["fechar", str(pasta), "F001", "caso_unico", "--justificativa", "só neste vídeo"]) == 0
    assert modelo.main(["validar", str(pasta)]) == 0


# --- correções da revisão ---------------------------------------------------


def test_feedback_fechado_nao_fecha_de_novo(pasta):
    fid = modelo.registrar_feedback(pasta, "x")
    modelo.fechar_feedback(pasta, fid, "caso_unico", justificativa="y")
    with pytest.raises(ValueError, match="fechado"):
        modelo.fechar_feedback(pasta, fid, "caso_unico", justificativa="z")


def test_regra_nova_so_fecha_o_feedback_que_a_criou(pasta):
    f1 = modelo.registrar_feedback(pasta, "rápido demais")
    modelo.adicionar_regra(pasta, _regra("M01"), feedback=f1)
    f2 = modelo.registrar_feedback(pasta, "outra coisa")
    with pytest.raises(ValueError, match="F002"):
        modelo.fechar_feedback(pasta, f2, "regra_nova", regra="M01")
    modelo.fechar_feedback(pasta, f1, "regra_nova", regra="M01")


def test_ajuste_exige_ajuste_registrado_com_o_feedback(pasta):
    f1 = modelo.registrar_feedback(pasta, "a")
    modelo.adicionar_regra(pasta, _regra("M01"), feedback=f1)
    modelo.fechar_feedback(pasta, f1, "regra_nova", regra="M01")
    f2 = modelo.registrar_feedback(pasta, "b")
    with pytest.raises(ValueError, match="F002"):
        modelo.fechar_feedback(pasta, f2, "ajuste", regra="M01")
    modelo.ajustar_regra(pasta, "M01", {"texto": "novo"}, f2)
    modelo.fechar_feedback(pasta, f2, "ajuste", regra="M01")


def test_regra_criada_por_feedback_guarda_o_id_na_origem(pasta):
    f1 = modelo.registrar_feedback(pasta, "a")
    modelo.adicionar_regra(pasta, _regra("M01"), feedback=f1)
    assert modelo.carregar(pasta)["regras"][0]["origem"]["feedback"] == "F001"


def test_evento_de_fechamento_orfao_vira_erro_e_nao_excecao(pasta):
    (pasta / "feedback.jsonl").write_text('{"evento": "fechado", "id": "F009", "destino": "caso_unico"}\n')
    assert any("F009" in e for e in modelo.validar(pasta))


def test_modelo_ausente_ou_quebrado_vira_erro(tmp_path):
    (tmp_path / "regras.json").write_text("{quebrado")
    assert modelo.validar(tmp_path)


def test_cli_exige_video_e_minuto_juntos(pasta):
    with pytest.raises(SystemExit):
        modelo.main(["feedback", str(pasta), "x", "--video", "v.mp4"])


def test_checklist_lista_as_regras_manuais(pasta):
    modelo.adicionar_regra(pasta, _regra("M01", verificacao="manual"))
    modelo.adicionar_regra(pasta, _regra("M02", verificacao="planejada", tarefa="T17"))
    ids = [r["id"] for r in modelo.checklist(pasta)]
    assert ids == ["M01", "M02"]  # planejada ainda não é automática: entra no checklist


def test_video_registra_a_versao_do_modelo(pasta, tmp_path):
    modelo.adicionar_regra(pasta, _regra("M01"))
    video = tmp_path / "ep1"
    video.mkdir()
    carimbo = modelo.carimbar_video(video, pasta)
    assert carimbo["versao"] == 2
    gravado = json.loads((video / "modelo.json").read_text())
    assert gravado["versao"] == 2 and gravado["modelo"] == str(pasta)


def test_feedback_retroativo_nao_inventa_horario(pasta):
    fid = modelo.registrar_feedback(pasta, "x", data="2026-10-08", retroativo=True)
    f = modelo.feedbacks(pasta)[fid]
    assert f["quando"] == "2026-10-08" and f["retroativo"] is True


def test_regra_automatica_com_varias_funcoes(pasta):
    modelo.adicionar_regra(pasta, _regra(verificacao="auto", funcoes=["a", "b"]))
    assert modelo.validar(pasta, funcoes={"a": lambda c: [], "b": lambda c: []}) == []
    erros = modelo.validar(pasta, funcoes={"a": lambda c: []})
    assert any("'b'" in e for e in erros)


def test_regra_automatica_sem_nenhuma_funcao_reprova(pasta):
    with pytest.raises(ValueError, match="funcao"):
        modelo.adicionar_regra(pasta, _regra(verificacao="auto", funcoes=[]))
