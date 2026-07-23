#!/usr/bin/env python3
"""
MNX Management Console - TTY1 Entry Point (Improved)

TTY1 콘솔 접속 시 로그인 화면 표시.
시스템 계정 (Linux /etc/passwd, /etc/shadow) 인증 사용.

개선사항:
- 환경 검증 (터미널, Python 버전, 의존성)
- 시스템 계정 인증 강화
- 구조화된 로깅
- 터미널 상태 복구
- 시그널 핸들링 강화
- 로그인 시도 제한 및 잠금

Author: MNX Team
Version: 2.3.0
"""

import sys
import os
import signal
import logging
import atexit
import subprocess
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# 상수 정의
# ═══════════════════════════════════════════════════════════════════════════════

MINIMUM_PYTHON_VERSION = (3, 9)
LOG_DIR = Path("/var/log/mnx")
LOG_FILE = LOG_DIR / "mnx_console.log"
AUTH_LOG_FILE = LOG_DIR / "mnx_auth.log"

# 로그인 정책
MAX_LOGIN_ATTEMPTS = 3
LOCKOUT_DURATION = 30  # seconds

# ═══════════════════════════════════════════════════════════════════════════════
# 로깅 설정
# ═══════════════════════════════════════════════════════════════════════════════

def setup_logging() -> logging.Logger:
    """
    구조화된 로깅 설정.
    
    Returns:
        설정된 Logger 인스턴스
    """
    logger = logging.getLogger("mnx_console")
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 파일 핸들러
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


def setup_auth_logging() -> logging.Logger:
    """
    인증 전용 로깅 설정.
    
    Returns:
        인증 Logger 인스턴스
    """
    auth_logger = logging.getLogger("mnx_auth")
    auth_logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(AUTH_LOG_FILE)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        auth_logger.addHandler(file_handler)
    except PermissionError:
        pass
    
    return auth_logger


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
        os.environ["TERM"] = "linux"  # TTY1에서는 linux 터미널
    
    # TTY1에서 UTF-8 보장 (유니코드 문자 렌더링용)
    lang = os.environ.get("LANG", "")
    if not lang or lang == "unknown":
        os.environ["LANG"] = "C.UTF-8"
    
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


def check_root_privileges() -> bool:
    """
    Root 권한 확인.
    
    시스템 계정 인증을 위해 /etc/shadow 읽기 권한 필요.
    """
    if os.geteuid() == 0:
        return True
    
    # shadow 파일 읽기 가능 여부 확인
    try:
        with open("/etc/shadow", "r") as f:
            f.readline()
        return True
    except PermissionError:
        return False


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
            print("\033[0m", end="")  # 속성 리셋
            print("\033[?25h", end="")  # 커서 표시
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
    signal_names = {
        signal.SIGINT: "SIGINT",
        signal.SIGTERM: "SIGTERM",
        signal.SIGHUP: "SIGHUP",
    }
    sig_name = signal_names.get(signum, str(signum))
    
    print(f"\n\033[1;33m[MNX]\033[0m Received {sig_name}, shutting down...")
    cleanup()
    sys.exit(128 + signum)


def setup_signal_handlers():
    """시그널 핸들러 설정."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)


# ═══════════════════════════════════════════════════════════════════════════════
# 배너
# ═══════════════════════════════════════════════════════════════════════════════

def print_startup_banner():
    """시작 배너 출력."""
    # 화면 클리어
    print("\033[2J\033[H", end="")
    
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
    print("║          MNX Management Console v2.3.0                     ║")
    print("║          SANDSLAB Inc. NDR Solution                        ║")
    print("║                                                            ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print("\033[0m")
    print()
    print("\033[1;33m[INFO]\033[0m System account authentication required.")
    print("\033[1;33m[INFO]\033[0m Use your Linux system username and password.")
    print()


def print_privilege_warning():
    """권한 경고 출력."""
    print("\033[1;33m")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║                     ⚠  WARNING  ⚠                         ║")
    print("╠════════════════════════════════════════════════════════════╣")
    print("║  System account authentication requires root privileges.   ║")
    print("║                                                            ║")
    print("║  Please run as root:                                       ║")
    print("║    sudo python3 main-login.py                              ║")
    print("║                                                            ║")
    print("║  Or configure PAM for non-root authentication.             ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print("\033[0m")


# ═══════════════════════════════════════════════════════════════════════════════
# 메인 함수
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    """
    TTY1 진입점 (로그인 필요).
    
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
    
    # 5. 로깅 설정
    logger = setup_logging()
    auth_logger = setup_auth_logging()
    logger.info("MNX Console starting (login mode)")
    
    # 6. 권한 확인
    if not check_root_privileges():
        print_privilege_warning()
        logger.warning("Insufficient privileges for system authentication")
        print()
        print("\033[1;33m[NOTE]\033[0m Attempting to continue with PAM authentication...")
        print()
    
    # 7. 터미널 상태 관리
    term_manager = TerminalStateManager()
    term_manager.save()
    register_cleanup(term_manager.restore)
    
    # 8. 시그널 핸들러
    setup_signal_handlers()
    
    # 9. atexit 등록
    atexit.register(cleanup)
    
    # 10. 배너 출력
    print_startup_banner()

    # 11. 커널 콘솔 메시지 억제 (TUI 위에 출력되는 커널/ethtool 메시지 방지)
    try:
        subprocess.run(['dmesg', '-n', '1'], capture_output=True, timeout=5)
        register_cleanup(
            lambda: subprocess.run(['dmesg', '-n', '4'], capture_output=True, timeout=5)
        )
    except Exception:
        pass

    # 12. 앱 실행
    try:
        from app.main_app import MNXApp
        
        logger.info("Starting MNX application (skip_login=False)")
        auth_logger.info("Login session started")
        
        app = MNXApp(skip_login=False, authenticated_user=None)
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
