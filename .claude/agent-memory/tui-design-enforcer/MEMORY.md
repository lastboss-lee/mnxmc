# TUI Design Enforcer - Agent Memory

## Project: MNXMC TUI Application
- Framework: Textual (Python)
- Path: /mnt/d/mnxmc-dev/202602191000/ (개발), /mnxmc (런타임)
- CSS: app/styles/theme.tcss
- Version: 2.1.0 (2026-04-21)

## ✅ v2.1.0 (2026-04-21) UI 변경
- ✅ Service R/S/X/A/Z 액션 다이얼로그가 진행 중 메시지("starting...", "(N/M) ...stopping...")
     를 표시하도록 변경. 작업 자체는 백그라운드 스레드에서 실행되어 UI 응답성 유지.
- ✅ Dashboard F7/F8 rescan 시 즉시 "⟳ Rescanning..." 표시 후 비동기 처리.
- ✅ Logs Inspection 점검 항목 수집을 @work 로 이전. 화면 이탈 시 자동 취소.
- ✅ Login 화면 — utils.auth.AuthenticationManager 단일 구현으로 통합. 인증 로직
     분기로 인한 UI 메시지 불일치 해소.
- ✅ MNX Config 진입 인증(MnxConfigAuthScreen) 도 동일 인증 경로 공유.

## Architecture
- main_app.py: MNXApp (App), lazy module loading, F1/F5/F7/F8/F10/ESC global bindings
- Widgets: CustomHeader, MenuList, TwoPanelLayout, LeftPanel, RightPanel, MenuTitle
- Screens: login, dashboard, system, performance, kafka, elasticsearch, logs, network, shell, service, mnx_config

## Key Compliance Findings (2026-03-03)
See: compliance-findings.md for full violation list

### CRITICAL Violations
1. Header height = 1 (MUST be 3) - custom_header.py:26, ALL screens
2. Navigation width = fixed 30 cols (MUST be 25% of terminal width)
3. Status bar (Footer) has no inverse color - theme.tcss:27-35
4. Min width = 100 not enforced anywhere in app

### Confirmed Compliant
- Keyboard-only operability: all screens have keyboard bindings, mouse hover is additive only
- Focus management: set_timer(0.1, focus) pattern used consistently
- ESC back navigation: consistent across all screens
- F5 refresh: consistent across content screens

## Patterns Observed
- All content screens: CustomHeader + two-panel layout (#left-panel 30col + #right-panel 1fr)
- Menu highlight: [reverse] markup for cursor, [cyan]▸[/] for selected item
- Background color: #0c0c0c (not pure black #000000) - inconsistency with theme.tcss $bg-black
- Timer pattern: set_timer(0.1, ...) for focus init, set_interval(N, ...) for refresh
- All screens yield Footer() - needed for key binding display

## Non-Selectable Menu Items
- Separators: "─" or "---" prefix, disabled=True
- Section headers: ending with ":", disabled=True
- Special class pattern: -section, -separator, -back, -disabled

## Screen-specific Notes
- kafka.py / elasticsearch.py: uses threading + call_from_thread for async data
- service.py: unique key bindings R/S/X/A/Z for service control
- shell.py: uses app.suspend() for interactive bash session
- mnx_config.py: left panel width=26 (differs from 30 used elsewhere)
- logs.py: menu-title uses dock:top (inconsistency)
- network.py: has ModalScreen (NetworkConfigModal) with width=62
