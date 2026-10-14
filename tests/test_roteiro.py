import pytest

from scripts import plano, roteiro

# palavras da narração (tempo da narração original), como o transcritor devolve
PAL = [[0.1, 0.4, "Em"], [0.4, 0.9, "1963,"], [1.0, 1.3, "ele"], [1.3, 1.9, "se"], [1.9, 2.5, "formou."],
       [3.0, 3.5, "Tentou"], [3.5, 3.8, "a"], [3.8, 4.6, "faculdade."],
       [5.0, 5.4, "Mas,"], [5.4, 5.8, "nas"], [5.8, 6.2, "horas"], [6.2, 6.8, "vagas,"], [6.9, 7.3, "ele"], [7.3, 8.0, "dirigia."]]
TEXTO = "[low] Em 1963, ele se formou. Tentou a faculdade. [pause] Mas, nas horas vagas, ele dirigia."


def test_frases_do_roteiro_com_os_tempos_da_fala():
    fs = roteiro.frases(TEXTO, PAL)
    assert [f["texto"] for f in fs] == ["Em 1963, ele se formou.", "Tentou a faculdade.", "Mas, nas horas vagas, ele dirigia."]
    assert fs[0]["ini"] == 0.1 and fs[0]["fim"] == 2.5
    assert fs[1]["ini"] == 3.0 and fs[2]["fim"] == 8.0


def test_alinhamento_aguenta_palavra_transcrita_errada():
    """O transcritor erra palavras (ex.: 'facudade' para 'faculdade'); o alinhamento precisa aguentar."""
    pal = [list(p) for p in PAL]
    pal[7][2] = "facudade."
    fs = roteiro.frases(TEXTO, pal)
    assert fs[1]["fim"] == 4.6


def test_frase_que_nao_foi_dita_reprova():
    with pytest.raises(ValueError, match="não foi dita"):
        roteiro.frases(TEXTO + " Uma frase que a voz pulou inteira aqui.", PAL)


def test_tempo_na_faixa_desconta_vozes_e_pausas_inseridas():
    montagem = {"deslocamentos": [{"em": 2.7, "dur": 5.0}, {"em": 4.8, "dur": 1.0}]}
    assert roteiro.tempo_na_faixa(1.0, montagem) == 1.0
    assert roteiro.tempo_na_faixa(3.0, montagem) == 8.0
    assert roteiro.tempo_na_faixa(5.0, montagem) == 11.0


def test_esqueleto_cobre_a_parte_sem_buraco_e_junta_frases_curtas():
    fs = roteiro.frases(TEXTO, PAL)
    esq = roteiro.esqueleto(fs, inicio=3.6, dur=12.0)
    cenas = esq["cenas"]
    assert cenas[0]["ini"] == 3.6 and cenas[-1]["fim"] == 12.0
    assert all(c["fim"] - c["ini"] >= 3.0 for c in cenas)
    assert plano.checar_duracao({"plano": esq}) == []
    assert "Tentou a faculdade." in " ".join(c["frase"] for c in cenas)
    assert all(c["componente"] == "" and c["fonte"] == "" for c in cenas)  # preenchidos por quem planeja


def test_tempo_na_faixa_exige_os_deslocamentos_da_montagem():
    with pytest.raises(ValueError, match="deslocamentos"):
        roteiro.tempo_na_faixa(1.0, {"pausas": [{"em": 1, "dur": 1}]})


def test_abreviacao_nao_quebra_a_frase():
    texto = "O Dr. Silva chegou. Ele saiu."
    pal = [[0.0, 0.2, "O"], [0.2, 0.5, "Dr."], [0.5, 0.9, "Silva"], [0.9, 1.4, "chegou."], [1.6, 1.9, "Ele"], [1.9, 2.3, "saiu."]]
    fs = roteiro.frases(texto, pal)
    assert [f["texto"] for f in fs] == ["O Dr. Silva chegou.", "Ele saiu."]


def test_frase_repetida_no_roteiro_casa_cada_ocorrencia_no_seu_lugar():
    texto = "Ele esperou. Nada aconteceu. Ele esperou."
    pal = [[0, .4, "Ele"], [.4, 1, "esperou."], [1.2, 1.5, "Nada"], [1.5, 2.2, "aconteceu."], [2.5, 2.8, "Ele"], [2.8, 3.4, "esperou."]]
    fs = roteiro.frases(texto, pal)
    assert [f["ini"] for f in fs] == [0, 1.2, 2.5]


def test_sigla_soletrada_com_pontos_e_uma_frase_so():
    """'[whispers] A. B. C.' virava três frases; o transcritor ouve 'ABC'."""
    texto = "E dava a si mesmo um nome. [whispers] A. B. C."
    pal = [[0, .2, "E"], [.2, .5, "dava"], [.5, .6, "a"], [.6, .8, "si"], [.8, 1.1, "mesmo"], [1.1, 1.3, "um"],
           [1.3, 1.8, "nome."], [2.5, 3.5, "ABC."]]
    fs = roteiro.frases(texto, pal)
    assert [f["texto"] for f in fs] == ["E dava a si mesmo um nome.", "A. B. C."]
    assert fs[1]["ini"] == 2.5


def test_sussurro_final_nao_transcrito_sai_da_energia_do_audio(tmp_path):
    """o '[whispers] A. B. C.' está no áudio, mas o transcritor não ouve."""
    import wave
    import numpy as np
    sr = 44100
    x = np.zeros(int(sr * 4.0))
    for a in (2.6, 3.1):  # duas rajadas de 'sussurro' depois da última palavra
        x[int(a * sr):int((a + 0.3) * sr)] = 0.05 * np.sin(2 * np.pi * 900 * np.arange(int(0.3 * sr)) / sr)
    with wave.open(str(tmp_path / "n.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    texto = "E dava a si mesmo um nome. [whispers] A. B. C."
    pal = [[0, .2, "E"], [.2, .5, "dava"], [.5, .6, "a"], [.6, .8, "si"], [.8, 1.1, "mesmo"], [1.1, 1.3, "um"], [1.3, 1.8, "nome."]]
    with pytest.raises(ValueError):
        roteiro.frases(texto, pal)
    fs = roteiro.frases(texto, pal, audio=tmp_path / "n.wav")
    assert fs[1]["ini"] == pytest.approx(2.6, abs=0.06) and fs[1]["fim"] == pytest.approx(3.4, abs=0.06)


# --- correções da revisão (10/10/2026) ----------------------------------------


def test_sigla_transcrita_letra_por_letra_tambem_casa():
    """Revisão: o whisper costuma dar 'A.', 'B.', 'C.' separados; só casava 'ABC' numa palavra."""
    texto = "E dava a si mesmo um nome. A. B. C."
    pal = [[0, .2, "E"], [.2, .5, "dava"], [.5, .6, "a"], [.6, .8, "si"], [.8, 1.1, "mesmo"], [1.1, 1.3, "um"],
           [1.3, 1.8, "nome."], [2.5, 2.8, "A."], [3.0, 3.3, "B."], [3.5, 3.9, "C."]]
    fs = roteiro.frases(texto, pal)
    assert fs[1]["ini"] == 2.5 and fs[1]["fim"] == 3.9


def test_letra_maiuscula_seguida_de_artigo_nao_vira_sigla():
    """Revisão: 'a letra B e o C' virava o token 'beoc'."""
    assert roteiro._tokens("a letra B e o C") == ["a", "letra", "b", "e", "o", "c"]
    assert roteiro._tokens("o plano B e a vitamina D") == ["o", "plano", "b", "e", "a", "vitamina", "d"]


def test_sussurro_transcrito_errado_nao_estica_a_frase_anterior(tmp_path):
    """Revisão: palavras erradas do sussurro ficavam no fim e a frase anterior se esticava por cima dele."""
    import wave
    import numpy as np
    sr = 44100
    x = np.zeros(int(sr * 4.0))
    for a in (2.6, 3.1):
        x[int(a * sr):int((a + 0.3) * sr)] = 0.05 * np.sin(2 * np.pi * 900 * np.arange(int(0.3 * sr)) / sr)
    with wave.open(str(tmp_path / "n.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    texto = "E dava a si mesmo um nome. [whispers] A. B. C."
    pal = [[0, .2, "E"], [.2, .5, "dava"], [.5, .6, "a"], [.6, .8, "si"], [.8, 1.1, "mesmo"], [1.1, 1.3, "um"],
           [1.3, 1.8, "nome."], [2.6, 3.4, "bitcoin"]]
    fs = roteiro.frases(texto, pal, audio=tmp_path / "n.wav")
    assert fs[0]["fim"] == 1.8
    assert fs[1]["ini"] == pytest.approx(2.6, abs=0.06)


def test_frase_que_termina_em_aspas_e_separada_da_seguinte():
    """Capítulo 4: '...atenção nacional?" Naquela tarde...' virava uma frase só."""
    texto = 'E perguntava: "Quantos eu preciso matar?" Naquela tarde, a cidade ouviu.'
    assert roteiro._sentencas(texto) == ['E perguntava: "Quantos eu preciso matar?"', "Naquela tarde, a cidade ouviu."]


def test_citacao_no_meio_da_frase_nao_divide():
    """Revisão: 'Ele gritou "Pare!" e correu.' virava duas frases."""
    assert roteiro._sentencas('Ele gritou "Pare!" e correu.') == ['Ele gritou "Pare!" e correu.']
    assert roteiro._sentencas('O apelido "A. B. C." veio depois.') == ['O apelido "A. B. C." veio depois.']
