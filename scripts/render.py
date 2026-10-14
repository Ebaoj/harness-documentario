"""Renderizador único (T19): HTML de uma parte (scripts/cenas.py) -> MP4 mudo, quadro a quadro.

Tempo virtual (window.render(T)), rede bloqueada no navegador, espera cada imagem decodificar antes da foto
do quadro. Cada cena vira um segmento em cache, identificado por uma impressão digital do que muda a sua
imagem: a cena, o estilo, a biblioteca, a guia de capítulos, as legendas que aparecem nela e os bytes das
fotos e quadros de clipe que ela usa. Trocou uma cena: só ela renderiza de novo.
"""
import hashlib
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # rodado como `python scripts/render.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.cenas import _fontes_da_cena  # noqa: E402
from scripts.formato import CODIFICADOR, FORMATO  # noqa: E402

LARGURA, ALTURA = 1920, 1080
QUALIDADE_JPEG = 95
ESPERA_IMAGENS = ("Promise.all([...document.images].map(i => i.complete ? (i.decode ? i.decode().catch(() => 0) : 0)"
                  " : new Promise(r => { i.onload = i.onerror = r })))")
_DADOS = re.compile(r"window\.DADOS=(\{.*?\});\n", re.S)


def _ler(html):
    texto = Path(html).read_text(encoding="utf-8")
    m = _DADOS.search(texto)
    if not m:
        raise ValueError(f"{html}: não é um HTML gerado por scripts/cenas.py (sem window.DADOS)")
    return texto, json.loads(m.group(1)), texto.replace(m.group(1), "")


def _hash_arquivo(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else "ausente"


def quadros_da_cena(c, fps):
    """Quadros [q0, q1) cujo instante i/fps cai dentro da cena: é a cena que render(i/fps) desenha."""
    return math.ceil(c["ini"] * fps - 1e-9), math.ceil(c["fim"] * fps - 1e-9)


def _impressao(c, dados, molde, base, fps):
    """O que muda a imagem desta cena, e nada além disso."""
    arquivos = {}
    for i in _fontes_da_cena(c):
        rel = dados["recursos"].get(i)
        if rel:
            arquivos[rel] = _hash_arquivo(base / rel)
    if c.get("clip"):
        d = base / c["clip"]["dir"]
        arquivos[c["clip"]["dir"]] = hashlib.sha256(
            "".join(_hash_arquivo(f) for f in sorted(d.glob("f*.jpg"))).encode()).hexdigest()
    q0, q1 = quadros_da_cena(c, fps)
    a, b = q0 / fps, q1 / fps  # instantes reais dos quadros desta cena
    legendas = [it for v in dados.get("vozes") or [] for it in v.get("legendas") or [] if it[0] < b and it[1] > a]
    chave = {"cena": c, "estilo": dados["estilo"], "molde": hashlib.sha256(molde.encode()).hexdigest(),
             "capitulos": dados.get("capitulos"), "legendas": legendas, "arquivos": arquivos, "fps": fps,
             "tela": [LARGURA, ALTURA, QUALIDADE_JPEG, FORMATO], "quadros": [q0, q1]}
    return hashlib.sha256(json.dumps(chave, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def _abrir(pw, html, espera_ms):
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": LARGURA, "height": ALTURA})
    pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
    pg.goto(Path(html).resolve().as_uri())
    try:
        pg.wait_for_function("window.pronto === true", timeout=espera_ms)
    except Exception as e:
        b.close()
        raise RuntimeError(f"{html}: a página não ficou pronta (window.pronto) em {espera_ms} ms") from e
    return b, pg


def _quadro(pg, t):
    pg.evaluate(f"window.render({t!r})")
    pg.evaluate(ESPERA_IMAGENS)


def _segmento(pg, q0, q1, fps, saida):
    tmp = saida.with_suffix(".parcial.mp4")
    # sem B-frames: os segmentos emendam por cópia com a duração exata (quadros / fps)
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg",
                           "-i", "-", *CODIFICADOR, "-r", str(fps), str(tmp)], stdin=subprocess.PIPE)
    try:
        for i in range(q0, q1):
            _quadro(pg, i / fps)
            ff.stdin.write(pg.screenshot(type="jpeg", quality=QUALIDADE_JPEG))
        ff.stdin.close()
        if ff.wait():
            raise RuntimeError(f"ffmpeg falhou no segmento {saida.name}")
        tmp.rename(saida)
    except BaseException:
        ff.kill()
        ff.wait()
        tmp.unlink(missing_ok=True)
        raise


def renderizar(html, saida, fps=30, cache=None, espera_ms=60000, log=print, cenas=None):
    """Renderiza a parte inteira, ou só as cenas pedidas (para revisar um trecho)."""
    html, saida = Path(html), Path(saida)
    cache = Path(cache) if cache else saida.parent / ".cache-render"
    cache.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b, pg = _abrir(pw, html, espera_ms)
        try:
            _, dados, molde = _ler(html)
            base = html.parent
            rel = {"renderizadas": [], "do_cache": [], "quadros": 0}
            segmentos, t0 = [], time.time()
            pedidas = set(cenas or [])
            desconhecidas = pedidas - {c["id"] for c in dados["cenas"]}
            if desconhecidas:
                raise ValueError(f"cenas que não estão no plano: {sorted(desconhecidas)}")
            for c in dados["cenas"]:
                if pedidas and c["id"] not in pedidas:
                    continue
                q0, q1 = quadros_da_cena(c, fps)
                if q1 <= q0:
                    continue
                seg = cache / f"{_impressao(c, dados, molde, base, fps)}.mp4"
                if seg.exists():
                    rel["do_cache"].append(c["id"])
                else:
                    _segmento(pg, q0, q1, fps, seg)
                    rel["renderizadas"].append(c["id"])
                    log(f"cena {c['id']}: {q1 - q0} quadros ({time.time() - t0:.0f} s)")
                segmentos.append(seg)
                rel["quadros"] += q1 - q0
        finally:
            b.close()
    import tempfile

    saida.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("".join(f"file '{s.resolve()}'\n" for s in segmentos))
        lista = Path(f.name)
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy",
                        "-metadata", f"comment={FORMATO}", str(saida)], check=True)
    finally:
        lista.unlink(missing_ok=True)
    rel["segundos"] = round(time.time() - t0, 1)
    return rel


def previa(html, instantes, pasta, espera_ms=60000):
    """Quadros soltos em PNG, para olhar antes de renderizar tudo."""
    from playwright.sync_api import sync_playwright

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    arqs = []
    with sync_playwright() as pw:
        b, pg = _abrir(pw, html, espera_ms)
        try:
            for t in instantes:
                _quadro(pg, t)
                a = pasta / f"previa-{t:06.2f}.png"
                pg.screenshot(path=str(a))
                arqs.append(a)
        finally:
            b.close()
    return arqs


def main(argv=None):
    """Uso:
      python -m scripts.render <parte.html> <saida.mp4> [--fps 30] [--cache pasta]
      python -m scripts.render <parte.html> --previa <pasta> <t1> <t2> ..."""
    import argparse

    a = argparse.ArgumentParser(prog="render")
    a.add_argument("html")
    a.add_argument("saida", nargs="?")
    a.add_argument("--fps", type=int, default=30)
    a.add_argument("--cache")
    a.add_argument("--previa", nargs="+")
    a.add_argument("--cenas", nargs="+", help="renderiza só estas cenas (revisão de um trecho)")
    a = a.parse_args(argv)
    if a.previa:
        for p in previa(a.html, [float(x) for x in a.previa[1:]], a.previa[0]):
            print(p)
        return 0
    if not a.saida:
        print(main.__doc__)
        return 2
    rel = renderizar(a.html, a.saida, fps=a.fps, cache=a.cache, cenas=a.cenas)
    print(f"{a.saida}: {rel['quadros']} quadros, {len(rel['renderizadas'])} cenas renderizadas, "
          f"{len(rel['do_cache'])} do cache, {rel['segundos']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
