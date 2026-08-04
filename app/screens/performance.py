"""
Performance Monitor Screen

CPU, 메모리, 네트워크 성능을 실시간으로 모니터링하는 화면입니다.
왼쪽 메뉴에서 항목 선택 시 해당 섹션만 상세하게 표시됩니다.

Features:
    - CPU 전체 및 코어별 사용률
    - 메모리 사용률 및 상세 정보
    - 네트워크 I/O 속도
    - 상위 프로세스 목록
    - 1초 간격 실시간 업데이트
"""

import threading

from textual.app import ComposeResult
from textual.widgets import Static, ListView
from textual.containers import ScrollableContainer
from textual.binding import Binding

from app.ui import tokens
from app.ui.screen import BaseScreen
from app.ui.widgets import SectionTitle, fmt_bytes


class PerformanceScreen(BaseScreen):
    """
    성능 모니터 화면.

    공통 디자인 시스템(BaseScreen)의 4구획 골격을 사용하며,
    좌측 사이드바에서 항목을 선택하면 해당 섹션의 상세 정보를 표시합니다.
    콘텐츠 렌더링 로직은 기존과 동일하게 유지합니다.
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("f5", "refresh", "Refresh"),
        Binding("tab", "switch_focus", "Switch", show=False),
        Binding("pageup", "scroll_up", "Page Up", show=False),
        Binding("pagedown", "scroll_down", "Page Down", show=False),
        Binding("home", "scroll_home", "Home", show=False),
        Binding("end", "scroll_end", "End", show=False),
    ]

    SIDEBAR_TITLE = "PERFORMANCE"

    # (nav_id, 라벨) — nav_id 는 곧 현재 뷰(view) 키
    SIDEBAR_ITEMS = [
        ("back",    "← Back"),
        ("all",     "All Information"),
        ("cpu",     "CPU Usage"),
        ("memory",  "Memory Usage"),
        ("disk",    "Disk I/O Stats"),
        ("network", "Network I/O"),
        ("process", "Top Processes"),
    ]

    FOOTER_KEYS = [
        ("↑↓", "Select"),
        ("Enter", "Open"),
        ("F5", "Refresh"),
        ("Tab", "Focus"),
        ("F10", "Exit"),
        ("ESC", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._max_cores_display = 32
        self._current_view = "all"  # 현재 표시 중인 뷰

    def compose_content(self) -> ComposeResult:
        yield SectionTitle("All Information", id="content-title")
        with ScrollableContainer(id="content-panel"):
            yield Static(self._get_all_info(), id="perf-info")
            yield Static("[bright_black]Tab: switch focus | ↑↓ PgUp/PgDn: scroll[/]", id="scroll-hint")

    def on_mount(self) -> None:
        """화면 마운트 시 초기화."""
        self.log.info("PerformanceScreen mounted")
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
        """정보 업데이트. (비동기 — blocking subprocess를 스레드로 오프로드)"""
        _titles = {
            "all":     "All Information",
            "cpu":     "CPU Usage",
            "memory":  "Memory Usage",
            "disk":    "Disk I/O",
            "network": "Network I/O",
            "process": "Top Processes",
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
                elif view == "cpu":
                    data = self._get_cpu_detail()
                elif view == "memory":
                    data = self._get_memory_detail()
                elif view == "disk":
                    data = self._get_disk_detail()
                elif view == "network":
                    data = self._get_network_detail()
                elif view == "process":
                    data = self._get_process_detail()
                else:
                    data = ""
                self.app.call_from_thread(self._render_info, data)
            except Exception as e:
                self.app.call_from_thread(
                    self._render_info, f"[red]Update error: {e}[/]"
                )

        threading.Thread(target=_collect, daemon=True).start()

    def _render_info(self, content: str) -> None:
        """UI 업데이트 (메인 스레드에서 call_from_thread로 호출)."""
        try:
            self.query_one("#perf-info", Static).update(content)
        except Exception as e:
            self.log.error(f"Render failed: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # 전체 정보
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_all_info(self) -> str:
        """전체 성능 정보."""
        try:
            if not self.app.perf_monitor:
                return "[red]Performance monitor not available[/]"
            
            summary = self.app.perf_monitor.get_performance_summary()

            content = "[bold cyan]═══ Performance Monitor ═══[/]\n\n"
            content += tokens.panel("CPU", self._format_cpu_summary(summary).strip("\n")) + "\n\n"
            content += tokens.panel("Memory", self._format_memory_summary(summary).strip("\n")) + "\n\n"
            content += tokens.panel("Disk I/O", self._format_disk_summary().strip("\n")) + "\n\n"
            content += tokens.panel("Network I/O", self._format_network_summary(summary).strip("\n")) + "\n\n"
            content += tokens.panel("Top Processes", self._format_process_summary().strip("\n")) + "\n"
            content += self._get_footer()

            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # CPU 상세 정보
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_cpu_detail(self) -> str:
        """CPU 상세 정보."""
        try:
            if not self.app.perf_monitor:
                return "[red]Performance monitor not available[/]"
            
            summary = self.app.perf_monitor.get_performance_summary()
            
            content = "[bold cyan]═══ CPU Usage Detail ═══[/]\n\n"
            
            # 전체 사용률
            cpu_total = summary.get('cpu_total', 0)
            cpu_bar = self._create_bar(cpu_total, 40)
            content += f"[yellow]Total CPU Usage:[/]\n"
            content += f"  {cpu_bar}\n\n"
            
            # Load Average
            load = summary.get('load_avg', {})
            content += "[yellow]Load Average:[/]\n"
            content += f"  1 min:  [white]{load.get('1min', 0):.2f}[/]\n"
            content += f"  5 min:  [white]{load.get('5min', 0):.2f}[/]\n"
            content += f"  15 min: [white]{load.get('15min', 0):.2f}[/]\n\n"
            
            # 코어별 사용률 (전체)
            cpu_per_core = summary.get('cpu_per_core', [])
            
            if cpu_per_core:
                content += f"[yellow]Per-Core Usage ({len(cpu_per_core)} cores):[/]\n"
                content += "  " + "─" * 60 + "\n"
                
                # 2열 표시
                cols = 2
                for i in range(0, len(cpu_per_core), cols):
                    line = "  "
                    for j in range(cols):
                        idx = i + j
                        if idx < len(cpu_per_core):
                            core_id, usage = cpu_per_core[idx]
                            bar = self._create_bar(usage, 15)
                            line += f"CPU{core_id:2d}: {bar}  "
                    content += line + "\n"
            
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # Memory 상세 정보
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_memory_detail(self) -> str:
        """메모리 상세 정보."""
        try:
            if not self.app.perf_monitor:
                return "[red]Performance monitor not available[/]"
            
            summary = self.app.perf_monitor.get_performance_summary()
            memory = summary.get('memory', {})
            
            content = "[bold cyan]═══ Memory Usage Detail ═══[/]\n\n"
            
            total = memory.get('total_gb', 0)
            used = memory.get('used_gb', 0)
            free = memory.get('free_gb', 0)
            usage_pct = memory.get('usage_pct', 0)
            
            # 사용률 바
            mem_bar = self._create_bar(usage_pct, 40)
            content += f"[yellow]Memory Usage:[/]\n"
            content += f"  {mem_bar}\n\n"
            
            # 상세 정보
            content += "[yellow]Memory Statistics:[/]\n"
            content += f"  Total:     [white]{total:>8.2f} GB[/]\n"
            content += f"  Used:      [yellow]{used:>8.2f} GB[/]\n"
            content += f"  Available: [green]{free:>8.2f} GB[/]\n"
            content += f"  Usage:     [white]{usage_pct:>8.1f} %[/]\n\n"
            
            # 그래픽 표현
            content += "[yellow]Visual Breakdown:[/]\n"
            used_blocks = int((used / total) * 50) if total > 0 else 0
            free_blocks = 50 - used_blocks
            content += f"  [yellow]{'█' * used_blocks}[/][green]{'░' * free_blocks}[/]\n"
            content += f"  [yellow]Used[/]{'─' * 20}[green]Available[/]\n"
            
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # Disk I/O 상세 정보
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_disk_detail(self) -> str:
        """디스크 I/O 상세 정보."""
        try:
            disk_mon = self.app.disk_monitor
            if not disk_mon:
                return "[red]Disk monitor module not available[/]"

            # 통계 가져오기
            stats = disk_mon.get_disk_io_stats()
            
            content = "[bold cyan]═══ Disk I/O Statistics ═══[/]\n\n"
            content += f"[bright_black]Updated: {stats['timestamp']}[/]\n\n"
            
            # 헤더
            content += f"[yellow]  {'Mount':<15} {'Device':<10} {'Read':>10} {'Write':>10} {'IOPS':>8} {'Await':>8} {'Util':>6}  {'State':<10}[/]\n"
            content += f"  {'─' * 15} {'─' * 10} {'─' * 10} {'─' * 10} {'─' * 8} {'─' * 8} {'─' * 6}  {'─' * 10}\n"
            
            for m in stats['mounts']:
                mount = m['mount']
                device = m['device']
                rMBps = f"{m['rMBps']:.1f} MB/s"
                wMBps = f"{m['wMBps']:.1f} MB/s"
                iops = str(m['iops'])
                await_ms = f"{m['await_ms']:.1f} ms"
                util = f"{m['util']}%"
                state = m['state']
                
                # 상태에 따른 색상
                if state == 'SATURATED':
                    state_display = f"[red]● {state}[/]"
                    util_display = f"[red]{util:>6}[/]"
                elif state == 'BUSY':
                    state_display = f"[yellow]● {state}[/]"
                    util_display = f"[yellow]{util:>6}[/]"
                elif state == 'UNMOUNTED':
                    state_display = f"[red]● {state}[/]"
                    util_display = f"[bright_black]{util:>6}[/]"
                elif state == 'NO_DATA':
                    state_display = f"[bright_black]● {state}[/]"
                    util_display = f"[bright_black]{util:>6}[/]"
                else:
                    state_display = f"[green]● {state}[/]"
                    util_display = f"[green]{util:>6}[/]"
                
                content += f"  {mount:<15} {device:<10} {rMBps:>10} {wMBps:>10} {iops:>8} {await_ms:>8} {util_display}  {state_display}\n"
            
            content += "\n[yellow]Status Legend:[/]\n"
            content += "  [green]● NORMAL[/]    : Utilization < 50%\n"
            content += "  [yellow]● BUSY[/]      : Utilization 50-80%\n"
            content += "  [red]● SATURATED[/] : Utilization > 80%\n"
            
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # Network 상세 정보
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_network_detail(self) -> str:
        """네트워크 상세 정보 — 상단 테이블(실시간) / 하단 테이블(정적) 분리."""
        try:
            if not self.app.perf_monitor:
                return "[red]Performance monitor not available[/]"

            summary = self.app.perf_monitor.get_performance_summary()
            network = summary.get('network', {})

            content = "[bold cyan]═══ Network I/O Detail ═══[/]\n\n"

            if not network or 'error' in network:
                content += "[red]Network monitoring unavailable[/]\n"
                return content

            ifaces = [(n, s) for n, s in network.items() if isinstance(s, dict)]

            # ── 상단 테이블: 실시간 데이터 ────────────────────────────────────
            hdr = (
                f"[yellow]{'Interface':<14} {'Status':<8} "
                f"{'RX Rate':<16} {'TX Rate':<16} "
                f"{'RX Total':<12} {'TX Total'}[/]"
            )
            content += hdr + "\n"
            content += "─" * 76 + "\n"

            for iface_name, stats in ifaces:
                status   = stats.get('status', 'UNKNOWN')
                rx_rate  = stats.get('rx_rate_mbps', 0)
                tx_rate  = stats.get('tx_rate_mbps', 0)
                rx_bytes = stats.get('rx_bytes', 0)
                tx_bytes = stats.get('tx_bytes', 0)
                s_color  = "green" if status == "UP" else "red"

                content += (
                    f"  {iface_name:<12} "
                    f"[{s_color}]● {status:<6}[/] "
                    f"↓ {self._format_rate(rx_rate):<14} "
                    f"↑ {self._format_rate(tx_rate):<14} "
                    f"{fmt_bytes(rx_bytes, sep=''):<12} "
                    f"{fmt_bytes(tx_bytes, sep='')}\n"
                )

            # ── 하단 테이블: 정적 정보 ────────────────────────────────────────
            content += "\n" + "─" * 76 + "\n"
            content += (
                f"[yellow]{'Interface':<14} {'MAC Address':<22} "
                f"{'Speed':<14} {'Errors since boot (RX / TX)'}[/]\n"
            )
            content += "─" * 76 + "\n"

            for iface_name, stats in ifaces:
                status = stats.get('status', 'UNKNOWN')
                if status == "UP":
                    mac   = stats.get('mac',       'N/A')
                    speed = stats.get('speed',     'N/A')
                    r_err = stats.get('rx_errors', 0)
                    t_err = stats.get('tx_errors', 0)
                else:
                    mac   = "—"
                    speed = "—"
                    r_err = "—"
                    t_err = "—"

                content += (
                    f"  [bright_black]{iface_name:<12}  "
                    f"{str(mac):<22} {str(speed):<14} "
                    f"RX={r_err}   TX={t_err}[/]\n"
                )

            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # Process 상세 정보
    # ═══════════════════════════════════════════════════════════════════════
    
    def _get_process_detail(self) -> str:
        """프로세스 상세 정보."""
        try:
            if not self.app.perf_monitor:
                return "[red]Performance monitor not available[/]"
            
            content = "[bold cyan]═══ Top Processes Detail ═══[/]\n\n"
            
            processes = self.app.perf_monitor.get_top_processes(15)
            
            if not processes:
                content += "[red]No process data available[/]\n"
                return content
            
            # 헤더
            content += f"[yellow]{'USER':<10} {'PID':<8} {'%CPU':<7} {'%MEM':<7} {'VSZ':<10} {'RSS':<10} {'COMMAND'}[/]\n"
            content += "─" * 80 + "\n"
            
            for proc in processes:
                if 'error' in proc:
                    continue
                
                user = proc.get('user', 'N/A')[:10]
                pid = proc.get('pid', 'N/A')
                cpu = proc.get('cpu', '0')
                mem = proc.get('mem', '0')
                vsz = proc.get('vsz', '0')
                rss = proc.get('rss', '0')
                cmd = proc.get('command', 'N/A')[:35]
                
                # CPU 색상
                try:
                    cpu_val = float(cpu)
                    if cpu_val >= 50:
                        cpu_str = f"[red]{cpu:>6}[/]"
                    elif cpu_val >= 20:
                        cpu_str = f"[yellow]{cpu:>6}[/]"
                    else:
                        cpu_str = f"[white]{cpu:>6}[/]"
                except ValueError:
                    cpu_str = f"[white]{cpu:>6}[/]"
                
                content += f"  {user:<10} {pid:<8} {cpu_str} {mem:>6}  "
                content += f"{vsz:>8}  {rss:>8}  {cmd}\n"
            
            content += "\n[cyan]VSZ: Virtual Memory Size (KB), RSS: Resident Set Size (KB)[/]\n"
            content += self._get_footer()
            return content
        except Exception as e:
            return f"[red]Error: {e}[/]"
    
    # ═══════════════════════════════════════════════════════════════════════
    # 요약 포맷터 (전체 보기용)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _format_cpu_summary(self, summary: dict) -> str:
        """CPU 요약."""
        content = ""
        
        cpu_total = summary.get('cpu_total', 0)
        cpu_bar = self._create_bar(cpu_total)
        content += f"  Total: {cpu_bar}\n"
        
        load = summary.get('load_avg', {})
        content += f"  Load:  {load.get('1min', 0):.2f}, "
        content += f"{load.get('5min', 0):.2f}, "
        content += f"{load.get('15min', 0):.2f}\n\n"
        
        cpu_per_core = summary.get('cpu_per_core', [])
        if cpu_per_core:
            content += "  [cyan]Per-Core Usage:[/]\n"
            cols = 4
            core_count = min(len(cpu_per_core), 16)
            
            for i in range(0, core_count, cols):
                line = "  "
                for j in range(cols):
                    idx = i + j
                    if idx < core_count:
                        core_id, usage = cpu_per_core[idx]
                        mini_bar = self._create_mini_bar(usage)
                        line += f"CPU{core_id:2d}: {mini_bar}  "
                content += line + "\n"
        
        content += "\n"
        return content
    
    def _format_memory_summary(self, summary: dict) -> str:
        """메모리 요약."""
        content = ""
        
        memory = summary.get('memory', {})
        total = memory.get('total_gb', 0)
        used = memory.get('used_gb', 0)
        free = memory.get('free_gb', 0)
        usage_pct = memory.get('usage_pct', 0)
        
        mem_bar = self._create_bar(usage_pct, 30)
        
        content += f"  Total:     {total:.1f} GB\n"
        content += f"  Used:      {used:.1f} GB\n"
        content += f"  Available: {free:.1f} GB\n"
        content += f"  Usage:     {mem_bar}\n\n"
        
        return content
    
    def _format_disk_summary(self) -> str:
        """디스크 I/O 요약."""
        content = ""

        try:
            disk_mon = self.app.disk_monitor
            if not disk_mon:
                content += "  [bright_black]Disk monitoring unavailable[/]\n\n"
                return content

            stats = disk_mon.get_disk_io_stats()
            
            # 상위 3개 마운트 포인트만 표시
            for m in stats['mounts'][:3]:
                mount = m['mount']
                state = m['state']
                util = m['util']
                
                if state == 'SATURATED':
                    state_icon = "[red]●[/]"
                elif state == 'BUSY':
                    state_icon = "[yellow]●[/]"
                elif state in ['UNMOUNTED', 'NO_DATA']:
                    state_icon = "[bright_black]●[/]"
                else:
                    state_icon = "[green]●[/]"
                
                content += f"  {mount:15s} {state_icon} {util:3d}% util\n"
            
            content += "\n"
        except Exception as e:
            content += f"  [bright_black]Error: {e}[/]\n\n"
        
        return content
    
    def _format_network_summary(self, summary: dict) -> str:
        """네트워크 요약."""
        content = ""
        
        network = summary.get('network', {})
        
        if not network or 'error' in network:
            content += "  [red]Network monitoring unavailable[/]\n\n"
            return content
        
        for iface_name, stats in list(network.items())[:3]:
            if not isinstance(stats, dict):
                continue
            
            status = stats.get('status', 'UNKNOWN')
            if status != 'UP':
                continue
            
            rx_rate = stats.get('rx_rate_mbps', 0)
            tx_rate = stats.get('tx_rate_mbps', 0)
            
            content += f"  {iface_name:10s} [green]●[/] "
            content += f"↓ {self._format_rate(rx_rate)} "
            content += f"↑ {self._format_rate(tx_rate)}\n"
        
        content += "\n"
        return content
    
    def _format_process_summary(self) -> str:
        """프로세스 요약."""
        content = ""
        
        try:
            processes = self.app.perf_monitor.get_top_processes(8)
            
            if not processes:
                content += "  No process data\n"
                return content
            
            content += f"  {'USER':<8} {'PID':<7} {'%CPU':<6} {'%MEM':<6} {'COMMAND'}\n"
            content += "  " + "─" * 50 + "\n"
            
            for proc in processes:
                if 'error' in proc:
                    continue
                
                user = proc.get('user', 'N/A')[:8]
                pid = proc.get('pid', 'N/A')[:7]
                cpu = proc.get('cpu', '0')
                mem = proc.get('mem', '0')
                cmd = proc.get('command', 'N/A')[:30]
                
                content += f"  {user:<8} {pid:<7} {cpu:>5} {mem:>5}  {cmd}\n"
        
        except Exception as e:
            content += f"  [red]Error: {e}[/]\n"
        
        return content
    
    # ═══════════════════════════════════════════════════════════════════════
    # 유틸리티
    # ═══════════════════════════════════════════════════════════════════════
    
    def _create_bar(self, percentage: float, width: int = 20) -> str:
        """사용률 바 생성."""
        try:
            filled = int((percentage / 100) * width)
            filled = max(0, min(width, filled))
            
            bar = "█" * filled + "░" * (width - filled)
            
            if percentage >= 90:
                color = "red"
            elif percentage >= 75:
                color = "yellow"
            else:
                color = "green"
            
            return f"[{color}]{bar}[/] {percentage:5.1f}%"
        except Exception:
            return f"{percentage:.1f}%"
    
    def _create_mini_bar(self, percentage: float, width: int = 5) -> str:
        """미니 사용률 바 생성."""
        try:
            filled = int((percentage / 100) * width)
            filled = max(0, min(width, filled))
            
            bar = "█" * filled + "░" * (width - filled)
            
            if percentage >= 90:
                color = "red"
            elif percentage >= 75:
                color = "yellow"
            else:
                color = "green"
            
            return f"[{color}]{bar}[/]{percentage:5.1f}%"
        except Exception:
            return f"{percentage:.1f}%"
    
    def _format_rate(self, mbps: float) -> str:
        """전송률 포맷 (MB/s 입력 → Gbps/Mbps/Kbps 표시)."""
        gbps = mbps / 125.0
        if gbps >= 1.0:
            return f"{gbps:.2f} Gbps"
        mbits = mbps * 8
        if mbits >= 1.0:
            return f"{mbits:.1f} Mbps"
        return f"{mbits * 1000:.0f} Kbps"
    
    def _get_footer(self) -> str:
        """하단 안내."""
        return """
[cyan]────────────────────────────────────────[/]
[white]Auto-refresh: 1s | Press [yellow]F5[/] to refresh, [yellow]ESC[/] to return[/]"""
    
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