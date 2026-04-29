                )
            except Exception as exc:
                log.warning("GPIB: error closing %s — %s", self._resource_str, exc)
            log.info("GPIB: %s closed", self._resource_str)
        # Shut down the dedicated executor so threads don't accumulate
        # across reconnect cycles.
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    async def write(self, cmd: str) -> None:
        """Write command to persistent resource.

        Parameters
        ----------
        cmd:
            SCPI command, e.g. ``"*RST"``.
        """
        if self.mock:
            log.debug("GPIB [mock] write: %s", cmd)
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._get_executor(), self._resource.write, cmd)
        log.debug("GPIB write → %s: %s", self._resource_str, cmd)


codex
The functional timeout change is reasonable, but the newly added safety-manager documentation asserts a convergence guarantee that the slew-rate-limited regulation loop does not provide. This is actionable because the patch is primarily documenting operational behavior for safety-critical hardware.

Review comment:

- [P2] Document slew-limited target convergence accurately — /Users/vladimir/Projects/cryodaq/src/cryodaq/core/safety_manager.py:436-437
  For target changes that require more than `MAX_DELTA_V_PER_STEP` (0.5 V) of adjustment, `Keithley2604B.read_channels()` deliberately clamps the voltage change and only moves another step on subsequent polls; if the channel is in compliance it does not adjust at all. Saying the instrument output converges within one poll interval can mislead callers/operators that wait only ~1s after `update_target()` before relying on the new power, especially for large `p_target` changes.
The functional timeout change is reasonable, but the newly added safety-manager documentation asserts a convergence guarantee that the slew-rate-limited regulation loop does not provide. This is actionable because the patch is primarily documenting operational behavior for safety-critical hardware.

Review comment:

- [P2] Document slew-limited target convergence accurately — /Users/vladimir/Projects/cryodaq/src/cryodaq/core/safety_manager.py:436-437
  For target changes that require more than `MAX_DELTA_V_PER_STEP` (0.5 V) of adjustment, `Keithley2604B.read_channels()` deliberately clamps the voltage change and only moves another step on subsequent polls; if the channel is in compliance it does not adjust at all. Saying the instrument output converges within one poll interval can mislead callers/operators that wait only ~1s after `update_target()` before relying on the new power, especially for large `p_target` changes.
