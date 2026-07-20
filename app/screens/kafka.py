"""
Kafka Monitoring Screen

Kafka Consumer Group 상태를 상세히 모니터링하는 화면입니다.

Features:
    - MNX Consumer Group 상태
    - 파티션별 오프셋/Lag 정보
    - 실시간 업데이트 (5초 간격)
    - 토픽 상세 정보
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, DataTable, ListView, ListItem, Label
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual import on
from app.widgets import CustomHeader
import threading


class KafkaScreen(Screen):
    """
    Kafka 모니터링 화면.

    MNX Consumer Group의 상태를 실시간으로 모니터링합니다.
    파티션별 오프셋, Lag, Consumer ID 등을 표시합니다.

    Attributes:
        _refresh_handle: 정보 업데이트 타이머
        _cache: 마지막 성공 데이터 (클래스 레벨 캐시 — 재진입 시 즉시 표시)

    Bindings:
        F5: 새로고침
        ESC: 뒤로가기
    """

    # 클래스 레벨 캐시: 화면을 나갔다 돌아와도 유지
    _cache: dict = {}
    
    CSS = """
    KafkaScreen {
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

    #nav-menu {
        width: 100%;
        height: auto;
        background: #0c0c0c;
        border: none;
        padding: 1 0;
    }

    #nav-menu > ListItem {
        background: #0c0c0c;
        color: white;
        height: 1;
        padding: 0 2;
    }

    #nav-menu > ListItem:hover {
        background: #5fd7d7;
        color: black;
    }

    #nav-menu:focus > ListItem.--highlight {
        background: #5fd7d7;
        color: black;
        text-style: bold;
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

    #kafka-status {
        width: 100%;
        height: auto;
        color: white;
        background: #0c0c0c;
        padding: 1 2;
    }

    #partition-table {
        width: 100%;
        height: 1fr;
        margin: 0 2;
    }
    """
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("f5", "refresh", "Refresh"),
    ]
    
    def __init__(self) -> None:
        """KafkaScreen을 초기화합니다."""
        super().__init__()
    
    def compose(self) -> ComposeResult:
        """
        Kafka 모니터링 화면 UI를 구성합니다.
        
        Yields:
            Widget: 화면 구성 요소들
        """
        yield CustomHeader()
        
        with Container(id="main-container"):
            # 좌측 메뉴
            with Vertical(id="left-panel"):
                yield Static(" Kafka Monitor ", id="menu-title")
                yield ListView(id="nav-menu")
            
            # 우측 콘텐츠
            with Vertical(id="content-panel"):
                yield Static("Kafka Monitor", id="content-title")
                cached = KafkaScreen._cache.get('status_text', "[bright_black]Loading...[/]")
                yield Static(cached, id="kafka-status")

                # 파티션 테이블
                table = DataTable(id="partition-table")
                table.add_columns(
                    "Partition", "Current Offset", "Log End", "Lag",
                    "Consumer ID", "Host"
                )
                yield table
        
        yield Footer()
    
    def on_mount(self) -> None:
        """화면이 마운트될 때 호출됩니다."""
        self.log.info("KafkaScreen mounted")

        # 좌측 네비게이션 메뉴 구성
        nav = self.query_one("#nav-menu", ListView)
        nav.append(ListItem(Label("← Back"), id="nav-back"))
        nav.append(ListItem(Label("▸ Overview"), id="nav-overview"))
        nav.append(ListItem(Label("  Consumer Groups"), id="nav-groups"))
        nav.append(ListItem(Label("  Topics"), id="nav-topics"))

        # 캐시된 테이블 rows 즉시 복원
        if KafkaScreen._cache.get('rows'):
            self._apply_rows(KafkaScreen._cache['rows'])

        # 비동기 초기 데이터 로드
        self.set_timer(0.1, self._async_refresh)

        # 5초 간격으로 업데이트
        self._refresh_handle = self.set_interval(5.0, self._async_refresh)

        # 좌측 패널에 포커스
        self.set_timer(0.1, self._focus_nav)

    def _focus_nav(self) -> None:
        """마운트 후 nav-menu에 포커스 설정."""
        try:
            self.query_one("#nav-menu", ListView).focus()
        except Exception:
            pass

    @on(ListView.Selected, "#nav-menu")
    def on_nav_selected(self, event: ListView.Selected) -> None:
        """네비게이션 메뉴 선택 처리."""
        if event.item.id == "nav-back":
            self.action_go_back()

    @on(ListView.Highlighted, "#nav-menu")
    def on_nav_highlighted(self, event: ListView.Highlighted) -> None:
        """네비게이션 하이라이트 시 content-title 업데이트."""
        if not event.item:
            return
        titles = {
            "nav-overview": "Kafka Monitor",
            "nav-groups":   "Consumer Groups",
            "nav-topics":   "Topics",
        }
        title = titles.get(event.item.id or "", "Kafka Monitor")
        try:
            self.query_one("#content-title", Static).update(title)
        except Exception:
            pass

    def on_unmount(self) -> None:
        """화면이 언마운트될 때 호출됩니다."""
        if hasattr(self, '_refresh_handle') and self._refresh_handle:
            self._refresh_handle.stop()
    
    def _async_refresh(self) -> None:
        """백그라운드 스레드에서 Kafka 데이터를 수집하고 UI를 갱신합니다."""
        self._set_updating(True)
        def _worker():
            data = self._fetch_kafka_data()
            self.app.call_from_thread(self._render_kafka_data, data)
        threading.Thread(target=_worker, daemon=True).start()

    def _set_updating(self, updating: bool) -> None:
        """fetch 중 title에 ↻ 표시."""
        try:
            title = self.query_one("#content-title", Static)
            title.update("Kafka Monitor  [bright_black]↻[/]" if updating else "Kafka Monitor")
        except Exception:
            pass

    def _fetch_kafka_data(self) -> dict:
        """백그라운드 스레드에서 Kafka 상태 수집 (블로킹 허용)."""
        try:
            if not self.app.kafka_monitor:
                return {
                    'status_text': "[red]Kafka monitor module not available[/]",
                    'rows': [],
                }

            status = self.app.kafka_monitor.get_kafka_status()

            if not status.get('is_running') and not status.get('success'):
                error = status.get('error', '')
                not_running = any(k in error.lower() for k in ('connect', 'timeout', 'refused', 'not running'))
                if not_running or not error:
                    return {
                        'status_text': """[bold cyan]═══ Kafka Monitor ═══[/]

[red]✗ Kafka service is not running[/]

[white]Possible issues:[/]
  • Kafka service not started
  • localhost:9092 not reachable
  • Zookeeper not running

[yellow]Check service status:[/]
  systemctl status kafka
  systemctl status zookeeper
""",
                        'rows': [],
                    }
            if not status.get('success'):
                error = status.get('error', 'Unknown error')
                return {
                    'status_text': f"""[bold cyan]═══ Kafka Monitor ═══[/]

[green]✓ Kafka service is running[/]

[yellow]Warning:[/] {error}

[white]The service is running but cannot retrieve consumer group data.[/]
""",
                    'rows': [],
                }

            raw_data  = status.get('raw_data', [])
            timestamp = status.get('timestamp', 'N/A')
            total_partitions = len(raw_data)
            total_lag = sum(
                int(d.get('lag', 0))
                for d in raw_data if d.get('lag', '').isdigit()
            )

            status_text = f"""[bold cyan]═══ Kafka Monitor ═══[/]

[green]✓ Kafka service is running[/]

[yellow]MNX Consumer Group Status[/]
  [white]Last Update  :[/] {timestamp}
  [white]Partitions   :[/] {total_partitions}
  [white]Total Lag    :[/] {total_lag:,}

[cyan]────────────────────────────────────────[/]
[white]Partition details shown in table below[/]
"""

            rows = []
            for item in raw_data:
                partition      = item.get('partition', 'N/A')
                current_offset = item.get('current_offset', 'N/A')
                log_end        = item.get('log_end_offset', 'N/A')
                lag            = item.get('lag', 'N/A')
                consumer_id    = item.get('consumer_id', '-')
                host           = item.get('host', '-')

                if lag.isdigit():
                    lag_num = int(lag)
                    if lag_num > 1000:
                        lag = f"[red]{lag}[/]"
                    elif lag_num > 100:
                        lag = f"[yellow]{lag}[/]"
                    else:
                        lag = f"[green]{lag}[/]"

                rows.append((
                    partition, current_offset, log_end, lag,
                    consumer_id[:20] if consumer_id != '-' else '-',
                    host,
                ))

            return {'status_text': status_text, 'rows': rows}

        except Exception as e:
            self.log.error(f"Kafka fetch error: {e}")
            return {'status_text': f"[red]Error: {e}[/]", 'rows': []}

    def _render_kafka_data(self, data: dict) -> None:
        """메인 스레드에서 UI 업데이트 — 기존 화면 유지, 값만 교체."""
        self._set_updating(False)

        # 성공 데이터일 때만 캐시 갱신
        if data.get('rows') is not None and data.get('status_text'):
            KafkaScreen._cache = {
                'status_text': data['status_text'],
                'rows': data['rows'],
            }

        try:
            self.query_one("#kafka-status", Static).update(data['status_text'])
        except Exception:
            pass

        rows = data.get('rows', [])
        self._apply_rows(rows)

    def _apply_rows(self, rows: list) -> None:
        """테이블 rows 적용 — row 수 동일하면 in-place 업데이트, 다르면 clear 후 재삽입."""
        try:
            table = self.query_one("#partition-table", DataTable)
            existing = table.row_count

            if existing == len(rows):
                # row 수 동일 → 셀 값만 교체 (깜빡임 없음)
                for r_idx, row in enumerate(rows):
                    for c_idx, val in enumerate(row):
                        table.update_cell_at((r_idx, c_idx), val)
            else:
                # row 수 다름 → clear 후 재삽입
                table.clear()
                for row in rows:
                    table.add_row(*row)
        except Exception as e:
            self.log.error(f"Kafka table update error: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════════════════════════════════════

    def action_go_back(self) -> None:
        """ESC: 대시보드로 돌아갑니다."""
        self.app.pop_screen()

    def action_refresh(self) -> None:
        """F5: 정보를 새로고침합니다."""
        self._async_refresh()
        self.app.notify("Kafka status refreshed")
