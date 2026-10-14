"""Entrega de um vídeo (T20): montagem final, cópia para WhatsApp, versões, abrir e limpar.

Montagem (M28): junta o vídeo mudo e a mixagem crua (WAV) de cada parte, recusa faixa com duração
diferente do vídeo e silêncio digital na emenda, e normaliza o volume UMA vez no vídeo inteiro.
Entrega (M25): a versão vai para versoes/ sem sobrescrever (R11), sai uma cópia abaixo do limite do
WhatsApp e o vídeo abre no QuickTime (nunca tocar áudio sem janela).
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

if __package__ in (None, ""):  # rodado como `python scripts/entrega.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.formato import ALTURA, CODIFICADOR, ESPECIFICACAO, FORMATO, FPS, LARGURA  # noqa: E402,F401

ALVO_LUFS, PICO_DBTP, LRA = -14, -1.5, 20
LUFS_ACEITO = (-16.5, -13.0)   # a curva linear para antes de passar do pico; o YouTube normaliza para -14
SILENCIO_DB = -60.0          # abaixo disto, numa janela de 10 ms, é silêncio digital
JANELA_EMENDA = 0.15         # segundos olhados de cada lado da emenda
TOLERANCIA_DURACAO = 1 / 30  # um quadro


def _duracao(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip().split(",")[0])


def _ler_wav(p):
    """Amostras (n, canais) em -1..1 e a taxa. Só PCM de 16 bits, que é o que a mixagem crua produz."""
    with wave.open(str(p)) as w:
        sr, ch, n, larg = w.getframerate(), w.getnchannels(), w.getnframes(), w.getsampwidth()
        if larg != 2:
            raise ValueError(f"{p}: WAV de {8 * larg} bits; a montagem espera PCM de 16 bits")
        x = np.frombuffer(w.readframes(n), "<i2").reshape(-1, ch) / 32768.0
    return x, sr


def menor_nivel(x, sr, janela=0.01):
    """Menor nível RMS (dB) em janelas de 10 ms, no canal mais baixo."""
    x = np.asarray(x)
    if x.ndim == 2:
        return min(menor_nivel(x[:, c], sr, janela) for c in range(x.shape[1]))
    n = max(1, int(sr * janela))
    niveis = [20 * np.log10(np.sqrt(np.mean(x[i:i + n] ** 2)) + 1e-12) for i in range(0, max(1, len(x) - n + 1), n)]
    return min(niveis)


def checar_duracoes(ctx):
    erros, taxas = [], set()
    for i, (video, audio) in enumerate(ctx.get("partes") or []):
        dv = _duracao(video)
        x, sr = _ler_wav(audio)
        taxas.add(sr)
        da = len(x) / sr
        if abs(dv - da) > TOLERANCIA_DURACAO + 1e-3:
            erros.append(f"M28 parte {i + 1}: duração do áudio {da:.3f} s diferente do vídeo {dv:.3f} s")
    if len(taxas) > 1:
        erros.append(f"M28 partes com taxas de amostragem diferentes: {sorted(taxas)}")
    return erros


def checar_emendas(ctx):
    """Silêncio digital nas emendas. ctx["silencios_permitidos"]: emendas (1 = entre a parte 1 e a 2) com silêncio
    declarado no roteiro. Olha 0,15 s de cada lado: um silêncio dentro de uma parte é assunto da mixagem."""
    erros, partes = [], ctx.get("partes") or []
    livres = set(ctx.get("silencios_permitidos") or [])
    t = 0.0
    for i in range(len(partes) - 1):
        t += _duracao(partes[i][0])
        a, sra = _ler_wav(partes[i][1])
        b, srb = _ler_wav(partes[i + 1][1])
        nivel = min(menor_nivel(a[-int(sra * JANELA_EMENDA):], sra), menor_nivel(b[:int(srb * JANELA_EMENDA)], srb))
        if nivel < SILENCIO_DB and (i + 1) not in livres:
            erros.append(f"M28 emenda em {t:.2f} s: silêncio digital ({nivel:.0f} dB) entre a parte {i + 1} e a {i + 2}")
    return erros


REGRAS = {"faixas_com_duracao_da_parte": checar_duracoes, "emenda_sem_silencio": checar_emendas}


def _medir(entradas, juntar):
    r = subprocess.run(["ffmpeg", "-hide_banner", *entradas, "-filter_complex",
                        juntar + f",loudnorm=I={ALVO_LUFS}:TP={PICO_DBTP}:LRA={LRA}:print_format=json[a]",
                        "-map", "[a]", "-f", "null", "-"], capture_output=True, text=True, check=True)
    return json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])


def _formato(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=comment", "-of", "csv=p=0", str(mp4)],
                       capture_output=True, text=True)
    return r.stdout.strip()


def _confere(mp4):
    """Copiável só se a etiqueta E o stream conferem: o ffmpeg copia o comentário para qualquer recompressão."""
    if _formato(mp4) != FORMATO:
        return False
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=" + ",".join(ESPECIFICACAO), "-of", "json", str(mp4)], capture_output=True, text=True)
    try:
        st = json.loads(r.stdout)["streams"][0]
    except (ValueError, KeyError, IndexError):
        return False
    st.setdefault("color_range", "unknown")  # o ffprobe omite o campo quando não há marca
    return all(st.get(k) in (v if isinstance(v, tuple) else (v,)) for k, v in ESPECIFICACAO.items())


def _no_formato(video, cache):
    """O vídeo no formato padrão: o próprio arquivo, ou uma cópia convertida UMA vez e guardada no cache
    (o nome vem do caminho, do tamanho, da data e do FORMATO: trocar a parte ou o formato gera outra conversão)."""
    video = Path(video)
    if _confere(video):
        return video
    st = video.stat()
    chave = hashlib.sha256(f"{video.resolve()}|{st.st_size}|{st.st_mtime_ns}|{FORMATO}".encode()).hexdigest()[:24]
    alvo = Path(cache) / f"{chave}.mp4"
    if not alvo.exists():
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_name(f"{chave}.{os.getpid()}.parcial")
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", "0:v", *CODIFICADOR,
                            "-r", str(FPS), "-metadata", f"comment={FORMATO}", "-f", "mp4", str(tmp)], check=True)
            tmp.rename(alvo)
        finally:
            tmp.unlink(missing_ok=True)
    return alvo


def montar(partes, saida, silencios_permitidos=()):
    """partes: [(video_mudo.mp4, mixagem_crua.wav), ...] na ordem. Devolve {"emendas", "lufs", "pico"}.
    Cada áudio é ajustado à duração exata do seu vídeo, para a diferença de até um quadro não se acumular."""
    partes = [(Path(v), Path(a)) for v, a in partes]
    ctx = {"partes": partes, "silencios_permitidos": silencios_permitidos}
    erros = checar_duracoes(ctx) + checar_emendas(ctx)
    if erros:
        raise ValueError("; ".join(erros))
    n = len(partes)
    durs = [_duracao(v) for v, _ in partes]
    so_audio = sum([["-i", str(a)] for _, a in partes], [])
    ajuste = lambda base: "".join(f"[{base + i}:a]apad,atrim=0:{durs[i]}[c{i}];" for i in range(n)) + \
        "".join(f"[c{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1"
    m = _medir(so_audio, ajuste(0))
    ln = (f"loudnorm=I={ALVO_LUFS}:TP={PICO_DBTP}:LRA={LRA}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
          f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
          f":linear=true,aresample=44100")
    # vídeo: emendado por cópia (sem recomprimir); parte fora do formato é convertida uma vez, no cache
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    videos = [_no_formato(v, saida.parent / ".cache-montagem") for v, _ in partes]
    lista = saida.with_suffix(".lista.txt")
    so_video = saida.with_suffix(".video.mp4")
    esc = lambda c: str(c).replace("'", "'\\''")
    lista.write_text("".join(f"file '{esc(v.resolve())}'\n" for v in videos))
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy",
                        str(so_video)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(so_video), *so_audio, "-filter_complex",
                        ajuste(1) + f",{ln}[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "192k", "-metadata", f"comment={FORMATO}", "-movflags", "+faststart", "-shortest",
                        str(saida)], check=True)
    finally:
        lista.unlink(missing_ok=True)
        so_video.unlink(missing_ok=True)
    final = _medir(["-i", str(saida)], "[0:a]anull")
    lufs = float(final["input_i"])
    if not LUFS_ACEITO[0] <= lufs <= LUFS_ACEITO[1]:
        raise ValueError(f"{saida}: volume final {lufs:.1f} LUFS fora de {LUFS_ACEITO} (M27)")
    emendas = [round(sum(durs[:k + 1]), 3) for k in range(n - 1)]
    return {"emendas": emendas, "lufs": lufs, "pico": float(final["input_tp"])}


def whatsapp(mp4, saida, limite_mb=15.5, ini=0.0, dur=None):
    """Cópia abaixo do limite. A taxa sai da duração: 720p com áudio de 64k quando sobra taxa;
    vídeo longo cai para 480p com áudio mono de 48k. Se passar do limite, tenta de novo mais baixo.
    ini e dur cortam um trecho (busca antes da entrada, exata porque reencoda)."""
    saida = Path(saida)
    dur = dur if dur is not None else _duracao(mp4) - ini
    trecho = ["-ss", f"{ini:.3f}", "-t", f"{dur:.3f}"]
    fator = 0.92
    for _ in range(4):
        total = limite_mb * 8 * 1024 * fator / dur
        longo = total < 400
        audio_kbps = 48 if longo else 64
        kbps = max(30, int(total - audio_kbps))
        log = saida.with_suffix(".2pass")
        base = ["ffmpeg", "-v", "error", "-y", *trecho, "-i", str(mp4), "-vf", "scale=854:480" if longo else "scale=1280:720",
                "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k", "-passlogfile", str(log)]
        try:
            subprocess.run(base + ["-pass", "1", "-an", "-f", "mp4", "/dev/null"], check=True)
            subprocess.run(base + ["-pass", "2", "-c:a", "aac", "-b:a", f"{audio_kbps}k"] + (["-ac", "1"] if longo else [])
                           + ["-movflags", "+faststart", str(saida)], check=True)
        finally:
            for f in saida.parent.glob(log.name + "*"):
                f.unlink()
        if saida.stat().st_size < limite_mb * 1024 * 1024:
            return saida
        fator *= 0.85
    raise RuntimeError(f"{saida}: não coube em {limite_mb} MB")


def whatsapp_partes(mp4, saida, limite_mb=15.5, cortes=(), taxa_min_kbps=250):
    """Uma cópia só quando a taxa total fica acima de taxa_min_kbps; senão divide em partes, cada uma
    terminando na maior emenda (cortes, em segundos) que cabe, ou no tamanho máximo se nenhuma couber."""
    total, saida = _duracao(mp4), Path(saida)
    maximo = limite_mb * 8 * 1024 * 0.92 / taxa_min_kbps   # segundos por arquivo na taxa mínima
    if total <= maximo:
        return [whatsapp(mp4, saida, limite_mb)]
    pontos, pos = [], 0.0
    while total - pos > maximo:
        cabem = [c for c in cortes if pos + 1.0 < c <= pos + maximo]
        resto = total - pos
        # sem emenda que caiba, fatia o resto em pedaços iguais (cortar no máximo deixava uma sobra de décimos)
        pos = max(cabem) if cabem else pos + resto / math.ceil(resto / maximo)
        pontos.append(pos)
    limites = [0.0, *pontos, total]
    return [whatsapp(mp4, saida.with_name(f"{saida.stem}-parte{i}{saida.suffix}"), limite_mb, a, b - a)
            for i, (a, b) in enumerate(zip(limites, limites[1:]), 1)]


def versionar(arquivo, pasta_versoes, nome):
    """Guarda a entrega em versoes/ com um nome novo; nunca sobrescreve (R11)."""
    arquivo, pasta = Path(arquivo), Path(pasta_versoes)
    destino = pasta / f"{nome}{arquivo.suffix}"
    if destino.exists():
        raise FileExistsError(f"já existe: {destino} (cada entrega leva um nome novo)")
    pasta.mkdir(parents=True, exist_ok=True)
    shutil.copy2(arquivo, destino)
    return destino


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def limpar(pasta_saida, pasta_versoes):
    """Apaga prévias, segmentos parciais e vídeos com cópia idêntica em versoes/. O resto fica."""
    pasta_saida, pasta_versoes = Path(pasta_saida).resolve(), Path(pasta_versoes).resolve()
    if pasta_saida.name != "07-saida":
        raise ValueError(f"limpar só apaga em 07-saida, não em {pasta_saida}")
    if pasta_saida == pasta_versoes or pasta_versoes in pasta_saida.parents or pasta_saida in pasta_versoes.parents:
        raise ValueError("a pasta de saída e a de versões não podem ser a mesma nem uma dentro da outra")
    guardados = {}
    for v in pasta_versoes.glob("*") if pasta_versoes.exists() else []:
        if v.is_file():
            guardados.setdefault(v.stat().st_size, set()).add(_sha(v))
    removidos = []
    for f in sorted(pasta_saida.iterdir()):
        if not f.is_file():
            continue
        lixo = f.name.startswith("previa-") or ".parcial." in f.name
        copia = f.suffix == ".mp4" and f.stat().st_size in guardados and _sha(f) in guardados[f.stat().st_size]
        if lixo or copia:
            f.unlink()
            removidos.append(f)
    return removidos


ABRIR = """on run argv
  set alvo to item 1 of argv
  tell application "QuickTime Player"
    activate
    set d to missing value
    try
      set d to open (POSIX file alvo)
    end try
    repeat 120 times -- arquivo grande: o open pode voltar antes do documento existir
      if d is not missing value then exit repeat
      delay 0.5
      repeat with x in documents -- procura pelo caminho, nunca pelo documento da frente
        try
          if POSIX path of (file of x as alias) is alvo then set d to contents of x
        end try
      end repeat
    end repeat
    if d is missing value then error "o QuickTime não abriu " & alvo
    if (item 2 of argv) is not "" then set current time of d to ((item 2 of argv) as real)
    play d
  end tell
end run"""


def abrir(mp4, inicio=None):
    """Abre e toca no QuickTime (com janela), opcionalmente a partir de um ponto em segundos.
    O caminho vai como argumento do script, nunca dentro do texto dele."""
    subprocess.run(["osascript", "-e", ABRIR, str(Path(mp4).resolve()), "" if inicio is None else f"{inicio:g}"],
                   check=True)


def main(argv=None):
    """Uso:
      python -m scripts.entrega montar <saida.mp4> <video1> <audio1.wav> [<video2> <audio2.wav> ...]
      python -m scripts.entrega whatsapp <video.mp4> <saida.mp4> [--limite 15.5]
      python -m scripts.entrega versionar <arquivo> <pasta versoes> <nome>
      python -m scripts.entrega abrir <video.mp4> [--inicio s]
      python -m scripts.entrega limpar <pasta 07-saida> <pasta versoes>"""
    import argparse

    p = argparse.ArgumentParser(prog="entrega")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("montar"); m.add_argument("saida"); m.add_argument("pares", nargs="+")
    w = sub.add_parser("whatsapp"); w.add_argument("video"); w.add_argument("saida"); w.add_argument("--limite", type=float, default=15.5)
    v = sub.add_parser("versionar"); v.add_argument("arquivo"); v.add_argument("pasta"); v.add_argument("nome")
    a = sub.add_parser("abrir"); a.add_argument("video"); a.add_argument("--inicio", type=float)
    lp = sub.add_parser("limpar"); lp.add_argument("saida"); lp.add_argument("versoes")
    a = p.parse_args(argv)
    if a.cmd == "montar":
        if len(a.pares) % 2:
            p.error("montar recebe pares: vídeo e áudio de cada parte")
        print(montar(list(zip(a.pares[::2], a.pares[1::2])), a.saida))
    elif a.cmd == "whatsapp":
        s = whatsapp(a.video, a.saida, a.limite)
        print(f"{s} ({s.stat().st_size / 1048576:.1f} MB)")
    elif a.cmd == "versionar":
        print(versionar(a.arquivo, a.pasta, a.nome))
    elif a.cmd == "abrir":
        abrir(a.video, a.inicio)
    else:
        for f in limpar(a.saida, a.versoes):
            print("apagado:", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
