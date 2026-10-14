"""Testes das funcoes puras de scripts/espaco.py (sem rede)."""
import json

import pytest

from scripts import espaco as e


@pytest.mark.parametrize("texto,esperado", [
    ("1.5K", 1500),
    ("2,3 mil", 2300),
    ("1,2 mi", 1200000),
    ("1,5 mil inscritos", 1500),
    ("12 mil visualizações", 12000),
    ("1,2 mi de visualizações", 1200000),
    ("1.234 visualizações", 1234),
    ("950 visualizações", 950),
    ("3.4M", 3400000),
    ("2 bi", 2000000000),
    ("1 inscrito", 1),
])
def test_parse_numero(texto, esperado):
    assert e.parse_numero(texto) == esperado


@pytest.mark.parametrize("texto", ["", None, "sem views", "Nenhuma visualização"])
def test_parse_numero_invalido(texto):
    assert e.parse_numero(texto) is None


@pytest.mark.parametrize("texto,dias", [
    ("há 6 dias", 6),
    ("há 1 dia", 1),
    ("6d ago", 6),
    ("6 days ago", 6),
    ("há 2 semanas", 14),
    ("há 3 meses", 90),
    ("há 1 ano", 365),
    ("há 2 anos", 730),
    ("Transmitido há 5 dias", 5),
    ("há 5 horas", 0),
    ("3 months ago", 90),
    ("há 1 mês", 30),
    ("há 3 sem.", 21),
    ("há 2 sem", 14),
    ("há 11 meses", 330),
])
def test_parse_idade_dias(texto, dias):
    assert e.parse_idade_dias(texto) == dias


def test_parse_idade_invalida():
    assert e.parse_idade_dias("") is None
    assert e.parse_idade_dias("ontem") is None


def test_parse_duracao():
    assert e.parse_duracao("12:34") == 754
    assert e.parse_duracao("1:02:03") == 3723
    assert e.parse_duracao("0:45") == 45
    assert e.parse_duracao("") is None
    assert e.parse_duracao(None) is None


def test_mediana():
    assert e.mediana([1, 3, 2]) == 2
    assert e.mediana([1, 2, 3, 4]) == 2.5
    assert e.mediana([]) == 0


def test_ano_entrada():
    assert e.ano_entrada("Inscreveu-se em 3 de mar. de 2025") == 2025
    assert e.ano_entrada("Joined Mar 3, 2026") == 2026
    assert e.ano_entrada("") is None


def test_pequeno_recente():
    assert e.pequeno_e_recente(50000, 2025)
    assert e.pequeno_e_recente(60000, 2026)
    assert not e.pequeno_e_recente(60001, 2026)
    assert not e.pequeno_e_recente(1000, 2024)
    assert not e.pequeno_e_recente(None, 2025)
    assert not e.pequeno_e_recente(1000, None)


def test_extrai_initial_data():
    html = '<script>var ytInitialData = {"a": {"b": [1, 2]}};</script>'
    assert e.extrai_initial_data(html) == {"a": {"b": [1, 2]}}
    assert e.extrai_initial_data("<html></html>") is None


def test_videos_da_busca_descarta_shorts():
    def vr(titulo, dur, views="10 mil visualizações"):
        r = {"title": {"runs": [{"text": titulo}]},
             "ownerText": {"runs": [{"text": "Canal X", "navigationEndpoint": {"browseEndpoint": {"browseId": "UC1"}}}]},
             "viewCountText": {"simpleText": views},
             "publishedTimeText": {"simpleText": "há 6 dias"}}
        if dur:
            r["lengthText"] = {"simpleText": dur}
        return {"videoRenderer": r}
    dados = {"x": [vr("Longo", "14:20"), vr("Curto", "0:50"), vr("SemDur", None)]}
    vs = e.videos_da_busca(dados)
    assert [v["titulo"] for v in vs] == ["Longo"]
    assert vs[0]["canal_id"] == "UC1" and vs[0]["views"] == 10000 and vs[0]["dias"] == 6


def test_perfil_do_about():
    html = ('..."subscriberCountText":"12,5 mil inscritos"..."joinedDateText":{"content":"Inscreveu-se em 3 de mar. de 2025"}'
            '..."viewCountText":"1.234.567 visualizações"..."country":"Brasil"...')
    p = e.perfil_do_about(html)
    assert p["inscritos"] == 12500 and p["ano"] == 2025 and p["pais"] == "Brasil"


def test_perfil_do_about_com_espaco_nao_separavel():
    # o YouTube devolve "55,5\xa0mil inscritos" e "5,21\xa0mi de inscritos"
    html = ('..."subscriberCountText":"55,5\xa0mil inscritos"..."joinedDateText":{"content":"Inscreveu-se em 3 de mar. de 2026"}'
            '..."viewCountText":"10 visualizações"..."country":"Brasil"...')
    assert e.perfil_do_about(html)["inscritos"] == 55500
    html2 = html.replace("55,5\xa0mil inscritos", "5,21\xa0mi de inscritos")
    assert e.perfil_do_about(html2)["inscritos"] == 5210000


def test_videos_do_canal_lockup():
    lista = [{"lockupViewModel": {"x": {"content": "Titulo A"}, "y": {"content": "1,5 mil visualizações"}, "z": {"content": "há 6 dias"}}}]
    vs = e.videos_do_canal(lista)
    assert vs and vs[0]["views"] == 1500 and vs[0]["dias"] == 6


def test_resumo_canal():
    vs = [{"views": v} for v in (100, 500, 900, 40000, 50000)]
    r = e.resumo_canal(vs)
    assert r["mediana"] == 900 and r["minimo"] == 100 and r["n"] == 5
    assert e.resumo_canal([])["n"] == 0


def test_classe_canal():
    assert e.classe_canal({"inscritos": 5_000_000, "ano": 2016}) == "grande"
    assert e.classe_canal({"inscritos": 60001, "ano": 2025}) == "grande"
    assert e.classe_canal({"inscritos": 9000, "ano": 2026}) == "pequeno_recente"
    assert e.classe_canal({"inscritos": 9000, "ano": 2019}) == "pequeno_antigo"
    assert e.classe_canal({"inscritos": None, "ano": 2019}) == "desconhecido"


def test_estatisticas_busca():
    busca = [
        {"consulta": "q1", "janela": "mes", "ok": True, "videos": [
            {"canal_id": "A", "views": 1000}, {"canal_id": "B", "views": 100}, {"canal_id": "B", "views": 100}]},
        {"consulta": "q2", "janela": "mes", "ok": True, "videos": []},
    ]
    canais = {"A": {"inscritos": 2_000_000, "ano": 2010}, "B": {"inscritos": 500, "ano": 2026}}
    est = e.estatisticas_busca(busca, canais)
    q1 = est["q1"]
    assert q1["videos"] == 3
    assert q1["pct_videos_grandes"] == pytest.approx(1 / 3)
    assert q1["pct_views_grandes"] == pytest.approx(1000 / 1200)
    assert est["q2"]["videos"] == 0 and est["q2"]["pct_videos_grandes"] is None
