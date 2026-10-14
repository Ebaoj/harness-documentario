import pytest

from scripts.estudo_amostra import escolher, normalizar_entrada, parse_views


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("1.5K", 1500),
        ("1,5 mil", 1500),
        ("1,2 mi", 1_200_000),
        ("1.2M", 1_200_000),
        ("523 views", 523),
        ("1,234 views", 1234),
        ("2.1K views", 2100),
        ("3 mi de visualizações", 3_000_000),
        (4200, 4200),
        (None, None),
        ("sem dado", None),
    ],
)
def test_parse_views(texto, esperado):
    assert parse_views(texto) == esperado


def test_normalizar_entrada_aceita_json_do_ytdlp_e_texto():
    a = normalizar_entrada({"id": "abc", "title": "T", "duration": 600, "view_count": 1000})
    assert a == {"id": "abc", "titulo": "T", "duracao_s": 600, "views": 1000}
    b = normalizar_entrada({"id": "x", "titulo": "U", "duracao_s": 700, "views": "1.5K"})
    assert b["views"] == 1500


def _v(i, views, dur=900, titulo="video"):
    return {"id": f"v{i}", "titulo": titulo, "duracao_s": dur, "views": views}


def test_escolhe_top_e_mediana_ou_abaixo():
    videos = [_v(i, 1000 * (i + 1)) for i in range(10)]  # 1K..10K, mediana 5.5K
    r = escolher(videos, n_melhores=2, n_base=2, min_views=0)
    melhores = [v["id"] for v in r if v["grupo"] == "melhores"]
    base = [v["id"] for v in r if v["grupo"] == "base"]
    assert melhores == ["v9", "v8"]
    assert len(base) == 2
    assert all(v["views"] <= 5500 for v in r if v["grupo"] == "base")
    assert "v4" in base  # o mais perto da mediana entra


def test_filtra_shorts_e_curtos():
    videos = [
        _v(0, 9_000_000, dur=45),
        _v(1, 8_000_000, dur=300),
        _v(2, 7_000_000, titulo="Algo #shorts"),
        _v(3, 6_000_000), _v(4, 5_000_000), _v(5, 4_000_000), _v(6, 3_000_000), _v(7, 2_000_000),
    ]
    ids = {v["id"] for v in escolher(videos, 2, 2, min_views=0)}
    assert not ids & {"v0", "v1", "v2"}


def test_ignora_views_ausentes_e_muito_novos():
    videos = [_v(0, None), _v(1, 6), _v(2, 5000), _v(3, 6000), _v(4, 7000), _v(5, 8000), _v(6, 9000)]
    ids = {v["id"] for v in escolher(videos, 2, 2, min_views=1000)}
    assert "v0" not in ids and "v1" not in ids


def test_canal_pequeno_nao_repete_video():
    videos = [_v(0, 1000), _v(1, 2000), _v(2, 3000)]
    r = escolher(videos, 2, 2, min_views=0)
    assert len({v["id"] for v in r}) == len(r) == 3
    assert {v["grupo"] for v in r} == {"melhores", "base"}


def test_video_com_exatamente_o_minimo_de_views_entra_e_o_de_baixo_nao():
    from scripts.estudo_amostra import MIN_VIEWS

    base = {"duracao_s": 900, "titulo": "t"}
    vs = [dict(base, id="a", views=MIN_VIEWS), dict(base, id="b", views=MIN_VIEWS - 1)]
    ids = {v["id"] for v in escolher(vs)}
    assert ids == {"a"}
