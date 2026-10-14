from scripts.estudo_sobreposicao import normalizar_palavras, sobreposicao_literal

REF = "Em 1994 o plano mudou a vida de milhões de pessoas, e ninguém acreditava que daria certo naquela época."


def test_normaliza_caixa_e_pontuacao():
    assert normalizar_palavras("Olá, Mundo! Tudo-bem?") == ["olá", "mundo", "tudo", "bem"]


def test_detecta_sequencia_de_oito_palavras_iguais():
    novo = "Hoje sabemos que o plano mudou a vida de milhões de pessoas, segundo todos."
    achados = sobreposicao_literal(novo, REF, n=8)
    assert len(achados) == 1
    assert achados[0]["tamanho"] >= 8
    assert "plano mudou a vida" in achados[0]["trecho"]


def test_sete_palavras_nao_dispara():
    novo = "o plano mudou a vida de milhões, mas outra coisa aconteceu depois."
    assert sobreposicao_literal(novo, REF, n=8) == []


def test_ignora_caixa_e_pontuacao_na_comparacao():
    novo = "O PLANO, mudou: a vida; de milhões de pessoas e ninguém"
    assert sobreposicao_literal(novo, REF, n=8) != []


def test_funde_sequencias_vizinhas_em_um_trecho_maximal():
    ref = "a b c d e f g h i j k l"
    novo = "x a b c d e f g h i j y"
    achados = sobreposicao_literal(novo, ref, n=8)
    assert len(achados) == 1 and achados[0]["tamanho"] == 10


def test_texto_vazio_ou_curto_nao_quebra():
    assert sobreposicao_literal("", REF) == []
    assert sobreposicao_literal("oi", REF) == []
    assert sobreposicao_literal("oi", "") == []


def test_n_invalido():
    import pytest
    with pytest.raises(ValueError):
        sobreposicao_literal("a b", "a b", n=0)


def test_hindi_nao_perde_as_matras():
    # \w+ partia "चलिए" em letras soltas; a comparação precisa guardar a palavra inteira
    assert normalizar_palavras("तो चलिए शुरू करते हैं।") == ["तो", "चलिए", "शुरू", "करते", "हैं"]


def test_sobreposicao_em_hindi_e_detectada():
    ref = "साल 1845 आयरलैंड कल्पना कीजिए एक गरीब किसान सुबह उठता है और खेत देखता है"
    novo = "आयरलैंड कल्पना कीजिए एक गरीब किसान सुबह उठता है और कुछ नया"
    assert sobreposicao_literal(novo, ref, n=8) != []


def test_default_de_n_e_oito_palavras():
    ref = "um dois três quatro cinco seis sete oito nove dez"
    exatamente_oito = "antes um dois três quatro cinco seis sete oito depois"
    assert sobreposicao_literal(exatamente_oito, ref) != []  # sem passar n: o default pega 8
    sete = "antes um dois três quatro cinco seis sete depois"
    assert sobreposicao_literal(sete, ref) == []
