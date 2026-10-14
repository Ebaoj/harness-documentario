from scripts import preflight


def test_checar_devolve_lista_com_nome_e_ok():
    resultados = preflight.checar()
    assert resultados
    for r in resultados:
        assert set(r) >= {"nome", "ok", "detalhe"}
    nomes = {r["nome"] for r in resultados}
    assert {"ffmpeg", "ffprobe"} <= nomes


def test_checar_acusa_binario_ausente(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda n: None)
    resultados = {r["nome"]: r["ok"] for r in preflight.checar()}
    assert resultados["ffmpeg"] is False
    assert resultados["ffprobe"] is False


def _por_nome(prefixo):
    return next(r for r in preflight.checar() if r["nome"].startswith(prefixo))


def test_ytdlp_ausente_reprova(monkeypatch):
    monkeypatch.setattr(preflight, "_versao_ytdlp", lambda: None)
    assert _por_nome("yt-dlp")["ok"] is False


def test_ytdlp_antigo_reprova(monkeypatch):
    monkeypatch.setattr(preflight, "_versao_ytdlp", lambda: "2026.03.01")
    assert _por_nome("yt-dlp")["ok"] is False


def test_ytdlp_no_minimo_ou_acima_passa(monkeypatch):
    monkeypatch.setattr(preflight, "_versao_ytdlp", lambda: preflight.YTDLP_MINIMO)
    assert _por_nome("yt-dlp")["ok"] is True
    monkeypatch.setattr(preflight, "_versao_ytdlp", lambda: "2027.01.02")
    assert _por_nome("yt-dlp")["ok"] is True


def test_python_fora_do_312_reprova(monkeypatch):
    monkeypatch.setattr(preflight, "_versao_python", lambda: (3, 14, 0))
    assert _por_nome("python")["ok"] is False


def test_fora_da_venv_reprova(monkeypatch):
    monkeypatch.setattr(preflight, "_na_venv", lambda: False)
    assert _por_nome("venv")["ok"] is False


def test_modelo_do_canal_com_feedback_aberto_reprova(monkeypatch, tmp_path):
    from scripts import modelo

    canal = tmp_path / "canal-x" / "modelo"
    modelo.criar(canal)
    modelo.registrar_feedback(canal, "a cena não faz sentido")
    monkeypatch.setattr(modelo, "RAIZ_CANAIS", tmp_path)
    r = _por_nome("modelo canal-x")
    assert r["ok"] is False
    assert "F001" in r["detalhe"]


def test_modelo_do_canal_valido_passa(monkeypatch, tmp_path):
    from scripts import modelo

    modelo.criar(tmp_path / "canal-y" / "modelo")
    monkeypatch.setattr(modelo, "RAIZ_CANAIS", tmp_path)
    assert _por_nome("modelo canal-y")["ok"] is True


def test_navegador_do_playwright_ausente_reprova(monkeypatch):
    monkeypatch.setattr(preflight, "_chromium", lambda: None)
    assert _por_nome("chromium")["ok"] is False


def test_transcritor_e_modelo_sao_conferidos(monkeypatch):
    nomes = {r["nome"] for r in preflight.checar()}
    assert "whisper-cli" in nomes and any(n.startswith("modelo whisper") for n in nomes)


def test_gasto_sem_aprovacao_em_algum_episodio_reprova(monkeypatch, tmp_path):
    ep = tmp_path / "ep"
    ep.mkdir()
    (ep / "00-custos.jsonl").write_text('{"servico": "elevenlabs", "creditos": 5}\n')
    monkeypatch.setattr(preflight, "RAIZ_VIDEOS", tmp_path)
    r = _por_nome("custos")
    assert r["ok"] is False and "M24" in r["detalhe"]
