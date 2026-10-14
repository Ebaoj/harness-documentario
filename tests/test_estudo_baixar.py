import json

from scripts import estudo_baixar as b


def test_comando_usa_ytdlp_da_venv_baixa_resolucao_e_legenda_no_idioma(tmp_path):
    cmd = b.montar_comando("abc123", tmp_path, "hi")
    from pathlib import Path

    esperado = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "yt-dlp"
    assert cmd[0] == str(esperado)  # o yt-dlp da venv deste repo, qualquer que seja o nome da pasta
    junto = " ".join(cmd)
    assert "height<=360" in junto
    assert "--write-subs" in cmd and "--write-auto-subs" in cmd
    assert "hi" in cmd[cmd.index("--sub-langs") + 1]
    assert cmd[-1].endswith("watch?v=abc123")
    assert str(tmp_path) in junto


def test_sem_legenda_registra_sem_transcricao_e_segue(tmp_path):
    def runner(cmd):
        (tmp_path / "abc.mp4").write_bytes(b"x")
        return 0, ""

    r = b.baixar_video("abc", tmp_path, "en", runner=runner)
    assert r["status"] == "sem_transcricao"
    assert r["video"] == "abc.mp4"
    assert json.loads((tmp_path / "status.json").read_text())["status"] == "sem_transcricao"


def test_com_legenda_ok(tmp_path):
    def runner(cmd):
        (tmp_path / "abc.mp4").write_bytes(b"x")
        (tmp_path / "abc.hi.json3").write_text("{}")
        return 0, ""

    r = b.baixar_video("abc", tmp_path, "hi", runner=runner)
    assert r["status"] == "ok" and r["legenda"] == "abc.hi.json3"


def test_falha_do_ytdlp_vira_erro_registrado_sem_excecao(tmp_path):
    r = b.baixar_video("abc", tmp_path, "en", runner=lambda cmd: (1, "HTTP Error 403"))
    assert r["status"] == "erro" and "403" in r["erro"]


def test_pasta_de_midia_fica_sob_referencias_canal_id(tmp_path):
    p = b.pasta_midia(tmp_path, "meu-canal", "abc")
    assert p == tmp_path / "meu-canal" / "abc" / "midia"


def test_legenda_com_falha_temporaria_mantem_o_video_e_registra_o_motivo(tmp_path):
    def runner(cmd):
        (tmp_path / "abc.mp4").write_bytes(b"x")
        return 1, "ERROR: Unable to download video subtitles for 'en': HTTP Error 429"

    assert "--ignore-errors" in b.montar_comando("abc", tmp_path, "en")
    r = b.baixar_video("abc", tmp_path, "en", runner=runner)
    assert r["status"] == "sem_transcricao" and "429" in r["motivo"] and r["video"] == "abc.mp4"


def test_video_muito_longo_baixa_so_o_comeco():
    cmd = b.montar_comando("abc", "/x", "en", recorte_s=1500)
    assert cmd[cmd.index("--download-sections") + 1] == "*0-1500"
    assert "--download-sections" not in b.montar_comando("abc", "/x", "en")


def test_status_registra_o_recorte(tmp_path):
    def runner(cmd):
        (tmp_path / "abc.mp4").write_bytes(b"x")
        (tmp_path / "abc.en.json3").write_text("{}")
        return 0, ""

    assert b.baixar_video("abc", tmp_path, "en", runner=runner, recorte_s=1500)["recorte_s"] == 1500
