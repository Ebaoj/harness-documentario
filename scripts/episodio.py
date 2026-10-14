"""Produção de um episódio de ponta a ponta (T24/T26): um comando por parte, um para montar.

parte:  confere o catálogo e o plano (regras do modelo), gera as cenas, renderiza o vídeo mudo e mixa o som
        cru; para no primeiro erro de regra, antes de gastar tempo de render.
montar: junta as partes (scripts.entrega: emendas, volume), guarda em versoes/, faz a cópia para WhatsApp.
Os avisos que não impedem produzir (licença a confirmar) aparecem no relatório; publicar é sempre manual.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):  # rodado como `python scripts/episodio.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import cenas, entrega, fontes, plano, registro, render, som  # noqa: E402

AVISOS = ("licença pendente",)  # não impedem produzir; impedem publicar (revisão jurídica)


_NOME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _impressao(plano_json):
    return hashlib.sha256(Path(plano_json).read_bytes()).hexdigest()[:12]


def aprovar_plano(pasta_ep, plano_json, nota):
    """Registra o aprovado humano (portão 'plano') preso à versão exata do arquivo do plano."""
    registro.registrar_aprovacao(pasta_ep, "plano", True, f"plano {Path(plano_json).name} sha {_impressao(plano_json)}: {nota}")


def _aprovado(pasta_ep, plano_json):
    sha = f"sha {_impressao(plano_json)}"
    dec = [e for e in registro._ler(pasta_ep, "aprovacoes.jsonl")
           if e["portao"] == "plano" and e.get("por") == registro.AUTOR_HUMANO and sha in e["nota"]]
    return bool(dec) and dec[-1]["aprovado"]


def _conferir(pasta_ep, p, palavras_json):
    cat = json.loads((pasta_ep / "fontes.json").read_text(encoding="utf-8"))
    erros_cat = fontes.validar(cat)
    avisos = [e for e in erros_cat if any(a in e for a in AVISOS)]
    bloqueios = [e for e in erros_cat if e not in avisos]
    palavras = json.loads(Path(palavras_json).read_text(encoding="utf-8")) if palavras_json else {}
    if not isinstance(palavras, dict):
        raise ValueError("--palavras espera {fonte de voz: [[ini, fim, texto], ...]}; "
                         "a lista simples é o formato do scripts.roteiro")
    for k in ("dur", "som"):
        if k not in p:
            bloqueios.append(f"plano sem {k!r} (o som e a duração da parte vêm do plano)")
    bloqueios += plano.validar({"plano": p, "fontes": cat["fontes"], "palavras": palavras})
    if bloqueios:
        raise ValueError("o plano não passa nas regras:\n  " + "\n  ".join(bloqueios))
    return avisos


def prancha(pasta_ep, plano_json, estilo, nome):
    """Um quadro do meio de cada cena numa folha só: o que o revisor humano olha para aprovar o plano, sem render."""
    from PIL import Image

    pasta_ep = Path(pasta_ep)
    p = json.loads(Path(plano_json).read_text(encoding="utf-8"))
    html = cenas.gerar(pasta_ep, p, estilo, pasta_ep / "04-cenas" / f"{nome}.html")
    meios = [round((c["ini"] + c["fim"]) / 2, 2) for c in sorted(p["cenas"], key=lambda c: c["ini"])]
    pngs = render.previa(html, meios, pasta_ep / "07-saida" / f"prancha-{nome}")
    ims = [Image.open(f).convert("RGB").resize((480, 270)) for f in pngs]
    cols = 4
    folha = Image.new("RGB", (cols * 484, ((len(ims) + cols - 1) // cols) * 274), "gray")
    for i, im in enumerate(ims):
        folha.paste(im, ((i % cols) * 484, (i // cols) * 274))
    saida = pasta_ep / "07-saida" / f"prancha-{nome}.jpg"
    folha.save(saida, quality=85)
    for f in pngs:
        f.unlink()
    return saida


def produzir_parte(pasta_ep, plano_json, estilo, nome, fps=30, palavras_json=None, log=print):
    """Valida e produz a parte. Só renderiza um plano aprovado por um humano nesta versão exata (aprovar_plano)."""
    if not _NOME.match(nome or ""):
        raise ValueError(f"nome de parte inválido {nome!r}: letras, números, _ e -")
    pasta_ep = Path(pasta_ep)
    p = json.loads(Path(plano_json).read_text(encoding="utf-8"))
    avisos = _conferir(pasta_ep, p, palavras_json)
    if not _aprovado(pasta_ep, plano_json):
        raise PermissionError(f"plano {Path(plano_json).name} sem aprovação humana nesta versão: "
                              "mostre a prancha (episodio prancha) e registre o aprovado (episodio aprovar)")
    saida = pasta_ep / "07-saida"
    html = cenas.gerar(pasta_ep, p, estilo, pasta_ep / "04-cenas" / f"{nome}.html")
    log(f"{nome}: cenas geradas em {html}")
    video = saida / f"{nome}-mudo.mp4"
    rel = render.renderizar(html, video, fps=fps, cache=saida / ".cache-render", log=log)
    log(f"{nome}: {rel['quadros']} quadros, {len(rel['renderizadas'])} renderizadas, {len(rel['do_cache'])} do cache")
    audio = som.mixar(pasta_ep, p, estilo, saida / f"{nome}-cru.wav")
    folga = json.loads(audio.with_suffix(".folga.json").read_text(encoding="utf-8"))
    erros = som.checar_folga({"folgas": [folga]})  # M32: a trilha não pode cobrir a fala
    if erros:
        raise ValueError("a mixagem não passa nas regras:\n  " + "\n  ".join(erros))
    log(f"{nome}: som em {audio} (folga {folga['pior']} dB, alvo {folga['alvo']} dB)")
    return {"video": video, "audio": audio, "avisos": avisos, "render": rel}


def _tipo(pasta_ep, nome):
    p = Path(pasta_ep) / nome / "02-plano" / "plano.json"
    return json.loads(p.read_text(encoding="utf-8")).get("tipo") if p.exists() else None


def montar(pasta_ep, nomes, versao, abrir=False, inicio=None):
    pasta_ep = Path(pasta_ep)
    saida = pasta_ep / "07-saida"
    partes = [(saida / f"{n}-mudo.mp4", saida / f"{n}-cru.wav") for n in nomes]
    for v, a in partes:
        for f in (v, a):
            if not f.exists():
                raise FileNotFoundError(f"parte não produzida: {f} (rode episodio parte)")
    final = saida / f"{versao}.mp4"
    # a história termina em fade e o encerramento começa do zero: essa emenda tem silêncio de propósito
    livres = [i for i, n in enumerate(nomes) if i and _tipo(pasta_ep, n) == "encerramento"]
    rel = entrega.montar(partes, final, silencios_permitidos=livres)
    guardado = entrega.versionar(final, pasta_ep / "versoes", versao)
    wpp = entrega.whatsapp_partes(final, saida / f"{versao}-whatsapp.mp4", cortes=rel.get("emendas", ()))
    if abrir:
        entrega.abrir(guardado, inicio)
    return {**rel, "versao": guardado, "whatsapp": wpp}


def main(argv=None):
    """Uso:
      python -m scripts.episodio prancha <episódio> <plano.json> <estilo.json> <nome>
      python -m scripts.episodio aprovar <episódio> <plano.json> "<nota com a frase de quem aprovou>"
      python -m scripts.episodio parte <episódio> <plano.json> <estilo.json> <nome> [--palavras p.json] [--fps 30]
      python -m scripts.episodio montar <episódio> <versão> <nome1> [<nome2> ...] [--abrir] [--inicio s]"""
    import argparse

    a = argparse.ArgumentParser(prog="episodio")
    sub = a.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("parte")
    for n in ("episodio", "plano", "estilo", "nome"):
        pa.add_argument(n)
    pa.add_argument("--palavras")
    pa.add_argument("--fps", type=int, default=30)
    pr = sub.add_parser("prancha")
    for n in ("episodio", "plano", "estilo", "nome"):
        pr.add_argument(n)
    ap = sub.add_parser("aprovar")
    ap.add_argument("episodio"); ap.add_argument("plano"); ap.add_argument("nota")
    mo = sub.add_parser("montar")
    mo.add_argument("episodio"); mo.add_argument("versao"); mo.add_argument("nomes", nargs="+")
    mo.add_argument("--abrir", action="store_true"); mo.add_argument("--inicio", type=float)
    a = a.parse_args(argv)
    if a.cmd == "prancha":
        print(prancha(a.episodio, a.plano, a.estilo, a.nome))
        return 0
    if a.cmd == "aprovar":
        aprovar_plano(a.episodio, a.plano, a.nota)
        print("aprovado:", a.plano, _impressao(a.plano))
        return 0
    if a.cmd == "parte":
        r = produzir_parte(a.episodio, a.plano, a.estilo, a.nome, a.fps, a.palavras)
        for av in r["avisos"]:
            print("AVISO (impede publicar):", av)
    else:
        r = montar(a.episodio, a.nomes, a.versao, a.abrir, a.inicio)
        print(f"{r['versao']}: emendas {r['emendas']}, {r['lufs']} LUFS; WhatsApp em {', '.join(str(w) for w in r['whatsapp'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
