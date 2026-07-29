#!/usr/bin/env python3
"""
MNX Management Console - SSH Entry Point (Improved)

SSH 접속 시 로그인 건너뛰고 대시보드 직행.

개선사항:
- 환경 검증 (터미널, Python 버전, 의존성)
- 구조화된 로깅
- 터미널 상태 복구
- 시그널 핸들링 강화
- 세션 관리

Author: MNX Team
Version: 2.3.2
"""

import sys
import os
import pwd
import signal
import logging
import atexit
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# 상수 정의
# ═══════════════════════════════════════════════════════════════════════════════

MINIMUM_PYTHON_VERSION = (3, 9)
LOG_DIR = Path("/var/log/mnx")
LOG_FILE = LOG_DIR / "mnx_console.log"

# ═══════════════════════════════════════════════════════════════════════════════
# 로깅 설정
# ═══════════════════════════════════════════════════════════════════════════════

def setup_logging(username: str) -> logging.Logger:
    """
    구조화된 로깅 설정.
    
    Args:
        username: 현재 사용자명
    
    Returns:
        설정된 Logger 인스턴스
    """
    logger = logging.getLogger("mnx_console")
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 파일 핸들러 (가능한 경우)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except PermissionError:
        pass
    
    # 콘솔 핸들러 (디버그용)
    if os.environ.get("MNX_DEBUG"):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger


# ═══════════════════════════════════════════════════════════════════════════════
# 환경 검증
# ═══════════════════════════════════════════════════════════════════════════════

def check_python_version() -> bool:
    """Python 버전 확인."""
    current = sys.version_info[:2]
    if current < MINIMUM_PYTHON_VERSION:
        print(f"\033[1;31m[ERROR]\033[0m Python {MINIMUM_PYTHON_VERSION[0]}.{MINIMUM_PYTHON_VERSION[1]}+ required.")
        print(f"        Current: {current[0]}.{current[1]}")
        return False
    return True


def check_terminal() -> bool:
    """터미널 환경 확인."""
    if not sys.stdin.isatty():
        print("\033[1;31m[ERROR]\033[0m Interactive terminal required.")
        return False
    
    term = os.environ.get("TERM", "")
    if not term:
        os.environ["TERM"] = "xterm-256color"
    
    return True


def check_dependencies() -> tuple:
    """필수 의존성 확인."""
    missing = []
    
    try:
        import textual
    except ImportError:
        missing.append("textual")
    
    try:
        import rich
    except ImportError:
        missing.append("rich")
    
    return len(missing) == 0, missing


def get_current_user() -> tuple:
    """
    현재 사용자 정보.
    
    Returns:
        (username, uid, home_dir)
    """
    try:
        pw_entry = pwd.getpwuid(os.getuid())
        return pw_entry.pw_name, pw_entry.pw_uid, pw_entry.pw_dir
    except KeyError:
        return "unknown", os.getuid(), "/tmp"


# ═══════════════════════════════════════════════════════════════════════════════
# MNXMC 콘솔 설정 읽기
# ═══════════════════════════════════════════════════════════════════════════════

MNXMC_CONFIG_PATH = Path("/opt/mnx/etc/mnxmc_console.json")

def read_mnxmc_config() -> tuple:
    """
    MNXMC 콘솔 설정 읽기.

    Returns:
        (timeout_minutes, max_sessions) — 파일 없으면 기본값 (15, 5)
    """
    try:
        if MNXMC_CONFIG_PATH.exists():
            import json as _json
            data = _json.loads(MNXMC_CONFIG_PATH.read_text())
            s = data.get("session", {})
            timeout      = int(s.get("timeout",      15))
            max_sessions = int(s.get("max_sessions",  5))
            return timeout, max_sessions
    except Exception:
        pass
    return 15, 5


# ═══════════════════════════════════════════════════════════════════════════════
# PTS 세션 정리
# ═══════════════════════════════════════════════════════════════════════════════

def cleanup_old_pts_sessions(
    max_age_minutes: int = 60,
    max_concurrent: int = 4,
    logger: logging.Logger = None
) -> int:
    """
    MNX PTS 세션 자동 정리.

    SSH 접속(main.py 시작) 시 호출되어 main.py / main-login.py 가
    실행 중인 PTS 세션만 선별하여 정리합니다.

    ★ 안전 규칙:
        - main.py / main-login.py 없는 일반 SSH 세션 → 절대 건드리지 않음
        - tty 세션(서비스용 tty1 등) → 항상 제외
        - 현재 접속 세션 → 항상 제외
        - F10으로 정상 종료한 세션 → main.py 없음 → 자동 제외

    종료 조건 (둘 중 하나라도 해당):
        1. SSH 로그인 시간 기준 max_age_minutes(60분) 이상 경과
        2. MNX PTS 세션 총 수(현재 포함)가 max_concurrent(4)를 초과:
           5개째부터 가장 오래된 순으로 종료

    시간 기준: who -u 로그인 시간 우선, 없으면 프로세스 elapsed time 사용.

    Args:
        max_age_minutes: 나이 임계값 (분, 기본 60)
        max_concurrent:  최대 동시 허용 세션 수 (현재 세션 포함, 기본 4)
        logger:          로거

    Returns:
        종료된 세션(SSH 연결) 수
    """
    killed = 0

    # ── 현재 세션 controlling terminal (자기 자신 제외용) ─────────────────
    try:
        current_tty = os.ttyname(sys.stdin.fileno()).replace('/dev/', '')
    except Exception:
        current_tty = None

    now = datetime.now()

    try:
        # ── Step 1: ps 로 main.py/main-login.py 프로세스 → SID 수집 ─────────
        # pid  sid  tty     etimes  cmd
        ps_result = subprocess.run(
            ['ps', '-eo', 'pid,sid,tty,etimes,cmd', '--no-headers'],
            capture_output=True, text=True, timeout=10
        )
        if ps_result.returncode != 0:
            return 0

        # { sid -> { 'ttys': set(pts where main.py runs), 'max_etimes': int } }
        mnx_sids: dict = {}

        for line in ps_result.stdout.strip().splitlines():
            cols = line.split(None, 4)
            if len(cols) < 5:
                continue
            _, sid, tty, etimes_s, cmd = cols

            if 'main.py' not in cmd and 'main-login.py' not in cmd:
                continue
            if tty.startswith('tty'):        # 서비스 tty 제외
                continue
            if tty == current_tty:           # 현재 세션 제외
                continue
            if not tty.startswith('pts/'):   # orphaned(?) 등 제외
                continue

            try:
                etimes = int(etimes_s)
            except ValueError:
                continue

            if sid not in mnx_sids:
                mnx_sids[sid] = {'ttys': set(), 'max_etimes': 0}
            mnx_sids[sid]['ttys'].add(tty)
            mnx_sids[sid]['max_etimes'] = max(mnx_sids[sid]['max_etimes'], etimes)

        if not mnx_sids:
            return 0

        # ── Step 2: who -u 로 SSH 로그인 시간 수집 ──────────────────────────
        # { pts -> login_datetime }
        login_times: dict = {}
        try:
            who_result = subprocess.run(
                ['who', '-u'], capture_output=True, text=True, timeout=5
            )
            for line in who_result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) < 5 or not parts[1].startswith('pts/'):
                    continue
                try:
                    if '-' in parts[2]:
                        lt = datetime.strptime(
                            f"{parts[2]} {parts[3]}", "%Y-%m-%d %H:%M"
                        )
                    else:
                        lt = datetime.strptime(
                            f"{now.year} {parts[2]} {parts[3]} {parts[4]}",
                            "%Y %b %d %H:%M"
                        )
                    login_times[parts[1]] = lt
                except Exception:
                    pass
        except Exception:
            pass   # who -u 실패 시 etimes fallback 사용

        # ── Step 3: SID → 세션 리더 tty → 로그인 시간 매핑 ────────────────
        # { login_tty -> { 'all_ttys': set, 'age_secs': float } }
        # all_ttys: 로그인 tty + main.py가 실행 중인 tty (둘 다 kill 대상)
        mnx_sessions: dict = {}

        for sid, info in mnx_sids.items():
            # 세션 리더(SSH shell)의 controlling terminal 조회
            try:
                r = subprocess.run(
                    ['ps', '-p', sid, '-o', 'tty='],
                    capture_output=True, text=True, timeout=3
                )
                leader_tty = r.stdout.strip()
            except Exception:
                leader_tty = ''

            # 세션 리더가 pts/* 이고 현재 세션이 아닌 경우 → login terminal 확정
            if leader_tty.startswith('pts/') and leader_tty != current_tty:
                login_tty = leader_tty
            else:
                # 세션 리더가 tty1(service) 또는 ? → main.py 직접 pts 사용
                candidates = info['ttys'] - {current_tty}
                if not candidates:
                    continue
                login_tty = min(candidates)  # 사전순 첫번째

            # kill 대상 pts: SSH 로그인 pts + main.py 실행 pts 전부
            all_ttys = (info['ttys'] | {login_tty}) - {current_tty}
            if not all_ttys:
                continue

            # 나이 계산: who -u 로그인 시간 우선, 없으면 etimes
            login_time = login_times.get(login_tty)
            if login_time:
                age_secs = (now - login_time).total_seconds()
            else:
                age_secs = float(info['max_etimes'])

            # 같은 login_tty가 여러 SID에 걸리면 더 오래된(나이 큰) 것 우선
            if (login_tty not in mnx_sessions
                    or age_secs > mnx_sessions[login_tty]['age_secs']):
                mnx_sessions[login_tty] = {
                    'all_ttys': all_ttys,
                    'age_secs': age_secs,
                }

        if not mnx_sessions:
            return 0

        # ── Step 4: 오래된 순 정렬, 종료 대상 결정 ──────────────────────────
        # age_secs 내림차순 (오래된 것 먼저)
        sorted_sessions = sorted(
            mnx_sessions.items(), key=lambda x: -x[1]['age_secs']
        )
        cutoff_secs = max_age_minutes * 60
        to_kill: set = set()

        # 규칙 1: 60분 이상 된 세션 종료
        for login_tty, info in sorted_sessions:
            if info['age_secs'] >= cutoff_secs:
                to_kill.add(login_tty)
                if logger:
                    logger.info(
                        f"MNX cleanup (age {info['age_secs'] / 60:.0f}min): "
                        f"{login_tty} → {info['all_ttys']}"
                    )

        # 규칙 2: 현재 세션 포함 총 수가 max_concurrent 초과 시 가장 오래된 것 종료
        # 5번째부터 제거 (max_concurrent=4 이면 5이상일 때 제거)
        active = [(t, i) for t, i in sorted_sessions if t not in to_kill]
        total_with_current = len(active) + 1   # +1 = 현재 접속 세션
        if total_with_current > max_concurrent:
            excess = total_with_current - max_concurrent   # 제거할 수
            for login_tty, info in active[:excess]:        # 오래된 것부터
                to_kill.add(login_tty)
                if logger:
                    logger.info(
                        f"MNX cleanup (count {total_with_current}>{max_concurrent}): "
                        f"{login_tty} → {info['all_ttys']}"
                    )

        # ── Step 5: 종료 실행 ────────────────────────────────────────────────
        for login_tty in to_kill:
            info    = mnx_sessions[login_tty]
            age_min = int(info['age_secs'] // 60)
            any_ok  = False

            for tty in info['all_ttys']:
                try:
                    subprocess.run(
                        ['pkill', '-HUP', '-t', tty],
                        capture_output=True, text=True, timeout=5
                    )
                    any_ok = True
                except Exception as e:
                    if logger:
                        logger.warning(f"pkill -HUP -t {tty}: {e}")

            if any_ok:
                killed += 1
                msg = (
                    f"MNX session terminated: {login_tty} "
                    f"(ttys={info['all_ttys']}, age={age_min}min)"
                )
                if logger:
                    logger.info(msg)
                print(
                    f"\033[1;33m[SESSION]\033[0m "
                    f"MNX session terminated on {login_tty} (age: {age_min}min)"
                )

    except Exception as e:
        if logger:
            logger.warning(f"PTS session cleanup error: {e}")

    return killed


# ═══════════════════════════════════════════════════════════════════════════════
# 세션 관리
# ═══════════════════════════════════════════════════════════════════════════════

class SessionManager:
    """세션 관리자 - 중복 실행 방지."""
    
    def __init__(self, uid: int):
        self.session_file = Path(f"/tmp/mnx_session_{uid}.lock")
        self.pid = os.getpid()
    
    def acquire(self) -> bool:
        """세션 잠금 획득."""
        try:
            if self.session_file.exists():
                try:
                    old_pid = int(self.session_file.read_text().strip())
                    os.kill(old_pid, 0)
                    return False
                except (ValueError, ProcessLookupError, PermissionError):
                    pass
            
            self.session_file.write_text(str(self.pid))
            return True
        except Exception:
            return True
    
    def release(self):
        """세션 잠금 해제."""
        try:
            if self.session_file.exists():
                current_pid = int(self.session_file.read_text().strip())
                if current_pid == self.pid:
                    self.session_file.unlink()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# 터미널 상태 관리
# ═══════════════════════════════════════════════════════════════════════════════

class TerminalStateManager:
    """터미널 상태 저장 및 복구."""
    
    def __init__(self):
        self.original_state = None
        self._saved = False
    
    def save(self):
        """터미널 상태 저장."""
        try:
            import termios
            self.original_state = termios.tcgetattr(sys.stdin)
            self._saved = True
        except Exception:
            pass
    
    def restore(self):
        """터미널 상태 복구."""
        if not self._saved or self.original_state is None:
            return
        
        try:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.original_state)
        except Exception:
            pass
        
        try:
            print("\033[0m", end="")
            sys.stdout.flush()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# 시그널 핸들러
# ═══════════════════════════════════════════════════════════════════════════════

_cleanup_handlers = []


def register_cleanup(handler):
    """정리 핸들러 등록."""
    _cleanup_handlers.append(handler)


def cleanup():
    """모든 정리 작업 실행."""
    for handler in _cleanup_handlers:
        try:
            handler()
        except Exception:
            pass


def signal_handler(signum, frame):
    """시그널 핸들러."""
    if signum == signal.SIGHUP:
        # 세션 관리에 의한 종료 — 메시지 없이 즉시 종료 (asyncio 우회)
        cleanup()
        os._exit(0)
    signal_names = {
        signal.SIGINT: "SIGINT",
        signal.SIGTERM: "SIGTERM",
    }
    sig_name = signal_names.get(signum, str(signum))

    print(f"\n\033[1;33m[MNX]\033[0m Received {sig_name}, shutting down...")
    cleanup()
    sys.exit(128 + signum)


def setup_signal_handlers():
    """시그널 핸들러 설정."""
    signal.signal(signal.SIGINT,  signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP,  signal_handler)


# ═══════════════════════════════════════════════════════════════════════════════
# 배너
# ═══════════════════════════════════════════════════════════════════════════════

def print_startup_banner(username: str):
    """시작 배너 출력."""
    print("\033[1;38;2;0;174;239m")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║                                                            ║")
    print("║   ███╗   ███╗███╗   ██╗██╗  ██╗                            ║")
    print("║   ████╗ ████║████╗  ██║╚██╗██╔╝                            ║")
    print("║   ██╔████╔██║██╔██╗ ██║ ╚███╔╝                             ║")
    print("║   ██║╚██╔╝██║██║╚██╗██║ ██╔██╗                             ║")
    print("║   ██║ ╚═╝ ██║██║ ╚████║██╔╝ ██╗                            ║")
    print("║   ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝                            ║")
    print("║                                                            ║")
    print("║          MNX Management Console v2.3.2                     ║")
    print("║          SANDS LAB Inc. NDR Solution                       ║")
    print("║                                                            ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print("\033[0m")
    print(f"\033[1;32m[SESSION]\033[0m User: {username}")
    print(f"\033[1;32m[SESSION]\033[0m Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# 메인 함수
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    """
    SSH 접속 시 진입점 (로그인 건너뜀).
    
    Returns:
        종료 코드 (0: 성공, 1: 오류)
    """
    # 1. Python 버전 확인
    if not check_python_version():
        return 1
    
    # 2. 터미널 환경 확인
    if not check_terminal():
        return 1
    
    # 3. 의존성 확인
    deps_ok, missing = check_dependencies()
    if not deps_ok:
        print(f"\033[1;31m[ERROR]\033[0m Missing: {', '.join(missing)}")
        print("        Install: pip install " + " ".join(missing))
        return 1
    
    # 4. 경로 설정
    base_dir = Path(__file__).parent.absolute()
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))
    
    # 5. 사용자 정보
    username, uid, home_dir = get_current_user()
    
    # 6. 로깅 설정
    logger = setup_logging(username)
    logger.info(f"MNX Console starting for user: {username} (UID: {uid})")

    # 7. MNXMC 설정 읽기 → 세션 정책 적용
    timeout_minutes, max_sessions = read_mnxmc_config()

    # 8. MNX PTS 세션 정리 (main.py/main-login.py 실행 중인 세션만 대상)
    cleaned = cleanup_old_pts_sessions(
        max_age_minutes=timeout_minutes if timeout_minutes > 0 else 99999,
        max_concurrent=max_sessions,
        logger=logger,
    )
    if cleaned:
        print(f"\033[1;33m[SESSION]\033[0m {cleaned} stale PTS session(s) terminated.")
        print()

    # 9. 세션 관리 (stale lock은 묻지 않고 자동 덮어씀)
    session = SessionManager(uid)
    if not session.acquire():
        # PTS 정리 직후 lock 프로세스가 아직 종료 중일 수 있음 → 강제 획득
        logger.warning("Stale session lock detected; force-acquiring.")
        print(f"\033[1;33m[SESSION]\033[0m Stale lock detected; proceeding.")
        try:
            session.session_file.write_text(str(session.pid))
        except Exception:
            pass

    register_cleanup(session.release)

    # 9. 터미널 상태 관리
    term_manager = TerminalStateManager()
    term_manager.save()
    register_cleanup(term_manager.restore)

    # 10. 시그널 핸들러
    setup_signal_handlers()

    # 11. atexit 등록
    atexit.register(cleanup)

    # 12. 배너 출력
    print_startup_banner(username)

    # 13. 커널 콘솔 메시지 억제 (TUI 위에 출력되는 커널/ethtool 메시지 방지)
    # dmesg -n 1: KERN_ALERT 이상만 콘솔에 표시 (기본값 4=WARNING)
    try:
        subprocess.run(['dmesg', '-n', '1'], capture_output=True, timeout=5)
        register_cleanup(
            lambda: subprocess.run(['dmesg', '-n', '4'], capture_output=True, timeout=5)
        )
    except Exception:
        pass  # 권한 없거나 실패해도 계속 진행

    # 14. 앱 실행
    try:
        from app.main_app import MNXApp

        logger.info(
            f"Starting MNX application (skip_login=True, "
            f"idle_timeout={timeout_minutes}min)"
        )
        app = MNXApp(
            skip_login=True,
            authenticated_user=username,
            idle_timeout_minutes=timeout_minutes,
        )
        app.run()
        logger.info("MNX application terminated normally")
        
        return 0
    
    except ImportError as e:
        logger.error(f"Import error: {e}")
        print(f"\033[1;31m[ERROR]\033[0m Import failed: {e}")
        return 1
    
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"\033[1;31m[ERROR]\033[0m {e}")
        return 1
    
    finally:
        cleanup()


# ═══════════════════════════════════════════════════════════════════════════════
# 엔트리 포인트
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\033[1;33m[MNX]\033[0m Interrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"\n\033[1;31m[FATAL]\033[0m {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
