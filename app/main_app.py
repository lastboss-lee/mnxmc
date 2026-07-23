#!/usr/bin/env python3
"""
MNX Management Console - Main Application

XenServer 스타일의 TUI 기반 시스템 관리 콘솔.

Features:
    - SSH 접속 시 로그인 건너뛰기 (skip_login=True)
    - TTY1 접속 시 로그인 화면 표시 (skip_login=False)
    - 실시간 시스템 모니터링
    - 네트워크 설정 관리
    - 로그 뷰어

Author: MNX Development Team
Version: 2.3.0
"""

import sys
import os
import time
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen


class MNXApp(App):
    """
    MNX Management Console 메인 애플리케이션.
    
    Textual 기반의 TUI 애플리케이션으로, XenServer 스타일의
    관리 인터페이스를 제공합니다.
    
    Attributes:
        skip_login: 로그인 화면을 건너뛸지 여부 (SSH 접속 시 True)
        authenticated_user: 인증된 사용자명
        system_info: 시스템 정보 모듈
        perf_monitor: 성능 모니터링 모듈
        kafka_monitor: Kafka 모니터링 모듈
        es_monitor: Elasticsearch 모니터링 모듈
        log_viewer: 로그 뷰어 모듈
        network_mgmt: 네트워크 관리 모듈
    
    Example:
        >>> app = MNXApp(skip_login=True, authenticated_user="admin")
        >>> app.run()
    """
    
    # CSS 파일 경로 (디자인 시스템 theme 을 뒤에 로드하여 공통 Shell/컴포넌트 스타일 제공)
    CSS_PATH = ["styles/theme.tcss", "ui/theme.tcss"]
    
    # 애플리케이션 제목
    TITLE = "MNX Appliance Management Console"
    
    # Command Palette 비활성화 (Ctrl+P 제거)
    ENABLE_COMMAND_PALETTE = False
    
    # 전역 키 바인딩
    BINDINGS = [
        Binding("f1", "show_help", "Help", priority=True),
        Binding("f5", "refresh", "Refresh", priority=True),
        Binding("f7", "rescan_system", "Rescan System", priority=True),
        Binding("f8", "rescan_network", "Rescan Network", priority=True),
        Binding("f10", "quit_app", "Exit", priority=True),
        Binding("escape", "go_back", "Back", priority=False),
        # Ctrl+Q, Ctrl+P 무시 (아무 동작 안함)
        Binding("ctrl+q", "noop", show=False),
        Binding("ctrl+p", "noop", show=False),
    ]
    
    def __init__(
        self,
        skip_login: bool = False,
        authenticated_user: Optional[str] = None,
        debug: bool = False,
        idle_timeout_minutes: int = 0,
    ):
        """
        MNX 애플리케이션을 초기화합니다.

        Args:
            skip_login: True이면 로그인 화면을 건너뜁니다 (SSH 접속용)
            authenticated_user: 이미 인증된 사용자명 (SSH 접속 시)
            debug: 디버그 모드 활성화 여부
            idle_timeout_minutes: 키 입력 없을 시 자동 종료 (0=비활성)
        """
        super().__init__()

        # 인증 관련 속성
        self.skip_login = skip_login
        self.authenticated_user = authenticated_user
        self.debug_mode = debug

        # 백엔드 모듈 참조 (lazy initialization)
        self._system_info = None
        self._perf_monitor = None
        self._kafka_monitor = None
        self._es_monitor = None
        self._log_viewer = None
        self._network_mgmt = None
        self._disk_monitor = None

        # 모듈 초기화 상태
        self._modules_initialized = False

        # idle timeout
        self._idle_timeout_minutes: int  = idle_timeout_minutes
        self._last_activity_time: float  = time.monotonic()
        self._idle_warning_shown: bool   = False
    
    # ═══════════════════════════════════════════════════════════════════════
    # Properties - Lazy Initialization
    # ═══════════════════════════════════════════════════════════════════════
    
    @property
    def system_info(self):
        """시스템 정보 모듈 (lazy loading)."""
        if self._system_info is None:
            self._init_system_info()
        return self._system_info
    
    @property
    def perf_monitor(self):
        """성능 모니터링 모듈 (lazy loading)."""
        if self._perf_monitor is None:
            self._init_perf_monitor()
        return self._perf_monitor
    
    @property
    def kafka_monitor(self):
        """Kafka 모니터링 모듈 (lazy loading)."""
        if self._kafka_monitor is None:
            self._init_kafka_monitor()
        return self._kafka_monitor
    
    @property
    def es_monitor(self):
        """Elasticsearch 모니터링 모듈 (lazy loading)."""
        if self._es_monitor is None:
            self._init_es_monitor()
        return self._es_monitor
    
    @property
    def log_viewer(self):
        """로그 뷰어 모듈 (lazy loading)."""
        if self._log_viewer is None:
            self._init_log_viewer()
        return self._log_viewer
    
    @property
    def network_mgmt(self):
        """네트워크 관리 모듈 (lazy loading)."""
        if self._network_mgmt is None:
            self._init_network_mgmt()
        return self._network_mgmt

    @property
    def disk_monitor(self):
        """디스크 모니터링 모듈 (lazy loading)."""
        if self._disk_monitor is None:
            self._init_disk_monitor()
        return self._disk_monitor
    
    # ═══════════════════════════════════════════════════════════════════════
    # Module Initialization
    # ═══════════════════════════════════════════════════════════════════════
    
    def _init_system_info(self) -> None:
        """시스템 정보 모듈을 초기화합니다."""
        try:
            from modules.system_info import SystemInfo
            self._system_info = SystemInfo()
            self.log.info("SystemInfo module initialized")
        except ImportError as e:
            self.log.error(f"Failed to import SystemInfo: {e}")
            self._system_info = None
        except Exception as e:
            self.log.error(f"SystemInfo initialization failed: {e}")
            self._system_info = None
    
    def _init_perf_monitor(self) -> None:
        """성능 모니터링 모듈을 초기화합니다."""
        try:
            from modules.performance_monitor import PerformanceMonitor
            self._perf_monitor = PerformanceMonitor()
            self.log.info("PerformanceMonitor module initialized")
        except ImportError as e:
            self.log.error(f"Failed to import PerformanceMonitor: {e}")
            self._perf_monitor = None
        except Exception as e:
            self.log.error(f"PerformanceMonitor initialization failed: {e}")
            self._perf_monitor = None
    
    def _init_kafka_monitor(self) -> None:
        """Kafka 모니터링 모듈을 초기화합니다."""
        try:
            from modules.kafka_monitor import KafkaMonitor
            self._kafka_monitor = KafkaMonitor()
            self.log.info("KafkaMonitor module initialized")
        except ImportError as e:
            self.log.error(f"Failed to import KafkaMonitor: {e}")
            self._kafka_monitor = None
        except Exception as e:
            self.log.error(f"KafkaMonitor initialization failed: {e}")
            self._kafka_monitor = None
    
    def _init_es_monitor(self) -> None:
        """Elasticsearch 모니터링 모듈을 초기화합니다."""
        try:
            from modules.elasticsearch_monitor import ElasticsearchMonitor
            self._es_monitor = ElasticsearchMonitor()
            self.log.info("ElasticsearchMonitor module initialized")
        except ImportError as e:
            self.log.error(f"Failed to import ElasticsearchMonitor: {e}")
            self._es_monitor = None
        except Exception as e:
            self.log.error(f"ElasticsearchMonitor initialization failed: {e}")
            self._es_monitor = None
    
    def _init_log_viewer(self) -> None:
        """로그 뷰어 모듈을 초기화합니다."""
        try:
            from modules.log_viewer import LogViewer
            self._log_viewer = LogViewer()
            self.log.info("LogViewer module initialized")
        except ImportError as e:
            self.log.error(f"Failed to import LogViewer: {e}")
            self._log_viewer = None
        except Exception as e:
            self.log.error(f"LogViewer initialization failed: {e}")
            self._log_viewer = None
    
    def _init_network_mgmt(self) -> None:
        """네트워크 관리 모듈을 초기화합니다."""
        try:
            from network_management.network_management import NetworkManagement
            self._network_mgmt = NetworkManagement()
            self._network_mgmt.discover_interfaces()
            self.log.info("NetworkManagement module initialized")
        except ImportError as e:
            self.log.error(f"Failed to import NetworkManagement: {e}")
            self._network_mgmt = None
        except Exception as e:
            self.log.error(f"NetworkManagement initialization failed: {e}")
            self._network_mgmt = None

    def _init_disk_monitor(self) -> None:
        """디스크 모니터링 모듈을 초기화합니다."""
        try:
            from modules.disk_monitor import DiskMonitor
            self._disk_monitor = DiskMonitor()
            self.log.info("DiskMonitor module initialized")
        except ImportError as e:
            self.log.error(f"Failed to import DiskMonitor: {e}")
            self._disk_monitor = None
        except Exception as e:
            self.log.error(f"DiskMonitor initialization failed: {e}")
            self._disk_monitor = None
    
    def init_all_modules(self) -> None:
        """모든 백엔드 모듈을 한 번에 초기화합니다."""
        if self._modules_initialized:
            return
        
        self.log.info("Initializing all backend modules...")
        
        # 각 모듈 속성에 접근하여 lazy initialization 트리거
        _ = self.system_info
        _ = self.perf_monitor
        _ = self.kafka_monitor
        _ = self.es_monitor
        _ = self.log_viewer
        _ = self.network_mgmt
        _ = self.disk_monitor
        
        self._modules_initialized = True
        self.log.info("All backend modules initialized")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Lifecycle Methods
    # ═══════════════════════════════════════════════════════════════════════
    
    def on_mount(self) -> None:
        """
        애플리케이션이 마운트될 때 호출됩니다.
        
        skip_login 플래그에 따라 적절한 시작 화면을 표시합니다.
        """
        self.log.info(f"MNX Console starting (skip_login={self.skip_login})")

        # Min width 100 columns 보장 (Rule 5)
        if self.size.width < 100:
            self.notify(
                f"Terminal width ({self.size.width}) is below minimum 100 columns. "
                "Please resize your terminal for best experience.",
                severity="warning",
                timeout=5,
            )

        if self.skip_login:
            # SSH 접속: 대시보드 직행
            self.log.info(f"SSH mode: Direct to dashboard (user={self.authenticated_user})")
            self._push_dashboard()
        else:
            # TTY1 접속: 로그인 화면
            self.log.info("TTY mode: Showing login screen")
            self._push_login()

        # idle timeout 타이머 (1분 간격 체크)
        if self._idle_timeout_minutes > 0:
            self.set_interval(60, self._check_idle_timeout)
    
    def _push_login(self) -> None:
        """로그인 화면으로 전환합니다."""
        try:
            from app.screens.login import LoginScreen
            self.push_screen(LoginScreen())
        except ImportError as e:
            self.log.error(f"Failed to import LoginScreen: {e}")
            self.exit(message="Failed to load login screen")
    
    def _push_dashboard(self) -> None:
        """대시보드 화면으로 전환합니다."""
        try:
            from app.screens.dashboard import DashboardScreen
            self.push_screen(DashboardScreen())
        except ImportError as e:
            self.log.error(f"Failed to import DashboardScreen: {e}")
            self.exit(message="Failed to load dashboard screen")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Action Methods (Key Bindings)
    # ═══════════════════════════════════════════════════════════════════════
    
    # ═══════════════════════════════════════════════════════════════════════
    # Idle Timeout
    # ═══════════════════════════════════════════════════════════════════════

    def on_key(self, event) -> None:
        """키 입력 시 마지막 활동 시간 갱신."""
        self._last_activity_time = time.monotonic()
        self._idle_warning_shown = False

    def on_mouse_down(self, event) -> None:
        """마우스 클릭 시 마지막 활동 시간 갱신."""
        self._last_activity_time = time.monotonic()
        self._idle_warning_shown = False

    def _check_idle_timeout(self) -> None:
        """1분마다 호출 — idle 시간 초과 시 앱 종료."""
        if self._idle_timeout_minutes <= 0:
            return

        elapsed_min = (time.monotonic() - self._last_activity_time) / 60

        if elapsed_min >= self._idle_timeout_minutes:
            self.log.info(
                f"Idle timeout: {elapsed_min:.0f}min elapsed "
                f"(limit={self._idle_timeout_minutes}min) — exiting"
            )
            self.exit()
            return

        # 1분 전 경고 (중복 방지)
        if not self._idle_warning_shown and elapsed_min >= self._idle_timeout_minutes - 1:
            self._idle_warning_shown = True
            remaining = self._idle_timeout_minutes - int(elapsed_min)
            self.notify(
                f"유휴 상태 {remaining}분 후 세션이 자동 종료됩니다.",
                severity="warning",
                timeout=60,
            )

    def action_noop(self) -> None:
        """아무 동작도 하지 않음 (Ctrl+Q, Ctrl+P 등 무시용)."""
        pass
    
    def action_quit_app(self) -> None:
        """
        F10/q: 애플리케이션을 종료합니다.
        
        TTY1 모드 (main-login.py)에서는 확인 후 로그인 화면으로 돌아갑니다.
        SSH 모드 (main.py)에서는 정상 종료됩니다.
        """
        if not self.skip_login:
            # TTY1 모드: 로그인 전이면 바로 종료, 로그인 후면 확인 다이얼로그
            if self.authenticated_user:
                self._show_logout_confirm()
            else:
                self.exit()
            return
        
        # SSH 모드: 정상 종료
        self.log.info("User requested application exit")
        self.exit()
    
    def _show_logout_confirm(self) -> None:
        """로그아웃 확인 다이얼로그 표시."""
        from textual.screen import ModalScreen
        from textual.widgets import Static, Button
        from textual.containers import Vertical, Horizontal
        from textual.app import ComposeResult
        
        app = self
        
        class LogoutConfirmScreen(ModalScreen):
            """로그아웃 확인 모달."""
            
            DEFAULT_CSS = """
            LogoutConfirmScreen {
                align: center middle;
                background: rgba(0, 0, 0, 0.8);
            }
            
            #dialog {
                width: 40;
                height: 11;
                border: solid cyan;
                background: #1a1a1a;
                padding: 1 2;
            }
            
            #dialog-title {
                width: 100%;
                height: 1;
                text-align: center;
                text-style: bold;
                color: cyan;
                margin-bottom: 1;
            }
            
            #dialog-message {
                width: 100%;
                height: 1;
                text-align: center;
                color: white;
                margin-bottom: 1;
            }
            
            #dialog-buttons {
                width: 100%;
                height: 3;
                layout: horizontal;
                align: center middle;
                margin-top: 1;
            }
            
            #dialog-buttons Button {
                width: 10;
                height: 3;
                margin: 0 1;
                content-align: center middle;
                border: solid cyan;
            }
            
            #btn-yes {
                background: #006666;
                color: white;
            }
            
            #btn-yes:hover {
                background: cyan;
                color: black;
            }
            
            #btn-no {
                background: #444444;
                color: white;
            }
            
            #btn-no:hover {
                background: #666666;
                color: white;
            }
            
            #dialog-buttons Button:focus {
                text-style: bold;
                border: solid white;
            }
            """
            
            def compose(self) -> ComposeResult:
                with Vertical(id="dialog"):
                    yield Static("Logout", id="dialog-title")
                    yield Static("Return to login screen?", id="dialog-message")
                    with Horizontal(id="dialog-buttons"):
                        yield Button("Yes", id="btn-yes")
                        yield Button("No", id="btn-no")
            
            def on_button_pressed(self, event: Button.Pressed) -> None:
                if event.button.id == "btn-yes":
                    self.dismiss(True)
                else:
                    self.dismiss(False)
            
            def on_key(self, event) -> None:
                if event.key == "y":
                    self.dismiss(True)
                elif event.key == "n" or event.key == "escape":
                    self.dismiss(False)
        
        def handle_logout(result: bool) -> None:
            if result:
                app.log.info("User confirmed logout")
                app.logout()
        
        self.push_screen(LogoutConfirmScreen(), handle_logout)
    
    def action_refresh(self) -> None:
        """
        F5: 현재 화면을 새로고침합니다.
        
        현재 활성화된 화면에 action_refresh 메서드가 있으면 호출합니다.
        """
        current_screen = self.screen
        if hasattr(current_screen, 'action_refresh'):
            self.log.info(f"Refreshing screen: {current_screen.__class__.__name__}")
            current_screen.action_refresh()
        else:
            self.log.debug("Current screen has no refresh action")
    
    def action_go_back(self) -> None:
        """
        ESC: 이전 화면으로 돌아갑니다.
        
        스크린 스택에 화면이 있으면 pop, 없으면 무시합니다.
        """
        if len(self.screen_stack) > 1:
            self.log.info("Navigating back to previous screen")
            self.pop_screen()
        else:
            self.log.debug("Already at root screen, cannot go back")
    
    def action_show_help(self) -> None:
        """
        F1: 도움말 화면을 표시합니다.
        """
        self.log.info("Showing help screen")
        try:
            from app.screens.help import HelpScreen
            self.push_screen(HelpScreen())
        except ImportError:
            # 도움말 화면이 없으면 알림만 표시
            self.notify("Help: F5=Refresh, F7=Rescan, F10=Exit, ESC=Back")
    
    def action_rescan_system(self) -> None:
        """
        F7: 시스템 정보를 다시 스캔합니다.
        """
        self.log.info("Rescanning system information")
        
        if self.system_info:
            try:
                self.system_info.rescan_system()
                self.notify("System information rescanned", title="Rescan Complete")
                
                # 현재 화면에 업데이트 요청
                if hasattr(self.screen, 'on_system_rescan'):
                    self.screen.on_system_rescan()
            except Exception as e:
                self.log.error(f"System rescan failed: {e}")
                self.notify(f"Rescan failed: {e}", severity="error")
        else:
            self.notify("System info module not available", severity="warning")
    
    def action_rescan_network(self) -> None:
        """
        F8: 네트워크 인터페이스를 다시 스캔합니다.
        """
        self.log.info("Rescanning network interfaces")
        
        if self.network_mgmt:
            try:
                self.network_mgmt.discover_interfaces()
                count = len(self.network_mgmt.interfaces)
                self.notify(f"Found {count} interfaces", title="Network Rescan")
                
                # 현재 화면에 업데이트 요청
                if hasattr(self.screen, 'on_network_rescan'):
                    self.screen.on_network_rescan()
            except Exception as e:
                self.log.error(f"Network rescan failed: {e}")
                self.notify(f"Rescan failed: {e}", severity="error")
        else:
            self.notify("Network module not available", severity="warning")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Utility Methods
    # ═══════════════════════════════════════════════════════════════════════
    
    def switch_to_dashboard(self) -> None:
        """
        대시보드 화면으로 전환합니다.

        로그인 성공 후 호출됩니다.
        로그인 화면을 스택에서 제거하고 대시보드로 교체합니다.
        """
        self.log.info("Switching to dashboard")
        try:
            from app.screens.dashboard import DashboardScreen
            self.switch_screen(DashboardScreen())
        except Exception as e:
            self.log.error(f"switch_screen failed, falling back to push_screen: {e}")
            self._push_dashboard()
    
    def logout(self) -> None:
        """
        로그아웃하고 로그인 화면으로 돌아갑니다.
        """
        self.log.info(f"User {self.authenticated_user} logging out")
        self.authenticated_user = None
        
        # 로그인 화면으로 전환 (switch_screen 사용)
        try:
            from app.screens.login import LoginScreen
            self.switch_screen(LoginScreen())
        except Exception as e:
            self.log.error(f"Failed to switch to login screen: {e}")
    
    def get_module_status(self) -> dict:
        """
        모든 모듈의 상태를 반환합니다.
        
        Returns:
            dict: 모듈명과 초기화 상태의 딕셔너리
        """
        return {
            'system_info': self._system_info is not None,
            'perf_monitor': self._perf_monitor is not None,
            'kafka_monitor': self._kafka_monitor is not None,
            'es_monitor': self._es_monitor is not None,
            'log_viewer': self._log_viewer is not None,
            'network_mgmt': self._network_mgmt is not None,
            'disk_monitor': self._disk_monitor is not None,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Entry Points
# ═══════════════════════════════════════════════════════════════════════════

def run_with_login() -> None:
    """
    로그인 화면을 포함하여 애플리케이션을 실행합니다.
    
    TTY1 콘솔에서 사용합니다.
    """
    app = MNXApp(skip_login=False)
    app.run()


def run_without_login(username: str) -> None:
    """
    로그인 없이 대시보드로 직접 진입합니다.
    
    SSH 접속 시 사용합니다.
    
    Args:
        username: 이미 인증된 사용자명
    """
    app = MNXApp(skip_login=True, authenticated_user=username)
    app.run()


if __name__ == "__main__":
    # 테스트 실행
    import pwd
    import os
    
    try:
        current_user = pwd.getpwuid(os.getuid()).pw_name
        app = MNXApp(skip_login=True, authenticated_user=current_user, debug=True)
        app.run()
    except KeyboardInterrupt:
        print("\nApplication terminated by user")
    except Exception as e:
        print(f"Application error: {e}")
        import traceback
        traceback.print_exc()