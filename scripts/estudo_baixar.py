"""Baixa um vídeo de referência em baixa resolução, com a legenda no idioma original.

A mídia é só para análise local: fica em referencias/<canal>/<id>/midia/ e nunca entra no git.
Sem legenda não se gasta com transcrição paga: registra `sem_transcricao` e segue.
"""
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
YTDLP = str(RAIZ / ".venv" / "bin" / "yt-dlp")  # o yt-dlp do sistema toma 403
FORMATO = "bv*[height<=360]+ba/b[height<=360]/worst"
EXT_LEGENDA = (".json3", ".vtt")


def pasta_midia(raiz, canal, video_id):
    return Path(raiz) / canal / video_id / "midia"


def montar_comando(video_id, destino, idioma, recorte_s=None):
    secao = ["--download-sections", f"*0-{int(recorte_s)}"] if recorte_s else []
    cmd = [
        YTDLP,
        "-f", FORMATO,
        "--merge-output-format", "mp4",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", f"{idioma},{idioma}-orig",
        "--sub-format", "json3/vtt",
        "--ignore-errors", "--no-playlist", "--no-progress", "--no-warnings",
        "-o", f"{destino}/%(id)s.%(ext)s",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    if secao:  # a URL continua sendo o último argumento
        cmd[1:1] = secao
    return cmd


def _executar(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return 124, "yt-dlp demorou mais de 30 minutos"
    return r.returncode, (r.stderr or r.stdout)[-1500:]


def _achar(destino, video_id, extensoes):
    achados = sorted(p for p in Path(destino).glob(f"{video_id}*") if p.suffix in extensoes)
    return achados[0].name if achados else None


def baixar_video(video_id, destino, idioma, runner=_executar, recorte_s=None):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    codigo, saida = runner(montar_comando(video_id, destino, idioma, recorte_s))
    video = _achar(destino, video_id, (".mp4", ".mkv", ".webm"))
    legenda = _achar(destino, video_id, EXT_LEGENDA)
    if codigo != 0 and not video:
        r = {"video_id": video_id, "status": "erro", "erro": saida.strip()[-500:]}
    elif not legenda:
        r = {"video_id": video_id, "status": "sem_transcricao", "video": video}
        if codigo != 0:  # falha temporária na legenda (429, por exemplo) não é ausência de legenda
            r["motivo"] = saida.strip()[-300:]
    else:
        r = {"video_id": video_id, "status": "ok", "video": video, "legenda": legenda}
    if recorte_s:
        r["recorte_s"] = recorte_s
    (destino / "status.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    return r


def main(argv=None):
    """estudo_baixar.py <canal-slug> <video_id> <idioma>"""
    argv = argv or sys.argv[1:]
    canal, vid, idioma = argv[:3]
    r = baixar_video(vid, pasta_midia(RAIZ / "referencias", canal, vid), idioma)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r["status"] != "erro" else 1


if __name__ == "__main__":
    sys.exit(main())
