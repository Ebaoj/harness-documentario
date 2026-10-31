#!/usr/bin/env bash
# merge-guard.sh <PR> [--repo dono/repo] [--merge]
# Único caminho de merge do bot dono. Sem --merge só confere (dry-run).
# Recusa se: PR não mergeável, alguma check não verde, `ci-ok` ausente/vermelho,
# ou há commit `fix:` sem arquivo de teste no diff, ou sem "Revisor: APROVA" no PR.
set -euo pipefail
PR="${1:?uso: merge-guard.sh <PR> [--repo o/r] [--merge]}"; shift
REPO_ARGS=(); DO_MERGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO_ARGS=(--repo "$2"); shift 2;;
    --merge) DO_MERGE=1; shift;;
    *) echo "arg desconhecido: $1" >&2; exit 2;;
  esac
done
falha() { echo "RECUSADO: $*" >&2; exit 1; }
command -v gh >/dev/null || falha "gh não instalado"
command -v jq >/dev/null || falha "jq não instalado"

INFO=$(gh pr view "$PR" "${REPO_ARGS[@]}" --json state,isDraft,mergeable,baseRefName,headRefOid,body,comments,commits,files)
[ "$(jq -r .state <<<"$INFO")" = OPEN ] || falha "PR não está aberto"
[ "$(jq -r .isDraft <<<"$INFO")" = false ] || falha "PR é draft"
[ "$(jq -r .baseRefName <<<"$INFO")" = main ] || falha "base não é main"
[ "$(jq -r .mergeable <<<"$INFO")" = MERGEABLE ] || falha "conflito ou mergeable desconhecido (rebase)"
HEAD_SHA=$(jq -r .headRefOid <<<"$INFO")

# 1) checks: todas concluídas e verdes; ci-ok presente e success
CHECKS=$(gh pr checks "$PR" "${REPO_ARGS[@]}" --json name,state,bucket 2>/dev/null || echo '[]')
[ "$(jq length <<<"$CHECKS")" -gt 0 ] || falha "nenhuma check encontrada"
RUIM=$(jq -r '.[] | select(.bucket != "pass" and .bucket != "skipping") | "\(.name)=\(.state)"' <<<"$CHECKS")
[ -z "$RUIM" ] || falha "checks não verdes: $RUIM"
jq -e '.[] | select(.name=="ci-ok" and .bucket=="pass")' <<<"$CHECKS" >/dev/null || falha "ci-ok ausente ou não verde"

# 2) regressão por bug: commit fix: exige arquivo de teste no PR
FIXES=$(jq -r '.commits[].messageHeadline | select(test("^fix(\\(.+\\))?!?:"))' <<<"$INFO")
if [ -n "$FIXES" ]; then
  TESTES=$(jq -r '.files[].path | select(test("(__tests__/|\\.test\\.|\\.spec\\.|^tests?/|^testes/|/test_[^/]*\\.py$)"))' <<<"$INFO")
  [ -n "$TESTES" ] || falha "commit fix: sem teste de regressão no diff: $FIXES"
  # o id do bug (KAN-nn / TKT-xnn) do fix deve aparecer em algum arquivo de teste do PR
  for ID in $(grep -oE '(KAN-[0-9]+|TKT-[A-Z]?[0-9]+)' <<<"$FIXES" | sort -u); do
    gh pr diff "$PR" "${REPO_ARGS[@]}" | grep -E '^\+' | grep -q "$ID" \
      || falha "nenhum teste adicionado cita $ID"
  done
fi

# 3) revisão independente registrada no PR (corpo ou comentário)
jq -e '[.body, .comments[].body] | map(select(. != null and test("Revisor: *APROVA"))) | length > 0' <<<"$INFO" >/dev/null \
  || falha "sem 'Revisor: APROVA' no PR"

echo "OK: PR #$PR @ ${HEAD_SHA:0:7} — checks verdes, ci-ok verde, regressão e revisão conferidas."
if [ "$DO_MERGE" = 1 ]; then
  # --match-head-commit evita mergear um commit diferente do que foi conferido
  gh pr merge "$PR" "${REPO_ARGS[@]}" --squash --delete-branch --match-head-commit "$HEAD_SHA"
else
  echo "(dry-run; use --merge para mergear)"
fi
