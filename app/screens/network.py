"""
Network Management Screen

네트워크 인터페이스 관리 및 설정 화면입니다.

Features:
    - 네트워크 인터페이스 목록
    - 인터페이스 상세 정보
    - nmtui 스타일 설정 모달
    - Promiscuous Mode 설정
    - Mirror Port 설정
    - 실시간 네트워크 통계
"""

from textual.app import ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Footer, Static, ListView, ListItem,
    Label, Input, Button, Checkbox
)
from textual.containers import Container, Vertical, Horizontal, Center
from textual.binding import Binding
from textual.reactive import reactive
from textual import on
from app.widgets import CustomHeader
from typing import Optional
import subprocess
import threading


# ═══════════════════════════════════════════════════════════════════════════════
# Network Configuration Modal (nmtui Style)
# ═══════════════════════════════════════════════════════════════════════════════

class NetworkConfigModal(ModalScreen[dict]):
    """네트워크 설정 모달 - Mirror / DHCP / Static / Disable 모드."""

    CSS = """
    NetworkConfigModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.85);
    }

    #config-dialog {
        width: 62;
        height: auto;
        border: solid #5fd7d7;
        border-title-align: center;
        border-title-color: #5fd7d7;
        background: #1a1a1a;
        padding: 0 2;
    }

    /* ── 섹션 헤더 [ Title ] ─── */
    .section-header {
        width: 100%;
        height: 1;
        margin-top: 1;
    }

    /* ── 링크 상태 ── */
    #link-status {
        width: 100%;
        height: 1;
        padding: 0 1;
        margin-bottom: 1;
    }

    /* ── Method 섹션 행 ── */
    .method-row {
        width: 100%;
        height: 1;
    }

    .method-label {
        width: 12;
        height: 1;
        color: #aaaaaa;
        content-align: left middle;
    }

    /* ── 라디오 버튼 ([ ] / [●]) ── */
    .radio-btn {
        width: auto;
        min-width: 12;
        height: 1;
        border: none;
        background: transparent;
        color: #767676;
        content-align: left middle;
        padding: 0;
        margin: 0 1;
    }

    .radio-btn:hover {
        background: transparent;
        border: none;
        color: white;
    }

    .radio-btn:focus {
        border: none;
        background: transparent;
        color: white;
        text-style: bold;
    }

    .radio-btn.active {
        color: #5fd7d7;
        background: transparent;
        text-style: bold;
        border: none;
    }

    /* ── 입력 필드 (언더라인 스타일) ── */
    .field-row {
        width: 100%;
        height: 2;
        layout: horizontal;
    }

    .field-label {
        width: 13;
        height: 2;
        color: #aaaaaa;
        content-align: left middle;
    }

    .field-input {
        width: 1fr;
        height: 2;
        border-top: none;
        border-left: none;
        border-right: none;
        border-bottom: solid #5fd7d7;
        background: transparent;
        color: white;
        padding: 0 1;
    }

    .field-input:focus {
        border-top: none;
        border-left: none;
        border-right: none;
        border-bottom: solid white;
        background: transparent;
        color: yellow;
    }

    .field-input.-disabled {
        color: #333333;
        background: transparent;
        border-top: none;
        border-left: none;
        border-right: none;
        border-bottom: solid #333333;
    }

    /* ── 에러 + 하단 구분선 + 버튼 ── */
    #error-message {
        width: 100%;
        height: 1;
        color: #ff5555;
    }

    #sep-bottom {
        width: 100%;
        height: 1;
        margin-top: 1;
    }

    #button-row {
        width: 100%;
        height: 1;
        layout: horizontal;
        align: center middle;
        margin-top: 0;
        margin-bottom: 1;
    }

    #btn-apply {
        width: 20;
        height: 1;
        border: none;
        background: transparent;
        color: #5fd7d7;
        text-style: bold;
        content-align: center middle;
        padding: 0;
        margin: 0 2;
    }

    #btn-apply:hover {
        color: black;
        background: #5fd7d7;
        border: none;
        text-style: bold;
    }

    #btn-apply:focus {
        border: none;
        color: black;
        background: #5fd7d7;
        text-style: bold;
    }

    #btn-cancel {
        width: 20;
        height: 1;
        border: none;
        background: transparent;
        color: #cc4444;
        text-style: bold;
        content-align: center middle;
        padding: 0;
        margin: 0 2;
    }

    #btn-cancel:hover {
        color: black;
        background: #cc4444;
        border: none;
        text-style: bold;
    }

    #btn-cancel:focus {
        border: none;
        color: black;
        background: #cc4444;
        text-style: bold;
    }
    """

    # 모드 상수
    MODE_STATIC = "static"
    MODE_DHCP = "dhcp"
    MODE_MIRROR = "mirror"
    MODE_DISABLE = "disable"

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "apply",  "Apply"),
    ]

    def __init__(
        self,
        interface_name: str,
        current_ip: str = "",
        current_netmask: str = "255.255.255.0",
        current_gateway: str = "",
        current_dns: str = "",
        is_mirror: bool = False,
        is_promisc: bool = False,
        is_dhcp4: bool = False,
        is_dhcp6: bool = False,
        interface_status: str = "UP",
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.interface_name = interface_name
        self.interface_status = interface_status
        self.current_ip = current_ip if current_ip and current_ip != "No IP" else ""
        self.current_netmask = current_netmask or "255.255.255.0"
        self.current_gateway = current_gateway or ""
        self.current_dns = current_dns or ""
        self.is_promisc = is_promisc

        # 초기 모드 결정
        if is_mirror:
            self._mode = self.MODE_MIRROR
        elif is_dhcp4 or is_dhcp6:
            self._mode = self.MODE_DHCP
        elif self.current_ip:
            self._mode = self.MODE_STATIC
        else:
            self._mode = self.MODE_DISABLE

        # IP 버전 (IPv4 기본)
        self._ipv4 = True
        self._ipv6 = is_dhcp6 and not is_dhcp4
        if self._ipv6:
            self._ipv4 = False

        self._initial_mode = self._mode

    def compose(self) -> ComposeResult:
        with Vertical(id="config-dialog"):

            # ── [ Status ] ────────────────────────────────────
            yield Static(
                r"[bold #5fd7d7]\[ Status \][/] [bright_black]" + "─" * 43 + "[/]",
                classes="section-header",
            )
            status = self.interface_status
            if status == "NO-CARRIER":
                link_text = "[yellow]⚠ NO-CARRIER — cable unplugged. Config saved; applies when connected.[/]"
            elif status == "DOWN":
                link_text = "[red]⚠ Interface is DOWN. Config will apply when brought up.[/]"
            else:
                link_text = f"[green]● Link {status}[/]"
            yield Static(f" {link_text}", id="link-status")

            # ── [ Method ] ────────────────────────────────────
            yield Static(
                r"[bold #5fd7d7]\[ Method \][/] [bright_black]" + "─" * 44 + "[/]",
                classes="section-header",
            )
            with Horizontal(id="protocol-row", classes="method-row"):
                yield Static("Protocol:", classes="method-label")
                yield Button(r"\[ \] IPv4", id="btn-ipv4", classes="radio-btn")
                yield Button(r"\[ \] IPv6", id="btn-ipv6", classes="radio-btn")
            with Horizontal(classes="method-row"):
                yield Static("Assign:",  classes="method-label")
                yield Button(r"\[ \] Mirror",  id="btn-mode-mirror",  classes="radio-btn")
                yield Button(r"\[ \] DHCP",    id="btn-mode-dhcp",    classes="radio-btn")
            with Horizontal(classes="method-row"):
                yield Static("",         classes="method-label")
                yield Button(r"\[ \] Static",  id="btn-mode-static",  classes="radio-btn")
                yield Button(r"\[ \] Disable", id="btn-mode-disable", classes="radio-btn")

            # ── [ Configuration ] ─────────────────────────────
            yield Static(
                r"[bold #5fd7d7]\[ Configuration \][/] [bright_black]" + "─" * 35 + "[/]",
                classes="section-header",
            )
            with Horizontal(classes="field-row"):
                yield Static("IP Address:", classes="field-label")
                yield Input(
                    value=self.current_ip,
                    placeholder="192.168.1.100",
                    id="input-ip",
                    classes="field-input",
                )
            with Horizontal(classes="field-row"):
                yield Static("Netmask:", classes="field-label")
                yield Input(
                    value=self.current_netmask,
                    placeholder="255.255.255.0 or /24",
                    id="input-netmask",
                    classes="field-input",
                )
            with Horizontal(classes="field-row"):
                yield Static("Gateway:", classes="field-label")
                yield Input(
                    value=self.current_gateway,
                    placeholder="192.168.1.1",
                    id="input-gateway",
                    classes="field-input",
                )
            with Horizontal(classes="field-row"):
                yield Static("DNS:", classes="field-label")
                yield Input(
                    value=self.current_dns,
                    placeholder="8.8.8.8, 8.8.4.4",
                    id="input-dns",
                    classes="field-input",
                )

            yield Static("", id="error-message")

            # ── 하단 구분선 + 버튼 ──────────────────────────────
            yield Static("[bright_black]" + "─" * 56 + "[/]", id="sep-bottom")
            with Horizontal(id="button-row"):
                yield Button(r"< \[A\]pply (Ctrl+S) >", id="btn-apply")
                yield Button(r"< \[C\]ancel (ESC) >", id="btn-cancel")

    def on_mount(self) -> None:
        """마운트 시 초기 상태 반영."""
        # 다이얼로그 제목을 border에 표시
        try:
            self.query_one("#config-dialog", Vertical).border_title = (
                f"  Configure {self.interface_name}  "
            )
        except Exception:
            pass

        self._update_mode_display()
        self._update_ipversion_display()

        # 초기 포커스
        if self._mode == self.MODE_STATIC:
            self.query_one("#input-ip", Input).focus()
        else:
            btn_id = f"btn-mode-{self._mode}"
            try:
                self.query_one(f"#{btn_id}", Button).focus()
            except Exception:
                pass

    # ── 모드 전환 ──

    def _set_mode(self, mode: str) -> None:
        """모드 변경."""
        self._mode = mode
        self._update_mode_display()
        # 에러 메시지 초기화
        self.query_one("#error-message", Static).update("")
        # Static 외 모드로 전환 시 IP 입력 필드 초기화 (이전 값 잔류 방지)
        if mode != self.MODE_STATIC:
            for field_id in ("#input-ip", "#input-netmask", "#input-gateway", "#input-dns"):
                try:
                    self.query_one(field_id, Input).value = ""
                except Exception:
                    pass

    def action_set_mirror(self) -> None:
        self._set_mode(self.MODE_MIRROR)

    def action_set_dhcp(self) -> None:
        self._set_mode(self.MODE_DHCP)

    def action_set_static(self) -> None:
        self._set_mode(self.MODE_STATIC)
        self.query_one("#input-ip", Input).focus()

    def action_set_disable(self) -> None:
        self._set_mode(self.MODE_DISABLE)

    def _update_mode_display(self) -> None:
        """모드에 따라 UI 전체 업데이트."""
        mode_labels = {
            self.MODE_MIRROR:  "Mirror",
            self.MODE_DHCP:    "DHCP",
            self.MODE_STATIC:  "Static",
            self.MODE_DISABLE: "Disable",
        }
        mode_ids = {
            self.MODE_MIRROR:  "btn-mode-mirror",
            self.MODE_DHCP:    "btn-mode-dhcp",
            self.MODE_STATIC:  "btn-mode-static",
            self.MODE_DISABLE: "btn-mode-disable",
        }

        # 라디오 스타일 라벨 업데이트: [●] 선택됨, [ ] 비선택
        for mode, btn_id in mode_ids.items():
            btn = self.query_one(f"#{btn_id}", Button)
            label = mode_labels[mode]
            if mode == self._mode:
                btn.label = rf"\[●\] {label}"
                btn.add_class("active")
            else:
                btn.label = rf"\[ \] {label}"
                btn.remove_class("active")

        # IP 필드 활성화/비활성화
        fields_enabled = (self._mode == self.MODE_STATIC)
        for field_id in ["#input-ip", "#input-netmask", "#input-gateway", "#input-dns"]:
            inp = self.query_one(field_id, Input)
            inp.disabled = not fields_enabled

        # Protocol 행(IPv4/IPv6) 표시/숨김 (Mirror/Disable에서는 숨김)
        show_ipver = self._mode in (self.MODE_DHCP, self.MODE_STATIC)
        try:
            self.query_one("#protocol-row").display = show_ipver
        except Exception:
            pass

    # ── IPv4/IPv6 토글 ──

    def _toggle_ipv4(self) -> None:
        self._ipv4 = True
        self._ipv6 = False
        self._update_ipversion_display()

    def _toggle_ipv6(self) -> None:
        self._ipv4 = False
        self._ipv6 = True
        self._update_ipversion_display()

    def _update_ipversion_display(self) -> None:
        """IPv4/IPv6 버튼 라디오 스타일 업데이트."""
        btn4 = self.query_one("#btn-ipv4", Button)
        btn6 = self.query_one("#btn-ipv6", Button)

        if self._ipv4:
            btn4.label = r"\[●\] IPv4"
            btn6.label = r"\[ \] IPv6"
            btn4.add_class("active")
            btn6.remove_class("active")
        else:
            btn4.label = r"\[ \] IPv4"
            btn6.label = r"\[●\] IPv6"
            btn4.remove_class("active")
            btn6.add_class("active")

        # placeholder 업데이트
        ip_input = self.query_one("#input-ip", Input)
        mask_input = self.query_one("#input-netmask", Input)
        gw_input = self.query_one("#input-gateway", Input)

        if self._ipv4:
            ip_input.placeholder = "192.168.1.100"
            mask_input.placeholder = "255.255.255.0 or /24"
            gw_input.placeholder = "192.168.1.1"
        else:
            ip_input.placeholder = "2001:db8::1"
            mask_input.placeholder = "/64"
            gw_input.placeholder = "2001:db8::ffff"

    # ── 버튼 이벤트 ──

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """버튼 클릭 처리."""
        btn_id = event.button.id

        if btn_id == "btn-mode-mirror":
            self._set_mode(self.MODE_MIRROR)
        elif btn_id == "btn-mode-dhcp":
            self._set_mode(self.MODE_DHCP)
        elif btn_id == "btn-mode-static":
            self._set_mode(self.MODE_STATIC)
            self.query_one("#input-ip", Input).focus()
        elif btn_id == "btn-mode-disable":
            self._set_mode(self.MODE_DISABLE)
        elif btn_id == "btn-ipv4":
            self._toggle_ipv4()
        elif btn_id == "btn-ipv6":
            self._toggle_ipv6()
        elif btn_id == "btn-apply":
            self._apply_config()
        elif btn_id == "btn-cancel":
            self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
            return

        # Input에 포커스가 있으면 단축키 무시 (타이핑 허용)
        focused = self.app.focused
        if isinstance(focused, Input):
            return

        # 모드 전환 단축키
        key = event.key.lower()
        if key == "m":
            self._set_mode(self.MODE_MIRROR)
            event.stop()
        elif key == "d":
            self._set_mode(self.MODE_DHCP)
            event.stop()
        elif key == "s":
            self._set_mode(self.MODE_STATIC)
            self.query_one("#input-ip", Input).focus()
            event.stop()
        elif key == "n":
            self._set_mode(self.MODE_DISABLE)
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_apply(self) -> None:
        self._apply_config()

    # ── 설정 적용 ──

    def _apply_config(self) -> None:
        """설정을 수집하여 dismiss."""
        error = self.query_one("#error-message", Static)
        error.update("")

        if self._mode == self.MODE_MIRROR:
            self.dismiss({
                "interface": self.interface_name,
                "mode": self.MODE_MIRROR,
                "is_mirror": True,
                "promisc": True,
            })
            return

        if self._mode == self.MODE_DHCP:
            self.dismiss({
                "interface": self.interface_name,
                "mode": self.MODE_DHCP,
                "is_mirror": False,
                "dhcp4": self._ipv4,
                "dhcp6": self._ipv6,
            })
            return

        if self._mode == self.MODE_DISABLE:
            self.dismiss({
                "interface": self.interface_name,
                "mode": self.MODE_DISABLE,
                "is_mirror": False,
            })
            return

        # Static 모드: 입력값 검증
        ip = self.query_one("#input-ip", Input).value.strip()
        netmask = self.query_one("#input-netmask", Input).value.strip()
        gateway = self.query_one("#input-gateway", Input).value.strip()
        dns = self.query_one("#input-dns", Input).value.strip()

        if not ip:
            error.update("[red]IP address is required for Static mode[/]")
            return

        if self._ipv4:
            if "/" in ip:
                ip_part = ip.split("/")[0]
                if not self._is_valid_ipv4(ip_part):
                    error.update("[red]Invalid IPv4 address[/]")
                    return
            else:
                if not self._is_valid_ipv4(ip):
                    error.update("[red]Invalid IPv4 address[/]")
                    return

            if netmask and not netmask.startswith("/"):
                if not self._is_valid_ipv4(netmask):
                    error.update("[red]Invalid netmask format[/]")
                    return

            if gateway and not self._is_valid_ipv4(gateway):
                error.update("[red]Invalid gateway address[/]")
                return
        else:
            if not ip:
                error.update("[red]IPv6 address is required[/]")
                return

        self.dismiss({
            "interface": self.interface_name,
            "mode": self.MODE_STATIC,
            "is_mirror": False,
            "ipv4": self._ipv4,
            "ipv6": self._ipv6,
            "ip": ip,
            "netmask": netmask or ("255.255.255.0" if self._ipv4 else "/64"),
            "gateway": gateway,
            "dns": dns,
        })

    def _is_valid_ipv4(self, ip: str) -> bool:
        try:
            parts = ip.split(".")
            return len(parts) == 4 and all(0 <= int(p) <= 255 for p in parts)
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# Network Screen
# ═══════════════════════════════════════════════════════════════════════════════

class NetworkScreen(Screen):
    """
    네트워크 관리 화면.

    왼쪽 패널: 인터페이스 목록
    오른쪽 패널: 선택된 인터페이스 상세 정보
    """

    CSS = """
    NetworkScreen {
        background: #0c0c0c;
    }

    #main-container {
        width: 100%;
        height: 1fr;
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

    #interface-list {
        width: 100%;
        height: 1fr;
        background: #0c0c0c;
        border: none;
        padding: 1 0;
    }

    #interface-list > ListItem {
        background: #0c0c0c;
        color: white;
        height: 2;
        padding: 0 2;
    }

    #interface-list > ListItem:hover {
        background: #1a1a1a;
    }

    #interface-list > ListItem.-selected {
        background: #222222;
        color: white;
    }

    #right-panel {
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

    #interface-details {
        width: 100%;
        height: auto;
        color: white;
        background: #0c0c0c;
        padding: 1 2;
    }

    .status-up {
        color: green;
    }

    .status-down {
        color: red;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("f5", "refresh", "Refresh"),
        Binding("f8", "rescan", "Rescan Network"),
        Binding("enter", "configure", "Configure IP"),
        Binding("u", "toggle_link", "Link Up/Down"),
    ]

    selected_interface = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self._interfaces = []
        self._menu_texts = {}
        self._hovered_interface = ""  # 현재 하이라이트(hover)된 인터페이스

    # ── Helper methods ──

    def _get_iface_mode_tag(self, iface) -> str:
        """인터페이스 모드 태그 반환. PROMISC = 항상 mirror."""
        if getattr(iface, 'promisc', False):
            return " [magenta](mirror)[/]"
        return ""

    def _get_status_icon(self, status: str) -> str:
        """상태 아이콘 반환."""
        return {
            "UP": "[green]●[/]",
            "DOWN": "[red]○[/]",
            "NO-CARRIER": "[yellow]◐[/]",
        }.get(status, "[bright_black]?[/]")

    def _get_status_color(self, status: str) -> str:
        """상태 색상 반환."""
        return {"UP": "green", "NO-CARRIER": "yellow"}.get(status, "red")

    def _build_iface_label(self, iface, state: str = "normal") -> str:
        """인터페이스 목록 항목 텍스트 생성 (state: normal|highlighted|selected)."""
        name = iface.name
        status = getattr(iface, 'status', 'UNKNOWN')
        ip_addr = getattr(iface, 'ip', 'No IP') or 'No IP'
        status_color = self._get_status_color(status)
        mode_tag = self._get_iface_mode_tag(iface)

        if state == "highlighted":
            return f"[reverse] ▸ {name}{mode_tag} [/]\n    [{status_color}]{status}[/] {ip_addr}"
        elif state == "selected":
            return f"[cyan]▸ {name}{mode_tag}[/]\n    [{status_color}]{status}[/] {ip_addr}"
        else:
            return f"  {name}{mode_tag}\n    [{status_color}]{status}[/] {ip_addr}"

    def compose(self) -> ComposeResult:
        yield CustomHeader()

        with Container(id="main-container"):
            with Vertical(id="left-panel"):
                yield Static("Network Management", id="menu-title")
                yield ListView(id="interface-list")

            with Vertical(id="right-panel"):
                yield Static("Network Management", id="content-title")
                yield Static(self._get_interface_details(), id="interface-details")

        yield Footer()

    def on_mount(self) -> None:
        self.log.info("NetworkScreen mounted")
        self._load_interfaces()
        self._refresh_handle = self.set_interval(2.0, self._update_stats)

    def on_unmount(self) -> None:
        if hasattr(self, '_refresh_handle') and self._refresh_handle:
            self._refresh_handle.stop()

    def _load_interfaces(self) -> None:
        """네트워크 인터페이스 목록을 로드합니다."""
        try:
            interface_list = self.query_one("#interface-list", ListView)

            # 기존 항목들 완전히 제거
            while interface_list.children:
                interface_list.children[0].remove()

            self._menu_texts = {}

            if self.app.network_mgmt:
                self.app.network_mgmt.discover_interfaces()
                self._interfaces = self.app.network_mgmt.interfaces
            else:
                self._interfaces = []

            # Back 항목
            back_item = ListItem(Label("  ← Back"), classes="menu-back")
            self._menu_texts["menu-back"] = "← Back"
            interface_list.append(back_item)

            # 구분선
            sep_item = ListItem(Label("[cyan]─" * 28 + "[/]"))
            sep_item.disabled = True
            interface_list.append(sep_item)

            # 인터페이스 항목들
            if self._interfaces:
                prev_selected = self.selected_interface
                found_prev = False

                skip_prefixes = ('docker', 'veth', 'br-', 'virbr', 'vnet')
                filtered_interfaces = [
                    iface for iface in self._interfaces
                    if not iface.name.startswith(skip_prefixes)
                ]

                for iface in filtered_interfaces:
                    label_text = self._build_iface_label(iface, "normal")
                    item = ListItem(Label(label_text), classes=f"iface-{iface.name}")
                    self._menu_texts[f"iface-{iface.name}"] = iface.name
                    interface_list.append(item)

                    if iface.name == prev_selected:
                        found_prev = True

                if filtered_interfaces:
                    if not found_prev:
                        self.selected_interface = filtered_interfaces[0].name
            else:
                no_iface = ListItem(Label("[bright_black]  No interfaces found[/]"))
                no_iface.disabled = True
                interface_list.append(no_iface)

            interface_list.focus()
            self._update_menu_styles()

        except Exception as e:
            self.log.error(f"Failed to load interfaces: {e}")
            import traceback
            self.log.error(traceback.format_exc())
            self.app.notify(f"Error: {e}", severity="error")

    @on(ListView.Selected)
    def on_interface_selected(self, event: ListView.Selected) -> None:
        if event.item.has_class("menu-back"):
            self.app.pop_screen()
            return

        for cls in event.item.classes:
            if cls.startswith("iface-"):
                interface_name = cls.replace("iface-", "")
                self.selected_interface = interface_name
                self._update_menu_styles()
                self.action_configure()  # 단일 Enter로 바로 모달 열기
                return

    @on(ListView.Highlighted)
    def handle_menu_highlight(self, event: ListView.Highlighted) -> None:
        try:
            interface_list = self.query_one("#interface-list", ListView)

            for item in interface_list.children:
                if isinstance(item, ListItem):
                    if item.disabled:
                        continue

                    menu_key = None
                    is_back = item.has_class("menu-back")

                    if is_back:
                        menu_key = "menu-back"
                    else:
                        for cls in item.classes:
                            if cls.startswith("iface-"):
                                menu_key = cls
                                break

                    if not menu_key:
                        continue

                    label = item.query_one(Label)
                    text = self._menu_texts.get(menu_key, "")

                    if not text:
                        continue

                    if item == event.item:
                        if is_back:
                            label.update(f"[reverse] ▸ {text} [/]")
                        else:
                            iface = self._get_interface_by_class(menu_key)
                            if iface:
                                label.update(self._build_iface_label(iface, "highlighted"))
                            else:
                                label.update(f"[reverse] ▸ {text} [/]")
                    elif self._is_selected_interface_class(menu_key):
                        if is_back:
                            label.update(f"[cyan]▸ {text}[/]")
                        else:
                            iface = self._get_interface_by_class(menu_key)
                            if iface:
                                label.update(self._build_iface_label(iface, "selected"))
                            else:
                                label.update(f"[cyan]▸ {text}[/]")
                    else:
                        if is_back:
                            label.update(f"  {text}")
                        else:
                            iface = self._get_interface_by_class(menu_key)
                            if iface:
                                label.update(self._build_iface_label(iface, "normal"))
                            else:
                                label.update(f"  {text}")

            # 현재 하이라이트된 인터페이스 추적 + 우측 패널 즉시 미리보기
            hovered_name = ""
            if event.item:
                for cls in event.item.classes:
                    if cls.startswith("iface-"):
                        hovered_name = cls.replace("iface-", "")
                        break
            self._hovered_interface = hovered_name
            if hovered_name:
                self._update_details_for(hovered_name)

        except Exception as e:
            self.log.error(f"Highlight error: {e}")

    def _get_interface_by_class(self, class_name: str):
        """클래스명으로 인터페이스 찾기."""
        if not class_name.startswith("iface-"):
            return None
        iface_name = class_name.replace("iface-", "")
        for iface in self._interfaces:
            if iface.name == iface_name:
                return iface
        return None

    def _get_interface_by_id(self, item_id: str):
        """ID로 인터페이스 찾기 (하위 호환성)."""
        return self._get_interface_by_class(item_id)

    def _is_selected_interface_class(self, class_name: str) -> bool:
        """클래스명이 선택된 인터페이스인지 확인."""
        if not self.selected_interface:
            return False
        expected_class = f"iface-{self.selected_interface}"
        return class_name == expected_class

    def _is_selected_interface(self, menu_id: str) -> bool:
        """ID가 선택된 인터페이스인지 확인 (하위 호환성)."""
        return self._is_selected_interface_class(menu_id)

    def _update_menu_styles(self) -> None:
        try:
            interface_list = self.query_one("#interface-list", ListView)

            for item in interface_list.children:
                if isinstance(item, ListItem):
                    if item.disabled:
                        continue

                    menu_key = None
                    is_back = item.has_class("menu-back")

                    if is_back:
                        menu_key = "menu-back"
                    else:
                        for cls in item.classes:
                            if cls.startswith("iface-"):
                                menu_key = cls
                                break

                    if not menu_key:
                        continue

                    label = item.query_one(Label)
                    text = self._menu_texts.get(menu_key, "")

                    if not text:
                        continue

                    if self._is_selected_interface_class(menu_key):
                        iface = self._get_interface_by_class(menu_key)
                        if iface:
                            label.update(self._build_iface_label(iface, "selected"))
                        else:
                            label.update(f"[cyan]▸ {text}[/]")
                    else:
                        if is_back:
                            label.update(f"  {text}")
                        else:
                            iface = self._get_interface_by_class(menu_key)
                            if iface:
                                label.update(self._build_iface_label(iface, "normal"))
                            else:
                                label.update(f"  {text}")
        except Exception as e:
            self.log.error(f"Menu style update error: {e}")

    def _get_interface_details(self) -> str:
        """인터페이스 상세 정보를 가져옵니다."""
        if not self.selected_interface:
            return """[bold cyan]═══ Network Configuration ═══[/]

[yellow]Select an interface from the list[/]

[bright_black]Use arrow keys to navigate
Press Enter to configure[/]
"""

        try:
            iface = None
            if self.app.network_mgmt:
                iface = self.app.network_mgmt.get_interface(self.selected_interface)

            if not iface:
                return f"[red]Interface {self.selected_interface} not found[/]"

            status = iface.status if hasattr(iface, 'status') else 'UNKNOWN'
            status_color = self._get_status_color(status)

            # Promiscuous mode 상태 확인
            is_promisc = hasattr(iface, 'promisc') and iface.promisc
            promisc_status = "[magenta]Enabled[/]" if is_promisc else "[red]Disabled[/]"

            # Mirror port 상태 (PROMISC = 항상 mirror)
            if is_promisc:
                mirror_status = "[magenta]Configured[/]"
            else:
                mirror_status = "[bright_black]Not configured[/]"

            # DHCP 상태 감지 (netplan)
            dhcp_status = "[bright_black]Disabled[/]"
            dns_info = "N/A"
            try:
                np_result = subprocess.run(
                    ["/usr/sbin/netplan", "get", f"ethernets.{self.selected_interface}"],
                    capture_output=True, text=True, timeout=5
                )
                if np_result.returncode == 0 and np_result.stdout.strip():
                    import yaml
                    np_conf = yaml.safe_load(np_result.stdout) or {}
                    d4 = np_conf.get('dhcp4', False) is True
                    d6 = np_conf.get('dhcp6', False) is True
                    if d4 and d6:
                        dhcp_status = "[green]IPv4 + IPv6[/]"
                    elif d4:
                        dhcp_status = "[green]IPv4[/]"
                    elif d6:
                        dhcp_status = "[green]IPv6[/]"

                    ns = np_conf.get('nameservers', {})
                    if isinstance(ns, dict):
                        addrs = ns.get('addresses', [])
                        if addrs:
                            dns_info = ", ".join(str(a) for a in addrs)
            except Exception:
                pass

            # PROMISC(mirror) 인터페이스는 IP 표시 대신 안내 문구
            if is_promisc:
                ip_display   = "[magenta]— (mirror port)[/]"
                mask_display = "[bright_black]—[/]"
                gw_display   = "[bright_black]—[/]"
                dns_display  = "[bright_black]—[/]"
                dhcp_display = "[bright_black]—[/]"
            else:
                ip_display   = getattr(iface, 'ip', 'No IP')
                mask_display = getattr(iface, 'netmask', 'N/A')
                gw_display   = getattr(iface, 'gateway', 'N/A')
                dns_display  = dns_info
                dhcp_display = dhcp_status

            content = f"""[bold cyan]═══ {self.selected_interface} Details ═══[/]

[yellow]Basic Information:[/]
  [white]Interface   :[/] {iface.name}
  [white]Status      :[/] [{status_color}]{status}[/]
  [white]MAC Address :[/] {getattr(iface, 'mac', 'N/A')}
  [white]MTU         :[/] {getattr(iface, 'mtu', 'N/A')}

[yellow]IP Configuration:[/]
  [white]IP Address  :[/] {ip_display}
  [white]Netmask     :[/] {mask_display}
  [white]Gateway     :[/] {gw_display}
  [white]DNS Server  :[/] {dns_display}
  [white]DHCP        :[/] {dhcp_display}

[yellow]Link Information:[/]
  [white]Speed       :[/] {getattr(iface, 'speed', 'Unknown')}
  [white]Duplex      :[/] {getattr(iface, 'duplex', 'Unknown')}
  [white]Driver      :[/] {getattr(iface, 'driver', 'Unknown')}

[yellow]Advanced Settings:[/]
  [white]Promiscuous :[/] {promisc_status}
  [white]Mirror Port :[/] {mirror_status}

[yellow]Traffic Statistics:[/]
  [white]RX Bytes    :[/] {self._format_bytes(getattr(iface, 'rx_bytes', 0))}
  [white]TX Bytes    :[/] {self._format_bytes(getattr(iface, 'tx_bytes', 0))}
  [white]RX Packets  :[/] {getattr(iface, 'rx_packets', 0):,}
  [white]TX Packets  :[/] {getattr(iface, 'tx_packets', 0):,}

[cyan]────────────────────────────────────────[/]
[white]Press [yellow]Enter[/] to configure (Mirror/DHCP/Static/Disable)[/]
[white]Press [yellow]U[/] to toggle Link Up/Down[/]
[white]Press [yellow]F5[/] to refresh, [yellow]ESC[/] to return[/]
"""
            return content

        except Exception as e:
            self.log.error(f"Failed to get interface details: {e}")
            return f"[red]Error: {e}[/]"

    def _update_details_for(self, iface_name: str) -> None:
        """특정 인터페이스 정보를 오른쪽 패널에 표시 (캐시 사용, netplan 호출 없음)."""
        try:
            iface = None
            if self.app.network_mgmt:
                iface = self.app.network_mgmt.get_interface(iface_name)

            if not iface:
                return

            status = getattr(iface, 'status', 'UNKNOWN')
            status_color = self._get_status_color(status)

            is_promisc = getattr(iface, 'promisc', False)

            # PROMISC = 항상 mirror로 표시
            if is_promisc:
                mirror_status = "[magenta]Configured[/]"
                promisc_status = "[magenta]Enabled[/]"
            else:
                mirror_status = "[bright_black]Not configured[/]"
                promisc_status = "[red]Disabled[/]"

            # PROMISC(mirror)는 IP 대신 안내 문구
            if is_promisc:
                ip_display   = "[magenta]— (mirror port)[/]"
                mask_display = "[bright_black]—[/]"
                gw_display   = "[bright_black]—[/]"
            else:
                ip_display   = getattr(iface, 'ip', 'No IP')
                mask_display = getattr(iface, 'netmask', 'N/A')
                gw_display   = getattr(iface, 'gateway', 'N/A')

            content = f"""[bold cyan]═══ {iface_name} Details ═══[/]

[yellow]Basic Information:[/]
  [white]Interface   :[/] {iface.name}
  [white]Status      :[/] [{status_color}]{status}[/]
  [white]MAC Address :[/] {getattr(iface, 'mac', 'N/A')}
  [white]MTU         :[/] {getattr(iface, 'mtu', 'N/A')}

[yellow]IP Configuration:[/]
  [white]IP Address  :[/] {ip_display}
  [white]Netmask     :[/] {mask_display}
  [white]Gateway     :[/] {gw_display}
  [white]DNS Server  :[/] [bright_black]N/A (cached)[/]
  [white]DHCP        :[/] [bright_black]N/A (cached)[/]

[yellow]Link Information:[/]
  [white]Speed       :[/] {getattr(iface, 'speed', 'Unknown')}
  [white]Duplex      :[/] {getattr(iface, 'duplex', 'Unknown')}
  [white]Driver      :[/] {getattr(iface, 'driver', 'Unknown')}

[yellow]Advanced Settings:[/]
  [white]Promiscuous :[/] {promisc_status}
  [white]Mirror Port :[/] {mirror_status}

[yellow]Traffic Statistics:[/]
  [white]RX Bytes    :[/] {self._format_bytes(getattr(iface, 'rx_bytes', 0))}
  [white]TX Bytes    :[/] {self._format_bytes(getattr(iface, 'tx_bytes', 0))}
  [white]RX Packets  :[/] {getattr(iface, 'rx_packets', 0):,}
  [white]TX Packets  :[/] {getattr(iface, 'tx_packets', 0):,}

[cyan]────────────────────────────────────────[/]
[white]Press [yellow]Enter[/] to configure (Mirror/DHCP/Static/Disable)[/]
[white]Press [yellow]U[/] to toggle Link Up/Down[/]
[white]Press [yellow]F5[/] to refresh, [yellow]ESC[/] to return[/]
"""
            try:
                self.query_one("#content-title", Static).update(iface_name)
            except Exception:
                pass
            details_widget = self.query_one("#interface-details", Static)
            details_widget.update(content)
        except Exception as e:
            self.log.error(f"Details preview failed: {e}")

    def _format_bytes(self, bytes_val: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} PB"

    def _update_details(self) -> None:
        try:
            try:
                title = self.selected_interface or "Network Management"
                self.query_one("#content-title", Static).update(title)
            except Exception:
                pass
            details_widget = self.query_one("#interface-details", Static)
            details_widget.update(self._get_interface_details())
        except Exception as e:
            self.log.error(f"Details update failed: {e}")

    def _update_stats(self) -> None:
        """인터페이스 통계 비동기 갱신.

        현재 화면에 표시 중인 인터페이스(hover 우선, 없으면 selected)를 갱신.
        갱신 완료 후 표시 인터페이스가 변경됐으면(stale) 업데이트 무시.
        """
        # hover 중인 인터페이스 우선, 없으면 selected
        iface_name = self._hovered_interface or self.selected_interface
        if not iface_name or not self.app.network_mgmt:
            return

        def _worker():
            try:
                self.app.network_mgmt.refresh_interface(iface_name)
                self.app.call_from_thread(self._apply_stats_update, iface_name)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_stats_update(self, refreshed_iface: str) -> None:
        """통계 갱신 결과 적용. stale guard: 갱신 중 화면이 바뀌었으면 무시."""
        current = self._hovered_interface or self.selected_interface
        if refreshed_iface != current:
            return  # 갱신 완료 전 다른 인터페이스로 이동 → 무시
        if self._hovered_interface:
            self._update_details_for(self._hovered_interface)
        else:
            self._update_details()

    # ═══════════════════════════════════════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════════════════════════════════════

    def action_go_back(self) -> None:
        """ESC: 우측 패널 포커스 → 메뉴 복귀, 메뉴 포커스 → 이전 화면."""
        try:
            iface_list = self.query_one("#interface-list", ListView)
            if iface_list.has_focus:
                self.app.pop_screen()
            else:
                iface_list.focus()
        except Exception:
            self.app.pop_screen()

    def action_refresh(self) -> None:
        self._update_details()
        self.app.notify("Interface info refreshed")

    def action_rescan(self) -> None:
        try:
            self._load_interfaces()
            self._update_details()
            self.app.notify("Network interfaces rescanned", title="Rescan Complete")
        except Exception as e:
            self.app.notify(f"Rescan failed: {e}", severity="error")

    def action_configure(self) -> None:
        """Enter: 설정 다이얼로그를 엽니다."""
        if not self.selected_interface:
            self.app.notify("Please select an interface first", severity="warning")
            return

        # 현재 설정 가져오기
        current_ip = ""
        current_netmask = "255.255.255.0"
        current_gateway = ""
        current_dns = ""
        is_mirror = False
        is_promisc = False
        is_dhcp4 = False
        is_dhcp6 = False
        interface_status = "UNKNOWN"

        if self.app.network_mgmt:
            iface = self.app.network_mgmt.get_interface(self.selected_interface)
            if iface:
                interface_status = getattr(iface, 'status', 'UNKNOWN')
                ip_raw = getattr(iface, 'ip', 'No IP') or 'No IP'
                has_ip = ip_raw and ip_raw != "No IP"
                current_ip = ip_raw if has_ip else ""

                current_netmask = getattr(iface, 'netmask', '255.255.255.0') or "255.255.255.0"
                current_gateway = getattr(iface, 'gateway', '') or ""

                is_promisc = hasattr(iface, 'promisc') and iface.promisc
                # PROMISC = 항상 mirror 모드로 초기 선택 (IP가 남아있어도 mirror로 처리)
                is_mirror = is_promisc
                if is_mirror:
                    current_ip = ""  # mirror port에 IP 표시 안 함

        # netplan에서 DHCP 상태 및 DNS 감지
        try:
            result = subprocess.run(
                ["/usr/sbin/netplan", "get", f"ethernets.{self.selected_interface}"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                import yaml
                np_conf = yaml.safe_load(result.stdout) or {}
                is_dhcp4 = np_conf.get('dhcp4', False) is True
                is_dhcp6 = np_conf.get('dhcp6', False) is True

                ns = np_conf.get('nameservers', {})
                if isinstance(ns, dict):
                    addrs = ns.get('addresses', [])
                    if addrs:
                        current_dns = ", ".join(str(a) for a in addrs)

                if not current_gateway:
                    routes = np_conf.get('routes', [])
                    for r in routes:
                        if isinstance(r, dict) and r.get('to') in ('default', '0.0.0.0/0'):
                            current_gateway = r.get('via', '')
                            break
        except Exception:
            pass

        def handle_config(config: Optional[dict]) -> None:
            if config is None:
                return
            self.set_timer(0.1, lambda: self._apply_network_config(config))

        self.app.push_screen(
            NetworkConfigModal(
                interface_name=self.selected_interface,
                current_ip=current_ip,
                current_netmask=current_netmask,
                current_gateway=current_gateway,
                current_dns=current_dns,
                is_mirror=is_mirror,
                is_promisc=is_promisc,
                is_dhcp4=is_dhcp4,
                is_dhcp6=is_dhcp6,
                interface_status=interface_status,
            ),
            handle_config
        )

    def action_toggle_link(self) -> None:
        """U키: 선택된 인터페이스의 Link Up/Down 토글."""
        if not self.selected_interface and not self._hovered_interface:
            self.app.notify("Please select an interface first", severity="warning")
            return

        iface_name = self._hovered_interface or self.selected_interface

        try:
            # 현재 링크 상태 확인
            result = subprocess.run(
                ["/usr/sbin/ip", "link", "show", iface_name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                self.app.notify(
                    f"Failed to query link state: {iface_name}",
                    severity="error"
                )
                return

            output = result.stdout
            # "UP" 플래그 존재 여부로 관리적 상태 판단
            is_up = f"<" in output and "UP" in output.split("<", 1)[1].split(">", 1)[0]

            if is_up:
                action = "down"
            else:
                action = "up"

            set_result = subprocess.run(
                ["sudo", "/usr/sbin/ip", "link", "set", iface_name, action],
                capture_output=True, text=True, timeout=10
            )

            if set_result.returncode == 0:
                self.app.notify(
                    f"{iface_name}: link set {action}",
                    title="Link Toggled"
                )
                self.log.info(f"action_toggle_link: {iface_name} -> {action}")
            else:
                err = set_result.stderr.strip() or "unknown error"
                self.app.notify(
                    f"Failed to set {iface_name} {action}: {err}",
                    severity="error"
                )
                self.log.error(f"action_toggle_link failed: {iface_name} {action}: {err}")
                return

            # 상태 갱신
            if self.app.network_mgmt:
                self.app.network_mgmt.refresh_interface(iface_name)
            self._update_details()
            self._update_menu_styles()

        except subprocess.TimeoutExpired:
            self.log.error(f"action_toggle_link timeout: {iface_name}")
            self.app.notify(f"Timeout while toggling {iface_name}", severity="error")
        except Exception as e:
            self.log.error(f"action_toggle_link error: {e}")
            self.app.notify(f"Error: {e}", severity="error")

    def _apply_network_config(self, config: dict) -> None:
        """네트워크 설정을 적용합니다."""
        try:
            interface = config.get("interface")

            mode = config.get("mode", "")
            is_mirror = config.get("is_mirror", False)

            if is_mirror or mode == "mirror":
                # 1. netplan에서 주소/DHCP 완전 제거 (재부팅 후에도 IP 없이 유지)
                self._apply_disable_config(interface)
                # 2. promisc 설정
                success = self._set_promiscuous_mode_sync(interface, True)
                if success:
                    # 3. promisc 재부팅 영속성 (systemd oneshot 서비스)
                    try:
                        from network_management.network_config import NetworkConfig
                        NetworkConfig().set_promisc_persistent(interface, True)
                    except Exception as e:
                        self.log.warning(f"promisc persist failed: {e}")
                    # 4. 즉시 IP flush (커널 레벨)
                    self._remove_ip_config(interface)
                    self.app.notify(
                        f"Mirror port configured on {interface}. Press F8 to refresh.",
                        title="Mirror Port"
                    )
                else:
                    self.app.notify(
                        f"Failed to configure mirror port on {interface}",
                        severity="error"
                    )
                return

            if mode == "dhcp":
                # mirror에서 전환 시 promisc 영속성 서비스 제거
                self._set_promiscuous_mode_sync(interface, False)
                try:
                    from network_management.network_config import NetworkConfig
                    NetworkConfig().set_promisc_persistent(interface, False)
                except Exception as e:
                    self.log.warning(f"promisc persist removal failed: {e}")
                dhcp4 = config.get("dhcp4", True)
                dhcp6 = config.get("dhcp6", False)
                success = self._apply_dhcp_config(interface, dhcp4, dhcp6)
                if success:
                    ver = "IPv4" if dhcp4 else "IPv6"
                    self.app.notify(
                        f"DHCP ({ver}) enabled on {interface}. Press F8 to refresh.",
                        title="DHCP Configured"
                    )
                else:
                    self.app.notify(
                        f"Failed to configure DHCP on {interface}",
                        severity="error"
                    )
                return

            if mode == "disable":
                self._set_promiscuous_mode_sync(interface, False)
                try:
                    from network_management.network_config import NetworkConfig
                    NetworkConfig().set_promisc_persistent(interface, False)
                except Exception as e:
                    self.log.warning(f"promisc persist removal failed: {e}")
                success = self._apply_disable_config(interface)
                if success:
                    self.app.notify(
                        f"IP configuration removed from {interface}. Press F8 to refresh.",
                        title="Configuration Cleared"
                    )
                else:
                    self.app.notify(
                        f"Failed to clear configuration on {interface}",
                        severity="error"
                    )
                return

            # Static 모드
            self._set_promiscuous_mode_sync(interface, False)
            try:
                from network_management.network_config import NetworkConfig
                NetworkConfig().set_promisc_persistent(interface, False)
            except Exception as e:
                self.log.warning(f"promisc persist removal failed: {e}")

            ip = config.get("ip")
            netmask = config.get("netmask")
            gateway = config.get("gateway")
            dns = config.get("dns")
            is_ipv6 = config.get("ipv6", False)

            if ip:
                dns_list = None
                if dns:
                    dns_list = [d.strip() for d in dns.split(",")]

                self.log.info(f"Applying static config to {interface}: {ip}/{netmask} gw {gateway} ipv6={is_ipv6}")

                if is_ipv6:
                    success = self._apply_static_ipv6(interface, ip, netmask, gateway, dns_list)
                else:
                    if self.app.network_mgmt:
                        success = self.app.network_mgmt.configure_static_ip(
                            interface, ip, netmask, gateway, dns_list
                        )
                    else:
                        success = False

                if success:
                    self.app.notify(
                        f"IP {ip} configured on {interface}. Press F8 to refresh.",
                        title="Configuration Applied"
                    )
                else:
                    self.app.notify(
                        "Failed to apply IP configuration",
                        severity="error"
                    )

        except Exception as e:
            self.log.error(f"Configuration failed: {e}")
            self.app.notify(f"Error: {e}", severity="error")

    def _apply_dhcp_config(self, interface: str, dhcp4: bool, dhcp6: bool) -> bool:
        """DHCP 설정 적용 (NetworkConfig YAML 직접 수정)."""
        try:
            from network_management.network_config import NetworkConfig
            return NetworkConfig().set_dhcp(interface, dhcp4, dhcp6)
        except Exception as e:
            self.log.error(f"DHCP config failed: {e}")
            return False

    def _apply_static_ipv6(self, interface: str, ip: str, prefix: str, gateway: str, dns_list: list = None) -> bool:
        """IPv6 Static IP 설정 (NetworkConfig YAML 직접 수정)."""
        try:
            from network_management.network_config import NetworkConfig
            return NetworkConfig().set_static_ip(interface, ip, prefix, gateway, dns_list)
        except Exception as e:
            self.log.error(f"IPv6 static config failed: {e}")
            return False

    def _apply_disable_config(self, interface: str) -> bool:
        """IP 설정 완전 제거 (NetworkConfig YAML 직접 수정)."""
        try:
            from network_management.network_config import NetworkConfig
            return NetworkConfig().remove_ip_config(interface)
        except Exception as e:
            self.log.error(f"Disable config failed: {e}")
            return False

    def _remove_ip_config(self, interface: str) -> bool:
        """인터페이스의 IP 설정을 제거합니다 (ip 명령 사용 - 빠름)."""
        try:
            result = subprocess.run(
                ["/usr/sbin/ip", "addr", "flush", "dev", interface],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            self.log.error(f"Failed to remove IP config: {e}")
            return False

    def _set_promiscuous_mode_sync(self, interface: str, enable: bool) -> bool:
        """Promiscuous mode를 설정합니다."""
        try:
            action = "on" if enable else "off"
            result = subprocess.run(
                ["sudo", "/usr/sbin/ip", "link", "set", interface, "promisc", action],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            self.log.error(f"Failed to set promisc mode: {e}")
            return False

    def _deferred_refresh(self) -> None:
        """인터페이스 정보를 갱신합니다."""
        try:
            if self.app.network_mgmt:
                self._interfaces = self.app.network_mgmt.interfaces

            self._update_menu_from_cache()
            self._update_details()
        except Exception as e:
            self.log.error(f"Deferred refresh failed: {e}")

    def _update_menu_from_cache(self) -> None:
        """캐시된 인터페이스 정보로 메뉴만 갱신 (discover 없이)."""
        try:
            if self.app.network_mgmt:
                self._interfaces = self.app.network_mgmt.interfaces

            interface_list = self.query_one("#interface-list", ListView)

            while interface_list.children:
                interface_list.children[0].remove()

            self._menu_texts = {}

            back_item = ListItem(Label("  ← Back"), classes="menu-back")
            self._menu_texts["menu-back"] = "← Back"
            interface_list.append(back_item)

            sep_item = ListItem(Label("[cyan]─" * 28 + "[/]"))
            sep_item.disabled = True
            interface_list.append(sep_item)

            if self._interfaces:
                prev_selected = self.selected_interface
                found_prev = False

                skip_prefixes = ('docker', 'veth', 'br-', 'virbr', 'vnet')
                filtered_interfaces = [
                    iface for iface in self._interfaces
                    if not iface.name.startswith(skip_prefixes)
                ]

                for iface in filtered_interfaces:
                    label_text = self._build_iface_label(iface, "normal")
                    item = ListItem(Label(label_text), classes=f"iface-{iface.name}")
                    self._menu_texts[f"iface-{iface.name}"] = iface.name
                    interface_list.append(item)

                    if iface.name == prev_selected:
                        found_prev = True

                if filtered_interfaces and not found_prev:
                    self.selected_interface = filtered_interfaces[0].name
            else:
                no_iface = ListItem(Label("[bright_black]  No interfaces found[/]"))
                no_iface.disabled = True
                interface_list.append(no_iface)

            interface_list.focus()
            self._update_menu_styles()

        except Exception as e:
            self.log.error(f"Menu refresh failed: {e}")
