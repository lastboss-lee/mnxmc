"""
Log Monitoring Screen

시스템 로그를 실시간으로 모니터링하는 화면입니다.
좌측에 로그 디렉토리/파일 트리, 우측에 로그 내용을 표시합니다.

Features:
    - 로그 디렉토리 트리 네비게이션
    - 실시간 로그 내용 표시
    - 로그 파일 자동 갱신
    - Kafka/ES 모니터 통합
"""

import subprocess
import os
import re
import threading

from textual.app import ComposeResult
from textual.widgets import Static, RichLog, ListView
from textual.binding import Binding

from app.ui.screen import BaseScreen, Sidebar


class LogsScreen(BaseScreen):
    """
    로그 모니터링 화면.
    
    시스템의 다양한 로그 파일을 탐색하고 내용을 실시간으로 표시합니다.
    
    Attributes:
        LOG_SOURCES: 로그 소스 목록
        _current_log: 현재 선택된 로그 소스
        _refresh_handle: 로그 업데이트 타이머
    
    Bindings:
        F5: 로그 새로고침
        ESC: 대시보드로 돌아가기
    """
    
    CSS = """
    LogsScreen {
        background: #0c0c0c;
    }

    #main-container {
        width: 100%;
        height: 100%;
        layout: horizontal;
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

    #log-menu {
        width: 100%;
        height: 1fr;
        background: #0c0c0c;
        border: none;
        padding: 1 0;
    }

    #log-menu > ListItem {
        background: #0c0c0c;
        color: white;
        height: 1;
        padding: 0 2;
    }
    
    #log-menu > ListItem:hover {
        background: #5fd7d7;
        color: black;
    }
    
    #log-menu > ListItem.-section {
        color: #5fd7d7;
        text-style: bold;
    }

    #log-menu > ListItem.-separator {
        color: #5fd7d7;
    }
    
    #right-panel {
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

    #log-content {
        width: 100%;
        height: 1fr;
        background: #0c0c0c;
        scrollbar-size: 1 1;
        padding: 0 2;
    }
    """
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("f5", "refresh", "Refresh"),
    ]
    
    # 로그 소스 메뉴
    LOG_SOURCES = [
        ("← Back", "back"),
        ("──────────────────────────────", None),
        ("Inspection:", None),
        ("  Inspection Summary", "inspection_summary"),
        ("──────────────────────────────", None),
        ("System Logs:", None),
        ("  File Analysis AI", "file_analysis_ai"),
        ("  MNX Capture", "mnxcapture"),
        ("  MNX DPI", "mnxdpi"),
        ("  MNX Service Control", "mnx_service_control"),
        ("  Payload Analysis", "payload_analysis"),
        ("  Suricata", "suricata"),
        ("  Syslog", "syslog"),
        ("──────────────────────────────", None),
        ("Monitoring:", None),
        ("  Kafka Monitor", "kafka"),
        ("  Elasticsearch Monitor", "elasticsearch"),
    ]
    
    SIDEBAR_TITLE = "LOG MONITOR"
    SIDEBAR_BULLET = False   # LOG_SOURCES 라벨이 자체 서식을 가짐

    def __init__(self) -> None:
        """LogsScreen을 초기화합니다."""
        super().__init__()
        self._current_log = None
        self._refresh_handle = None  # 타이머 핸들 (항상 초기화)
        self._prev_net_drops = None  # RX/TX drop delta 계산용 기준값

        # LOG_SOURCES → 사이드바 항목 + 선택 항목 텍스트 맵 구성
        self.SIDEBAR_ITEMS = []
        self._item_text = {}
        for idx, (label, source_id) in enumerate(self.LOG_SOURCES):
            stripped = label.strip()
            if stripped.startswith("─"):
                self.SIDEBAR_ITEMS.append((f"sep-{idx}", label, "separator"))
            elif stripped.endswith(":"):
                self.SIDEBAR_ITEMS.append((f"hdr-{idx}", label, "header"))
            elif source_id == "back":
                self.SIDEBAR_ITEMS.append(("back", "← Back"))
                self._item_text["back"] = "← Back"
            else:
                self.SIDEBAR_ITEMS.append((source_id, stripped))
                self._item_text[source_id] = stripped

    def compose_content(self) -> ComposeResult:
        yield Static("Select a log source", id="content-title")
        yield RichLog(
            id="log-content",
            highlight=True,
            markup=True,
            auto_scroll=True,
            max_lines=2000,
        )

    def on_mount(self) -> None:
        """화면이 마운트될 때 호출됩니다."""
        self.log.info("LogsScreen mounted")
        # 사이드바 항목은 BaseScreen 이 SIDEBAR_ITEMS 로 구성함
        self._show_welcome_message()
        self.set_timer(0.1, self._focus_menu)

    def on_unmount(self) -> None:
        """화면이 언마운트될 때 호출됩니다."""
        if self._refresh_handle is not None:
            self._refresh_handle.stop()
            self._refresh_handle = None

    def _focus_menu(self) -> None:
        """메뉴에 포커스를 설정합니다."""
        try:
            self.query_one("Sidebar ListView", ListView).focus()
        except Exception as e:
            self.log.error(f"Menu focus failed: {e}")
    
    def _show_welcome_message(self) -> None:
        """환영 메시지를 표시합니다."""
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.clear()
            log_widget.write("[bold cyan]═══ Log Monitor ═══[/]")
            log_widget.write("")
            log_widget.write("[white]Select a log source from the menu.[/]")
            log_widget.write("")
            log_widget.write("[yellow]Available log sources:[/]")
            log_widget.write("  • File Analysis AI")
            log_widget.write("  • MNX Capture")
            log_widget.write("  • MNX DPI")
            log_widget.write("  • MNX Service Control")
            log_widget.write("  • Payload Analysis")
            log_widget.write("  • Suricata")
            log_widget.write("  • Syslog")
            log_widget.write("")
            log_widget.write("[yellow]Monitoring:[/]")
            log_widget.write("  • Kafka Monitor")
            log_widget.write("  • Elasticsearch Monitor")
            log_widget.write("")
            log_widget.write("[yellow]Inspection:[/]")
            log_widget.write("  • Inspection Summary  (all checks in one view)")
            log_widget.write("")
            log_widget.write("[cyan]────────────────────────────────────────[/]")
            log_widget.write("[white]Press F5 to refresh, ESC to return[/]")
        except Exception as e:
            self.log.error(f"Welcome message failed: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Menu Selection
    # ═══════════════════════════════════════════════════════════════════════
    
    def on_nav_selected(self, source_id: str) -> None:
        """메뉴 항목 선택을 처리합니다 (BaseScreen 라우팅)."""
        try:
            self.log.info(f"Log menu selected: id='{source_id}'")

            if source_id == "back":
                self.action_go_back()
                return
            elif source_id == "inspection_summary":
                self._current_log = "inspection_summary"
                self._show_inspection_summary()
            elif source_id == "kafka":
                self._current_log = "kafka"
                self._show_kafka_status()
            elif source_id == "elasticsearch":
                self._current_log = "elasticsearch"
                self._show_elasticsearch_status()
            else:
                text = self._item_text.get(source_id, source_id)
                self._current_log = source_id
                self._show_log_content(source_id, text)

            # content-title 업데이트
            try:
                self.query_one("#content-title", Static).update(
                    self._item_text.get(source_id, source_id).strip()
                )
            except Exception:
                pass
            # 선택 후 메뉴 스타일 업데이트
            self._update_menu_styles()

        except Exception as e:
            self.log.error(f"Menu selection error: {e}")

    def _update_menu_styles(self) -> None:
        """현재 선택된 로그 항목에 지속 마커(▸)를 표시합니다."""
        try:
            sidebar = self.query_one(Sidebar)
        except Exception:
            return
        for sid, text in self._item_text.items():
            if sid == "back":
                sidebar.update_item_label("back", "  ← Back")
            elif sid == self._current_log:
                sidebar.update_item_label(sid, f"[cyan]▸ {text}[/]")
            else:
                sidebar.update_item_label(sid, f"  {text}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Log Content Display
    # ═══════════════════════════════════════════════════════════════════════
    
    def _show_log_content(self, source_id: str, source_name: str) -> None:
        """로그 내용을 표시합니다."""
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.clear()
            
            self._current_log = source_id
            
            # 로그 뷰어 모듈 사용
            if self.app.log_viewer:
                log_file = self.app.log_viewer.get_latest_log_file(source_id)
                
                if log_file:
                    log_widget.write(f"[bold cyan]═══ {source_name} ═══[/]")
                    log_widget.write(f"[white]File: {log_file}[/]")
                    log_widget.write("[cyan]" + "─" * 50 + "[/]")
                    log_widget.write("")
                    
                    # 로그 내용 가져오기
                    content = self.app.log_viewer.get_log_content(log_file, lines=50)
                    
                    for line in content:
                        # 로그 레벨에 따른 색상
                        if 'ERROR' in line.upper() or 'FAIL' in line.upper():
                            log_widget.write(f"[red]{line}[/]")
                        elif 'WARN' in line.upper():
                            log_widget.write(f"[yellow]{line}[/]")
                        elif 'INFO' in line.upper():
                            log_widget.write(f"[green]{line}[/]")
                        else:
                            log_widget.write(line)
                else:
                    log_widget.write(f"[bold cyan]═══ {source_name} ═══[/]")
                    log_widget.write("")
                    log_widget.write(f"[yellow]No log files found for {source_id}[/]")
            else:
                log_widget.write(f"[bold cyan]═══ {source_name} ═══[/]")
                log_widget.write("")
                log_widget.write("[red]Log viewer module not available[/]")
            
            # 자동 업데이트 설정
            if hasattr(self, '_refresh_handle') and self._refresh_handle:
                self._refresh_handle.stop()
            self._refresh_handle = self.set_interval(3.0, self._refresh_current_log)
        
        except Exception as e:
            self.log.error(f"Log content error: {e}")
            self._show_error(str(e))
    
    def _show_kafka_status(self) -> None:
        """Kafka 상태를 표시합니다. (비동기 — 이벤트 루프 차단 없음)"""
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.clear()
            self._current_log = "kafka"
            log_widget.write("[bold cyan]═══ Kafka Monitor ═══[/]")
            log_widget.write("")
            log_widget.write("[bright_black]Loading...[/]")

            # 자동 업데이트: 콜백은 _refresh_current_log로 통일 (자기 재등록 방지)
            if self._refresh_handle is not None:
                self._refresh_handle.stop()
            self._refresh_handle = self.set_interval(5.0, self._refresh_current_log)

            def _worker():
                status = self.app.kafka_monitor.get_kafka_status() if self.app.kafka_monitor else None
                self.app.call_from_thread(self._render_kafka_status, status)

            threading.Thread(target=_worker, daemon=True).start()

        except Exception as e:
            self.log.error(f"Kafka status error: {e}")
            self._show_error(str(e))

    def _render_kafka_status(self, status) -> None:
        """Kafka 상태 렌더링 (메인 스레드에서 call_from_thread로 호출)."""
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.clear()
            log_widget.write("[bold cyan]═══ Kafka Monitor ═══[/]")
            log_widget.write("")

            if status is None:
                log_widget.write("[red]Kafka monitor module not available[/]")
                return

            if status.get('is_running'):
                log_widget.write("[green]● Kafka is running[/]")
                log_widget.write(f"[white]Timestamp: {status.get('timestamp', 'N/A')}[/]")
                log_widget.write("")

                raw_data = status.get('raw_data', [])
                if raw_data:
                    log_widget.write("[yellow]MNX Consumer Group:[/]")
                    log_widget.write(f"{'Partition':<10} {'Offset':<12} {'End':<12} {'Lag':<8}")
                    log_widget.write("─" * 50)
                    for item in raw_data:
                        partition = item.get('partition', 'N/A')
                        current = item.get('current_offset', 'N/A')
                        end = item.get('log_end_offset', 'N/A')
                        lag = item.get('lag', 'N/A')
                        log_widget.write(f"{partition:<10} {current:<12} {end:<12} {lag:<8}")
                else:
                    log_widget.write("[yellow]No consumer group data[/]")
            else:
                log_widget.write("[red]○ Kafka is not running[/]")
                log_widget.write(f"[red]Error: {status.get('error', 'Unknown')}[/]")
        except Exception as e:
            self.log.error(f"Kafka render error: {e}")
    
    def _show_elasticsearch_status(self) -> None:
        """Elasticsearch 상태를 표시합니다. (비동기 — 이벤트 루프 차단 없음)"""
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.clear()
            self._current_log = "elasticsearch"
            log_widget.write("[bold cyan]═══ Elasticsearch Monitor ═══[/]")
            log_widget.write("")
            log_widget.write("[bright_black]Loading...[/]")

            # 자동 업데이트: 콜백은 _refresh_current_log로 통일 (자기 재등록 방지)
            if self._refresh_handle is not None:
                self._refresh_handle.stop()
            self._refresh_handle = self.set_interval(10.0, self._refresh_current_log)

            def _worker():
                status = self.app.es_monitor.get_elasticsearch_status() if self.app.es_monitor else None
                self.app.call_from_thread(self._render_elasticsearch_status, status)

            threading.Thread(target=_worker, daemon=True).start()

        except Exception as e:
            self.log.error(f"Elasticsearch status error: {e}")
            self._show_error(str(e))

    def _render_elasticsearch_status(self, status) -> None:
        """ES 상태 렌더링 (메인 스레드에서 call_from_thread로 호출)."""
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.clear()
            log_widget.write("[bold cyan]═══ Elasticsearch Monitor ═══[/]")
            log_widget.write("")

            if status is None:
                log_widget.write("[red]Elasticsearch monitor module not available[/]")
                return

            if status.get('is_running'):
                log_widget.write("[green]● Elasticsearch is running[/]")
                log_widget.write(f"[white]Timestamp: {status.get('timestamp', 'N/A')}[/]")
                log_widget.write("")

                # 클러스터 헬스
                health = status.get('cluster_health', {})
                if health:
                    cluster_status = health.get('status', 'unknown').upper()
                    color = {'GREEN': 'green', 'YELLOW': 'yellow', 'RED': 'red'}.get(cluster_status, 'white')
                    log_widget.write("[yellow]Cluster Health:[/]")
                    log_widget.write(f"  Status: [{color}]{cluster_status}[/]")
                    log_widget.write(f"  Nodes: {health.get('number_of_nodes', 0)}")
                    log_widget.write(f"  Active Shards: {health.get('active_shards', 0)}")
                    log_widget.write(f"  Unassigned: {health.get('unassigned_shards', 0)}")

                    if cluster_status in ('YELLOW', 'RED'):
                        unhealthy = status.get('unhealthy_indices', [])
                        if unhealthy:
                            log_widget.write(f"  [{color}]Problem Indices:[/]")
                            for idx in unhealthy:
                                idx_name = idx.get('index', 'unknown')
                                idx_health = idx.get('health', 'unknown')
                                h_color = 'yellow' if idx_health == 'yellow' else 'red'
                                log_widget.write(f"    [{h_color}]{idx_name}[/]")
                    log_widget.write("")

                # 인덱스 정보
                log_widget.write("[yellow]Indices:[/]")
                log_widget.write(f"  Total: {status.get('all_indices_count', 0)}")
                log_widget.write(f"  Session: {status.get('session_count', 0)}")

                # 세션 인덱스 목록 - 종류별 최신 인덱스만
                session_indices = status.get('session_indices', [])
                if session_indices:
                    log_widget.write("")
                    log_widget.write("[yellow]Session Indices (latest per type):[/]")
                    log_widget.write(f"{'Health':<8} {'Index':<40} {'Docs':<12} {'Size':<10}")
                    log_widget.write("─" * 72)
                    seen_groups = set()
                    for idx in session_indices:
                        index_name = idx.get('index', 'N/A')
                        group = re.sub(r'-\d{4,8}$', '', index_name)
                        if group in seen_groups:
                            continue
                        seen_groups.add(group)
                        health_val = idx.get('health', 'N/A')
                        docs = idx.get('docs.count', '0') or '0'
                        size = idx.get('store.size', '0b') or '0b'
                        color = {'green': 'green', 'yellow': 'yellow', 'red': 'red'}.get(health_val, 'white')
                        log_widget.write(
                            f"[{color}]{health_val:<8}[/] {index_name[:38]:<40} {docs:<12} {size:<10}"
                        )
            else:
                log_widget.write("[red]○ Elasticsearch is not running[/]")
                log_widget.write(f"[red]Error: {status.get('error', 'Unknown')}[/]")
        except Exception as e:
            self.log.error(f"ES render error: {e}")
    
    def _refresh_current_log(self) -> None:
        """현재 로그를 새로고침합니다."""
        if self._current_log == "inspection_summary":
            self._show_inspection_summary()
        elif self._current_log == "kafka":
            self._show_kafka_status()
        elif self._current_log == "elasticsearch":
            self._show_elasticsearch_status()
        elif self._current_log:
            # 일반 로그 파일 새로고침
            for label, source_id in self.LOG_SOURCES:
                if source_id == self._current_log:
                    self._show_log_content(source_id, label.strip())
                    break
    
    def _show_error(self, error: str) -> None:
        """에러 메시지를 표시합니다."""
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.write(f"[red]Error: {error}[/]")
        except Exception:
            pass
    
    # ═══════════════════════════════════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════════════════════════════════
    
    def action_go_back(self) -> None:
        """ESC: 로그 선택 상태 → 메뉴 복귀, 미선택 상태 → 이전 화면."""
        if self._current_log is not None:
            self._current_log = None
            self._show_welcome_message()
            try:
                self.query_one("Sidebar ListView", ListView).focus()
            except Exception:
                pass
        else:
            self.app.pop_screen()
    
    def action_refresh(self) -> None:
        """F5: 로그를 새로고침합니다."""
        self._refresh_current_log()
        self.app.notify("Log refreshed")

    # ═══════════════════════════════════════════════════════════════════════
    # Inspection Summary
    # ═══════════════════════════════════════════════════════════════════════

    def _show_inspection_summary(self) -> None:
        """점검 항목 종합 요약 화면을 표시합니다."""
        from datetime import datetime
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.clear()
            log_widget.write("[bold cyan]═══ Inspection Summary ═══[/]")
            log_widget.write(f"[bright_black]Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/]")
            log_widget.write("")
            log_widget.write("[yellow]⟳  Collecting data... (may take a few seconds)[/]")
            log_widget.write("[bright_black]  MNX Capture / Elasticsearch / DPI / Kafka /[/]")
            log_widget.write("[bright_black]  dir_cache / CPU·Memory / Storage / Network /[/]")
            log_widget.write("[bright_black]  Disk SMART / System Logs[/]")

            self._current_log = "inspection_summary"

            def _run_checks() -> None:
                results = self._collect_inspection_data()
                self.app.call_from_thread(self._display_inspection_results, results)

            thread = threading.Thread(target=_run_checks, daemon=True)
            thread.start()

            if hasattr(self, '_refresh_handle') and self._refresh_handle:
                self._refresh_handle.stop()
            self._refresh_handle = self.set_interval(60.0, self._show_inspection_summary)

        except Exception as e:
            self.log.error(f"Inspection summary error: {e}")
            self._show_error(str(e))

    def _collect_inspection_data(self) -> list:
        """모든 점검 항목 데이터를 수집합니다. (백그라운드 스레드에서 실행)"""
        checks = [
            ("MNX Capture",   "Capture Log Errors", self._check_capture_errors),
            ("MNX Capture",   "Drop Count",          self._check_capture_drops),
            ("Elasticsearch", "Index Health",         self._check_elasticsearch_indices),
            ("MNX DPI",       "DPI Queue",            self._check_dpi_queue),
            ("Kafka",         "Consumer LAG",         self._check_kafka_lag),
            ("dir_cache",     "Backlog",              self._check_dir_cache),
            ("CPU/Memory",    "Usage",                self._check_cpu_memory),
            ("Storage",       "Filesystem",           self._check_storage),
            ("Network",       "RX/TX Drops",          self._check_network_drops),
            ("Hardware",      "Disk SMART",           self._check_disk_health),
            ("System Logs",   "Critical Errors",      self._check_system_critical),
        ]

        results = []
        for category, check_item, check_fn in checks:
            try:
                result = check_fn()
            except Exception as e:
                result = {'level': 'warn', 'detail': f'Check failed: {str(e)[:25]}'}
            results.append({
                'category': category,
                'check_item': check_item,
                'result': result,
            })
        return results

    def _display_inspection_results(self, results: list) -> None:
        """점검 결과를 UI에 표시합니다. (메인 스레드에서 호출)"""
        from datetime import datetime
        try:
            log_widget = self.query_one("#log-content", RichLog)
            log_widget.clear()

            log_widget.write("[bold cyan]═══ Inspection Summary ═══[/]")
            log_widget.write(f"[bright_black]Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/]")
            log_widget.write("")

            hdr = f"{'STATUS':<9} {'CATEGORY':<15} {'CHECK ITEM':<22} DETAIL"
            log_widget.write(f"[bold yellow]{hdr}[/]")
            log_widget.write("[cyan]" + "─" * 68 + "[/]")

            errors = 0
            warns = 0
            for item in results:
                self._write_check_row(
                    log_widget,
                    item['category'],
                    item['check_item'],
                    item['result'],
                )
                level = item['result'].get('level', 'ok')
                if level == 'error':
                    errors += 1
                elif level == 'warn':
                    warns += 1

            log_widget.write("[cyan]" + "─" * 68 + "[/]")
            if errors > 0:
                log_widget.write(
                    f"[bold red]Overall: ✗ CRITICAL  "
                    f"({errors} critical, {warns} warning(s))[/]"
                )
            elif warns > 0:
                log_widget.write(
                    f"[bold yellow]Overall: ⚠ WARNING  "
                    f"({warns} item(s) need attention)[/]"
                )
            else:
                log_widget.write(
                    f"[bold green]Overall: ✓ OK  "
                    f"All {len(results)} checks passed[/]"
                )

            log_widget.write("")
            log_widget.write("[bright_black]Auto-refresh: 60s  │  F5: Manual refresh[/]")

        except Exception as e:
            self.log.error(f"Display inspection results error: {e}")

    def _write_check_row(
        self, log_widget, category: str, check_item: str, result: dict
    ) -> None:
        """점검 결과 행을 RichLog에 출력합니다."""
        level = result.get('level', 'ok')
        detail = result.get('detail', '')

        if level == 'error':
            status_col = "[bold red]✗ CRIT  [/]"
            detail_color = "red"
        elif level == 'warn':
            status_col = "[bold yellow]⚠ WARN  [/]"
            detail_color = "yellow"
        else:
            status_col = "[bold green]✓ OK    [/]"
            detail_color = "green"

        cat_str = category[:15].ljust(15)
        item_str = check_item[:22].ljust(22)

        log_widget.write(
            f"{status_col} [white]{cat_str}[/] {item_str} [{detail_color}]{detail}[/]"
        )

    # ─── Individual Check Methods ────────────────────────────────────────

    def _check_capture_errors(self) -> dict:
        """MNX Capture 로그 ERROR 여부 확인."""
        try:
            log_file = None
            if self.app.log_viewer:
                log_file = self.app.log_viewer.get_latest_log_file("mnxcapture")
            if not log_file:
                return {'level': 'warn', 'detail': 'Log file not found'}

            result = subprocess.run(
                ['tail', '-n', '200', log_file],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                errors = [l for l in result.stdout.split('\n') if 'ERROR' in l.upper()]
                if errors:
                    return {'level': 'error', 'detail': f'{len(errors)} ERROR(s) in last 200 lines'}
                return {'level': 'ok', 'detail': 'No ERROR in last 200 lines'}
            return {'level': 'warn', 'detail': 'Cannot read log file'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_capture_drops(self) -> dict:
        """MNX Capture Drop Count 확인."""
        try:
            log_file = None
            if self.app.log_viewer:
                log_file = self.app.log_viewer.get_latest_log_file("mnxcapture")
            if not log_file:
                return {'level': 'warn', 'detail': 'Log file not found'}

            result = subprocess.run(
                ['grep', '-i', 'drop', log_file],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                nonzero = []
                for line in result.stdout.strip().split('\n'):
                    m = re.search(r'drop[=: ]+(\d+)', line, re.IGNORECASE)
                    if m and int(m.group(1)) > 0:
                        nonzero.append(m.group(1))
                if nonzero:
                    return {'level': 'warn', 'detail': f'{len(nonzero)} drop line(s) with count>0'}
                return {'level': 'ok', 'detail': 'Drop count = 0'}
            return {'level': 'ok', 'detail': 'No drop entries found'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_elasticsearch_indices(self) -> dict:
        """Elasticsearch 인덱스 상태 (yellow/red 여부) 확인."""
        try:
            if not self.app.es_monitor:
                return {'level': 'warn', 'detail': 'ES monitor not available'}
            if not self.app.es_monitor.is_running():
                return {'level': 'error', 'detail': 'Elasticsearch not running'}

            health = self.app.es_monitor.get_cluster_health()
            if health:
                status = health.get('status', 'unknown').lower()
                if status == 'red':
                    unassigned = health.get('unassigned_shards', 0)
                    return {'level': 'error', 'detail': f'Cluster RED, unassigned: {unassigned}'}
                elif status == 'yellow':
                    unhealthy = self.app.es_monitor.get_unhealthy_indices()
                    return {'level': 'warn', 'detail': f'Cluster YELLOW ({len(unhealthy)} indices)'}
                nodes = health.get('number_of_nodes', 0)
                return {'level': 'ok', 'detail': f'Cluster GREEN, nodes: {nodes}'}
            return {'level': 'warn', 'detail': 'Health check failed'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_dpi_queue(self) -> dict:
        """MNX DPI Queue 상태 확인 (q=현재/최대)."""
        try:
            log_file = None
            if self.app.log_viewer:
                log_file = self.app.log_viewer.get_latest_log_file("mnxdpi")
            if not log_file:
                return {'level': 'warn', 'detail': 'DPI log not found'}

            result = subprocess.run(
                ['grep', '-i', 'stat', log_file],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in reversed(result.stdout.strip().split('\n')):
                    m = re.search(r'q=(\d+)/(\d+)', line)
                    if m:
                        current = int(m.group(1))
                        max_q = int(m.group(2))
                        pct = (current / max_q * 100) if max_q > 0 else 0
                        if pct >= 90:
                            return {'level': 'error', 'detail': f'q={current}/{max_q} ({pct:.0f}% full)'}
                        elif pct >= 70:
                            return {'level': 'warn', 'detail': f'q={current}/{max_q} ({pct:.0f}% full)'}
                        return {'level': 'ok', 'detail': f'q={current}/{max_q}'}
                return {'level': 'ok', 'detail': 'Stat found (no q= pattern)'}
            return {'level': 'warn', 'detail': 'No stat lines found'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_kafka_lag(self) -> dict:
        """Kafka Consumer LAG (Offset 지연) 확인."""
        try:
            if not self.app.kafka_monitor:
                return {'level': 'warn', 'detail': 'Kafka monitor not available'}

            status = self.app.kafka_monitor.get_kafka_status()
            if not status.get('is_running'):
                return {'level': 'error', 'detail': 'Kafka service not running'}

            raw_data = status.get('raw_data', [])
            if not raw_data:
                return {'level': 'ok', 'detail': 'No consumer group data'}

            total_lag = 0
            max_lag = 0
            for item in raw_data:
                try:
                    lag_val = item.get('lag', '0')
                    lag = int(lag_val) if lag_val not in ('-', '', None) else 0
                    total_lag += lag
                    max_lag = max(max_lag, lag)
                except (ValueError, TypeError):
                    pass

            if max_lag > 10000:
                return {'level': 'error', 'detail': f'Total: {total_lag:,} (max: {max_lag:,})'}
            elif max_lag > 1000:
                return {'level': 'warn', 'detail': f'Total: {total_lag:,} (max: {max_lag:,})'}
            return {'level': 'ok', 'detail': f'Total LAG: {total_lag:,}'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_dir_cache(self) -> dict:
        """dir_cache Backlog (*.dir 파일 증가 여부) 확인."""
        try:
            if not os.path.isdir('/dir_cache'):
                return {'level': 'ok', 'detail': '/dir_cache not mounted'}

            result = subprocess.run(
                ['find', '/dir_cache', '-name', '*.dir', '-mtime', '+1'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                files = [f for f in result.stdout.strip().split('\n') if f.strip()]
                count = len(files)
                if count > 100:
                    return {'level': 'error', 'detail': f'{count} stale .dir file(s)'}
                elif count > 10:
                    return {'level': 'warn', 'detail': f'{count} stale .dir file(s)'}
                return {'level': 'ok', 'detail': f'{count} stale .dir file(s)'}
            return {'level': 'warn', 'detail': 'find command failed'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_cpu_memory(self) -> dict:
        """CPU/Memory 사용률 확인. (/proc 직접 읽기)"""
        import time
        try:
            # CPU: /proc/stat 0.5초 간격으로 2회 측정
            def _read_cpu():
                with open('/proc/stat', 'r') as f:
                    parts = f.readline().split()
                vals = [int(x) for x in parts[1:8]]
                return sum(vals), vals[3] + vals[4]  # total, idle+iowait

            t1, i1 = _read_cpu()
            time.sleep(0.5)
            t2, i2 = _read_cpu()

            dt = t2 - t1
            cpu_pct = ((dt - (i2 - i1)) / dt * 100) if dt > 0 else 0.0

            # Memory: /proc/meminfo
            mem_total = mem_available = 0
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        mem_total = int(line.split()[1])
                    elif line.startswith('MemAvailable:'):
                        mem_available = int(line.split()[1])
                    if mem_total and mem_available:
                        break

            mem_pct = ((mem_total - mem_available) / mem_total * 100) if mem_total > 0 else 0.0

            detail = f"CPU:{cpu_pct:.1f}% MEM:{mem_pct:.1f}%"
            if cpu_pct >= 90 or mem_pct >= 90:
                return {'level': 'error', 'detail': detail}
            elif cpu_pct >= 75 or mem_pct >= 80:
                return {'level': 'warn', 'detail': detail}
            return {'level': 'ok', 'detail': detail}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_storage(self) -> dict:
        """Filesystem 사용률 확인."""
        try:
            result = subprocess.run(
                ['df', '--output=target,pcent', '-x', 'tmpfs', '-x', 'devtmpfs'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]
                critical = []
                warns = []
                for line in lines:
                    parts = line.split()
                    if len(parts) == 2:
                        mount = parts[0]
                        pct_str = parts[1].rstrip('%')
                        try:
                            pct = int(pct_str)
                            if pct >= 90:
                                critical.append(f"{mount}:{pct}%")
                            elif pct >= 80:
                                warns.append(f"{mount}:{pct}%")
                        except ValueError:
                            pass
                if critical:
                    return {'level': 'error', 'detail': ', '.join(critical[:3])}
                elif warns:
                    return {'level': 'warn', 'detail': ', '.join(warns[:3])}
                return {'level': 'ok', 'detail': 'All filesystems OK'}
            return {'level': 'warn', 'detail': 'df command failed'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_network_drops(self) -> dict:
        """Network RX/TX Drop — 직전 측정 대비 delta로 현재 발생량 판단."""
        try:
            with open('/proc/net/dev', 'r') as f:
                lines = f.readlines()

            current = {}
            for line in lines[2:]:
                parts = line.split()
                if len(parts) >= 13:
                    if_name = parts[0].rstrip(':')
                    if if_name == 'lo':
                        continue
                    try:
                        current[if_name] = (int(parts[4]), int(parts[12]))
                    except (ValueError, IndexError):
                        pass

            prev = self._prev_net_drops
            self._prev_net_drops = current

            if prev is None:
                return {'level': 'ok', 'detail': 'Initializing...'}

            rx_delta = 0
            tx_delta = 0
            for if_name, (rx, tx) in current.items():
                if if_name in prev:
                    rx_delta += max(0, rx - prev[if_name][0])
                    tx_delta += max(0, tx - prev[if_name][1])

            total_delta = rx_delta + tx_delta
            detail = f"RX:{rx_delta:,} TX:{tx_delta:,}"
            if total_delta > 1000:
                return {'level': 'error', 'detail': detail}
            elif total_delta > 100:
                return {'level': 'warn', 'detail': detail}
            return {'level': 'ok', 'detail': detail}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_disk_health(self) -> dict:
        """Disk SMART Health 확인."""
        try:
            result = subprocess.run(
                ['lsblk', '-d', '-n', '-o', 'NAME,TYPE'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return {'level': 'warn', 'detail': 'Cannot list block devices'}

            disks = []
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 2 and parts[1] == 'disk':
                    disks.append(parts[0])

            if not disks:
                return {'level': 'warn', 'detail': 'No disks found'}

            failed = []
            for disk in disks[:6]:
                try:
                    r = subprocess.run(
                        ['sudo', 'smartctl', '-H', f'/dev/{disk}'],
                        capture_output=True, text=True, timeout=8,
                    )
                    combined = r.stdout + r.stderr
                    if 'FAILED' in combined:
                        failed.append(disk)
                except FileNotFoundError:
                    return {'level': 'warn', 'detail': 'smartctl not installed'}
                except Exception:
                    pass

            if failed:
                return {'level': 'error', 'detail': f'FAILED: {", ".join(failed)}'}
            return {'level': 'ok', 'detail': f'{len(disks)} disk(s) healthy'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}

    def _check_system_critical(self) -> dict:
        """System Logs Critical Error 확인."""
        try:
            log_candidates = ['/var/log/syslog', '/var/log/messages']
            log_file = next((f for f in log_candidates if os.path.exists(f)), None)
            if not log_file:
                return {'level': 'warn', 'detail': 'System log not found'}

            result = subprocess.run(
                ['tail', '-n', '200', log_file],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                crit_kws = ['CRIT', 'EMERG', 'ALERT', 'panic', 'Oops']
                crit_lines = [
                    l for l in result.stdout.split('\n')
                    if any(kw in l for kw in crit_kws)
                ]
                if crit_lines:
                    return {'level': 'error', 'detail': f'{len(crit_lines)} critical entry(ies)'}
                return {'level': 'ok', 'detail': 'No critical errors in last 200 lines'}
            return {'level': 'warn', 'detail': 'Cannot read system log'}
        except Exception as e:
            return {'level': 'warn', 'detail': str(e)[:35]}