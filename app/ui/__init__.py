#!/usr/bin/env python3
"""
MNXMC Design System (app.ui)

Enterprise Network Appliance 수준의 일관된 TUI를 위한 공통 디자인 시스템.

구성
    tokens.py   — 디자인 토큰 (색상/간격/글리프/상태 매핑) 단일 소스
    theme.tcss  — Textual 스타일시트 (Shell 레이아웃 + 컴포넌트 스타일)
    widgets.py  — 공통 컴포넌트 (Card/Meter/PropertyGrid/MessageBox 등)
    screen.py   — App Shell 및 BaseScreen (Header/Sidebar/Content/Footer)

각 모듈은 명시 경로로 임포트한다 (`from app.ui.widgets import ...`).
"""
