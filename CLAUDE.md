# Claude Code

Read and follow [`AGENTS.md`](AGENTS.md). It is the canonical repository
instruction file for Claude Code and every other developer agent.

Detailed, tool-neutral orchestration guidance is in
[`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md). Neither this file nor local
Claude settings override `AGENTS.md`.

## Model orchestra

Route work across external and heavyweight models by tier. Cheap/fast → implement.
Medium → review. Megamind → strategy, nuance, and the final before-merge review.

| Tier | Models | Role |
|---|---|---|
| Implement (fast / cheap) | `codex exec -m gpt-5.6-luna`, GLM 5.2 (`opencode run -m zai-coding-plan/glm-5.2 --variant high`), Sonnet subagents | hands-on implementation |
| Review (medium) | `codex exec -m gpt-5.6-terra` | routine review / verification passes |
| Strategy + final review (megamind) | `codex exec -m gpt-5.6-sol`, Fable 5 (Agent `model:"fable"`) | strategic insight, clawing through nuances, whole pre-merge review |

Discipline:

- codex: `codex exec -m <model> -s read-only|workspace-write --skip-git-repo-check -C <repo> "…"`.
  No `-a` flag (`exec` rejects it). Use absolute `/opt/homebrew/bin/codex` when PATH is flaky.
  Reasoning effort is high by default. Run **one** `codex exec` at a time — concurrent runs cause
  DNS/network failures. Always wrap in `timeout` (codex can stall for minutes).
- GLM via opencode is a different backend, so it may run **concurrently** with codex — ideal for
  cross-checking one hard question on two independent experts before touching safety-critical code.
- Author ≠ verifier: whoever implements does not sign off; a separate model owns the review verdict.
  The coordinator never self-approves.

### Quota & parallelism

Anthropic/Claude quota is the scarce resource; GLM 5.2 (opencode/Zhipu) and codex
luna/terra/sol (OpenAI) bill separately. **Default to GLM and luna as implementers to conserve
Claude quota** — reserve Sonnet subagents for work that genuinely needs Agent-tool worktree
isolation or reasoning the CLIs can't do. When speed matters, spawn as many implementers in
parallel as there is *logically independent* (disjoint-file) work.

- **GLM (opencode)** is a different backend from codex, so it runs concurrently with codex and with
  other GLM runs — the main parallel-implementer lane. Give each concurrent worker a **disjoint file
  scope** (or its own git worktree) so parallel writers don't clobber each other.
- **codex (luna/terra/sol)** must run **one at a time** — concurrent `codex exec` hits DNS/network
  failures. It is the serial lane: use it for the single most important implement (luna) or review
  (terra/sol) in flight.
- **Sonnet subagents** run in parallel but cost Claude quota; prefer them last, and use worktree
  isolation when several write at once.
- Cap parallelism at logical independence — more workers than disjoint work just creates merge
  conflicts. Keep reviewers (terra medium; sol/fable final) a separate lane from implementers.
