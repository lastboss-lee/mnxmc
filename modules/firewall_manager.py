"""
UFW Firewall Manager

UFW 방화벽 상태 조회, 규칙 파싱, 명령 실행 백엔드 모듈.
"""

import os
import re
import shutil
import subprocess
import syslog

# PATH를 보강하여 getty/minimal 환경에서도 ufw를 찾을 수 있도록 한다.
_SBIN_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _full_env() -> dict:
    env = os.environ.copy()
    existing = env.get("PATH", "")
    env["PATH"] = _SBIN_PATH + (":" + existing if existing else "")
    return env


def _is_root() -> bool:
    """현재 프로세스가 root 권한으로 실행 중인지 확인한다."""
    return os.geteuid() == 0


class FirewallManager:
    """UFW 방화벽 관리자."""

    def __init__(self) -> None:
        self._ufw_path: str = shutil.which("ufw", path=_SBIN_PATH) or "ufw"

    def is_available(self) -> bool:
        return shutil.which("ufw", path=_SBIN_PATH) is not None

    def _build_ufw_args(self, ufw_sub_args: list) -> list:
        """ufw 실행 인자를 구성한다.

        root 권한이면 ufw를 직접 실행하고,
        그렇지 않으면 sudo -n을 prepend하여 NOPASSWD 설정 환경에서 동작하게 한다.
        MNXMC는 운영 환경에서 root 또는 NOPASSWD sudo 권한으로 실행된다.
        """
        base = [self._ufw_path] + ufw_sub_args
        if _is_root():
            return base
        sudo_path = shutil.which("sudo", path=_SBIN_PATH) or "sudo"
        return [sudo_path, "-n"] + base

    def _run_ufw(self, sub_args: list, timeout: int = 10) -> subprocess.CompletedProcess:
        """ufw 서브명령을 실행하고 CompletedProcess를 반환한다."""
        args = self._build_ufw_args(sub_args)
        return subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True,
            timeout=timeout,
            env=_full_env(),
        )

    # ── Status ─────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """ufw status verbose 파싱. 반환값: dict."""
        result = {
            "active":   False,
            "incoming": "deny",
            "outgoing": "allow",
            "logging":  "off",
            "rules":    [],
            "error":    None,
        }
        if not self.is_available():
            result["error"] = "ufw not installed"
            return result
        try:
            proc = self._run_ufw(["status", "verbose"])
            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                result["error"] = stderr if stderr else f"ufw exited with code {proc.returncode}"
                return result

            out = proc.stdout

            if re.search(r"Status:\s*active", out, re.I):
                result["active"] = True

            m = re.search(
                r"Default:\s*(\w+)\s*\(incoming\)[^,]*,\s*(\w+)\s*\(outgoing\)",
                out, re.I,
            )
            if m:
                result["incoming"] = m.group(1).lower()
                result["outgoing"] = m.group(2).lower()

            m = re.search(r"Logging:\s*(on|off)(?:\s*\((\w+)\))?", out, re.I)
            if m:
                if m.group(1).lower() == "on":
                    lvl = m.group(2) or "low"
                    result["logging"] = f"on ({lvl})"
                else:
                    result["logging"] = "off"

            # 규칙 테이블 파싱 (구분선 이후)
            in_table = False
            for line in out.splitlines():
                if re.match(r"^-{2,}\s+-{2,}\s+-{2,}", line):
                    in_table = True
                    continue
                if in_table and line.strip():
                    m = re.match(
                        r"^(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)\s+(?:IN|OUT|FWD)?\s+(.*)$",
                        line.strip(), re.I,
                    )
                    if m:
                        result["rules"].append({
                            "to":     m.group(1).strip(),
                            "action": m.group(2).upper(),
                            "from":   m.group(3).strip(),
                        })
        except Exception as e:
            result["error"] = str(e)
        return result

    def get_numbered_rules(self) -> list:
        """ufw status numbered 파싱. 반환값: list of dict."""
        rules = []
        if not self.is_available():
            return rules
        try:
            proc = self._run_ufw(["status", "numbered"])
            if proc.returncode != 0:
                return rules
            for line in proc.stdout.splitlines():
                m = re.match(
                    r"^\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)\s+(?:IN|OUT|FWD)?\s+(.*)$",
                    line.strip(), re.I,
                )
                if m:
                    rules.append({
                        "num":    int(m.group(1)),
                        "to":     m.group(2).strip(),
                        "action": m.group(3).upper(),
                        "from":   m.group(4).strip(),
                        "is_v6":  "(v6)" in m.group(2),
                    })
        except Exception:
            pass
        return rules

    # ── Execute ────────────────────────────────────────────────────────────────

    def execute(self, commands: list) -> tuple:
        """명령 목록 순차 실행. 반환값: (success: bool, output: str)."""
        if not self.is_available():
            return False, f"Error: ufw를 찾을 수 없습니다 (PATH={os.environ.get('PATH','')})"
        lines = []
        try:
            for cmd in commands:
                tokens = cmd.split()
                # 첫 번째 토큰이 'ufw'이면 권한 래핑 후 실행
                if tokens and tokens[0] == "ufw":
                    sub_args = tokens[1:]
                    proc = self._run_ufw(sub_args, timeout=30)
                else:
                    # ufw가 아닌 명령(향후 확장용)은 그대로 실행
                    proc = subprocess.run(
                        tokens,
                        stdin=subprocess.DEVNULL,
                        capture_output=True, text=True, timeout=30,
                        env=_full_env(),
                    )
                lines.append(f"$ {cmd}")
                if proc.stdout.strip():
                    lines.append(proc.stdout.strip())
                if proc.returncode != 0:
                    err = proc.stderr.strip()
                    if err:
                        lines.append(f"Error: {err}")
                    return False, "\n".join(lines)
                try:
                    syslog.syslog(syslog.LOG_INFO, f"[MNXMC][UFW] {cmd}")
                except Exception:
                    pass
            return True, "\n".join(lines)
        except Exception as e:
            lines.append(f"Exception: {e}")
            return False, "\n".join(lines)

    # ── Command builders ───────────────────────────────────────────────────────

    def cmd_enable(self) -> str:
        return "ufw --force enable"

    def cmd_disable(self) -> str:
        return "ufw disable"

    def cmd_reset(self) -> str:
        return "ufw --force reset"

    def cmd_policy(self, direction: str, policy: str) -> str:
        return f"ufw default {policy} {direction}"

    def cmd_port_rule(self, action: str, port: str, proto: str, range_end: str = "") -> str:
        if range_end:
            p = proto if proto != "both" else "tcp"
            return f"ufw {action} {port}:{range_end}/{p}"
        if proto == "both":
            return f"ufw {action} {port}"
        return f"ufw {action} {port}/{proto}"

    def cmd_acl(self, action: str, source: str, port: str = "",
                proto: str = "", interface: str = "") -> str:
        if interface:
            cmd = f"ufw allow in on {interface} from {source}"
        else:
            cmd = f"ufw {action} from {source}"
        if port:
            cmd += f" to any port {port}"
        if proto and proto not in ("all", "both"):
            cmd += f" proto {proto}"
        return cmd

    def cmd_delete(self, rule_num: int) -> str:
        return f"ufw --force delete {rule_num}"

    def cmd_logging(self, level: str = "on") -> str:
        """level: on | off | low | medium | high | full"""
        return f"ufw logging {level}"
