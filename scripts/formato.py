"""Formato de vídeo padrão do harness (decisão de produto, 12/10/2026).

Compressão pelo chip de vídeo do Mac (VideoToolbox) em vez do x264 na CPU: no M1 foi dez vezes mais rápido,
com o mesmo tamanho e qualidade quase igual (SSIM 0,980 contra 0,984 num trecho de 20 s) e saída idêntica
quadro a quadro entre execuções, também com o chip disputado. Sem B-frames, 1080p, faixa de cor limitada
(a entrada do render é JPEG, de faixa cheia: sem normalizar, emendar por cópia trocaria o contraste).
A montagem só copia o vídeo de uma parte que confere com ESPECIFICACAO; o resto é convertido uma vez.
Mudou CODIFICADOR ou ESPECIFICACAO: mude FORMATO (a etiqueta entra nas chaves de cache).
"""
FORMATO = "harness-h264-vt20m-1080-tv"
LARGURA, ALTURA, FPS = 1920, 1080, 30
CODIFICADOR = ["-vf", f"scale={LARGURA}:{ALTURA}:out_range=tv,format=yuv420p", "-c:v", "h264_videotoolbox",
               "-b:v", "20M", "-profile:v", "high", "-bf", "0", "-pix_fmt", "yuv420p", "-color_range", "tv"]
# o que precisa ser igual em todas as partes para emendar por cópia (ffprobe, stream de vídeo)
ESPECIFICACAO = {"codec_name": "h264", "width": LARGURA, "height": ALTURA, "r_frame_rate": f"{FPS}/1",
                 "has_b_frames": 0, "pix_fmt": "yuv420p", "color_range": ("tv", "unknown")}  # sem marca = limitada
