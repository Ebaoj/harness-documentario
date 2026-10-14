"""Mixagem de uma parte do vídeo a partir do plano (T21).

plano["som"] = {
  "voz":     [{"arquivo": <relativo ao episódio>, "em": s}, ...],      narração e vozes reais já montadas
  "trilha":  {"arquivo", "trechos": [[ini, fim|None], ...], "curva": [[t, ganho], ...], "entra"?: s, "sai"?: s},
  "efeitos": {"sopros": [[t, ganho, dur]], "impactos": [[t, ganho, freq]], "sopros_nos_cortes": bool, "semente"?}}
Os padrões da mixagem aprovada (volume da trilha, queda sob voz real, efeitos) vêm do estilo do canal (M27).
Sob a fala a trilha fica num nível constante por trecho, com o nível típico som.folga_sob_voz_db abaixo do
nível típico da voz e os picos pelo menos 6 dB menos que isso (M32): um compressor de limite fixo não agia
quando a narração era baixa. A folga medida vai para <saida>.folga.json. A trilha continua de onde a parte anterior parou: o primeiro trecho começa nesse ponto (M28).
Sai a mixagem CRUA e mono, com a duração exata da parte; o volume final é normalizado uma vez na entrega.
A trilha é procurada na pasta de músicas quando o caminho não é absoluto: a variável de ambiente HARNESS_MUSICAS,
ou som.pasta_musicas do estilo (relativa à pasta do estilo.json quando não é absoluta).
O intervalo de cada voz real (para a trilha cair a sob_voz_real) é plano["vozes"][i]["dur"], ou o trecho do catálogo.
"""
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

if __package__ in (None, ""):  # rodado como `python scripts/som.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SR = 44100


def _lp(x, a):
    y = np.zeros_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += a * (v - acc)
        y[i] = acc
    return y


def efeitos(plano, E, dur):
    """Efeitos sóbrios sintetizados (determinísticos pela semente): sopros nos cortes e impactos."""
    ef = plano["som"].get("efeitos") or {}
    rng = np.random.default_rng(ef.get("semente", E.get("semente", 0)))
    out = np.zeros(int(round(SR * dur)))

    def put(t, x):
        i = int(t * SR)
        if i < 0:  # começa antes da parte: entra o pedaço que cabe
            x, i = x[-i:], 0
        j = min(len(out), i + len(x))
        if i < len(out):
            out[i:j] += x[:j - i]

    def sopro(t, g=.2, d=.9):
        n = int(SR * d)
        tt = np.arange(n) / SR
        put(t - d / 2, _lp(rng.standard_normal(n), .03) * np.sin(np.pi * tt / tt[-1]) ** 2 * g)

    def impacto(t, g=1.0, f=46):
        n = int(SR * 1.3)
        tt = np.arange(n) / SR
        put(t, (np.sin(2 * np.pi * f * tt * (1 + .5 * np.exp(-tt * 10))) * np.exp(-tt * 4)
                + _lp(rng.standard_normal(n), .07) * np.exp(-tt * 16) * .5) * g)

    for t, g, d in ef.get("sopros") or []:
        sopro(t, g, d)
    impactos = ef.get("impactos") or []
    for t, g, f in impactos:
        impacto(t, g, f)
    if ef.get("sopros_nos_cortes", True):
        for c in sorted(plano["cenas"], key=lambda c: c["ini"])[1:]:
            if all(abs(c["ini"] - t) > E.get("longe_de_impacto", .4) for t, _, _ in impactos):
                sopro(c["ini"])
    pico = np.max(np.abs(out)) if len(out) else 0
    return out / pico * E.get("efeitos_pico", .5) if pico > 0 else out


def _curva(pontos):
    """Ganho por quadros-chave [[t, ganho], ...], linear entre eles, como expressão do ffmpeg."""
    pontos = sorted(pontos or [[0, 1.0]], key=lambda q: q[0])  # só pelo tempo: tempos iguais mantêm a ordem (degrau)
    expr = f"{pontos[-1][1]}"
    for (t0, v0), (t1, v1) in reversed(list(zip(pontos, pontos[1:]))):
        if t1 <= t0:  # dois tempos iguais: degrau
            continue
        expr = f"if(lt(t,{t1}),{v0}+({v1 - v0})*(t-{t0})/{t1 - t0},{expr})"
    return f"if(lt(t,{pontos[0][0]}),{pontos[0][1]},{expr})"


def _wav(p, x):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def _duracao(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip().split(",")[0])


def _janelas_db(x, n):
    k = len(x) // n
    if k == 0:
        return np.array([])
    q = x[:k * n].reshape(k, n)
    return 20 * np.log10(np.sqrt(np.mean(q ** 2, axis=1)) + 1e-12)


def _regioes(vdb, janela, silencio_minimo, limiar_db):
    """Trechos de fala em janelas [i0, i1]: pausas mais curtas que silencio_minimo ficam dentro do trecho."""
    ativos = np.flatnonzero(vdb > limiar_db)
    if not len(ativos):
        return []
    lacuna = int(round(silencio_minimo / janela))
    regs, i0, ant = [], ativos[0], ativos[0]
    for i in ativos[1:]:
        if i - ant > lacuna:
            regs.append((i0, ant))
            i0 = i
        ant = i
    return regs + [(i0, ant)]


def _deslocado(x, d):
    """x deslocado d posições (d > 0: o valor de i vem de i + d), completando com 0 dB."""
    y = np.zeros_like(x)
    if d > 0:
        y[:len(x) - d] = x[d:]
    elif d < 0:
        y[-d:] = x[:len(x) + d]
    else:
        y[:] = x
    return y


def ganho_sob_voz(voz, mus, folga_db, janela=0.05, silencio_minimo=1.5, desce=0.4, segura=0.3, sobe_db_s=20.0,
                  limiar_db=-50, ref_pct=50, mus_pct=50, folga_pico_db=6.0, pico_pct=90):
    """Ganho (por amostra) da música: CONSTANTE em cada trecho de fala (as pausas curtas não a fazem oscilar).
    O nível típico da música fica folga_db abaixo do nível típico da fala, e os picos dela (percentil pico_pct)
    ficam pelo menos folga_db - folga_pico_db abaixo (um crescendo não cobre a fala). Comparar o trecho mais
    baixo da voz com o pico da música deixava a trilha muda, a -68 dB. Só sobe em silêncio de verdade
    (>= silencio_minimo): segura depois da fala, sobe a sobe_db_s e desce numa rampa linear de `desce`
    segundos que termina na primeira palavra."""
    n = int(SR * janela)
    vdb, mdb = _janelas_db(voz, n), _janelas_db(mus[:len(voz)], n)
    k = min(len(vdb), len(mdb))
    alvo = np.zeros(k)
    for i0, i1 in _regioes(vdb[:k], janela, silencio_minimo, limiar_db):
        v = vdb[i0:i1 + 1]
        ref = np.percentile(v[v > limiar_db], ref_pct)
        m = mdb[i0:i1 + 1]
        alvo[i0:i1 + 1] = min(0.0, ref - folga_db - np.percentile(m, mus_pct),
                              ref - (folga_db - folga_pico_db) - np.percentile(m, pico_pct))
    kd, kh = max(1, int(round(desce / janela))), int(round(segura / janela))
    g = alvo.copy()
    for d in range(1, kh + 1):  # segura depois da fala
        g = np.minimum(g, _deslocado(alvo, -d))
    for d in range(1, kd + 1):  # rampa linear antes da fala, completa na primeira palavra
        g = np.minimum(g, _deslocado(alvo, d) * (kd - d + 1) / kd)
    passo = sobe_db_s * janela
    for i in range(1, k):  # a subida é lenta
        g[i] = min(g[i], g[i - 1] + passo)
    t = (np.arange(k) + .5) * n
    db = np.interp(np.arange(len(voz)), t, g) if k else np.zeros(len(voz))
    return 10 ** (db / 20)


def _medir_folga(voz, mus, alvo, janela=0.05, silencio_minimo=1.5, limiar_db=-50, ref_pct=50, mus_pct=50,
                 folga_pico_db=6.0, pico_pct=90):
    """Folga por trecho de fala, medida na música JÁ mixada: o pior entre (voz típica - música típica) e
    (voz típica - pico da música) + folga_pico_db. Reprova o crescendo que a mediana esconde."""
    n = int(SR * janela)
    vdb, mdb = _janelas_db(voz, n), _janelas_db(mus, n)
    k = min(len(vdb), len(mdb))
    fs = []
    for i0, i1 in _regioes(vdb[:k], janela, silencio_minimo, limiar_db):
        v = vdb[i0:i1 + 1]
        ref, m = np.percentile(v[v > limiar_db], ref_pct), mdb[i0:i1 + 1]
        fs.append(min(ref - np.percentile(m, mus_pct), ref - np.percentile(m, pico_pct) + folga_pico_db))
    return {"alvo": alvo, "pior": round(float(min(fs)), 1) if fs else None,
            "mediana": round(float(np.median(fs)), 1) if fs else None}


def juntar(voz, mus, sfx, reais, E):
    """Mixagem crua: voz + trilha abaixada sob a fala (e mais ainda sob voz real) + efeitos. -> (x, folga)"""
    m = min(len(voz), len(mus), len(sfx))
    voz, mus, sfx = voz[:m], mus[:m], sfx[:m]
    g = ganho_sob_voz(voz, mus, E["folga_sob_voz_db"], silencio_minimo=E["silencio_minimo_s"])
    r = np.zeros(m)
    w = int(SR * .15)  # rampa de 0,15 s: completa quando a voz real entra, desfeita depois que ela sai
    for a, b in reais:
        ia, ib = min(m, max(0, int(a * SR))), min(m, max(0, int(b * SR)))
        r[ia:ib] = 1.0
        i0 = max(0, ia - w)
        r[i0:ia] = np.maximum(r[i0:ia], np.linspace(0, 1, w, endpoint=False)[w - (ia - i0):])
        i1 = min(m, ib + w)
        r[ib:i1] = np.maximum(r[ib:i1], np.linspace(1, 0, w, endpoint=False)[:i1 - ib])
    musf = mus * g * (1 - (1 - E["sob_voz_real"]) * r)
    sfxf = sfx * ganho_sob_voz(voz, sfx, E.get("efeitos_folga_db", 10), silencio_minimo=0.2, desce=0.05,
                               segura=0.05, sobe_db_s=400.0, ref_pct=25, mus_pct=100)  # efeito: pico sobre a palavra
    return voz + musf + sfxf, _medir_folga(voz, musf, E["folga_sob_voz_db"], silencio_minimo=E["silencio_minimo_s"])


def checar_folga(ctx):
    """M32: em cada mixagem, a trilha ficou abaixo da fala pela folga do estilo (tolerância de 1 dB)."""
    erros = []
    for f in ctx.get("folgas") or []:
        if f.get("pior") is not None and f["pior"] < f["alvo"] - 1:
            erros.append(f"M32 {f.get('arquivo', 'mixagem')}: a trilha chega a {f['pior']} dB da fala "
                         f"(mínimo {f['alvo']} dB): a narração some sob a música")
    return erros


REGRAS = {"musica_abaixo_da_fala": checar_folga}


def _ler_float(p):
    """WAV pcm_f32le mono -> float. Percorre os chunks RIFF pelo tamanho (um metadado com a palavra 'data'
    no título não pode ser confundido com o áudio) e lê só o tamanho declarado do chunk de dados."""
    import struct

    b = Path(p).read_bytes()
    if b[:4] != b"RIFF" or b[8:12] != b"WAVE":
        raise ValueError(f"{p}: não é WAV")
    i = 12
    while i + 8 <= len(b):
        cid, tam = b[i:i + 4], struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"data":
            dados = b[i + 8:i + 8 + tam]
            return np.frombuffer(dados[:len(dados) // 4 * 4], "<f4").astype(float)
        i += 8 + tam + (tam & 1)
    raise ValueError(f"{p}: WAV sem chunk de dados")


def mixar(pasta_ep, plano, estilo, saida):
    pasta_ep, saida = Path(pasta_ep), Path(saida)
    E = json.loads(Path(estilo).read_text(encoding="utf-8"))["som"]
    S, dur = plano["som"], float(plano["dur"])
    vozes = S.get("voz") or []
    for v in vozes:
        if not (pasta_ep / v["arquivo"]).is_file():
            raise ValueError(f"som: voz {v['arquivo']} não existe em {pasta_ep}")
    tr = S["trilha"]
    arq_trilha = Path(os.path.expanduser(tr["arquivo"]))
    if not arq_trilha.is_absolute():
        # HARNESS_MUSICAS vence; senão som.pasta_musicas, relativa à pasta do estilo do canal quando não é absoluta
        pasta = Path(os.path.expanduser(os.environ.get("HARNESS_MUSICAS") or E.get("pasta_musicas", ".")))
        if not pasta.is_absolute():
            pasta = Path(estilo).resolve().parent / pasta
        arq_trilha = pasta / arq_trilha
    if not arq_trilha.is_file():
        raise ValueError(f"som: trilha {arq_trilha} não existe")
    trechos, cz = tr["trechos"], tr.get("cruzamento", E["cruzamento"])
    fim_arq = _duracao(arq_trilha)
    trechos = [[a, min(b if b is not None else a + dur + cz * len(trechos), fim_arq)] for a, b in trechos]
    cobre = sum(b - a for a, b in trechos) - cz * (len(trechos) - 1)
    if cobre < dur - 1e-3:
        raise ValueError(f"som: a trilha cobre {cobre:.2f} s e a parte tem {dur:.2f} s (o fim ficaria em silêncio)")
    cat = {f["id"]: f for f in json.loads((pasta_ep / "fontes.json").read_text(encoding="utf-8"))["fontes"]}
    reais = []
    for v in plano.get("vozes") or []:
        a, b = (cat.get(v["fonte"]) or {}).get("trecho") or [0, 0]
        reais.append((v["em"], v["em"] + v.get("dur", b - a)))

    saida.parent.mkdir(parents=True, exist_ok=True)
    fd, nome_ef = tempfile.mkstemp(suffix="-efeitos.wav")
    os.close(fd)
    arq_ef = Path(nome_ef)
    _wav(arq_ef, efeitos(plano, E, dur))

    nv = len(vozes)
    ent = sum([["-i", str(pasta_ep / v["arquivo"])] for v in vozes], []) + ["-i", str(arq_trilha), "-i", str(arq_ef)]
    it, ie = nv, nv + 1
    f = [f"[{i}:a]aresample={SR},adelay={int(round(v['em'] * 1000))}:all=1,apad,atrim=0:{dur}[v{i}]"
         for i, v in enumerate(vozes)]
    if nv:
        f.append("".join(f"[v{i}]" for i in range(nv)) + (f"amix=inputs={nv}:normalize=0," if nv > 1 else "")
                 + f"apad,atrim=0:{dur}[voz]")
    else:  # parte sem voz: silêncio no lugar dela (sem isso o ffmpeg liga a trilha na cadeia da voz)
        f.append(f"anullsrc=r={SR}:cl=mono,atrim=0:{dur}[voz]")
    n = len(trechos)
    f.append(f"[{it}:a]asplit={n}" + "".join(f"[m{k}]" for k in range(n)) if n > 1 else f"[{it}:a]anull[m0]")
    for k, (a, b) in enumerate(trechos):
        f.append(f"[m{k}]atrim={a}:{b},asetpts=N/SR/TB[t{k}]")
    atual = "t0"
    for k in range(1, n):
        f.append(f"[{atual}][t{k}]acrossfade=d={cz}[x{k}]")
        atual = f"x{k}"
    vol = _curva(tr.get("curva"))  # a queda sob voz real e sob a fala vem depois, em juntar()
    fades = (f",afade=t=in:d={tr['entra']}" if tr.get("entra") else "") + \
            (f",afade=t=out:st={dur - tr['sai']}:d={tr['sai']}" if tr.get("sai") else "")
    # asetnsamples: o acrossfade entrega blocos de segundos, e o volume avalia a curva uma vez por bloco
    f.append(f"[{atual}]atrim=0:{dur},asetpts=N/SR/TB,aresample={SR},asetnsamples=n=1024,volume={E['trilha_db']}dB,"
             f"volume='{vol}':eval=frame{fades}[mus]")
    f.append(f"[{ie}:a]volume={E['efeitos_db']}dB,apad,atrim=0:{dur}[sfx]")
    tmp = Path(tempfile.mkdtemp(prefix="mix-"))
    faixas = {k: tmp / f"{k}.wav" for k in ("voz", "mus", "sfx")}
    saidas = sum([["-map", f"[{k}]", "-map_metadata", "-1", "-t", str(dur), "-ac", "1", "-c:a", "pcm_f32le", str(p)]
                  for k, p in faixas.items()], [])
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *ent, "-filter_complex", ";".join(f), *saidas], check=True)
        x, folga = juntar(*(_ler_float(faixas[k]) for k in ("voz", "mus", "sfx")), reais, E)
    finally:
        arq_ef.unlink(missing_ok=True)
        for p in faixas.values():
            p.unlink(missing_ok=True)
        tmp.rmdir()
    n = int(round(dur * SR))
    x = np.pad(x, (0, max(0, n - len(x))))[:n]
    _wav(saida, x)
    saida.with_suffix(".folga.json").write_text(json.dumps({"arquivo": saida.name, **folga}), encoding="utf-8")
    return saida


def main(argv=None):
    """Uso: python -m scripts.som <pasta do episódio> <plano.json> <estilo.json> <saida.wav>"""
    a = argv if argv is not None else sys.argv[1:]
    if len(a) != 4:
        print(main.__doc__)
        return 2
    print(mixar(a[0], json.loads(Path(a[1]).read_text(encoding="utf-8")), a[2], a[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
