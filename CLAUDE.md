# harness-documentario

## Padrão de trabalho dos agentes

Todo agente (bot dono, Claude Code, Codex, mcode) segue `docs/PADRAO.md`:
- Leia `docs/estado.md` ao começar e atualize ao terminar; decisões do Joabe vão em `docs/decisoes.md`; reports de worker em `docs/handoff/`.
- Worker trabalha em worktree/branch própria a partir de `docs/templates/brief.md` e entrega `docs/templates/report.md`.
- Nunca push direto em `main` (ative o hook: `git config core.hooksPath scripts/hooks`).
- Antes de qualquer merge rode `scripts/merge-guard.sh <PR>` (só mergeia com `--merge` se tudo verde, incluindo `ci-ok`).
