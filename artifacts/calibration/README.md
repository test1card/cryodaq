# Calibration log

Append-only structured record of multi-model audit dispatches.
Each dispatch creates one record per model in `log.jsonl`.

## Purpose

Accumulate empirical data on model performance across task
classes over weeks/months. Pilot session 2026-04-30 was n=1
per class; this log enables n>1 statistics over time.

## Schema

See prompt files for write-time schema, or inspect log.jsonl keys.

## Reading

```bash
# All records for a model
cat log.jsonl | jq 'select(.model == "codex/gpt-5.5")'

# All records for a task class
cat log.jsonl | jq 'select(.task_class == "foundational_change_review")'

# Real-finding ratio per model (post-verification)
cat log.jsonl | jq 'select(.architect_verification_done == true) | 
  {model: .model, ratio: (.real_findings_count / 
   (.real_findings_count + .hallucinated_findings_count + 
    .ambiguous_findings_count))}'
```

## Synthesis

`MODEL-PROFILES.md` — periodically updated synthesis of accumulated
data. Architect-maintained, not auto-generated.

## Sessions

| Date | Session | Purpose | Records added |
|---|---|---|---|
| 2026-04-30 | pilot calibration | 8 models × 7 task classes | 56 |
| 2026-05-01 | f28-cycle0 | EventBus foundation review | 5 |
