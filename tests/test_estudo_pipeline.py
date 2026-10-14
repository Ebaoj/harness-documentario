import json

from scripts import estudo_pipeline as pl


def test_canais_carregados_do_json(tmp_path):
    (tmp_path / "canais.json").write_text(json.dumps({"canais": [{"slug": "a", "id": "UC1", "idioma": "hi"}]}))
    assert pl.carregar_canais(tmp_path)[0]["idioma"] == "hi"


def test_amostrar_grava_amostra_json_a_partir_da_lista(tmp_path):
    (tmp_path / "a").mkdir()
    lista = [{"id": f"v{i}", "title": "t", "duration": 900, "view_count": 2000 * (i + 1)} for i in range(8)]
    (tmp_path / "a" / "lista.json").write_text(json.dumps(lista))
    r = pl.amostrar(tmp_path, {"slug": "a"})
    assert len(r) == 4
    assert json.loads((tmp_path / "a" / "amostra.json").read_text()) == r


def test_baixar_todos_respeita_limite_de_tres_em_paralelo(tmp_path):
    import threading, time
    ativos, pico, trava = [0], [0], threading.Lock()

    def falso(vid, destino, idioma, recorte_s=None):
        with trava:
            ativos[0] += 1
            pico[0] = max(pico[0], ativos[0])
        time.sleep(0.05)
        with trava:
            ativos[0] -= 1
        return {"video_id": vid, "status": "ok"}

    tarefas = [("c", {"id": f"v{i}"}, "en") for i in range(9)]
    r = pl.baixar_todos(tmp_path, tarefas, baixar=falso)
    assert len(r) == 9 and pico[0] <= 3


def test_video_longo_vai_com_recorte(tmp_path):
    vistos = {}

    def falso(vid, destino, idioma, recorte_s=None):
        vistos[vid] = recorte_s
        return {"video_id": vid, "status": "ok"}

    pl.baixar_todos(tmp_path, [("c", {"id": "curto", "duracao_s": 900}, "en"),
                               ("c", {"id": "longo", "duracao_s": 10000}, "en")], baixar=falso)
    assert vistos == {"curto": None, "longo": pl.RECORTE_S}
