# harness-documentario

A video editing harness for long-form documentaries. You give it a narration (voice-over audio plus word timings) and a scene plan (JSON); it renders an edited 1080p video: motion graphics built in HTML/SVG and captured frame by frame with Playwright/Chromium, archive clips and photos with camera moves, maps, life timelines, subtitles for third-party voices, music ducked under the voice, sober synthesized sound effects, and an ffmpeg assembly with integer frame counts and one loudness normalization for the whole video.

Every step is checked by a rule verifier (rules M01 to M37) and gated: nothing renders without a human approval tied to the exact plan file, and nothing paid runs without a cost estimate and a recorded approval.

Code comments, docstrings and CLI messages are in Portuguese. File and field names are Portuguese too (`plano.json`, `fontes.json`, `cenas`, `ini`, `fim`).

## Pipeline

```
narration -> word timings -> plan -> storyboard ("prancha") -> approval -> render -> mix -> assembly -> delivery
```

1. **Narration.** `scripts.narracao estimar` estimates TTS credits; `gerar` calls ElevenLabs only with `--aprovado-por` and `--creditos-aprovados`, logging the attempt before the call. You can also bring your own recorded narration. `narracao.montar` builds the part's voice track: third-party voice clips are inserted at the nearest silence, leveled to the narration, and dramatic pauses are cut into the audio without regenerating it.
2. **Word timings.** `scripts.vozes transcrever` runs a local whisper.cpp (`whisper-cli`) and returns `[[start, end, word], ...]`, with word starts corrected by audio energy. `vozes cortar` cuts third-party voice clips and re-transcribes the cut to confirm it starts and ends on the expected words (sha256 recorded).
3. **Plan.** `scripts.roteiro` aligns each script sentence to the spoken words and emits a skeleton of contiguous scenes of 3 s or more. Whoever plans (a person or a coding agent) fills in what each scene shows: component, source, camera, texts.
4. **Storyboard.** `scripts.episodio prancha` renders one frame from the middle of each scene into a contact sheet (JPEG), without rendering video.
5. **Approval.** `scripts.episodio aprovar` records a human approval bound to the sha256 of the plan file. Edit the plan and the approval no longer counts.
6. **Render.** `scripts.render` opens the generated HTML in headless Chromium with the network blocked, drives a virtual clock (`window.render(T)`), waits for every image to decode, and pipes JPEG frames to ffmpeg. Each scene is a cached segment keyed by a fingerprint of everything that changes its pixels, so editing one scene re-renders only that scene.
7. **Mix.** `scripts.som` mixes voice, music and effects into a raw mono WAV with the exact duration of the part. Music sits at a constant level per speech region, a configured margin below the voice; the measured margin is written next to the mix and checked.
8. **Assembly.** `scripts.entrega montar` joins parts by stream copy (no re-encode when the format matches), rejects tracks whose length differs from the video and digital silence at a seam, and normalizes loudness once for the whole video (two-pass loudnorm, linear, target -14 LUFS, -1.5 dBTP).
9. **Delivery.** Versions are stored under `versoes/` and never overwritten; a small copy for messaging apps is produced (split at seams if needed); the file opens in a player with a visible window.

`scripts.episodio parte` chains validation, scene generation, render and mix for one part, and stops at the first rule failure before spending render time.

## Scene components

Defined in `motion/componentes.js`, whitelisted in `scripts/cenas.py` (`COMPONENTES`). Every component is a pure function of time; nothing uses a wall clock, so renders are deterministic.

| Component | What it shows |
|---|---|
| `foto` | Full-screen photo with a slow camera move (zoom and pan keyframes), optional credit |
| `retrato` | Portrait in a paper frame, optionally cross-fading to another photo |
| `fotoFato` | Portrait on the left, facts in the right margin (text never over the image) |
| `arquivo` | Archive clip in a framed window over its own blurred frame, scan lines, source label, speed control |
| `mural` | Wall of documents; the camera moves card to card, with red circles drawn on cue |
| `mapa` | Land outline (Natural Earth 110m) with a dashed route from an origin to points, in narration order |
| `linhaVida` | Life timeline: real photos placed on their years, camera travels across years, chapter title card |
| `lista` | Portrait plus an itemized list revealed on cue, with an optional stamp |
| `chamada` | End screen: animated subscribe button click, like, next-episode teaser |

Layers available on any scene: margin facts, typed or faded texts, the "AI reconstruction" label, a "voice of" label, subtitles from word timings, a persistent chapter guide at the top, film grain and vignette. Colors and fonts come only from the channel style (`canais/<channel>/estilo.json`).

## Rule verifier

Rules live in `canais/<channel>/modelo/regras.json`. Each rule records where it came from (date and the review note that created it) and how it is checked: `auto` (a registered function), `planejada` (planned to become automatic) or `manual` (goes to the human review checklist). `python -m scripts.modelo validar` fails on unknown functions, malformed rules or any open feedback item. Automatic checks are implemented in `scripts/plano.py`, `scripts/fontes.py`, `scripts/vozes.py`, `scripts/narracao.py`, `scripts/som.py` and `scripts/entrega.py`.

Automatic:

- **M01** every scene lasts at least 3 s; no gaps or overlaps between scenes.
- **M02** real footage covers at least 51% of screen time, and no 15 s window drops below 30% (end screen exempt).
- **M03** "real" means material from the story itself; stock and AI images never count.
- **M04** no text over real video unless the plan declares the intent.
- **M06** the accused's face does not appear before the reveal point.
- **M07** each scene shows what its sentence mentions (whole-word match against source tags).
- **M08** AI images carry an on-screen reconstruction label, a recorded prompt, and no real faces.
- **M10** an interview is on screen only while that person's own voice plays, lip-synced within 0.1 s.
- **M11** subtitles start at sentence starts and end within 0.3 s of the last word.
- **M12** every third-party voice cut is re-transcribed and verified; the record is bound to the file hash.
- **M13** a person appears only with a confirmed identity and how it was confirmed.
- **M14** every clip is classified (TV archive, interview, reenactment, ...); reenactments never carry a person's name.
- **M15** speed changes never run past the useful range of a clip.
- **M16** uninvolved living people (bystanders, audience) must have their eyes blurred.
- **M24** every paid TTS call has a recorded approval.
- **M28** each part's audio matches its video length; no digital silence at seams unless declared.
- **M32** music stays at least 18 dB below speech (peaks 12 dB), constant within each speech region.

Every source in `fontes.json` must also declare its origin and license; a license marked as pending is reported as a warning that blocks publishing but not producing.

Planned (M09, M17, M18, M19, M22) and manual rules cover things like real voices replacing narration, chapter cards as life timelines, the chapter guide, red circles on group photos, translated on-screen text, final mix targets (M27), no burned-in captions from other productions, no overlapping labels on the storyboard, spoken-but-correct Portuguese, fiction clips only when discussing the work itself, and the end screen.

Engineering conventions referenced in comments: **R11** deliveries never overwrite, **R12** only a human approves (a model judge can disagree but never approves), **R14** code under `scripts/` and `motion/` contains no episode content, **R15** approvals and feedback are append-only logs, **R16** learn structure from references, never copy their text.

## Gates

- **Plan gate.** `episodio parte` refuses a plan without a human approval matching its sha256.
- **Review gates.** `scripts.registro` keeps append-only approvals per stage (`pauta`, `roteiro`, `plano`, `narracao`, `montagem`, `publicacao`, ...). The last human decision wins.
- **Cost gate.** Paid calls require an approver and an approved ceiling; the estimate must fit under it; attempts and real costs go to `00-custos.jsonl`; `scripts.preflight` fails if any spend lacks approval.
- **Mix gate.** A mix whose music margin is below target fails the part.
- **Loudness gate.** Final loudness outside -16.5 to -13 LUFS fails the assembly.
- Publishing is always manual.

## Requirements

- Python 3.12
- ffmpeg and ffprobe
- Playwright Chromium: `.venv/bin/python -m playwright install chromium`
- whisper.cpp (`whisper-cli`) and a model, in `modelos/ggml-small.bin` or `WHISPER_MODELO`
- Optional: an ElevenLabs API key, read from the environment variable named in `estilo.json` (`narracao.chave`) or from a secrets helper command set in `HARNESS_SECRET_CMD` (it receives the name and prints the value). The key never goes to logs, errors or files.

Tested on macOS (Apple Silicon). Two parts are macOS specific: the encoder in `scripts/formato.py` uses `h264_videotoolbox` (switch `CODIFICADOR` to `libx264` elsewhere) and `entrega abrir` uses QuickTime. Fonts in the example style are system fonts; none are bundled.

```
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m scripts.preflight
.venv/bin/python -m pytest -q
```

Tests marked `transcricao` need `whisper-cli`, the model and the macOS `say` command; without them they are skipped with the reason.

## Layout

```
scripts/        harness modules (one CLI per module)
motion/         scene component library and Natural Earth land data
canais/exemplo/ example channel: estilo.json (colors, fonts, mix, TTS) and modelo/regras.json
tests/          pytest suite
videos/<slug>/  one folder per episode (ignored by git): fontes.json, plans, audio, assets, 07-saida, versoes
```

Music is looked up in `HARNESS_MUSICAS`, or `som.pasta_musicas` in the style (relative paths resolve from the style's folder; `canais/exemplo/musicas/` by default, ignored by git).

## Main commands

```
python -m scripts.narracao estimar <text.txt> <estilo.json>
python -m scripts.narracao gerar <text.txt> <out.mp3> <estilo.json> <00-custos.jsonl> --aprovado-por "..." --creditos-aprovados N
python -m scripts.vozes transcrever <audio> <lang> [out.json]
python -m scripts.vozes cortar <audio> <start> <end> <out.wav> <lang> "<first words>" "<last words>" [--aparar]
python -m scripts.roteiro <script.txt> <words.json> <start> <dur> [montagem.json] > skeleton.json
python -m scripts.plano <episode> <plano.json> [words.json]
python -m scripts.episodio prancha <episode> <plano.json> <estilo.json> <name>
python -m scripts.episodio aprovar <episode> <plano.json> "<approval note>"
python -m scripts.episodio parte <episode> <plano.json> <estilo.json> <name> [--palavras p.json] [--fps 30]
python -m scripts.episodio montar <episode> <version> <name1> [<name2> ...] [--abrir] [--inicio s]
python -m scripts.entrega montar|whatsapp|versionar|abrir|limpar ...
python -m scripts.render <part.html> <out.mp4> [--cenas A B] | --previa <dir> <t1> <t2> ...
python -m scripts.modelo feedback|fechar|validar <canais/<channel>/modelo> ...
python -m scripts.preflight
```

The `estudo_*` and `espaco` modules are an optional study of reference channels (download low-resolution samples with yt-dlp, measure pacing, extract structural patterns with evidence timestamps, reject any literal overlap with the source text). They write to `referencias/`, which is ignored by git.

## Operating it with a coding agent

The harness is built to be driven by any coding agent (Claude Code, Codex, Gemini CLI, and others) or by a person at a terminal. Everything is a CLI command or a JSON file: the agent writes `fontes.json` and `plano.json`, runs the validators, reads the failures (each one names the rule and the scene), fixes the plan and runs again. Judgment stays with the operator: which archive frame shows the sentence, where a quote starts and ends, how to translate it. The harness guarantees the result: timing, rules, determinism, gates.

The harness itself never calls an LLM API, so the reasoning runs on the agent's own subscription. The only paid API is the optional TTS, behind the cost gate. The optional reference study shells out to an agent CLI (`claude -p` by default, injectable in `scripts/estudo_ficha.py`).

The gates are meant for this setup: an agent can produce a storyboard, but only a recorded human approval of that exact plan unlocks the render, and only a recorded approval with a ceiling unlocks spending.

## License

MIT, see `LICENSE`.
