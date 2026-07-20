"""
System Overview Screen

시스템 상세 정보를 표시하는 화면입니다.
왼쪽 메뉴에서 항목 선택 시 해당 섹션만 상세하게 표시됩니다.

Features:
    - 하드웨어 정보 (CPU, RAM, 스토리지)
    - 운영체제 정보
    - 네트워크 인터페이스 목록
    - 실시간 업데이트
"""

from textual.app import ComposeResult
from textual.widgets import Static, ListView
from textual.containers import ScrollableContainer
from textual.binding import Binding
from rich.markup import escape as _rich_escape
import re as _re
import threading

# graidctl 등 외부 CLI 출력에 들어있는 ANSI 색상 escape를 제거하기 위한 패턴.
_ANSI_RE = _re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
from app.ui import tokens
from app.ui.screen import BaseScreen
from app.ui.widgets import SectionTitle


class SystemScreen(BaseScreen):
    """
    시스템 정보 화면.
    
    왼쪽 메뉴에서 항목을 선택하면 해당 섹션의 상세 정보를 표시합니다.
    """
    
    CSS = """
    SystemScreen {
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

    #content-panel {
        width: 100%;
        height: 1fr;
        background: #0c0c0c;
        padding: 1 2;
    }

    #system-info {
        width: 100%;
        height: auto;
        color: white;
        background: #0c0c0c;
    }
    
    #scroll-hint {
        width: 100%;
        height: 1;
        color: #666666;
        text-align: right;
        dock: bottom;
    }
    """
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("f5", "refresh", "Refresh"),
        Binding("f7", "rescan", "Rescan System"),
        Binding("tab", "switch_focus", "Switch", show=False),
        Binding("pageup", "scroll_up", "Page Up", show=False),
        Binding("pagedown", "scroll_down", "Page Down", show=False),
        Binding("home", "scroll_home", "Home", show=False),
        Binding("end", "scroll_end", "End", show=False),
    ]
    
    # 메뉴 항목
    MENU_ITEMS = [
        ("back", "← Back"),
        ("all", "All Information"),
        ("system", "System Info"),
        ("cpu", "CPU Info"),
        ("memory", "Memory Info"),
        ("storage", "Storage Info"),
        ("disk", "Disk Info"),
        ("network", "Network Devices"),
    ]

    SIDEBAR_TITLE = "SYSTEM OVERVIEW"
    SIDEBAR_ITEMS = MENU_ITEMS          # nav_id 가 곧 현재 뷰 키
    FOOTER_KEYS = [
        ("↑↓", "Select"),
        ("Enter", "Open"),
        ("F5", "Refresh"),
        ("F7", "Rescan"),
        ("F10", "Exit"),
        ("ESC", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_view = "all"

    def compose_content(self) -> ComposeResult:
        yield SectionTitle("All Information", id="content-title")
        with ScrollableContainer(id="content-panel"):
            yield Static(self._get_all_info(), id="system-info")
            yield Static("[bright_black]Tab: switch focus | ↑↓ PgUp/PgDn: scroll[/]", id="scroll-hint")

    def on_mount(self) -> None:
        """화면 마운트 시 초기화."""
        self.log.info("SystemScreen mounted")
        # 사이드바 포커스 및 초기 선택("All Information")
        self.set_timer(0.1, self._initialize_menu)
        # 1초 간격 업데이트
        self._update_handle = self.set_interval(1.0, self._update_info)

    def on_unmount(self) -> None:
        """화면 언마운트 시 타이머 정리."""
        if getattr(self, "_update_handle", None):
            self._update_handle.stop()

    def _initialize_menu(self) -> None:
        """사이드바 초기 포커스/선택."""
        try:
            menu_list = self.query_one("Sidebar ListView", ListView)
            menu_list.focus()
            if menu_list.children:
                menu_list.index = 1  # "All Information"
        except Exception as e:
            self.log.error(f"Menu init failed: {e}")

    def on_nav_selected(self, item_id: str) -> None:
        """사이드바 선택 처리 (Enter)."""
        try:
            if item_id == "back":
                self.app.pop_screen()
                return
            self._current_view = item_id
            self._update_info()
        except Exception as e:
            self.log.error(f"Selection error: {e}")

    def _update_info(self) -> None:
        """정보 업데이트. (blocking subprocess를 스레드로 오프로드 — UI 프리즈 방지)"""
        _titles = {
            "all":     "All Information",
            "system":  "System Info",
            "cpu":     "CPU Info",
            "memory":  "Memory Info",
            "storage": "Storage Info",
            "disk":    "Disk Info",
            "network": "Network Devices",
        }
        try:
            self.query_one("#content-title", Static).update(
                _titles.get(self._current_view, "All Information")
            )
        except Exception:
            pass

        view = self._current_view

        def _collect():
            try:
                if view == "all":
                    data = self._get_all_info()
                elif view == "system":
                    data = self._get_system_detail()
                elif view == "cpu":
                    data = self._get_cpu_detail()
                elif view == "memory":
                    data = self._get_memory_detail()
                elif view == "storage":
                    data = self._get_storage_detail()
                elif view == "disk":
                    try:
                        data = self._get_disk_info()
                    except Exception:
                        import traceback as _tb
                        data = ("[red]Disk Info render error[/]\n\n"
                                + _rich_escape(_tb.format_exc()))
                elif view == "network":
                    data = self._get_network_detail()
                else:
                    data = ""
            except Exception as e:
                data = f"[red]Update error: {e}[/]"
            self.app.call_from_thread(self._render_info, data)

        threading.Thread(target=_collect, daemon=True).start()

    def _render_info(self, content: str) -> None:
        """UI 업데이트 (메인 스레드에서 call_from_thread로 호출)."""
        try:
            self.query_one("#system-info", Static).update(content)
        except Exception as e:
            self.log.error(f"Render failed: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # 정보 수집 헬퍼
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_info(self):
        """시스템 정보 가져오기."""
        if not self.app.system_info:
            return None
        return self.app.system_info.get_comprehensive_info()
    
    def _get_mem_usage(self):
        """실시간 메모리 사용량."""
        if not self.app.system_info:
            return {}
        return self.app.system_info.get_memory_usage()
    
    # ═══════════════════════════════════════════════════════════════════════
    # 전체 정보
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_all_info(self) -> str:
        """전체 시스템 정보."""
        try:
            info = self._get_info()
            if not info:
                return "[red]System info module not available[/]"
            
            system = info.get('system', {})
            cpu = info.get('cpu', {})
            memory = info.get('memory', {})
            disk = info.get('disk', {})
            network = info.get('network', [])
            load = info.get('load', {})
            mem_usage = self._get_mem_usage()
            
            mem_bar = self._format_bar(mem_usage.get('usage_percent', 0))
            disk_usage = self.app.system_info.get_disk_usage() if self.app.system_info else 'N/A'

            content = "[bold cyan]═══ System Overview ═══[/]\n\n"
            content += tokens.panel("System", (
                f"Product  : {system.get('product_name', 'Unknown')}\n"
                f"Hostname : {info.get('hostname', 'Unknown')}\n"
                f"OS       : {system.get('os_version', 'Unknown')}\n"
                f"Kernel   : {system.get('kernel', 'Unknown')}\n"
                f"Uptime   : {info.get('uptime', 'Unknown')}"
            )) + "\n\n"
            content += tokens.panel("CPU", (
                f"Model    : {self._truncate(cpu.get('model', 'Unknown'), 45)}\n"
                f"Cores    : {cpu.get('cores', 0)} / {cpu.get('threads', 0)} threads\n"
                f"Arch     : {cpu.get('architecture', 'Unknown')}"
            )) + "\n\n"
            content += tokens.panel("Memory", (
                f"Total    : {memory.get('total_gb', 0):.1f} GB\n"
                f"Used     : {mem_usage.get('used_gb', 0):.1f} GB\n"
                f"Usage    : {mem_bar}"
            )) + "\n\n"
            content += tokens.panel("Storage", (
                f"Type     : {disk.get('filesystem', 'Unknown')}\n"
                f"Usage    : {disk_usage}"
            )) + "\n\n"
            content += tokens.panel("Load", (
                f"1/5/15   : {load.get('1min', 0):.2f}, "
                f"{load.get('5min', 0):.2f}, {load.get('15min', 0):.2f}"
            )) + "\n\n"
            content += tokens.panel("Network",
                f"{len(network)} interface(s) detected") + "\n"
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # System 상세
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_system_detail(self) -> str:
        """시스템 상세 정보."""
        try:
            info = self._get_info()
            if not info:
                return "[red]System info not available[/]"
            
            system = info.get('system', {})
            load = info.get('load', {})
            
            content = f"""[bold cyan]═══ System Information ═══[/]

[yellow]Hardware:[/]
  Product Name   : {system.get('product_name', 'Unknown')}
  
[yellow]Operating System:[/]
  OS Version     : {system.get('os_version', 'Unknown')}
  Kernel Version : {system.get('kernel', 'Unknown')}
  
[yellow]Host:[/]
  Hostname       : {info.get('hostname', 'Unknown')}
  Main IP        : {system.get('main_ip', 'Unknown')}
  Current User   : {system.get('current_user', 'Unknown')}
  
[yellow]Uptime:[/]
  System Uptime  : {info.get('uptime', 'Unknown')}
  
[yellow]Load Average:[/]
  1 minute       : [white]{load.get('1min', 0):.2f}[/]
  5 minutes      : [white]{load.get('5min', 0):.2f}[/]
  15 minutes     : [white]{load.get('15min', 0):.2f}[/]
"""
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # CPU 상세
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_cpu_detail(self) -> str:
        """CPU 상세 정보."""
        try:
            info = self._get_info()
            if not info:
                return "[red]System info not available[/]"
            
            cpu = info.get('cpu', {})
            
            content = f"""[bold cyan]═══ CPU Information ═══[/]

[yellow]Processor:[/]
  Model          : {cpu.get('model', 'Unknown')}
  
[yellow]Configuration:[/]
  Physical Cores : [white]{cpu.get('cores', 0)}[/]
  Logical CPUs   : [white]{cpu.get('threads', 0)}[/]
  Architecture   : [white]{cpu.get('architecture', 'Unknown')}[/]
  
[yellow]Performance:[/]
  Base Frequency : [white]{cpu.get('frequency', 'Unknown')}[/]
"""
            # 실시간 CPU 사용률
            if self.app.perf_monitor:
                try:
                    # 총 CPU 사용률
                    summary = self.app.perf_monitor.get_performance_summary()
                    cpu_total = summary.get('cpu_total', 0)
                    cpu_bar = self._format_bar(cpu_total, 30)
                    content += f"""
[yellow]Current Usage:[/]
  Total CPU      : {cpu_bar}
"""
                except Exception as e:
                    content += f"\n[bright_black]Error getting CPU stats: {e}[/]\n"
            
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    def _format_mini_bar(self, percentage: float, width: int = 8) -> str:
        """작은 사용률 바 생성."""
        try:
            filled = int((percentage / 100) * width)
            filled = max(0, min(width, filled))
            
            bar = "▓" * filled + "░" * (width - filled)
            
            if percentage >= 90:
                color = "red"
            elif percentage >= 75:
                color = "yellow"
            else:
                color = "green"
            
            return f"[{color}]{bar}[/]{percentage:5.1f}%"
        except Exception:
            return f"{percentage:.1f}%"
    
    # ═══════════════════════════════════════════════════════════════════════
    # Memory 상세
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_memory_detail(self) -> str:
        """메모리 상세 정보."""
        try:
            info = self._get_info()
            if not info:
                return "[red]System info not available[/]"
            
            memory = info.get('memory', {})
            mem_usage = self._get_mem_usage()
            
            total = memory.get('total_gb', 0)
            used = mem_usage.get('used_gb', 0)
            available = mem_usage.get('available_gb', 0)
            usage_pct = mem_usage.get('usage_percent', 0)
            
            mem_bar = self._format_bar(usage_pct, 40)
            
            content = f"""[bold cyan]═══ Memory Information ═══[/]

[yellow]Physical Memory:[/]
  Total Capacity : [white]{total:.2f} GB[/]
  
[yellow]Current Usage:[/]
  Used           : [yellow]{used:.2f} GB[/]
  Available      : [green]{available:.2f} GB[/]
  Usage          : {mem_bar}

[yellow]DIMM Configuration:[/]
  Installed      : [white]{memory.get('installed_modules', 'N/A')} module(s)[/]
  Total Slots    : [white]{memory.get('total_slots', 'N/A')}[/]

[yellow]Visual:[/]
"""
            # 시각적 표현
            used_blocks = int((used / total) * 50) if total > 0 else 0
            free_blocks = 50 - used_blocks
            content += f"  [yellow]{'█' * used_blocks}[/][green]{'░' * free_blocks}[/]\n"
            content += f"  [yellow]Used ({used:.1f}GB)[/]{'─' * 15}[green]Free ({available:.1f}GB)[/]\n"
            
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # Storage 상세
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_storage_detail(self) -> str:
        """스토리지 상세 정보."""
        try:
            # 모니터링할 중요 마운트 포인트
            IMPORTANT_MOUNTS = {
                '/': 'Root',
                '/docker': 'Docker',
                '/logs': 'Logs',
                '/pipeline': 'Pipeline',
                '/application': 'Application',
                '/data': 'Data',
                '/dir_cache': 'Dir Cache',
            }
            
            content = "[bold cyan]═══ Storage Information ═══[/]\n\n"
            
            # df 명령 결과 파싱
            try:
                import subprocess
                result = subprocess.run(['df', '-hT'], capture_output=True, text=True, timeout=5)
                
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    
                    # 헤더
                    content += "[yellow]Important Mount Points:[/]\n\n"
                    content += f"  {'Mount Point':<15} {'Type':<8} {'Size':>8} {'Used':>8} {'Avail':>8} {'Use%':>6}  {'Status':<10}\n"
                    content += f"  {'─' * 15} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 6}  {'─' * 10}\n"
                    
                    # 마운트된 포인트 파싱
                    mounted_points = {}
                    for line in lines[1:]:
                        parts = line.split()
                        if len(parts) >= 7:
                            filesystem = parts[0]
                            fstype = parts[1]
                            size = parts[2]
                            used = parts[3]
                            avail = parts[4]
                            use_percent = parts[5].rstrip('%')
                            mount_point = parts[6]
                            
                            mounted_points[mount_point] = {
                                'filesystem': filesystem,
                                'type': fstype,
                                'size': size,
                                'used': used,
                                'avail': avail,
                                'use_percent': use_percent,
                            }
                    
                    # 중요 마운트 포인트 표시
                    for mount_path, label in IMPORTANT_MOUNTS.items():
                        if mount_path in mounted_points:
                            mp = mounted_points[mount_path]
                            try:
                                use_pct = int(mp['use_percent'])
                            except Exception:
                                use_pct = 0
                            
                            # 상태 판단
                            if use_pct > 80:
                                status = "[yellow]WARNING[/]"
                                status_icon = "[yellow]●[/]"
                            else:
                                status = "[green]OK[/]"
                                status_icon = "[green]●[/]"
                            
                            content += f"  {status_icon} {mount_path:<13} {mp['type']:<8} {mp['size']:>8} {mp['used']:>8} {mp['avail']:>8} {mp['use_percent']:>5}%  {status}\n"
                        else:
                            # 마운트 안됨
                            content += f"  [red]●[/] {mount_path:<13} {'---':<8} {'---':>8} {'---':>8} {'---':>8} {'---':>6}  [red]FAULT[/]\n"
                    
                    # 요약
                    content += "\n[yellow]Status Legend:[/]\n"
                    content += "  [green]● OK[/]      : Mounted, usage ≤ 80%\n"
                    content += "  [yellow]● WARNING[/] : Mounted, usage > 80%\n"
                    content += "  [red]● FAULT[/]   : Not mounted\n"
                    
            except Exception as e:
                content += f"  [red]Unable to get mount point information: {e}[/]\n"
            
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # Disk Info (raid.cfg 기반 CLI 자동 선택)
    # ═══════════════════════════════════════════════════════════════════════

    _RAID_CFG = "/mnxmc/raid.cfg"

    # (raid_type, cli_path) — 감지된 타입과 일치하는 항목만 사용
    _RAID_CLI_CANDIDATES = [
        ("megaraid",  "/usr/local/bin/storcli64"),
        ("dell_perc", "/usr/local/bin/perccli64"),
        ("dell_perc", "/opt/MegaRAID/perccli/perccli64"),
        ("graid",     "/usr/bin/graidctl"),
    ]

    @staticmethod
    def _probe_cli(raid_type: str, cli_path: str) -> bool:
        """
        CLI를 실제 실행하여 컨트롤러 응답 여부 확인.

        - megaraid/dell_perc: `/call show` 출력에 "Status = Success" 포함 확인
        - graid           : `version` 명령 정상 종료 확인
        """
        import subprocess
        try:
            if raid_type == "graid":
                r = subprocess.run(
                    ["sudo", cli_path, "version"],
                    capture_output=True, text=True, timeout=10,
                )
                return r.returncode == 0
            r = subprocess.run(
                ["sudo", cli_path, "/call", "show"],
                capture_output=True, text=True, timeout=10,
            )
            return "Status = Success" in r.stdout
        except Exception:
            return False

    def _load_raid_cfg(self) -> tuple[str, str]:
        """
        RAID CLI 경로 결정 — 우선순위:
          1. /mnxmc/raid.cfg (수동 지정, 최우선)
          2. 설치된 CLI를 실제 실행 → "Status = Success" 응답하는 CLI 채택
          3. 실행 응답 없음 — 설치된 CLI 순서 fallback (바이너리 존재 여부만)
        """
        import os

        # ── 1순위: raid.cfg 명시적 설정 ───────────────────────────────────
        try:
            cfg = {}
            with open(self._RAID_CFG) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        cfg[k.strip()] = v.strip()
            raid_type = cfg.get("RAID_TYPE", "")
            raid_cli  = cfg.get("RAID_CLI", "")
            if raid_type and raid_cli:
                return raid_type, raid_cli
        except Exception:
            pass

        # ── 2순위: CLI 실행 응답 기반 자동 선택 ──────────────────────────
        for raid_type, cli_path in self._RAID_CLI_CANDIDATES:
            if os.path.isfile(cli_path) and self._probe_cli(raid_type, cli_path):
                return raid_type, cli_path

        # ── 3순위: 바이너리 존재 여부 fallback ───────────────────────────
        for raid_type, cli_path in self._RAID_CLI_CANDIDATES:
            if os.path.isfile(cli_path):
                return raid_type, cli_path

        return "", ""

    def _get_disk_info(self) -> str:
        """RAID VD/PD 정보 — /mnxmc/raid.cfg 에서 CLI 결정."""
        import subprocess

        raid_type, cli = self._load_raid_cfg()

        if not cli:
            return (
                "[bold cyan]═══ Disk Info ═══[/]\n\n"
                "[red]RAID CLI를 찾을 수 없습니다.[/]\n\n"
                "[white]확인 사항:[/]\n"
                "  • sudo bash /mnxmc/packages/install_packages.sh 실행\n"
                "  • storcli64 / perccli64 / graidctl 설치 여부 확인\n"
                f"  • {self._RAID_CFG} 파일 존재 여부 확인\n"
            )

        type_label = {
            "megaraid":  "MegaRAID (StorCLI)",
            "dell_perc": "Dell PERC (PercCLI)",
            "graid":     "GRAID SupremeRAID (graidctl)",
        }.get(raid_type, raid_type)

        content = f"[bold cyan]═══ Disk Info ═══[/]\n\n"
        content += f"[bright_black]RAID Type : {type_label}[/]\n"
        content += f"[bright_black]CLI       : {cli}[/]\n\n"

        def _run_cmd(args: list, header_marker: str) -> str:
            """CLI 실행 후 해당 테이블 섹션만 추출 (storcli/perccli)."""
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    err = result.stderr.strip() or result.stdout.strip()
                    return f"  [red]Error: {err}[/]\n"
                in_table = False
                lines_out = []
                for line in result.stdout.splitlines():
                    stripped = line.strip()
                    if stripped.startswith(header_marker):
                        in_table = True
                    if in_table:
                        if stripped == "" and lines_out:
                            break
                        lines_out.append(f"  {line}")
                if lines_out:
                    return "\n".join(lines_out) + "\n"
                return "  [bright_black]No data found.[/]\n"
            except FileNotFoundError:
                return f"  [red]CLI not found: {cli}[/]\n"
            except subprocess.TimeoutExpired:
                return "  [red]Timeout[/]\n"
            except Exception as e:
                return f"  [red]Error: {e}[/]\n"

        def _run_graidctl(args: list) -> str:
            """graidctl 실행 후 박스 테이블만 추출 (✔ 상태 줄은 제외).

            graidctl은 stdout에 ANSI 색상 escape(\\x1b[...m)를 포함해 출력하므로
            먼저 `_ANSI_RE`로 strip 후 `_rich_escape`로 Rich 마크업 안전화한다.
            """
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    err = _ANSI_RE.sub("", result.stderr.strip() or result.stdout.strip())
                    return f"  [red]Error: {_rich_escape(err)}[/]\n"
                lines_out = []
                for line in result.stdout.splitlines():
                    line = _ANSI_RE.sub("", line)
                    stripped = line.strip()
                    if not stripped or stripped.startswith("✔"):
                        continue
                    lines_out.append(f"  {_rich_escape(line)}")
                if lines_out:
                    return "\n".join(lines_out) + "\n"
                return "  [bright_black]No data found.[/]\n"
            except FileNotFoundError:
                return f"  [red]CLI not found: {cli}[/]\n"
            except subprocess.TimeoutExpired:
                return "  [red]Timeout[/]\n"
            except Exception as e:
                return f"  [red]Error: {e}[/]\n"

        if raid_type == "graid":
            # ── Drive Group LIST ─────────────────────────────────────────
            content += "[yellow]Drive Group List (DG LIST):[/]\n"
            content += _run_graidctl(["sudo", cli, "list", "drive_group"])
            content += "\n"

            # ── Virtual Drive LIST ───────────────────────────────────────
            content += "[yellow]Virtual Drive List (VD LIST):[/]\n"
            content += _run_graidctl(["sudo", cli, "list", "virtual_drive"])
            content += "\n"

            # ── Physical Drive LIST ──────────────────────────────────────
            content += "[yellow]Physical Drive List (PD LIST):[/]\n"
            content += _run_graidctl(["sudo", cli, "list", "physical_drive"])
        else:
            # ── VD LIST ──────────────────────────────────────────────────
            content += "[yellow]Virtual Drive List (VD LIST):[/]\n"
            content += _run_cmd(["sudo", cli, "/c0", "/vall", "show"], "DG/VD")
            content += "\n"

            # ── PD LIST ──────────────────────────────────────────────────
            content += "[yellow]Physical Drive List (PD LIST):[/]\n"
            content += _run_cmd(["sudo", cli, "/c0", "/eall", "/sall", "show"], "EID:Slt")

        content += self._get_footer()
        return content

    # ═══════════════════════════════════════════════════════════════════════
    # Network 상세
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_network_detail(self) -> str:
        """네트워크 상세 정보."""
        try:
            info = self._get_info()
            if not info:
                return "[red]System info not available[/]"
            
            network = info.get('network', [])
            
            content = f"""[bold cyan]═══ Network Devices ═══[/]

[yellow]Detected Network Controllers:[/] {len(network)}
"""
            if network:
                for idx, iface in enumerate(network):
                    pci = iface.get('pci_addr', 'N/A')
                    vendor = iface.get('vendor', 'Unknown')
                    controller = iface.get('controller', 'Unknown')
                    speed = iface.get('speed', 'Unknown')
                    
                    content += f"""
  [cyan]Interface #{idx + 1}[/]
    PCI Address : {pci}
    Vendor      : {vendor}
    Controller  : {self._truncate(controller, 50)}
    Speed       : {speed}
"""
            else:
                content += "\n  No network interfaces detected\n"
            
            # 활성 인터페이스 정보 (network_mgmt가 있으면)
            if self.app.network_mgmt:
                try:
                    # discover_interfaces()는 F8(Rescan Network) 시에만 호출
                    # 매초 호출 방지: 캐시된 interfaces 직접 사용
                    interfaces = self.app.network_mgmt.interfaces
                    
                    content += "\n[yellow]Active Interfaces:[/]\n"
                    for iface in interfaces[:5]:
                        status_color = "green" if iface.status == "UP" else "red"
                        content += f"  {iface.name:<12} [{status_color}]{iface.status:<6}[/] "
                        content += f"IP: {iface.ip}  MAC: {iface.mac}\n"
                except Exception:
                    pass
            
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # 유틸리티
    # ═══════════════════════════════════════════════════════════════════════
    
    def _format_bar(self, percentage: float, width: int = 20) -> str:
        """사용률 바 생성."""
        try:
            filled = int((percentage / 100) * width)
            filled = max(0, min(width, filled))
            
            bar = "▓" * filled + "░" * (width - filled)
            
            if percentage >= 90:
                color = "red"
            elif percentage >= 75:
                color = "yellow"
            else:
                color = "green"
            
            return f"[{color}]{bar}[/] {percentage:.1f}%"
        except Exception:
            return f"{percentage:.1f}%"
    
    def _truncate(self, text: str, max_length: int) -> str:
        """텍스트 자르기."""
        if len(text) > max_length:
            return text[:max_length - 3] + "..."
        return text
    
    def _get_footer(self) -> str:
        """하단 안내."""
        return """
[cyan]────────────────────────────────────────[/]
[white]Press [yellow]F5[/] refresh, [yellow]F7[/] rescan, [yellow]ESC[/] return[/]"""
    
    # ═══════════════════════════════════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════════════════════════════════
    
    def action_go_back(self) -> None:
        """ESC: 세부 뷰 → 메뉴 복귀, 기본 뷰(all) → 이전 화면."""
        if self._current_view != "all":
            self._current_view = "all"
            self._update_info()
            try:
                menu = self.query_one("Sidebar ListView", ListView)
                menu.index = 1  # "All Information"
                menu.focus()
            except Exception:
                pass
        else:
            self.app.pop_screen()
    
    def action_refresh(self) -> None:
        """F5: 새로고침."""
        self._update_info()
    
    def action_rescan(self) -> None:
        """F7: 시스템 재스캔."""
        try:
            if self.app.system_info:
                self.app.system_info.rescan_system()
                self._update_info()
        except Exception as e:
            self.log.error(f"Rescan failed: {e}")
    
    def action_scroll_up(self) -> None:
        """Page Up: 페이지 위로."""
        try:
            content = self.query_one("#content-panel", ScrollableContainer)
            content.scroll_page_up()
        except Exception:
            pass
    
    def action_scroll_down(self) -> None:
        """Page Down: 페이지 아래로."""
        try:
            content = self.query_one("#content-panel", ScrollableContainer)
            content.scroll_page_down()
        except Exception:
            pass
    
    def action_scroll_home(self) -> None:
        """Home: 맨 위로."""
        try:
            content = self.query_one("#content-panel", ScrollableContainer)
            content.scroll_home()
        except Exception:
            pass
    
    def action_scroll_end(self) -> None:
        """End: 맨 아래로."""
        try:
            content = self.query_one("#content-panel", ScrollableContainer)
            content.scroll_end()
        except Exception:
            pass
    
    def action_switch_focus(self) -> None:
        """Tab: 메뉴와 콘텐츠 간 포커스 전환."""
        try:
            menu = self.query_one("Sidebar ListView", ListView)
            content = self.query_one("#content-panel", ScrollableContainer)
            
            if menu.has_focus:
                content.focus()
            else:
                menu.focus()
        except Exception:
            pass