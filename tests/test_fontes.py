import json

import pytest

from scripts import fontes, modelo


def _foto(**extra):
    f = {
        "id": "pai-1993",
        "tipo": "foto",
        "arquivo": "03-assets/pai.jpg",
        "origem": {"fonte": "jornal local, 1993", "licenca": "imprensa: revisão jurídica"},
        "do_caso": True,
        "etiquetas": ["pai", "mãe"],
        "pessoas": [{"nome": "o pai", "papel": "familia", "olhos": "borrar"}],
        "identidade": {"verificada": True, "como": "legenda do jornal com os nomes"},
        "ano": 1993,
    }
    f.update(extra)
    return f


def _clipe(**extra):
    f = {
        "id": "especialista-1",
        "tipo": "clipe",
        "arquivo": "03-assets/real/doc.mp4",
        "origem": {"fonte": "documentário, 2022", "licenca": "uso de trecho curto: revisão jurídica"},
        "do_caso": True,
        "etiquetas": ["especialista"],
        "natureza": "entrevista",
        "trecho": [74.0, 80.9],
        "pessoas": [{"nome": "a especialista", "papel": "especialista", "olhos": "manter"}],
        "identidade": {"verificada": True, "como": "letreiro do documentário"},
        "ano": 2022,
    }
    f.update(extra)
    return f


def _erros(*itens):
    return fontes.validar({"fontes": list(itens)})


def _ctx(*itens):
    return {"fontes": list(itens)}


def test_catalogo_valido_nao_tem_erro():
    assert _erros(_foto(), _clipe()) == []


def test_id_repetido_reprova():
    assert any("repetido" in e for e in _erros(_foto(), _foto()))


def test_tipo_desconhecido_reprova():
    assert any("tipo" in e for e in _erros(_foto(tipo="gif")))


def test_fonte_sem_etiqueta_reprova():
    """Sem dizer o que mostra, o planejador não sabe casar imagem e frase (M07)."""
    assert any("etiquetas" in e for e in _erros(_foto(etiquetas=[])))


def test_fonte_sem_origem_ou_licenca_reprova():
    assert any("licenca" in e for e in _erros(_foto(origem={"fonte": "x"})))


# M13: foto só com identidade confirmada
def test_foto_de_pessoa_sem_identidade_verificada_reprova():
    erros = _erros(_foto(identidade={"verificada": False, "como": "parece ele"}))
    assert any("M13" in e for e in erros)
    assert any("M13" in e for e in _erros(_foto(identidade=None)))


def test_foto_sem_pessoa_dispensa_identidade():
    assert _erros(_foto(pessoas=[], identidade=None, etiquetas=["rua"])) == []


# M14: clipe de terceiros classificado; reencenação não leva nome de pessoa
def test_clipe_sem_natureza_reprova():
    c = _clipe()
    del c["natureza"]
    assert any("M14" in e for e in _erros(c))


def test_reencenacao_com_pessoa_nomeada_reprova():
    erros = _erros(_clipe(natureza="reencenacao"))
    assert any("M14" in e and "reencenação" in e for e in erros)
    assert _erros(_clipe(natureza="reencenacao", pessoas=[], identidade=None, etiquetas=["sofá"])) == []


# M15 (campo): clipe declara o trecho útil
def test_clipe_sem_trecho_util_reprova():
    assert any("trecho" in e for e in _erros(_clipe(trecho=None)))
    assert any("trecho" in e for e in _erros(_clipe(trecho=[80.0, 74.0])))


# M16 (revista em 10/10/2026): só quem não tem nada a ver com o caso e está vivo fica com o rosto borrado
@pytest.mark.parametrize("papel", ["vitima", "familia", "testemunha", "policia", "jornalista", "especialista", "acusado"])
def test_pessoa_envolvida_no_caso_pode_aparecer_com_o_rosto(papel):
    """'só não pode aparecer rosto de gente viva que não tem nada a ver; as pessoas envolvidas pode aparecer'."""
    assert not any("M16" in e for e in _erros(_foto(pessoas=[{"nome": "x", "papel": papel, "olhos": "manter"}])))


def test_pessoa_de_fora_do_caso_viva_precisa_de_borrao():
    erros = _erros(_foto(pessoas=[{"nome": "o advogado ao fundo", "papel": "publico", "olhos": "manter"}]))
    assert any("M16" in e for e in erros)
    assert _erros(_foto(pessoas=[{"nome": "o advogado ao fundo", "papel": "publico", "olhos": "borrar"}])) == []
    assert _erros(_foto(pessoas=[{"nome": "x", "papel": "publico", "olhos": "manter", "falecido": True}])) == []


def test_papel_ou_olhos_desconhecido_reprova():
    assert any("papel" in e for e in _erros(_foto(pessoas=[{"nome": "x", "papel": "vizinho", "olhos": "borrar"}])))
    assert any("olhos" in e for e in _erros(_foto(pessoas=[{"nome": "x", "papel": "familia", "olhos": "?"}])))


# M03: real é do caso; stock e IA não contam
def test_do_caso_tem_de_ser_declarado_em_foto_clipe_e_documento():
    f = _foto()
    del f["do_caso"]
    assert any("M03" in e for e in _erros(f))


def test_stock_nunca_e_do_caso():
    assert any("M03" in e for e in _erros(_foto(tipo="stock", pessoas=[], identidade=None)))


def test_conta_como_real():
    assert fontes.conta_como_real(_foto()) is True
    assert fontes.conta_como_real(_foto(do_caso=False)) is False
    assert fontes.conta_como_real(_clipe(natureza="reencenacao")) is False
    assert fontes.conta_como_real({"tipo": "ia"}) is False


# IA: rotulada e sem rosto de pessoa real (D4)
def test_ia_exige_rotulo_e_sem_rosto_real():
    ia = {"id": "sala", "tipo": "ia", "arquivo": "ia.png", "etiquetas": ["sala"],
          "origem": {"fonte": "gerada por IA", "licenca": "própria"}, "prompt": "sala dos anos 50",
          "rotulo": True, "sem_rosto_real": True}
    assert _erros(ia) == []
    assert any("rótulo" in e for e in _erros({**ia, "rotulo": False}))
    assert any("rosto" in e for e in _erros({**ia, "sem_rosto_real": False}))


# arquivo e integração com o modelo
def test_carregar_le_o_arquivo_do_episodio(tmp_path):
    (tmp_path / "fontes.json").write_text(json.dumps({"fontes": [_foto()]}))
    assert fontes.carregar(tmp_path)["fontes"][0]["id"] == "pai-1993"


def test_funcoes_das_regras_ficam_registradas_no_modelo():
    funcoes = modelo.funcoes_registradas()
    assert {"fontes_identidade", "fontes_natureza_clipe", "fontes_olhos", "fontes_do_caso"} <= set(funcoes)
    # contrato único: função(contexto) -> lista de erros
    assert funcoes["fontes_olhos"](_ctx(_foto())) == []


def test_cli_do_modelo_valida_o_canal_com_as_funcoes_automaticas():
    import subprocess
    import sys

    for cmd in ([sys.executable, "-m", "scripts.modelo"], [sys.executable, "scripts/modelo.py"]):
        r = subprocess.run(cmd + ["validar", "canais/exemplo/modelo"], capture_output=True, text=True,
                           cwd=modelo.RAIZ_CANAIS.parent)
        assert r.returncode == 0, r.stdout + r.stderr


def _voz(**extra):
    v = {"id": "voz-1", "tipo": "voz", "arquivo": "voz.wav", "ano": 2005, "etiquetas": ["pai"],
         "origem": {"fonte": "documentário", "licenca": "trecho curto: revisão jurídica"}, "trecho": [1.0, 5.0],
         "pessoas": [{"nome": "o acusado", "papel": "acusado", "olhos": "manter"}],
         "identidade": {"verificada": True, "como": "letreiro"}}
    v.update(extra)
    return v


def test_voz_de_pessoa_exige_identidade_e_trecho():
    assert _erros(_voz()) == []
    assert any("M13" in e for e in _erros(_voz(identidade=None)))
    assert any("trecho" in e for e in _erros(_voz(trecho=None)))


def test_ano_obrigatorio_em_material_do_caso():
    f = _foto()
    del f["ano"]
    assert any("ano" in e for e in _erros(f))
    assert _erros(_foto(ano="anos 1950")) == []


@pytest.mark.parametrize("campo,valor", [("pessoas", "o pai"), ("identidade", "sim"), ("etiquetas", "pai"),
                                         ("origem", "jornal")])
def test_tipo_errado_reprova_sem_derrubar(campo, valor):
    assert _erros(_foto(**{campo: valor}))


def test_trecho_com_texto_reprova_sem_derrubar():
    assert any("trecho" in e for e in _erros(_clipe(trecho=["1", "2"])))


def test_reencenacao_com_nome_de_pessoa_nas_etiquetas_reprova():
    """Lição F014: a reencenação foi rotulada com o nome da especialista."""
    especialista = _clipe()
    reenc = _clipe(id="sofa", natureza="reencenacao", pessoas=[], identidade=None,
                   etiquetas=["sofá", "a especialista"])
    assert any("M14" in e and "sofa" in e for e in _erros(especialista, reenc))


def test_ia_nao_e_do_caso_nem_tem_pessoa():
    ia = {"id": "sala", "tipo": "ia", "arquivo": "ia.png", "etiquetas": ["sala"], "prompt": "sala",
          "origem": {"fonte": "IA", "licenca": "própria"}, "rotulo": True, "sem_rosto_real": True}
    assert any("M03" in e for e in _erros({**ia, "do_caso": True}))
    assert any("pessoa" in e for e in _erros({**ia, "pessoas": [{"nome": "x", "papel": "vitima", "olhos": "borrar"}]}))


@pytest.mark.parametrize("lic", ["verificar", "domínio público (verificar)", "a confirmar", "ver página", "?"])
def test_licenca_pendente_reprova(lic):
    assert any("licença" in e for e in _erros(_foto(origem={"fonte": "x", "licenca": lic})))
