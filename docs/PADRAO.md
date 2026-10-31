# Padrão de agentes (bots especialistas + workers de código)

Base: o SDD que já existe no `CLAUDE.md` global (seção "SDD: spec antes de código" e "Regras de
engenharia (KAN-62)"), os modelos `docs/sdd/TEMPLATE-*.md` e o gate do Talvium (`docs/plans/gates/`).
Este padrão **não substitui** nada disso: estende para várias sessões e duas camadas de agente.
Marcação: **[CLAUDE.md]** = regra que já existia; **[NOVO]** = fecha uma lacuna.

## 0. Papéis
- **Joabe**: aprova ticket, aprova deploy, decide `[DECIDIR]`. Só fala com bots.
- **Bressani (gerente)**: visão geral, distribui trabalho entre bots, resolve conflito entre repos. Não codifica.
- **Bot dono (especialista T)**: **um por repo** [NOVO]. Único que fala com o Joabe sobre aquele repo,
  escreve ticket/brief, dispara workers, revisa o report, faz merge. Só ele escreve em `main`.
- **Worker** (Claude Code, `mcode`, Codex): sem estado, sem contato com o Joabe. Recebe `brief.md`,
  trabalha numa worktree, entrega `report.md`. Pergunta vira `BLOQUEADO` no report, nunca chute.
- **Revisor**: worker de contexto limpo, de **outro modelo** quando possível (ex.: código pelo `mcode`,
  revisão pelo Claude Code). Lê só ticket + diff [CLAUDE.md: "revisão por subagente de contexto limpo"; NOVO: modelo diferente].

## 1. Camada de spec
1. Mudança que toca dado de usuário, dinheiro, segurança, migração ou comportamento visível começa
   em ticket; bug pequeno = mini; diff de uma frase = sem ticket [CLAUDE.md].
2. Ticket nasce `RASCUNHO`, bot **para** e espera "aprovado" do Joabe [CLAUDE.md].
3. Requisitos EARS com **DEVE** e **Aceite** concreto; tabela de rastreio requisito→teste [TEMPLATE-completo].
4. **Aceite = teste** [NOVO]: cada `Aceite` vira um nome de teste no brief (`[R1] ...`), igual ao padrão
   `testesObrigatorios` dos `fase-N.json` (`F22-01`...). O worker não pode marcar pronto sem esse teste existir e passar.
5. O ticket continua no Jira (`KAN`) [CLAUDE.md], mas o worker **não lê Jira**: o bot dono gera
   `brief.md` (templates/brief.md) a partir do ticket. O brief é o contrato do worker.
6. **Orçamento** no brief [NOVO]: tempo máx., tentativas máx. de CI (padrão 3), arquivos permitidos
   (= `escopo` do gate), custo de tokens. Estourou → para e reporta, não amplia escopo.
7. Escopo mudou → atualiza ticket antes do código; achado novo vira ticket novo [CLAUDE.md].

## 2. Camada de coordenação
1. **Estado no repo, não na memória** [NOVO]. Todo repo com bot dono tem:
   - `docs/estado.md` (templates/estado.md): fase atual, tarefas abertas com worker/branch, bloqueios, próximo passo. Fonte da verdade para qualquer sessão nova.
   - `docs/decisoes.md`: uma linha por decisão do Joabe (data, ticket, decisão, citação curta). Ex.: "Aprovação do gate passa a ser do Claude, com registro" (hoje só em `MUDANCAS.md`).
   - `docs/handoff/<data>-<tarefa>.md`: o report.md arquivado de cada worker.
   Memória do Claude e Jira viram **ponteiro** para esses arquivos, não cópia. Bot que termina sessão atualiza `estado.md` antes.
2. **Uma tarefa = uma worktree = uma branch** [NOVO]:
   `git worktree add ../<repo>-wt/<TKT>-<slug> -b w/<TKT>-<slug> main`. Nunca dois workers na mesma worktree;
   nunca worker em `main`. Bot dono remove a worktree após merge (`git worktree remove`).
3. **Trava de repo** [NOVO]: `docs/estado.md` lista quem trabalha em quais pastas. Duas tarefas que
   tocam o mesmo `escopo` rodam em série, não em paralelo.
4. Worker entrega `report.md` (templates/report.md): status, o que mudou, saída **colada** de
   `test/typecheck/lint/gate/build` [CLAUDE.md: "saída colada no ticket"], testes de regressão, riscos,
   o que não foi feito [KAN-62]. Report sem saída colada = reprovado sem leitura.
5. Bot dono cola o resumo do report no comentário do Jira [CLAUDE.md] e arquiva em `docs/handoff/`.

## 3. Camada de verificação
1. **Local**, pelo worker: teste falhando antes do código [CLAUDE.md]; `npm test · typecheck · lint · gate · build` [talvium/CLAUDE.md].
2. **Gate por fase**: régua em `docs/plans/gates/fase-N.json` (escopo, testes obrigatórios, cobertura),
   integridade por `APROVADO.sha256`, mudança só via `gate:aprovar` com entrada em `MUDANCAS.md`; afrouxar
   exige avisar o Joabe [talvium/CLAUDE.md]. Worker **nunca** roda `gate:aprovar`: só o bot dono, e AFROUXA vai ao Joabe [NOVO].
3. **Regressão por bug** [CLAUDE.md KAN-62, tornado verificável — NOVO]: commit `fix:` exige no mesmo
   PR um teste novo/alterado cujo nome contém o id do bug (`[KAN-123]` ou `[TKT-T03]`). O revisor confere
   que o teste falha no `main` (rodar o teste contra o commit pai) e passa na branch. O `merge-guard.sh` bloqueia `fix:` sem arquivo de teste no diff.
4. **CI** (templates/ci.yml) [NOVO]: jobs `typecheck`, `lint`, `test`, `gate`, `build`, `regressao` e um job
   agregado **`ci-ok`** (`needs:` todos, `if: always()`, falha se qualquer um não for `success`). Só `ci-ok` importa para merge.
5. **Bloqueio de merge sem GitHub Pro — o que é possível de verdade (conferido em docs.github.com, 31/10/2026):**
   - Repo **privado** em conta Free: **não** há branch protection nem rulesets (ambos exigem Pro/Team/Enterprise
     em privado). Required status checks, portanto, **não existe** aí. Não há como o GitHub barrar um `git push` em `main`.
   - Repo **público** em Free: branch protection e rulesets funcionam (required check `ci-ok`, PR obrigatório).
   - **GitHub Pro** (US$ 4/mês) libera protected branches em privado: a solução real e barata.
   - **Contorno adotado sem pagar** (disciplina, não garantia): (a) só o bot dono faz merge, sempre por
     `templates/merge-guard.sh <PR>`, que exige `ci-ok`=success e todas as checks verdes, PR mergeável e regra de regressão;
     (b) workers recebem worktree sem credencial de push para `main` (só `w/*`) — quando possível, token fine-grained só
     com o repo, ou nenhum push e o bot dono empurra; (c) um workflow `on: push: main` que roda o CI e, se falhar,
     abre issue/alerta o bot (detecção, não prevenção); (d) hook local `pre-push` que recusa push direto em `main`.
   - Recomendação: **Pro** para os repos com dado de usuário/dinheiro (Talvium); contorno para o resto.
6. **Revisão independente** antes do merge: revisor recebe ticket + diff + report, responde
   `APROVA` / `REPROVA: <lacunas>` só sobre correção contra requisitos [TEMPLATE-completo §15]. Sem APROVA, sem merge.
7. Operação destrutiva/migração: dry-run, inventário antes/depois [CLAUDE.md KAN-62] — sempre como tarefa separada com aprovação.

## 4. Fluxo de uma tarefa
1. Joabe pede → bot dono escreve ticket RASCUNHO (Jira) → para.
2. "aprovado" → bot dono gera `brief.md`, cria worktree, atualiza `estado.md`, dispara worker.
3. Worker: testes de aceite falhando → código → verificação local → commit na branch `w/*` → `report.md`.
4. Bot dono lê report; dispara revisor; abre PR (`gh pr create`); CI roda.
5. `merge-guard.sh` verde + APROVA do revisor → merge (squash) na `main` — merge local/PR **não é deploy**.
6. Deploy/push para produção: **parar e perguntar** "Posso fazer o deploy?" [CLAUDE.md, regra crítica].
   Nota: abrir PR exige `git push` da branch; isso precisa de autorização do Joabe **uma vez por repo**, registrada em `decisoes.md`.
7. Bot dono move o card (Em análise/Concluído), arquiva report, atualiza `estado.md`.

## 5. Escalada ao Joabe (o bot dono escala; worker nunca)
Escalar **imediatamente**:
- Qualquer `[DECIDIR]`; ticket novo/escopo ampliado; aprovação de RASCUNHO.
- Deploy, push para remoto, migração em produção, operação destrutiva [CLAUDE.md].
- Afrouxar régua do gate (`AFROUXA` em `MUDANCAS.md`) [talvium/CLAUDE.md].
- Caminho definido por ele falhou — dizer o que falhou, não trocar de caminho [CLAUDE.md KAN-62].
- Orçamento estourado ou CI vermelho após N tentativas.
- Revisor e worker discordam duas vezes seguidas.
- Segredo exposto, dado de terceiro em risco, custo pago inesperado.
Não escalar: escolha técnica dentro do brief, refactor dentro do escopo, retry de flake (1x, registrado no report).
Formato: 5 linhas, como o "Resumo para decisão" do TEMPLATE-completo: o que, risco de fazer/não fazer, padrão proposto.
Conflito entre repos (ex. `casa`↔`fluxo`) → Bressani, que leva ao Joabe se precisar.
