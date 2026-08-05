"""
모든 모듈의 베이스 클래스

Textual TUI 가 화면을 그리고, 모듈은 데이터 수집만 담당한다.
따라서 대화형 CLI 용 계약(run/clear_screen/wait_for_key)과 shell=True 실행
헬퍼(execute_command)는 제거했다 — 호출자가 없었고, TUI 안에서 실행되면
이벤트 루프를 멈추거나 셸 인젝션 표면을 만든다.
명령 실행은 shell=False 인 run_safe() 만 사용한다.
"""

import subprocess


class BaseModule:
    """모듈 베이스 클래스 — 이름 보관 + 안전한 명령 실행."""

    def __init__(self, name):
        self.name = name
        self.running = False

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
