"""
Command Shell Screen

인증된 사용자를 위한 대화형 셸 접근 화면입니다.

Features:
    - 셸 접근을 위한 인증
    - 대화형 bash 셸 실행
    - 셸 종료 후 콘솔로 복귀
"""

from textual.app import ComposeResult
from textual.widgets import Static, ListView
from textual.binding import Binding
from app.ui.screen import BaseScreen
import subprocess
import os
import sys
import pwd


class ShellScreen(BaseScreen):
    """
    Command Shell 화면.
    
    인증 후 대화형 bash 셸을 실행합니다.
    """
    
    CSS = """
    ShellScreen {
        background: #0c0c0c;
    }

    #content-panel {
        width: 1fr;
        height: 100%;
        background: #0c0c0c;
        padding: 0;
    }

    #content-title {
        width: 100%;
        height: 1;
        background: #333333;
        color: white;
        text-style: bold;
        padding: 0 2;
    }

    #shell-content {
        width: 100%;
        height: 1fr;
        background: #0c0c0c;
        color: white;
        padding: 1 2;
    }
    """
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]
    
    # 메뉴 항목
    MENU_ITEMS = [
        ("back", "← Back"),
        ("info", "Shell Info"),
        ("history", "Command History"),
        ("shell", "Launch Shell"),
    ]

    SIDEBAR_TITLE = "COMMAND SHELL"
    SIDEBAR_ITEMS = MENU_ITEMS          # nav_id 가 곧 현재 뷰 키
    FOOTER_KEYS = [
        ("↑↓", "Select"),
        ("Enter", "Open"),
        ("F10", "Exit"),
        ("ESC", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_view = "info"
        self._shell_active = False  # 이중 실행 방지

    def compose_content(self) -> ComposeResult:
        yield Static("Shell Info", id="content-title")
        yield Static(self._get_content(), id="shell-content")

    def on_mount(self) -> None:
        """화면 마운트 시 초기화."""
        self.log.info("ShellScreen mounted")
        # 사이드바 항목은 BaseScreen 이 SIDEBAR_ITEMS 로 구성함
        self.set_timer(0.1, self._initialize_menu)

    def _initialize_menu(self) -> None:
        """사이드바 초기 포커스/선택."""
        try:
            menu_list = self.query_one("Sidebar ListView", ListView)
            menu_list.focus()
            if menu_list.children:
                menu_list.index = 1  # "Shell Info"
        except Exception as e:
            self.log.error(f"Menu init failed: {e}")
    
    def _get_content(self) -> str:
        """현재 뷰에 따른 콘텐츠 생성."""
        view_methods = {
            "info": self._get_shell_info,
            "shell": self._get_shell_prompt,
            "history": self._get_command_history,
        }
        
        method = view_methods.get(self._current_view, self._get_shell_info)
        return method()
    
    def _get_shell_info(self) -> str:
        """셸 정보."""
        user = getattr(self.app, 'authenticated_user', None) or os.environ.get('USER', 'unknown')
        
        try:
            user_info = pwd.getpwnam(user)
            home_dir = user_info.pw_dir
            shell = user_info.pw_shell
            uid = user_info.pw_uid
            gid = user_info.pw_gid
        except Exception:
            home_dir = os.environ.get('HOME', '/root')
            shell = os.environ.get('SHELL', '/bin/bash')
            uid = os.getuid()
            gid = os.getgid()
        
        return f"""[bold cyan]══ Shell Information ══[/]

[yellow]Current User:[/]
  Username    : {user}
  UID         : {uid}
  GID         : {gid}
  Home        : {home_dir}
  Shell       : {shell}

[yellow]System Info:[/]
  Hostname    : {os.uname().nodename}
  OS          : {os.uname().sysname} {os.uname().release}
  Architecture: {os.uname().machine}

[yellow]Environment:[/]
  TERM        : {os.environ.get('TERM', 'unknown')}
  LANG        : {os.environ.get('LANG', 'unknown')}
  PATH        : {os.environ.get('PATH', '')[:50]}...

[bright_black]─────────────────────────────────────────────[/]
Select [cyan]Launch Shell[/] to start interactive shell
Press [yellow]ESC[/] to return to dashboard
"""
    
    def _get_shell_prompt(self) -> str:
        """셸 실행 안내."""
        return """[bold cyan]══ Launch Interactive Shell ══[/]

[yellow]Press Enter to launch bash shell[/]

[white]The shell will:[/]
  • Open an interactive bash session
  • Run with your current user privileges
  • Return to MNX Console when you type 'exit'

[yellow]Tips:[/]
  • Type 'exit' or press Ctrl+D to return
  • Use 'sudo' for administrative commands
  • Shell history will be preserved

[bright_black]─────────────────────────────────────────────[/]
[bold green]Ready to launch shell...[/]
Press [yellow]Enter[/] on 'Launch Shell' menu item
"""
    
    def _get_command_history(self) -> str:
        """명령 히스토리."""
        try:
            from datetime import datetime as _dt
            # 'root' 기본값 금지 — 인증 정보가 없을 때 root 의 .bash_history 를
            # 노출하게 된다. 사용자를 특정할 수 없으면 히스토리를 읽지 않는다.
            user = getattr(self.app, 'authenticated_user', None)
            if not user:
                return ("[bold cyan]══ Command History ══[/]\n\n"
                        "[yellow]인증된 사용자 정보가 없어 히스토리를 표시할 수 없습니다.[/]")
            user_info = pwd.getpwnam(user)
            history_file = os.path.join(user_info.pw_dir, '.bash_history')

            if os.path.exists(history_file):
                with open(history_file, 'r', errors='replace') as f:
                    lines = f.readlines()

                # #<unix_timestamp> 행과 명령어 행을 쌍으로 파싱
                entries = []   # list of (datetime_str, cmd)
                pending_ts = ""
                for line in lines:
                    line = line.rstrip('\n')
                    if line.startswith('#'):
                        try:
                            ts = int(line[1:])
                            pending_ts = _dt.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            pending_ts = ""
                    else:
                        cmd = line.strip()
                        if cmd:
                            entries.append((pending_ts, cmd))
                            pending_ts = ""

                total = len(entries)
                recent = entries[-20:] if total > 20 else entries

                content = "[bold cyan]══ Recent Command History ══[/]\n\n"
                content += "[yellow]Last 20 commands:[/]\n"
                for i, (ts, cmd) in enumerate(recent, 1):
                    if ts:
                        content += f"  {i:3d}. [bright_black]{ts}[/] {cmd[:50]}\n"
                    else:
                        content += f"  {i:3d}. {cmd[:65]}\n"

                content += f"\n[bright_black]History file: {history_file}[/]\n"
                content += f"[bright_black]Total commands: {total}[/]\n"
                return content
            else:
                return """[bold cyan]══ Command History ══[/]

[yellow]No history file found[/]

History file will be created after shell usage.
"""
        except Exception as e:
            return f"""[bold cyan]══ Command History ══[/]

[red]Error reading history: {e}[/]
"""
    
    def on_nav_selected(self, item_id: str) -> None:
        """사이드바 선택 처리 (Enter)."""
        try:
            if item_id == "back":
                self.app.pop_screen()
                return
            if item_id == "shell":
                self._launch_shell()
                return
            self._current_view = item_id
            self._update_content()
        except Exception as e:
            self.log.error(f"Selection error: {e}")

    def _update_content(self) -> None:
        """콘텐츠 업데이트."""
        _titles = {
            "info":    "Shell Info",
            "history": "Command History",
            "shell":   "Launch Shell",
        }
        try:
            self.query_one("#content-title", Static).update(
                _titles.get(self._current_view, "Shell Info")
            )
        except Exception:
            pass
        try:
            content_widget = self.query_one("#shell-content", Static)
            content_widget.update(self._get_content())
        except Exception as e:
            self.log.error(f"Content update error: {e}")
    
    def _launch_shell(self) -> None:
        """대화형 셸을 '로그인한 사용자' 권한으로 실행.

        TUI 는 tty1 에서 root 로 기동되므로, 셸을 그냥 spawn 하면 로그인 계정과
        무관하게 root 셸이 뜬다. 반드시 authenticated_user 로 권한을 강하시키고,
        강하에 실패하면 **셸을 열지 않는다**(root 셸 fallback 금지).
        """
        if self._shell_active:
            return

        # 인증된 사용자가 없으면 셸을 열지 않는다.
        # (예전엔 USER 미설정 시 'root' 로 기본값을 줘서 root 셸이 열렸다)
        user = getattr(self.app, 'authenticated_user', None)
        if not user:
            self._show_error(
                "인증된 사용자 정보가 없어 셸을 실행할 수 없습니다.\n"
                "로그아웃 후 다시 로그인하세요."
            )
            return

        # root 로 강하할 대상이 root 가 아니라면 사전에 권한 강하 가능 여부를 확인한다.
        # sudo -i -u <user> 는 자식 셸의 종료코드를 그대로 전달하므로, 실행 후의
        # 반환값으로는 "강하 실패" 와 "정상 세션이 비정상 종료코드로 끝남" 을
        # 구분할 수 없다. 따라서 spawn 전에 probe 한다.
        drop_privs = os.geteuid() == 0 and user != 'root'
        if drop_privs:
            try:
                probe = subprocess.run(
                    ['sudo', '-n', '-u', user, 'true'],
                    capture_output=True, timeout=10,
                )
            except Exception as e:
                self._show_error(f"권한 강하 확인 실패: {e}")
                return
            if probe.returncode != 0:
                err = probe.stderr.decode('utf-8', errors='replace').strip()
                self.log.error(f"privilege drop to '{user}' failed: {err}")
                self._show_error(
                    f"'{user}' 권한으로 셸을 시작할 수 없습니다.\n"
                    f"{err or f'sudo -u {user} 실패'}\n\n"
                    "보안 정책상 root 셸로 대체하지 않습니다."
                )
                return

        self._shell_active = True
        try:
            # Textual 앱 일시 중지
            with self.app.suspend():
                # 터미널 화면 초기화 (실제 출력해야 화면이 지워짐)
                subprocess.run(['clear'], check=False)

                # 배너 출력
                from datetime import datetime
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # 역할 결정 — 셸이 실제로 실행될 대상 사용자 기준.
                # (프로세스 uid 로 판정하면 TUI 가 root 라서 sands 세션에도
                #  "Administrator (root)" 로 표시돼 실제 권한을 오인하게 된다)
                role = "Administrator (root)" if user == 'root' else "User"

                # ASCII 아트 배너
                print("\033[1;36m")
                print(r"  ███╗   ███╗███╗   ██╗██╗  ██╗    ███╗   ██╗██████╗ ██████╗ ")
                print(r"  ████╗ ████║████╗  ██║╚██╗██╔╝    ████╗  ██║██╔══██╗██╔══██╗")
                print(r"  ██╔████╔██║██╔██╗ ██║ ╚███╔╝     ██╔██╗ ██║██║  ██║██████╔╝")
                print(r"  ██║╚██╔╝██║██║╚██╗██║ ██╔██╗     ██║╚██╗██║██║  ██║██╔══██╗")
                print(r"  ██║ ╚═╝ ██║██║ ╚████║██╔╝ ██╗    ██║ ╚████║██████╔╝██║  ██║")
                print(r"  ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝    ╚═╝  ╚═══╝╚═════╝ ╚═╝  ╚═╝")
                print("\033[0m")
                print("\033[1;33m            SANDS LAB Inc.  NDR SOLUTION SYSTEM \033[0m")
                print()
                
                # 사용자 정보 박스
                print("\033[1;36m╔══════════════════════════════════════════════════════════╗\033[0m")
                print("\033[1;36m║\033[0m                                                          \033[1;36m║\033[0m")
                
                # 사용자 이름 (중앙 정렬)
                user_text = f"Logged in as: {user}"
                user_padding = (58 - len(user_text)) // 2
                print(f"\033[1;36m║\033[0m{' ' * user_padding}\033[1;32m{user_text}\033[0m{' ' * (58 - user_padding - len(user_text))}\033[1;36m║\033[0m")
                
                # 역할 (중앙 정렬)
                role_text = f"Role: {role}"
                role_padding = (58 - len(role_text)) // 2
                print(f"\033[1;36m║\033[0m{' ' * role_padding}\033[1;33m{role_text}\033[0m{' ' * (58 - role_padding - len(role_text))}\033[1;36m║\033[0m")
                
                print("\033[1;36m║\033[0m                                                          \033[1;36m║\033[0m")
                
                # 시간 정보 (중앙 정렬)
                time_text = f"Session started: {now}"
                time_padding = (58 - len(time_text)) // 2
                print(f"\033[1;36m║\033[0m{' ' * time_padding}\033[1;37m{time_text}\033[0m{' ' * (58 - time_padding - len(time_text))}\033[1;36m║\033[0m")
                
                print("\033[1;36m║\033[0m                                                          \033[1;36m║\033[0m")
                print("\033[1;36m╚══════════════════════════════════════════════════════════╝\033[0m")
                print()
                print("\033[1;37mType 'exit' to return to MNX Console\033[0m")
                print()
                
                # 셸 시작 디렉토리를 해당 사용자의 $HOME 으로 변경
                try:
                    import pwd as _pwd
                    home_dir = _pwd.getpwnam(user).pw_dir
                except Exception:
                    home_dir = os.environ.get('HOME', '/root')
                os.chdir(home_dir)

                # 셸 실행
                # su - user 는 PAM 보안 정책(securetty/pam_wheel)으로 차단되므로
                # sudo -i -u user 사용 (PAM su 우회, sudo 권한 체계 적용)
                #
                # 종료코드는 검사하지 않는다 — sudo 가 자식 셸의 종료코드를 그대로
                # 전달하므로(예: 셸에서 마지막 명령 실패 후 exit → ret=1),
                # ret != 0 을 "강하 실패" 로 보고 root 셸을 띄우면 권한 상승이 된다.
                # 강하 가능 여부는 위에서 이미 probe 로 확인했다.
                if drop_privs:
                    subprocess.call(['sudo', '-i', '-u', user])
                else:
                    # 이미 목표 권한(비root 세션이거나 로그인 사용자가 root)
                    subprocess.call(['/bin/bash', '--login'])

                # 셸 종료 후 터미널 리셋 (출력 숨김)
                subprocess.call(['reset'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        except Exception as e:
            self.log.error(f"Shell launch error: {e}")
            self._show_error(str(e))
        finally:
            self._shell_active = False
    
    def _show_error(self, message: str) -> None:
        """에러 메시지 표시."""
        try:
            content_widget = self.query_one("#shell-content", Static)
            content_widget.update(f"""[bold red]══ Error ══[/]

{message}

[yellow]Press ESC to return[/]
""")
        except Exception:
            pass
    
    def action_go_back(self) -> None:
        """ESC: 세부 뷰 → 메뉴 복귀, 기본 뷰(info) → 이전 화면."""
        if self._current_view != "info":
            self._current_view = "info"
            self._update_content()
            try:
                self.query_one("Sidebar ListView", ListView).focus()
            except Exception:
                pass
        else:
            self.app.pop_screen()