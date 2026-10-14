"""Métricas de ritmo de um vídeo de referência: fala (da legenda) e cortes (do vídeo, por detecção de cena).

Não se ouve áudio aqui: a fala vem do tempo das legendas, que no caso das automáticas é aproximado.
"""
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

LIMIAR_CENA = 0.30  # calibrado em vídeo real, ver referencias/calibracao-cena.md
PAUSA_MIN_S = 0.7  # intervalo entre legendas que conta como pausa
JUNTA_FALA_S = 0.5  # intervalos menores que isso não separam blocos de fala

_TS = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d{3})\s*-->\s*(\d+):(\d\d):(\d\d)[.,](\d{3})")
_TAG = re.compile(r"<[^>]+>")


def _seg(a, b, texto):
    return {"inicio_s": round(a, 3), "fim_s": round(b, 3), "texto": texto}


def _ler_json3(caminho):
    dados = json.loads(Path(caminho).read_text())
    segs = []
    for ev in dados.get("events", []):
        texto = "".join(s.get("utf8", "") for s in ev.get("segs", []) or []).replace("\n", " ").strip()
        if not texto:
            continue
        a = ev.get("tStartMs", 0) / 1000
        segs.append(_seg(a, a + ev.get("dDurationMs", 0) / 1000, re.sub(r"\s+", " ", texto)))
    return segs


def _ler_vtt(caminho):
    segs, anteriores = [], set()
    for bloco in re.split(r"\n\s*\n", Path(caminho).read_text()):
        linhas = bloco.strip().splitlines()
        for k, linha in enumerate(linhas):
            m = _TS.search(linha)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            textos = [re.sub(r"\s+", " ", _TAG.sub("", t)).strip() for t in linhas[k + 1 :]]
            textos = [t for t in textos if t]
            novos = [t for t in textos if t not in anteriores]  # legenda automática repete a linha anterior
            anteriores = set(textos)
            if novos:
                segs.append(_seg(a, b, " ".join(novos)))
            break
    return segs


def ler_legenda(caminho):
    caminho = Path(caminho)
    segs = _ler_json3(caminho) if caminho.suffix == ".json3" else _ler_vtt(caminho)
    return sorted(segs, key=lambda s: s["inicio_s"])


def metricas_fala(segmentos, duracao_s):
    palavras = sum(len(s["texto"].split()) for s in segmentos)
    blocos = []
    for s in segmentos:
        if blocos and s["inicio_s"] - blocos[-1][1] < JUNTA_FALA_S:
            blocos[-1][1] = max(blocos[-1][1], s["fim_s"])
        else:
            blocos.append([s["inicio_s"], s["fim_s"]])
    # pausas: intervalos entre legendas consecutivas maiores que PAUSA_MIN_S
    pausas, fim_ant = [], None
    for s in segmentos:
        if fim_ant is not None and s["inicio_s"] - fim_ant >= PAUSA_MIN_S:
            pausas.append([fim_ant, s["inicio_s"]])
        fim_ant = s["fim_s"] if fim_ant is None else max(fim_ant, s["fim_s"])
    tempo_fala = sum(b - a for a, b in blocos)
    pal_1min = sum(len(s["texto"].split()) for s in segmentos if s["inicio_s"] < 60)
    return {
        "palavras": palavras,
        "ppm_total": round(palavras / (duracao_s / 60), 1) if duracao_s else 0.0,
        "ppm_fala": round(palavras / (tempo_fala / 60), 1) if tempo_fala else 0.0,
        "ppm_primeiro_minuto": float(pal_1min) if duracao_s >= 60 else 0.0,
        "blocos_fala": [[round(a, 2), round(b, 2)] for a, b in blocos],
        "pausas": [[round(a, 2), round(b, 2)] for a, b in pausas],
        "pausa_mediana_s": round(statistics.median(b - a for a, b in pausas), 2) if pausas else 0.0,
        "fala_percentual": round(100 * tempo_fala / duracao_s, 1) if duracao_s else 0.0,
    }


def comando_cenas(video, limiar=LIMIAR_CENA):
    # reduz antes de medir: a mudança de cena não precisa de resolução e fica várias vezes mais rápida
    return ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an",
            "-vf", f"scale=320:-2,select='gt(scene,{limiar})',showinfo", "-f", "null", "-"]


def parse_showinfo(stderr):
    return [float(t) for t in re.findall(r"pts_time:\s*([0-9.]+)", stderr)]


def detectar_cenas(video, limiar=LIMIAR_CENA):
    r = subprocess.run(comando_cenas(video, limiar), capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr[-400:]}")
    return parse_showinfo(r.stderr)


def parse_pontuacao(saida):
    """Pares (tempo, nota de cena) da saída do filtro metadata=print."""
    return [(float(t), float(n)) for t, n in re.findall(r"pts_time:\s*([0-9.]+)\s*\n\s*lavfi\.scene_score=([0-9.]+)", saida)]


def pontuar_cenas(video, piso=0.05):
    """Uma única leitura do vídeo guarda a nota de todo quadro acima de `piso`; o limiar se aplica depois,
    sem reler (serve para calibrar)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an",
           "-vf", f"scale=320:-2,select='gt(scene,{piso})',metadata=print:key=lavfi.scene_score:file=-",
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr[-400:]}")
    return parse_pontuacao(r.stdout)


def filtrar_por_limiar(pontuacao, limiar):
    return [t for t, n in pontuacao if n > limiar]


def duracao_video(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, timeout=60)
    return float(r.stdout.strip())


def estatisticas_cortes(tempos, duracao_s):
    limites = [0.0] + sorted(tempos) + [duracao_s]
    planos = [b - a for a, b in zip(limites, limites[1:]) if b > a]
    return {
        "cortes": len(tempos),
        "cortes_por_min": round(len(tempos) / (duracao_s / 60), 2) if duracao_s else 0.0,
        "cortes_primeiro_minuto": sum(1 for t in tempos if t < 60),
        "plano_mediano_s": round(statistics.median(planos), 2) if planos else duracao_s,
        "plano_medio_s": round(statistics.mean(planos), 2) if planos else duracao_s,
    }


def folha_de_contato(video, saida, cada_s=10, colunas=6, largura=240):
    """Um quadro a cada `cada_s` segundos numa grade, para olhar."""
    filtro = f"fps=1/{cada_s},scale={largura}:-2,tile={colunas}x20"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", filtro, "-frames:v", "1", str(saida)],
                   check=True, timeout=1800)


def espectrograma(video, saida, largura=1600):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-lavfi",
                    f"showspectrumpic=s={largura}x400:legend=0", str(saida)], check=True, timeout=1800)


def analisar(pasta, limiar=LIMIAR_CENA, extras=True):
    """Calcula tudo de um vídeo em `pasta` (midia/ ao lado) e grava metricas.json."""
    pasta = Path(pasta)
    midia = pasta / "midia"
    status = json.loads((midia / "status.json").read_text())
    video = midia / status["video"]
    dur = duracao_video(video)
    cortes = estatisticas_cortes(filtrar_por_limiar(pontuar_cenas(video), limiar), dur)
    out = {"video_id": pasta.name, "duracao_s": round(dur, 1), "limiar_cena": limiar, "cortes": cortes}
    if status.get("legenda"):
        segs = [x for x in ler_legenda(midia / status["legenda"]) if x["inicio_s"] < dur]  # vídeo recortado: legenda é do inteiro
        out["fala"] = metricas_fala(segs, dur)
        (midia / "transcricao.json").write_text(json.dumps(segs, ensure_ascii=False))  # só para análise local
    else:
        out["fala"] = None
    if extras:
        folha_de_contato(video, pasta / "folha.png", cada_s=max(10, int(dur // 120)))
        espectrograma(video, pasta / "espectro.png")
    (pasta / "metricas.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main(argv=None):
    argv = argv or sys.argv[1:]
    print(json.dumps(analisar(argv[0]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
