# Stability Check Patterns — Backend Stability Agent

## Textual TUI Stability Checks

### Timer Leak Detection
Search: `set_interval\|set_timer` — verify each result has a corresponding handle variable
and `on_unmount` with `.stop()` call. CustomHeader or other reusable widgets are highest
risk because they multiply with each screen push.

### Event Loop Blocking Detection
Search: `time\.sleep` in any file that is reachable from a Textual callback
(on_mount, set_interval handler, action_*, on_* event handler).
Any sleep > 0 in this call chain blocks all UI rendering and input.

### Thread Safety Pattern (correct)
Background work → threading.Thread(daemon=True) → results posted via call_from_thread()
Do NOT access widget DOM directly from the worker thread.

### Signal Handler Safety
Module-level signal.signal() calls are always wrong in a library/module context.
They must be inside a function or class method, with original handler saved and restored.

## Python 3.13 Breaking Changes
- `crypt` module: REMOVED. Replace with passlib.hash.sha512_crypt / sha256_crypt
- `spwd` module: REMOVED. Replace with direct /etc/shadow parsing or passlib
- Check with: grep -rn "import crypt\|import spwd\|from crypt\|from spwd"

## subprocess Security
- shell=True with any non-literal string = injection risk
- Safe pattern: subprocess.run(["cmd", arg1, arg2], shell=False, timeout=N)
- Unsafe pattern: subprocess.run(f"cmd {user_value}", shell=True)
- The name "run_command_safe" does NOT guarantee shell=False — always verify the impl

## Credential Security
- Passwords in JSON config files → must use keyring, secrets file (mode 0600), or encryption
- Elasticsearch http:// default → always escalate as SECURITY CRITICAL
- Input fields for passwords must use password=True (Textual) to mask display
- /etc/shadow sp_expire field: -1 = no expiry, 0 = expired at epoch, >0 = specific date
  Correct check for "has expiry set": if sp_expire > 0

## File Permission Patterns
- Temp files with sensitive data: use os.open(..., 0o600) not open()
- Lock files: use O_CREAT | O_EXCL for atomic creation (prevents TOCTOU)
- Config files written by application: verify umask or set explicit mode

## Logging in TUI Applications
- print() in any code path reachable during Textual session = display corruption
- Correct: logging.getLogger(__name__).info(...) → FileHandler
- Textual screen/widget level: self.log.info(...) routes to Textual's internal log
- Entry point must configure FileHandler before app.run() to capture all output

## Fail-Fast Configuration Validation
Check at startup (before first screen push):
1. CSS files referenced by CSS_PATH exist
2. Required system tools on PATH (ip, systemctl, netplan, etc.)
3. Config files readable and parseable
4. External services reachable (with timeout, non-blocking)
Surface errors on a startup validation screen rather than at navigation time.
