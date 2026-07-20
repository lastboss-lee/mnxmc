"""
Custom Header Widget

모든 화면에서 사용하는 통일된 헤더 위젯입니다.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static
from datetime import datetime


class CustomHeader(Widget):
    """
    커스텀 헤더 위젯 (height=3, Rule 1 준수).

    줄 1: [title                              ] [HH:MM:SS]
    줄 2: [──────────────────────────────────────────────]
    줄 3: (padding / 빈 줄 — 헤더 하단 여백)
    """

    DEFAULT_CSS = """
    CustomHeader {
        width: 100%;
        height: 3;
        dock: top;
        layout: vertical;
        background: #0c0c0c;
    }

    CustomHeader > #header-row {
        width: 100%;
        height: 1;
        layout: horizontal;
        background: #0c0c0c;
    }

    CustomHeader > #header-row > #header-user {
        width: 20;
        height: 1;
        background: #0c0c0c;
        color: #5fd7d7;
        content-align: left middle;
        padding: 0 1;
    }

    CustomHeader > #header-row > #header-title {
        width: 1fr;
        height: 1;
        background: #0c0c0c;
        color: white;
        text-style: bold;
        content-align: center middle;
    }

    CustomHeader > #header-row > #header-clock {
        width: 12;
        height: 1;
        background: #0c0c0c;
        color: #5fd7d7;
        text-style: bold;
        content-align: center middle;
    }

    CustomHeader > #header-separator {
        width: 100%;
        height: 1;
        background: #5fd7d7;
        color: #0c0c0c;
    }

    CustomHeader > #header-padding {
        width: 100%;
        height: 1;
        background: #0c0c0c;
    }
    """

    def __init__(
        self,
        title: str = "MNX Appliance Management Console",
        show_clock: bool = True,
        **kwargs
    ) -> None:
        """
        Args:
            title: 헤더 중앙에 표시할 제목
            show_clock: 시계 표시 여부
        """
        super().__init__(**kwargs)
        self._title = title
        self._show_clock = show_clock
        self._clock_handle = None

    def compose(self) -> ComposeResult:
        """헤더 구성 (3줄)."""
        with Horizontal(id="header-row"):
            yield Static("", id="header-user")
            yield Static(self._title, id="header-title")
            if self._show_clock:
                yield Static(datetime.now().strftime("%H:%M:%S"), id="header-clock")
        yield Static("", id="header-separator")
        yield Static("", id="header-padding")

    def on_mount(self) -> None:
        """마운트 시 시계 업데이트 타이머 시작."""
        if self._show_clock:
            self._clock_handle = self.set_interval(1.0, self._update_clock)
        self._update_user_display()

    def _update_user_display(self) -> None:
        """인증된 사용자 이름 표시 업데이트."""
        try:
            user = getattr(self.app, 'authenticated_user', None) or ""
            widget = self.query_one("#header-user", Static)
            widget.update(f" login:{user}" if user else "")
        except Exception:
            pass

    def on_unmount(self) -> None:
        """타이머 정리."""
        if self._clock_handle is not None:
            self._clock_handle.stop()
            self._clock_handle = None

    def _update_clock(self) -> None:
        """시계 업데이트."""
        try:
            clock = self.query_one("#header-clock", Static)
            clock.update(datetime.now().strftime("%H:%M:%S"))
        except Exception:
            pass

    def set_title(self, title: str) -> None:
        """제목 변경."""
        try:
            title_widget = self.query_one("#header-title", Static)
            title_widget.update(title)
            self._title = title
        except Exception:
            pass