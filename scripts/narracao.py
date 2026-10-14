"""Narração (T23): estimar, gerar no ElevenLabs com aprovação, montar a faixa de voz da parte.

M24: narração na voz e no modelo do estilo do canal, texto com tags de interpretação;
     custo estimado ANTES e gasto só com aprovação registrada (aprovado_por), custo real no log.
M23: pausas dramáticas entram como silêncio no ponto exato da faixa, sem gerar a voz de novo.
A chave sai do ambiente (variável com o nome em narracao.chave do estilo) ou de um gerenciador de segredos
(HARNESS_SECRET_CMD: um comando que recebe o nome e imprime o valor) direto para o cabeçalho da chamada;
nunca vai para log, erro ou arquivo.
"""
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import urllib.request
import wave
from datetime import date
from pathlib import Path

import numpy as np

if __package__ in (None, ""):  # rodado como `python scripts/narracao.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SR = 44100
API = "https://api.elevenlabs.io/v1/text-to-speech/{voz}?output_format={formato}"
FADE = 0.03            # nas bordas de cada corte da narração
JANELA_BUSCA = 0.4     # o ponto de corte é o trecho mais quieto até 0,4 s do ponto pedido
SILENCIO_CORTE_DB = -40
GANHO_MAX_DB = 12      # quanto uma voz real pode subir ou descer para casar com a narração
SEMELHANCA_ROTEIRO = 0.85


def _config(estilo):
    return json.loads(Path(estilo).read_text(encoding="utf-8"))["narracao"]


def estimar(texto, estilo):
    c = _config(estilo)
    n = len(texto)
    return {"caracteres": n, "creditos": math.ceil(n * c["creditos_por_caractere"])}


def _chave_do_ambiente(nome):
    """Valor da chave: a variável de ambiente `nome`; sem ela, o gerenciador de segredos em HARNESS_SECRET_CMD
    (ex.: um script que consulta o seu cofre), chamado com o nome como último argumento."""
    valor = os.environ.get(nome, "").strip()
    if valor:
        return valor
    cmd = os.environ.get("HARNESS_SECRET_CMD", "").strip()
    if cmd:
        r = subprocess.run(shlex.split(cmd) + [nome], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    raise RuntimeError(f"chave {nome} ausente: defina a variável de ambiente {nome} ou HARNESS_SECRET_CMD")


def _post(url, corpo, cabecalhos):
    return urllib.request.urlopen(urllib.request.Request(url, data=corpo, headers=cabecalhos, method="POST"), timeout=300)


def _registrar(log, reg):
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False) + "\n")


def gerar(texto, saida, estilo, log_custos, aprovado_por, creditos_aprovados, chave=None, item=""):
    """Gera a narração. Exige quem aprovou (e a frase) e o valor aprovado; recusa se a estimativa passar dele.
    A tentativa vai para o log ANTES da chamada (a cobrança pode acontecer mesmo se a conexão cair)."""
    if not (aprovado_por or "").strip():
        raise PermissionError("narração sem aprovação registrada: mostre a estimativa e peça o aprovado antes (M24)")
    est = estimar(texto, estilo)
    if est["creditos"] > creditos_aprovados:
        raise PermissionError(f"estimativa de {est['creditos']} créditos passa dos {creditos_aprovados} aprovados (M24)")
    c = _config(estilo)
    base = {"data": date.today().isoformat(), "servico": "elevenlabs", "modelo": c["modelo"], "item": item,
            "caracteres": len(texto), "creditos_estimados": est["creditos"], "creditos_aprovados": creditos_aprovados,
            "aprovado_por": aprovado_por}
    _registrar(log_custos, {**base, "evento": "tentativa"})
    url = API.format(voz=c["voz"], formato=c["formato"])
    corpo = json.dumps({"text": texto, "model_id": c["modelo"], "language_code": c["idioma"]}).encode()
    k = (chave or (lambda: _chave_do_ambiente(c["chave"])))()
    try:
        with _post(url, corpo, {"xi-api-key": k, "Content-Type": "application/json"}) as r:
            audio, custo = r.read(), r.headers.get("character-cost")
    except Exception as e:  # a mensagem não pode levar a chave
        raise RuntimeError(f"ElevenLabs falhou: {str(e).replace(k, '***')}") from None
    finally:
        k = None
    reg = {**base, "evento": "concluido", "creditos": int(custo) if custo else est["creditos"],
           "custo_real_ausente": not custo}
    _registrar(log_custos, reg)
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_bytes(audio)
    return reg


def checar_custos(ctx):
    """M24: todo gasto no ElevenLabs tem aprovação registrada."""
    return [f"M24 gasto de {c.get('creditos')} créditos em {c.get('data')} ({c.get('item', '')}) sem aprovação registrada"
            for c in ctx.get("custos") or [] if c.get("servico") == "elevenlabs" and not (c.get("aprovado_por") or "").strip()]


def checar_custos_dos_episodios(raiz_videos):
    """Lê o 00-custos.jsonl de cada episódio e roda a M24."""
    erros = []
    for log in sorted(Path(raiz_videos).glob("*/00-custos.jsonl")):
        custos = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        erros += [f"{log.parent.name}: {e}" for e in checar_custos({"custos": custos})]
    return erros


REGRAS = {"narracao_aprovada": checar_custos}


def _carregar(p):
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "a.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-ar", str(SR), "-ac", "1", str(w)], check=True)
        with wave.open(str(w)) as f:
            return np.frombuffer(f.readframes(f.getnframes()), "<i2").astype(float) / 32768.0


def _rms_fala(x):
    """RMS só dos trechos com fala: até 30 dB abaixo do trecho mais alto do próprio arquivo (0 se for silêncio digital)."""
    n = int(SR * .02)
    j = [np.sqrt(np.mean(x[i:i + n] ** 2)) for i in range(0, len(x) - n, n)]
    if not j or max(j) < 10 ** (-90 / 20):
        return 0.0
    piso = max(j) * 10 ** (-30 / 20)
    j = [v for v in j if v >= piso]
    return float(np.sqrt(np.mean(np.square(j))))


def _ponto_quieto(x, t):
    n = int(SR * .02)
    if not 0 <= t <= len(x) / SR:
        raise ValueError(f"ponto {t:.2f} s fora da narração (0 a {len(x) / SR:.2f} s)")
    a, b = max(0, int((t - JANELA_BUSCA) * SR)), min(len(x) - n, int((t + JANELA_BUSCA) * SR))
    nivel, i = min((20 * np.log10(np.sqrt(np.mean(x[i:i + n] ** 2)) + 1e-12), i) for i in range(a, max(a + 1, b), n // 2))
    if nivel > SILENCIO_CORTE_DB:
        raise ValueError(f"nenhum silêncio a até {JANELA_BUSCA} s de {t:.2f} s (o mais quieto tem {nivel:.0f} dB): "
                         "a voz real cortaria a narração no meio da fala")
    return (i + n / 2) / SR


def _fade(x):
    n = min(int(FADE * SR), len(x) // 2)
    if n:
        x = x.copy()
        x[:n] *= np.linspace(0, 1, n)
        x[-n:] *= np.linspace(1, 0, n)
    return x


def montar(narracao_audio, insercoes, pausas, saida):
    """Faixa de voz da parte. Os tempos de entrada (perto_de, em) são da narração ORIGINAL; os de saída
    (segmentos, pausas) são da faixa montada.
    insercoes: [{"perto_de", "arquivo", "antes"?, "depois"?}]: a voz real entra no silêncio mais próximo,
    nivelada com a narração (até 12 dB) e com o pico limitado só nela; pausas: [{"em", "dur"}] (M23)."""
    x = _carregar(narracao_audio)
    for p in pausas:
        if not 0 <= p["em"] <= len(x) / SR:
            raise ValueError(f"pausa em {p['em']:.2f} s fora da narração (0 a {len(x) / SR:.2f} s)")
    alvo = _rms_fala(x)
    eventos = [("nat", _ponto_quieto(x, i["perto_de"]), i) for i in insercoes] + [("pausa", p["em"], p) for p in pausas]
    eventos.sort(key=lambda e: e[1])
    partes, segs, cortes, pausas_saida, deslocamentos = [], [], [], [], []
    t_saida, ini = 0.0, 0.0

    def poe(sinal, tipo=None):
        nonlocal t_saida
        if tipo:
            segs.append({"tipo": tipo, "ini": round(t_saida, 3), "fim": round(t_saida + len(sinal) / SR, 3)})
        partes.append(sinal)
        t_saida += len(sinal) / SR

    for tipo, t, ev in eventos:
        poe(_fade(x[int(ini * SR):int(t * SR)]), "narr")
        antes_do_evento = t_saida
        if tipo == "pausa":
            pausas_saida.append({"em": round(t_saida, 3), "dur": ev["dur"]})
            poe(np.zeros(int(ev["dur"] * SR)))
        else:
            cortes.append(round(t, 3))
            v = _carregar(ev["arquivo"])
            r = _rms_fala(v)
            if r <= 0:
                raise ValueError(f"voz real {ev['arquivo']} sem fala audível")
            if alvo > 0:
                ganho = 20 * np.log10(alvo / r)
                v = v * 10 ** (max(-GANHO_MAX_DB, min(GANHO_MAX_DB, ganho)) / 20)
            pico_v = np.abs(v).max()
            if pico_v > 0.98:  # o pico de uma voz real não abaixa a narração
                v = v / pico_v * 0.98
            poe(np.zeros(int(ev.get("antes", .7) * SR)))
            poe(_fade(v), "nat")
            poe(np.zeros(int(ev.get("depois", .8) * SR)))
        deslocamentos.append({"em": round(t, 3), "dur": round(t_saida - antes_do_evento, 3)})
        ini = t
    poe(_fade(x[int(ini * SR):]), "narr")
    y = np.clip(np.concatenate(partes), -0.98, 0.98)
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(saida), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return {"segmentos": [s for s in segs if s["fim"] > s["ini"]], "cortes": cortes, "pausas": pausas_saida,
            "deslocamentos": deslocamentos,
            "dur": round(len(y) / SR, 3)}


def conferir_narracao(audio, roteiro, idioma="pt"):
    """O que a voz gerada disse bate com o roteiro (sem as [tags])? Pega frase pulada ou trocada."""
    import difflib
    import re

    from scripts import vozes

    limpo = re.sub(r"\[[^\]]*\]", " ", roteiro)
    esperado = vozes._norm(limpo)
    dito = vozes._norm(" ".join(p[2] for p in vozes.transcrever(audio, idioma)))
    sem = difflib.SequenceMatcher(None, " ".join(dito), " ".join(esperado)).ratio()
    if sem < SEMELHANCA_ROTEIRO:
        raise ValueError(f"a narração gerada não bate com o roteiro (semelhança {sem:.2f}); ouça antes de usar")
    return {"semelhanca": round(sem, 3), "palavras_ditas": len(dito), "palavras_roteiro": len(esperado)}


def main(argv=None):
    """Uso:
      python -m scripts.narracao estimar <texto.txt> <estilo.json>
      python -m scripts.narracao gerar <texto.txt> <saida.mp3> <estilo.json> <00-custos.jsonl> --aprovado-por "..." [--item ...]"""
    import argparse

    p = argparse.ArgumentParser(prog="narracao")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimar"); e.add_argument("texto"); e.add_argument("estilo")
    g = sub.add_parser("gerar")
    for n in ("texto", "saida", "estilo", "custos"):
        g.add_argument(n)
    g.add_argument("--aprovado-por", required=True)
    g.add_argument("--creditos-aprovados", type=int, required=True)
    g.add_argument("--item", default="")
    a = p.parse_args(argv)
    texto = Path(a.texto).read_text(encoding="utf-8").strip()
    if a.cmd == "estimar":
        print(estimar(texto, a.estilo))
    else:
        print(gerar(texto, a.saida, a.estilo, a.custos, a.aprovado_por, a.creditos_aprovados, item=a.item))
    return 0


if __name__ == "__main__":
    sys.exit(main())
