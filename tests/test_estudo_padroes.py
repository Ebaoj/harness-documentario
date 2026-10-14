import pytest
import json

from scripts import estudo_padroes as p


def ficha(vid, ids):
    return {
        "video_id": vid,
        "padroes": [
            {"id": i, "nota": f"nota {i}", "evidencia": {"video_id": vid, "inicio_s": 1, "fim_s": 9}} for i in ids
        ],
    }


def entrada(canal, grupo, vid, ids):
    return {"canal": canal, "grupo": grupo, "ficha": ficha(vid, ids)}


ENTRADAS = [
    entrada("c1", "melhores", "v1", ["A", "C"]),
    entrada("c1", "base", "v2", ["C", "D"]),
    entrada("c2", "melhores", "v3", ["A", "C", "B"]),
    entrada("c2", "base", "v4", ["C", "D", "B"]),
    entrada("c3", "melhores", "v5", ["A", "C"]),
    entrada("c3", "base", "v6", ["C", "D"]),
]


def _agregado():
    return {r["id"]: r for r in p.agregar(ENTRADAS, minimo=3)}


def test_promove_so_com_tres_videos_ou_mais():
    r = _agregado()
    assert r["A"]["promovido"] and r["C"]["promovido"] and r["D"]["promovido"]
    assert not r["B"]["promovido"] and r["B"]["videos"] == 2


def test_classificacao_dos_grupos():
    r = _agregado()
    assert r["A"]["grupo"] == "so_nos_melhores"
    assert r["D"]["grupo"] == "so_na_mediana"
    assert r["C"]["grupo"] == "nos_dois_grupos"
    assert r["B"]["grupo"] == "nos_dois_grupos"


def test_aparece_em_todos_nao_e_padrao_que_explica_desempenho():
    r = _agregado()
    assert r["C"]["aparece_em_todos"] is True
    assert r["A"]["aparece_em_todos"] is False


def test_multicanal_e_por_canal():
    r = _agregado()
    assert r["A"]["multicanal"] and r["A"]["canais"] == ["c1", "c2", "c3"]
    assert r["A"]["por_canal"]["c1"] == {"melhores": "1/1", "base": "0/1"}


def test_escreve_um_json_por_padrao_sem_texto_de_narracao(tmp_path):
    p.escrever_biblioteca(p.agregar(ENTRADAS, 3), tmp_path)
    assert (tmp_path / "A.json").exists() and (tmp_path / "indice.json").exists()
    dado = json.loads((tmp_path / "A.json").read_text())
    assert {e["video_id"] for e in dado["evidencias"]} == {"v1", "v3", "v5"}
    assert all({"canal", "video_id", "inicio_s", "fim_s", "grupo"} <= set(e) for e in dado["evidencias"])
    assert dado["promovido"] is True
    indice = json.loads((tmp_path / "indice.json").read_text())
    assert {x["id"] for x in indice["padroes"]} == {"A", "B", "C", "D"}


def test_escrita_recusa_evidencia_com_texto_de_narracao(tmp_path):
    import pytest
    ruim = [entrada("c1", "melhores", "v1", ["A"])]
    ruim[0]["ficha"]["padroes"][0]["evidencia"]["texto"] = "frase da narração"
    with pytest.raises(ValueError, match="narra"):
        p.agregar(ruim, 1)


def test_diferenca_de_taxa_entre_melhores_e_base():
    r = _agregado()
    assert r["A"]["diferenca_taxa"] == 1.0   # 3/3 nos melhores contra 0/3 na base
    assert r["D"]["diferenca_taxa"] == -1.0
    assert r["C"]["diferenca_taxa"] == 0.0
    assert r["A"]["tendencia"] == "mais_nos_melhores"
    assert r["D"]["tendencia"] == "mais_na_mediana"
    assert r["C"]["tendencia"] == "sem_diferenca"


def test_estrutura_comparada_por_grupo():
    def e(grupo, gancho, atos, voltas, revs):
        return {"canal": "c", "grupo": grupo, "ficha": {
            "video_id": "v", "padroes": [],
            "gancho": {"fim_s": gancho}, "atos": [{}] * atos,
            "voltas": [{"fechada_s": 1}] * voltas[0] + [{"fechada_s": None}] * voltas[1],
            "reviravoltas": [{}] * revs, "retencao": []}}

    r = p.estrutura_comparada([e("melhores", 30, 4, (3, 1), 2), e("melhores", 50, 6, (1, 1), 0), e("base", 90, 3, (0, 2), 1)])
    assert r["melhores"]["gancho_fim_s_mediana"] == 40
    assert r["melhores"]["atos_mediana"] == 5
    assert r["melhores"]["voltas_fechadas_percentual"] == 66.7
    assert r["base"]["voltas_fechadas_percentual"] == 0.0
    assert r["base"]["reviravoltas_mediana"] == 1
    assert r["melhores"]["videos"] == 2


def test_default_de_producao_promove_com_tres_videos():
    r = {x["id"]: x for x in p.agregar(ENTRADAS)}  # sem passar minimo: vale o default do R16
    assert p.MINIMO_VIDEOS == 3
    assert not r["B"]["promovido"] and r["D"]["promovido"]


def _entradas_para_tendencia(n_m, n_b, em_m, em_b):
    es = []
    for i in range(n_m):
        es.append(entrada("c", "melhores", f"m{i}", ["X"] if i < em_m else ["Y"]))
    for i in range(n_b):
        es.append(entrada("c", "base", f"b{i}", ["X"] if i < em_b else ["Y"]))
    return es


def test_tendencia_no_limite_exato_de_25_pontos():
    r = {x["id"]: x for x in p.agregar(_entradas_para_tendencia(4, 4, 2, 1), 1)}
    assert r["X"]["diferenca_taxa"] == 0.25
    assert r["X"]["tendencia"] == "mais_nos_melhores"
    r = {x["id"]: x for x in p.agregar(_entradas_para_tendencia(5, 5, 3, 2), 1)}  # 0.6 - 0.4 = 0.2
    assert r["X"]["tendencia"] == "sem_diferenca"
    assert p.LIMITE_TENDENCIA == 0.25


def test_biblioteca_nao_guarda_nota_nem_texto_livre(tmp_path):
    p.escrever_biblioteca(p.agregar(ENTRADAS, 3), tmp_path, {"A": "o que é o padrão"})
    for arq in tmp_path.glob("*.json"):
        texto = arq.read_text()
        assert '"nota"' not in texto, arq.name
    dado = json.loads((tmp_path / "A.json").read_text())
    assert set(dado["evidencias"][0]) == {"canal", "video_id", "grupo", "inicio_s", "fim_s", "ampla"}
    assert dado["descricao"] == "o que é o padrão"


def test_evidencia_ampla_e_marcada():
    es = [entrada("c", "melhores", "v1", ["A"])]
    es[0]["ficha"]["padroes"][0]["evidencia"] = {"video_id": "v1", "inicio_s": 0, "fim_s": 600}
    es.append(entrada("c", "base", "v2", ["A"]))
    r = p.agregar(es, 1)[0]
    por_video = {e["video_id"]: e["ampla"] for e in r["evidencias"]}
    assert por_video == {"v1": True, "v2": False}


@pytest.mark.parametrize(
    "ev_ruim",
    [
        {"video_id": "OUTRO", "inicio_s": 1, "fim_s": 9},
        {"video_id": "v1", "inicio_s": 99999, "fim_s": 0},
        {"video_id": "v1", "inicio_s": -4, "fim_s": 9},
    ],
)
def test_agregar_revalida_a_evidencia_de_cada_ficha(ev_ruim):
    es = [entrada("c", "melhores", "v1", ["A"])]
    es[0]["ficha"]["padroes"][0]["evidencia"] = ev_ruim
    with pytest.raises(ValueError, match="evid"):
        p.agregar(es, 1)


def test_agregar_recusa_padrao_sem_evidencia_com_erro_claro():
    es = [entrada("c", "melhores", "v1", ["A"])]
    del es[0]["ficha"]["padroes"][0]["evidencia"]
    with pytest.raises(ValueError, match="evid"):
        p.agregar(es, 1)


def test_carregar_entradas_recusa_ficha_de_outro_video(tmp_path):
    canal = tmp_path / "c1"
    (canal / "v1").mkdir(parents=True)
    (canal / "amostra.json").write_text(json.dumps([{"id": "v1", "grupo": "melhores"}]))
    (canal / "v1" / "ficha.json").write_text(json.dumps(ficha("OUTRO", ["A"])))
    with pytest.raises(ValueError, match="video_id"):
        p.carregar_entradas(tmp_path)
