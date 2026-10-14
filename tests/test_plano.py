import copy

import pytest

from scripts import modelo, plano

# Catálogo mínimo de fontes (forma do scripts/fontes.py)
FONTES = [
    {"id": "foto-acusado", "tipo": "foto", "do_caso": True, "etiquetas": ["acusado", "1974"],
     "pessoas": [{"nome": "o acusado", "papel": "acusado", "olhos": "manter"}]},
    {"id": "rua", "tipo": "clipe", "do_caso": True, "natureza": "local", "trecho": [10.0, 20.0],
     "etiquetas": ["bairro", "rua"], "pessoas": []},
    {"id": "tv-1978", "tipo": "clipe", "do_caso": True, "natureza": "arquivo_tv", "trecho": [0.0, 30.0],
     "etiquetas": ["polícia 1978"], "pessoas": [{"nome": "o chefe", "papel": "policia", "olhos": "manter"}]},
    {"id": "especialista-cam", "tipo": "clipe", "do_caso": True, "natureza": "entrevista", "trecho": [100.0, 106.0],
     "etiquetas": ["especialista"], "pessoas": [{"nome": "a especialista", "papel": "especialista", "olhos": "manter"}]},
    {"id": "voz-especialista", "tipo": "voz", "trecho": [100.0, 110.0], "etiquetas": ["projetos"],
     "pessoas": [{"nome": "a especialista", "papel": "especialista", "olhos": "manter"}]},
    {"id": "ia-sala", "tipo": "ia", "etiquetas": ["sala"], "rotulo": True, "sem_rosto_real": True},
    {"id": "mapa", "tipo": "mapa", "etiquetas": ["mapa"]},
]


def _cena(id_, ini, fim, **extra):
    c = {"id": id_, "ini": ini, "fim": fim}
    c.update(extra)
    return c


def _plano(*cenas, **extra):
    p = {"dur": max(c["fim"] for c in cenas), "cenas": list(cenas)}
    p.update(extra)
    return p


def _erros(p, regra=None, palavras=None):
    ctx = {"plano": p, "fontes": FONTES, "palavras": palavras or {}}
    if regra:
        return plano.REGRAS[regra](ctx)
    return plano.validar(ctx)


BOM = _plano(
    _cena("A", 0, 8, fonte="foto-acusado", mostra=["acusado"]),
    _cena("B", 8, 12, fonte="mapa"),
    _cena("C", 12, 20, fonte="rua", clipe={"de": 10.0, "velocidade": 1.0}),
)


def test_plano_bom_passa():
    assert _erros(BOM) == []


# M01: cena com 3 s ou mais, sem buraco nem sobreposição
def test_cena_curta_reprova():
    p = _plano(_cena("A", 0, 2.5, fonte="mapa"), _cena("B", 2.5, 10, fonte="foto-acusado"))
    assert any("M01" in e and "A" in e for e in _erros(p, "plano_duracao"))


def test_ultima_cena_pode_ser_curta():
    p = _plano(_cena("A", 0, 8, fonte="foto-acusado"), _cena("B", 8, 9.5, fonte="mapa"))
    assert _erros(p, "plano_duracao") == []


def test_buraco_entre_cenas_reprova():
    p = _plano(_cena("A", 0, 5, fonte="foto-acusado"), _cena("B", 5.5, 10, fonte="mapa"))
    assert any("buraco" in e for e in _erros(p, "plano_duracao"))


# M02: 51% real e nenhuma janela de 15 s abaixo de 30%
def test_pouca_imagem_real_reprova():
    p = _plano(_cena("A", 0, 10, fonte="mapa"), _cena("B", 10, 14, fonte="foto-acusado"))
    assert any("M02" in e and "51%" in e for e in _erros(p, "plano_real"))


def test_janela_sem_imagem_real_reprova_mesmo_com_media_boa():
    p = _plano(_cena("A", 0, 30, fonte="foto-acusado"), _cena("B", 30, 46, fonte="mapa"),
               _cena("C", 46, 76, fonte="foto-acusado"))
    erros = _erros(p, "plano_real")
    assert any("janela" in e for e in erros)


def test_ia_e_reencenacao_nao_contam_como_real():
    assert plano.cena_real(_cena("A", 0, 4, fonte="ia-sala"), {f["id"]: f for f in FONTES}) is False


# M04: texto sobre vídeo real só se for intencional
def test_texto_sobre_video_reprova():
    c = _cena("C", 12, 20, fonte="rua", clipe={"de": 10.0, "velocidade": 1.0},
              texto=[{"texto": "TROLLING", "sobre_video": True}])
    assert any("M04" in e for e in _erros(_plano(c), "plano_texto"))
    c["texto"][0]["intencional"] = "a palavra é o título do trecho"
    assert _erros(_plano(c), "plano_texto") == []


# M06: rosto do acusado só depois da revelação
def test_rosto_do_acusado_antes_da_revelacao_reprova():
    p = _plano(_cena("A", 0, 8, fonte="foto-acusado"), revelacao=30.0)
    assert any("M06" in e for e in _erros(p, "plano_revelacao"))
    p["revelacao"] = 0.0
    assert _erros(p, "plano_revelacao") == []


# M07: a imagem mostra o que a frase diz
def test_cena_que_nao_mostra_o_que_a_frase_pede_reprova():
    c = _cena("A", 0, 8, fonte="rua", clipe={"de": 10.0, "velocidade": 1.0}, mostra=["pai"])
    assert any("M07" in e and "pai" in e for e in _erros(_plano(c), "plano_semantica"))


# M08: imagem de IA com rótulo na tela
def test_ia_sem_rotulo_na_cena_reprova():
    assert any("M08" in e for e in _erros(_plano(_cena("A", 0, 8, fonte="ia-sala")), "plano_ia"))
    assert _erros(_plano(_cena("A", 0, 8, fonte="ia-sala", rotulo_ia=True)), "plano_ia") == []


# M10: entrevista só com a voz da própria pessoa; arquivo de TV mudo pode
def test_entrevista_muda_reprova():
    c = _cena("A", 0, 6, fonte="especialista-cam", clipe={"de": 100.0, "velocidade": 1.0})
    assert any("M10" in e for e in _erros(_plano(c), "plano_entrevista"))
    c["voz"] = {"fonte": "voz-especialista", "em": 0.0}
    assert _erros(_plano(c), "plano_entrevista") == []


def test_arquivo_de_tv_mudo_pode():
    c = _cena("A", 0, 6, fonte="tv-1978", clipe={"de": 0.0, "velocidade": 1.0})
    assert _erros(_plano(c), "plano_entrevista") == []


# M15: o clipe não passa do trecho útil
def test_clipe_alem_do_trecho_util_reprova():
    c = _cena("C", 0, 8, fonte="rua", clipe={"de": 14.0, "velocidade": 1.0})  # 14 + 8 = 22 > 20
    assert any("M15" in e for e in _erros(_plano(c), "plano_trecho"))
    c["clipe"]["velocidade"] = 0.5  # 14 + 4 = 18
    assert _erros(_plano(c), "plano_trecho") == []


def test_clipe_antes_do_trecho_util_reprova():
    c = _cena("C", 0, 4, fonte="rua", clipe={"de": 8.0, "velocidade": 1.0})
    assert any("M15" in e for e in _erros(_plano(c), "plano_trecho"))


# M11: legenda colada aos tempos de palavra (±0,3 s)
PALAVRAS = {"voz-especialista": [[0.0, 0.4, "Ele"], [0.5, 1.2, "chamava"], [1.3, 2.0, "projetos."],
                                  [3.0, 3.5, "Se"], [3.6, 4.4, "virar"], [4.5, 5.0, "rotina."]]}


def _com_legendas(itens, em=1.0):
    c = _cena("A", 0, 7, fonte="especialista-cam", clipe={"de": 100.0, "velocidade": 1.0},
              voz={"fonte": "voz-especialista", "em": em})
    return _plano(c, vozes=[{"fonte": "voz-especialista", "em": em, "legendas": itens}])


def test_legenda_alinhada_passa_e_desalinhada_reprova():
    assert _erros(_com_legendas([[1.0, 3.0, "Primeira frase."], [4.0, 6.0, "Segunda frase."]]), "plano_legenda", PALAVRAS) == []
    # começa 0,8 s antes da fala
    assert any("M11" in e for e in _erros(_com_legendas([[1.0, 3.0, "A frase."], [3.2, 6.0, "Outra frase."]]), "plano_legenda", PALAVRAS))


def test_legenda_tem_de_comecar_no_inicio_de_uma_frase():
    """Revisão T17: encostar em qualquer palavra deixava passar legenda no meio da frase."""
    erros = _erros(_com_legendas([[1.0, 3.0, "A frase."], [4.6, 6.0, "Começa no meio."]]), "plano_legenda", PALAVRAS)
    assert any("M11" in e and "meio de uma frase" in e for e in erros)


def test_legenda_sem_tempos_de_palavra_reprova():
    assert any("M11" in e and "transcrição" in e for e in _erros(_com_legendas([[1.0, 3.0, "x"]]), "plano_legenda", {}))


def test_cena_com_fonte_desconhecida_reprova():
    assert any("nao-existe" in e for e in _erros(_plano(_cena("A", 0, 8, fonte="nao-existe"))))


def test_regras_do_plano_ficam_registradas_no_modelo():
    nomes = set(modelo.funcoes_registradas())
    assert {"plano_duracao", "plano_real", "plano_texto", "plano_revelacao", "plano_semantica", "plano_ia",
            "plano_entrevista", "plano_trecho", "plano_legenda"} <= nomes


def test_fim_da_legenda_pode_cair_dentro_da_ultima_palavra_esticada():
    """O transcritor estica a última palavra até o silêncio: a legenda pode sair antes desse fim marcado."""
    ws = {"voz-especialista": [[0.0, 0.5, "Você"], [0.6, 3.0, "perigo."]]}
    assert _erros(_com_legendas([[0.0, 1.2, "Frase."]], em=0.0), "plano_legenda", ws) == []
    assert any("M11" in e for e in _erros(_com_legendas([[0.0, 3.6, "Frase."]], em=0.0), "plano_legenda", ws))


# --- correções da revisão da T17 ---------------------------------------------


def test_cena_de_clipe_sem_chave_clipe_tambem_respeita_o_trecho():
    c = _cena("C", 0, 50, fonte="rua")  # trecho útil de 10 s usado por 50 s
    assert any("M15" in e for e in _erros(_plano(c), "plano_trecho"))


def test_velocidade_zero_ou_negativa_reprova():
    c = _cena("C", 0, 4, fonte="rua", clipe={"de": 10.0, "velocidade": 0})
    assert any("M15" in e and "velocidade" in e for e in _erros(_plano(c), "plano_trecho"))


def test_fontes_extra_tambem_passam_por_m06_e_m08():
    p = _plano(_cena("A", 0, 8, fonte="mapa", fontes_extra=["foto-acusado"]), revelacao=30.0)
    assert any("M06" in e for e in _erros(p, "plano_revelacao"))
    assert any("M08" in e for e in _erros(_plano(_cena("A", 0, 8, fonte="mapa", fontes_extra=["ia-sala"])), "plano_ia"))


def test_mostra_compara_palavra_inteira():
    """Revisão T17: 'pai' não pode casar com 'paisagem'."""
    fontes = FONTES + [{"id": "paisagem", "tipo": "foto", "do_caso": False, "etiquetas": ["paisagem do planalto"]}]
    ctx = {"plano": _plano(_cena("A", 0, 8, fonte="paisagem", mostra=["pai"])), "fontes": fontes}
    assert any("M07" in e for e in plano.checar_semantica(ctx))
    ctx["plano"] = _plano(_cena("A", 0, 8, fonte="paisagem", mostra=["planalto"]))
    assert plano.checar_semantica(ctx) == []


def test_entrevista_com_voz_de_outra_pessoa_sem_nome_reprova():
    fontes = FONTES + [{"id": "cam-sem-nome", "tipo": "clipe", "natureza": "entrevista", "trecho": [0, 9], "etiquetas": ["x"],
                        "pessoas": [{"papel": "especialista"}]},
                       {"id": "voz-sem-nome", "tipo": "voz", "trecho": [0, 9], "etiquetas": ["x"], "pessoas": [{"papel": "policia"}]}]
    c = _cena("A", 0, 6, fonte="cam-sem-nome", clipe={"de": 0, "velocidade": 1}, voz={"fonte": "voz-sem-nome", "em": 0})
    assert any("M10" in e for e in plano.checar_entrevista({"plano": _plano(c), "fontes": fontes}))


def test_entrevista_fora_de_sincronia_reprova():
    """A voz e o clipe vêm da mesma gravação: o ponto do clipe tem de bater com o ponto da voz."""
    fontes = [dict(f) for f in FONTES]
    for f in fontes:
        if f["id"] in ("especialista-cam", "voz-especialista"):
            f["origem"] = {"fonte": "documentário X"}
    c = _cena("A", 2, 6, fonte="especialista-cam", clipe={"de": 102.0, "velocidade": 1.0}, voz={"fonte": "voz-especialista", "em": 0.0})
    assert plano.checar_entrevista({"plano": _plano(c), "fontes": fontes}) == []
    c["clipe"]["de"] = 100.5  # boca 1,5 s atrasada em relação à voz
    assert any("M10" in e and "sincronia" in e for e in plano.checar_entrevista({"plano": _plano(c), "fontes": fontes}))


def test_cena_mal_formada_vira_erro_e_nao_excecao():
    p = {"dur": 10, "cenas": [{"id": "A", "fim": 5, "fonte": "mapa"}, _cena("B", 5, 10, fonte="foto-acusado")]}
    assert any("A" in e and "ini" in e for e in _erros(p))


def test_cenas_sobrepostas_nao_contam_real_em_dobro():
    p = _plano(_cena("A", 0, 10, fonte="foto-acusado"), _cena("B", 0, 10, fonte="foto-acusado"), _cena("C", 10, 30, fonte="mapa"))
    assert any("M02" in e and "51%" in e for e in _erros(p, "plano_real"))


def test_ultima_janela_tambem_e_julgada():
    p = _plano(_cena("A", 0, 20, fonte="foto-acusado"), _cena("B", 20, 34.7, fonte="mapa"))  # 20 a 34,7 sem real
    assert any("janela" in e for e in _erros(p, "plano_real"))


def test_cli_verifica_um_plano(tmp_path, capsys):
    import json

    (tmp_path / "fontes.json").write_text(json.dumps({"fontes": FONTES}))
    (tmp_path / "plano.json").write_text(json.dumps(BOM))
    assert plano.main([str(tmp_path), str(tmp_path / "plano.json")]) == 0
    ruim = _plano(_cena("A", 0, 2, fonte="mapa"), _cena("B", 2, 9, fonte="mapa"))
    (tmp_path / "ruim.json").write_text(json.dumps(ruim))
    assert plano.main([str(tmp_path), str(tmp_path / "ruim.json")]) == 1
    assert "M01" in capsys.readouterr().out


def test_legenda_em_minuscula_continua_a_anterior_sem_buraco():
    ok = _com_legendas([[1.0, 3.0, "E uma coisa que ele dizia:"], [3.0, 6.0, "se virar meu projeto."]])
    ws = {"voz-especialista": [[0.0, 0.4, "And"], [0.5, 1.9, "said"], [2.0, 2.5, "if"], [2.6, 4.8, "trouble."]]}
    assert _erros(ok, "plano_legenda", ws) == []
    buraco = _com_legendas([[1.0, 2.5, "E uma coisa que ele dizia:"], [3.0, 6.0, "se virar meu projeto."]])
    assert any("M11" in e for e in _erros(buraco, "plano_legenda", ws))


def test_legenda_que_comeca_antes_da_anterior_acabar_reprova():
    ws = {"voz-especialista": [[0.0, 0.4, "Ele"], [0.5, 1.2, "chamava"], [1.3, 2.0, "projetos."], [3.0, 3.5, "Se"]]}
    p = _com_legendas([[0.0, 2.0, "Ele chamava projetos."], [1.9, 3.5, "Se."]], em=0.0)
    assert any("M11" in e for e in _erros(p, "plano_legenda", ws))


def test_frase_que_termina_em_ponto_e_aspas_abre_legenda_nova():
    """Uma frase terminada em ponto e aspas era tida como meio de frase, e a fala de uma especialista virou
    uma legenda só, longa e resumida, que não acompanhava o que ela dizia."""
    pal = {"voz-especialista": [[0.0, 0.4, "Ele"], [0.5, 1.2, "disse"], [1.3, 2.0, 'isso."'],
                                [3.0, 3.5, "Mas"], [3.6, 4.4, "não"], [4.5, 5.0, "era."]]}
    assert _erros(_com_legendas([[1.0, 3.0, "Ele disse isso."], [4.0, 6.0, "Mas não era."]]), "plano_legenda", pal) == []


def test_encerramento_curto_sem_fala_de_terceiros_dispensa_imagem_real():
    """Decisão de produto (12/10/2026): tela de like e inscrição no fim. M02 vale para o conteúdo, não para o CTA."""
    c = {"id": "E", "ini": 0, "fim": 30, "componente": "chamada", "params": {"botao": "INSCREVER-SE"}}
    p = {"dur": 30.0, "tipo": "encerramento", "cenas": [c], "vozes": []}
    assert not any("M02" in e for e in _erros(p))
    assert any("M02" in e for e in _erros({**p, "tipo": None}))                       # sem a marca, a regra vale
    assert any("M02" in e for e in _erros({**p, "dur": 60.0, "cenas": [{**c, "fim": 60}]}))  # longo demais


def test_dispensa_do_encerramento_mede_as_cenas_e_nao_o_dur_declarado():
    """Revisão: um plano dizendo dur 30 com cenas até 300 s ficava todo dispensado da M02."""
    c = {"id": "E", "ini": 0, "fim": 300, "componente": "chamada", "params": {"botao": "INSCREVER-SE"}}
    assert any("M02" in e for e in _erros({"dur": 30.0, "tipo": "encerramento", "cenas": [c], "vozes": []}))
    assert any("M02" in e for e in _erros({"dur": None, "tipo": "encerramento", "cenas": [c], "vozes": []}))
