"""
모든 모듈의 베이스 클래스
"""

import os
import subprocess
from abc import ABC, abstractmethod


class BaseModule(ABC):
    """모듈 베이스 클래스"""

    def __init__(self, name):
        self.name = name
        self.running = False

    @abstractmethod
    def run(self):
        """모듈 실행 (서브클래스에서 구현)"""
        pass

    def execute_command(self, command):
        """시스템 명령 실행"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except subprocess.TimeoutExpired:
            return "명령 실행 시간 초과"
        except Exception as e:
            return f"명령 실행 오류: {e}"

    def run_safe(self, args: list, timeout: int = 10) -> str:
        """shell=False 안전한 명령 실행"""
        try:
            result = subprocess.run(
                args, shell=False, capture_output=True, text=True, timeout=timeout
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except subprocess.TimeoutExpired:
            return "Command timed out"
        except Exception as e:
            return f"Error: {e}"

    def clear_screen(self) -> None:
        """터미널 화면 클리어"""
        os.system('clear' if os.name != 'nt' else 'cls')

    def wait_for_key(self) -> None:
        """키 입력 대기"""
        try:
            input("\nPress Enter to continue...")
        except (EOFError, KeyboardInterrupt):
            pass
