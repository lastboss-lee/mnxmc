# Backend Stability Agent Memory — MNXMC Project

## Project Identity
- Path: /mnt/d/mnxmc-dev/202602191000 (개발), /mnxmc (런타임)
- Type: Python TUI monitoring application using the Textual framework
- Entry points: main.py (SSH/PTS), main-login.py (TTY1)
- Full validation report delivered: 2026-03-03
- v2.1.0 릴리스: 2026-04-21 (CRITICAL auth bypass 수정 포함)

## ✅ v2.1.0 (2026-04-21) 에서 해결된 항목 — 재조사 금지
- ✅ 3중 AuthenticationManager 중복 구현 → utils.auth.AuthenticationManager 단일화
  (login.py / service.py / dashboard.MnxConfigAuthScreen 모두 동일 클래스 참조)
- ✅ Python 3.12 환경에서 spwd/crypt 직접 import 제거 (utils/auth.py 내부에서
  `import crypt as _crypt` + `/etc/shadow` 직접 파싱으로 대체)
- ✅ CRITICAL: root 실행 시 su-PAM fallback 무조건 성공 취약점
  → authenticate() 및 _verify_with_pam() 양쪽에 os.geteuid()==0 가드 추가
- ✅ SessionManager TOCTOU race → os.O_CREAT|os.O_EXCL 원자 생성으로 수정
- ✅ shell=True 경로 제거 (base_module.py, system_info.py) — shlex.split + list argv
- ✅ UI 블로킹 subprocess 동기 호출 (service all_start/stop, dashboard F7/F8,
  logs inspection) → @work(thread=True, exclusive=True) 로 이전
- ✅ FileHandler → RotatingFileHandler (10MB × 5) — main.py/main-login.py/utils/auth.py
- ✅ mnx_config 비밀번호 Base64 → Fernet(AES-128-CBC+HMAC-SHA256), ENC: legacy 호환
- ✅ sudoers 강화 + /usr/local/bin/mnx_fio wrapper 도입
- ✅ app/main_app.py 버전 2.0.0 → 2.1.0 통일
- ✅ requirements.txt 생성, pip/ 중복 버전(textual/requests/pygments) 정리
- ✅ build_deb.sh __pycache__/*.log/*.bak exclude, prerm 정리 로직 보강
- ✅ /usr/local/bin/mnxmc 런처 생성 (exec python3.12 /mnxmc/main.py)

## Key Validated Findings (do not re-investigate)

### Authentication (SECURITY CRITICAL)
- `crypt` and `spwd` removed in Python 3.13. Affected files:
  - utils/auth.py:21 (top-level import crypt)
  - utils/auth.py:163 (lazy import spwd)
  - app/screens/login.py:21 (top-level import crypt)
  - app/screens/login.py:97 (lazy import spwd)
  - app/screens/service.py:26-27 (BOTH at module top level — import fails on screen load)
- Duplicate AuthenticationManager exists in login.py and utils/auth.py — diverged implementations

### Missing Methods (CRITICAL — AttributeError)
- BaseModule has NO clear_screen() or wait_for_key() defined
- 10 call sites across 4 files will raise AttributeError immediately:
  - modules/kafka_monitor.py:126,149
  - modules/log_viewer.py:341,356
  - modules/performance_monitor.py:519,558,693,724
  - modules/system_info.py:364,378

### Signal Handlers (CRITICAL)
- modules/performance_monitor.py:14-15 installs SIGINT/SIGTERM at MODULE IMPORT TIME
- Overrides entry-point signal handlers silently on first Performance screen open

### Event Loop Blocking
- modules/performance_monitor.py:84 — time.sleep(1) in get_cpu_usage_per_core()
- modules/disk_monitor.py:326 — time.sleep(0.3) on first disk stats call
- app/screens/logs.py:945 — time.sleep(0.5)
- app/screens/service.py:817-867 — _do_all_start()/_do_all_stop() run synchronously in event loop

### Timer Leaks (set_interval handles never cancelled)
- app/screens/dashboard.py:165
- app/screens/performance.py:188
- app/screens/system.py:188
- app/screens/login.py:366
- app/widgets/custom_header.py:75  <- multiplies per screen push

### Shell Injection (shell=True)
- modules/base_module.py:26 — execute_command()
- modules/system_info.py:19 — _run_command()
- utils/helpers.py:64 — run_command_safe() (name contradicts implementation)
- network_management/network_config.py:354 — netplan set

### TUI Corruption (print() during Textual session)
- modules/system_info.py:31,263,272,365,369-375,377
- network_management/network_management.py:306

### Credentials / TLS
- app/screens/mnx_config.py:38 — auth_pw stored plaintext in JSON config
- modules/elasticsearch_monitor.py:20 — hardcoded http:// (TLS disabled)
- Config default: "tls": "false"

### Other Confirmed Issues
- app/main_app.py:51 — CSS_PATH = "styles/theme.tcss" — file does not exist (no styles/ directory)
- app/screens/system.py:676 — discover_interfaces() called inside 1-second refresh loop
- app/screens/shell.py:468 — os.chdir() mutates global process CWD, not restored
- utils/auth.py:172 — sp_expire >= 0 should be > 0 (0 = expired at epoch, not "no expiry")
- modules/system_info.py — cache at /tmp/mnx_system_info.json created with default umask (world-readable)
- modules/log_viewer.py — _scan_directory() has no depth limit (RecursionError risk)
- main.py — SessionManager.acquire() has TOCTOU race (no O_EXCL)
- main.py — double cleanup: atexit + signal handler both call cleanup() without guard

## Textual-Specific Patterns Confirmed in This Project
- set_interval() returns a Timer handle — must store and call .stop() in on_unmount()
- call_from_thread() is correctly used by service.py and network.py background threads
- self.app.suspend() is correctly used by shell.py for blocking subprocess
- self.log.info/error() is the correct Textual logging API for screen-level code
- module-level signal.signal() calls override app-level handlers — never install at import time

See: patterns.md for reusable stability check patterns
