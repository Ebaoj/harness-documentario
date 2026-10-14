"""Do roteiro ao esqueleto do plano (T24).

Quem planeja (o agente de código que opera o harness, ou uma pessoa) decide o que cada cena mostra; este módulo dá os
tempos: cada frase do roteiro alinhada às palavras que a voz disse, levada para o tempo da faixa montada
(descontando as vozes reais e as pausas inseridas), e um esqueleto de cenas contíguas de 3 s ou mais.
"""
import difflib
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):  # rodado como `python scripts/roteiro.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.vozes import _norm  # noqa: E402

MINIMO_DITO = 0.5   # uma frase precisa ter pelo menos metade das palavras reconhecidas na fala


ABREVIACOES = ("Dr", "Dra", "Sr", "Sra", "Srta", "Jr", "Mr", "Mrs", "Ms", "St", "Prof", "Lt", "Sgt", "Gen")


def _sentencas(texto):
    limpo = re.sub(r"\[[^\]]*\]", " ", texto)
    limpo = re.sub(r"\s+", " ", limpo).strip()
    for ab in ABREVIACOES:  # o ponto de um título não termina a frase
        limpo = re.sub(rf"\b{ab}\.\s", f"{ab}\u2024 ", limpo)
    limpo = re.sub(r"\b([A-Z])\.\s(?=[A-Z]\.)", "\\1\u2024 ", limpo)  # sigla soletrada: A. B. C. é uma frase só
    return [s.strip().replace("\u2024", ".") for s in re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"”»])\s+(?=[A-ZÀ-Ú\"“«\[])", limpo) if _norm(s)]


def _tokens_seq(itens):
    """[(texto, índice)] -> [(token, índice do começo, índice do fim)]. Letras maiúsculas soltas em sequência,
    mesmo em palavras separadas ('A.' 'B.' 'C.'), viram uma sigla só ('abc'); minúscula nunca entra na sigla."""
    brutos = []
    for texto, idx in itens:
        for w in re.sub(r"[^\w\s']", " ", texto).split():
            brutos.append((w, idx))
    out = []
    for w, idx in brutos:
        sigla = len(w) == 1 and w.isalpha() and w.isupper()
        if sigla and out and out[-1][3]:
            t, i0, _, _ = out[-1]
            out[-1] = (t + w.lower(), i0, idx, True)
        else:
            out.append((w.lower(), idx, idx, sigla))
    return [(t, i0, i1) for t, i0, i1, _ in out]


def _tokens(s):
    """Palavras normalizadas de um texto, com as siglas soletradas juntas."""
    return [t for t, _, _ in _tokens_seq([(s, 0)])]


def _fala_depois(audio, t0, limiar_db=-40, janela=0.05):
    """Primeiro e último instante com fala depois de t0, pela energia (sussurro que o transcritor não ouve)."""
    import numpy as np
    from scripts.narracao import SR, _carregar

    x = _carregar(audio)
    n = int(SR * janela)
    ativos = [i / SR for i in range(int(t0 * SR), len(x) - n, n)
              if 20 * np.log10(np.sqrt(np.mean(x[i:i + n] ** 2)) + 1e-12) > limiar_db]
    return (round(ativos[0], 3), round(ativos[-1] + janela, 3)) if ativos else None


def frases(texto, palavras, audio=None):
    """[{id, texto, ini, fim}] com os tempos da narração (o tempo das palavras recebidas).
    Com o áudio, a ÚLTIMA frase que o transcritor não reconheceu (ex.: um sussurro) recebe a fala que vier
    depois da última palavra, medida pela energia; frase do meio não reconhecida continua sendo erro."""
    sents = _sentencas(texto)
    script, dono = [], []
    for tok, k, _ in _tokens_seq([(s, k) for k, s in enumerate(sents)]):
        script.append(tok)
        dono.append(k)
    falado, palavra_de, palavra_ate = [], [], []
    for tok, i0, i1 in _tokens_seq([(p[2], i) for i, p in enumerate(palavras)]):
        falado.append(tok)
        palavra_de.append(i0)
        palavra_ate.append(i1)
    m = difflib.SequenceMatcher(None, script, falado, autojunk=False)
    par = {}
    for b in m.get_matching_blocks():
        for d in range(b.size):
            par[b.a + d] = b.b + d
    inicios, sussurro, fim_anterior = [], None, None
    for k, s in enumerate(sents):
        idx = [i for i, o in enumerate(dono) if o == k]
        if not idx:
            raise ValueError(f"frase sem palavras: {s!r}")
        casados = [i for i in idx if i in par]
        if len(casados) < MINIMO_DITO * len(idx):
            if k == len(sents) - 1 and k > 0 and audio is not None:
                # palavras erradas do sussurro no fim não são da frase anterior: ela acaba no último acerto
                ult = max(par[i] for i in range(len(script)) if dono[i] < k and i in par)
                fim_anterior = ult
                sussurro = _fala_depois(audio, palavras[palavra_ate[ult]][1] + 0.05)
                if sussurro:
                    sents = sents[:-1]
                    final = s
                    break
            raise ValueError(f"frase não foi dita (ou não foi reconhecida): {s!r}")
        antes = sum(1 for i in idx if i < casados[0])  # palavras do começo da frase que o transcritor errou
        ini = max(par[casados[0]] - antes, inicios[-1] + 1 if inicios else 0)
        inicios.append(ini)
    out = []
    for k, s in enumerate(sents):
        t0 = inicios[k]
        t1 = (inicios[k + 1] - 1) if k + 1 < len(sents) else (fim_anterior if fim_anterior is not None
                                                             else len(falado) - 1)
        w0, w1 = palavra_de[t0], palavra_ate[t1]
        out.append({"id": f"F{k + 1:02d}", "texto": s, "ini": palavras[w0][0], "fim": palavras[w1][1]})
    if sussurro:
        out.append({"id": f"F{len(out) + 1:02d}", "texto": final, "ini": sussurro[0], "fim": sussurro[1],
                    "pela_energia": True})
    return out


def tempo_na_faixa(t, montagem):
    """Tempo da narração original -> tempo da faixa montada (scripts.narracao.montar)."""
    desloc = montagem.get("deslocamentos")  # o que scripts.narracao.montar devolve (tempo de entrada)
    if desloc is None:
        raise ValueError("montagem sem deslocamentos: use o resultado de scripts.narracao.montar (tempos de entrada)")
    return round(t + sum(d["dur"] for d in desloc if d["em"] <= t), 3)


def esqueleto(fs, inicio, dur, minimo=3.0):
    """Cenas contíguas de inicio a dur, uma por frase (frases curtas se juntam à seguinte).
    inicio = onde a narração começa na parte (ex.: depois da cartela); os tempos das frases já na faixa."""
    if not fs:
        return {"dur": dur, "cenas": [{"id": "C01", "ini": inicio, "fim": dur, "frase": "", "componente": "", "fonte": ""}]}
    cortes = [inicio] + [round(inicio + f["ini"], 3) for f in fs[1:]] + [dur]
    grupos = [[f["texto"]] for f in fs]
    i = 0
    while i < len(grupos):
        if cortes[i + 1] - cortes[i] < minimo and len(grupos) > 1:
            if i + 1 < len(grupos):  # junta com a seguinte
                grupos[i] += grupos.pop(i + 1)
                cortes.pop(i + 1)
            else:  # a última junta com a anterior
                grupos[i - 1] += grupos.pop(i)
                cortes.pop(i)
                i -= 1
            continue
        i += 1
    cenas = [{"id": f"C{k + 1:02d}", "ini": cortes[k], "fim": cortes[k + 1], "frase": " ".join(g),
              "componente": "", "fonte": ""} for k, g in enumerate(grupos)]
    return {"dur": dur, "cenas": cenas}


def main(argv=None):
    """Uso: python -m scripts.roteiro <roteiro.txt> <palavras.json> <inicio> <dur> [montagem.json] > esqueleto.json
    palavras.json: [[ini, fim, texto], ...] da narração (scripts.vozes transcrever)."""
    a = argv if argv is not None else sys.argv[1:]
    if len(a) not in (4, 5):
        print(main.__doc__)
        return 2
    fs = frases(Path(a[0]).read_text(encoding="utf-8"), json.loads(Path(a[1]).read_text(encoding="utf-8")))
    if len(a) == 5:
        mont = json.loads(Path(a[4]).read_text(encoding="utf-8"))
        for f in fs:
            f["ini"], f["fim"] = tempo_na_faixa(f["ini"], mont), tempo_na_faixa(f["fim"], mont)
    print(json.dumps(esqueleto(fs, float(a[2]), float(a[3])), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
