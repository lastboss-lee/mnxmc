#!/usr/bin/env python3
"""
MNXMC Design System — Design Tokens (Single Source of Truth)

Enterprise Network Appliance 수준의 일관된 TUI를 위한 디자인 토큰 정의.
색상 / 간격 / 글리프 / 상태 매핑을 한 곳에서 관리한다.

설계 기준
    - Terminal Friendly: 순수 ANSI/트루컬러 터미널에서 안정적으로 표시.
    - Color-Blind Friendly: 색상 단독으로 의미를 전달하지 않는다.
      상태는 항상 (색상 + 글리프) 조합으로 표현한다 (예: 정상=✔ 녹색, 위험=✖ 적색).
    - Config 기반: 화면 코드에서 색상/간격 하드코딩을 제거하고 이 토큰을 참조한다.

⚠ theme.tcss 와 짝을 이룬다.
    이 파일(Python 위젯용 Rich 마크업)과 theme.tcss(Textual CSS)의 색상 값은
    동일하게 유지해야 한다. 한쪽을 수정하면 반드시 다른 쪽도 함께 수정한다.

Author: MNX Team
Version: 2.2.0
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Color System
# ═══════════════════════════════════════════════════════════════════════════════
#
# 브랜드 기조: MNX 시그니처 시안(#00AEEF) 을 Primary 로 사용.
# 배경은 near-black(살짝 청색 편향)으로 어플라이언스 콘솔 톤을 통일한다.
# 상태색은 명도(luminance)를 서로 다르게 배치하여 색맹 사용자도 구분 가능하게 한다.


class Color:
    """디자인 시스템 색상 팔레트 (hex)."""

    # ── Surface / Structure ──────────────────────────────────────────────
    BG          = "#0b0f14"   # 최하단 배경
    SURFACE     = "#11161d"   # 카드 / 패널 표면
    SURFACE_ALT = "#161c25"   # 교차 행 / 보조 표면
    BORDER      = "#2a3440"   # 기본 테두리
    BORDER_MUTED = "#1c2530"  # 약한 구분선

    # ── Text ─────────────────────────────────────────────────────────────
    TEXT        = "#e6edf3"   # 본문
    TEXT_MUTED  = "#8b98a5"   # 보조 / 라벨
    TEXT_FAINT  = "#5a6673"   # 비활성 / disabled

    # ── Brand ────────────────────────────────────────────────────────────
    PRIMARY     = "#00aeef"   # MNX 시그니처 시안 (강조/선택)
    ACCENT      = "#33c9ff"   # 하이라이트 액센트

    # ── Semantic (상태) — 항상 글리프와 함께 사용할 것 ────────────────────
    SUCCESS     = "#3fb950"   # 정상 (✔)
    INFO        = "#58a6ff"   # 정보 (ℹ)
    WARNING     = "#d29922"   # 경고 (▲)
    CRITICAL    = "#f85149"   # 위험 (✖)
    DISABLED    = "#5a6673"   # 사용 불가 (○)

    # ── Interaction ──────────────────────────────────────────────────────
    HOVER       = "#1c2530"   # 마우스 오버 배경
    SELECTED_BG = "#00aeef"   # 선택 항목 배경 (Primary)
    SELECTED_FG = "#04141b"   # 선택 항목 전경 (어두운 텍스트)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Spacing Scale — Margin / Padding / Gap 통일
# ═══════════════════════════════════════════════════════════════════════════════
#
# TUI 셀 단위(정수). 모든 화면이 동일 스케일을 사용해 여백을 통일한다.


class Space:
    """간격 스케일 (터미널 셀 단위)."""

    NONE = 0
    XS   = 1   # 요소 내부 최소 간격
    SM   = 1   # 라벨-값 간격 등
    MD   = 2   # 카드 내부 패딩 기본
    LG   = 3   # 섹션 간 간격
    XL   = 4   # 화면 여백

    SIDEBAR_WIDTH = 26   # 사이드바 고정 폭 (항상 동일)
    HEADER_HEIGHT = 3    # 헤더 고정 높이
    FOOTER_HEIGHT = 1    # 푸터 고정 높이


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Glyphs — Box Drawing / 상태 아이콘 (ASCII 터미널 최적)
# ═══════════════════════════════════════════════════════════════════════════════


class Glyph:
    """박스 드로잉 및 상태 글리프."""

    # 상태 아이콘 (색상과 함께 사용 — 색맹 대응)
    OK       = "✔"
    WARN     = "▲"
    CRIT     = "✖"
    INFO     = "ℹ"
    UNKNOWN  = "○"
    ACTIVE   = "●"
    INACTIVE = "○"

    # 구분선 / 박스
    H_LINE   = "─"
    V_LINE   = "│"
    BULLET   = "•"
    ARROW    = "›"
    CARET    = "▸"

    # 미터/게이지 바
    BAR_FULL  = "█"
    BAR_EMPTY = "░"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Status Map — (state → 글리프 + 색상) 통일 매핑
# ═══════════════════════════════════════════════════════════════════════════════
#
# 서비스/헬스/알람 등 모든 상태 표현이 이 매핑을 단일 기준으로 사용한다.

# state 키: "ok" | "warn" | "crit" | "info" | "disabled" | "unknown"
STATUS_MAP: dict[str, tuple[str, str]] = {
    "ok":       (Glyph.OK,       Color.SUCCESS),
    "warn":     (Glyph.WARN,     Color.WARNING),
    "crit":     (Glyph.CRIT,     Color.CRITICAL),
    "info":     (Glyph.INFO,     Color.INFO),
    "disabled": (Glyph.INACTIVE, Color.DISABLED),
    "unknown":  (Glyph.UNKNOWN,  Color.TEXT_MUTED),
}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Rich 마크업 헬퍼 — 위젯이 공통 규칙으로 문자열을 조립할 때 사용
# ═══════════════════════════════════════════════════════════════════════════════


def status_badge(state: str, label: str = "") -> str:
    """
    상태 배지 Rich 마크업 문자열 반환.

    색상 + 글리프 조합으로 색맹 사용자도 구분 가능하다.

    Args:
        state: STATUS_MAP 키 ("ok"/"warn"/"crit"/"info"/"disabled"/"unknown")
        label: 배지 뒤에 붙일 텍스트 (선택)

    Returns:
        Rich 마크업 문자열 (예: "[#3fb950]✔[/] 정상")
    """
    glyph, color = STATUS_MAP.get(state, STATUS_MAP["unknown"])
    text = f"[{color}]{glyph}[/]"
    if label:
        text += f" {label}"
    return text


def panel(title: str, body: str, width: int = 60, color: str = Color.PRIMARY) -> str:
    """
    카드/패널 형태의 프레임 Rich 마크업 문자열 반환.

    상단에 제목이 박힌 테두리, 본문은 2칸 들여쓰기. 본문에 Rich 마크업이
    포함돼도 폭 계산이 어긋나지 않도록 좌우 세로선은 생략하고 상/하단만 그린다.
    모든 화면이 동일한 카드 룩을 공유하도록 한다.

    Args:
        title: 카드 제목 (평문)
        body:  본문 (여러 줄 가능, Rich 마크업 허용)
        width: 카드 폭(셀)
        color: 테두리 색

    Returns:
        Rich 마크업 문자열
    """
    inner = max(10, width - 2)
    dashes = max(0, inner - len(title) - 3)
    top = f"[{color}]╭─ {title} " + Glyph.H_LINE * dashes + "╮[/]"
    bottom = f"[{color}]╰" + Glyph.H_LINE * inner + "╯[/]"
    lines = [top]
    for ln in body.split("\n"):
        lines.append(f"  {ln}")
    lines.append(bottom)
    return "\n".join(lines)


def meter(percent: float, width: int = 20, warn: float = 70.0,
          crit: float = 90.0) -> str:
    """
    사용률 미터 바 Rich 마크업 문자열 반환.

    임계값에 따라 색상이 자동 변경된다 (정상/경고/위험).
    모든 화면이 동일한 바 문자·길이 규칙을 공유하도록 한다.

    Args:
        percent: 0~100 사용률
        width:   바 전체 셀 폭
        warn:    경고 임계값(%)
        crit:    위험 임계값(%)

    Returns:
        Rich 마크업 문자열
    """
    pct = max(0.0, min(100.0, percent))
    filled = int(round(pct / 100.0 * width))
    empty = width - filled

    if pct >= crit:
        color = Color.CRITICAL
    elif pct >= warn:
        color = Color.WARNING
    else:
        color = Color.SUCCESS

    bar = f"[{color}]{Glyph.BAR_FULL * filled}[/]"
    bar += f"[{Color.BORDER}]{Glyph.BAR_EMPTY * empty}[/]"
    return bar
