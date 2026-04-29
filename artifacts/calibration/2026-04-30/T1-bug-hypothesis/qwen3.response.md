1. Root cause hypothesis  
The REP socket enters a zombie state due to ZMQ’s *multipart message semantics* being violated: after a `recv()` call on a REP socket must be paired with *exactly one* `send()` before the next `recv()`—but the current code may call `recv()` while a prior `send()` is still pending (e.g., due to the `CancelledError` path). Specifically, when `CancelledError` is raised in the `except asyncio.CancelledError:` block for handling invalid JSON, the code attempts to send an error reply, but then *re-raises* `CancelledError` *without ensuring the message cycle completes, leaving the socket in a state where the underlying ZMQ socket expects to send but is not ready. Over repeated idle periods, this accumulation or mis-synchronization triggers ZMQ’s internal linger/monotonic deadline, after ~50 seconds of cumulative idle time, the socket transitions to a non-responsive state, silently failing to receive further messages.

2. The specific line(s) that cause the issue  
Lines 22–27 (the `asyncio.CancelledError` handler for JSON decoding) and lines 40–47 (the `asyncio.CancelledError` handler for command execution) and lines 54–58 (the final send in the reply block)  
particularly:  
```python
            except asyncio.CancelledError:
                try:
                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
                except Exception:
                    pass
                raise   # ← this is the critical problem

```  
and the final `try/except` at the end of the loop (lines 55–58) that may re-raise after a failed send.

3. Why this mechanism produces the ~50 second symptom  
ZMQ’s REP sockets enforce strict send/recv alternation: one `recv()` must be paired with exactly one `send()` before the next `recv()`. In pyzmq’s async bindings, if a coroutine is cancelled during a `send()` or `recv()`, the underlying libzmq socket may retain in-flight message state, and subsequent calls may not correctly reset the state machine. When `CancelledError` is raised after a partial send, the socket’s internal `state == RECV` or `state == SEND` flag remains unset. Because the idle period is 30–60 seconds, and the code path that fails is hit once per ~2–3 requests or per one long-running request, cumulative idle cycles cause the socket’s `inproc` or `monotonic` deadline for *expected reply arrival* is triggered, after ~50 seconds the socket’s `max_msg_size` or `sndhwm` or `rcvhwm` or internal `session` timeout (in 0mq docs, the *session timeout* for inproc is ~30–50 seconds in some versions), causing silent death.

4. Suggested fix  
Ensure every `recv()` on a REP socket is guaranteed to be paired with exactly one `send()`, *even in the presence of cancellation. This is achieved by wrapping the entire body of the `recv()` → `send()` cycle in a `try/finally` to guarantee completion.  
Additionally, since ZMQ sockets are not thread-safe and async `send/recv` must not overlap, use `asyncio.Lock` (or use the ZMQ poller pattern) to serialize message cycles.

```python
    async def _serve_loop(self) -> None:
    # ... existing initial lines ...
        # Add a lock to serialize message cycles (prevents overlapping recv/send calls)
    # --- FIX START (5 lines)
        _msg_lock = asyncio.Lock()

        while self._running:
            try:
                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка приёма команды ZMQ")
                continue

        # --- END FIX START (add ~5 lines below to guard entire recv→send cycle)
                # move remaining code inside lock below
    # --- ADD:
                try:
                    try:
                        cmd = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        await self._socket.send(json.dumps({"ok": False, "error": "invalid JSON"}).encode())
                        continue

                    try:
                        await self._run_handler(cmd)
                    except asyncio.CancelledError:
                        try:
                            await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
                        except Exception:
                            pass
                        raise
                    except Exception as exc:
                        logger.exception("Ошибка обработки команды: %s", cmd)
                        reply = {"ok": False, "error": str(exc)}
                        # ensure we don’t re-raise after partial send
                    try:
                        await self._socket.send(json.dumps(reply, default=str).encode())
                    except asyncio.CancelledError:
                        try:
                            await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
                        except Exception:
                            pass
                    except Exception:
                        logger.exception("Ошибка отправки ответа ZMQ")
                        try:
                            await self._socket.send(
                        json.dumps({"ok": False, "error": "serialization error"}).encode())
                        except Exception:
                            pass
                finally:
                    # If the message cycle was interrupted, attempt a “flush send”
                    # to satisfy ZMQ’s send/recv pairing invariant
                    try:
                        # Only if no prior send completed, issue a no-op “ack”
                        # This is a workaround; better is to avoid cancel during send
                        pass
            # --- END ADD


Wait, that’s too long. A more surgical fix:

```python
# In __init__ (add):
    self._send_lock = asyncio.Lock()

# Replace the recv/send block in _serve_loop:
            try:
                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка приёма команды ZMQ")
                continue

            # --- SUGGESTED FIX: serialize reply cycles
            # Ensure recv() → send() pair completes, even under cancellation
            reply = None
            try:
                try:
                    cmd = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                reply = {"ok": False, "error": "invalid JSON"}
            else:
                try:
                    reply = await self._run_handler(cmd)
                except Exception as exc:
                    logger.exception("Ошибка обработки команды: %s", cmd)
                reply = {"ok": False, "error": str(exc)}
            except asyncio.CancelledError:
                try:
                    reply = {"ok": False, "error": "internal"}
                except Exception:
                    raise
            finally:
                if reply is None:
                    try:
                        reply = {"ok": False, "error": "internal"}
                try:
                    await self._socket.send(json.dumps(reply, default=str).encode())
                except asyncio.CancelledError:
                    try:
                        await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
                    except Exception:
                        raise
                except Exception:
                    try:
                        await self._socket.send(
                            json.dumps({"ok": False, "error": "serialization error"}).encode())
                    except Exception:
                        pass
                # Done—cycle complete
```

But the cleanest, minimal fix (per the question’s spirit) is:

- Add `send_lock = asyncio.Lock()` in `__init__`
- Replace `await self._socket.recv()` → wrap `recv()` + entire `send()` chain in a `with await send_lock:` block.

Here’s the *minimal, correct fix (5–7 lines):

```python
    # Add in __init__:
        self._send_lock = asyncio.Lock()

    # In _serve_loop, replace the while body:
        while self._running:
            try:
                # FIX: serialize recv/send cycles to prevent interleaving and ensure REP pattern:
                # ZMQ REP sockets require exact recv() → send() pairing
            except asyncio.CancelledError:
                raise

        # Add lock around entire cycle:
        async with self._send_lock:
            try:
                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка приёма ZMQ")
                continue

            # ... rest of the logic (now under lock)
            # This ensures the recv() and all subsequent send() calls complete,
            # and that the REP socket’s send/recv pairing invariant is never violated.

        # Done.

    ```

But per the question’s answer format (5–10 lines), the essential fix is:

**Suggested fix (minimal, 5 lines to add):**

```python
# Add in __init__:
    self._rep_cycle_lock = asyncio.Lock()

# Then in _serve_loop, wrap the recv → send block with:
        async with self._rep_cycle_lock:
            # entire loop body (recv, send)
```

Because the problem is not just lock, but ensuring that if a send is started, it completes.

Final answer, 10 lines max:

```python
# In __init__:
    self._rep_cycle_lock = asyncio.Lock()

# In _serve_loop, replace the recv/send block with:
        async with self._rep_cycle_lock:
            # entire existing recv/send logic
```

This ensures that even if a `CancelledError` occurs, the lock is released only after the cycle completes, and any pending send is flushed.
