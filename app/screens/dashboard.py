"""
Dashboard Screen
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, ListView, ListItem, Label, Input
from textual.containers import Container, Vertical, Horizontal
from textual.binding import Binding
from textual import on

from app.widgets import CustomHeader


class DashboardScreen(Screen):
    """
    메인 대시보드 화면.

    Features:
    - 좌측 메뉴 패널 (25%)
    - 우측 시스템 상태 패널
    - 실시간 상태 업데이트 (1초)
    - 키보드 네비게이션
    """

    CSS = """
    DashboardScreen {
        background: #0c0c0c;
    }

    #main-container {
        width: 100%;
        height: 1fr;
        background: #0c0c0c;
    }

    #left-panel {
        width: 25%;
        height: 100%;
        background: #0c0c0c;
        border-right: solid #5fd7d7;
    }

    #menu-title {
        width: 100%;
        height: 1;
        background: #333333;
        color: white;
        text-style: bold;
        padding: 0 2;
    }

    #menu-list {
        width: 100%;
        height: auto;
        background: #0c0c0c;
        border: none;
        padding: 1 0;
    }

    #menu-list > ListItem {
        background: #0c0c0c;
        color: white;
        height: 1;
        padding: 0 2;
    }

    #menu-list > ListItem:hover {
        background: #5fd7d7;
        color: black;
    }

    #menu-list:focus > ListItem.--highlight {
        background: #5fd7d7;
        color: black;
        text-style: bold;
    }

    #right-panel {
        width: 1fr;
        height: 100%;
        background: #0c0c0c;
    }

    #content-title {
        width: 100%;
        height: 1;
        background: #333333;
        color: white;
        text-style: bold;
        padding: 0 2;
    }

    #system-status {
        width: 100%;
        height: 1fr;
        color: white;
        background: #0c0c0c;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("f5", "refresh", "F5: Refresh"),
        Binding("f7", "rescan_system", "F7: Rescan System"),
        Binding("f8", "rescan_network", "F8: Rescan Network"),
        Binding("escape", "back", "Back"),
    ]

    MAIN_MENU = [
        "System Overview",
        "Performance Monitor",
        "Log Monitoring",
        "Service Status",
        "Network Management",
        "MNX Config",
        "Command Shell",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._menu_texts = {}

    def compose(self) -> ComposeResult:
        """UI 구성."""
        yield CustomHeader()

        with Horizontal(id="main-container"):
            with Vertical(id="left-panel"):
                yield Static(" Main Menu ", id="menu-title")
                yield ListView(id="menu-list")

            with Vertical(id="right-panel"):
                yield Static("System Status", id="content-title")
                yield Static("Loading...", id="system-status")

        yield Footer()

    def on_mount(self) -> None:
        self.log.info("DashboardScreen mounted")

        try:
            menu_list = self.query_one("#menu-list", ListView)
            for idx, item_text in enumerate(self.MAIN_MENU):
                menu_id = f"menu-{idx}"
                item = ListItem(Label(f"  {item_text}"), id=menu_id)
                self._menu_texts[menu_id] = item_text
                menu_list.append(item)
        except Exception as e:
            self.log.error(f"Menu setup failed: {e}")

        self.set_timer(0.1, self._focus_menu)
        self._update_status()
        self._update_handle = self.set_interval(1.0, self._update_status)

    def on_unmount(self) -> None:
        if hasattr(self, '_update_handle') and self._update_handle:
            self._update_handle.stop()

    def _focus_menu(self) -> None:
        try:
            menu_list = self.query_one("#menu-list", ListView)
            menu_list.focus()
            if menu_list.children:
                menu_list.index = 0
        except Exception as e:
            self.log.error(f"Menu focus failed: {e}")

    def _update_status(self) -> None:
        try:
            self.query_one("#system-status", Static).update(self._get_system_status())
        except Exception:
            pass

    def _get_system_status(self) -> str:
        try:
            user = getattr(self.app, 'authenticated_user', None) or "unknown"
            system_info = getattr(self.app, 'system_info', None)

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
            mem_usage = info.get('memory_usage', 0)
            mem_bar = self._create_bar(mem_usage)

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

    def _create_bar(self, percentage: float, length: int = 20) -> str:
        filled = max(0, min(length, int((percentage / 100) * length)))
        bar = "▓" * filled + "░" * (length - filled)
        if percentage >= 90:
            return f"[red]{bar}[/]"
        elif percentage >= 75:
            return f"[yellow]{bar}[/]"
        else:
            return f"[green]{bar}[/]"

    # ═══════════════════════════════════════════════════════════════════════════
    # 메뉴 이벤트 핸들러
    # ═══════════════════════════════════════════════════════════════════════════

    @on(ListView.Selected)
    def handle_menu_selection(self, event: ListView.Selected) -> None:
        try:
            selected = self._menu_texts.get(event.item.id, "")
            self.log.info(f"Menu selected: '{selected}'")
            self._navigate_to(selected)
        except Exception as e:
            self.log.error(f"Selection error: {e}")

    @on(ListView.Highlighted)
    def handle_menu_highlight(self, event: ListView.Highlighted) -> None:
        try:
            menu_list = self.query_one("#menu-list", ListView)
            for item in menu_list.children:
                if isinstance(item, ListItem) and item.id:
                    label = item.query_one(Label)
                    text = self._menu_texts.get(item.id, "")
                    if item == event.item:
                        label.update(f"[reverse] ▸ {text} [/]")
                    else:
                        label.update(f"  {text}")
        except Exception as e:
            self.log.error(f"Highlight error: {e}")

    def _navigate_to(self, screen_name: str) -> None:
        try:
            if screen_name == "System Overview":
                from app.screens.system import SystemScreen
                self.app.push_screen(SystemScreen())

            elif screen_name == "Performance Monitor":
                from app.screens.performance import PerformanceScreen
                self.app.push_screen(PerformanceScreen())

            elif screen_name == "Log Monitoring":
                from app.screens.logs import LogsScreen
                self.app.push_screen(LogsScreen())

            elif screen_name == "Service Status":
                from app.screens.service import ServiceScreen
                self.app.push_screen(ServiceScreen())

            elif screen_name == "Network Management":
                from app.screens.network import NetworkScreen
                self.app.push_screen(NetworkScreen())

            elif screen_name == "MNX Config":
                self.app.push_screen(MnxConfigAuthScreen())

            elif screen_name == "Command Shell":
                from app.screens.shell import ShellScreen
                self.app.push_screen(ShellScreen())

            else:
                self.log.warning(f"Unknown screen: {screen_name}")

        except ImportError as e:
            self.log.error(f"Import error: {e}")
            self._show_error(f"Failed to load screen: {screen_name}")
        except Exception as e:
            self.log.error(f"Navigation error: {e}")
            self._show_error(str(e))

    def _show_error(self, message: str) -> None:
        try:
            self.query_one("#system-status", Static).update(f"""[bold red]═══ Error ═══[/]

[white]{message}[/]

[yellow]Press F5 to refresh...[/]
""")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════════════
    # 액션 핸들러
    # ═══════════════════════════════════════════════════════════════════════════

    def action_refresh(self) -> None:
        self._update_status()

    def action_rescan_system(self) -> None:
        try:
            system_info = getattr(self.app, 'system_info', None)
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
            network_mgmt = getattr(self.app, 'network_mgmt', None)
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
