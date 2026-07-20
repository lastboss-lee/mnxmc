# utils/helpers.py
"""
공통 헬퍼 함수들
"""

import os
import sys
import subprocess
import signal
from dataclasses import dataclass


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


def run_safe(args: list, timeout: int = 10) -> CommandResult:
    """shell=False 안전한 명령 실행"""
    try:
        r = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=timeout)
        return CommandResult(r.returncode, r.stdout, r.stderr)
    except subprocess.TimeoutExpired:
        return CommandResult(1, "", "Command timed out")
    except Exception as e:
        return CommandResult(1, "", str(e))


def setup_signal_handlers():
    """시그널 핸들러 설정"""
    def signal_handler(signum, frame):
        print(f"\n시그널 {signum} 수신, 프로그램을 종료합니다...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def check_root_permissions():
    """root 권한 확인"""
    return os.geteuid() == 0


def format_bytes(bytes_value):
    """바이트를 읽기 쉬운 형태로 변환"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def is_service_running(service_name: str) -> bool:
    """서비스 실행 상태 확인"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', service_name],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def get_process_by_name(process_name: str) -> list:
    """프로세스 이름으로 PID 찾기"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', process_name],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return [int(pid) for pid in result.stdout.strip().split('\n') if pid.isdigit()]
    except Exception:
        pass
    return []
