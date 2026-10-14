"""Orquestra o estudo de canais de referência: lista -> amostra -> download -> métricas -> ficha -> padrões.

Uso: estudo_pipeline.py <etapa> [canal-slug ...]
Etapas: listar, amostrar, baixar, metricas, fichas, padroes
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts import estudo_amostra, estudo_baixar, estudo_ficha, estudo_metricas, estudo_padroes

RAIZ = Path(__file__).resolve().parent.parent / "referencias"
RECORTE_S = 1500  # vídeo com mais de 40 min (compilações de horas): só os primeiros 25 min entram no estudo
LIMITE_RECORTE_S = 2400
PARALELO = 3  # respeita a plataforma: no máximo 3 downloads ao mesmo tempo


def carregar_canais(raiz=RAIZ):
    return json.loads((Path(raiz) / "canais.json").read_text())["canais"]


def listar(raiz, canal, ate=40):
    saida = subprocess.run(
        [estudo_baixar.YTDLP, "--flat-playlist", "--playlist-end", str(ate), "--dump-json",
         f"https://www.youtube.com/channel/{canal['id']}/videos"],
        capture_output=True, text=True, timeout=300).stdout
    itens = []
    for linha in saida.splitlines():
        d = json.loads(linha)
        itens.append({k: d.get(k) for k in ("id", "title", "duration", "view_count")})
    (Path(raiz) / canal["slug"]).mkdir(parents=True, exist_ok=True)
    (Path(raiz) / canal["slug"] / "lista.json").write_text(json.dumps(itens, ensure_ascii=False, indent=1))
    return itens


def amostrar(raiz, canal, n_melhores=2, n_base=2):
    pasta = Path(raiz) / canal["slug"]
    escolhidos = estudo_amostra.escolher(json.loads((pasta / "lista.json").read_text()), n_melhores, n_base)
    (pasta / "amostra.json").write_text(json.dumps(escolhidos, ensure_ascii=False, indent=1))
    return escolhidos


def baixar_todos(raiz, tarefas, baixar=estudo_baixar.baixar_video):
    """tarefas: [(slug, video, idioma)]."""
    def um(t):
        slug, v, idioma = t
        recorte = RECORTE_S if (v.get("duracao_s") or 0) > LIMITE_RECORTE_S else None
        return baixar(v["id"], estudo_baixar.pasta_midia(raiz, slug, v["id"]), idioma, recorte_s=recorte)

    with ThreadPoolExecutor(max_workers=PARALELO) as ex:
        return list(ex.map(um, tarefas))


def main(argv=None):
    argv = argv or sys.argv[1:]
    etapa, filtro = argv[0], set(argv[1:])
    canais = [c for c in carregar_canais() if not filtro or c["slug"] in filtro]
    if etapa == "listar":
        for c in canais:
            print(c["slug"], len(listar(RAIZ, c)))
    elif etapa == "amostrar":
        for c in canais:
            print(c["slug"], [v["id"] for v in amostrar(RAIZ, c)])
    elif etapa == "baixar":
        tarefas = [(c["slug"], v, c["idioma"]) for c in canais
                   for v in json.loads((RAIZ / c["slug"] / "amostra.json").read_text())]
        for r in baixar_todos(RAIZ, tarefas):
            print(json.dumps(r, ensure_ascii=False))
    elif etapa == "metricas":
        for c in canais:
            for v in json.loads((RAIZ / c["slug"] / "amostra.json").read_text()):
                pasta = RAIZ / c["slug"] / v["id"]
                try:
                    estudo_metricas.analisar(pasta)
                    print("ok", c["slug"], v["id"])
                except Exception as e:  # um vídeo ruim não derruba o lote
                    print("ERRO", c["slug"], v["id"], e)
    elif etapa == "fichas":
        for c in canais:
            for v in json.loads((RAIZ / c["slug"] / "amostra.json").read_text()):
                pasta = RAIZ / c["slug"] / v["id"]
                if not (pasta / "midia" / "transcricao.json").exists():
                    print("sem_transcricao", c["slug"], v["id"])
                    continue
                try:
                    estudo_ficha.main([str(pasta), c["idioma"]])
                except Exception as e:
                    print("ERRO", c["slug"], v["id"], e)
    elif etapa == "padroes":
        return estudo_padroes.main()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
