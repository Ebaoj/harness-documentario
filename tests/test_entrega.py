import json
import subprocess
import wave

import numpy as np
import pytest

from scripts import entrega, modelo

SR = 44100


def _video(p, dur, cor="blue"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={cor}:s=320x180:r=30:d={dur}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)], check=True)
    return p


def _wav(p, dur, freq=220.0, zeros_no_fim=0.0, amp=0.3):
    t = np.arange(int(SR * dur)) / SR
    x = amp * np.sin(2 * np.pi * freq * t)
    if zeros_no_fim:
        x[-int(SR * zeros_no_fim):] = 0
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return p


def _dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


@pytest.fixture
def partes(tmp_path):
    return [(_video(tmp_path / "a.mp4", 2.0), _wav(tmp_path / "a.wav", 2.0, 220)),
            (_video(tmp_path / "b.mp4", 3.0, "red"), _wav(tmp_path / "b.wav", 3.0, 330))]


def test_montar_junta_as_partes_e_normaliza_uma_vez(tmp_path, partes):
    rel = entrega.montar(partes, tmp_path / "final.mp4")
    assert abs(_dur(tmp_path / "final.mp4") - 5.0) < 0.05
    assert rel["emendas"] == [2.0]
    assert -16.5 < rel["lufs"] < -13.0


def test_faixa_mais_curta_que_o_video_reprova(tmp_path):
    """M28: a voz 80 ms mais curta zerou o fim da trilha na emenda."""
    p = [(_video(tmp_path / "a.mp4", 2.0), _wav(tmp_path / "a.wav", 1.92)),
         (_video(tmp_path / "b.mp4", 2.0), _wav(tmp_path / "b.wav", 2.0))]
    with pytest.raises(ValueError, match="M28.*duração"):
        entrega.montar(p, tmp_path / "x.mp4")


def test_silencio_digital_na_emenda_reprova(tmp_path):
    p = [(_video(tmp_path / "a.mp4", 2.0), _wav(tmp_path / "a.wav", 2.0, zeros_no_fim=0.08)),
         (_video(tmp_path / "b.mp4", 2.0), _wav(tmp_path / "b.wav", 2.0))]
    with pytest.raises(ValueError, match="M28.*silêncio"):
        entrega.montar(p, tmp_path / "x.mp4")


def test_silencio_medido_no_audio_cru():
    assert entrega.menor_nivel(np.zeros(SR), SR) < -100
    x = 0.3 * np.sin(2 * np.pi * 220 * np.arange(SR) / SR)
    assert entrega.menor_nivel(x, SR) > -20


def test_copia_para_whatsapp_fica_abaixo_do_limite(tmp_path):
    v = _video(tmp_path / "v.mp4", 20.0)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(v), "-i", str(_wav(tmp_path / "v.wav", 20.0)),
                    "-c:v", "copy", "-c:a", "aac", "-shortest", str(tmp_path / "va.mp4")], check=True)
    saida = entrega.whatsapp(tmp_path / "va.mp4", tmp_path / "w.mp4", limite_mb=2.0)
    assert saida.stat().st_size < 2.0 * 1024 * 1024
    assert abs(_dur(saida) - 20.0) < 0.1


def test_versionar_copia_e_nunca_sobrescreve(tmp_path, partes):
    v = partes[0][0]
    d = entrega.versionar(v, tmp_path / "versoes", "episodio-v1")
    assert d.name == "episodio-v1.mp4" and d.read_bytes() == v.read_bytes()
    with pytest.raises(FileExistsError):
        entrega.versionar(v, tmp_path / "versoes", "episodio-v1")


def test_limpar_apaga_so_intermediarios_e_copias_identicas(tmp_path, partes):
    saida, versoes = tmp_path / "07-saida", tmp_path / "versoes"
    saida.mkdir()
    (saida / "previa-001.00.png").write_bytes(b"x")
    (saida / "seg.parcial.mp4").write_bytes(b"x")
    dup = saida / "ep-v1.mp4"
    dup.write_bytes(partes[0][0].read_bytes())
    unico = saida / "ep-mudo.mp4"
    unico.write_bytes(partes[1][0].read_bytes())
    entrega.versionar(dup, versoes, "ep-v1")
    removidos = entrega.limpar(saida, versoes)
    assert sorted(p.name for p in removidos) == ["ep-v1.mp4", "previa-001.00.png", "seg.parcial.mp4"]
    assert unico.exists() and (versoes / "ep-v1.mp4").exists()


def test_abrir_usa_o_quicktime_no_ponto_pedido(monkeypatch, tmp_path):
    chamadas = []
    monkeypatch.setattr(entrega.subprocess, "run", lambda cmd, **k: chamadas.append(cmd))
    entrega.abrir(tmp_path / "v.mp4", inicio=92)
    (cmd,) = chamadas
    assert cmd[0] == "osascript" and "QuickTime Player" in cmd[2] and cmd[-1] == "92"


def test_regras_da_entrega_ficam_registradas_no_modelo():
    assert {"emenda_sem_silencio", "faixas_com_duracao_da_parte"} <= set(modelo.funcoes_registradas())


# --- correções da revisão da T20 ---------------------------------------------


def test_whatsapp_cabe_mesmo_num_video_longo(tmp_path):
    """Revisão T20: com 15 min a taxa cai abaixo do piso antigo e o arquivo estourava o limite."""
    v = tmp_path / "longo.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=1:d=900", "-f", "lavfi",
                    "-i", "sine=f=220:d=900", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(v)], check=True)
    saida = entrega.whatsapp(v, tmp_path / "w.mp4", limite_mb=15.5)
    assert saida.stat().st_size < 15.5 * 1024 * 1024
    assert not list(tmp_path.glob("*2pass*"))


def test_limpar_recusa_a_pasta_de_versoes_e_pasta_que_nao_e_saida(tmp_path, partes):
    versoes = tmp_path / "versoes"
    entrega.versionar(partes[0][0], versoes, "v1")
    with pytest.raises(ValueError):
        entrega.limpar(versoes, versoes)
    with pytest.raises(ValueError, match="07-saida"):
        entrega.limpar(tmp_path, versoes)
    assert (versoes / "v1.mp4").exists()


def test_abrir_passa_o_caminho_como_argumento(monkeypatch, tmp_path):
    chamadas = []
    monkeypatch.setattr(entrega.subprocess, "run", lambda cmd, **k: chamadas.append(cmd))
    perigoso = tmp_path / 'nome "com" aspas.mp4'
    entrega.abrir(perigoso, inicio=3)
    (cmd,) = chamadas
    assert str(perigoso.resolve()) == cmd[-2] and '"com"' not in cmd[2] and cmd[-1] == "3"


def test_audio_ajustado_a_duracao_exata_do_video_de_cada_parte(tmp_path):
    """Revisão T20: diferença de até 1 quadro por parte não pode se acumular."""
    p = [(_video(tmp_path / "a.mp4", 2.0), _wav(tmp_path / "a.wav", 2.02)),
         (_video(tmp_path / "b.mp4", 2.0), _wav(tmp_path / "b.wav", 2.02)),
         (_video(tmp_path / "c.mp4", 2.0), _wav(tmp_path / "c.wav", 2.02))]
    rel = entrega.montar(p, tmp_path / "x.mp4")
    assert rel["emendas"] == [2.0, 4.0]
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration",
                        "-of", "csv=p=0", str(tmp_path / "x.mp4")], capture_output=True, text=True, check=True)
    assert abs(float(r.stdout.strip().split(",")[0]) - 6.0) < 0.03


def test_wav_que_nao_e_16_bits_reprova(tmp_path):
    p24 = tmp_path / "a24.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=2", "-c:a", "pcm_s24le", str(p24)],
                   check=True)
    p = [(_video(tmp_path / "a.mp4", 2.0), p24), (_video(tmp_path / "b.mp4", 2.0), _wav(tmp_path / "b.wav", 2.0))]
    with pytest.raises(ValueError, match="16 bits"):
        entrega.montar(p, tmp_path / "x.mp4")


def test_silencio_em_qualquer_canal_conta(tmp_path):
    x = 0.3 * np.sin(2 * np.pi * 220 * np.arange(SR * 2) / SR)
    est = np.stack([x, x], 1)
    est[-int(SR * 0.08):, 1] = 0  # canal direito mudo no fim
    p = tmp_path / "e.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((est * 32767).astype("<i2").tobytes())
    partes = [(_video(tmp_path / "a.mp4", 2.0), p), (_video(tmp_path / "b.mp4", 2.0), _wav(tmp_path / "b.wav", 2.0))]
    with pytest.raises(ValueError, match="silêncio"):
        entrega.montar(partes, tmp_path / "x.mp4")


def test_silencio_declarado_no_roteiro_passa(tmp_path):
    p = [(_video(tmp_path / "a.mp4", 2.0), _wav(tmp_path / "a.wav", 2.0, zeros_no_fim=0.08)),
         (_video(tmp_path / "b.mp4", 2.0), _wav(tmp_path / "b.wav", 2.0))]
    entrega.montar(p, tmp_path / "x.mp4", silencios_permitidos=[1])


def test_abrir_espera_o_quicktime_carregar_arquivo_grande(monkeypatch, tmp_path):
    """Capítulo 3: com 900 MB, o 'open' voltou sem documento e o 'set current time' falhou."""
    scripts = []
    monkeypatch.setattr(entrega.subprocess, "run", lambda args, **k: scripts.append(args))
    entrega.abrir(tmp_path / "v.mp4", inicio=10)
    s = scripts[0][2]
    assert "repeat" in s and "missing value" in s


def test_script_do_quicktime_compila_e_acha_o_documento_pelo_caminho(tmp_path):
    """Revisão: 'd' podia ficar indefinido (erro -2753) e 'front document' podia tocar outro vídeo aberto."""
    import subprocess
    s = entrega.ABRIR
    assert "set d to missing value" in s and "front document" not in s and "POSIX path" in s
    r = subprocess.run(["osacompile", "-o", str(tmp_path / "a.scpt"), "-e", s], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --- montagem sem recomprimir (decisão de produto, 12/10/2026) -------------------


def _md5_video_copiado(*mp4s):
    """md5 dos quadros decodificados: recomprimir (x264 ou chip de vídeo, ambos com perda) muda os pixels."""
    import hashlib
    h = hashlib.md5()
    for m in mp4s:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(m), "-map", "0:v", "-f", "framemd5", "-"],
                           capture_output=True, text=True, check=True)
        h.update("".join(l.split(",")[-1] for l in r.stdout.splitlines() if not l.startswith("#")).encode())
    return h.hexdigest()


def _video_padrao(p, dur, cor):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={cor}:s=320x180:r=30:d={dur}",
                    *entrega.CODIFICADOR, "-r", str(entrega.FPS), "-metadata", f"comment={entrega.FORMATO}", str(p)],
                   check=True)
    return p


def test_partes_no_formato_padrao_tem_o_video_copiado_sem_recomprimir(tmp_path):
    a = _video_padrao(tmp_path / "a.mp4", 2.0, "blue")
    b = _video_padrao(tmp_path / "b.mp4", 3.0, "red")
    partes = [(a, _wav(tmp_path / "a.wav", 2.0, 220)), (b, _wav(tmp_path / "b.wav", 3.0, 330))]
    rel = entrega.montar(partes, tmp_path / "f.mp4")
    assert _md5_video_copiado(tmp_path / "f.mp4") == _md5_video_copiado(a, b)
    assert rel["emendas"] == [pytest.approx(2.0, abs=0.04)]
    assert abs(_dur(tmp_path / "f.mp4") - 5.0) < 0.06


def test_parte_fora_do_formato_e_convertida_uma_vez_e_fica_no_cache(tmp_path, partes):
    entrega.montar(partes, tmp_path / "saida" / "f1.mp4")
    cache = tmp_path / "saida" / ".cache-montagem"
    feitos = {p.name: p.stat().st_mtime_ns for p in cache.glob("*.mp4")}
    assert len(feitos) == 2
    entrega.montar(partes, tmp_path / "saida" / "f2.mp4")
    assert {p.name: p.stat().st_mtime_ns for p in cache.glob("*.mp4")} == feitos
    assert abs(_dur(tmp_path / "saida" / "f2.mp4") - 5.0) < 0.06


def _video_renderizado_antigo(p, dur, cor):
    """Como o render saía antes: JPEG na entrada (faixa cheia, yuvj) e a etiqueta do formato no comentário."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={cor}:s=320x180:r=30:d={dur}",
                    "-c:v", "mjpeg", "-f", "mjpeg", str(p) + ".mjpeg"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-c:v", "mjpeg", "-i", str(p) + ".mjpeg",
                    "-c:v", "h264_videotoolbox", "-b:v", "20M", "-bf", "0", "-pix_fmt", "yuv420p",
                    "-metadata", f"comment={entrega.FORMATO}", str(p)], check=True)
    return p


def _stream(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,color_range", "-of", "json", str(mp4)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["streams"][0]


def test_parte_em_outra_faixa_de_cor_nao_e_copiada_junto(tmp_path):
    """Revisão: o concat por cópia usa o cabeçalho do primeiro arquivo; faixa cheia e limitada juntas
    mudavam o contraste da segunda parte (diferença média de 15 por canal)."""
    a = _video_renderizado_antigo(tmp_path / "a.mp4", 2.0, "blue")
    b = _video_padrao(tmp_path / "b.mp4", 2.0, "red")
    entrega.montar([(a, _wav(tmp_path / "a.wav", 2.0)), (b, _wav(tmp_path / "b.wav", 2.0, 330))], tmp_path / "s" / "f.mp4")
    assert _stream(tmp_path / "s" / "f.mp4")["color_range"] == "tv"
    assert len(list((tmp_path / "s" / ".cache-montagem").glob("*.mp4"))) == 1  # só a parte fora do padrão


def test_parte_com_outra_resolucao_e_fps_e_normalizada(tmp_path):
    """Revisão: 720p25 emendado por cópia em 1080p30 encurtava o vídeo (3,33 s em vez de 4) sem erro."""
    a = _video_padrao(tmp_path / "a.mp4", 2.0, "blue")
    b = tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=1280x720:r=25:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(b)], check=True)
    entrega.montar([(a, _wav(tmp_path / "a.wav", 2.0)), (b, _wav(tmp_path / "b.wav", 2.0, 330))], tmp_path / "f.mp4")
    s = _stream(tmp_path / "f.mp4")
    assert (s["width"], s["height"], s["r_frame_rate"]) == (entrega.LARGURA, entrega.ALTURA, f"{entrega.FPS}/1")
    assert abs(_dur(tmp_path / "f.mp4") - 4.0) < 0.06


def test_etiqueta_copiada_por_outro_programa_nao_basta(tmp_path):
    """Revisão: o ffmpeg copia o comentário; um vídeo recomprimido com B-frames não pode passar por padrão."""
    a = _video_padrao(tmp_path / "a.mp4", 2.0, "blue")
    b = tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(_video_padrao(tmp_path / "x.mp4", 2.0, "red")),
                    "-c:v", "libx264", "-bf", "2", "-pix_fmt", "yuv420p", str(b)], check=True)
    assert entrega._formato(b) == entrega.FORMATO  # a etiqueta veio junto
    entrega.montar([(a, _wav(tmp_path / "a.wav", 2.0)), (b, _wav(tmp_path / "b.wav", 2.0, 330))], tmp_path / "s" / "f.mp4")
    assert len(list((tmp_path / "s" / ".cache-montagem").glob("*.mp4"))) == 1


def test_whatsapp_partes_divide_nas_emendas_quando_a_taxa_ficaria_ilegivel(tmp_path):
    """Episódio real: 26 min em 15 MB davam 30 kb/s de vídeo e a cópia única falhava. Divide nos capítulos."""
    v = tmp_path / "longo.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=10:d=60", "-f", "lavfi",
                    "-i", "sine=f=220:d=60", "-c:v", "libx264", "-g", "10", "-c:a", "aac", "-shortest", str(v)], check=True)
    # 1 MB para 60 s dá cerca de 125 kb/s; com piso de 250 kb/s cabe no máximo ~30 s por parte
    saidas = entrega.whatsapp_partes(v, tmp_path / "w.mp4", limite_mb=1.0, cortes=[18.0, 25.0, 41.0], taxa_min_kbps=250)
    assert [p.name for p in saidas] == ["w-parte1.mp4", "w-parte2.mp4", "w-parte3.mp4"]
    durs = [_dur(p) for p in saidas]
    assert abs(sum(durs) - 60.0) < 0.5
    # usa a maior emenda que cabe: 25 s, depois 41 s
    assert abs(durs[0] - 25.0) < 0.3 and abs(durs[1] - 16.0) < 0.3
    assert all(p.stat().st_size < 1.0 * 1024 * 1024 for p in saidas)


def test_whatsapp_partes_mantem_um_arquivo_quando_cabe(tmp_path):
    v = _video(tmp_path / "v.mp4", 10.0)
    saidas = entrega.whatsapp_partes(v, tmp_path / "w.mp4", limite_mb=2.0, cortes=[5.0])
    assert [p.name for p in saidas] == ["w.mp4"]


def test_whatsapp_partes_sem_emenda_que_caiba_corta_no_tamanho_maximo(tmp_path):
    v = _video(tmp_path / "v.mp4", 40.0)
    saidas = entrega.whatsapp_partes(v, tmp_path / "w.mp4", limite_mb=0.5, cortes=[], taxa_min_kbps=250)
    assert len(saidas) >= 2 and abs(sum(_dur(p) for p in saidas) - 40.0) < 0.5


def test_whatsapp_partes_sem_emenda_divide_em_partes_iguais(tmp_path):
    """Revisão: cortar no tamanho máximo deixava a última parte com décimos de segundo."""
    v = _video(tmp_path / "v.mp4", 30.0)
    # 0,4925 MB a 250 kb/s cabe 14,85 s; 30 s pedem 3 partes de 10 s, não 14,85 + 14,85 + 0,3
    saidas = entrega.whatsapp_partes(v, tmp_path / "w.mp4", limite_mb=0.4925, cortes=[], taxa_min_kbps=250)
    durs = [_dur(p) for p in saidas]
    assert max(durs) - min(durs) < 0.5 and abs(sum(durs) - 30.0) < 0.5
