#!/usr/bin/env python3
"""
MNXMC Design System — Common Components

모든 화면이 재사용하는 공통 위젯. 화면별 중복 위젯/인라인 스타일을 제거하고
여기 정의된 컴포넌트로 통일한다. 스타일은 app/ui/theme.tcss 에서 관리한다.

제공 컴포넌트
    SectionTitle   — 섹션 제목
    Card           — 카드 골격 (StatusCard/MetricCard 의 베이스)
    StatusCard     — 상태 카드 (제목 + 상태 배지)
    MetricCard     — 지표 카드 (제목 + 값 + 선택적 미터)
    PropertyGrid   — key-value 속성 그리드
    MeterBar       — 사용률 미터 바
    MessageBox     — 정보/경고/오류/성공 박스 (info_box/... 팩토리)

Author: MNX Team
Version: 2.3.2
"""

from __future__ import annotations

from typing import Iterable, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from app.ui import tokens
from app.ui.tokens import Color, Glyph


# ═══════════════════════════════════════════════════════════════════════════════
# SectionTitle
# ═══════════════════════════════════════════════════════════════════════════════


class SectionTitle(Static):
    """섹션 제목. 앞에 캐럿 글리프를 붙여 시각적 계층을 통일한다."""

    def __init__(self, title: str, **kwargs) -> None:
        super().__init__(f"{Glyph.CARET} {title}", **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# Card / StatusCard / MetricCard
# ═══════════════════════════════════════════════════════════════════════════════


class Card(Vertical):
    """카드 골격. 제목과 본문을 감싸는 공통 컨테이너."""

    def __init__(self, title: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(self._title, classes="card-title")


class StatusCard(Card):
    """
    상태 카드 — 제목 + 상태 배지(글리프+색상).

    Example:
        StatusCard("Capture Engine", state="ok", detail="active (3d)")
    """

    def __init__(self, title: str, state: str = "unknown",
                 detail: str = "", **kwargs) -> None:
        super().__init__(title, **kwargs)
        self._state = state
        self._detail = detail

    def compose(self) -> ComposeResult:
        yield from super().compose()
        badge = tokens.status_badge(self._state, self._detail)
        yield Static(badge, classes="card-value")


class MetricCard(Card):
    """
    지표 카드 — 제목 + 값 + (선택) 사용률 미터.

    Example:
        MetricCard("CPU", value="42%", percent=42.0)
    """

    def __init__(self, title: str, value: str = "",
                 percent: Optional[float] = None, **kwargs) -> None:
        super().__init__(title, **kwargs)
        self._value = value
        self._percent = percent

    def compose(self) -> ComposeResult:
        yield from super().compose()
        if self._value:
            yield Static(self._value, classes="card-value")
        if self._percent is not None:
            yield MeterBar(self._percent)


# ═══════════════════════════════════════════════════════════════════════════════
# PropertyGrid
# ═══════════════════════════════════════════════════════════════════════════════


class PropertyGrid(Static):
    """
    key-value 속성 그리드. Config/System 화면의 속성 나열을 통일한다.

    라벨은 muted, 값은 본문색으로 정렬 렌더링한다.
    """

    def __init__(self, rows: Optional[Iterable[tuple[str, str]]] = None,
                 label_width: int = 22, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._rows: list[tuple[str, str]] = list(rows or [])
        self._label_width = label_width

    def set_rows(self, rows: Iterable[tuple[str, str]]) -> None:
        """속성 행을 교체하고 다시 렌더한다."""
        self._rows = list(rows)
        self._render_rows()

    def on_mount(self) -> None:
        self._render_rows()

    def _render_rows(self) -> None:
        text = Text()
        for key, value in self._rows:
            text.append(f"{key:<{self._label_width}}", style=Color.TEXT_MUTED)
            text.append(f"{value}\n", style=Color.TEXT)
        self.update(text)


# ═══════════════════════════════════════════════════════════════════════════════
# MeterBar
# ═══════════════════════════════════════════════════════════════════════════════


class MeterBar(Static):
    """
    사용률 미터 바. 임계값에 따라 색상이 자동 변경된다(정상/경고/위험).

    percent 를 갱신하면 자동으로 다시 렌더된다.
    """

    percent: reactive[float] = reactive(0.0)

    def __init__(self, percent: float = 0.0, width: int = 20,
                 show_value: bool = True, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._width = width
        self._show_value = show_value
        self.percent = percent

    def watch_percent(self, value: float) -> None:
        bar = tokens.meter(value, width=self._width)
        if self._show_value:
            bar += f" [{Color.TEXT}]{value:5.1f}%[/]"
        self.update(bar)


# ═══════════════════════════════════════════════════════════════════════════════
# MessageBox (Info / Warning / Error / Success)
# ═══════════════════════════════════════════════════════════════════════════════

_LEVEL_GLYPH = {
    "info":    Glyph.INFO,
    "warning": Glyph.WARN,
    "error":   Glyph.CRIT,
    "success": Glyph.OK,
}


class MessageBox(Static):
    """
    정보/경고/오류/성공 박스. level 에 따라 테두리색과 글리프가 결정된다.

    개별 박스 클래스 대신 하나의 컴포넌트로 통합한다.
    """

    def __init__(self, message: str, level: str = "info", **kwargs) -> None:
        glyph = _LEVEL_GLYPH.get(level, Glyph.INFO)
        super().__init__(f"{glyph} {message}", **kwargs)
        self.add_class(f"-{level}")


def info_box(message: str, **kwargs) -> MessageBox:
    """정보 박스."""
    return MessageBox(message, level="info", **kwargs)


def warning_box(message: str, **kwargs) -> MessageBox:
    """경고 박스."""
    return MessageBox(message, level="warning", **kwargs)


def error_box(message: str, **kwargs) -> MessageBox:
    """오류 박스."""
    return MessageBox(message, level="error", **kwargs)


def success_box(message: str, **kwargs) -> MessageBox:
    """성공 박스."""
    return MessageBox(message, level="success", **kwargs)


def fmt_bytes(value: float, sep: str = " ") -> str:
    """바이트를 사람이 읽는 단위로 — 화면 전체 공용 단일 소스.

    sep: 숫자와 단위 사이 구분자. Performance 화면은 열 정렬 폭 때문에 "" 를 쓴다.
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0:
            return f"{value:.1f}{sep}{unit}"
        value /= 1024.0
    return f"{value:.1f}{sep}PB"
