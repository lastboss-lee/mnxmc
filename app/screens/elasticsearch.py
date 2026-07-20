"""
Elasticsearch Monitoring Screen

Elasticsearch 클러스터 상태를 상세히 모니터링하는 화면입니다.

Features:
    - 클러스터 헬스 상태 (YELLOW/RED 시 문제 인덱스 표시)
    - 노드/샤드 정보
    - Session Indices / All Indices 뷰 전환
    - 최신 인덱스 우선 표시 (내림차순)
    - 실시간 업데이트 (5초 간격)
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static, DataTable, ListView, ListItem, Label
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual import on
from app.widgets import CustomHeader
import threading


class ElasticsearchScreen(Screen):
    """Elasticsearch 모니터링 화면."""

    CSS = """
    ElasticsearchScreen {
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

    #es-status {
        width: 100%;
        height: auto;
        color: white;
        background: #0c0c0c;
        padding: 1 2;
    }

    #index-table {
        width: 100%;
        height: 1fr;
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("f5", "refresh", "Refresh"),
    ]

    # 뷰 정의: (nav_id, 표시명, 테이블 제목)
    _VIEWS = {
        "nav-health":   "Cluster Health",
        "nav-sessions": "Session Indices",
        "nav-all":      "All Indices",
    }

    def __init__(self) -> None:
        super().__init__()
        self._current_view = "nav-health"

    def compose(self) -> ComposeResult:
        yield CustomHeader()

        with Container(id="main-container"):
            with Vertical(id="left-panel"):
                yield Static(" Elasticsearch ", id="menu-title")
                yield ListView(id="nav-menu")

            with Vertical(id="content-panel"):
                yield Static("Cluster Health", id="content-title")
                yield Static("", id="es-status")
                table = DataTable(id="index-table")
                table.add_columns("Health", "Status", "Index Name", "Docs", "Size")
                yield table

        yield Footer()

    def on_mount(self) -> None:
        self.log.info("ElasticsearchScreen mounted")

        nav = self.query_one("#nav-menu", ListView)
        nav.append(ListItem(Label("  ← Back"),          id="nav-back"))
        nav.append(ListItem(Label("▸ Cluster Health"),   id="nav-health"))
        nav.append(ListItem(Label("  Session Indices"),  id="nav-sessions"))
        nav.append(ListItem(Label("  All Indices"),      id="nav-all"))

        self.set_timer(0.3, self._async_refresh)
        self._refresh_handle = self.set_interval(5.0, self._async_refresh)
        self.set_timer(0.1, self._focus_nav)

    def on_unmount(self) -> None:
        if hasattr(self, '_refresh_handle') and self._refresh_handle:
            self._refresh_handle.stop()

    def _focus_nav(self) -> None:
        try:
            menu = self.query_one("#nav-menu", ListView)
            menu.focus()
            menu.index = 1  # Cluster Health 기본 선택
        except Exception:
            pass

    # ── 네비게이션 ──────────────────────────────────────────────────────────

    @on(ListView.Selected, "#nav-menu")
    def on_nav_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id == "nav-back":
            self.action_go_back()
            return
        if item_id in self._VIEWS:
            self._current_view = item_id
            self._update_nav_labels(highlighted_id=item_id)
            self._async_refresh()

    @on(ListView.Highlighted, "#nav-menu")
    def on_nav_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item:
            self._update_nav_labels(highlighted_id=event.item.id or "")

    def _update_nav_labels(self, highlighted_id: str = "") -> None:
        """네비게이션 레이블 상태 업데이트."""
        nav_labels = {
            "nav-back":     "← Back",
            "nav-health":   "Cluster Health",
            "nav-sessions": "Session Indices",
            "nav-all":      "All Indices",
        }
        try:
            menu = self.query_one("#nav-menu", ListView)
            for item_id, text in nav_labels.items():
                try:
                    item  = menu.query_one(f"#{item_id}", ListItem)
                    label = item.query_one(Label)
                    if item_id == highlighted_id:
                        label.update(f"[reverse] ▸ {text} [/]")
                    elif item_id == self._current_view:
                        label.update(f"[cyan]▸ {text}[/]")
                    elif item_id == "nav-back":
                        label.update(f"  {text}")
                    else:
                        label.update(f"  {text}")
                except Exception:
                    pass
        except Exception:
            pass

    # ── 데이터 갱신 ────────────────────────────────────────────────────────

    def _async_refresh(self) -> None:
        """백그라운드 스레드에서 ES 데이터를 수집하고 UI를 갱신합니다."""
        view = self._current_view

        def _worker():
            data = self._fetch_es_data(view)
            self.app.call_from_thread(self._apply_refresh, data)

        threading.Thread(target=_worker, daemon=True).start()

    def _fetch_es_data(self, view: str) -> dict:
        """백그라운드 스레드에서 ES 상태 수집 (블로킹 허용)."""
        try:
            es_status = (
                self.app.es_monitor.get_elasticsearch_status()
                if self.app.es_monitor else {}
            )
        except Exception:
            es_status = {}

        all_indices = []
        if view == "nav-all":
            try:
                all_indices = self.app.es_monitor.get_all_indices_sorted() if self.app.es_monitor else []
            except Exception:
                all_indices = []

        return {'es_status': es_status, 'all_indices': all_indices, 'view': view}

    def _apply_refresh(self, data: dict) -> None:
        """메인 스레드에서 UI 전체 갱신."""
        es_status   = data.get('es_status', {})
        all_indices = data.get('all_indices', [])
        view        = data.get('view', self._current_view)

        # 타이틀
        title = self._VIEWS.get(self._current_view, "Elasticsearch")
        try:
            self.query_one("#content-title", Static).update(title)
        except Exception:
            pass

        # 상태 패널
        try:
            self.query_one("#es-status", Static).update(self._build_status_text(es_status))
        except Exception:
            pass

        # 테이블
        try:
            table = self.query_one("#index-table", DataTable)
            table.clear()

            if not self.app.es_monitor or not es_status.get('is_running', False):
                return

            if view == "nav-health":
                self._fill_table_unhealthy(table, es_status)
            elif view == "nav-sessions":
                self._fill_table_sessions(table, es_status)
            elif view == "nav-all":
                self._fill_table_all_data(table, all_indices)
        except Exception as e:
            self.log.error(f"Table update error: {e}")

    def _build_status_text(self, es_status: dict) -> str:
        """상태 텍스트 생성."""
        if not self.app.es_monitor:
            return "[red]Elasticsearch monitor module not available[/]"

        if not es_status.get('is_running', False):
            return """[bold cyan]═══ Elasticsearch Monitor ═══[/]

[red]✗ Elasticsearch service is not running[/]

[white]Possible issues:[/]
  • Elasticsearch service not started
  • localhost:9200 not reachable
  • Insufficient memory

[yellow]Check:[/]
  systemctl status elasticsearch-node-1 elasticsearch-node-2
"""

        health = es_status.get('cluster_health') or {}
        status = health.get('status', 'unknown').upper()
        status_color = {'GREEN': 'green', 'YELLOW': 'yellow', 'RED': 'red'}.get(status, 'white')

        session_count  = es_status.get('session_count', 0)
        all_count      = es_status.get('all_indices_count', 0)
        unassigned     = health.get('unassigned_shards', 0)

        content = f"""[bold cyan]═══ Elasticsearch Monitor ═══[/]

[green]✓ Service running[/]

[yellow]Cluster Health:[/]
  [white]Status         :[/] [{status_color}]{status}[/]
  [white]Cluster Name   :[/] {health.get('cluster_name', 'N/A')}
  [white]Nodes          :[/] {health.get('number_of_nodes', 0)} (data: {health.get('number_of_data_nodes', 0)})

[yellow]Shard Status:[/]
  [white]Active         :[/] {health.get('active_shards', 0)} (primary: {health.get('active_primary_shards', 0)})
  [white]Relocating     :[/] {health.get('relocating_shards', 0)}
  [white]Initializing   :[/] {health.get('initializing_shards', 0)}
  [white]Unassigned     :[/] [{status_color}]{unassigned}[/]

[yellow]Index Summary:[/]
  [white]Total          :[/] {all_count}
  [white]Session        :[/] {session_count}
"""

        # YELLOW/RED 시 문제 인덱스 표시
        if status in ('YELLOW', 'RED'):
            unhealthy = es_status.get('unhealthy_indices', [])
            if unhealthy:
                content += f"\n[{status_color}]⚠ Problem Indices ({len(unhealthy)}):[/]\n"
                for idx in unhealthy[:8]:
                    name      = idx.get('index', 'unknown')
                    ih        = idx.get('health', 'unknown')
                    unassign  = idx.get('unassigned.shards', '?')
                    h_color   = 'yellow' if ih == 'yellow' else 'red'
                    # 이름이 길면 줄임
                    disp_name = name if len(name) <= 38 else name[:35] + "..."
                    content += f"  [{h_color}]{ih:6}[/] {disp_name}  [bright_black](unassigned: {unassign})[/]\n"
                if len(unhealthy) > 8:
                    content += f"  [bright_black]... and {len(unhealthy) - 8} more (see table)[/]\n"
            else:
                content += f"\n[{status_color}]⚠ Cluster {status} — no index-level data available[/]\n"

        content += "\n[bright_black]F5: Refresh  ESC: Back[/]"
        return content

    # ── 테이블 갱신 ────────────────────────────────────────────────────────

    def _add_index_row(self, table: DataTable, idx: dict) -> None:
        """공통 인덱스 행 추가."""
        health     = idx.get('health', 'unknown')
        status     = idx.get('status', 'unknown')
        index_name = idx.get('index', 'unknown')
        docs       = idx.get('docs.count', '0') or '0'
        size       = idx.get('store.size', '0b') or '0b'

        health_symbol = {
            'green':  '[green]●[/]',
            'yellow': '[yellow]◐[/]',
            'red':    '[red]○[/]',
        }.get(health, '[white]?[/]')

        if len(index_name) > 42:
            index_name = index_name[:39] + "..."

        table.add_row(
            f"{health_symbol} {health}",
            status,
            index_name,
            docs,
            size,
        )

    def _fill_table_unhealthy(self, table: DataTable, es_status: dict) -> None:
        """Cluster Health 뷰: 문제 인덱스만 표시."""
        unhealthy = es_status.get('unhealthy_indices', [])
        if not unhealthy:
            table.add_row("[green]●[/] green", "open", "[bright_black]All indices are healthy[/]", "", "")
            return

        for idx in unhealthy:
            self._add_index_row(table, idx)

    def _fill_table_sessions(self, table: DataTable, es_status: dict) -> None:
        """Session Indices 뷰: session/net-stats 인덱스 (최신 순, 최대 50개)."""
        indices = es_status.get('session_indices', [])
        limit   = 50

        for idx in indices[:limit]:
            self._add_index_row(table, idx)

        if len(indices) > limit:
            table.add_row("", "", f"[bright_black]... and {len(indices) - limit} more[/]", "", "")

    def _fill_table_all_data(self, table: DataTable, indices: list) -> None:
        """All Indices 뷰: 사전 수집된 인덱스 목록 표시 (최대 100개)."""
        limit = 100
        for idx in indices[:limit]:
            self._add_index_row(table, idx)

        if len(indices) > limit:
            table.add_row("", "", f"[bright_black]... and {len(indices) - limit} more[/]", "", "")

    # ── 액션 ───────────────────────────────────────────────────────────────

    def action_go_back(self) -> None:
        """ESC: 세부 뷰 → 기본 뷰(Cluster Health) 복귀, 기본 뷰 → 이전 화면."""
        if self._current_view != "nav-health":
            self._current_view = "nav-health"
            self._update_nav_labels(highlighted_id="nav-health")
            self._async_refresh()
            try:
                self.query_one("#nav-menu", ListView).focus()
            except Exception:
                pass
        else:
            self.app.pop_screen()

    def action_refresh(self) -> None:
        self._async_refresh()
        self.app.notify("Elasticsearch status refreshed")
