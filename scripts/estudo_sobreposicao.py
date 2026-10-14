"""Sobreposição literal entre um texto novo e uma transcrição de referência (R16).

Aprendemos o padrão, nunca copiamos o texto: um trecho de roteiro com `n` palavras seguidas iguais às da
transcrição de referência deve ser reescrito. A comparação ignora caixa e pontuação.
"""
import unicodedata


def normalizar_palavras(texto):
    """Palavras em minúsculas, sem pontuação nem símbolos. Não usa `\\w+`: ele parte hindi nas matras
    (combining marks), e uma palavra como "चलिए" viraria letras soltas."""
    limpo = "".join(" " if unicodedata.category(c)[0] in "PSZC" else c for c in (texto or ""))
    return [p.casefold() for p in limpo.split()]


def sobreposicao_literal(texto_novo, transcricao_ref, n=8):
    """Trechos maximais de pelo menos `n` palavras iguais nos dois textos.

    Devolve uma lista de {"trecho", "tamanho", "pos_novo", "pos_ref"} (posições em palavras normalizadas).
    Lista vazia = sem sobreposição relevante.
    """
    if n < 1:
        raise ValueError("n precisa ser pelo menos 1")
    novo = normalizar_palavras(texto_novo)
    ref = normalizar_palavras(transcricao_ref)
    if len(novo) < n or len(ref) < n:
        return []
    indice = {}
    for j in range(len(ref) - n + 1):
        indice.setdefault(tuple(ref[j : j + n]), []).append(j)
    achados = []
    i = 0
    while i <= len(novo) - n:
        posicoes = indice.get(tuple(novo[i : i + n]))
        if not posicoes:
            i += 1
            continue
        melhor = (0, 0)
        for j in posicoes:  # estende cada candidato o máximo possível e guarda o maior
            k = n
            while i + k < len(novo) and j + k < len(ref) and novo[i + k] == ref[j + k]:
                k += 1
            if k > melhor[0]:
                melhor = (k, j)
        tamanho, j = melhor
        achados.append({"trecho": " ".join(novo[i : i + tamanho]), "tamanho": tamanho, "pos_novo": i, "pos_ref": j})
        i += tamanho
    return achados


def tem_sobreposicao(texto_novo, transcricao_ref, n=8):
    return bool(sobreposicao_literal(texto_novo, transcricao_ref, n))
