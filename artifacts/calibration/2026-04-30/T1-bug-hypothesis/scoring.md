# Task class T1 — Bug hypothesis (ground truth) — scoring

## Ground truth
`asyncio.wait_for(self._socket.recv(), timeout=1.0)` cancellation pattern
accumulates pyzmq reactor state. Each timeout cancels an in-flight pyzmq async
recv() coroutine; pyzmq/libzmq's async reactor cannot cleanly unwind these
cancellations. After ~50 such cancellations (~50 seconds idle), the REP socket
is wedged in "awaiting send" state and stops delivering new requests.

Rubric:
- 0: did not identify cancellation-related issue
- 1: identified cancellation as suspect but wrong specific mechanism
- 2: correct root cause but missed pyzmq-specific reactor state detail
- 3: correctly identified wait_for(recv()) cancellation + explained pyzmq reactor state

## Dispatch notes
- Codex: `--sandbox none` is invalid. Re-dispatched with `--sandbox workspace-write`. ✓
- MiniMax: max_tokens=32000 rejected (cap=8192 non-streaming). Re-dispatched at 8192. ✓
- GLM/Kimi: curl raw file never created (capacity/connection failure).
- Gemini: 429 capacity exhausted ("No capacity available for gemini-3.1-pro-preview").

## Per-model scores

| Model | Score | Verdict | Notes |
|---|---|---|---|
| Codex (gpt-5.5) | **3/3** | PERFECT | Named wait_for+pyzmq reactor state explicitly. Cited empirical D2/D3 timing. Referenced docs. Best response. |
| Gemini | N/A | QUOTA | 429 capacity exhausted |
| R1-0528 | **1/3** | WRONG_MECHANISM | Identified wait_for cancellation ✓ but blamed "TCP keepalive timeout" for 50s threshold ✗ |
| Chimera (TNG) | **2/3** | PARTIAL | "pyzmq's async implementation fails to cleanly handle frequent cancellations" ✓. Mechanism: "exhausts internal socket resources" — vague but directionally correct. |
| Qwen3-Coder | **1/3** | WRONG_MECHANISM | Focused on CancelledError handler code paths violating REP send/recv sequencing — missed that the BUG is the wait_for timeout pattern itself |
| GLM-5.1 | N/A | PARSE_ERROR | curl raw file missing — capacity |
| Kimi-K2.6 | N/A | PARSE_ERROR | curl raw file missing — capacity |
| MiniMax-M2.5 | **2/3** | PARTIAL | "fd detached from asyncio event loop's poller after ~50 timeout cycles" ✓ directionally. Vague on "reactor state" specificity. Correct fix (poll+recv). |

## Notable patterns
- **Hallucinations observed**: R1 invented "TCP keepalive timeout" as the 50s threshold cause — wrong mechanism.
- **Surprising performances**: Codex 3/3 with full empirical detail (D2/D3 timestamps, docs references). Codex read the decision docs during its run.
- **Failure modes**:
  - Qwen3: "wrong frame" — analyzed the CancelledError handler code quality instead of the `wait_for` timeout pattern
  - R1: "right direction, wrong mechanism" — identified cancellation but then pivoted to TCP keepalive
  - GLM/Kimi: capacity failures (curl raw file never created)
  - Gemini: model capacity exhausted (429)
- **Score distribution**: Codex 3, Chimera 2, MiniMax 2, Qwen3 1, R1 1, GLM/Kimi/Gemini N/A
