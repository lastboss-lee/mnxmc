#!/usr/bin/env python3
"""
MNXMC Design System — App Shell & BaseScreen

모든 화면이 공유하는 4구획 골격(Header / Sidebar / Content / Footer)을 정의한다.
화면은 BaseScreen 을 상속하고 사이드바 항목·푸터 키·본문만 선언하면
Enterprise Appliance 수준의 일관된 레이아웃을 자동으로 얻는다.

Phase 1 에서는 이 골격을 제공만 하며, 기존 화면은 아직 이를 사용하지 않는다.
(각 화면 마이그레이션은 Phase 2 이후 별도 commit 으로 진행)

Author: MNX Team
Version: 2.2.0
"""

from __future__ import annotations

import time
from typing import Iterable, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import ListItem, ListView, Static

from app.ui import tokens
from app.ui.tokens import Color, Glyph, Space


# ═══════════════════════════════════════════════════════════════════════════════
# AppShell — CSS 타겟용 최상위 컨테이너
# ═══════════════════════════════════════════════════════════════════════════════


class AppShell(Vertical):
    """4구획 골격의 최상위 컨테이너 (theme.tcss 의 AppShell 규칙 대상)."""


# ═══════════════════════════════════════════════════════════════════════════════
# AppHeader — 항상 표시 (Hostname / User / Time / Service / Alarm / Health)
# ═══════════════════════════════════════════════════════════════════════════════


class AppHeader(Static):
    """
    공통 헤더. 어플라이언스 상단 상태 표시줄.

    표시 항목: Hostname, Current User, Current Time,
              Service Status(정상/전체), Alarm Count, Health.
    reactive 속성을 갱신하면 자동으로 다시 렌더된다.
    """

    hostname:     reactive[str] = reactive("mnx")
    user:         reactive[str] = reactive("-")
    clock:        reactive[str] = reactive("")
    svc_ok:       reactive[int] = reactive(0)
    svc_total:    reactive[int] = reactive(0)
    alarms:       reactive[int] = reactive(0)
    health:       reactive[str] = reactive("unknown")   # ok|warn|crit|unknown

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self.clock = time.strftime("%Y-%m-%d %H:%M:%S")

    def render(self) -> Text:
        # 1행: 브랜드 + 호스트명
        line1 = Text()
        line1.append("MNX ", style=f"bold {Color.PRIMARY}")
        line1.append("Appliance Management Console", style=Color.TEXT_MUTED)
        line1.append("   ")
        line1.append(f"{Glyph.V_LINE} ", style=Color.BORDER)
        line1.append(self.hostname, style=f"bold {Color.TEXT}")

        # 2행: 사용자 · 시간 · 서비스 · 알람 · 헬스
        sep = Text(f"  {Glyph.V_LINE}  ", style=Color.BORDER)
        line2 = Text()
        line2.append(f"{Glyph.ACTIVE} {self.user}", style=Color.TEXT)
        line2.append_text(sep.copy())
        line2.append(self.clock, style=Color.TEXT_MUTED)
        line2.append_text(sep.copy())

        svc_state = "ok" if self.svc_ok == self.svc_total and self.svc_total else "warn"
        svc_glyph, svc_color = tokens.STATUS_MAP[svc_state]
        line2.append(f"{svc_glyph} SVC {self.svc_ok}/{self.svc_total}", style=svc_color)
        line2.append_text(sep.copy())

        alarm_state = "crit" if self.alarms else "ok"
        a_glyph, a_color = tokens.STATUS_MAP[alarm_state]
        line2.append(f"{a_glyph} ALARM {self.alarms}", style=a_color)
        line2.append_text(sep.copy())

        h_glyph, h_color = tokens.STATUS_MAP.get(self.health, tokens.STATUS_MAP["unknown"])
        line2.append(f"{h_glyph} HEALTH", style=h_color)

        return Text.assemble(line1, "\n", line2)


# ═══════════════════════════════════════════════════════════════════════════════
# AppFooter — Function Key (항상 동일)
# ═══════════════════════════════════════════════════════════════════════════════

# (key, label) — 화면이 재정의하지 않으면 이 기본 세트를 사용한다.
DEFAULT_FOOTER_KEYS: list[tuple[str, str]] = [
    ("F1", "Help"),
    ("F3", "Default"),
    ("F5", "Refresh"),
    ("F7", "Rescan"),
    ("F8", "Network"),
    ("F10", "Exit"),
    ("ESC", "Back"),
]


class AppFooter(Static):
    """공통 푸터. 기능키를 통일된 스타일로 표시한다."""

    def __init__(self, keys: Optional[list[tuple[str, str]]] = None, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._keys = keys if keys is not None else DEFAULT_FOOTER_KEYS

    def on_mount(self) -> None:
        text = Text()
        for i, (key, label) in enumerate(self._keys):
            if i:
                text.append("  ")
            text.append(f" {key} ", style=f"bold {Color.SELECTED_FG} on {Color.PRIMARY}")
            text.append(f" {label}", style=Color.TEXT_MUTED)
        self.update(text)


# ═══════════════════════════════════════════════════════════════════════════════
# Sidebar — 항상 동일 폭 · 스타일, 스크롤 지원, 현재 선택 강조
# ═══════════════════════════════════════════════════════════════════════════════


class Sidebar(Vertical):
    """
    공통 좌측 내비게이션.

    카테고리 라벨 + 메뉴 항목 리스트. 선택 강조/스크롤은 theme.tcss 가 담당한다.

    항목 형식 (하위 호환):
        (key, label)              → 선택 가능한 일반 항목 (kind="item")
        (key, label, kind)        → kind = "item" | "header" | "separator"
                                     header/separator 는 비활성(선택 불가) 라벨.

    Args:
        bullet: True 면 일반 항목 앞에 캐럿 글리프를 붙인다.
                라벨에 자체 들여쓰기 체계가 있는 화면은 False 로 끈다.
    """

    def __init__(self, title: str, items: Iterable[tuple], bullet: bool = True,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._items: list[tuple] = list(items)
        self._bullet = bullet

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(self._title, classes="nav-category")
        list_view = ListView()
        yield list_view

    def on_mount(self) -> None:
        list_view = self.query_one(ListView)
        for entry in self._items:
            list_view.append(self._make_item(entry))

    def _make_item(self, entry: tuple) -> ListItem:
        """단일 항목 위젯 생성 (on_mount / set_items 공용)."""
        key, label = entry[0], entry[1]
        kind = entry[2] if len(entry) > 2 else "item"

        if kind == "header":
            item = ListItem(Static(label), classes="nav-header")
            item.disabled = True
        elif kind == "separator":
            item = ListItem(Static(label), classes="nav-sep")
            item.disabled = True
        else:
            prefix = f"{Glyph.ARROW} " if self._bullet else ""
            item = ListItem(Static(f"{prefix}{label}"))

        item.id = f"nav-{key}"
        return item

    def set_items(self, items: Iterable[tuple]) -> None:
        """항목 목록을 동적으로 교체한다 (런타임에 채워지는 메뉴용)."""
        self._items = list(items)
        lv = self.query_one(ListView)
        lv.clear()
        for entry in self._items:
            lv.append(self._make_item(entry))

    def update_item_label(self, key: str, markup: str) -> None:
        """특정 항목의 라벨만 제자리 갱신한다 (라이브 상태 아이콘 등)."""
        try:
            item = self.query_one(f"#nav-{key}", ListItem)
            item.query_one(Static).update(markup)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# BaseScreen — 화면 공통 골격
# ═══════════════════════════════════════════════════════════════════════════════


class BaseScreen(Screen):
    """
    모든 화면의 베이스. Header / Sidebar / Content / Footer 골격을 자동 구성한다.

    서브클래스 사용법
        class MyScreen(BaseScreen):
            SIDEBAR_TITLE = "SYSTEM"
            SIDEBAR_ITEMS = [("hw", "Hardware"), ("os", "OS")]
            FOOTER_KEYS   = None            # None 이면 기본 세트 사용
            def compose_content(self):      # 본문만 채우면 됨
                yield SectionTitle("Hardware")
                ...
            def on_nav_selected(self, item_id: str) -> None:
                ...                          # 사이드바 선택 처리

    이렇게 하면 화면마다 달랐던 2패널 CSS/레이아웃 중복이 제거되고
    모든 화면이 동일한 골격을 공유한다.
    """

    # 서브클래스가 재정의
    SIDEBAR_TITLE: str = ""
    SIDEBAR_ITEMS: list[tuple] = []
    SIDEBAR_BULLET: bool = True   # 라벨에 자체 들여쓰기가 있으면 False
    FOOTER_KEYS: Optional[list[tuple[str, str]]] = None

    def compose(self) -> ComposeResult:
        with AppShell():
            yield AppHeader()
            with Horizontal(id="shell-body"):
                yield Sidebar(self.SIDEBAR_TITLE, self.SIDEBAR_ITEMS,
                              bullet=self.SIDEBAR_BULLET)
                with Container(id="content"):
                    yield from self.compose_content()
            yield AppFooter(self.FOOTER_KEYS)

    def compose_content(self) -> ComposeResult:
        """서브클래스가 본문 위젯을 반환하도록 재정의한다."""
        return iter(())

    # ── 헤더 상태 갱신 헬퍼 ──────────────────────────────────────────────
    def update_header(self, **kwargs) -> None:
        """헤더 reactive 속성을 일괄 갱신한다 (예: update_header(hostname='mnx01'))."""
        try:
            header = self.query_one(AppHeader)
        except Exception:
            return
        for name, value in kwargs.items():
            if hasattr(header, name):
                setattr(header, name, value)

    # ── 사이드바 선택 라우팅 ─────────────────────────────────────────────
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = (event.item.id or "") if event.item else ""
        if item_id.startswith("nav-"):
            self.on_nav_selected(item_id[len("nav-"):])

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item_id = (event.item.id or "") if event.item else ""
        if item_id.startswith("nav-"):
            self.on_nav_highlighted(item_id[len("nav-"):])

    def on_nav_selected(self, item_id: str) -> None:
        """서브클래스가 사이드바 선택(Enter)을 처리하도록 재정의한다."""

    def on_nav_highlighted(self, item_id: str) -> None:
        """서브클래스가 사이드바 커서 이동을 처리하도록 재정의한다(선택)."""
