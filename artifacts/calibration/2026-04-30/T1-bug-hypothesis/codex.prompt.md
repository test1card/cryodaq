# Bug Investigation Challenge

You are reviewing pre-fix Python code from a cryogenic data-acquisition system.
The code uses pyzmq's async socket API to receive ZMQ commands.

**Symptom observed in production:** The REP socket stops responding after ~50 seconds
of idle time. No exception raised. Subsequent client requests time out.
Restarting the process fixes the issue.

## Source files to read
- src/cryodaq/core/zmq_bridge.py (current post-fix version)
- docs/decisions/2026-04-27-d4-h5-fix.md
- docs/bug_B1_zmq_idle_death_handoff.md

Focus on the pre-fix `_serve_loop` pattern. The H5 fix replaced `asyncio.wait_for(recv(), timeout=1.0)` with `poll()+recv()`. Your task: explain WHY the old pattern causes idle death.

## Output format
1. Root cause hypothesis (1-3 sentences, specific mechanism)
2. Which line(s) in the pre-fix code cause the issue
3. Why this produces the ~50 second symptom
4. Brief explanation of the correct fix

Hard cap 1500 words. No preamble.
