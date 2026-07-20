#!/usr/bin/env python3
"""
MNXMC Design System (app.ui)

Enterprise Network Appliance 수준의 일관된 TUI를 위한 공통 디자인 시스템.

구성
    tokens.py   — 디자인 토큰 (색상/간격/글리프/상태 매핑) 단일 소스
    theme.tcss  — Textual 스타일시트 (Shell 레이아웃 + 컴포넌트 스타일)
    widgets.py  — 공통 컴포넌트 (Card/Meter/PropertyGrid/MessageBox 등)
    screen.py   — App Shell 및 BaseScreen (Header/Sidebar/Content/Footer)

Phase 1(기반)에서는 제공만 하며 기존 화면 동작에 영향을 주지 않는다.
화면별 적용은 Phase 2 이후 각각 별도 commit 으로 진행한다.
"""

__all__ = ["tokens"]
