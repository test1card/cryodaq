# HF — Telegram aiohttp SSL verification config knob

> Hotfix v0.47.1: add opt-in SSL verification disable for Telegram
> aiohttp sessions. Required for macOS dev with VPN that performs
> SSL inspection (Amnezia на api.telegram.org).
>
> ARCHITECT REQUEST source: parallel real-world testing session
> (2026-05-01 telegram-bot-realworld handoff).
>
> Severity: BLOCKING для macOS dev workflow. Bot 100% non-functional
> с VPN, engine spam-logs SSL errors каждые 2s.
>
> Reference: existing pattern in `notifications.local.yaml`
> (gitignored config) — same approach for opt-in dev settings.

---

## 0. Context

**Problem:** Telegram blocked в Russia → VPN mandatory → Amnezia
performs SSL inspection on `api.telegram.org` → presents
self-signed cert → aiohttp rejects → bot non-functional.

**Lab Ubuntu PC** (no VPN, direct hardware access) — unaffected.

**Existing pattern:** `config/notifications.local.yaml` is
gitignored, used for dev-machine secrets и overrides.
`commands_enabled: false` precedent — opt-in safety-relaxation
для dev-only scenarios.

**Why not "just disable SSL for everyone":** production lab PC
shouldn't disable SSL verification — bot token is sensitive,
MITM via cert injection would expose it. Default stays
`verify_ssl: true`, opt-in via `.local.yaml` only.

---

## 1. Operating posture

- Architect synchronously available
- Branch: `hotfix/v0.47.1-telegram-ssl-config`
- Ships: v0.47.1 (patch release)
- Effort: XS (~30 LOC code + ~15 LOC tests = ~45 LOC total)
- Verifier scaling per ORCHESTRATION v1.4 §16.3:
  hotfix scope (XS, no architectural change) → 1-model audit
  (Codex sufficient)

---

## 2. Architect decisions baked in

| Decision | Verdict | Rationale |
|---|---|---|
| Config key location | `telegram.verify_ssl` in `notifications.yaml` | Same section as `bot_token`, `chat_id`, `timeout_s` |
| Default value | `true` | Production-safe; existing behavior unchanged |
| Activation | Override in gitignored `.local.yaml` | Existing pattern для dev secrets |
| Two files affected | `telegram.py` + `telegram_commands.py` | Both create aiohttp sessions independently |
| Implementation method | `aiohttp.TCPConnector(ssl=False)` passed to `ClientSession(connector=...)` | aiohttp documented API; minimal surface change |
| Logging when disabled | WARNING-level on first session creation | Operator visibility — disabled SSL is non-default state |
| Test coverage | One unit test per file (verify_ssl=False creates connector with ssl=False) | XS scope, не нужно integration coverage |
| Default config update | Add commented-out `verify_ssl: true` к `notifications.yaml` example | Documentation visibility |

---

## 3. Implementation

### 3.1 Phase A — telegram.py changes (~10 LOC)

Edit `src/cryodaq/notifications/telegram.py`:

**Constructor signature extension:**

```python
def __init__(
    self,
    bot_token: str | SecretStr,
    chat_id: int | str,
    *,
    send_cleared: bool = True,
    timeout_s: float = 10.0,
    verify_ssl: bool = True,  # NEW
) -> None:
    # ... existing init body ...
    self._verify_ssl = verify_ssl
    if not verify_ssl:
        logger.warning(
            "TelegramNotifier SSL verification DISABLED. "
            "Use only for dev environments behind VPN/SSL-inspection. "
            "Production deployments must keep verify_ssl=true."
        )
```

**from_config classmethod extension:**

```python
return cls(
    bot_token=str(tg["bot_token"]),
    chat_id=tg["chat_id"],
    send_cleared=bool(tg.get("send_cleared", True)),
    timeout_s=float(tg.get("timeout_s", 10.0)),
    verify_ssl=bool(tg.get("verify_ssl", True)),  # NEW
)
```

**_get_session() extension:**

```python
async def _get_session(self) -> aiohttp.ClientSession:
    if self._session is None or self._session.closed:
        connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self._timeout_s),
            connector=connector,
        )
    return self._session
```

### 3.2 Phase B — telegram_commands.py changes (~10 LOC)

Edit `src/cryodaq/notifications/telegram_commands.py`:

**Constructor signature extension** (insert as `verify_ssl: bool = True`
keyword arg, place after `commands_enabled`):

```python
def __init__(
    self,
    broker: DataBroker | None = None,
    alarm_engine: AlarmEngine | None = None,
    *,
    bot_token: str | SecretStr,
    allowed_chat_ids: list[int] | None = None,
    poll_interval_s: float = 2.0,
    command_handler: Callable[[dict], Awaitable[dict]] | None = None,
    commands_enabled: bool = True,
    query_agent: Any | None = None,
    verify_ssl: bool = True,  # NEW
) -> None:
    # ... existing init body ...
    self._verify_ssl = verify_ssl
    if not verify_ssl:
        logger.warning(
            "TelegramCommandBot SSL verification DISABLED. "
            "Use only for dev environments behind VPN/SSL-inspection. "
            "Production deployments must keep verify_ssl=true."
        )
```

**_get_session() extension:**

```python
async def _get_session(self) -> aiohttp.ClientSession:
    if self._session is None or self._session.closed:
        connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=30),
            connector=connector,
        )
    return self._session
```

### 3.3 Phase C — engine wiring (~5 LOC)

Find где engine constructs `TelegramCommandBot` and `TelegramNotifier`
(`src/cryodaq/engine.py` или wherever — recon during Phase A).

Pass `verify_ssl` from notifications config:

```python
# In engine startup (sketch)
notif_cfg = load_notifications_config(...)
tg_cfg = notif_cfg.get("telegram", {})
verify_ssl = bool(tg_cfg.get("verify_ssl", True))

telegram_notifier = TelegramNotifier(
    # ... existing args ...
    verify_ssl=verify_ssl,
)

# Same for TelegramCommandBot construction
telegram_bot = TelegramCommandBot(
    # ... existing args ...
    verify_ssl=verify_ssl,
)
```

If engine already uses `TelegramNotifier.from_config(path)` —
that path already reads `verify_ssl` from YAML per Phase A.
But TelegramCommandBot may be constructed manually — verify
during recon, add explicit pass-through if needed.

### 3.4 Phase D — config schema documentation (~5 LOC)

Edit `config/notifications.yaml` (the example file checked in,
not `.local.yaml`):

```yaml
telegram:
  bot_token: "..."
  chat_id: ...
  send_cleared: true
  timeout_s: 10.0

  # SSL verification for api.telegram.org. Default: true.
  # Set to false ONLY in dev environments behind VPN with SSL
  # inspection (e.g. Amnezia on macOS dev). Override in gitignored
  # config/notifications.local.yaml. Production must keep true.
  # verify_ssl: true

commands:
  enabled: true
  allowed_chat_ids: []
  poll_interval_s: 2.0
```

Comment-out по умолчанию — ясно что field optional, default true.

### 3.5 Phase E — Tests (~15 LOC)

`tests/notifications/test_telegram_ssl_verification.py`:

```python
"""Test verify_ssl config knob for TelegramNotifier and TelegramCommandBot.

Per HF v0.47.1: opt-in disable of SSL verification for dev environments
behind VPN with SSL inspection (e.g. Amnezia on macOS).
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cryodaq.notifications.telegram import TelegramNotifier
from cryodaq.notifications.telegram_commands import TelegramCommandBot


class TestTelegramNotifierSSL:
    @pytest.mark.asyncio
    async def test_get_session_uses_default_ssl_true(self):
        notifier = TelegramNotifier(
            bot_token="123:abc",
            chat_id=42,
        )
        with patch("aiohttp.TCPConnector") as mock_conn, \
             patch("aiohttp.ClientSession") as mock_session:
            await notifier._get_session()
            mock_conn.assert_called_once()
            kwargs = mock_conn.call_args.kwargs
            assert kwargs.get("ssl") is True

    @pytest.mark.asyncio
    async def test_get_session_with_verify_ssl_false(self, caplog):
        with caplog.at_level(logging.WARNING):
            notifier = TelegramNotifier(
                bot_token="123:abc",
                chat_id=42,
                verify_ssl=False,
            )
        # WARNING logged on construction
        assert any(
            "SSL verification DISABLED" in r.message for r in caplog.records
        ), "Expected WARNING log when verify_ssl=False"

        with patch("aiohttp.TCPConnector") as mock_conn, \
             patch("aiohttp.ClientSession"):
            await notifier._get_session()
            kwargs = mock_conn.call_args.kwargs
            assert kwargs.get("ssl") is False

    def test_from_config_reads_verify_ssl_field(self, tmp_path):
        config_path = tmp_path / "notifications.yaml"
        config_path.write_text(
            'telegram:\n'
            '  bot_token: "123:abc"\n'
            '  chat_id: 42\n'
            '  verify_ssl: false\n',
            encoding="utf-8",
        )
        notifier = TelegramNotifier.from_config(config_path)
        assert notifier._verify_ssl is False

    def test_from_config_default_verify_ssl_true(self, tmp_path):
        config_path = tmp_path / "notifications.yaml"
        config_path.write_text(
            'telegram:\n'
            '  bot_token: "123:abc"\n'
            '  chat_id: 42\n',
            encoding="utf-8",
        )
        notifier = TelegramNotifier.from_config(config_path)
        assert notifier._verify_ssl is True


class TestTelegramCommandBotSSL:
    def test_default_verify_ssl_true(self):
        bot = TelegramCommandBot(
            bot_token="123:abc",
            allowed_chat_ids=[42],
        )
        assert bot._verify_ssl is True

    def test_verify_ssl_false_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            bot = TelegramCommandBot(
                bot_token="123:abc",
                allowed_chat_ids=[42],
                verify_ssl=False,
            )
        assert bot._verify_ssl is False
        assert any(
            "SSL verification DISABLED" in r.message for r in caplog.records
        ), "Expected WARNING log when verify_ssl=False"

    @pytest.mark.asyncio
    async def test_get_session_uses_verify_ssl(self):
        bot = TelegramCommandBot(
            bot_token="123:abc",
            allowed_chat_ids=[42],
            verify_ssl=False,
        )
        with patch("aiohttp.TCPConnector") as mock_conn, \
             patch("aiohttp.ClientSession"):
            await bot._get_session()
            kwargs = mock_conn.call_args.kwargs
            assert kwargs.get("ssl") is False
```

### 3.6 Phase F — smoke test (manual verification)

After implementation:

1. Edit Vladimir's `config/notifications.local.yaml`:
   ```yaml
   telegram:
     verify_ssl: false
   ```
2. Restart engine with VPN active
3. Verify:
   - WARNING line in startup log: "SSL verification DISABLED"
   - No SSL errors в spam loop (was every 2s)
   - Test `/status` command from phone — receive reply
   - Send free-text query "что сейчас?" — receive Russian response
4. Verify production safety:
   - Remove `verify_ssl: false` from `.local.yaml`
   - Restart engine
   - Verify NO warning, normal operation на lab PC (when access)
5. Document in `artifacts/handoffs/2026-05-XX-hf-v0.47.1-smoke.md`:
   - Confirmed VPN+macOS workflow restored
   - WARNING log appears as expected
   - Production-safe defaults preserved

### 3.7 Phase G — release v0.47.1

After audit + smoke PASS:

1. Bump `pyproject.toml`: 0.47.0 → 0.47.1
2. CHANGELOG entry:

```markdown
## [0.47.1] — 2026-05-XX — HF: Telegram SSL verification config knob

### Added
- `telegram.verify_ssl` config field in `notifications.yaml` (default: `true`)
- TelegramNotifier and TelegramCommandBot accept `verify_ssl: bool` parameter
- WARNING log when SSL verification disabled (visibility for non-default state)

### Fixed
- macOS dev environment behind Amnezia VPN: bot was 100% non-functional
  due to SSL inspection presenting self-signed cert. Engine spam-logged
  SSL errors every 2s. Now operator can opt-in to disable SSL verification
  in gitignored `notifications.local.yaml`.

### Security note
- Production deployments MUST keep `verify_ssl: true` (default).
- Override via `notifications.local.yaml` (gitignored) only for dev environments
  with controlled VPN/SSL-inspection setups.
- Disabling SSL verification exposes bot token to potential MITM. Acceptable
  for dev where threat model is local-only.

### Reference
- ARCHITECT REQUEST from parallel testing session, 2026-05-01
- HF spec: `CC_PROMPT_HF_V0.47.1_TELEGRAM_SSL.md`
```

3. ROADMAP: no F-task entry (это HF, не feature). Optionally
   add line к "Hotfixes" section if exists.

4. Commit + tag v0.47.1:

```bash
git add pyproject.toml CHANGELOG.md \
        src/cryodaq/notifications/telegram.py \
        src/cryodaq/notifications/telegram_commands.py \
        config/notifications.yaml \
        tests/notifications/test_telegram_ssl_verification.py

git commit -m "fix(telegram): add verify_ssl config knob for VPN environments

Hotfix v0.47.1. Resolves macOS dev workflow blocker: Amnezia VPN
performs SSL inspection on api.telegram.org, presenting self-signed
cert. aiohttp rejected it, bot 100% non-functional, engine spam-logged
SSL errors every 2s.

Changes:
- telegram.py: TelegramNotifier accepts verify_ssl=True (default)
- telegram_commands.py: TelegramCommandBot accepts verify_ssl=True
- _get_session() now creates aiohttp.TCPConnector(ssl=verify_ssl)
- WARNING logged on construction when verify_ssl=False
- from_config() reads telegram.verify_ssl YAML field
- Engine wiring passes verify_ssl from notifications.yaml

Production-safe: default true. Override via gitignored
notifications.local.yaml only.

Tests: 7 new unit tests (default true, false override, warning log,
config loading, both classes covered).

Ref: ARCHITECT REQUEST from realworld testing session 2026-05-01
Ref: CC_PROMPT_HF_V0.47.1_TELEGRAM_SSL.md
Risk: low — minimal surface change, default behavior unchanged."

git tag -a v0.47.1 -m "v0.47.1 — HF: Telegram SSL verification config knob

Adds telegram.verify_ssl config field (default true) to support dev
environments behind VPN with SSL inspection (Amnezia on macOS).

Production unaffected. Opt-in via gitignored notifications.local.yaml."

git push origin master
git push origin v0.47.1
```

---

## 4. Acceptance criteria

After all phases:

1. ✅ `telegram.verify_ssl` config field works in YAML loading
2. ✅ `TelegramNotifier(verify_ssl=False)` constructs successfully
3. ✅ `TelegramCommandBot(verify_ssl=False)` constructs successfully
4. ✅ `_get_session()` passes `aiohttp.TCPConnector(ssl=False)` when verify_ssl=False
5. ✅ WARNING logged when verify_ssl=False (visibility for non-default)
6. ✅ Default `verify_ssl=True` preserves existing behavior
7. ✅ Engine wiring passes config field to both notifier and bot
8. ✅ Vladimir's macOS dev workflow restored: `/status` works through
   Amnezia VPN
9. ✅ Production safety: removing override returns to SSL-verified behavior
10. ✅ All existing tests pass (no regressions)
11. ✅ 7 new unit tests covering both classes + warning log + config
    loading

---

## 5. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Operator accidentally commits verify_ssl: false to production | MEDIUM | `.local.yaml` is gitignored; default in committed `notifications.yaml` is true; WARNING log on construction is operator-visible signal |
| aiohttp `TCPConnector(ssl=False)` API changes between versions | LOW | aiohttp documented stable API since 3.x; pin in pyproject if version drift suspected |
| Engine doesn't currently read notifications config — wiring gap | MEDIUM | Recon during Phase C; if missing, expand to read config and pass through |
| Test mocking of aiohttp.TCPConnector breaks on aiohttp upgrade | LOW | Use functional smoke (Phase F) as ground truth; unit tests are belt+suspenders |
| Operator has neither verify_ssl=false nor active VPN — confusion | LOW | WARNING log + CHANGELOG note clarify purpose |

---

## 6. Hard stops

- aiohttp `TCPConnector(ssl=False)` doesn't suppress SSL verification
  on actual VPN test → STOP, investigate alternative (connector_kwargs
  variant, sslcontext parameter)
- Phase F smoke fails (bot still non-functional with verify_ssl=false
  through VPN) → STOP, root cause не SSL inspection, что-то ещё
- Production wiring gap discovered (engine не read notifications
  config) → expand spec scope to include config loader fix; surface
  to architect

---

## 7. Architect comm-out discipline

Surface immediately:

- Phase C wiring discovery: where exactly engine constructs
  TelegramNotifier and TelegramCommandBot? Pass-through additions
  may need engine refactor.
- Phase F smoke result — VPN test confirms fix или нет
- Any unexpected aiohttp behavior

Otherwise execute autonomously per ORCHESTRATION v1.4 §18.1
(within-cycle autonomy).

---

## 8. Single-verifier audit (post-implementation)

Per ORCHESTRATION v1.4 §16.3 — hotfix XS scope warrants 1-model audit:

```bash
codex exec --sandbox workspace-write --skip-git-repo-check -- \
  "$(cat <<'EOF'
Audit hotfix branch hotfix/v0.47.1-telegram-ssl-config.

Diff range: master..HEAD

Focus:
1. SSL config wiring correctness
2. Default behavior preservation (verify_ssl=True must keep existing tests green)
3. WARNING log visibility — is it loud enough to prevent accidental production deployment with disabled SSL?
4. Config loading robustness — missing field defaults to True?
5. Engine wiring path — does notifications.yaml verify_ssl reach both notifier AND command bot?
6. Test coverage gaps — anything else worth covering?

Output verdict + findings table.
EOF
)" > artifacts/calibration/2026-05-XX-hf-v0.47.1/codex.response.md
```

Append calibration log record per ORCHESTRATION v1.4 §17.

---

## 9. Begin

Phase A first (telegram.py changes). Then B (telegram_commands.py).
Then C (engine wiring recon + extension). Then D (config example
documentation). Then E (tests). Then F (manual smoke through VPN).
Then audit (Phase 8). Then G (release).

Estimated total time: ~1-1.5 hours including audit.

GO.
