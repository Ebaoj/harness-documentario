# Estado do repo harness-documentario

> Fonte da verdade entre sessões. Bot dono atualiza ao começar e ao terminar cada sessão.

- **Bot dono:** a definir · **Atualizado em:** 2026-10-31 13:05 (UTC-3) por Grok Bot (instalação do padrão)
- **main @** `2e3a109` (Initial commit, 2026-10-14) · **CI de main:** não havia CI; `ci.yml` entra com este PR
- **Stack:** Python (pytest, Playwright/Chromium, ffmpeg, whisper.cpp). Harness de edição de documentários: narração → tempos → plano → prancha → aprovação → render → mixagem → montagem → entrega. Regras M01–M37 no verificador.

## Em andamento
| Ticket | Worker | Branch / worktree | Escopo (pastas travadas) | Desde | Status |
|---|---|---|---|---|---|

## Aguardando Joabe
| Item | Pergunta / decisão | Desde | Padrão proposto |
|---|---|---|---|

## Bloqueios
- `tests/test_render.py`, `test_entrega.py` e `test_episodio.py` (21 testes) dependem do encoder `h264_videotoolbox` (macOS) e falham em Linux; ficam fora do CI e precisam rodar no Mac antes de merge.

## Próximo passo
1. Definir o bot dono e ativar o hook: `git config core.hooksPath scripts/hooks`.

## Últimos merges
| Data | PR | Ticket | Report (docs/handoff/...) |
|---|---|---|---|

Decisões duráveis: `docs/decisoes.md`. Histórico de workers: `docs/handoff/`.
