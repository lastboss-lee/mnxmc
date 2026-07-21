"""
MNX Config Screen

Configuration editor for:
  - /opt/mnx/etc/mnx_config.json  (global/ES, base_path, mnxdpi, pcap)
  - /opt/mnx/etc/config.ini       (interface, interfaceOps)
"""

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import datetime
from pathlib import Path
from collections import OrderedDict
from rich.markup import escape as markup_escape

from textual.app import ComposeResult
from app.ui.screen import BaseScreen
from textual.widgets import Footer, Static, ListView, ListItem, Label, Input, Button
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual import on, events



# ── File paths ────────────────────────────────────────────────────────────────
JSON_PATH      = "/opt/mnx/etc/mnx_config.json"
INI_PATH       = "/opt/mnx/etc/config.ini"
MNXMC_PATH     = "/opt/mnx/etc/mnxmc_console.json"
SVC_CTRL_PATH  = "/opt/service_control/settings.json"
SURICATA_YAML  = "/etc/suricata/suricata.yaml"

# ── Password obfuscation ─────────────────────────────────────────────────────
_PW_PREFIX = "ENC:"

def _encode_pw(plaintext: str) -> str:
    """Encode password for config storage (base64 obfuscation)."""
    if not plaintext:
        return ""
    return _PW_PREFIX + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

def _decode_pw(stored: str) -> str:
    """Decode password from config storage."""
    if not stored:
        return ""
    if stored.startswith(_PW_PREFIX):
        try:
            return base64.b64decode(stored[len(_PW_PREFIX):]).decode("utf-8")
        except Exception:
            return stored
    return stored  # legacy plaintext — returned as-is

# ── Disk perf test constants ──────────────────────────────────────────────────
PERF_RESULT_DIR = "/tmp/mnxmc_perf"
IODEPTH_DEFAULT = 32  # fallback (타겟별 iodepth 미지정 시)

PERF_TARGETS_CONFIG = {
    # Elasticsearch: 랜덤 R/W 혼합 (인덱싱 70% + 검색 30%)
    "application": {
        "path": "/application", "bs": "4k",  "numjobs": 4,
        "rw": "randrw", "rwmixread": 30, "size": "256m", "iodepth": 64,
    },
    # PCAP Capture: 순차 R/W 혼합 (캡처 80% + 재생분석 20%)
    "data": {
        "path": "/data",        "bs": "1m",  "numjobs": 1,
        "rw": "rw",     "rwmixread": 20, "size": "1g",  "iodepth": 4,
    },
    # NDR Pipeline: 혼합 R/W 처리 성능 검증
    "pipeline": {
        "path": "/pipeline",    "bs": "64k", "numjobs": 6,
        "rw": "randrw", "size": "512m", "iodepth": 32,
    },
}

PERF_MODES_CONFIG = {
    "quick":    60,
    "standard": 600,
    "stress":   1800,
}

# 네트워크 수용능력 검증 기준 (지속 쓰기 기준)
# BW: 1G=125MB/s≈119MiB/s, 5G=625MB/s≈596MiB/s, 10G=1250MB/s≈1192MiB/s
CAPACITY_TIERS = [
    {"label": "1G",  "bw_mib":   119, "es_iops":  10_000},
    {"label": "5G",  "bw_mib":   596, "es_iops":  50_000},
    {"label": "10G", "bw_mib": 1_192, "es_iops": 100_000},
]


# ── Default values (from reference config) ────────────────────────────────────
DEFAULTS: dict = {
    "global_es": OrderedDict([
        ("address",  "127.0.0.1:9200"),
        ("tls",      "false"),
        ("auth_id",  ""),
        ("auth_pw",  ""),
    ]),
    "base_path": OrderedDict([
        ("log",                  "/logs"),
        ("pid",                  "/var/run/"),
        ("unixsocket",           "/var/run/"),
        ("pcap",                 "/pipeline/raw"),
        ("data",                 "/data"),
        ("dpi_workspace",        "/dir_cache"),
        ("payload_binary",       "/data/payload"),
        ("payload_mail_content", "/data/payload/mail_content"),
        ("payload_ai_content",   "/data/payload/ai_content"),
    ]),
    "mnxdpi": OrderedDict([
        ("worker_count",        "64"),
        ("subworkers_count",    "3"),
        ("worker_count_extra",  "4"),
        ("worker_idle_timeout", "60000"),
        ("queue_size",          "10000"),
        ("port",                "9500"),
    ]),
    "pcap": OrderedDict([
        ("exclusive_read",    "true"),
        ("read_tail_wait_ms", "15000"),
        ("path",              "/data/raw"),
        ("files",             "4"),
        ("idle_ms",           "1000"),
        ("mode",              "direct"),
        ("page_size_k",       "256"),
        ("file_size_g",       "12"),
        ("pre_pages_g",       "2"),
    ]),
    "capture": OrderedDict([
        ("interface",    "eno8403;enp174s0f1"),
        ("interfaceOps", "tags=Net-1;tags=Net-1"),
    ]),
    "mnxmc": OrderedDict([
        ("timeout",      "15"),
        ("max_sessions", "5"),
    ]),
    "svcctrl": OrderedDict([
        ("thread_count_job",                 "2"),
        ("mode",                             "1"),
        ("log_path",                         "/logs/"),
        ("log_level",                        "info"),
        ("module_heartbeat_interval_second", "60"),
        ("mnxweb_host",                      "https://127.0.0.1:8443"),
        ("pcap_raw_proc_flag",               "true"),
        ("pcap_raw_dpi_mode",                "mnx"),
        ("pcap_raw_file_count_key",          "packetThreads"),
        ("pcap_raw_pre_path",                "/pipeline/raw/"),
        ("pcap_raw_post_path",               "/data/raw/"),
        ("pcap_raw_cycle",                   "10"),
    ]),
}

# ── Field labels and hints ────────────────────────────────────────────────────
FIELD_LABELS: dict = {
    "global_es": {
        "address":  ("ES Address",        "Comma-separated list, e.g. 127.0.0.1:9200,10.0.0.1:9200"),
        "tls":      ("TLS Enabled",       "true / false"),
        "auth_id":  ("Auth Username",     "Leave blank if no auth"),
        "auth_pw":  ("Auth Password",     "Leave blank if no auth"),
    },
    "base_path": {
        "log":                  ("Log Directory",       ""),
        "pid":                  ("PID Directory",       ""),
        "unixsocket":           ("Unix Socket Dir",     ""),
        "pcap":                 ("PCAP Directory",      ""),
        "data":                 ("Data Directory",      ""),
        "dpi_workspace":        ("DPI Workspace",       ""),
        "payload_binary":       ("Payload Binary Dir",  ""),
        "payload_mail_content": ("Mail Content Dir",    ""),
        "payload_ai_content":   ("AI Content Dir",      ""),
    },
    "mnxdpi": {
        "worker_count":        ("Worker Count",         "Number of DPI worker threads"),
        "subworkers_count":    ("Sub-Worker Count",     ""),
        "worker_count_extra":  ("Extra Workers",        ""),
        "worker_idle_timeout": ("Worker Idle Timeout",  "Milliseconds"),
        "queue_size":          ("Queue Size",           ""),
        "port":                ("DPI Port",             "libmnxdpi listen port"),
    },
    "pcap": {
        "exclusive_read":    ("Exclusive Read",     "true / false"),
        "read_tail_wait_ms": ("Read Tail Wait",     "Milliseconds"),
        "path":              ("PCAP Path",          ""),
        "files":             ("File Count",         ""),
        "idle_ms":           ("Idle (ms)",          ""),
        "mode":              ("Mode",               "direct / mmap"),
        "page_size_k":       ("Page Size (KB)",     ""),
        "file_size_g":       ("File Size (GB)",     "Max per-file size"),
        "pre_pages_g":       ("Pre-Pages (GB)",     ""),
    },
    "capture": {
        "interface":    ("Interfaces",    "Semicolon-separated, e.g. eno1;enp2s0"),
        "interfaceOps": ("Interface Ops", "Semicolon-separated tags, e.g. tags=Net-1;tags=Net-2"),
    },
    "mnxmc": {
        "timeout":      ("Session Timeout (min)", "Idle session auto-disconnect. 0 = disabled"),
        "max_sessions": ("Max Concurrent Sessions", "Max simultaneous MNXMC sessions (1-10)"),
    },
    "svcctrl": {
        "thread_count_job":                 ("Thread Count (Job)",      "Number of job threads"),
        "mode":                             ("Mode",                    "Operation mode (integer)"),
        "log_path":                         ("Log Path",                "Directory for log files"),
        "log_level":                        ("Log Level",               "info / debug / warn / error"),
        "module_heartbeat_interval_second": ("Heartbeat Interval (s)",  "Module heartbeat interval in seconds"),
        "mnxweb_host":                      ("MNXWeb Host",             "https://host:port"),
        "pcap_raw_proc_flag":               ("PCAP Raw Proc Flag",      "true / false"),
        "pcap_raw_dpi_mode":                ("PCAP DPI Mode",           "e.g. mnx"),
        "pcap_raw_file_count_key":          ("PCAP File Count Key",     "Config key name for thread count"),
        "pcap_raw_pre_path":                ("PCAP Pre Path",           "Raw PCAP input directory"),
        "pcap_raw_post_path":               ("PCAP Post Path",          "Processed output directory"),
        "pcap_raw_cycle":                   ("PCAP Raw Cycle",          "Cycle interval (seconds)"),
    },
}

# ── Left menu definition ───────────────────────────────────────────────────────
MENU_ITEMS = [
    ("back",      "← Back"),
    ("hdr",       "── MNX Config (JSON) ─"),
    ("global_es", "   Elasticsearch"),
    ("base_path", "   Base Paths"),
    ("mnxdpi",    "   DPI Workers"),
    ("pcap",      "   PCAP"),
    ("sep1",      ""),
    ("hdr2",      "── Capture Config ────"),
    ("capture",   "   Interfaces"),
    ("sep2",      ""),
    ("hdr3",      "── MNXMC Console ─────"),
    ("mnxmc",     "   Session Policy"),
    ("sep3",      ""),
    ("hdr4",      "── Service Control ──"),
    ("svcctrl",   "   Service Control"),
    ("sep4",      ""),
    ("hdr5",      "── Disk Performance ──"),
    ("disk_perf", "   Disk Perf Test"),
    ("sep5",      ""),
    ("hdr6",      "── Security ──────────"),
    ("fw_status", "   UFW  Status"),
    ("fw_policy", "   UFW  Policy"),
    ("fw_rules",  "   UFW  Rules"),
    ("fw_acl",    "   UFW  ACL"),
    ("fw_mgmt",   "   UFW  Mgmt"),
    ("fw_profile","   UFW  Profile"),
    ("sep6",      ""),
    ("hdr7",      "── System Power ──────"),
    ("sys_power", "   Power Control"),
]

SECTION_TITLES = {
    "global_es": "MNX Config › Elasticsearch",
    "base_path": "MNX Config › Base Paths",
    "mnxdpi":    "MNX Config › DPI Workers",
    "pcap":      "MNX Config › PCAP",
    "capture":   "Capture Config › Interfaces",
    "mnxmc":     "MNXMC Console › Session Policy",
    "disk_perf": "MNX Config › Disk Perf Test",
    "svcctrl":   "Service Control › Settings",
    "fw_status":  "Security > UFW Status",
    "fw_policy":  "Security > UFW Policy",
    "fw_rules":   "Security > UFW Port Rules",
    "fw_acl":     "Security > UFW ACL",
    "fw_mgmt":    "Security > UFW Management",
    "fw_profile": "Security > UFW Quick Profile",
    "sys_power":  "System Power › Power Control",
}

NON_SELECTABLE = {"hdr", "hdr2", "hdr3", "hdr4", "hdr5", "hdr6", "hdr7", "sep1", "sep2", "sep3", "sep4", "sep5", "sep6"}

# 섹션별 한 줄 설명 (설정 페이지 느낌 — Option/Description 명확화)
SECTION_DESC = {
    "global_es": "Elasticsearch 접속 주소·TLS·인증 정보. (mnx_config.json)",
    "base_path": "MNX 데이터/로그 기본 경로. (mnx_config.json)",
    "mnxdpi":    "DPI 워커 수 등 mnxdpi 엔진 설정. (mnx_config.json)",
    "pcap":      "PCAP 캡처/읽기 관련 파라미터. (mnx_config.json)",
    "capture":   "캡처 대상 인터페이스 및 옵션. (config.ini)",
    "mnxmc":     "콘솔 세션 타임아웃·최대 동시 세션. (mnxmc_console.json)",
    "svcctrl":   "service_control 동작 설정. (settings.json)",
}


class MnxConfigScreen(BaseScreen):
    """MNX configuration editor screen (공통 BaseScreen 골격 사용)."""

    SIDEBAR_TITLE = "MNX CONFIG"
    SIDEBAR_BULLET = True   # 항목 앞에 캐럿(›) — 전 화면 통일
    # 헤더/구분선 라벨은 자체 서식 유지, 선택 항목은 들여쓰기 제거(캐럿이 대신함)
    SIDEBAR_ITEMS = [
        (k,
         (l if (k.startswith("hdr") or k.startswith("sep")) else l.strip()),
         ("header" if k.startswith("hdr")
          else "separator" if k.startswith("sep")
          else "item"))
        for k, l in MENU_ITEMS
    ]

    FOOTER_KEYS = [
        ("↑↓", "Select"),
        ("Enter", "Open"),
        ("Ctrl+S", "Apply"),
        ("F3", "Default"),
        ("F10", "Exit"),
        ("ESC", "Back"),
    ]

    CSS = """
    MnxConfigScreen {
        background: #0c0c0c;
    }

    #panel-title {
        width: 100%;
        height: 1;
        background: #333333;
        color: white;
        text-style: bold;
        padding: 0 2;
    }

    #form-scroll {
        width: 100%;
        height: 1fr;
        background: #0c0c0c;
        padding: 1 2;
    }

    /* ── Input field rows: label | underline input (login style) ── */
    .field-row {
        width: 100%;
        height: 2;
        layout: horizontal;
        margin-bottom: 0;
        background: #0c0c0c;
    }

    .field-hint {
        width: 100%;
        height: 1;
        color: ansi_bright_black;
        padding: 0 0 0 28;
        background: #0c0c0c;
        margin-bottom: 1;
    }

    .field-label {
        width: 26;
        height: 2;
        content-align: left middle;
        color: #aaaaaa;
        padding: 0 1;
        background: #0c0c0c;
    }

    .field-sep {
        width: 1;
        height: 1;
        color: ansi_bright_black;
        background: #0c0c0c;
    }

    .field-input {
        width: 1fr;
        height: 2;
        color: white;
        background: #0c0c0c;
        border-top: none;
        border-right: none;
        border-bottom: solid #5fd7d7;
        border-left: none;
        padding: 0 0;
    }

    .field-input:focus {
        border-top: none;
        border-right: none;
        border-bottom: solid #87ffff;
        border-left: none;
        background: #0c0c0c;
    }

    #status-bar {
        width: 100%;
        height: 1;
        color: #aaaaaa;
        padding: 0 2;
        background: #111111;
    }

    #button-row {
        width: 100%;
        height: 1;
        layout: horizontal;
        align: left middle;
        padding: 0 2;
        background: #111111;
    }

    #btn-apply {
        width: 22;
        height: 1;
        background: #006666;
        color: white;
        border: none;
        margin-right: 2;
    }

    #btn-apply:hover, #btn-apply:focus {
        background: #5fd7d7;
        color: black;
        text-style: bold;
    }

    #btn-cancel {
        width: 20;
        height: 1;
        background: #2a2a2a;
        color: white;
        border: none;
    }

    #btn-cancel:hover {
        background: #444444;
        color: white;
        text-style: bold;
    }

    #btn-cancel:focus {
        background: #5fd7d7;
        color: #0c0c0c;
        text-style: bold;
        border: solid #5fd7d7;
    }

    /* ── Disk Perf Test section ── */
    #perf-header {
        width: 100%;
        height: 1;
        color: #5fd7d7;
        text-style: bold;
        background: #0c0c0c;
    }

    .perf-section-label {
        width: 100%;
        height: 1;
        color: #aaaaaa;
        background: #0c0c0c;
        margin-top: 1;
    }

    #target-display {
        width: 100%;
        height: 4;
        background: #0c0c0c;
        color: white;
    }

    #mode-display {
        width: 100%;
        height: 3;
        background: #0c0c0c;
        color: white;
    }

    #perf-controls {
        width: 100%;
        height: 3;
        color: #5fd7d7;
        background: #111111;
        margin-top: 1;
        padding: 0 1;
    }

    #perf-status {
        width: 100%;
        height: 2;
        color: white;
        background: #0c0c0c;
    }

    #perf-results {
        width: 100%;
        height: auto;
        color: white;
        background: #0c0c0c;
    }

    /* ── Service Control section ── */
    .svcctrl-info-header {
        width: 100%;
        height: 2;
        color: #5fd7d7;
        text-style: bold;
        background: #0c0c0c;
        margin-top: 1;
    }

    .svcctrl-info-body {
        width: 100%;
        color: white;
        background: #111111;
        padding: 1 2;
    }
    /* ── UFW section ── */
    .ufw-info {
        width: 100%; color: white; background: #0c0c0c;
    }
    .ufw-sep {
        width: 100%; height: 1; color: #333333; background: #0c0c0c;
    }
    .ufw-hdr {
        width: 100%; height: 1;
        color: #5fd7d7; text-style: bold; background: #0c0c0c;
        margin-top: 1;
    }
    .ufw-form-row {
        width: 100%; height: 3; layout: horizontal; background: #0c0c0c;
    }
    .ufw-form-lbl {
        width: 12; height: 3; color: #888888;
        content-align: left middle; background: #0c0c0c;
    }
    .ufw-form-inp {
        width: 1fr; height: 3; color: white; background: #0c0c0c;
        border-top: none; border-right: none;
        border-bottom: solid #5fd7d7; border-left: none;
        padding: 0 1;
    }
    .ufw-form-inp:focus { border-bottom: solid #87ffff; background: #0c0c0c; }
    .ufw-radio-row {
        width: 100%; height: 1; layout: horizontal; background: #0c0c0c;
    }
    .ufw-radio-lbl {
        width: 12; height: 1; color: #888888;
        content-align: left middle; background: #0c0c0c;
    }
    .ufw-rb {
        width: auto; min-width: 8; height: 1;
        border: none; background: #1e1e1e; color: #666666;
        padding: 0 1; margin-right: 1;
    }
    .ufw-rb:hover { border: none; color: white; background: #2a2a2a; }
    .ufw-rb:focus { border: none; color: white; background: #2a2a2a; }
    .ufw-rb.-active { border: none; }
    .ufw-rb-sel {
        width: auto; min-width: 8; height: 1;
        border: none; background: #003333; color: #5fd7d7;
        padding: 0 1; margin-right: 1;
    }
    .ufw-rb-sel:hover { border: none; background: #004444; color: #5fd7d7; }
    .ufw-rb-sel:focus { border: none; background: #003333; color: #5fd7d7; }
    .ufw-rb-sel.-active { border: none; }
    .ufw-act-btn {
        width: auto; min-width: 14; height: 1;
        background: #006666; color: white;
        border: none; margin-right: 1; margin-top: 1;
    }
    .ufw-act-btn:hover { border: none; background: #5fd7d7; color: black; }
    .ufw-act-btn:focus { border: none; background: #5fd7d7; color: black; }
    .ufw-act-btn.-active { border: none; }
    .ufw-del-btn {
        width: auto; min-width: 14; height: 1;
        background: #550000; color: white;
        border: none; margin-right: 1; margin-top: 1;
    }
    .ufw-del-btn:hover { border: none; background: #ff5f5f; color: black; }
    .ufw-del-btn:focus { border: none; background: #ff5f5f; color: black; }
    .ufw-del-btn.-active { border: none; }
    .ufw-wrn-btn {
        width: auto; min-width: 14; height: 1;
        background: #553300; color: white;
        border: none; margin-right: 1; margin-top: 1;
    }
    .ufw-wrn-btn:hover { border: none; background: #ffaf00; color: black; }
    .ufw-wrn-btn:focus { border: none; background: #ffaf00; color: black; }
    .ufw-wrn-btn.-active { border: none; }
    #ufw-pending {
        width: 100%; height: auto;
        min-height: 1; max-height: 4;
        color: #aaaaaa; background: #0d1a1a;
        padding: 0 1; margin-top: 1;
        border-top: solid #333333;
    }
    /* ── System Power section ── */
    .power-info {
        width: 100%; color: #aaaaaa; background: #0c0c0c;
        margin-bottom: 1;
    }
    .power-hdr {
        width: 100%; height: 1;
        color: #5fd7d7; text-style: bold; background: #0c0c0c;
        margin-top: 1;
    }
    .power-btn-row {
        width: 100%; height: 1; layout: horizontal; background: #0c0c0c;
        margin-top: 1;
    }
    #btn-reboot {
        width: auto; min-width: 16; height: 1;
        background: #553300; color: white;
        border: none; margin-right: 2;
    }
    #btn-reboot:hover { border: none; background: #ffaf00; color: black; }
    #btn-reboot:focus { border: none; background: #ffaf00; color: black; }
    #btn-reboot.-active { border: none; }
    #btn-shutdown {
        width: auto; min-width: 16; height: 1;
        background: #550000; color: white;
        border: none; margin-right: 2;
    }
    #btn-shutdown:hover { border: none; background: #ff5f5f; color: black; }
    #btn-shutdown:focus { border: none; background: #ff5f5f; color: black; }
    #btn-shutdown.-active { border: none; }
    .power-confirm-lbl {
        width: 100%; height: 1; color: #888888;
        background: #0c0c0c; padding: 0 1; margin-top: 1;
    }
    #power-confirm-inp {
        width: 100%; height: 2; color: white; background: #0c0c0c;
        border-top: none; border-right: none;
        border-bottom: solid #ffaf00; border-left: none;
        padding: 0 1;
    }
    #power-confirm-inp:focus {
        border-bottom: solid #ff5f5f; background: #0c0c0c;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel",        "Cancel"),
        Binding("ctrl+s", "apply",         "Apply"),
        Binding("f3",     "reset_default", "Set Default"),
        Binding("f5",     "refresh",       "Reload"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_section: str = ""
        self._field_keys: list = []
        self._menu_texts: dict = {}
        # UFW state
        from modules.firewall_manager import FirewallManager
        self._ufw_mgr        = FirewallManager()
        self._ufw_status: dict = {}
        self._ufw_rules_num: list = []
        self._ufw_pending: list = []
        self._ufw_pol_in     = "deny"
        self._ufw_pol_out    = "allow"
        self._ufw_rule_act   = "allow"
        self._ufw_rule_proto = "tcp"
        self._ufw_acl_act    = "allow"
        self._ufw_acl_proto  = "tcp"
        # Disk perf state
        self._test_target: str    = "application"
        self._test_mode: str      = "quick"
        self._test_status: str    = "READY"
        self._perf_focus: str     = "target"   # "target" | "mode"
        self._test_start_time: float = 0.0
        self._fio_proc            = None
        self._fio_lock            = threading.Lock()
        self._fio_thread          = None
        self._fio_stop_event      = threading.Event()
        # {target: metric_string} — 마지막 테스트에서 실제 수행한 타겟만 포함
        self._last_results: dict  = {}
        self._last_test_target: str = ""
        self._last_test_mode: str   = ""
        self._last_menu_index: int  = 0
        # System Power confirm state
        self._power_pending: str    = ""  # "reboot" | "shutdown" | ""

    # ── Compose ──────────────────────────────────────────────────────────────

    def compose_content(self) -> ComposeResult:
        yield Static(" Select a section", id="panel-title")
        with ScrollableContainer(id="form-scroll"):
            yield Static(
                "[bright_black]← Select a config section from the left menu[/]",
                id="form-placeholder"
            )
        yield Static("", id="status-bar")
        with Horizontal(id="button-row"):
            yield Button("< Apply (Ctrl+S) >", id="btn-apply")
            yield Button("< Cancel (ESC) >",   id="btn-cancel")

    def on_mount(self) -> None:
        self._ensure_config_files()
        self.set_timer(0.1, self._focus_menu)
        self.query_one("#button-row").display = False

    # ── Config file auto-initialization ──────────────────────────────────────

    _DEFAULT_JSON = json.dumps({
        "global": {
            "elasticsearch": {
                "address": ["127.0.0.1:9200"],
                "tls": False,
                "auth_id": "",
                "auth_pw": "",
            },
            "base_path": dict(DEFAULTS["base_path"]),
        },
        "mnxdpi": {
            **{k: int(v) if v.isdigit() else v for k, v in DEFAULTS["mnxdpi"].items()},
            "pcap": {
                k: (v.lower() == "true" if k == "exclusive_read"
                    else int(v) if v.isdigit() else v)
                for k, v in DEFAULTS["pcap"].items()
            },
        },
    }, indent=2, ensure_ascii=False)

    _DEFAULT_INI = (
        "[capture]\n"
        f"interface={DEFAULTS['capture']['interface']}\n"
        f"interfaceOps={DEFAULTS['capture']['interfaceOps']}\n"
    )

    _DEFAULT_MNXMC = json.dumps({
        "session": {
            "timeout": int(DEFAULTS["mnxmc"]["timeout"]),
            "max_sessions": int(DEFAULTS["mnxmc"]["max_sessions"]),
        }
    }, indent=2, ensure_ascii=False)

    def _ensure_config_files(self) -> None:
        """Create /opt/mnx/etc/ and default config files if missing."""
        config_dir = Path("/opt/mnx/etc")
        if not config_dir.is_dir():
            try:
                subprocess.run(
                    ["sudo", "-n", "mkdir", "-p", str(config_dir)],
                    capture_output=True, timeout=5,
                )
            except Exception as e:
                self.log.error(f"Cannot create {config_dir}: {e}")
                return

        for fpath, content in [
            (JSON_PATH,  self._DEFAULT_JSON),
            (INI_PATH,   self._DEFAULT_INI),
            (MNXMC_PATH, self._DEFAULT_MNXMC),
        ]:
            if not Path(fpath).exists():
                try:
                    self._sudo_tee_write(Path(fpath), content)
                    self.log.info(f"Created default config: {fpath}")
                except Exception as e:
                    self.log.error(f"Cannot create {fpath}: {e}")

    def on_unmount(self) -> None:
        """Stop any running fio test when the screen is removed."""
        self._fio_stop_event.set()
        with self._fio_lock:
            proc = self._fio_proc
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
            except Exception:
                pass

    def _focus_menu(self) -> None:
        try:
            menu = self.query_one("Sidebar ListView", ListView)
            menu.focus()
            menu.index = self._last_menu_index
        except Exception:
            pass

    # ── Menu navigation ───────────────────────────────────────────────────────

    def on_nav_selected(self, key: str) -> None:
        """사이드바 선택 처리 (BaseScreen 라우팅). 헤더/구분선은 비활성이라 미발생."""
        if not key or key in NON_SELECTABLE:
            return
        if key == "back":
            self.action_go_back()
        else:
            self._show_section(key)

    # ── Form rendering ────────────────────────────────────────────────────────

    def _show_section(self, section_key: str) -> None:
        try:
            self._last_menu_index = self.query_one("Sidebar ListView", ListView).index or 0
        except Exception:
            pass
        if section_key == "disk_perf":
            self._show_disk_perf_section()
            return

        if section_key == "sys_power":
            self._show_sys_power_section()
            return

        if section_key.startswith("fw_"):
            self._show_ufw_section(section_key)
            return

        self._current_section = section_key
        self._field_keys = list(DEFAULTS[section_key].keys())

        current = self._load_section(section_key)

        title = SECTION_TITLES.get(section_key, section_key)
        self.query_one("#panel-title", Static).update(f" {title}")

        scroll = self.query_one("#form-scroll")
        scroll.remove_children()

        # 섹션 설명 (설정 페이지 느낌 — Option/Description 명확화)
        desc = SECTION_DESC.get(section_key)
        if desc:
            scroll.mount(Static(f"[bright_black]{desc}[/]", classes="section-desc"))

        for field_key in self._field_keys:
            label_text, hint = FIELD_LABELS[section_key][field_key]
            default_val = DEFAULTS[section_key][field_key]
            current_val = current.get(field_key, default_val)

            fid = f"fld-{field_key.replace('_', '-')}"
            placeholder = markup_escape(hint) if hint else markup_escape(str(default_val))

            is_password = (field_key == "auth_pw")
            scroll.mount(Horizontal(
                Static(markup_escape(label_text), classes="field-label"),
                Static("│", classes="field-sep"),
                Input(
                    value=str(current_val),
                    id=fid,
                    classes="field-input",
                    placeholder=placeholder,
                    password=is_password,
                ),
                classes="field-row",
            ))

            ref = f"default: {markup_escape(str(default_val))}"
            if hint:
                ref += f"  ({markup_escape(hint)})"
            scroll.mount(Static(f"[bright_black]{ref}[/]", classes="field-hint"))

        try:
            self.query_one("#button-row").display = True
        except Exception:
            pass
        self._set_status(f"Loaded: {title}  ·  F3=Set Default  ·  Ctrl+S=Apply")

        if section_key == "svcctrl":
            self.call_after_refresh(self._mount_svcctrl_info)

    # ── Disk Perf Test UI ─────────────────────────────────────────────────────

    def _show_disk_perf_section(self) -> None:
        self._current_section = "disk_perf"
        self._field_keys = []

        self.query_one("#panel-title", Static).update(" MNX Config › Disk Perf Test")

        try:
            self.query_one("#button-row").display = False
        except Exception:
            pass

        scroll = self.query_one("#form-scroll")
        scroll.remove_children()

        scroll.mount(Static("[ Performance Test ]", id="perf-header"))

        scroll.mount(Static("", id="target-label", classes="perf-section-label"))
        scroll.mount(Static("", id="target-display"))

        scroll.mount(Static("", id="mode-label", classes="perf-section-label"))
        scroll.mount(Static("", id="mode-display"))

        scroll.mount(Static(
            "  ─────────────────────────────────────────────────\n"
            "  [ S Start Test ]  [ T Stop Test ]\n"
            "  ─────────────────────────────────────────────────",
            id="perf-controls",
        ))

        status_color = self._perf_status_color()
        scroll.mount(Static(
            f"\n  Status:  [{status_color}]{self._test_status}[/]",
            id="perf-status",
        ))

        scroll.mount(Static(self._render_perf_results(), id="perf-results"))

        # Reset focus area and render selection state immediately (no async needed)
        self._perf_focus = "target"
        self.call_after_refresh(self._refresh_selections)
        self._set_status("S=Start  T=Stop  ·  1-4=Target  1-3=Mode  Tab=Switch")

    def _perf_status_color(self) -> str:
        s = self._test_status
        if s.startswith("RUNNING"):
            return "yellow"
        if s == "DONE":
            return "green"
        if s.startswith("ERROR"):
            return "red"
        return "white"

    _TARGETS = [
        ("application", "(1) application   (/application)"),
        ("data",        "(2) data          (/data)        "),
        ("pipeline",    "(3) pipeline      (/pipeline)    "),
        ("all",         "(4) ALL                          "),
    ]
    _MODES = [
        ("quick",    "(1) quick       (60s)  "),
        ("standard", "(2) standard    (600s) "),
        ("stress",   "(3) stress      (1800s)"),
    ]

    def _render_target_display(self) -> str:
        lines = []
        for key, label in self._TARGETS:
            if key == self._test_target:
                lines.append(f"[black on #5fd7d7]  {label}[/]")
            else:
                lines.append(f"  [white]{label}[/]")
        return "\n".join(lines)

    def _render_mode_display(self) -> str:
        lines = []
        for key, label in self._MODES:
            if key == self._test_mode:
                lines.append(f"[black on #5fd7d7]  {label}[/]")
            else:
                lines.append(f"  [white]{label}[/]")
        return "\n".join(lines)

    def _refresh_selections(self) -> None:
        """Update target/mode Static displays and focus indicators."""
        if self._perf_focus == "target":
            t_lbl = "[bold #5fd7d7]  Target ◄[/]"
            m_lbl = "[#aaaaaa]  Mode[/]"
        else:
            t_lbl = "[#aaaaaa]  Target[/]"
            m_lbl = "[bold #5fd7d7]  Mode ◄[/]"
        try:
            self.query_one("#target-label", Static).update(t_lbl)
            self.query_one("#target-display", Static).update(self._render_target_display())
            self.query_one("#mode-label", Static).update(m_lbl)
            self.query_one("#mode-display", Static).update(self._render_mode_display())
        except Exception:
            pass

    def _update_test_status(self, status: str, elapsed: int = 0) -> None:
        self._test_status = status
        if self._current_section != "disk_perf":
            return
        try:
            color = self._perf_status_color()
            elapsed_str = f"  ·  {elapsed}s" if elapsed > 0 else ""
            self.query_one("#perf-status", Static).update(
                f"\n  Status:  [{color}]{status}[/]{elapsed_str}"
            )
        except Exception:
            pass

    @staticmethod
    def _lat_color(ms: float, target: str = "") -> str:
        # ES(application)는 더 엄격한 기준 적용
        if target == "application":
            return "red" if ms > 1.5 else ("yellow" if ms > 1.0 else "white")
        return "red" if ms > 2.0 else ("yellow" if ms > 1.0 else "white")

    def _render_fio_single(self, target: str, d: dict) -> str:
        cfg   = PERF_TARGETS_CONFIG.get(target, {})
        profile = (
            f"{cfg.get('rw','?')}, {cfg.get('bs','?')}, "
            f"{cfg.get('numjobs','?')} jobs, {self._last_test_mode}"
        )
        SEP = "  [#5fd7d7]" + "─" * 56 + "[/]"
        HDR = "  [#5fd7d7]" + "═" * 56 + "[/]"
        ri, wi = d["iops"]["read"],  d["iops"]["write"]
        rb, wb = d["bw"]["read"],    d["bw"]["write"]
        rl, wl = d["clat"]["read"],  d["clat"]["write"]
        cu, cs = d["cpu"]["usr"],    d["cpu"]["sys"]
        rc, wc = self._lat_color(rl, target), self._lat_color(wl, target)
        lat_legend = (
            "  [#aaaaaa]ES Latency: [white]<1ms[/] normal  [yellow]1-1.5ms[/] warn  [red]>1.5ms[/] critical[/]"
            if target == "application" else
            "  [#aaaaaa]Latency: [white]<1ms[/] normal  [yellow]1-2ms[/] warn  [red]>2ms[/] critical[/]"
        )
        lines = [
            HDR,
            f"  [bold #5fd7d7]  {target.upper()}[/]  [#aaaaaa]{profile}[/]",
            HDR,
            "",
            f"  [bold #5fd7d7]{'Metric':<22}{'Read':>14}{'Write':>14}[/]",
            SEP,
            f"  [#aaaaaa]{'IOPS':<22}[/][white]{ri:>11,.0f}[/]   [white]{wi:>11,.0f}[/]",
            f"  [#aaaaaa]{'BW (MiB/s)':<22}[/][white]{rb:>11.1f}[/]   [white]{wb:>11.1f}[/]",
            f"  [#aaaaaa]{'Latency clat (ms)':<22}[/][{rc}]{rl:>11.3f}[/]   [{wc}]{wl:>11.3f}[/]",
            SEP,
            f"  [#aaaaaa]{'CPU usr%':<22}[/][white]{cu:>11.1f}[/]",
            f"  [#aaaaaa]{'CPU sys%':<22}[/][white]{cs:>11.1f}[/]",
            "",
            lat_legend,
        ]
        lines += self._render_capacity_single(target, d)
        return "\n".join(lines)

    def _render_fio_all(self) -> str:
        C0, C1, C2, C3, C4, C5, C6, C7, C8 = 13, 8, 8, 8, 8, 7, 7, 6, 6
        SEP = "  [#5fd7d7]" + "─" * 78 + "[/]"
        HDR = "  [#5fd7d7]" + "═" * 78 + "[/]"
        lines = [
            HDR,
            f"  [bold #5fd7d7]  ALL Targets[/]  [#aaaaaa]{self._last_test_mode}[/]",
            HDR,
            "",
            (f"  [bold #5fd7d7]"
             f"{'':>{C0}}  {'─ IOPS ─':^{C1+C2+1}}  {'─ BW MiB/s ─':^{C3+C4+1}}"
             f"  {'─Lat ms─':^{C5+C6+1}}  {'─CPU%─':^{C7+C8+1}}[/]"),
            (f"  [#aaaaaa]{'Target':<{C0}}  {'R':>{C1}} {'W':>{C2}}"
             f"  {'R':>{C3}} {'W':>{C4}}  {'R':>{C5}} {'W':>{C6}}"
             f"  {'usr':>{C7}} {'sys':>{C8}}[/]"),
            SEP,
        ]
        for t in ("application", "data", "pipeline"):
            if t not in self._last_results:
                continue
            d = self._last_results[t]
            ri, wi = d["iops"]["read"],  d["iops"]["write"]
            rb, wb = d["bw"]["read"],    d["bw"]["write"]
            rl, wl = d["clat"]["read"],  d["clat"]["write"]
            cu, cs = d["cpu"]["usr"],    d["cpu"]["sys"]
            rc, wc = self._lat_color(rl, t), self._lat_color(wl, t)
            lines.append(
                f"  [bold white]{t:<{C0}}[/]"
                f"  [white]{ri:>{C1},.0f}[/] [white]{wi:>{C2},.0f}[/]"
                f"  [white]{rb:>{C3}.1f}[/] [white]{wb:>{C4}.1f}[/]"
                f"  [{rc}]{rl:>{C5}.3f}[/] [{wc}]{wl:>{C6}.3f}[/]"
                f"  [white]{cu:>{C7}.1f}[/] [white]{cs:>{C8}.1f}[/]"
            )
        lines += [
            SEP,
            "",
            "  [#aaaaaa]Latency: [white]<1ms[/] / ES [white]<1ms[/] normal  "
            "[yellow]warn[/]  [red]critical[/]  "
            "(ES 임계: [yellow]1-1.5ms[/] [red]>1.5ms[/])[/]",
        ]
        lines += self._render_capacity_all()
        return "\n".join(lines)

    def _render_capacity_single(self, target: str, d: dict) -> list:
        """단일 타겟 수용능력 평가 행 목록 반환."""
        SEP = "  [#5fd7d7]" + "─" * 56 + "[/]"
        HDR = "  [#5fd7d7]" + "═" * 56 + "[/]"
        lines = [
            "",
            HDR,
            "  [bold #5fd7d7]  Network Capacity Assessment[/]",
            f"  [bold #5fd7d7]{'Tier':<6}  {'Required':>14}  {'Measured':>14}  {'Margin':>8}  Status[/]",
            SEP,
        ]
        for tier in CAPACITY_TIERS:
            if target == "application":
                req    = tier["es_iops"]
                meas   = d["iops"]["write"]
                req_s  = f"{req:>10,} IOPS"
                meas_s = f"{meas:>10,.0f} IOPS"
                margin = meas / req if req else 0
                ok_bw  = True
                ok_lat = d["clat"]["write"] < 1.5
                ok_iops = meas >= req
                status = (
                    "[green]PASS[/]"   if (ok_iops and ok_lat) else
                    "[yellow]WARN[/]"  if ok_iops else
                    "[red]FAIL[/]"
                )
            else:
                req    = tier["bw_mib"]
                meas   = d["bw"]["write"]
                req_s  = f"{req:>10,} MiB/s"
                meas_s = f"{meas:>10.0f} MiB/s"
                margin = meas / req if req else 0
                status = (
                    "[green]PASS[/]"  if meas >= req else
                    "[red]FAIL[/]"
                )
            margin_s = f"{margin:.1f}x"
            lines.append(
                f"  [#aaaaaa]{tier['label']:<6}[/]  [#aaaaaa]{req_s}[/]"
                f"  [white]{meas_s}[/]  [white]{margin_s:>8}[/]  {status}"
            )
        lines.append(SEP)
        return lines

    def _render_capacity_all(self) -> list:
        """ALL 타겟 수용능력 평가 테이블 행 목록 반환."""
        SEP = "  [#5fd7d7]" + "─" * 78 + "[/]"
        HDR = "  [#5fd7d7]" + "═" * 78 + "[/]"

        def _status(ok_primary: bool, ok_secondary: bool = True) -> str:
            if ok_primary and ok_secondary:
                return "[green]PASS[/]"
            if ok_primary:
                return "[yellow]WARN[/]"
            return "[red]FAIL[/]"

        da = self._last_results.get("application")
        dd = self._last_results.get("data")
        dp = self._last_results.get("pipeline")

        lines = [
            "",
            HDR,
            "  [bold #5fd7d7]  Network Capacity Assessment[/]",
            (f"  [bold #5fd7d7]{'Tier':<5}  {'BW Req':>9}  "
             f"{'data W':>9}  {'pipeline W':>11}  "
             f"{'ES Req':>9}  {'app IOPS W':>11}  "
             f"{'ES Lat':>7}  Overall[/]"),
            SEP,
        ]
        for tier in CAPACITY_TIERS:
            bw_req  = tier["bw_mib"]
            es_req  = tier["es_iops"]

            dd_bw   = dd["bw"]["write"]   if dd else 0
            dp_bw   = dp["bw"]["write"]   if dp else 0
            da_iops = da["iops"]["write"] if da else 0
            da_lat  = da["clat"]["write"] if da else 999

            ok_dd   = dd_bw   >= bw_req
            ok_dp   = dp_bw   >= bw_req
            ok_iops = da_iops >= es_req
            ok_lat  = da_lat  <  1.5

            overall = _status(ok_dd and ok_dp and ok_iops, ok_lat)

            def _v(val: float, ok: bool, fmt: str) -> str:
                col = "green" if ok else "red"
                return f"[{col}]{val:{fmt}}[/]"

            lines.append(
                f"  [#aaaaaa]{tier['label']:<5}[/]  [#aaaaaa]{bw_req:>7,} M[/]"
                f"  {_v(dd_bw,   ok_dd,   '>7.0f')} M"
                f"  {_v(dp_bw,   ok_dp,   '>9.0f')} M"
                f"  [#aaaaaa]{es_req:>7,} K[/]"
                f"  {_v(da_iops/1000, ok_iops, '>8.1f')} K"
                f"  {_v(da_lat,  ok_lat,  '>5.3f')} ms"
                f"  {overall}"
            )
        lines.append(SEP)
        return lines

    def _render_perf_results(self) -> str:
        if not self._last_results:
            return "\n  Last Result:  [bright_black](no results yet)[/]"
        tested = [t for t in ("application", "data", "pipeline") if t in self._last_results]
        if len(tested) == 1:
            return "\n" + self._render_fio_single(tested[0], self._last_results[tested[0]])
        return "\n" + self._render_fio_all()

    def _update_perf_results(self) -> None:
        if self._current_section != "disk_perf":
            return
        try:
            self.query_one("#perf-results", Static).update(self._render_perf_results())
        except Exception:
            pass

    # ── Perf test actions ─────────────────────────────────────────────────────

    def action_start_test(self) -> None:
        if self._fio_thread is not None and self._fio_thread.is_alive():
            self.app.notify("Test already running. Press T to stop.", severity="warning")
            return

        # _test_target / _test_mode are updated in real-time by on_key
        # Disk space pre-check (non-blocking warning, does not prevent start)
        warnings = self._check_disk_space()
        if warnings:
            self.app.notify(
                "\n".join(warnings),
                severity="warning",
                title="Low Disk Space",
                timeout=8,
            )

        self._fio_stop_event.clear()
        self._test_start_time = time.time()
        t = threading.Thread(target=self._run_fio_background, daemon=True)
        self._fio_thread = t
        t.start()
        self._update_test_status("RUNNING")
        self.app.notify(
            f"target={self._test_target}  mode={self._test_mode}",
            title="Disk Perf Test Started",
        )

    def _check_disk_space(self) -> list:
        """Return warning strings for targets with insufficient free space."""
        _SIZE_UNIT = {"k": 1024, "m": 1024**2, "g": 1024**3}
        targets = (
            ["application", "data", "pipeline"]
            if self._test_target == "all"
            else [self._test_target]
        )
        warnings = []
        for target in targets:
            cfg = PERF_TARGETS_CONFIG[target]
            try:
                s = cfg["size"].lower()
                needed = int(s[:-1]) * _SIZE_UNIT.get(s[-1], 1) * cfg["numjobs"]
                free = shutil.disk_usage(cfg["path"]).free
                if free < needed * 1.5:
                    warnings.append(
                        f"{target}: needs ~{needed/1024**3:.1f} GB, "
                        f"free {free/1024**3:.1f} GB"
                    )
            except Exception:
                pass
        return warnings

    def action_stop_test(self) -> None:
        if self._fio_thread is None or not self._fio_thread.is_alive():
            self.app.notify("No test running.", severity="information")
            return
        self._fio_stop_event.set()
        with self._fio_lock:
            proc = self._fio_proc
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
            except Exception:
                pass
        self.app.notify("Stopping test…", title="Disk Perf Test")

    # ── fio background runner ─────────────────────────────────────────────────

    def _run_fio_background(self) -> None:
        targets = (
            ["application", "data", "pipeline"]
            if self._test_target == "all"
            else [self._test_target]
        )
        runtime = PERF_MODES_CONFIG.get(self._test_mode, 60)
        test_target_snap = self._test_target
        test_mode_snap   = self._test_mode
        results: dict = {}  # {target: metric_string} — 이번 실행 결과만

        for target in targets:
            if self._fio_stop_event.is_set():
                break

            try:
                elapsed = int(time.time() - self._test_start_time)
                self.app.call_from_thread(
                    self._update_test_status, f"RUNNING  ·  {target}", elapsed
                )
            except Exception:
                break

            cfg = PERF_TARGETS_CONFIG[target]
            # Isolated subdirectory — never write directly into production root
            test_dir = Path(cfg["path"]) / ".fio_perf_tmp"
            result_file = None

            try:
                test_dir.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                # root 소유 경로: sudo -n mkdir 으로 재시도
                r = subprocess.run(
                    ["sudo", "-n", "/usr/bin/install", "-d", "-m", "755", str(test_dir)],
                    capture_output=True, timeout=10,
                )
                if r.returncode != 0:
                    err_msg = r.stderr.decode("utf-8", errors="replace").strip()
                    self.log.error(f"Cannot create test dir {test_dir}: {err_msg}")
                    try:
                        self.app.call_from_thread(
                            self.app.notify,
                            f"Cannot create {test_dir}: {err_msg}",
                            severity="error",
                            title="Disk Perf Test",
                        )
                    except Exception:
                        pass
                    continue
            except Exception as e:
                self.log.error(f"Cannot create test dir {test_dir}: {e}")
                try:
                    self.app.call_from_thread(
                        self.app.notify,
                        f"Cannot create {test_dir}: {e}",
                        severity="error",
                        title="Disk Perf Test",
                    )
                except Exception:
                    pass
                continue

            try:
                fd, result_file = tempfile.mkstemp(
                    suffix=".json", prefix=f"mnxmc_fio_{target}_"
                )
                os.close(fd)

                cmd = [
                    "sudo", "-n", "/usr/bin/fio",
                    f"--name={target}_test",
                    f"--directory={test_dir}",
                    f"--rw={cfg['rw']}",
                    *(
                        [f"--rwmixread={cfg['rwmixread']}"]
                        if "rwmixread" in cfg else []
                    ),
                    f"--bs={cfg['bs']}",
                    f"--numjobs={cfg['numjobs']}",
                    f"--iodepth={cfg.get('iodepth', IODEPTH_DEFAULT)}",
                    "--ioengine=libaio",
                    "--direct=1",
                    f"--runtime={runtime}",
                    "--time_based",
                    f"--size={cfg['size']}",
                    "--output-format=json",
                    f"--output={result_file}",
                    "--unlink=1",
                    "--group_reporting",
                ]

                with self._fio_lock:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._fio_proc = proc

                tick = 0
                while proc.poll() is None:
                    if self._fio_stop_event.is_set():
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        break
                    time.sleep(0.5)
                    tick += 1
                    if tick % 2 == 0:  # every ~1s
                        elapsed = int(time.time() - self._test_start_time)
                        try:
                            self.app.call_from_thread(
                                self._update_test_status,
                                f"RUNNING  ·  {target}",
                                elapsed,
                            )
                        except Exception:
                            pass

                with self._fio_lock:
                    self._fio_proc = None

                if proc.returncode == 0 and not self._fio_stop_event.is_set():
                    try:
                        fio_data = json.loads(Path(result_file).read_text(encoding="utf-8"))
                        parsed = self._parse_fio_result(target, fio_data)
                        if parsed:
                            results[target] = parsed
                        self._save_perf_result(target, fio_data)
                    except Exception as e:
                        self.log.error(f"Parse fio result ({target}): {e}")
                        try:
                            self.app.call_from_thread(
                                self.app.notify,
                                f"Result parse error ({target}): {e}",
                                severity="warning",
                                title="Disk Perf Test",
                            )
                        except Exception:
                            pass
                elif (
                    proc.returncode not in (0, -15, -9)
                    and not self._fio_stop_event.is_set()
                ):
                    msg = (
                        f"fio failed for {target} (exit {proc.returncode}).\n"
                        f"Check permissions on {cfg['path']}."
                    )
                    self.log.error(msg)
                    try:
                        self.app.call_from_thread(
                            self.app.notify, msg,
                            severity="error", title="Disk Perf Test",
                        )
                    except Exception:
                        pass

            except FileNotFoundError:
                try:
                    self.app.call_from_thread(
                        self.app.notify,
                        "fio not found or sudo not configured. Install: sudo apt install fio",
                        severity="error",
                        title="fio missing",
                    )
                except Exception:
                    pass
                self._fio_stop_event.set()
                break
            except Exception as e:
                self.log.error(f"fio error ({target}): {e}")
            finally:
                # Always clean up temp result file and isolated test directory
                if result_file:
                    try:
                        Path(result_file).unlink(missing_ok=True)
                    except Exception:
                        pass
                try:
                    # sudo rm -rf: fio(root)가 생성한 파일을 sands가 직접 삭제 불가
                    r = subprocess.run(
                        ["sudo", "-n", "rm", "-rf", str(test_dir)],
                        capture_output=True, timeout=30,
                    )
                    if r.returncode != 0:
                        shutil.rmtree(test_dir, ignore_errors=True)
                except Exception:
                    shutil.rmtree(test_dir, ignore_errors=True)

        if results:  # 결과가 있을 때만 기록 (중단 시 덮어쓰지 않음)
            self._last_results     = results
            self._last_test_target = test_target_snap
            self._last_test_mode   = test_mode_snap
        final_status = "READY" if self._fio_stop_event.is_set() else "DONE"
        try:
            self.app.call_from_thread(self._update_test_status, final_status)
            self.app.call_from_thread(self._update_perf_results)
        except Exception:
            pass

    def _parse_fio_result(self, target: str, fio_data: dict) -> dict:
        try:
            jobs = fio_data.get("jobs", [])
            if not jobs:
                return {}
            job = jobs[0]

            def _clat_ms(side: str) -> float:
                ns = job.get(side, {}).get("clat_ns", {}).get("mean", 0)
                if ns == 0:
                    ns = job.get(side, {}).get("clat", {}).get("mean", 0) * 1000
                return ns / 1_000_000

            return {
                "iops": {
                    "read":  job.get("read",  {}).get("iops", 0),
                    "write": job.get("write", {}).get("iops", 0),
                },
                "bw": {
                    "read":  job.get("read",  {}).get("bw", 0) / 1024,
                    "write": job.get("write", {}).get("bw", 0) / 1024,
                },
                "clat": {
                    "read":  _clat_ms("read"),
                    "write": _clat_ms("write"),
                },
                "cpu": {
                    "usr": job.get("usr_cpu", 0),
                    "sys": job.get("sys_cpu", 0),
                },
            }

        except Exception as e:
            self.log.error(f"Parse fio ({target}): {e}")
        return {}

    def _save_perf_result(self, target: str, fio_data: dict) -> None:
        try:
            result_dir = Path(PERF_RESULT_DIR)
            result_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            out = result_dir / f"fio_{target}_{ts}.json"
            out.write_text(json.dumps(fio_data, indent=2))
        except Exception as e:
            self.log.error(f"Save perf result: {e}")

    # ── File readers ──────────────────────────────────────────────────────────

    def _load_section(self, section_key: str) -> dict:
        """Read current values from the appropriate config file."""
        try:
            if section_key in ("global_es", "base_path", "mnxdpi", "pcap"):
                return self._read_json_section(section_key)
            elif section_key == "capture":
                return self._read_ini_section()
            elif section_key == "mnxmc":
                return self._read_mnxmc_section()
            elif section_key == "svcctrl":
                return self._read_svcctrl_section()
        except Exception as e:
            self.log.error(f"Load section {section_key} failed: {e}")
        return {}

    def _read_json_section(self, section_key: str) -> dict:
        p = Path(JSON_PATH)
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        result = {}
        if section_key == "global_es":
            es = data.get("global", {}).get("elasticsearch", {})
            addrs = es.get("address", ["127.0.0.1:9200"])
            result["address"] = ", ".join(addrs) if isinstance(addrs, list) else str(addrs)
            result["tls"]     = str(es.get("tls", False)).lower()
            result["auth_id"] = str(es.get("auth_id", ""))
            result["auth_pw"] = _decode_pw(str(es.get("auth_pw", "")))
        elif section_key == "base_path":
            bp = data.get("global", {}).get("base_path", {})
            for k in DEFAULTS["base_path"]:
                result[k] = str(bp.get(k, DEFAULTS["base_path"][k]))
        elif section_key == "mnxdpi":
            d = data.get("mnxdpi", {})
            for k in DEFAULTS["mnxdpi"]:
                result[k] = str(d.get(k, DEFAULTS["mnxdpi"][k]))
        elif section_key == "pcap":
            d = data.get("mnxdpi", {}).get("pcap", {})
            for k in DEFAULTS["pcap"]:
                result[k] = str(d.get(k, DEFAULTS["pcap"][k])).lower() if k == "exclusive_read" else str(d.get(k, DEFAULTS["pcap"][k]))
        return result

    def _read_ini_section(self) -> dict:
        p = Path(INI_PATH)
        if not p.exists():
            return {}
        result = {}
        # errors="replace": 한국어 등 non-UTF-8 주석이 있어도 ASCII 값은 정상 파싱
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("interface=") and "Ops" not in stripped:
                result["interface"] = stripped.split("=", 1)[1]
            elif stripped.startswith("interfaceOps="):
                result["interfaceOps"] = stripped.split("=", 1)[1]
        return result

    def _read_mnxmc_section(self) -> dict:
        p = Path(MNXMC_PATH)
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        s = data.get("session", {})
        return {
            "timeout":      str(s.get("timeout",      DEFAULTS["mnxmc"]["timeout"])),
            "max_sessions": str(s.get("max_sessions", DEFAULTS["mnxmc"]["max_sessions"])),
        }

    def _read_svcctrl_section(self) -> dict:
        p = Path(SVC_CTRL_PATH)
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        d = DEFAULTS["svcctrl"]
        pcap_path = data.get("pcap_raw_path", {})
        return {
            "thread_count_job":                 str(data.get("thread_count_job",                 d["thread_count_job"])),
            "mode":                             str(data.get("mode",                             d["mode"])),
            "log_path":                         str(data.get("log_path",                         d["log_path"])),
            "log_level":                        str(data.get("log_level",                        d["log_level"])),
            "module_heartbeat_interval_second": str(data.get("module_heartbeat_interval_second", d["module_heartbeat_interval_second"])),
            "mnxweb_host":                      str(data.get("mnxweb_info", {}).get("host",      d["mnxweb_host"])),
            "pcap_raw_proc_flag":               str(data.get("pcap_raw_proc_flag",               True)).lower(),
            "pcap_raw_dpi_mode":                str(pcap_path.get("dpi_mode",                    d["pcap_raw_dpi_mode"])),
            "pcap_raw_file_count_key":          str(pcap_path.get("file_count_key",              d["pcap_raw_file_count_key"])),
            "pcap_raw_pre_path":                str(pcap_path.get("pre_path",                    d["pcap_raw_pre_path"])),
            "pcap_raw_post_path":               str(pcap_path.get("post_path",                   d["pcap_raw_post_path"])),
            "pcap_raw_cycle":                   str(data.get("pcap_raw_cycle",                   d["pcap_raw_cycle"])),
        }

    def _mount_svcctrl_info(self) -> None:
        """Append read-only service_list display after form fields."""
        scroll = self.query_one("#form-scroll")
        try:
            p = Path(SVC_CTRL_PATH)
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                svc_list = data.get("service_list", [])
            else:
                svc_list = []
        except Exception:
            svc_list = []

        scroll.mount(Static(
            "\n  ── Service List (read-only) ──",
            classes="svcctrl-info-header",
        ))
        if svc_list:
            lines = []
            # service_list may be a dict {"key": {"type":..,"name":..}} or a list
            if isinstance(svc_list, dict):
                items = svc_list.items()
            else:
                items = ((None, svc) for svc in svc_list)
            for key, svc in items:
                stype = markup_escape(str(svc.get("type", "")))
                sname = markup_escape(str(svc.get("name", "")))
                if key is not None:
                    lines.append(f"  [#aaaaaa]{markup_escape(key)}[/]  [#aaaaaa]type:[/] [white]{stype}[/]   [#aaaaaa]name:[/] [white]{sname}[/]")
                else:
                    lines.append(f"  [#aaaaaa]type:[/] [white]{stype}[/]   [#aaaaaa]name:[/] [white]{sname}[/]")
            scroll.mount(Static("\n".join(lines), classes="svcctrl-info-body"))
        else:
            scroll.mount(Static("  [bright_black](no services defined)[/]", classes="svcctrl-info-body"))

    # ── Collect form values ───────────────────────────────────────────────────

    def _get_form_values(self) -> dict:
        values = {}
        for field_key in self._field_keys:
            fid = f"fld-{field_key.replace('_', '-')}"
            try:
                values[field_key] = self.query_one(f"#{fid}", Input).value.strip()
            except Exception:
                values[field_key] = DEFAULTS[self._current_section].get(field_key, "")
        return values

    # ── File writers ──────────────────────────────────────────────────────────

    def _save_section(self, section_key: str, values: dict) -> bool:
        try:
            if section_key in ("global_es", "base_path", "mnxdpi", "pcap"):
                return self._save_json_section(section_key, values)
            elif section_key == "capture":
                return self._save_ini_section(values)
            elif section_key == "mnxmc":
                return self._save_mnxmc_section(values)
            elif section_key == "svcctrl":
                return self._save_svcctrl_section(values)
        except Exception as e:
            self.log.error(f"Save section {section_key} failed: {e}")
            self.app.notify(f"Save failed: {e}", severity="error")
        return False

    # ── 경로 집합: sudo -n tee 를 사용해야 하는 root 소유 설정 파일 ──────────
    _SUDO_TEE_PATHS: frozenset = frozenset([
        "/opt/mnx/etc/config.ini",
        "/opt/mnx/etc/mnx_config.json",
        "/opt/mnx/etc/mnxmc_console.json",
        "/opt/service_control/settings.json",
    ])

    @classmethod
    def _atomic_write_text(cls, p: Path, content: str) -> None:
        """Write content atomically.

        /opt/mnx/etc/ 하위 root 소유 파일: sudo -n tee 방식 (임시 파일 없음,
        tee가 atomic 보장하지 않으나 단일 write이므로 실무상 충분)
        그 외 파일: tempfile + os.replace atomic write
        """
        if str(p) in cls._SUDO_TEE_PATHS:
            cls._sudo_tee_write(p, content)
        else:
            cls._direct_atomic_write(p, content)

    @staticmethod
    def _sudo_tee_write(p: Path, content: str) -> None:
        """sudo -n tee 를 사용해 root 소유 파일에 쓴다.

        -n: 패스워드 프롬프트 없이 실패 (sudoers NOPASSWD 필수)
        content는 UTF-8로 인코딩해 stdin에 전달한다.
        """
        r = subprocess.run(
            ["sudo", "-n", "/usr/bin/tee", str(p)],
            input=content.encode("utf-8", errors="surrogateescape"),
            capture_output=True,
            timeout=10,
        )
        if r.returncode != 0:
            stderr = r.stderr.decode("utf-8", errors="replace").strip()
            raise PermissionError(
                f"sudo tee failed for {p}: {stderr or 'returncode=' + str(r.returncode)}"
            )

    @staticmethod
    def _direct_atomic_write(p: Path, content: str) -> None:
        """일반 파일 atomic write: tempfile + os.replace."""
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(content)
            os.replace(tmp, str(p))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _save_json_section(self, section_key: str, values: dict) -> bool:
        p = Path(JSON_PATH)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        else:
            data = {}

        if section_key == "global_es":
            es = data.setdefault("global", {}).setdefault("elasticsearch", {})
            addrs = [a.strip() for a in values["address"].split(",") if a.strip()]
            es["address"] = addrs
            es["tls"]     = values["tls"].lower() == "true"
            es["auth_id"] = values["auth_id"]
            es["auth_pw"] = _encode_pw(values["auth_pw"])

        elif section_key == "base_path":
            data.setdefault("global", {})["base_path"] = dict(values)

        elif section_key == "mnxdpi":
            d = data.setdefault("mnxdpi", {})
            int_keys = {"worker_count", "subworkers_count", "worker_count_extra",
                        "worker_idle_timeout", "queue_size", "port"}
            for k, v in values.items():
                d[k] = int(v) if k in int_keys and v.isdigit() else v

        elif section_key == "pcap":
            d = data.setdefault("mnxdpi", {}).setdefault("pcap", {})
            int_keys = {"read_tail_wait_ms", "files", "idle_ms",
                        "page_size_k", "file_size_g", "pre_pages_g"}
            for k, v in values.items():
                if k == "exclusive_read":
                    d[k] = v.lower() == "true"
                elif k in int_keys and v.isdigit():
                    d[k] = int(v)
                else:
                    d[k] = v

        self._atomic_write_text(p, json.dumps(data, indent=2, ensure_ascii=False))
        return True

    def _save_ini_section(self, values: dict) -> bool:
        p = Path(INI_PATH)
        if not p.exists():
            self.app.notify(f"File not found: {INI_PATH}", severity="error")
            return False
        # interfaceOps 각 항목에 tags= 접두어 보장
        raw_ops = values.get("interfaceOps", "")
        values["interfaceOps"] = ";".join(
            t if t.startswith("tags=") else f"tags={t}"
            for t in (s.strip() for s in raw_ops.split(";"))
            if t
        )
        # surrogateescape: non-UTF-8 바이트(EUC-KR 주석 등)를 보존하면서 roundtrip
        content = p.read_text(encoding="utf-8", errors="surrogateescape")
        for key, val in [
            ("interface",    values["interface"]),
            ("interfaceOps", values["interfaceOps"]),
        ]:
            new_content, n = re.subn(
                rf'^{key}=.*$', f'{key}={val}', content, flags=re.MULTILINE
            )
            if n > 0:
                content = new_content
            else:
                # 키가 파일에 없으면 말미에 추가
                content = content.rstrip("\n") + f"\n{key}={val}\n"
        self._atomic_write_text(p, content)

        # suricata.yaml af-packet / pcap 섹션 동기화
        ifaces = [s.strip() for s in values["interface"].split(";") if s.strip()]
        ok, err = self._sync_suricata_yaml(ifaces)
        if ok:
            self.app.notify(
                "suricata.yaml 인터페이스 동기화 완료",
                title="Suricata Sync",
            )
        elif err:
            self.log.warning(f"suricata.yaml sync: {err}")
            self.app.notify(
                f"config.ini 저장됨. suricata.yaml 미반영: {err}",
                severity="warning",
                title="Suricata Sync",
            )
        return True

    @staticmethod
    def _sync_suricata_yaml(interfaces: list) -> tuple:
        """config.ini 인터페이스 변경 시 suricata.yaml af-packet/pcap 동기화.

        텍스트 레벨 섹션 치환 — YAML 파서 미사용 (전체 재포맷 방지).
        '- interface: default' 블록과 주석은 보존.
        """
        p = Path(SURICATA_YAML)
        if not p.exists():
            return False, f"{SURICATA_YAML} 파일 없음"
        if not interfaces:
            return False, "인터페이스 목록이 비어있음"

        try:
            text = p.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError as e:
            return False, f"읽기 실패: {e}"

        # 변경 전 백업 (/opt/mnx/etc/ 는 sands 쓰기 가능)
        try:
            Path("/opt/mnx/etc/suricata.yaml.bak").write_text(
                text, encoding="utf-8", errors="surrogateescape",
            )
        except OSError:
            pass

        # ── af-packet 섹션 ────────────────────────────────────────────
        AF_START = "\naf-packet:\n"
        AF_END   = "\naf-xdp:\n"       # af-packet 직후 섹션

        af_pos = text.find(AF_START)
        if af_pos == -1:
            return False, "af-packet: 섹션을 찾을 수 없음"
        af_pos += 1                     # '\n' 건너뜀 → 'af-packet:\n' 시작
        af_end = text.find(AF_END, af_pos)
        if af_end == -1:
            return False, "af-xdp: 경계를 찾을 수 없음"

        af_block = text[af_pos : af_end + 1]   # 'af-packet:\n ... \n'

        # default 블록 위치 (보존 대상)
        af_def = af_block.find("\n  - interface: default")
        if af_def == -1:
            return False, "af-packet default 블록 없음"

        # 새 af-packet 인터페이스 블록 생성
        af_lines = []
        for i, iface in enumerate(interfaces):
            af_lines.append(f"  - interface: {iface}")
            af_lines.append(f"    threads: auto")
            af_lines.append(f"    cluster-id: {99 - i}")
            af_lines.append(f"    cluster-type: cluster_flow")
            af_lines.append(f"    defrag: yes")
            af_lines.append("")

        new_af = "af-packet:\n" + "\n".join(af_lines) + af_block[af_def:]
        text = text[:af_pos] + new_af + text[af_end + 1:]

        # ── pcap 섹션 ────────────────────────────────────────────────
        PCAP_START = "\npcap:\n"
        PCAP_END   = "\npcap-file:\n"   # pcap 직후 섹션

        pcap_pos = text.find(PCAP_START)
        if pcap_pos == -1:
            return False, "pcap: 섹션을 찾을 수 없음"
        pcap_pos += 1
        pcap_end = text.find(PCAP_END, pcap_pos)
        if pcap_end == -1:
            return False, "pcap-file: 경계를 찾을 수 없음"

        pcap_block = text[pcap_pos : pcap_end + 1]

        # default 블록 위치
        pcap_def = pcap_block.find("\n  - interface: default")
        if pcap_def == -1:
            return False, "pcap default 블록 없음"

        # 첫 번째 인터페이스의 주석 블록 보존 (buffer-size, bpf-filter 등)
        comment_block = ""
        first_iface = pcap_block.find("  - interface: ")
        if first_iface != -1:
            first_nl = pcap_block.find("\n", first_iface)
            # 두 번째 인터페이스 또는 default 중 먼저 나오는 위치
            second_iface = pcap_block.find("\n  - interface: ", first_nl)
            if second_iface != -1 and first_nl != -1:
                candidate = pcap_block[first_nl:second_iface]
                # 주석(#)이 포함된 경우만 보존
                if "#" in candidate:
                    comment_block = candidate

        pcap_lines = [f"  - interface: {interfaces[0]}{comment_block}"]
        for iface in interfaces[1:]:
            pcap_lines.append(f"  - interface: {iface}")

        new_pcap = "pcap:\n" + "\n".join(pcap_lines) + pcap_block[pcap_def:]
        text = text[:pcap_pos] + new_pcap + text[pcap_end + 1:]

        # ── 쓰기 (sudo tee) ──────────────────────────────────────────
        try:
            r = subprocess.run(
                ["sudo", "-n", "/usr/bin/tee", SURICATA_YAML],
                input=text.encode("utf-8", errors="surrogateescape"),
                capture_output=True,
                timeout=15,
            )
            if r.returncode != 0:
                stderr = r.stderr.decode("utf-8", errors="replace").strip()
                return False, f"sudo tee 실패: {stderr or 'rc=' + str(r.returncode)}"
        except Exception as e:
            return False, str(e)

        return True, ""

    def _save_mnxmc_section(self, values: dict) -> bool:
        p = Path(MNXMC_PATH)
        try:
            timeout      = int(values.get("timeout",      "15"))
            max_sessions = int(values.get("max_sessions", "5"))
        except ValueError as e:
            self.app.notify(f"Invalid value: {e}", severity="error")
            return False
        data = json.loads(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else {}
        data.setdefault("session", {}).update({"timeout": timeout, "max_sessions": max_sessions})
        self._atomic_write_text(p, json.dumps(data, indent=2))

        # sshd 즉시 적용 (idle timeout + max sessions)
        ok, err = self._apply_sshd_session_policy(timeout, max_sessions)
        if ok:
            self.app.notify(
                "sshd reload 완료 — 새 접속부터 즉시 적용",
                title="SSH Policy Applied",
            )
        else:
            self.app.notify(
                f"JSON 저장됨. sshd 미적용: {err}",
                severity="warning",
                title="SSH Policy",
            )
        return True

    @staticmethod
    def _apply_sshd_session_policy(timeout_minutes: int, max_sessions: int) -> tuple:
        """
        /etc/ssh/sshd_config.d/mnxmc.conf 작성 후 sshd reload.

        idle timeout:
          ClientAliveInterval=60  (1분마다 keepalive)
          ClientAliveCountMax=N   (N번 무응답 → N분 후 끊김)
          timeout_minutes=0 이면 두 값 모두 0 (비활성화)

        Returns:
          (True, "")          성공
          (False, reason_str) 실패
        """
        sshd_conf = Path("/etc/ssh/sshd_config.d/mnxmc.conf")

        if timeout_minutes > 0:
            alive_interval = 60
            alive_count    = timeout_minutes
        else:
            alive_interval = 0
            alive_count    = 3   # interval=0이면 무의미하지만 형식상 유지

        lines = [
            "# MNX Management Console — Session Policy",
            "# Auto-generated by MNXMC. Do not edit manually.",
            f"ClientAliveInterval {alive_interval}",
            f"ClientAliveCountMax {alive_count}",
            f"MaxSessions {max(1, max_sessions)}",
        ]
        content = "\n".join(lines) + "\n"

        # /etc/ssh 는 root 소유 → sudo -n tee 방식
        try:
            r = subprocess.run(
                ["sudo", "-n", "/usr/bin/tee", str(sshd_conf)],
                input=content.encode("utf-8"),
                capture_output=True,
                timeout=10,
            )
            if r.returncode != 0:
                stderr = r.stderr.decode("utf-8", errors="replace").strip()
                return False, f"/etc/ssh 쓰기 실패: {stderr or 'rc=' + str(r.returncode)}"
        except Exception as e:
            return False, str(e)

        # sshd reload (Ubuntu: ssh, RHEL/Rocky: sshd)
        for svc in ("ssh", "sshd"):
            try:
                r = subprocess.run(
                    ["sudo", "-n", "/usr/bin/systemctl", "reload", svc],
                    capture_output=True, text=True, timeout=10,
                )
                if r.returncode == 0:
                    return True, ""
            except Exception:
                continue

        return False, "systemctl reload 실패"

    def _save_svcctrl_section(self, values: dict) -> bool:
        p = Path(SVC_CTRL_PATH)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        else:
            data = {}

        def _int(v: str, fallback) -> object:
            try:
                return int(v)
            except (ValueError, TypeError):
                return fallback

        data["thread_count_job"]                 = _int(values["thread_count_job"],                 2)
        data["mode"]                             = _int(values["mode"],                             1)
        data["log_path"]                         = values["log_path"]
        data["log_level"]                        = values["log_level"]
        data["module_heartbeat_interval_second"] = _int(values["module_heartbeat_interval_second"], 60)
        data.setdefault("mnxweb_info", {})["host"] = values["mnxweb_host"]
        data["pcap_raw_proc_flag"]               = values["pcap_raw_proc_flag"].lower() == "true"
        pcap_path = data.setdefault("pcap_raw_path", {})
        pcap_path["dpi_mode"]       = values["pcap_raw_dpi_mode"]
        pcap_path["file_count_key"] = values["pcap_raw_file_count_key"]
        pcap_path["pre_path"]       = values["pcap_raw_pre_path"]
        pcap_path["post_path"]      = values["pcap_raw_post_path"]
        data["pcap_raw_cycle"]                   = _int(values["pcap_raw_cycle"],                   10)

        self._atomic_write_text(p, json.dumps(data, indent=2, ensure_ascii=False))
        return True

    # ── Status bar ────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, error: bool = False) -> None:
        color = "red" if error else "bright_black"
        try:
            self.query_one("#status-bar", Static).update(f"[{color}] {msg}[/]")
        except Exception:
            pass

    # ── Button / key actions ──────────────────────────────────────────────────

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id
        if bid == "btn-apply":
            self.action_apply()
            return
        if bid == "btn-cancel":
            self.action_cancel()
            return
        # System Power buttons
        if self._current_section == "sys_power":
            self._power_handle_button(bid)
            return
        # UFW inline buttons
        if self._current_section.startswith("fw_"):
            self._ufw_handle_button(bid)

    def action_apply(self) -> None:
        if not self._current_section:
            self.app.notify("Select a section first", severity="warning")
            return
        if self._current_section == "disk_perf":
            return
        if self._current_section == "sys_power":
            return
        if self._current_section.startswith("fw_"):
            self._ufw_execute_pending()
            return
        values = self._get_form_values()
        title  = SECTION_TITLES.get(self._current_section, self._current_section)
        if self._save_section(self._current_section, values):
            self._set_status(f"Saved: {title}")
            self.app.notify(f"Config saved: {title}", title="Saved")
        else:
            self._set_status(f"Save failed: {title}", error=True)

    def action_reset_default(self) -> None:
        if not self._current_section:
            self.app.notify("Select a section first", severity="warning")
            return
        if self._current_section in ("disk_perf", "sys_power"):
            return
        scroll = self.query_one("#form-scroll")
        for field_key in self._field_keys:
            fid = f"fld-{field_key.replace('_', '-')}"
            try:
                inp = scroll.query_one(f"#{fid}", Input)
                inp.value = str(DEFAULTS[self._current_section][field_key])
            except Exception:
                pass
        self._set_status("Reset to defaults — press Ctrl+S to save")
        self.app.notify("Fields reset to default. Press Ctrl+S to save.", title="Set Default")

    def action_cancel(self) -> None:
        """ESC/Cancel: UFW면 pending clear, 폼 활성 시 메뉴로 복귀, 미선택 시 이전 화면으로."""
        if self._current_section == "sys_power":
            self._power_pending = ""
            self._cancel_form()
            return
        if self._current_section.startswith("fw_"):
            self._ufw_clear_pending()
            return
        if self._current_section:
            self._cancel_form()
        else:
            self.app.pop_screen()

    def _cancel_form(self) -> None:
        """폼 초기화 후 왼쪽 메뉴로 복귀."""
        self._current_section = ""
        self._field_keys = []
        try:
            scroll = self.query_one("#form-scroll")
            scroll.remove_children()
            scroll.mount(Static(
                "[bright_black]← Select a config section from the left menu[/]",
                id="form-placeholder",
            ))
        except Exception:
            pass
        try:
            self.query_one("#panel-title", Static).update(" Select a section")
        except Exception:
            pass
        try:
            self.query_one("#button-row").display = False
        except Exception:
            pass
        self._set_status("")
        self.set_timer(0.05, self._focus_menu)

    def action_go_back(self) -> None:
        """← Back 메뉴 항목: 이전 화면으로."""
        self.app.pop_screen()


    # ═══════════════════════════════════════════════════════════════════════════
    # System Power section methods
    # ═══════════════════════════════════════════════════════════════════════════

    def _show_sys_power_section(self) -> None:
        self._current_section = "sys_power"
        self._field_keys = []
        self._power_pending = ""
        try:
            self.query_one("#panel-title", Static).update(" System Power › Power Control")
            self.query_one("#button-row").display = False
        except Exception:
            pass
        self._set_status("Power Control — Click a button, then type YES in the confirm field and press Enter")
        self._render_sys_power_section()

    def _render_sys_power_section(self) -> None:
        try:
            scroll = self.query_one("#form-scroll")
            scroll.remove_children()

            scroll.mount(Static(
                " [yellow]Warning:[/] The following actions will immediately reboot or shut down the system.\n"
                " Save your work and verify service status before proceeding.",
                classes="power-info",
            ))
            scroll.mount(Static("── Reboot ────────────────────────────────", classes="power-hdr"))
            scroll.mount(Horizontal(
                Button("  Reboot  ", id="btn-reboot"),
                classes="power-btn-row",
            ))
            scroll.mount(Static("── Shutdown ──────────────────────────────", classes="power-hdr"))
            scroll.mount(Horizontal(
                Button("  Shutdown  ", id="btn-shutdown"),
                classes="power-btn-row",
            ))
            scroll.mount(Static("── Confirm Action ───────────────────────", classes="power-hdr"))
            scroll.mount(Static(
                " [bright_black]Click a button above to activate the confirm field.\n"
                " Are you sure? Type YES and press Enter to proceed.[/]",
                classes="power-info",
            ))
            scroll.mount(Static("Confirm:", classes="power-confirm-lbl"))
            scroll.mount(Input(
                placeholder="Select a command first, then type YES",
                id="power-confirm-inp",
                disabled=True,
            ))
        except Exception as e:
            self.log.error(f"System Power render error: {e}")

    def _power_handle_button(self, bid: str) -> None:
        if bid == "btn-reboot":
            self._power_pending = "reboot"
            self._set_status(
                "[yellow]Reboot ready:[/] Type YES in the confirm field and press Enter."
            )
            try:
                inp = self.query_one("#power-confirm-inp", Input)
                inp.disabled = False
                inp.placeholder = "Reboot confirm: type YES and press Enter"
                inp.value = ""
                inp.focus()
            except Exception:
                pass
            return

        if bid == "btn-shutdown":
            self._power_pending = "shutdown"
            self._set_status(
                "[red]Shutdown ready:[/] Type YES in the confirm field and press Enter."
            )
            try:
                inp = self.query_one("#power-confirm-inp", Input)
                inp.disabled = False
                inp.placeholder = "Shutdown confirm: type YES and press Enter"
                inp.value = ""
                inp.focus()
            except Exception:
                pass
            return

    @on(Input.Submitted)
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "power-confirm-inp":
            return
        if self._current_section != "sys_power":
            return
        event.stop()
        confirmed = event.value.strip().upper()
        if confirmed != "YES":
            self._set_status("[red]Cancelled:[/] You must type YES exactly to proceed.")
            try:
                event.input.value = ""
            except Exception:
                pass
            return

        action = self._power_pending
        self._power_pending = ""
        try:
            event.input.disabled = True
            event.input.value = ""
        except Exception:
            pass

        if action == "reboot":
            self._set_status("[yellow]Rebooting the system...[/]")
            self.app.notify("Rebooting the system. Connection will be lost shortly.", title="Reboot", severity="warning")
            import threading as _threading
            def _do_reboot():
                import time as _time
                _time.sleep(1.5)
                try:
                    subprocess.run(
                        ["sudo", "-n", "/sbin/reboot"],
                        capture_output=True, timeout=10,
                    )
                except Exception as _e:
                    self.app.call_from_thread(
                        self._set_status, f"[red]Reboot error: {_e}[/]", True
                    )
            _threading.Thread(target=_do_reboot, daemon=True).start()

        elif action == "shutdown":
            self._set_status("[red]Shutting down the system...[/]")
            self.app.notify("Shutting down the system. Connection will be lost shortly.", title="Shutdown", severity="error")
            import threading as _threading
            def _do_shutdown():
                import time as _time
                _time.sleep(1.5)
                try:
                    subprocess.run(
                        ["sudo", "-n", "/sbin/shutdown", "-h", "now"],
                        capture_output=True, timeout=10,
                    )
                except Exception as _e:
                    self.app.call_from_thread(
                        self._set_status, f"[red]Shutdown error: {_e}[/]", True
                    )
            _threading.Thread(target=_do_shutdown, daemon=True).start()

        else:
            self._set_status("[bright_black]No command selected.[/]")

    # ═══════════════════════════════════════════════════════════════════════════
    # UFW section methods
    # ═══════════════════════════════════════════════════════════════════════════

    def _ufw_rb(self, label: str, btn_id: str, selected: bool) -> "Button":
        mark = "*" if selected else " "
        cls  = "ufw-rb-sel" if selected else "ufw-rb"
        return Button(f"{mark} {label}", id=btn_id, classes=cls)

    def _show_ufw_section(self, section_key: str) -> None:
        self._current_section = section_key
        self._field_keys = []
        title = SECTION_TITLES.get(section_key, section_key)
        try:
            self.query_one("#panel-title", Static).update(f" {title}")
            self.query_one("#button-row").display = True
            self.query_one("#btn-apply", Button).label = "Apply UFW (Ctrl+S)"
            self.query_one("#btn-cancel", Button).label = "Clear Pending (ESC)"
        except Exception:
            pass
        self._set_status("[yellow]Loading UFW status...[/]")
        self._ufw_bg_refresh(lambda: self._ufw_render_section(section_key))

    def _ufw_bg_refresh(self, callback=None) -> None:
        import threading as _threading
        def _fetch():
            try:
                self._ufw_status    = self._ufw_mgr.get_status()
                self._ufw_rules_num = self._ufw_mgr.get_numbered_rules()
                self._ufw_pol_in    = self._ufw_status.get("incoming", "deny")
                self._ufw_pol_out   = self._ufw_status.get("outgoing", "allow")
                err = self._ufw_status.get("error")
                # 상태 메시지 업데이트 후 렌더링 callback 호출 (순서 보장)
                if err:
                    self.app.call_from_thread(self._set_status, f"ufw error: {err}", True)
                else:
                    active = self._ufw_status.get("active", False)
                    state  = "ACTIVE" if active else "INACTIVE"
                    self.app.call_from_thread(
                        self._set_status,
                        f"UFW:{state}  pending={len(self._ufw_pending)}  Ctrl+S=Apply  ESC=Clear"
                    )
                if callback:
                    self.app.call_from_thread(callback)
            except Exception as _e:
                self.app.call_from_thread(
                    self._set_status, f"[red]UFW 백그라운드 오류: {_e}[/]", True
                )
        _threading.Thread(target=_fetch, daemon=True).start()

    def _ufw_render_section(self, section_key: str) -> None:
        if self._current_section != section_key:
            return
        try:
            scroll = self.query_one("#form-scroll")
            scroll.remove_children()
            render_map = {
                "fw_status":  self._ufw_render_status,
                "fw_policy":  self._ufw_render_policy,
                "fw_rules":   self._ufw_render_rules,
                "fw_acl":     self._ufw_render_acl,
                "fw_mgmt":    self._ufw_render_mgmt,
                "fw_profile": self._ufw_render_profile,
            }
            fn = render_map.get(section_key)
            if fn:
                fn(scroll)
            self._ufw_render_pending_widget(scroll)
        except Exception as e:
            self.log.error(f"UFW render error [{section_key}]: {e}")
            self._set_status(f"[red]UFW 화면 렌더링 오류: {e}[/]", True)

    def _ufw_render_status(self, scroll) -> None:
        if not self._ufw_mgr.is_available():
            scroll.mount(Static(" [red]ufw not installed.[/]", classes="ufw-info"))
            return

        s      = self._ufw_status
        active = s.get("active", False)
        inc    = s.get("incoming", "deny").upper()
        out    = s.get("outgoing", "allow").upper()
        log_   = s.get("logging",  "off")
        err    = s.get("error")
        ic     = "red"   if inc == "DENY"  else "green"
        oc     = "green" if out == "ALLOW" else "red"
        st_txt = "[green]ACTIVE[/]" if active else "[red]INACTIVE[/]"

        scroll.mount(Static(
            f" Status: {st_txt}   "
            f"Incoming: [{ic}]{inc}[/{ic}]   "
            f"Outgoing: [{oc}]{out}[/{oc}]   "
            f"Log: {markup_escape(log_)}",
            classes="ufw-info",
        ))
        if err:
            scroll.mount(Static(f" [red]Error: {markup_escape(err)}[/]", classes="ufw-info"))

        rules = s.get("rules", [])
        lines = [
            "[bright_black] To               Act      From[/]",
            "[bright_black] ---------------  -------  ----------------[/]",
        ]
        for r in rules[:20]:
            to  = r.get("to",     "")[:15].ljust(15)
            act = r.get("action", "")
            frm = r.get("from",   "")[:16]
            c   = "green" if act == "ALLOW" else "red"
            lines.append(
                f" {markup_escape(to)}  [{c}]{markup_escape(act):<7}[/{c}]  {markup_escape(frm)}"
            )
        if not rules:
            lines.append(" [bright_black](no rules)[/]")
        scroll.mount(Static("[bright_black] --- Rules ---[/]", classes="ufw-sep"))
        scroll.mount(Static("\n".join(lines), classes="ufw-info"))

        log_on  = "off" not in log_.lower()
        log_lbl = "Logging Off" if log_on  else "Logging On"
        log_cls = "ufw-wrn-btn" if log_on  else "ufw-act-btn"
        scroll.mount(Static("[bright_black] --- Actions ---[/]", classes="ufw-sep"))
        scroll.mount(Horizontal(
            Button("Enable",       id="ufw-enable",    classes="ufw-act-btn"),
            Button("Disable",      id="ufw-disable",   classes="ufw-wrn-btn"),
            Button("Reset All",    id="ufw-reset",     classes="ufw-del-btn"),
            Button(log_lbl,        id="ufw-logging",   classes=log_cls),
            Button("Log:Medium",   id="ufw-log-med",   classes="ufw-act-btn"),
        ))

    def _ufw_render_policy(self, scroll) -> None:
        s  = self._ufw_status
        ci = s.get("incoming", "deny").upper()
        co = s.get("outgoing", "allow").upper()
        ic = "red"   if ci == "DENY"  else "green"
        oc = "green" if co == "ALLOW" else "red"
        scroll.mount(Static(
            f" Current:  Incoming=[{ic}]{ci}[/{ic}]   Outgoing=[{oc}]{co}[/{oc}]",
            classes="ufw-info",
        ))
        scroll.mount(Static("[bright_black] --- Incoming ---[/]", classes="ufw-sep"))
        scroll.mount(Horizontal(
            Static("Incoming", classes="ufw-radio-lbl"),
            self._ufw_rb("DENY",   "ufw-pi-deny",   self._ufw_pol_in == "deny"),
            self._ufw_rb("ALLOW",  "ufw-pi-allow",  self._ufw_pol_in == "allow"),
            self._ufw_rb("REJECT", "ufw-pi-reject", self._ufw_pol_in == "reject"),
            classes="ufw-radio-row",
        ))
        scroll.mount(Static("[bright_black] --- Outgoing ---[/]", classes="ufw-sep"))
        scroll.mount(Horizontal(
            Static("Outgoing", classes="ufw-radio-lbl"),
            self._ufw_rb("ALLOW", "ufw-po-allow", self._ufw_pol_out == "allow"),
            self._ufw_rb("DENY",  "ufw-po-deny",  self._ufw_pol_out == "deny"),
            classes="ufw-radio-row",
        ))
        scroll.mount(Horizontal(
            Button("Queue Policy", id="ufw-policy-q", classes="ufw-act-btn"),
        ))

    def _ufw_render_rules(self, scroll) -> None:
        port_rules = [
            r for r in self._ufw_status.get("rules", [])
            if r.get("from", "") in ("Anywhere", "Anywhere (v6)", "")
        ]
        lines = [
            "[bright_black] To              Act      From[/]",
            "[bright_black] --------------  -------  ---------------[/]",
        ]
        for r in port_rules[:20]:
            to  = r.get("to", "")[:14].ljust(14)
            act = r.get("action", "")
            frm = r.get("from",   "")
            c   = "green" if act == "ALLOW" else "red"
            lines.append(
                f" {markup_escape(to)}  [{c}]{markup_escape(act):<7}[/{c}]  {markup_escape(frm)}"
            )
        if not port_rules:
            lines.append(" [bright_black](no port rules)[/]")
        scroll.mount(Static("\n".join(lines), classes="ufw-info"))
        scroll.mount(Static("[bright_black] --- Add Rule ---[/]", classes="ufw-sep"))
        scroll.mount(Horizontal(
            Static("Action  ", classes="ufw-radio-lbl"),
            self._ufw_rb("ALLOW", "ufw-ra-allow", self._ufw_rule_act == "allow"),
            self._ufw_rb("DENY",  "ufw-ra-deny",  self._ufw_rule_act == "deny"),
            classes="ufw-radio-row",
        ))
        scroll.mount(Horizontal(
            Static("Protocol", classes="ufw-radio-lbl"),
            self._ufw_rb("TCP",  "ufw-rp-tcp",  self._ufw_rule_proto == "tcp"),
            self._ufw_rb("UDP",  "ufw-rp-udp",  self._ufw_rule_proto == "udp"),
            self._ufw_rb("BOTH", "ufw-rp-both", self._ufw_rule_proto == "both"),
            classes="ufw-radio-row",
        ))
        scroll.mount(Horizontal(
            Static("Port    ", classes="ufw-form-lbl"),
            Input(placeholder="22 / 443 / 3000:3005", id="ufw-inp-port",
                  classes="ufw-form-inp"),
            classes="ufw-form-row",
        ))
        scroll.mount(Horizontal(
            Button("Add Rule", id="ufw-add-rule", classes="ufw-act-btn"),
        ))

    def _ufw_render_acl(self, scroll) -> None:
        import re as _re
        acl_rules = [
            r for r in self._ufw_status.get("rules", [])
            if r.get("from", "") not in ("Anywhere", "Anywhere (v6)", "")
            and _re.search(r"\d+\.\d+", r.get("from", ""))
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
        scroll.mount(Static("\n".join(lines), classes="ufw-info"))
        scroll.mount(Static("[bright_black] --- Add ACL Rule ---[/]", classes="ufw-sep"))
        scroll.mount(Horizontal(
            Static("Action  ", classes="ufw-radio-lbl"),
            self._ufw_rb("ALLOW", "ufw-aa-allow", self._ufw_acl_act == "allow"),
            self._ufw_rb("DENY",  "ufw-aa-deny",  self._ufw_acl_act == "deny"),
            classes="ufw-radio-row",
        ))
        scroll.mount(Horizontal(
            Static("Src IP  ", classes="ufw-form-lbl"),
            Input(placeholder="192.168.1.10 or 192.168.1.0", id="ufw-acl-ip",
                  classes="ufw-form-inp"),
            classes="ufw-form-row",
        ))
        scroll.mount(Horizontal(
            Static("Subnet /", classes="ufw-form-lbl"),
            Input(placeholder="24  (blank=single host)", id="ufw-acl-sub",
                  classes="ufw-form-inp"),
            classes="ufw-form-row",
        ))
        scroll.mount(Horizontal(
            Static("Port    ", classes="ufw-form-lbl"),
            Input(placeholder="22  (blank=all ports)", id="ufw-acl-port",
                  classes="ufw-form-inp"),
            classes="ufw-form-row",
        ))
        scroll.mount(Horizontal(
            Static("Proto   ", classes="ufw-radio-lbl"),
            self._ufw_rb("TCP", "ufw-ap-tcp", self._ufw_acl_proto == "tcp"),
            self._ufw_rb("UDP", "ufw-ap-udp", self._ufw_acl_proto == "udp"),
            self._ufw_rb("ALL", "ufw-ap-all", self._ufw_acl_proto == "all"),
            classes="ufw-radio-row",
        ))
        scroll.mount(Horizontal(
            Static("Iface   ", classes="ufw-form-lbl"),
            Input(placeholder="eth0  (blank=all)", id="ufw-acl-iface",
                  classes="ufw-form-inp"),
            classes="ufw-form-row",
        ))
        scroll.mount(Horizontal(
            Button("Add ACL Rule", id="ufw-add-acl", classes="ufw-act-btn"),
        ))

    def _ufw_render_mgmt(self, scroll) -> None:
        rules = self._ufw_rules_num
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
        scroll.mount(Static("\n".join(lines), classes="ufw-info"))
        scroll.mount(Static("[bright_black] --- Delete Rule ---[/]", classes="ufw-sep"))
        scroll.mount(Horizontal(
            Static("Rule #  ", classes="ufw-form-lbl"),
            Input(placeholder="e.g. 2", id="ufw-inp-del", classes="ufw-form-inp"),
            classes="ufw-form-row",
        ))
        scroll.mount(Horizontal(
            Button("Queue Delete",  id="ufw-del",      classes="ufw-del-btn"),
            Button("Refresh List",  id="ufw-ref-mgmt", classes="ufw-act-btn"),
        ))

    def _ufw_render_profile(self, scroll) -> None:
        _PORTS = [
            ("22",   "tcp", "SSH"),
            ("5601", "tcp", "Kibana"),
            ("9200", "tcp", "Elasticsearch"),
            ("5044", "tcp", "Logstash Beats"),
            ("9092", "tcp", "Kafka"),
            ("2181", "tcp", "Zookeeper"),
            ("9500", "tcp", "MNX DPI"),
        ]
        lines = [f" [cyan]{p}/{pr}[/cyan]  {d}" for p, pr, d in _PORTS]
        scroll.mount(Static(
            "MNX default open ports preset.\nQueues rules below then press Apply.",
            classes="ufw-info",
        ))
        scroll.mount(Static("\n".join(lines), classes="ufw-info"))
        scroll.mount(Horizontal(
            Button("Apply MNX Profile", id="ufw-mnx-profile", classes="ufw-act-btn"),
        ))
        # store for use in button handler
        self._ufw_profile_ports = _PORTS

    def _ufw_render_pending_widget(self, scroll) -> None:
        # 이미 존재하면 update만, 없으면 새로 mount
        try:
            w = scroll.query_one("#ufw-pending", Static)
            if not self._ufw_pending:
                w.update("[bright_black] No pending UFW commands.[/]")
            else:
                parts = [f"[yellow]Pending({len(self._ufw_pending)}):[/]"]
                for c in self._ufw_pending:
                    parts.append(f" [cyan]>[/] {markup_escape(c)}")
                w.update("\n".join(parts))
            return
        except Exception:
            pass
        if not self._ufw_pending:
            scroll.mount(Static("[bright_black] No pending UFW commands.[/]", id="ufw-pending"))
        else:
            parts = [f"[yellow]Pending({len(self._ufw_pending)}):[/]"]
            for c in self._ufw_pending:
                parts.append(f" [cyan]>[/] {markup_escape(c)}")
            scroll.mount(Static("\n".join(parts), id="ufw-pending"))

    def _ufw_update_pending_widget(self) -> None:
        try:
            w = self.query_one("#ufw-pending", Static)
            if not self._ufw_pending:
                w.update("[bright_black] No pending UFW commands.[/]")
            else:
                parts = [f"[yellow]Pending({len(self._ufw_pending)}):[/]"]
                for c in self._ufw_pending:
                    parts.append(f" [cyan]>[/] {markup_escape(c)}")
                w.update("\n".join(parts))
        except Exception:
            pass
        active = self._ufw_status.get("active", False)
        state  = "ACTIVE" if active else "INACTIVE"
        self._set_status(
            f"UFW:{state}  pending={len(self._ufw_pending)}  Ctrl+S=Apply  ESC=Clear"
        )

    def _ufw_add_pending(self, cmd: str) -> None:
        if cmd not in self._ufw_pending:
            self._ufw_pending.append(cmd)
        self._ufw_update_pending_widget()

    def _ufw_clear_pending(self) -> None:
        self._ufw_pending.clear()
        self._ufw_update_pending_widget()

    def _ufw_execute_pending(self) -> None:
        if not self._ufw_pending:
            self._set_status("No pending UFW commands")
            return
        cmds = list(self._ufw_pending)
        self._set_status(f"[yellow]Running {len(cmds)} UFW command(s)...[/]")

        def _run():
            try:
                ok, out = self._ufw_mgr.execute(cmds)
                self.app.call_from_thread(self._ufw_on_apply_done, ok, out, cmds)
            except Exception as _e:
                self.app.call_from_thread(
                    self._set_status, f"[red]UFW 실행 오류: {_e}[/]", True
                )

        import threading as _threading
        _threading.Thread(target=_run, daemon=True).start()

    def _ufw_on_apply_done(self, ok: bool, output: str, cmds: list) -> None:
        if ok:
            self._ufw_pending.clear()
            self._ufw_bg_refresh(
                lambda: self._ufw_render_section(self._current_section)
            )
            self.app.notify(
                f"{len(cmds)} UFW command(s) applied successfully.",
                title="UFW Apply OK",
            )
        else:
            excerpt = markup_escape(output[:200].replace("\n", " | "))
            self._set_status(f"[red]UFW Apply FAILED:[/] {excerpt}", True)
            self.app.notify(output[:300], title="UFW Apply FAILED", severity="error")

    def _ufw_handle_button(self, bid: str) -> None:
        import re as _re
        mgr = self._ufw_mgr

        # STATUS tab buttons
        if bid == "ufw-enable":
            self._ufw_queue_enable_safe(); return
        if bid == "ufw-disable":
            self._ufw_add_pending(mgr.cmd_disable())
            self._set_status("Queued: ufw disable"); return
        if bid == "ufw-reset":
            self._ufw_confirm_reset(); return
        if bid == "ufw-logging":
            lv = self._ufw_status.get("logging", "off")
            nl = "off" if "off" not in lv.lower() else "on"
            self._ufw_add_pending(mgr.cmd_logging(nl))
            self._set_status(f"Queued: ufw logging {nl}"); return
        if bid == "ufw-log-med":
            self._ufw_add_pending(mgr.cmd_logging("medium"))
            self._set_status("Queued: ufw logging medium"); return

        # POLICY radio buttons
        if bid.startswith("ufw-pi-"):
            self._ufw_pol_in = bid[len("ufw-pi-"):]
            self._ufw_render_section("fw_policy"); return
        if bid.startswith("ufw-po-"):
            self._ufw_pol_out = bid[len("ufw-po-"):]
            self._ufw_render_section("fw_policy"); return
        if bid == "ufw-policy-q":
            self._ufw_queue_policy(); return

        # RULES radio/buttons
        if bid.startswith("ufw-ra-"):
            self._ufw_rule_act = bid[len("ufw-ra-"):]
            self._ufw_render_section("fw_rules"); return
        if bid.startswith("ufw-rp-"):
            self._ufw_rule_proto = bid[len("ufw-rp-"):]
            self._ufw_render_section("fw_rules"); return
        if bid == "ufw-add-rule":
            self._ufw_queue_add_rule(); return

        # ACL radio/buttons
        if bid.startswith("ufw-aa-"):
            self._ufw_acl_act = bid[len("ufw-aa-"):]
            self._ufw_render_section("fw_acl"); return
        if bid.startswith("ufw-ap-"):
            self._ufw_acl_proto = bid[len("ufw-ap-"):]
            self._ufw_render_section("fw_acl"); return
        if bid == "ufw-add-acl":
            self._ufw_queue_add_acl(); return

        # MGMT buttons
        if bid == "ufw-del":
            self._ufw_queue_delete(); return
        if bid == "ufw-ref-mgmt":
            self._ufw_bg_refresh(lambda: self._ufw_render_section("fw_mgmt")); return

        # PROFILE
        if bid == "ufw-mnx-profile":
            self._ufw_queue_profile(); return

    def _ufw_queue_enable_safe(self) -> None:
        import re as _re
        rules      = self._ufw_status.get("rules", [])
        ssh_live   = any(
            _re.search(r"\b22\b", r.get("to", "")) and r.get("action") == "ALLOW"
            for r in rules
        )
        ssh_queued = any(_re.search(r"allow\s+22", c, _re.I) for c in self._ufw_pending)
        if not ssh_live and not ssh_queued:
            ssh_cmd    = self._ufw_mgr.cmd_port_rule("allow", "22", "tcp")
            enable_cmd = self._ufw_mgr.cmd_enable()
            if ssh_cmd not in self._ufw_pending:
                self._ufw_pending.append(ssh_cmd)
            if enable_cmd not in self._ufw_pending:
                self._ufw_pending.append(enable_cmd)
            self._ufw_update_pending_widget()
            self._set_status("[yellow]No SSH rule - allow 22/tcp prepended before enable[/]")
        else:
            self._ufw_add_pending(self._ufw_mgr.cmd_enable())
            self._set_status("Queued: ufw enable")

    def _ufw_confirm_reset(self) -> None:
        self.app.notify(
            "To reset UFW: queue is cleared and 'ufw --force reset' will be executed on Apply.\n"
            "Type 'ufw-reset-confirm' to proceed.",
            title="UFW Reset Warning",
            severity="warning",
        )
        self._ufw_add_pending(self._ufw_mgr.cmd_reset())
        self._set_status("[red]Queued: ufw --force reset  (Apply to execute)[/]")

    def _ufw_queue_policy(self) -> None:
        s   = self._ufw_status
        ci  = s.get("incoming", "deny")
        co  = s.get("outgoing", "allow")
        chg = False
        if self._ufw_pol_in != ci:
            self._ufw_add_pending(self._ufw_mgr.cmd_policy("incoming", self._ufw_pol_in))
            chg = True
        if self._ufw_pol_out != co:
            self._ufw_add_pending(self._ufw_mgr.cmd_policy("outgoing", self._ufw_pol_out))
            chg = True
        if chg:
            self._set_status(f"Queued: incoming={self._ufw_pol_in} outgoing={self._ufw_pol_out}")
        else:
            self._set_status("No change (already same as current policy)")

    def _ufw_queue_add_rule(self) -> None:
        try:
            pv = self.query_one("#ufw-inp-port", Input).value.strip()
        except Exception:
            pv = ""
        if not pv:
            self._set_status("Port required", True); return
        re_end = ""
        if ":" in pv:
            parts  = pv.split(":", 1)
            pv     = parts[0].strip()
            re_end = parts[1].strip()
        cmd = self._ufw_mgr.cmd_port_rule(self._ufw_rule_act, pv, self._ufw_rule_proto, re_end)
        self._ufw_add_pending(cmd)
        self._set_status(f"Queued: {cmd}")
        try:
            self.query_one("#ufw-inp-port", Input).value = ""
        except Exception:
            pass

    def _ufw_queue_add_acl(self) -> None:
        try:
            ip    = self.query_one("#ufw-acl-ip",   Input).value.strip()
            sub   = self.query_one("#ufw-acl-sub",  Input).value.strip()
            port  = self.query_one("#ufw-acl-port", Input).value.strip()
            iface = self.query_one("#ufw-acl-iface",Input).value.strip()
        except Exception:
            self._set_status("Form read error", True); return
        if not ip:
            self._set_status("Source IP required", True); return
        source = f"{ip}/{sub}" if sub else ip
        cmd = self._ufw_mgr.cmd_acl(self._ufw_acl_act, source, port, self._ufw_acl_proto, iface)
        self._ufw_add_pending(cmd)
        self._set_status(f"Queued: {cmd}")
        for fid in ("#ufw-acl-ip", "#ufw-acl-sub", "#ufw-acl-port", "#ufw-acl-iface"):
            try:
                self.query_one(fid, Input).value = ""
            except Exception:
                pass

    def _ufw_queue_delete(self) -> None:
        try:
            ns = self.query_one("#ufw-inp-del", Input).value.strip()
        except Exception:
            ns = ""
        if not ns.isdigit():
            self._set_status("Enter a valid rule number", True); return
        cmd = self._ufw_mgr.cmd_delete(int(ns))
        self._ufw_add_pending(cmd)
        self._set_status(f"Queued: {cmd}")

    def _ufw_queue_profile(self) -> None:
        _PORTS = getattr(self, "_ufw_profile_ports", [
            ("22","tcp","SSH"),("5601","tcp","Kibana"),("9200","tcp","Elasticsearch"),
            ("5044","tcp","Logstash Beats"),("9092","tcp","Kafka"),
            ("2181","tcp","Zookeeper"),("9500","tcp","MNX DPI"),
        ])
        added = 0
        for port, proto, _ in _PORTS:
            cmd = self._ufw_mgr.cmd_port_rule("allow", port, proto)
            if cmd not in self._ufw_pending:
                self._ufw_pending.append(cmd)
                added += 1
        self._ufw_update_pending_widget()
        self._set_status(f"MNX Profile: {added} rules queued")


    def action_refresh(self) -> None:
        if self._current_section and self._current_section not in ("disk_perf", "sys_power"):
            self._show_section(self._current_section)

    # ── Number key selection for disk_perf ───────────────────────────────────

    def on_key(self, event: events.Key) -> None:
        """Handle keys for disk_perf section (S/T/R actions, 1-4 list selection).

        on_key fires in the bubble-up phase — after the focused widget has already
        processed the key — so Input fields in other sections are not affected.
        """
        if self._current_section != "disk_perf":
            return
        key = event.key

        # ── S / T / R — test control ─────────────────────────────────────────
        if key == "s":
            self.action_start_test()
            return
        if key == "t":
            self.action_stop_test()
            return

        # ── Tab — toggle active selection area ────────────────────────────────
        if key == "tab":
            self._perf_focus = "mode" if self._perf_focus == "target" else "target"
            self._refresh_selections()
            event.prevent_default()
            return

        # ── Number keys — state-based selection (no ListView dependency) ──────
        if self._perf_focus == "target" and key in ("1", "2", "3", "4"):
            self._test_target = ["application", "data", "pipeline", "all"][int(key) - 1]
            self._refresh_selections()
        elif self._perf_focus == "mode" and key in ("1", "2", "3"):
            self._test_mode = ["quick", "standard", "stress"][int(key) - 1]
            self._refresh_selections()
