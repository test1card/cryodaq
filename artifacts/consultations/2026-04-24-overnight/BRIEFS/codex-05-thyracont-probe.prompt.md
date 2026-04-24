Model: gpt-5.5
Reasoning effort: high

# Driver hardening — Thyracont VSP63D probe checksum consistency

## Mission

`src/cryodaq/drivers/instruments/thyracont_vsp63d.py::_try_v1_probe`
(~lines 157-166) validates only the response prefix — it does NOT
check the checksum byte. The normal read path DOES validate the
checksum. Consequence: a non-VSP63D device (e.g., VSP206, which
bit us on 2026-04-20) can pass probe and be "connected" by the
driver, then emit NaN forever from read_channels. ~5 LOC fix
(patch spec only — CC will implement in a follow-up session).

## Context files

- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` full
- `HANDOFF_2026-04-20_GLM.md` §3 — the 2026-04-20 VSP206-masquerading
  incident record
- `tests/drivers/test_thyracont*.py` if any — match test style
- `src/cryodaq/drivers/base.py` `InstrumentDriver` / `Reading` ABC
  for return-value contract

## Specific questions

1. Why does the probe skip checksum validation? Git blame and
   architect intent (HANDOFF §3) suggest "forgiving probe for
   multi-firmware-version compatibility" — verify or refute.
2. Is there any case where a probe-without-checksum is correct?
   For example: do some legit VSP63D firmware revisions return a
   probe response with a non-standard or optional checksum that
   the current strict read-path would reject? If yes, we need to
   keep the probe lax but log the discrepancy loudly.
3. Propose: tighten probe to validate checksum (consistent with
   read path) OR keep lax probe + emit WARNING on checksum
   mismatch + record driver metadata flag "probe_checksum_mismatch".
   Which is safer given the 2026-04-20 failure mode and the
   SafetyManager's fail-closed default?
4. Patch (unified diff, under 50 lines) and regression test (under
   30 lines) for the chosen option.

## Output format

- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Root-cause / intent paragraph (≤ 120 words)
- Preferred option: `TIGHTEN` or `LAX+WARN` with one-line rationale
- Unified diff patch (< 50 lines)
- Test case (< 30 lines)
- Max 1500 words total

## Scope fence

- Do not rewrite the transport layer (`drivers/transport/serial.py`).
- Do not propose mocking Protocol V2 — not currently used in the
  lab.
- Do not comment on unrelated Thyracont features (pressure unit
  conversion, etc.).

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-05-thyracont-probe.response.md`
