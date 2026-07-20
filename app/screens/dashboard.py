"""
Dashboard Screen

메인 대시보드. 좌측 사이드바(메뉴) + 우측 실시간 시스템 상태.
공통 디자인 시스템(app.ui.BaseScreen)의 4구획 골격을 사용한다.
기능(7개 화면 네비게이션 / 1초 실시간 상태 / F5·F7·F8)은 기존과 동일하다.
"""

import threading

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, ListView, Input
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual import on

from app.widgets import CustomHeader
from app.ui import tokens
from app.ui.screen import BaseScreen
from app.ui.widgets import SectionTitle


class DashboardScreen(BaseScreen):
    """
    메인 대시보드 화면.

    Features:
    - 좌측 사이드바 메뉴 (공통 Sidebar)
    - 우측 시스템 상태 패널
    - 실시간 상태 업데이트 (1초)
    - 키보드 네비게이션
    """

    BINDINGS = [
        Binding("f5", "refresh", "F5: Refresh"),
        Binding("f7", "rescan_system", "F7: Rescan System"),
        Binding("f8", "rescan_network", "F8: Rescan Network"),
        Binding("escape", "back", "Back"),
    ]

    SIDEBAR_TITLE = "MAIN MENU"

    # (nav_id, 표시 라벨) — nav_id 는 _navigate_to 매핑 키
    SIDEBAR_ITEMS = [
        ("system",      "System Overview"),
        ("performance", "Performance Monitor"),
        ("logs",        "Log Monitoring"),
        ("service",     "Service Status"),
        ("network",     "Network Management"),
        ("config",      "MNX Config"),
        ("shell",       "Command Shell"),
    ]

    FOOTER_KEYS = [
        ("↑↓", "Select"),
        ("Enter", "Open"),
        ("F5", "Refresh"),
        ("F7", "Rescan"),
        ("F8", "Network"),
        ("F10", "Exit"),
    ]

    # nav_id → (모듈경로, 클래스명) ; config 는 특수 처리
    _NAV_MAP = {
        "system":      ("app.screens.system",      "SystemScreen"),
        "performance": ("app.screens.performance", "PerformanceScreen"),
        "logs":        ("app.screens.logs",        "LogsScreen"),
        "service":     ("app.screens.service",     "ServiceScreen"),
        "network":     ("app.screens.network",     "NetworkScreen"),
        "shell":       ("app.screens.shell",       "ShellScreen"),
    }

    def compose_content(self) -> ComposeResult:
        yield SectionTitle("System Status")
        yield Static("Loading...", id="system-status")

    def on_mount(self) -> None:
        self.log.info("DashboardScreen mounted")
        # 사이드바 리스트에 포커스 (화살표 키 네비게이션)
        self.set_timer(0.1, self._focus_menu)
        self._update_status()
        self._update_handle = self.set_interval(1.0, self._update_status)

    def on_unmount(self) -> None:
        if getattr(self, "_update_handle", None):
            self._update_handle.stop()

    def _focus_menu(self) -> None:
        try:
            menu_list = self.query_one("Sidebar ListView", ListView)
            menu_list.focus()
            if menu_list.children:
                menu_list.index = 0
        except Exception as e:
            self.log.error(f"Menu focus failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 실시간 상태 패널
    # ═══════════════════════════════════════════════════════════════════════════

    def _update_status(self) -> None:
        """상태 갱신 (blocking subprocess를 스레드로 오프로드 — UI 프리즈 방지)."""
        def _collect():
            try:
                data = self._get_system_status()
            except Exception as e:
                data = f"[red]Error: {e}[/]"
            self.app.call_from_thread(self._render_status, data)
        threading.Thread(target=_collect, daemon=True).start()

    def _render_status(self, content: str) -> None:
        try:
            self.query_one("#system-status", Static).update(content)
        except Exception:
            pass

    def _get_system_status(self) -> str:
        try:
            user = getattr(self.app, "authenticated_user", None) or "unknown"
            system_info = getattr(self.app, "system_info", None)

            if not system_info:
                return f"""[bold cyan]═══ System Status ═══[/]

[green]Logged in as:[/] {user}

[yellow]System info module not available[/]

[bold cyan]─── Navigation ───[/]
[white]↑/↓: Select menu item[/]
[white]Enter: Activate[/]
[white]F5: Refresh[/]
[white]F10: Exit[/]
"""

            info = system_info.get_basic_info()
            mem_usage = info.get("memory_usage", 0)
            mem_bar = tokens.meter(mem_usage, width=20)

            return f"""[bold cyan]═══ System Status ═══[/]

[green]Logged in as:[/] {user}

[bold white]System:[/]
  Hostname     : {info.get('hostname', 'N/A')}
  Uptime       : {info.get('uptime', 'N/A')}

[bold white]Resources:[/]
  Memory Usage : {mem_bar} {mem_usage:.1f}%
  Disk Usage   : {info.get('disk_usage', 'N/A')}
  Load Average : {info.get('load_avg', 'N/A')}

[bold cyan]─── Quick Keys ───[/]
  [yellow]F5[/]  : Refresh status
  [yellow]F7[/]  : Rescan system info
  [yellow]F8[/]  : Rescan network
  [yellow]F10[/] : Exit application
"""
        except Exception as e:
            self.log.error(f"Status error: {e}")
            return f"[red]Error: {str(e)}[/]"

    def _show_error(self, message: str) -> None:
        try:
            self.query_one("#system-status", Static).update(f"""[bold red]═══ Error ═══[/]

[white]{message}[/]

[yellow]Press F5 to refresh...[/]
""")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════════════
    # 사이드바 네비게이션
    # ═══════════════════════════════════════════════════════════════════════════

    def on_nav_selected(self, item_id: str) -> None:
        self.log.info(f"Menu selected: '{item_id}'")
        self._navigate_to(item_id)

    def _navigate_to(self, nav_id: str) -> None:
        try:
            if nav_id == "config":
                self.app.push_screen(MnxConfigAuthScreen())
                return

            target = self._NAV_MAP.get(nav_id)
            if not target:
                self.log.warning(f"Unknown screen: {nav_id}")
                return

            module_path, class_name = target
            module = __import__(module_path, fromlist=[class_name])
            screen_cls = getattr(module, class_name)
            self.app.push_screen(screen_cls())

        except ImportError as e:
            self.log.error(f"Import error: {e}")
            self._show_error(f"Failed to load screen: {nav_id}")
        except Exception as e:
            self.log.error(f"Navigation error: {e}")
            self._show_error(str(e))

    # ═══════════════════════════════════════════════════════════════════════════
    # 액션 핸들러
    # ═══════════════════════════════════════════════════════════════════════════

    def action_refresh(self) -> None:
        self._update_status()

    def action_rescan_system(self) -> None:
        try:
            system_info = getattr(self.app, "system_info", None)
            if system_info:
                system_info.rescan_system()
            self._update_status()
            status = self.query_one("#system-status", Static)
            status.update(f"{status.renderable}\n[green]✓ System info rescanned[/]")
        except Exception as e:
            self.log.error(f"Rescan failed: {e}")
            self._show_error(f"Rescan failed: {e}")

    def action_rescan_network(self) -> None:
        try:
            network_mgmt = getattr(self.app, "network_mgmt", None)
            if network_mgmt:
                network_mgmt.discover_interfaces()
            self._update_status()
            status = self.query_one("#system-status", Static)
            status.update(f"{status.renderable}\n[green]✓ Network interfaces rescanned[/]")
        except Exception as e:
            self.log.error(f"Network rescan failed: {e}")
            self._show_error(f"Network rescan failed: {e}")

    def action_back(self) -> None:
        pass


# ════════════════════════════════════════════════════════════════════════════
# MNX Config 인증 화면
# ════════════════════════════════════════════════════════════════════════════

class MnxConfigAuthScreen(Screen):
    """MNX Config 진입 전 인증 화면 (confirm → password 2단계)."""

    CSS = """
    MnxConfigAuthScreen {
        background: #0c0c0c;
    }

    #auth-container {
        width: 100%;
        height: 1fr;
        align: center middle;
        background: #0c0c0c;
    }

    #auth-box {
        width: 58;
        height: auto;
        background: #1a1a1a;
        border: double #5fd7d7;
        padding: 1 2;
    }

    #auth-title {
        color: #d7af00;
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }

    #auth-message {
        color: white;
        text-align: center;
        margin-bottom: 1;
    }

    #auth-input {
        margin-bottom: 1;
    }

    #auth-hint {
        color: #aaaaaa;
        text-align: center;
    }

    #auth-error {
        color: #ff5555;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._stage = "confirm"
        from app.screens.service import AuthenticationManager
        self._auth = AuthenticationManager()

    def compose(self) -> ComposeResult:
        yield CustomHeader()

        with Container(id="auth-container"):
            with Vertical(id="auth-box"):
                yield Static("⚠  MNX Config Access", id="auth-title")
                yield Static(
                    "You are about to enter [cyan]MNX Config[/].\n"
                    "Authentication required.",
                    id="auth-message",
                )
                yield Input(id="auth-input", placeholder="Type 'confirm' to proceed")
                yield Static("Press ESC to cancel", id="auth-hint")
                yield Static("", id="auth-error")

        yield Footer()

    def on_mount(self) -> None:
        self.set_timer(0.1, lambda: self.query_one("#auth-input", Input).focus())

    @on(Input.Submitted, "#auth-input")
    def on_auth_input(self, event: Input.Submitted) -> None:
        if self._stage == "confirm":
            if event.value.lower() == "confirm":
                self._stage              = "password"
                event.input.value        = ""
                event.input.placeholder  = "Enter your password"
                event.input.password     = True
                self.query_one("#auth-hint",  Static).update("Enter password to authenticate")
                self.query_one("#auth-error", Static).update("")
            else:
                self.query_one("#auth-error", Static).update("Type 'confirm' exactly")

        elif self._stage == "password":
            username = getattr(self.app, 'authenticated_user', 'root') or 'root'
            success, error = self._auth.authenticate(username, event.value)
            if success:
                from app.screens.mnx_config import MnxConfigScreen
                self.app.switch_screen(MnxConfigScreen())
            else:
                self.query_one("#auth-error", Static).update(f"Auth failed: {error}")
                event.input.value = ""

    def action_cancel(self) -> None:
        self.app.pop_screen()
