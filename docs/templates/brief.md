# BRIEF <TKT/KAN-nn>: <uma frase>

> Contrato do worker. Gerado pelo bot dono a partir do ticket aprovado. Worker não fala com o Joabe:
> dúvida que bloqueia → `Status: BLOQUEADO` no report.md e pare.

- **Ticket:** <link Jira KAN-nn> (aprovado em AAAA-MM-DD)
- **Repo / worktree:** <caminho> · **Branch:** `w/<TKT>-<slug>` (criada a partir de `main@<sha>`)
- **Tipo:** feature | fix | refactor | migração

## Objetivo
Uma frase (= seção 4 do ticket).

## Requisitos e testes de aceite (escreva os testes ANTES do código)
| Req | Requisito (EARS, DEVE) | Teste obrigatório (nome exato) | Arquivo de teste |
|---|---|---|---|
| R1 | QUANDO ..., O SISTEMA DEVE ... | `[R1] ...` | `src/.../__tests__/x.test.ts` |
| BUG | (só fix) reproduz o bug | `[KAN-nn] ...` — deve falhar em `main` | ... |

## Escopo permitido
- Pode mexer: <pastas = escopo do fase-N.json>
- Não pode: `docs/plans/gates/**`, `scripts/gate/**`, `.github/**`, `drizzle/**` (salvo dito aqui), segredos.
- Sem `git push`, sem deploy, sem migração em produção, sem `gate:aprovar`.

## Orçamento
- Tempo máx.: <ex. 45 min> · Tentativas de verificação vermelha: <3> · Tokens/custo: <teto>
- Estourou: pare, `Status: ORÇAMENTO`, report do que tem.

## Verificação obrigatória (colar saída no report)
```
npm test && npm run typecheck && npm run lint && npm run gate -- <N> && npm run build
```

## Contexto mínimo
- Arquivos para ler primeiro: ...
- Decisões já tomadas (de docs/decisoes.md): ...
- Regras de domínio relevantes (do CLAUDE.md do projeto): ...

## Entrega
`report.md` na raiz da worktree (modelo templates/report.md) + commits na branch (`feat:`/`fix:` + id).
