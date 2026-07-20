# Compliance Findings - MNXMC TUI (2026-03-03)

## Rule 1: Header height = 3 lines
VIOLATION - custom_header.py:26: height: 1 (should be 3)
All screens inherit this. Required: 3 lines total (title row + subtitle/breadcrumb + separator).

## Rule 2: Navigation width = 25%
VIOLATION - All screens use fixed pixel widths:
- dashboard.py:48, system.py:45, performance.py:43, kafka.py:51,
  elasticsearch.py:39, logs.py:58, shell.py:44, service.py:71: width: 30
- mnx_config.py:173: width: 26 (also fixed, also non-compliant)
- two_panel_layout.py:47: width: 32 (LeftPanel DEFAULT_CSS)
Required: width: 25% (responsive percentage)

## Rule 3: Status bar inverse color
VIOLATION - theme.tcss:27-35: Footer background: #0c0c0c, color: $bg-black
No text-style: reverse applied. Required: background/foreground inversion.

## Rule 4: Keyboard-only operability
COMPLIANT (with minor issues):
- All navigation uses ListView with Up/Down/Enter
- hover CSS present (mouse-additive only, not exclusive)
- service.py: dialog requires typing 'confirm' then password - acceptable
- network.py modal: keyboard navigable (Tab between buttons)
- login.py: Tab moves username -> password -> button, Enter submits

Minor issue: mnx_config.py buttons (Apply/Reset) reachable by Tab but
no explicit focus order enforced.

## Rule 5: Min width = 100 columns
VIOLATION - No enforcement anywhere:
- main_app.py: no MIN_WIDTH or terminal size check
- No CSS min-width: 100 on root Screen
- login.py main-box: width: 62 (fine if screen >=100)
- network.py modal: width: 62 (fine if screen >=100)
Required: Screen-level min-width: 100 in theme.tcss or main_app.py

## Layout Compliance
- Background inconsistency: theme.tcss uses $bg-black (#000000) but all
  screens override with #0c0c0c. Pick one.
- main-container height: system.py:39 uses height:100% instead of height:1fr
  (potential footer overlap issue)
- service.py:64: #main-horizontal height: 1fr (correct) but no header
  wrapping container - relies on Horizontal directly

## Interaction Compliance
- Global bindings (F1/F5/F7/F8/F10/ESC) defined in main_app.py
- Per-screen F5/ESC re-declared (redundant but harmless)
- service.py adds R/S/X/A/Z bindings - unique to that screen, not global
- mnx_config.py uses Ctrl+S for apply - acceptable, maps to action_apply
- kafka.py / elasticsearch.py: only F5 and ESC - no F7/F8 (by design, no system rescan needed)
- shell.py: only ESC binding - no F5 refresh (Shell Info is static)

## Accessibility Compliance
- Color contrast: cyan (#5fd7d7) on black (#0c0c0c) - passes WCAG AA (~4.8:1)
- Yellow (#d7af00) on black - passes (~4.5:1 borderline)
- Red on black (#ff5555 on #0c0c0c) - passes
- Reverse markup for menu cursor: ensures visible focus indicator
- login.py status widget (#888888 on #0c0c0c) - FAILS contrast (~2.5:1)
- service.py #action-hint (#555555 on #0c0c0c) - FAILS contrast (~2.1:1)
- mnx_config.py .field-hint (#555555) - FAILS contrast
- Screen reader: no ARIA equivalents (TUI limitation, acceptable)
- Focus indicator: [reverse] markup provides visible indicator
