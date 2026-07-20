"""
Firewall Management Screen (UFW)

UFW firewall management - nmtui-style compact TUI.
Tabs: STATUS / POLICY / RULES / ACL / MANAGEMENT / Quick Profile
"""

import re
import threading
from rich.markup import escape as markup_escape

from textual.app import ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import Footer, Static, ListView, ListItem, Label, Input, Button
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual import on

from app.widgets import CustomHeader
from modules.firewall_manager import FirewallManager


# ── Tab definitions ────────────────────────────────────────────────────────────

TAB_ITEMS = [
    ("back",       " <- Back"),
    ("sep0",       ""),
    ("status",     " STATUS"),
    ("policy",     " POLICY"),
    ("rules",      " RULES"),
    ("acl",        " ACL"),
    ("management", " MANAGEMENT"),
    ("sep1",       ""),
    ("profile",    " Quick Profile"),
]

NON_SELECTABLE_TABS = {"sep0", "sep1"}

TAB_TITLES = {
    "status":     "Firewall > Status",
    "policy":     "Firewall > Default Policy",
    "rules":      "Firewall > Port Rules",
    "acl":        "Firewall > ACL (IP-based)",
    "management": "Firewall > Rule Management",
    "profile":    "Firewall > Quick Profile",
}

MNX_PROFILE_PORTS = [
    ("22",   "tcp", "SSH"),
    ("5601", "tcp", "Kibana"),
    ("9200", "tcp", "Elasticsearch"),
    ("5044", "tcp", "Logstash Beats"),
    ("9092", "tcp", "Kafka"),
    ("2181", "tcp", "Zookeeper"),
    ("9500", "tcp", "MNX DPI"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Confirm Modal
# ═══════════════════════════════════════════════════════════════════════════════

class ConfirmModal(ModalScreen):
    """Yes / No confirmation dialog."""

    CSS = """
    ConfirmModal {
        align: center middle;
        background: rgba(0,0,0,0.85);
    }
    #dlg {
        width: 60;
        height: auto;
        border: solid #ff5f5f;
        background: #1a1a1a;
        padding: 1 2;
    }
    #dlg-msg  { width: 100%; color: white; margin-bottom: 1; }
    #dlg-btns { width: 100%; align: center middle; }
    #btn-yes {
        width: 12; height: 1;
        background: #8b0000; color: white;
        border: solid #ff5f5f; margin-right: 2;
    }
    #btn-yes:hover { background: #ff5f5f; color: black; }
    #btn-no {
        width: 12; height: 1;
        background: #2a2a2a; color: white;
        border: solid #aaaaaa;
    }
    #btn-no:hover { background: #444444; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Container(id="dlg"):
            yield Static(self._message, id="dlg-msg")
            with Horizontal(id="dlg-btns"):
                yield Button("Yes", id="btn-yes")
                yield Button("No",  id="btn-no")

    @on(Button.Pressed, "#btn-yes")
    def _yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-no")
    def _no(self) -> None:
        self.dismiss(False)


# ═══════════════════════════════════════════════════════════════════════════════
# Result Modal
# ═══════════════════════════════════════════════════════════════════════════════

class ResultModal(ModalScreen):
    """Apply result popup."""

    CSS = """
    ResultModal {
        align: center middle;
        background: rgba(0,0,0,0.85);
    }
    #res-dlg {
        width: 76;
        height: auto;
        max-height: 28;
        border: solid #5fd7d7;
        background: #1a1a1a;
        padding: 1 2;
    }
    #res-title { width: 100%; height: 1; color: #5fd7d7; text-style: bold; }
    #res-body  {
        width: 100%; height: auto; max-height: 20;
        color: white; margin-top: 1; margin-bottom: 1;
    }
    #res-btns  { width: 100%; align: center middle; }
    #btn-ok {
        width: 12; height: 1;
        background: #006666; color: white;
        border: solid #5fd7d7;
    }
    #btn-ok:hover { background: #5fd7d7; color: black; }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body  = body

    def compose(self) -> ComposeResult:
        with Container(id="res-dlg"):
            yield Static(self._title, id="res-title")
            yield Static(self._body,  id="res-body")
            with Horizontal(id="res-btns"):
                yield Button("OK", id="btn-ok")

    @on(Button.Pressed, "#btn-ok")
    def _ok(self) -> None:
        self.dismiss()


# ═══════════════════════════════════════════════════════════════════════════════
# Firewall Screen
# ═══════════════════════════════════════════════════════════════════════════════

class FirewallScreen(Screen):
    """UFW Firewall management screen."""

    CSS = """
    FirewallScreen { background: #0c0c0c; }

    /* ── Layout ── */
    #main-container {
        width: 100%; height: 1fr;
        layout: horizontal;
    }
    #left-panel {
        width: 18;
        height: 100%;
        background: #0c0c0c;
        border-right: solid #5fd7d7;
    }
    #fw-title {
        width: 100%; height: 1;
        background: #1a3333; color: #5fd7d7;
        text-style: bold; padding: 0 1;
    }
    #fw-badge {
        width: 100%; height: 1;
        background: #0c0c0c; padding: 0 1;
    }
    #tab-menu {
        width: 100%; height: 1fr;
        background: #0c0c0c;
        border: none; padding: 0;
    }
    #tab-menu > ListItem {
        background: #0c0c0c; color: #aaaaaa;
        height: 1; padding: 0 1;
    }
    #tab-menu > ListItem.--highlight {
        background: #5fd7d7; color: black; text-style: bold;
    }

    /* ── Right panel ── */
    #right-panel {
        width: 1fr; height: 100%;
        background: #0c0c0c; layout: vertical;
    }
    #tab-title {
        width: 100%; height: 1;
        background: #1a1a1a; color: #5fd7d7;
        text-style: bold; padding: 0 1;
    }
    #tab-content {
        width: 100%; height: 1fr;
        background: #0c0c0c; padding: 0 1;
    }
    #status-bar {
        width: 100%; height: 1;
        background: #111111; color: #888888; padding: 0 1;
    }
    #pending-bar {
        width: 100%; height: auto;
        min-height: 1; max-height: 4;
        background: #0d1a1a; color: #aaaaaa;
        padding: 0 1; border-top: solid #222222;
    }
    #action-row {
        width: 100%; height: 1;
        layout: horizontal; align: left middle;
        background: #111111; padding: 0 1;
    }

    /* ── Action row buttons ── */
    #btn-apply {
        width: 16; height: 1;
        background: #006666; color: white;
        border: none; margin-right: 1;
    }
    #btn-apply:hover, #btn-apply:focus {
        background: #5fd7d7; color: black; text-style: bold;
    }
    #btn-clear {
        width: 16; height: 1;
        background: #2a2a2a; color: #aaaaaa;
        border: none; margin-right: 1;
    }
    #btn-clear:hover { background: #444444; color: white; }
    #btn-refresh {
        width: 16; height: 1;
        background: #2a2a2a; color: #aaaaaa;
        border: none;
    }
    #btn-refresh:hover { background: #444444; color: white; }

    /* ── Form ── */
    .hdr {
        width: 100%; height: 1;
        color: #5fd7d7; text-style: bold;
        margin-top: 1;
    }
    .rule-table {
        width: 100%; color: white;
    }
    .sep {
        width: 100%; height: 1;
        color: #2a2a2a;
    }
    .form-row {
        width: 100%; height: 1;
        layout: horizontal; margin-bottom: 0;
    }
    .form-lbl {
        width: 12; height: 1;
        color: #888888; content-align: left middle;
    }
    .form-inp {
        width: 1fr; height: 1;
        color: white; background: #0c0c0c;
        border-top: none; border-right: none;
        border-bottom: solid #5fd7d7; border-left: none;
        padding: 0 1;
    }
    .form-inp:focus {
        border-bottom: solid #87ffff; background: #0c0c0c;
    }
    .radio-row {
        width: 100%; height: 1;
        layout: horizontal; margin-bottom: 0;
    }
    .radio-lbl {
        width: 12; height: 1;
        color: #888888; content-align: left middle;
    }
    .rb {
        width: auto; min-width: 8; height: 1;
        border: none; background: #1e1e1e;
        color: #666666; padding: 0 1; margin-right: 1;
    }
    .rb:hover { color: white; background: #2a2a2a; }
    .rb-sel {
        width: auto; min-width: 8; height: 1;
        border: none; background: #003333;
        color: #5fd7d7; padding: 0 1; margin-right: 1;
    }
    .act-btn {
        width: auto; min-width: 14; height: 1;
        background: #006666; color: white;
        border: none; margin-right: 1; margin-top: 1;
    }
    .act-btn:hover { background: #5fd7d7; color: black; }
    .del-btn {
        width: auto; min-width: 14; height: 1;
        background: #550000; color: white;
        border: none; margin-right: 1; margin-top: 1;
    }
    .del-btn:hover { background: #ff5f5f; color: black; }
    .wrn-btn {
        width: auto; min-width: 14; height: 1;
        background: #553300; color: white;
        border: none; margin-right: 1; margin-top: 1;
    }
    .wrn-btn:hover { background: #ffaf00; color: black; }
    """

    BINDINGS = [
        Binding("f1", "refresh_status", "F1:Refresh"),
        Binding("f2", "do_apply",       "F2:Apply"),
        Binding("escape", "go_back",    "Esc:Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._mgr   = FirewallManager()
        self._tab   = "status"
        self._pending: list = []
        self._status: dict  = {}
        self._rules_num: list = []
        self._menu_map: dict  = {}
        self._pol_in  = "deny"
        self._pol_out = "allow"
        self._rule_act  = "allow"
        self._rule_proto = "tcp"
        self._acl_act   = "allow"
        self._acl_proto = "tcp"

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield CustomHeader()
        with Container(id="main-container"):
            with Vertical(id="left-panel"):
                yield Static(" UFW", id="fw-title")
                yield Static("", id="fw-badge")
                yield ListView(id="tab-menu")
            with Vertical(id="right-panel"):
                yield Static(" Firewall", id="tab-title")
                with ScrollableContainer(id="tab-content"):
                    yield Static(
                        "[bright_black]Select a tab from the left[/]",
                        id="tab-placeholder",
                    )
                yield Static("", id="status-bar")
                yield Static("[bright_black]No pending.[/]", id="pending-bar")
                with Horizontal(id="action-row"):
                    yield Button("[F2] Apply",   id="btn-apply")
                    yield Button("Clear",        id="btn-clear")
                    yield Button("[F1] Refresh", id="btn-refresh")
        yield Footer()

    def on_mount(self) -> None:
        self._build_menu()
        self.set_timer(0.1, self._init_view)
        self._bg_refresh()

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menu = self.query_one("#tab-menu", ListView)
        for key, label in TAB_ITEMS:
            item = ListItem(Label(label), id=f"ti-{key}")
            self._menu_map[f"ti-{key}"] = (key, label)
            if key in NON_SELECTABLE_TABS:
                item.disabled = True
            menu.append(item)

    def _init_view(self) -> None:
        try:
            menu = self.query_one("#tab-menu", ListView)
            menu.focus()
            menu.index = 0
        except Exception:
            pass
        self._show_tab("status")

    @on(ListView.Selected)
    def on_tab_selected(self, event: ListView.Selected) -> None:
        lv = getattr(event, "list_view", None)
        if not lv or lv.id != "tab-menu":
            return
        item = event.item
        if item is None or item.id is None:
            return
        key, _ = self._menu_map.get(item.id, ("", ""))
        if not key:
            return
        if key == "back":
            self.action_go_back()
        elif key not in NON_SELECTABLE_TABS:
            self._show_tab(key)

    @on(ListView.Highlighted)
    def on_tab_highlighted(self, event: ListView.Highlighted) -> None:
        lv = getattr(event, "list_view", None)
        if not lv or lv.id != "tab-menu":
            return
        if event.item is None:
            return
        try:
            menu = self.query_one("#tab-menu", ListView)
            for item in menu.children:
                if not isinstance(item, ListItem) or item.disabled:
                    continue
                lbl = item.query_one(Label)
                _, text = self._menu_map.get(item.id, ("", ""))
                lbl.update(f"[reverse]{text}[/]" if item == event.item else text)
        except Exception:
            pass

    # ── Background refresh ────────────────────────────────────────────────────

    def _bg_refresh(self) -> None:
        def _fetch():
            self._status   = self._mgr.get_status()
            self._rules_num = self._mgr.get_numbered_rules()
            self._pol_in   = self._status.get("incoming", "deny")
            self._pol_out  = self._status.get("outgoing", "allow")
            self.call_from_thread(self._update_badge)
            if self._tab in ("status", "management"):
                self.call_from_thread(self._show_tab, self._tab)
            err = self._status.get("error")
            if err:
                self.call_from_thread(self._set_status, f"[red]ufw error: {err}[/]")
            else:
                state = "ACTIVE" if self._status.get("active") else "INACTIVE"
                self.call_from_thread(self._set_status, f"[bright_black]Ready  UFW:{state}[/]")
        threading.Thread(target=_fetch, daemon=True).start()

    def _update_badge(self) -> None:
        active = self._status.get("active", False)
        badge = "[green]* ON[/]" if active else "[red]* OFF[/]"
        try:
            self.query_one("#fw-badge", Static).update(badge)
        except Exception:
            pass

    # ── Tab rendering ─────────────────────────────────────────────────────────

    def _show_tab(self, key: str) -> None:
        self._tab = key
        try:
            self.query_one("#tab-title", Static).update(
                f" {TAB_TITLES.get(key, key)}"
            )
        except Exception:
            pass
        {
            "status":     self._tab_status,
            "policy":     self._tab_policy,
            "rules":      self._tab_rules,
            "acl":        self._tab_acl,
            "management": self._tab_mgmt,
            "profile":    self._tab_profile,
        }.get(key, lambda: None)()

    def _clear(self) -> None:
        try:
            self.query_one("#tab-content").remove_children()
        except Exception:
            pass

    def _m(self, *widgets) -> None:
        try:
            c = self.query_one("#tab-content")
            for w in widgets:
                c.mount(w)
        except Exception:
            pass

    def _rb(self, label: str, btn_id: str, selected: bool) -> Button:
        mark = "*" if selected else " "
        cls  = "rb-sel" if selected else "rb"
        return Button(f"{mark} {label}", id=btn_id, classes=cls)

    # ── STATUS ────────────────────────────────────────────────────────────────

    def _tab_status(self) -> None:
        self._clear()
        s        = self._status
        active   = s.get("active", False)
        inc      = s.get("incoming", "deny").upper()
        out      = s.get("outgoing", "allow").upper()
        log_     = s.get("logging",  "off")
        err      = s.get("error")

        st_txt = "[green]ACTIVE[/]"   if active else "[red]INACTIVE[/]"
        ic_clr = "red"   if inc == "DENY"  else "green"
        oc_clr = "green" if out == "ALLOW" else "red"

        rules = s.get("rules", [])
        rule_lines = [
            "[bright_black] To               Act      From[/]",
            "[bright_black] ---------------  -------  ----------------[/]",
        ]
        for r in rules[:20]:
            to  = r.get("to",     "")[:15].ljust(15)
            act = r.get("action", "")
            frm = r.get("from",   "")[:16]
            c   = "green" if act == "ALLOW" else "red"
            rule_lines.append(
                f" {markup_escape(to)}  [{c}]{markup_escape(act):<7}[/{c}]  {markup_escape(frm)}"
            )
        if not rules:
            rule_lines.append(" [bright_black](no rules)[/]")

        self._m(
            Static(
                f" Status:  {st_txt}   "
                f"Incoming: [{ic_clr}]{inc}[/{ic_clr}]   "
                f"Outgoing: [{oc_clr}]{out}[/{oc_clr}]   "
                f"Log: {markup_escape(log_)}",
                classes="rule-table",
            ),
        )
        if err:
            self._m(Static(f" [red]Error: {markup_escape(err)}[/]"))

        self._m(
            Static("[bright_black] --- Rules ---[/]", classes="sep"),
            Static("\n".join(rule_lines), classes="rule-table"),
            Static("[bright_black] --- Actions ---[/]", classes="sep"),
        )

        if not self._mgr.is_available():
            self._m(Static(" [red]ufw not installed.[/]"))
            return

        log_on    = "off" not in log_.lower()
        log_lbl   = "Logging Off" if log_on  else "Logging On"
        log_cls   = "wrn-btn"     if log_on  else "act-btn"

        self._m(
            Horizontal(
                Button("Enable",       id="btn-enable",    classes="act-btn"),
                Button("Disable",      id="btn-disable",   classes="wrn-btn"),
                Button("Reset All",    id="btn-reset-all", classes="del-btn"),
                Button(log_lbl,        id="btn-logging",   classes=log_cls),
                Button("Log:Medium",   id="btn-log-med",   classes="act-btn"),
            ),
        )

    # ── POLICY ────────────────────────────────────────────────────────────────

    def _tab_policy(self) -> None:
        self._clear()
        s    = self._status
        ci   = s.get("incoming", "deny").upper()
        co   = s.get("outgoing", "allow").upper()
        ic   = "red"   if ci == "DENY"  else "green"
        oc   = "green" if co == "ALLOW" else "red"

        self._m(
            Static(
                f" Current:  Incoming=[{ic}]{ci}[/{ic}]   Outgoing=[{oc}]{co}[/{oc}]",
                classes="rule-table",
            ),
            Static("[bright_black] --- Incoming ---[/]", classes="sep"),
            Horizontal(
                Static("Incoming", classes="radio-lbl"),
                self._rb("DENY",   "btn-pi-deny",   self._pol_in == "deny"),
                self._rb("ALLOW",  "btn-pi-allow",  self._pol_in == "allow"),
                self._rb("REJECT", "btn-pi-reject", self._pol_in == "reject"),
                classes="radio-row",
            ),
            Static("[bright_black] --- Outgoing ---[/]", classes="sep"),
            Horizontal(
                Static("Outgoing", classes="radio-lbl"),
                self._rb("ALLOW", "btn-po-allow", self._pol_out == "allow"),
                self._rb("DENY",  "btn-po-deny",  self._pol_out == "deny"),
                classes="radio-row",
            ),
            Horizontal(
                Button("Queue Policy", id="btn-policy-q", classes="act-btn"),
            ),
        )

    # ── RULES ─────────────────────────────────────────────────────────────────

    def _tab_rules(self) -> None:
        self._clear()
        port_rules = [
            r for r in self._status.get("rules", [])
            if r.get("from", "") in ("Anywhere", "Anywhere (v6)", "")
        ]
        lines = [
            "[bright_black] To              Act      From[/]",
            "[bright_black] --------------  -------  ---------------[/]",
        ]
        for r in port_rules[:25]:
            to  = r.get("to", "")[:14].ljust(14)
            act = r.get("action", "")
            frm = r.get("from",   "")
            c   = "green" if act == "ALLOW" else "red"
            lines.append(
                f" {markup_escape(to)}  [{c}]{markup_escape(act):<7}[/{c}]  {markup_escape(frm)}"
            )
        if not port_rules:
            lines.append(" [bright_black](no port rules)[/]")

        self._m(
            Static("\n".join(lines), classes="rule-table"),
            Static("[bright_black] --- Add Rule ---[/]", classes="sep"),
            Horizontal(
                Static("Action  ", classes="radio-lbl"),
                self._rb("ALLOW", "btn-ra-allow", self._rule_act == "allow"),
                self._rb("DENY",  "btn-ra-deny",  self._rule_act == "deny"),
                classes="radio-row",
            ),
            Horizontal(
                Static("Protocol", classes="radio-lbl"),
                self._rb("TCP",  "btn-rp-tcp",  self._rule_proto == "tcp"),
                self._rb("UDP",  "btn-rp-udp",  self._rule_proto == "udp"),
                self._rb("BOTH", "btn-rp-both", self._rule_proto == "both"),
                classes="radio-row",
            ),
            Horizontal(
                Static("Port    ", classes="form-lbl"),
                Input(placeholder="22 / 443 / 3000:3005", id="inp-port",
                      classes="form-inp"),
                classes="form-row",
            ),
            Horizontal(
                Button("Add Rule", id="btn-add-rule", classes="act-btn"),
            ),
        )

    # ── ACL ───────────────────────────────────────────────────────────────────

    def _tab_acl(self) -> None:
        self._clear()
        acl_rules = [
            r for r in self._status.get("rules", [])
            if r.get("from", "") not in ("Anywhere", "Anywhere (v6)", "")
            and re.search(r"\d+\.\d+", r.get("from", ""))
        ]
        lines = [
            "[bright_black] Source                 To/Port         Act[/]",
            "[bright_black] ---------------------  --------------  -----[/]",
        ]
        for r in acl_rules[:20]:
            frm = r.get("from", "")[:21].ljust(21)
            to  = r.get("to",   "")[:14].ljust(14)
            act = r.get("action", "")
            c   = "green" if act == "ALLOW" else "red"
            lines.append(
                f" {markup_escape(frm)}  {markup_escape(to)}  [{c}]{markup_escape(act)}[/{c}]"
            )
        if not acl_rules:
            lines.append(" [bright_black](no IP-based rules)[/]")

        self._m(
            Static("\n".join(lines), classes="rule-table"),
            Static("[bright_black] --- Add ACL Rule ---[/]", classes="sep"),
            Horizontal(
                Static("Action  ", classes="radio-lbl"),
                self._rb("ALLOW", "btn-aa-allow", self._acl_act == "allow"),
                self._rb("DENY",  "btn-aa-deny",  self._acl_act == "deny"),
                classes="radio-row",
            ),
            Horizontal(
                Static("Src IP  ", classes="form-lbl"),
                Input(placeholder="192.168.1.10 or 192.168.1.0",
                      id="inp-acl-ip", classes="form-inp"),
                classes="form-row",
            ),
            Horizontal(
                Static("Subnet /", classes="form-lbl"),
                Input(placeholder="24  (blank=single host)",
                      id="inp-acl-sub", classes="form-inp"),
                classes="form-row",
            ),
            Horizontal(
                Static("Port    ", classes="form-lbl"),
                Input(placeholder="22  (blank=all ports)",
                      id="inp-acl-port", classes="form-inp"),
                classes="form-row",
            ),
            Horizontal(
                Static("Proto   ", classes="radio-lbl"),
                self._rb("TCP", "btn-ap-tcp", self._acl_proto == "tcp"),
                self._rb("UDP", "btn-ap-udp", self._acl_proto == "udp"),
                self._rb("ALL", "btn-ap-all", self._acl_proto == "all"),
                classes="radio-row",
            ),
            Horizontal(
                Static("Iface   ", classes="form-lbl"),
                Input(placeholder="eth0  (blank=all interfaces)",
                      id="inp-acl-iface", classes="form-inp"),
                classes="form-row",
            ),
            Horizontal(
                Button("Add ACL Rule", id="btn-add-acl", classes="act-btn"),
            ),
        )

    # ── MANAGEMENT ────────────────────────────────────────────────────────────

    def _tab_mgmt(self) -> None:
        self._clear()
        rules = self._rules_num
        lines = [
            "[bright_black] Num  To                     Act      From[/]",
            "[bright_black] ---  ---------------------  -------  ---------------[/]",
        ]
        for r in rules:
            num = str(r.get("num", "?")).rjust(3)
            to  = r.get("to", "")[:21].ljust(21)
            act = r.get("action", "")
            frm = r.get("from",   "")[:15]
            c   = "green" if act == "ALLOW" else "red"
            v6  = " [bright_black](v6)[/]" if r.get("is_v6") else ""
            lines.append(
                f" {num}  {markup_escape(to)}  [{c}]{markup_escape(act):<7}[/{c}]  {markup_escape(frm)}{v6}"
            )
        if not rules:
            lines.append(" [bright_black](no rules / UFW inactive)[/]")

        self._m(
            Static("\n".join(lines), classes="rule-table"),
            Static("[bright_black] --- Delete Rule ---[/]", classes="sep"),
            Horizontal(
                Static("Rule #  ", classes="form-lbl"),
                Input(placeholder="e.g. 2", id="inp-del", classes="form-inp"),
                classes="form-row",
            ),
            Horizontal(
                Button("Queue Delete",  id="btn-del",      classes="del-btn"),
                Button("Refresh List",  id="btn-ref-mgmt", classes="act-btn"),
            ),
        )

    # ── PROFILE ───────────────────────────────────────────────────────────────

    def _tab_profile(self) -> None:
        self._clear()
        port_lines = [
            f" [cyan]{p}/{pr}[/cyan]  {d}"
            for p, pr, d in MNX_PROFILE_PORTS
        ]
        self._m(
            Static(
                "MNX default open ports preset.\n"
                "Queues rules below then press Apply.",
                classes="rule-table",
            ),
            Static("\n".join(port_lines), classes="rule-table"),
            Horizontal(
                Button("Apply MNX Profile", id="btn-mnx-profile", classes="act-btn"),
            ),
        )

    # ── Button handler ────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id
        if bid is None:
            return

        # Global
        if bid == "btn-apply":   self.action_do_apply();      return
        if bid == "btn-clear":   self._clear_pending();        return
        if bid == "btn-refresh": self.action_refresh_status(); return

        # STATUS
        if bid == "btn-enable":    self._q_enable_safe(); return
        if bid == "btn-disable":
            self._add_pending(self._mgr.cmd_disable())
            self._set_status("Queued: ufw disable"); return
        if bid == "btn-reset-all": self._confirm_reset(); return
        if bid == "btn-logging":
            lv = self._status.get("logging", "off")
            nl = "off" if "off" not in lv.lower() else "on"
            self._add_pending(self._mgr.cmd_logging(nl))
            self._set_status(f"Queued: ufw logging {nl}"); return
        if bid == "btn-log-med":
            self._add_pending(self._mgr.cmd_logging("medium"))
            self._set_status("Queued: ufw logging medium"); return

        # POLICY
        if bid.startswith("btn-pi-"):
            self._pol_in = bid[len("btn-pi-"):]
            self._tab_policy(); return
        if bid.startswith("btn-po-"):
            self._pol_out = bid[len("btn-po-"):]
            self._tab_policy(); return
        if bid == "btn-policy-q":
            self._q_policy(); return

        # RULES
        if bid.startswith("btn-ra-"):
            self._rule_act = bid[len("btn-ra-"):]
            self._tab_rules(); return
        if bid.startswith("btn-rp-"):
            self._rule_proto = bid[len("btn-rp-"):]
            self._tab_rules(); return
        if bid == "btn-add-rule":
            self._q_add_rule(); return

        # ACL
        if bid.startswith("btn-aa-"):
            self._acl_act = bid[len("btn-aa-"):]
            self._tab_acl(); return
        if bid.startswith("btn-ap-"):
            self._acl_proto = bid[len("btn-ap-"):]
            self._tab_acl(); return
        if bid == "btn-add-acl":
            self._q_add_acl(); return

        # MANAGEMENT
        if bid == "btn-del":       self._q_delete(); return
        if bid == "btn-ref-mgmt":  self.action_refresh_status(); return

        # PROFILE
        if bid == "btn-mnx-profile": self._q_mnx_profile(); return

    # ── Actions ───────────────────────────────────────────────────────────────

    def _q_enable_safe(self) -> None:
        rules      = self._status.get("rules", [])
        ssh_live   = any(
            re.search(r"\b22\b", r.get("to", "")) and r.get("action") == "ALLOW"
            for r in rules
        )
        ssh_queued = any(re.search(r"allow\s+22", c, re.I) for c in self._pending)
        if not ssh_live and not ssh_queued:
            ssh_cmd    = self._mgr.cmd_port_rule("allow", "22", "tcp")
            enable_cmd = self._mgr.cmd_enable()
            if ssh_cmd not in self._pending:
                self._pending.append(ssh_cmd)
            if enable_cmd not in self._pending:
                self._pending.append(enable_cmd)
            self._update_pending_bar()
            self._set_status("[yellow]No SSH rule - allow 22/tcp prepended before enable[/]")
        else:
            self._add_pending(self._mgr.cmd_enable())
            self._set_status("Queued: ufw enable")

    def _confirm_reset(self) -> None:
        def _cb(ok: bool) -> None:
            if ok:
                self._add_pending(self._mgr.cmd_reset())
                self._set_status("Queued: ufw --force reset")
        self.app.push_screen(
            ConfirmModal(
                "[bold red]WARNING[/bold red]: All firewall rules will be deleted.\n"
                "This resets UFW to default state.\nContinue?"
            ),
            _cb,
        )

    def _q_policy(self) -> None:
        s   = self._status
        ci  = s.get("incoming", "deny")
        co  = s.get("outgoing", "allow")
        chg = False
        if self._pol_in != ci:
            self._add_pending(self._mgr.cmd_policy("incoming", self._pol_in))
            chg = True
        if self._pol_out != co:
            self._add_pending(self._mgr.cmd_policy("outgoing", self._pol_out))
            chg = True
        if chg:
            self._set_status(f"Queued: incoming={self._pol_in} outgoing={self._pol_out}")
        else:
            self._set_status("No change (already same as current policy)")

    def _q_add_rule(self) -> None:
        try:
            pv = self.query_one("#inp-port", Input).value.strip()
        except Exception:
            pv = ""
        if not pv:
            self._set_status("[red]Port required[/]"); return

        re_end = ""
        if ":" in pv:
            parts = pv.split(":", 1)
            pv    = parts[0].strip()
            re_end = parts[1].strip()

        cmd = self._mgr.cmd_port_rule(self._rule_act, pv, self._rule_proto, re_end)
        if self._rule_act == "deny" and pv in ("22", "ssh"):
            self._ssh_warn(cmd); return

        self._add_pending(cmd)
        self._set_status(f"Queued: {cmd}")
        try:
            self.query_one("#inp-port", Input).value = ""
        except Exception:
            pass

    def _q_add_acl(self) -> None:
        try:
            ip    = self.query_one("#inp-acl-ip",   Input).value.strip()
            sub   = self.query_one("#inp-acl-sub",  Input).value.strip()
            port  = self.query_one("#inp-acl-port", Input).value.strip()
            iface = self.query_one("#inp-acl-iface",Input).value.strip()
        except Exception:
            self._set_status("[red]Form read error[/]"); return

        if not ip:
            self._set_status("[red]Source IP required[/]"); return

        source = f"{ip}/{sub}" if sub else ip
        cmd    = self._mgr.cmd_acl(self._acl_act, source, port, self._acl_proto, iface)

        if self._acl_act == "deny" and port in ("22", "ssh"):
            self._ssh_warn(cmd); return

        self._add_pending(cmd)
        self._set_status(f"Queued: {cmd}")
        for fid in ("#inp-acl-ip", "#inp-acl-sub", "#inp-acl-port", "#inp-acl-iface"):
            try:
                self.query_one(fid, Input).value = ""
            except Exception:
                pass

    def _q_delete(self) -> None:
        try:
            ns = self.query_one("#inp-del", Input).value.strip()
        except Exception:
            ns = ""
        if not ns.isdigit():
            self._set_status("[red]Enter a valid rule number[/]"); return
        cmd = self._mgr.cmd_delete(int(ns))
        self._add_pending(cmd)
        self._set_status(f"Queued: {cmd}")

    def _q_mnx_profile(self) -> None:
        added = 0
        for port, proto, _ in MNX_PROFILE_PORTS:
            cmd = self._mgr.cmd_port_rule("allow", port, proto)
            if cmd not in self._pending:
                self._pending.append(cmd)
                added += 1
        self._update_pending_bar()
        self._set_status(f"MNX Profile: {added} rules queued")

    def _ssh_warn(self, cmd: str) -> None:
        def _second(ok2: bool) -> None:
            if ok2:
                self._add_pending(cmd)
                self._set_status("[red]Queued: SSH port 22 DENY[/]")

        def _first(ok: bool) -> None:
            if not ok:
                return
            self.app.push_screen(
                ConfirmModal(
                    "[bold red]SECOND CONFIRM[/bold red]\n\n"
                    "Port 22 DENY will block all SSH access.\n"
                    "Only proceed if physical console access is available.\n\n"
                    "Really deny port 22?"
                ),
                _second,
            )

        self.app.push_screen(
            ConfirmModal(
                f"[bold red]SSH BLOCK WARNING[/bold red]\n\n"
                f"Command: [cyan]{markup_escape(cmd)}[/cyan]\n\n"
                "This will block SSH (port 22) access.\n"
                "Remote sessions will be terminated. Continue?"
            ),
            _first,
        )

    # ── Apply ─────────────────────────────────────────────────────────────────

    def action_do_apply(self) -> None:
        if not self._pending:
            self._set_status("No pending commands"); return
        self._execute_pending()

    def _execute_pending(self) -> None:
        cmds = list(self._pending)
        self._set_status(f"[yellow]Running {len(cmds)} command(s)...[/]")

        def _run():
            ok, out = self._mgr.execute(cmds)
            self.call_from_thread(self._on_apply_done, ok, out, cmds)

        threading.Thread(target=_run, daemon=True).start()

    def _on_apply_done(self, ok: bool, output: str, cmds: list) -> None:
        escaped = markup_escape(output)
        if ok:
            self._pending.clear()
            self._update_pending_bar()
            self._bg_refresh()
            self._set_status(f"[green]OK: {len(cmds)} command(s) applied[/]")
            self.app.push_screen(
                ResultModal(f"[green]Apply OK[/] ({len(cmds)} cmd)", escaped or "(no output)")
            )
        else:
            self._set_status("[red]Apply FAILED - see popup[/]")
            self.app.push_screen(
                ResultModal("[red]Apply FAILED[/]", escaped or "(no output)")
            )

    # ── Pending helpers ───────────────────────────────────────────────────────

    def _add_pending(self, cmd: str) -> None:
        if cmd not in self._pending:
            self._pending.append(cmd)
        self._update_pending_bar()

    def _clear_pending(self) -> None:
        self._pending.clear()
        self._update_pending_bar()
        self._set_status("Pending queue cleared")

    def _update_pending_bar(self) -> None:
        try:
            bar = self.query_one("#pending-bar", Static)
            if not self._pending:
                bar.update("[bright_black]No pending.[/]")
            else:
                parts = [f"[yellow]Pending({len(self._pending)}):[/]"]
                for c in self._pending:
                    parts.append(f" [cyan]>[/] {markup_escape(c)}")
                bar.update("  ".join(parts[:1]) + "\n" + "\n".join(parts[1:]))
        except Exception:
            pass

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status-bar", Static).update(f" {msg}")
        except Exception:
            pass

    # ── Bindings ──────────────────────────────────────────────────────────────

    def action_refresh_status(self) -> None:
        self._set_status("[yellow]Refreshing...[/]")
        self._bg_refresh()

    def action_go_back(self) -> None:
        self.app.pop_screen()
