

1. **Root cause hypothesis**: The repeated cancellation of `self._socket.recv()` via `asyncio.wait_for` during idle periods causes pyzmq's async socket to enter an unrecoverable state. Each timeout cancels an in-progress recv() operation, and pyzmq's async implementation fails to cleanly handle frequent cancellations, leading to socket corruption after ~50 cancellations.

2. **Specific line**:  
   `raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)`  
   This triggers cancellations every 1 second during idle, destabilizing the socket.

3. **Why ~50s idle causes failure**:  
   50 cancellations (1 per second over 50s) exhaust internal socket resources or orphan pending I/O operations. After this threshold, the socket silently hangs during subsequent recv() calls, ignoring timeouts and new messages.

4. **Suggested fix**: Replace `wait_for` with ZeroMQ-native polling to avoid cancellations:

```python
    async def _serve_loop(self) -> None:
        poller = zmq.asyncio.Poller()
        poller.register(self._socket, zmq.POLLIN)
        while self._running:
            try:
                # Poll without cancellation side effects
                events = await poller.poll(1000)  # 1s timeout (in ms)
                if not events:
                    continue
                
                raw = await self._socket.recv()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка приёма команды ZMQ")
                continue
            
            # ... [rest of original logic unchanged] ...
```
