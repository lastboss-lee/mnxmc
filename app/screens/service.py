"""
Service Manager Screen

MNX 서비스 상태 확인 및 제어 화면.

Layout:
    - Left Panel : Back / Overview / 11개 서비스 (status icon + 이름)
    - Right Panel: Overview → uptime 포함 전체 현황
                   Service  → systemctl status [svc] 출력

Controls (좌측 메뉴 포커스 상태):
    R: Restart  S: Start  X: Stop  A: All Start  Z: All Stop
    F5: Refresh  ESC: Back / Close dialog
"""

from textual.app import ComposeResult
from textual.widgets import Static, Input, ListView
from textual.containers import Container, Vertical
from textual.binding import Binding
from textual import on
from app.ui.screen import BaseScreen, Sidebar
from rich.markup import escape as _esc
import subprocess
import threading
from datetime import datetime
import os
import pwd
import shutil


# ════════════════════════════════════════════════════════════════════════════
# systemctl 명령어 빌더 (root 직접 실행 / non-root sudo -n 자동 분기)
# ════════════════════════════════════════════════════════════════════════════

_SBIN_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _systemctl_cmd(*args: str) -> list:
    """root이면 systemctl 직접, non-root이면 sudo -n으로 감싸 반환.

    sudoers.d/mnxmc에 `sands ALL=(root) NOPASSWD: /usr/bin/systemctl` 부여됨.
    """
    systemctl = shutil.which("systemctl", path=_SBIN_PATH) or "/usr/bin/systemctl"
    base = [systemctl, *args]
    if os.geteuid() == 0:
        return base
    sudo = shutil.which("sudo", path=_SBIN_PATH) or "/usr/bin/sudo"
    return [sudo, "-n", *base]

try:
    import crypt
    import spwd
    _SHADOW_AUTH_AVAILABLE = True
except ImportError:
    _SHADOW_AUTH_AVAILABLE = False


# ════════════════════════════════════════════════════════════════════════════
# Auth
# ════════════════════════════════════════════════════════════════════════════

class AuthenticationManager:
    """시스템 계정 인증.

    인증 우선순위:
      1. /etc/shadow 직접 비교 (root 권한 있을 때)
      2. su 명령어 PAM 인증 (non-root SSH 접속 시 fallback)
    """

    def authenticate(self, username: str, password: str) -> tuple:
        # ── 계정 존재 확인은 passwd 로 한다 ───────────────────────────────
        # /etc/shadow 는 root 만 읽으므로 "계정 없음" 판정에 쓸 수 없다.
        try:
            pwd.getpwnam(username)
        except KeyError:
            return False, "User not found"

        # ── 1순위: shadow 직접 비교 — root 일 때만 시도한다 ───────────────
        # 비root 에서 spwd.getspnam() 이 던지는 예외는 OS 에 따라 다르다:
        #   22.04: nsswitch `shadow: files`         → EACCES 전파 → PermissionError
        #   26.04: nsswitch `shadow: files systemd` → files 가 EACCES 로 실패하면
        #          다음 소스(systemd)로 넘어가 "not found" 가 되고 → KeyError
        # 예전 코드는 KeyError 를 "User not found" 로 즉시 반환해서, 26.04 의
        # 비root(SSH) 세션에서는 아래 su fallback 에 도달하지 못했다.
        # 예외 종류에 의존하지 않도록 euid 로 분기한다.
        if _SHADOW_AUTH_AVAILABLE and os.geteuid() == 0:
            try:
                shadow = spwd.getspnam(username)
                stored_hash = shadow.sp_pwdp
                if not stored_hash or stored_hash in ('*', '!', '!!', '*LK*'):
                    return False, "Account locked or no password"
                if crypt.crypt(password, stored_hash) == stored_hash:
                    return True, None
                return False, "Invalid password"
            except Exception:
                # shadow 를 읽지 못한 root 는 인증을 통과시키지 않는다.
                return False, "Authentication failed"

        # ── 2순위: su PAM fallback (non-root 전용) ─────────────────────────
        # root로 실행 중이면 su는 패스워드 없이 통과하므로 사용 금지
        if os.geteuid() != 0:
            return self._verify_with_su(username, password)

        return False, "Authentication failed"

    def _verify_with_su(self, username: str, password: str) -> tuple:
        """su 명령어를 통한 PAM 인증 (non-root 전용)."""
        try:
            proc = subprocess.Popen(
                ['su', '-', username, '-c', 'echo __AUTH_OK__'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin', 'TERM': 'dumb'},
            )
            stdout, _ = proc.communicate(input=password + '\n', timeout=10)
            if '__AUTH_OK__' in stdout:
                return True, None
            return False, "Invalid password"
        except Exception as e:
            return False, str(e)


# ════════════════════════════════════════════════════════════════════════════
# Screen
# ════════════════════════════════════════════════════════════════════════════

class ServiceScreen(BaseScreen):
    """MNX Service Manager (공통 BaseScreen 골격 사용)."""

    SIDEBAR_TITLE = "SERVICE MANAGER"
    SIDEBAR_BULLET = False   # 라벨은 상태 아이콘과 함께 동적으로 갱신됨

    FOOTER_KEYS = [
        ("↑↓", "Select"),
        ("R/S/X", "Restart/Start/Stop"),
        ("A/Z", "All Start/Stop"),
        ("F5", "Refresh"),
        ("F10", "Exit"),
        ("ESC", "Back"),
    ]

    CSS = """
    ServiceScreen {
        background: #0c0c0c;
    }

    /* 긴 서비스명 줄바꿈 허용 — 항목 높이를 내용에 맞춰 가변으로.
       (공통 Sidebar 는 건드리지 않도록 ServiceScreen 스코프로 한정) */
    ServiceScreen Sidebar ListItem {
        height: auto;
    }

    /* ── 우측 패널 ── */
    #content-panel {
        width: 1fr;
        height: 100%;
        background: #0c0c0c;
    }

    #content-title {
        width: 100%;
        height: 1;
        background: #333333;
        color: white;
        text-style: bold;
        padding: 0 2;
    }

    #content-body {
        width: 100%;
        height: 1fr;
        background: #0c0c0c;
        color: white;
        padding: 1 2;
        overflow-y: auto;
    }

    #action-hint {
        width: 100%;
        height: 1;
        color: #767676;
        padding: 0 2;
    }

    #action-result {
        width: 100%;
        height: 1;
        color: #5fd7d7;
        padding: 0 2;
    }

    /* ── 인증 다이얼로그 ── */
    #dialog-overlay {
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.7);
        align: center middle;
        display: none;
    }

    #dialog-overlay.visible {
        display: block;
    }

    #dialog-box {
        width: 56;
        height: auto;
        background: #1a1a1a;
        border: double #5fd7d7;
        padding: 1 2;
    }

    #dialog-title {
        color: #d7af00;
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }

    #dialog-message {
        color: white;
        text-align: center;
        margin-bottom: 1;
    }

    #dialog-input {
        margin-bottom: 1;
    }

    #dialog-hint {
        color: #aaaaaa;
        text-align: center;
    }

    #dialog-error {
        color: #ff5555;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back",         "Back"),
        Binding("f5",     "refresh",          "Refresh"),
        Binding("r",      "restart_service",  "Restart"),
        Binding("s",      "start_service",    "Start"),
        Binding("x",      "stop_service",     "Stop"),
        Binding("a",      "all_start",        "All Start"),
        Binding("z",      "all_stop",         "All Stop"),
    ]

    # (systemd unit, 좌측 표시 이름, 설명)
    SERVICES = [
        ("mnx_service_control.service", "mnx_service_control", "System Management"),
        ("eng_monitor.service",         "eng_monitor",         "Monitoring Service"),
        ("mnx_regression_api.service",  "mnx_regression_api",  "Regression Analysis API"),
        ("mnx-thirdparty.service",      "mnx-thirdparty",      "Thirdparty IP Block"),
        ("mnx_payload.service",         "mnx_payload",         "Payload Analysis"),
        ("mnx_payload_ai.service",      "mnx_payload_ai",      "AI Analysis"),
        ("mnx_payload_scan.service",    "mnx_payload_scan",    "Scan Engine"),
        ("mnxcapture.service",          "mnxcapture",          "Traffic Capture"),
        ("mnxdpi.service",              "mnxdpi",              "Deep Packet Inspection"),
        ("suricata.service",            "suricata",            "Network Security"),
        ("elasticsearch.service",       "elasticsearch",       "Search Cluster (node 1+2)"),
        ("elasticsearch-node-1.service", "elasticsearch-node-1", "Search & Analytics (Node 1)"),
        ("elasticsearch-node-2.service", "elasticsearch-node-2", "Search & Analytics (Node 2)"),
        ("kafka.service",               "kafka",               "Message Queue"),
        ("zookeeper.service",           "zookeeper",           "Coordination Service"),
    ]

    SIDEBAR_ITEMS = [("back", "← Back"), ("overview", "Overview")] + [
        (f"svc-{i}", short) for i, (_u, short, _d) in enumerate(SERVICES)
    ]

    def __init__(self) -> None:
        super().__init__()
        self._service_cache: dict = {}   # unit → "active" | "inactive" | ...
        self._since_cache:   dict = {}   # unit → elapsed string
        self._dialog_stage       = None
        self._pending_action     = None
        self._pending_service    = None
        self._auth               = AuthenticationManager()
        self._current_svc: str | None = None   # 현재 하이라이트된 서비스 unit
        self._is_overview: bool = True

    # ════════════════════════════════════════════════════════════════════════
    # Compose / Lifecycle
    # ════════════════════════════════════════════════════════════════════════

    def compose_content(self) -> ComposeResult:
        with Vertical(id="content-panel"):
            yield Static("Service Overview", id="content-title")
            yield Static("Loading...", id="content-body")
            yield Static("", id="action-hint")
            yield Static("", id="action-result")

        with Container(id="dialog-overlay"):
            with Vertical(id="dialog-box"):
                yield Static("⚠ Confirmation Required", id="dialog-title")
                yield Static("", id="dialog-message")
                yield Input(id="dialog-input", placeholder="Type 'confirm' to proceed")
                yield Static("Press ESC to cancel", id="dialog-hint")
                yield Static("", id="dialog-error")

    def on_mount(self) -> None:
        # 사이드바 항목은 BaseScreen 이 SIDEBAR_ITEMS 로 구성함
        # 힌트/레이블 먼저 표시 후 비동기 데이터 수집
        self._set_hint(overview=True)
        self._refresh_all_menu_labels()   # Overview 활성 표시
        self._async_scan()

        self._refresh_handle = self.set_interval(5.0, self._auto_refresh)
        self.set_timer(0.1, self._focus_menu)

    def on_unmount(self) -> None:
        if getattr(self, "_refresh_handle", None):
            self._refresh_handle.stop()

    def _focus_menu(self) -> None:
        try:
            menu = self.query_one("Sidebar ListView", ListView)
            menu.focus()
            menu.index = 1   # Overview 기본
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════════
    # 메뉴 이벤트
    # ════════════════════════════════════════════════════════════════════════

    def _refresh_all_menu_labels(self, highlighted_id: str = "") -> None:
        """전체 메뉴 레이블 갱신 (logs.py 스타일).

        커서 위치       : [reverse] ▸ text [/]
        현재 열람 중 항목: [cyan]▸[/] + 상태 아이콘(색상 유지) + 이름
        일반 항목       :   상태 아이콘 + 이름
        """
        try:
            sidebar = self.query_one(Sidebar)
        except Exception:
            return

        # 커서 하이라이트는 CSS(-highlight)가 담당. 항목은 캐럿(›)으로 시작하고
        # 현재 열람 중(active)인 항목만 굵은 마커(▸ cyan)로 구분한다. (전 화면 통일)

        # ── Back ──────────────────────────────────────────────────────────────
        sidebar.update_item_label("back", "› ← Back")

        # ── Overview ──────────────────────────────────────────────────────────
        if self._is_overview:
            sidebar.update_item_label("overview", "[cyan]▸ Overview[/]")
        else:
            sidebar.update_item_label("overview", "› Overview")

        # ── Services ──────────────────────────────────────────────────────────
        for i, (svc, short, _) in enumerate(self.SERVICES):
            key = f"svc-{i}"
            status = self._service_cache.get(svc, "unknown")
            color, symbol = self._status_icon(status)
            is_active = (not self._is_overview) and (self._current_svc == svc)
            name = self._wrap_svc_name(short)
            if is_active:
                sidebar.update_item_label(key, f"[cyan]▸[/] [{color}]{symbol}[/] {name}")
            else:
                sidebar.update_item_label(key, f"› [{color}]{symbol}[/] {name}")

    def on_nav_highlighted(self, item_id: str) -> None:
        """커서 이동 → 우측 패널 즉시 갱신 + Back/Overview 반전 효과."""
        if self._dialog_stage or not item_id:
            return

        # 우측 패널 갱신 (back 은 우측 유지)
        if item_id == "overview":
            self._is_overview = True
            self._current_svc = None
            self._set_title("Service Overview")
            self._refresh_overview()
            self._set_hint(overview=True)

        elif item_id.startswith("svc-"):
            idx = int(item_id[4:])
            svc, short, _ = self.SERVICES[idx]
            self._is_overview = False
            self._current_svc = svc
            self._set_title(short)
            self._refresh_detail(svc)
            self._set_hint(overview=False)

        # 메뉴 레이블 갱신 (커서 하이라이트는 CSS -highlight 가 담당 — 전 화면 통일)
        self._refresh_all_menu_labels()

    def on_nav_selected(self, item_id: str) -> None:
        """Enter → Back 처리."""
        if self._dialog_stage:
            return
        if item_id == "back":
            self.action_go_back()

    # ════════════════════════════════════════════════════════════════════════
    # 데이터 수집 (비동기)
    # ════════════════════════════════════════════════════════════════════════

    def _async_scan(self) -> None:
        """백그라운드 스레드에서 전체 서비스 상태를 수집합니다."""
        def _worker():
            service_cache, since_cache = self._do_scan()
            self.app.call_from_thread(self._after_scan, service_cache, since_cache)
        threading.Thread(target=_worker, daemon=True).start()

    def _do_scan(self) -> tuple:
        """백그라운드에서 모든 서비스 상태 수집 (블로킹 허용). 결과 반환."""
        service_cache: dict = {}
        since_cache:   dict = {}
        for svc, _, _ in self.SERVICES:
            try:
                r = subprocess.run(
                    ['systemctl', 'is-active', svc],
                    capture_output=True, text=True, timeout=5
                )
                service_cache[svc] = r.stdout.strip()
            except Exception:
                service_cache[svc] = "unknown"

            try:
                r = subprocess.run(
                    ['systemctl', 'show', svc,
                     '--property=ActiveEnterTimestamp'],
                    capture_output=True, text=True, timeout=5
                )
                line   = r.stdout.strip()
                ts_val = line.split('=', 1)[1].strip() if '=' in line else ""
                since_cache[svc] = self._elapsed(ts_val)
            except Exception:
                since_cache[svc] = "N/A"
        return service_cache, since_cache

    def _after_scan(self, service_cache: dict, since_cache: dict) -> None:
        """메인 스레드: 캐시 업데이트 후 현재 뷰 갱신."""
        self._service_cache = service_cache
        self._since_cache   = since_cache
        if self._is_overview:
            self._refresh_overview()
        elif self._current_svc:
            self._refresh_detail(self._current_svc)
            self._refresh_all_menu_labels()
        else:
            self._refresh_overview()

    def _scan_all_services(self) -> None:
        """모든 서비스의 상태 + 기동 시각 수집."""
        for svc, _, _ in self.SERVICES:
            # is-active
            try:
                r = subprocess.run(
                    ['systemctl', 'is-active', svc],
                    capture_output=True, text=True, timeout=5
                )
                self._service_cache[svc] = r.stdout.strip()
            except Exception:
                self._service_cache[svc] = "unknown"

            # ActiveEnterTimestamp → 경과 시간
            try:
                r = subprocess.run(
                    ['systemctl', 'show', svc,
                     '--property=ActiveEnterTimestamp'],
                    capture_output=True, text=True, timeout=5
                )
                line = r.stdout.strip()
                ts_val = line.split('=', 1)[1].strip() if '=' in line else ""
                self._since_cache[svc] = self._elapsed(ts_val)
            except Exception:
                self._since_cache[svc] = "N/A"

    def _elapsed(self, ts: str) -> str:
        """'Thu 2024-01-01 12:34:56 KST' → '2h 15m ago' 형태."""
        if not ts:
            return "N/A"
        try:
            parts = ts.split()
            if len(parts) >= 3:
                dt = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
                secs = int((datetime.now() - dt).total_seconds())
                if secs < 0:
                    return ts
                if secs < 60:
                    return f"{secs}s ago"
                m = secs // 60
                if m < 60:
                    return f"{m}m ago"
                h = m // 60
                if h < 24:
                    return f"{h}h {m%60}m ago"
                d = h // 24
                return f"{d}d {h%24}h ago"
        except Exception:
            pass
        return ts

    def _status_icon(self, status: str) -> tuple:
        if status == "active":
            return "green", "●"
        elif status in ("inactive", "dead"):
            return "red", "○"
        else:
            return "yellow", "◐"

    # 사이드바 폭 계산용 상수
    # theme: Sidebar width 26 - border-right 1 - ListItem padding(2+2) = 21
    _SIDEBAR_USABLE = 21
    _LABEL_PREFIX   = 4           # "› ● " / "▸ ● " 가시 폭

    def _wrap_svc_name(self, short: str) -> str:
        """사이드바 폭을 넘는 서비스명을 2줄로 줄바꿈한다.

        프리픽스(4칸) + 이름이 사용 가능 폭(22칸)을 넘으면 '_' 또는 '-'
        구분점에서 잘라 둘째 줄을 이름 시작 위치(4칸 들여쓰기)에 맞춘다.
        구분점이 없으면 예산 경계에서 강제 분할한다.
        """
        budget = self._SIDEBAR_USABLE - self._LABEL_PREFIX   # 첫 줄 이름 예산 = 18
        if len(short) <= budget:
            return short
        cut = -1
        for i in range(min(budget, len(short))):
            if short[i] in "_-":
                cut = i
        if cut < 0:
            cut = budget - 1                     # 구분점 없음 → 강제 분할
        line1, line2 = short[:cut + 1], short[cut + 1:]
        return f"{line1}\n    {line2}"           # 4칸 들여쓰기 = 이름 시작 정렬

    # ════════════════════════════════════════════════════════════════════════
    # 화면 갱신
    # ════════════════════════════════════════════════════════════════════════

    def _set_title(self, text: str) -> None:
        try:
            self.query_one("#content-title", Static).update(text)
        except Exception:
            pass

    def _set_hint(self, overview: bool) -> None:
        try:
            w = self.query_one("#action-hint", Static)
            if overview:
                w.update("[bright_black]F5: Refresh  A: All Start  Z: All Stop[/]")
            else:
                w.update("[bright_black]R: Restart  S: Start  X: Stop  "
                         "A: All Start  Z: All Stop[/]")
        except Exception:
            pass

    def _refresh_overview(self) -> None:
        """Overview: 전체 서비스 상태 + uptime 표."""
        running = stopped = other = 0
        now = datetime.now().strftime("%H:%M:%S")

        lines = [
            f"[bold cyan]══ Service Status ══[/]  [bright_black]{now}[/]\n",
            f"  [bold]{'Service':<28} {'Status':<12} Uptime[/]",
            f"  {'─'*28} {'─'*12} {'─'*20}",
        ]

        for svc, short, _ in self.SERVICES:
            status = self._service_cache.get(svc, "unknown")
            color, symbol = self._status_icon(status)
            uptime = self._since_cache.get(svc, "N/A")

            if status == "active":
                running += 1
            elif status in ("inactive", "dead"):
                stopped += 1
            else:
                other += 1

            uptime_str = f"[bright_black]{uptime}[/]" if status == "active" else "[bright_black]─[/]"
            lines.append(
                f"  [{color}]{symbol}[/] {short:<27}"
                f"[{color}]{status:<12}[/]  {uptime_str}"
            )

        lines.append(
            f"\n  [green]Running: {running}[/]   "
            f"[red]Stopped: {stopped}[/]   "
            f"[yellow]Other: {other}[/]"
        )

        try:
            self.query_one("#content-body", Static).update("\n".join(lines))
        except Exception:
            pass

        self._refresh_all_menu_labels()

    def _refresh_detail(self, svc: str) -> None:
        """systemctl status [svc] 출력을 우측에 비동기 표시."""
        try:
            self.query_one("#content-body", Static).update("[bright_black]Loading...[/]")
        except Exception:
            pass

        def _worker():
            try:
                r = subprocess.run(
                    ['systemctl', 'status', svc, '--no-pager', '--lines=30'],
                    capture_output=True, text=True, timeout=10
                )
                output = (r.stdout or r.stderr or f"No status for {svc}").rstrip()
            except Exception as e:
                output = f"Error: {e}"
            self.app.call_from_thread(self._apply_detail, svc, output)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_detail(self, svc: str, output: str) -> None:
        """메인 스레드: 현재 선택된 서비스와 일치할 때만 패널 갱신."""
        if self._current_svc != svc:
            return
        try:
            colored = self._colorize_status(output)
            self.query_one("#content-body", Static).update(colored)
        except Exception:
            pass

    @staticmethod
    def _colorize_status(output: str) -> str:
        """
        systemctl status 출력에 Textual rich 마크업 적용.

        색상 규칙:
          첫 줄 (서비스 이름)  : bold, 상태 심볼 색상
          Active:             : green(running) / red(failed/inactive) / yellow(activating)
          Loaded:             : enabled→green, disabled/masked→red
          필드 레이블          : cyan (Main PID, Memory, CPU, CGroup …)
          Memory/CPU 값       : bold white
          Main PID 번호        : yellow
          CGroup 프로세스 트리  : dim + PID yellow
          로그 줄 타임스탬프    : dim
          로그 error/fail      : red
          로그 warning         : yellow
          로그 start/ok        : green
        """
        import re

        # 로그 줄 패턴: "Jan  1 12:34:56 host svc[pid]: msg"
        _LOG = re.compile(
            r'^(\w{3}\s+\d+\s+[\d:]+)\s+(\S+)\s+(\S+\[\d+\]:\s*)(.*)'
        )

        lines  = output.split('\n')
        result = []

        for i, raw in enumerate(lines):
            # ── 첫 번째 줄: ● / × / ○ 심볼 + 서비스 이름 ─────────────
            if i == 0:
                if raw.startswith('●'):
                    result.append(f'[green bold]●[/][bold]{_esc(raw[1:])}[/]')
                elif raw.startswith(('×', '✗', 'x')):
                    result.append(f'[red bold]×[/][bold]{_esc(raw[1:])}[/]')
                else:
                    result.append(f'[bold]{_esc(raw)}[/]')
                continue

            stripped = raw.lstrip()
            indent   = raw[:len(raw) - len(stripped)]

            # ── Active: ──────────────────────────────────────────────────
            if stripped.startswith('Active:'):
                rest = stripped[7:].lstrip()
                if 'active (running)' in rest:
                    pre, post = rest.split('active (running)', 1)
                    post_esc  = re.sub(
                        r'(;\s*.+ago)', r'[bright_black]\1[/]', _esc(post)
                    )
                    colored = f'{_esc(pre)}[green]active (running)[/]{post_esc}'
                elif 'failed' in rest:
                    colored = re.sub(
                        r'(failed)', r'[red bold]\1[/]', _esc(rest)
                    )
                elif 'inactive' in rest:
                    colored = re.sub(
                        r'(inactive(?:\s*\([^)]*\))?)',
                        r'[red]\1[/]', _esc(rest)
                    )
                elif 'activating' in rest or 'deactivating' in rest:
                    colored = re.sub(
                        r'(de?activating(?:\s*\([^)]*\))?)',
                        r'[yellow]\1[/]', _esc(rest)
                    )
                else:
                    colored = _esc(rest)
                result.append(f'{indent}[cyan]Active:[/] {colored}')
                continue

            # ── Loaded: ──────────────────────────────────────────────────
            if stripped.startswith('Loaded:'):
                rest = re.sub(r'\benabled\b',  '[green]enabled[/]',
                       re.sub(r'\bdisabled\b', '[red]disabled[/]',
                       re.sub(r'\bmasked\b',   '[red]masked[/]',
                              _esc(stripped[7:].lstrip()))))
                result.append(f'{indent}[cyan]Loaded:[/] {rest}')
                continue

            # ── 기타 구조화 필드 ─────────────────────────────────────────
            fm = re.match(
                r'^(\s+)(Docs|Main PID|Tasks|Memory|CPU|CGroup|Drop-In|'
                r'Process|Status|Error|TriggeredBy|Condition|Control|'
                r'Invocation|IPAddress(?:Ingress|Egress)|Listen)(:)(.*)',
                raw
            )
            if fm:
                pre, label, colon, rest = fm.groups()
                rest_e = _esc(rest)
                if label in ('Memory', 'CPU'):
                    result.append(
                        f'{pre}[cyan]{label}{colon}[/][bold white]{rest_e}[/]'
                    )
                elif label == 'Main PID':
                    rest_e = re.sub(r'(\d+)', r'[yellow]\1[/]', rest_e, count=1)
                    result.append(f'{pre}[cyan]{label}{colon}[/]{rest_e}')
                elif label == 'Error':
                    result.append(
                        f'{pre}[red bold]{label}{colon}[/]{rest_e}'
                    )
                else:
                    result.append(f'{pre}[cyan]{label}{colon}[/]{rest_e}')
                continue

            # ── CGroup 프로세스 트리 ──────────────────────────────────────
            if '└─' in raw or '├─' in raw or ('│' in raw and raw.strip().startswith('│')):
                esc = re.sub(
                    r'(└─|├─)(\d+)', r'\1[yellow]\2[/]', _esc(raw)
                )
                result.append(f'[bright_black]{esc}[/]')
                continue

            # ── 로그 줄 ──────────────────────────────────────────────────
            m = _LOG.match(raw)
            if m:
                ts, host, proc, msg = m.groups()
                msg_e = _esc(msg)
                msg_e = re.sub(
                    r'\b(error|Error|ERROR|fail|failed|Failed|FAILED)\b',
                    r'[red]\1[/]', msg_e
                )
                msg_e = re.sub(
                    r'\b(warning|Warning|WARNING|warn|Warn)\b',
                    r'[yellow]\1[/]', msg_e
                )
                msg_e = re.sub(
                    r'\b(Starting|Started|started|OK|Success|success|Loaded)\b',
                    r'[green]\1[/]', msg_e
                )
                result.append(
                    f'[bright_black]{_esc(ts)} {_esc(host)} {_esc(proc)}[/]{msg_e}'
                )
                continue

            # ── 나머지 (빈 줄, 구분선 등) ────────────────────────────────
            result.append(_esc(raw))

        return '\n'.join(result)

    def _auto_refresh(self) -> None:
        if self._dialog_stage:
            return
        self._async_scan()

    def _show_result(self, msg: str, error: bool = False) -> None:
        try:
            w = self.query_one("#action-result", Static)
            ts = datetime.now().strftime("%H:%M:%S")
            color = "red" if error else "green"
            w.update(f"[{color}][{ts}] {msg}[/]")
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════════
    # 다이얼로그
    # ════════════════════════════════════════════════════════════════════════

    def _show_dialog(self, action: str, service: str = None) -> None:
        self._dialog_stage    = "confirm"
        self._pending_action  = action
        self._pending_service = service

        if action == "all_start":
            msg = "You are about to [cyan]START ALL[/] services."
        elif action == "all_stop":
            msg = "You are about to [red]STOP ALL[/] services."
        else:
            name = service.replace('.service', '') if service else ""
            msg = (f"You are about to [yellow]{action.upper()}[/] service:\n"
                   f"[cyan]{name}[/]")

        try:
            self.query_one("#dialog-message", Static).update(msg)
            self.query_one("#dialog-error",   Static).update("")
            self.query_one("#dialog-hint",    Static).update("Press ESC to cancel")
            inp = self.query_one("#dialog-input", Input)
            inp.value       = ""
            inp.placeholder = "Type 'confirm' to proceed"
            inp.password    = False
            self.query_one("#dialog-overlay", Container).add_class("visible")
            self.set_timer(0.1, lambda: inp.focus())
        except Exception as e:
            self.log.error(f"Dialog show error: {e}")

    def _hide_dialog(self) -> None:
        self._dialog_stage    = None
        self._pending_action  = None
        self._pending_service = None
        try:
            self.query_one("#dialog-overlay", Container).remove_class("visible")
        except Exception:
            pass
        try:
            self.query_one("Sidebar ListView", ListView).focus()
        except Exception:
            pass

    @on(Input.Submitted, "#dialog-input")
    def on_dialog_input(self, event: Input.Submitted) -> None:
        if self._dialog_stage == "confirm":
            if event.value.lower() == "confirm":
                self._dialog_stage      = "password"
                event.input.value       = ""
                event.input.placeholder = "Enter your password"
                event.input.password    = True
                self.query_one("#dialog-hint",  Static).update(
                    "Enter password to authenticate")
                self.query_one("#dialog-error", Static).update("")
            else:
                self.query_one("#dialog-error", Static).update(
                    "Type 'confirm' exactly")

        elif self._dialog_stage == "password":
            # 'root' 기본값 금지 — 세션 사용자를 특정할 수 없을 때 root 비밀번호로
            # 서비스 제어를 승인하게 된다(인증 대상 계정이 조용히 바뀜).
            username = getattr(self.app, 'authenticated_user', None)
            if not username:
                self.query_one("#dialog-error", Static).update(
                    "세션 사용자를 확인할 수 없습니다. 다시 로그인하세요.")
                event.input.value = ""
                return

            success, error = self._auth.authenticate(username, event.value)
            if success:
                action  = self._pending_action
                service = self._pending_service
                self._hide_dialog()
                name = service.replace('.service', '') if service else "services"
                self._show_result(f"Executing {action} on {name}...")
                self.set_timer(0.2, lambda: self._execute_action(action, service))
            else:
                self.query_one("#dialog-error", Static).update(
                    f"Auth failed: {error}")
                event.input.value = ""

    # ════════════════════════════════════════════════════════════════════════
    # 서비스 제어
    # ════════════════════════════════════════════════════════════════════════

    def _execute_action(self, action: str, service: str) -> None:
        if action == "all_start":
            self._do_all_start()
        elif action == "all_stop":
            self._do_all_stop()
        else:
            self._do_service_action(service, action)

    def _do_service_action(self, service: str, action: str) -> None:
        name = service.replace('.service', '')
        try:
            result = subprocess.run(
                _systemctl_cmd(action, service),
                capture_output=True, text=True, timeout=60
            )
            self._async_scan()

            if result.returncode == 0:
                self._show_result(f"{action.capitalize()}ed: {name}")
                self.app.notify(f"Service {name} {action}ed", title="Success")
            else:
                self._show_result(f"Failed: {name}", error=True)
                self.app.notify(f"Failed to {action} {name}", severity="error")
        except subprocess.TimeoutExpired:
            self._show_result(f"Timeout: {name}", error=True)
        except Exception as e:
            self._show_result(f"Error: {str(e)[:40]}", error=True)

    def _do_all_start(self) -> None:
        order = [
            "zookeeper.service", "kafka.service",
            "elasticsearch-node-1.service", "elasticsearch-node-2.service",
            "mnx_service_control.service", "eng_monitor.service",
            "mnx_regression_api.service", "mnx-thirdparty.service",
            "mnx_payload.service", "mnxcapture.service", "mnxdpi.service",
            "suricata.service",
        ]
        ok = fail = 0
        for svc in order:
            try:
                r = subprocess.run(
                    _systemctl_cmd('start', svc),
                    capture_output=True, timeout=30
                )
                ok += r.returncode == 0
                fail += r.returncode != 0
            except Exception:
                fail += 1

        self._async_scan()
        self._show_result(f"All Start: {ok} success, {fail} failed")
        self.app.notify(f"All Start: {ok} success, {fail} failed",
                        title="Complete")

    def _do_all_stop(self) -> None:
        order = [
            "suricata.service", "mnxdpi.service", "mnxcapture.service",
            "mnx_payload.service", "mnx_payload_ai.service",
            "mnx_payload_scan.service",
            "mnx-thirdparty.service", "mnx_regression_api.service",
            "eng_monitor.service", "mnx_service_control.service",
            "elasticsearch-node-2.service", "elasticsearch-node-1.service",
            "kafka.service", "zookeeper.service",
        ]
        ok = fail = 0
        for svc in order:
            try:
                r = subprocess.run(
                    _systemctl_cmd('stop', svc),
                    capture_output=True, timeout=30
                )
                ok += r.returncode == 0
                fail += r.returncode != 0
            except Exception:
                fail += 1

        self._async_scan()
        self._show_result(f"All Stop: {ok} success, {fail} failed")
        self.app.notify(f"All Stop: {ok} success, {fail} failed",
                        title="Complete")

    # ════════════════════════════════════════════════════════════════════════
    # 액션 핸들러 (BINDINGS)
    # ════════════════════════════════════════════════════════════════════════

    def action_go_back(self) -> None:
        if self._dialog_stage:
            self._hide_dialog()
        else:
            self.app.pop_screen()

    def action_refresh(self) -> None:
        self._async_scan()
        self._show_result("Refreshed")

    def action_restart_service(self) -> None:
        if self._dialog_stage:
            return
        if self._current_svc:
            self._show_dialog("restart", self._current_svc)
        else:
            self.app.notify("Select a service first", severity="warning")

    def action_start_service(self) -> None:
        if self._dialog_stage:
            return
        if self._current_svc:
            self._show_dialog("start", self._current_svc)
        else:
            self.app.notify("Select a service first", severity="warning")

    def action_stop_service(self) -> None:
        if self._dialog_stage:
            return
        if self._current_svc:
            self._show_dialog("stop", self._current_svc)
        else:
            self.app.notify("Select a service first", severity="warning")

    def action_all_start(self) -> None:
        if not self._dialog_stage:
            self._show_dialog("all_start")

    def action_all_stop(self) -> None:
        if not self._dialog_stage:
            self._show_dialog("all_stop")
