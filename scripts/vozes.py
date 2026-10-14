"""Vozes reais (T22): transcrever, cortar com conferência, aparar e gerar legendas.

O julgamento fica com quem produz (o agente de código ou uma pessoa): achar o trecho no documentário, decidir onde a frase
começa e acaba, traduzir. Este módulo garante o resultado:
  M12  todo corte é transcrito de novo e precisa começar e terminar nas palavras esperadas
  M11  a legenda sai dos tempos das palavras, com o fim real medido pela energia do áudio
Transcrição local com whisper-cli (modelo em WHISPER_MODELO ou modelos/ggml-small.bin na raiz do projeto).
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

if __package__ in (None, ""):  # rodado como `python scripts/vozes.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SR = 44100
MODELO = Path(os.environ.get("WHISPER_MODELO", str(Path(__file__).resolve().parent.parent / "modelos" / "ggml-small.bin"))).expanduser()
FOLGAS_APARAR = (0.15, 0.35, 0.6, 1.0)  # segundos depois do menor corte que ainda termina certo
SEMELHANCA = 0.8      # quanto o começo e o fim transcritos precisam lembrar o esperado
LIMIAR_FALA_DB = -35  # abaixo disto, depois da última palavra, a fala acabou


def _norm(s):
    return re.sub(r"[^\w\s']", "", s.lower()).split()


def _ler(p):
    with wave.open(str(p)) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, ch).mean(axis=1) / 32768.0
    return x, sr


def _inicio_real(x, sr, w0, w1, janela=0.02):
    """Primeiro instante com energia de fala dentro da palavra (o transcritor puxa o início para trás);
    nunca depois do fim marcado da palavra. Com música alta por baixo, não muda nada."""
    n = int(sr * janela)
    fim = min(len(x), int((w1 + 0.3) * sr))  # a palavra pode cobrir o silêncio inteiro antes dela
    for i in range(int(w0 * sr), max(int(w0 * sr), fim - n), n):
        if 20 * np.log10(np.sqrt(np.mean(x[i:i + n] ** 2)) + 1e-12) > LIMIAR_FALA_DB:
            return min(i / sr, w1)  # o resultado nunca passa do fim marcado
    return w0


def transcrever(audio, idioma):
    """Palavras [[ini, fim, texto], ...] em segundos, pelo whisper-cli local; o início de cada palavra é
    ajustado à energia do áudio (o whisper marca a primeira palavra em 0,0 s mesmo depois de silêncio)."""
    with tempfile.TemporaryDirectory() as d:
        w16 = Path(d) / "a.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-ar", "16000", "-ac", "1", str(w16)], check=True)
        subprocess.run(["whisper-cli", "-m", str(MODELO), "-l", idioma, "-f", str(w16), "-ml", "1", "-sow", "-oj",
                        "-of", str(Path(d) / "t")], check=True, capture_output=True)
        dados = json.loads((Path(d) / "t.json").read_text(encoding="utf-8"))
        x, sr = _ler(w16)
    ps = [[x_["offsets"]["from"] / 1000, x_["offsets"]["to"] / 1000, x_["text"].strip()]
          for x_ in dados["transcription"] if x_["text"].strip()]
    for i, p in enumerate(ps):
        teto = p[1] if i + 1 == len(ps) else min(p[1], ps[i + 1][0] + 0.0)
        p[0] = round(min(_inicio_real(x, sr, p[0], max(teto, p[0])), p[1]), 3)
    for a, b in zip(ps, ps[1:]):  # ordem preservada
        b[0] = max(b[0], a[0])
    return ps


def _parecido(palavras, esperado):
    a, b = " ".join(palavras), " ".join(esperado)
    return difflib.SequenceMatcher(None, a, b).ratio() >= SEMELHANCA


def fim_da_fala(x, sr, t_ultima_palavra, t_limite, janela=0.02):
    """Instante em que a energia cai de vez depois do começo da última palavra (o transcritor estica o fim)."""
    n = int(sr * janela)
    i0, i1 = int(t_ultima_palavra * sr), min(len(x), int(t_limite * sr))
    fim = t_ultima_palavra
    for i in range(i0, max(i0, i1 - n), n):
        if 20 * np.log10(np.sqrt(np.mean(x[i:i + n] ** 2)) + 1e-12) > LIMIAR_FALA_DB:
            fim = (i + n) / sr
        elif (i - int(fim * sr)) / sr > 0.25:  # 0,25 s seguidos abaixo do limiar: acabou
            break
    return fim


def _menor_corte(wav, idioma, t_ultima, fim_esp, precisao=0.05):
    """Menor duração em que a transcrição ainda termina com as palavras esperadas (busca por divisão).
    A energia não separa fala de música; o próprio transcritor separa."""
    x, sr = _ler(wav)
    lo, hi = t_ultima + 0.1, len(x) / sr
    with tempfile.TemporaryDirectory() as d:
        while hi - lo > precisao:
            meio = (lo + hi) / 2
            parte = Path(d) / "p.wav"
            with wave.open(str(parte), "wb") as w:  # só os últimos 5 s antes do ponto testado
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
                w.writeframes((x[max(0, int((meio - 5) * sr)):int(meio * sr)] * 32767).astype("<i2").tobytes())
            ditas = _norm(" ".join(p[2] for p in transcrever(parte, idioma)))
            if ditas and _parecido(ditas[-len(fim_esp):], fim_esp):
                hi = meio
            else:
                lo = meio
    return hi


def _sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def conferir(arquivo, idioma, comeca_com, termina_com):
    """M12: transcreve o PRÓPRIO arquivo e confere o começo e o fim; o registro leva o sha256 do arquivo."""
    from datetime import date

    ini_esp, fim_esp = _norm(comeca_com), _norm(termina_com)
    if not ini_esp or not fim_esp:
        raise ValueError("M12 diga com que palavras o corte começa e termina (texto vazio não confere nada)")
    ps = transcrever(arquivo, idioma)
    ditas = _norm(" ".join(p[2] for p in ps))
    if len(ditas) < max(len(ini_esp), len(fim_esp)) or not _parecido(ditas[:len(ini_esp)], ini_esp):
        raise ValueError(f"M12 o corte começa com {' '.join(ditas[:len(ini_esp) + 2])!r}, esperado {comeca_com!r}")
    if not _parecido(ditas[-len(fim_esp):], fim_esp):
        raise ValueError(f"M12 o corte termina com {' '.join(ditas[-len(fim_esp) - 2:])!r}, esperado {termina_com!r}")
    return {"comeca_com": comeca_com, "termina_com": termina_com, "quando": date.today().isoformat(),
            "sha256": _sha256(arquivo), "palavras": ps}


def cortar(audio, ini, fim, saida, idioma, comeca_com, termina_com, aparar=False):
    """Corta [ini, fim] do áudio da fonte, transcreve o pedaço e confere o começo e o fim (M12).
    aparar=True corta logo depois da última palavra (busca pelo próprio transcritor) com 0,2 s de fade e confere de novo."""
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ini:.3f}", "-to", f"{fim:.3f}", "-i", str(audio),
                    "-ar", str(SR), "-ac", "1", str(saida)], check=True)
    try:
        reg = conferir(saida, idioma, comeca_com, termina_com)
    except ValueError:
        saida.unlink(missing_ok=True)
        raise
    aparado, folga_usada = False, None
    if aparar:
        base = _menor_corte(saida, idioma, reg["palavras"][-1][0], _norm(termina_com))
        x, sr = _ler(saida)
        inteiro = saida.with_suffix(".inteiro.wav")
        tmp = saida.with_suffix(".tmp.wav")
        shutil.copy2(saida, inteiro)
        reg_inteiro, tentados = reg, set()
        try:
            for folga in FOLGAS_APARAR:  # o fade pode comer o fim da última palavra: confere e, se preciso, folga mais
                corte = round(min(len(x) / sr, base + folga), 3)
                if corte in tentados:  # preso no fim do arquivo: o mesmo corte já foi conferido
                    break
                tentados.add(corte)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(inteiro), "-af",
                                f"atrim=0:{corte:.3f},afade=t=out:st={max(0, corte - 0.2):.3f}:d=0.2", str(tmp)],
                               check=True)
                tmp.replace(saida)
                try:
                    reg = conferir(saida, idioma, comeca_com, termina_com)
                    aparado, folga_usada = True, folga
                    break
                except ValueError:
                    continue
            if not aparado:  # nenhuma folga passou: fica o corte inteiro, já conferido antes do laço
                shutil.copy2(inteiro, saida)
                reg = reg_inteiro
        finally:
            tmp.unlink(missing_ok=True)
            inteiro.unlink(missing_ok=True)
    ps = reg.pop("palavras")
    return {"arquivo": str(saida), "palavras": ps, "aparado": aparado, "folga": folga_usada, "conferido": reg}


def checar_conferidas(ctx):
    """M12: toda voz real do catálogo tem o registro da conferência (scripts.vozes conferir/cortar) com o
    sha256 do arquivo; com ctx["pasta"], o registro precisa bater com o arquivo que está no disco."""
    erros, pasta = [], ctx.get("pasta")
    for f in ctx.get("fontes") or []:
        if not (isinstance(f, dict) and f.get("tipo") == "voz"):
            continue
        reg = f.get("conferido") if isinstance(f.get("conferido"), dict) else {}
        if not (reg.get("comeca_com") and reg.get("termina_com") and reg.get("sha256")):
            erros.append(f"M12 {f.get('id')}: voz sem conferência registrada com sha256 (use scripts.vozes conferir)")
        elif pasta and f.get("arquivo"):
            arq = Path(pasta) / f["arquivo"]
            if not arq.is_file():
                erros.append(f"M12 {f.get('id')}: arquivo {f['arquivo']} não encontrado para conferir o sha256")
            elif _sha256(arq) != reg["sha256"]:
                erros.append(f"M12 {f.get('id')}: o arquivo mudou depois da conferência (sha256 diferente)")
    return erros


REGRAS = {"vozes_conferidas": checar_conferidas}


def legendas(palavras, em, trechos, audio=None):
    """Legendas [[ini, fim, texto], ...] no tempo do vídeo (em = onde a voz entra).
    trechos = [(índice da primeira palavra, índice da última, texto traduzido), ...]: a tradução e o ponto
    de quebra são decisão de quem produz; o tempo sai das palavras. Com o áudio, o fim de cada legenda é o
    fim real da fala (energia), não o fim esticado que o transcritor dá à última palavra."""
    x = sr = None
    if audio is not None:
        x, sr = _ler(audio)
    itens, ultima = [], -1
    for a, b, texto in trechos:
        if not (0 <= a <= b < len(palavras)):
            raise ValueError(f"legenda {texto[:30]!r}: palavra {a} a {b} fora da fala ({len(palavras)} palavras)")
        if a <= ultima:
            raise ValueError(f"legenda {texto[:30]!r}: fora de ordem ou sobreposta (começa na palavra {a}, a anterior acabou na {ultima})")
        ultima = b
        ini = palavras[a][0]
        fim = palavras[b][1]
        if x is not None:
            limite = palavras[b + 1][0] if b + 1 < len(palavras) else len(x) / sr
            fim = min(fim, fim_da_fala(x, sr, palavras[b][0], limite) + 0.25)
        fim = max(fim, palavras[b][0] + 0.1)  # nunca antes do início da última palavra (duração quase zero no whisper)
        itens.append([round(ini + em, 2), round(fim + em, 2), texto])
    for atual, prox in zip(itens, itens[1:]):  # nunca invade a seguinte (palavras coladas no áudio)
        atual[1] = min(atual[1], prox[0])
    for a, b, texto in itens:
        if b <= a:
            raise ValueError(f"legenda sem duração ({a} a {b} s): {texto!r}; confira os tempos das palavras")
    return itens


def main(argv=None):
    """Uso:
      python -m scripts.vozes transcrever <audio> <idioma> [saida.json]
      python -m scripts.vozes cortar <audio> <ini> <fim> <saida.wav> <idioma> "<começa com>" "<termina com>" [--aparar]"""
    import argparse

    p = argparse.ArgumentParser(prog="vozes")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transcrever"); t.add_argument("audio"); t.add_argument("idioma"); t.add_argument("saida", nargs="?")
    c = sub.add_parser("cortar")
    for k in ("audio", "ini", "fim", "saida", "idioma", "comeca_com", "termina_com"):
        c.add_argument(k)
    c.add_argument("--aparar", action="store_true")
    k = sub.add_parser("conferir")
    for n in ("arquivo", "idioma", "comeca_com", "termina_com"):
        k.add_argument(n)
    a = p.parse_args(argv)
    if a.cmd == "transcrever":
        ps = transcrever(a.audio, a.idioma)
        if a.saida:
            Path(a.saida).write_text(json.dumps(ps, ensure_ascii=False))
        print(" ".join(f"{i}:{w[2]}@{w[0]:.2f}" for i, w in enumerate(ps)))
    elif a.cmd == "conferir":
        r = conferir(a.arquivo, a.idioma, a.comeca_com, a.termina_com)
        r.pop("palavras")
        print(json.dumps(r, ensure_ascii=False))
    else:
        r = cortar(a.audio, float(a.ini), float(a.fim), a.saida, a.idioma, a.comeca_com, a.termina_com, a.aparar)
        print(f"{r['arquivo']}: {len(r['palavras'])} palavras, aparado={r['aparado']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
