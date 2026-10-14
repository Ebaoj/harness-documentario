import json
import subprocess

import pytest
from PIL import Image

from scripts import cenas, render
from tests.test_cenas import ESTILO, episodio  # noqa: F401  (fixture do episódio mínimo)

FPS = 10


def _plano_curto():
    c = lambda i, a, b, comp, **k: {"id": i, "ini": a, "fim": b, "componente": comp, **k}
    return {"dur": 3.0, "vozes": [{"fonte": "voz", "em": 1.0, "legendas": [[1.0, 1.8, "Uma legenda."]]}],
            "cenas": [c("A", 0, 1, "foto", fonte="foto-a"),
                      c("B", 1, 2, "retrato", fonte="foto-b", params={"legenda": "Pessoa"}),
                      c("C", 2, 3, "arquivo", fonte="rua", clipe={"de": 10.0, "velocidade": 1.0}, params={"rotulo": "UM LUGAR"})]}


def _gerar(ep, plano):
    return cenas.gerar(ep, plano, ESTILO, ep / "04-cenas" / "parte.html")


def _quadros(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_read_frames", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True, check=True)
    return int(r.stdout.strip().split(",")[0])


def _md5_quadros(mp4):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "framemd5", "-"], capture_output=True, text=True, check=True)
    return [l.split(",")[-1].strip() for l in r.stdout.splitlines() if not l.startswith("#")]


def test_renderiza_o_numero_exato_de_quadros(episodio):
    html = _gerar(episodio, _plano_curto())
    rel = render.renderizar(html, episodio / "saida.mp4", fps=FPS, cache=episodio / "cache")
    assert _quadros(episodio / "saida.mp4") == 30
    assert sorted(rel["renderizadas"]) == ["A", "B", "C"] and rel["do_cache"] == []


def test_segunda_vez_vem_toda_do_cache(episodio):
    html = _gerar(episodio, _plano_curto())
    render.renderizar(html, episodio / "a.mp4", fps=FPS, cache=episodio / "cache")
    rel = render.renderizar(html, episodio / "b.mp4", fps=FPS, cache=episodio / "cache")
    assert rel["renderizadas"] == [] and sorted(rel["do_cache"]) == ["A", "B", "C"]


def test_dois_renders_com_cache_vazio_saem_iguais_quadro_a_quadro(episodio):
    """Revisão T19: o determinismo só é provado renderizando de novo, sem cache."""
    html = _gerar(episodio, _plano_curto())
    render.renderizar(html, episodio / "a.mp4", fps=FPS, cache=episodio / "cache1")
    render.renderizar(html, episodio / "b.mp4", fps=FPS, cache=episodio / "cache2")
    assert _md5_quadros(episodio / "a.mp4") == _md5_quadros(episodio / "b.mp4")


def _duracao(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                        "-of", "csv=p=0", str(mp4)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip().split(",")[0])


def test_duracao_bate_com_os_quadros_e_borda_fora_da_grade_vai_para_a_cena_certa(episodio):
    """Revisão T19: cena começando em 1,04 s a 10 fps; o quadro de 1,0 s é da cena A, o de 1,1 s da B."""
    p = _plano_curto()
    p["cenas"][0]["fim"] = p["cenas"][1]["ini"] = 1.04
    html = _gerar(episodio, p)
    rel = render.renderizar(html, episodio / "a.mp4", fps=FPS, cache=episodio / "cache")
    assert rel["quadros"] == 30 and _quadros(episodio / "a.mp4") == 30
    assert abs(_duracao(episodio / "a.mp4") - 3.0) < 1e-3
    assert render.quadros_da_cena({"ini": 0, "fim": 1.04}, FPS) == (0, 11)
    assert render.quadros_da_cena({"ini": 1.04, "fim": 2}, FPS) == (11, 20)


def test_mudar_a_cena_anterior_nao_afeta_o_cache_da_seguinte_quando_nada_dela_aparece_la(episodio):
    p = _plano_curto()
    p["cenas"][0]["fim"] = p["cenas"][1]["ini"] = 1.04
    render.renderizar(_gerar(episodio, p), episodio / "a.mp4", fps=FPS, cache=episodio / "cache")
    p["cenas"][0]["params"] = {"z0": 1.3}
    rel = render.renderizar(_gerar(episodio, p), episodio / "b.mp4", fps=FPS, cache=episodio / "cache")
    assert rel["renderizadas"] == ["A"]


def test_render_so_das_cenas_pedidas(episodio):
    html = _gerar(episodio, _plano_curto())
    rel = render.renderizar(html, episodio / "so-b.mp4", fps=FPS, cache=episodio / "cache", cenas=["B"])
    assert rel["renderizadas"] == ["B"] and _quadros(episodio / "so-b.mp4") == 10


def test_falha_no_meio_nao_deixa_lixo_no_cache(episodio, monkeypatch):
    html = _gerar(episodio, _plano_curto())
    chamadas = {"n": 0}
    original = render._quadro

    def quebra(pg, t):
        chamadas["n"] += 1
        if chamadas["n"] == 5:
            raise RuntimeError("navegador caiu")
        return original(pg, t)

    monkeypatch.setattr(render, "_quadro", quebra)
    with pytest.raises(RuntimeError, match="caiu"):
        render.renderizar(html, episodio / "x.mp4", fps=FPS, cache=episodio / "cache")
    sobras = [f.name for f in (episodio / "cache").iterdir()]
    assert not [n for n in sobras if "parcial" in n or n.startswith("lista")], sobras


def test_mudar_uma_cena_renderiza_so_ela(episodio):
    render.renderizar(_gerar(episodio, _plano_curto()), episodio / "a.mp4", fps=FPS, cache=episodio / "cache")
    p = _plano_curto()
    p["cenas"][1]["params"]["legenda"] = "Outra pessoa"
    rel = render.renderizar(_gerar(episodio, p), episodio / "b.mp4", fps=FPS, cache=episodio / "cache")
    assert rel["renderizadas"] == ["B"]


def test_trocar_a_foto_no_disco_renderiza_a_cena_que_usa_ela(episodio):
    render.renderizar(_gerar(episodio, _plano_curto()), episodio / "a.mp4", fps=FPS, cache=episodio / "cache")
    Image.new("RGB", (300, 380), (10, 200, 10)).save(episodio / "03-assets" / "a.jpg")
    rel = render.renderizar(_gerar(episodio, _plano_curto()), episodio / "b.mp4", fps=FPS, cache=episodio / "cache")
    assert rel["renderizadas"] == ["A"]


def test_mudar_legenda_renderiza_so_a_cena_onde_ela_aparece(episodio):
    render.renderizar(_gerar(episodio, _plano_curto()), episodio / "a.mp4", fps=FPS, cache=episodio / "cache")
    p = _plano_curto()
    p["vozes"][0]["legendas"][0][2] = "Outra legenda."
    rel = render.renderizar(_gerar(episodio, p), episodio / "b.mp4", fps=FPS, cache=episodio / "cache")
    assert rel["renderizadas"] == ["B"]


def test_previa_salva_png_nos_instantes_pedidos(episodio):
    html = _gerar(episodio, _plano_curto())
    arqs = render.previa(html, [0.5, 2.5], episodio / "previa")
    assert [a.name for a in arqs] == ["previa-000.50.png", "previa-002.50.png"]
    assert all(a.stat().st_size > 0 for a in arqs)


def test_html_sem_pronto_falha_com_mensagem(tmp_path):
    h = tmp_path / "x.html"
    h.write_text("<html><body>sem render</body></html>")
    with pytest.raises(RuntimeError, match="pronto"):
        render.renderizar(h, tmp_path / "x.mp4", fps=FPS, cache=tmp_path / "c", espera_ms=1500)


# --- correções da prancha do capítulo 3 --------------------------------------


def test_lista_com_documento_deitado_nao_invade_os_itens(episodio):
    """Capítulo 3: a manchete deitada esticou o cartão da lista por cima dos nomes."""
    Image.new("RGB", (1600, 900), (255, 255, 255)).save(episodio / "03-assets" / "doc.jpg")
    c = {"id": "L", "ini": 0, "fim": 2, "componente": "lista", "fonte": "doc",
         "params": {"titulo": "NOMES", "largura_max": 760, "itens": [{"texto": "UM", "em": 0.1}]}}
    png, = render.previa(_gerar(episodio, {"dur": 2.0, "cenas": [c]}), [1.5], episodio / "pv")
    im = Image.open(png).convert("L")
    faixa = [im.getpixel((x, 540)) for x in range(1100, 1115)]  # coluna logo antes dos itens (left 1120)
    assert max(faixa) < 120, faixa


def test_rotulo_de_voz_pode_descer_para_nao_pisar_no_credito(episodio):
    c = {"id": "C", "ini": 0, "fim": 2, "componente": "arquivo", "fonte": "rua", "clipe": {"de": 10.0, "velocidade": 1.0},
         "params": {"voz_rotulo": {"texto": "A VOZ", "cor": "vermelho", "top": 1000}}}
    html = _gerar(episodio, {"dur": 2.0, "cenas": [c]})
    png, = render.previa(html, [1.0], episodio / "pv")
    im = Image.open(png).convert("RGB")
    vermelho = lambda y0, y1: sum(1 for x in range(120, 260) for y in range(y0, y1)
                                  if (lambda r, g, b: r > 60 and r > 2.5 * g)(*im.getpixel((x, y))))
    assert vermelho(95, 125) == 0 and vermelho(995, 1030) > 0


def test_lista_com_largura_maxima_amplia_imagem_pequena(episodio):
    """Revisão: com max-width/max-height, uma imagem pequena não crescia e o cartão ficava minúsculo."""
    Image.new("RGB", (200, 100), (128, 128, 128)).save(episodio / "03-assets" / "doc.jpg")
    c = {"id": "L", "ini": 0, "fim": 2, "componente": "lista", "fonte": "doc",
         "params": {"titulo": "NOMES", "largura_max": 760, "itens": [{"texto": "UM", "em": 0.1}]}}
    png, = render.previa(_gerar(episodio, {"dur": 2.0, "cenas": [c]}), [1.5], episodio / "pv")
    im = Image.open(png).convert("L")
    assert im.getpixel((330, 540)) > 70  # a 300 px do centro do cartão ainda é imagem


def _info(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,has_b_frames,pix_fmt:format_tags=comment", "-of", "json", str(mp4)],
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    return {**d["streams"][0], "comment": d.get("format", {}).get("tags", {}).get("comment")}


def test_render_sai_no_formato_padrao_do_harness_pelo_chip_de_video(episodio, monkeypatch):
    """Decisão de produto (12/10/2026): comprimir pelo chip de vídeo do M1 em vez do x264 na CPU."""
    chamadas = []
    original = subprocess.Popen

    def espia(args, *a, **k):
        chamadas.append(args)
        return original(args, *a, **k)

    monkeypatch.setattr(render.subprocess, "Popen", espia)
    render.renderizar(_gerar(episodio, _plano_curto()), episodio / "a.mp4", fps=FPS, cache=episodio / "cache")
    codificacoes = [c for c in chamadas if isinstance(c, list) and c[0] == "ffmpeg" and "image2pipe" in c]
    assert codificacoes and all("h264_videotoolbox" in c and "libx264" not in c for c in codificacoes)
    i = _info(episodio / "a.mp4")
    assert i["codec_name"] == "h264" and i["has_b_frames"] == 0 and i["comment"] == render.FORMATO
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt,color_range",
                        "-of", "json", str(episodio / "a.mp4")], capture_output=True, text=True, check=True)
    st = json.loads(r.stdout)["streams"][0]
    # entrada JPEG é faixa cheia: o render tem de sair em faixa limitada, senão a emenda por cópia muda o contraste
    assert st["pix_fmt"] == "yuv420p" and st.get("color_range", "unknown") in ("tv", "unknown")


def test_chamada_de_encerramento_mostra_botao_like_e_proximo_episodio(episodio):
    """Decisão de produto (12/10/2026): CTA de like e inscrição no fim, com o gancho do próximo episódio.
    Nada do texto mora no código (R14): vem do plano."""
    c = {"id": "F", "ini": 0, "fim": 6, "componente": "chamada",
         "params": {"botao": "INSCREVER-SE", "clique": 1.0, "like": 1.8,
                    "proximo": {"em": 3.0, "rotulo": "NO PRÓXIMO EPISÓDIO", "titulo": "UM TÍTULO QUALQUER"}}}
    html = _gerar(episodio, {"dur": 6.0, "cenas": [c]})
    assert "UM TÍTULO QUALQUER" in html.read_text() and "INSCREVER-SE" in html.read_text()
    antes, depois, fim = render.previa(html, [0.6, 1.5, 4.5], episodio / "pv")
    a, d = Image.open(antes).convert("RGB"), Image.open(depois).convert("RGB")
    # o botão muda de cor quando é "clicado" (vermelho -> apagado com o texto INSCRITO)
    assert a.getpixel((960, 540)) != d.getpixel((960, 540))
    assert Image.open(fim).convert("L").getbbox() is not None


def test_chamada_e_componente_conhecido():
    from scripts import cenas as cn
    assert "chamada" in cn.COMPONENTES


def test_chamada_sem_botao_deixa_a_tela_limpa_para_a_tela_final(episodio):
    c = {"id": "F", "ini": 0, "fim": 3, "componente": "chamada", "params": {}}
    html = _gerar(episodio, {"dur": 3.0, "cenas": [c]})
    png, = render.previa(html, [2.0], episodio / "pv")
    im = Image.open(png).convert("RGB")
    assert all(max(im.getpixel((x, y))) < 120 for x, y in [(960, 540), (1300, 540), (1440, 540), (1630, 540)])
