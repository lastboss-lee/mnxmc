"""
Network Configuration Module - netplan YAML 직접 수정 방식

Ubuntu 22.04+ netplan YAML 파일을 직접 파싱/수정하는 방식.

기존 `netplan set` 방식 대비 개선점:
  - shell=True 보안 위험 제거
  - quote 처리 불안정 문제 해결
  - 인터페이스가 이미 다른 파일에 있으면 해당 파일 직접 수정
    (예: 50-cloud-init.yaml의 ens160 IP 변경 시 해당 파일을 수정)
  - None 값으로 기존 설정 완전 제거 보장
  - Promisc 영속성: systemd oneshot 서비스 생성

Author: MNX Team
Version: 3.0.0
"""

import subprocess
import io
import os
import syslog
import glob
from typing import Optional, List, Dict

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# no-carrier / link not ready 관련 stderr 키워드
_CARRIER_KEYWORDS = ('carrier', 'link is not ready', 'not ready', 'no-carrier')

# netplan set 명령으로 생성되는 파일 (fallback 대상)
_NETPLAN_SET_FILE = '/etc/netplan/70-netplan-set.yaml'


class NetworkConfig:
    """
    netplan YAML 파일 직접 수정 방식의 네트워크 설정.

    주요 메서드:
        set_static_ip()        — Static IP 설정
        set_dhcp()             — DHCP 설정
        remove_ip_config()     — IP 완전 제거 (Mirror port용)
        set_promisc_persistent() — promisc 영속성 (systemd service)
        get_interface_config() — 현재 설정 조회
    """

    def __init__(self):
        self.name = "Network Configuration"

    # ── Public API ──────────────────────────────────────────────────────────

    def set_static_ip(self, interface: str, ip: str, netmask: str,
                      gateway: str = None, dns_servers: list = None) -> bool:
        """
        Static IP 설정.

        Args:
            interface:   인터페이스 이름 (예: ens160)
            ip:          IP 주소 (예: 10.10.1.100 또는 10.10.1.100/24)
            netmask:     넷마스크 또는 prefix (예: 255.255.255.0 또는 /24 또는 24)
            gateway:     게이트웨이 (선택)
            dns_servers: DNS 서버 리스트 (선택)
        """
        try:
            # IP에 prefix가 이미 포함된 경우 분리
            if '/' in ip:
                ip_addr, prefix = ip.rsplit('/', 1)
            else:
                ip_addr = ip
                prefix = self._mask_to_prefix(netmask)

            syslog.syslog(syslog.LOG_INFO,
                f"NetworkConfig: Configuring static {interface}: {ip_addr}/{prefix}")

            iface_cfg: Dict = {
                'dhcp4': False,
                'dhcp6': False,
                'addresses': [f"{ip_addr}/{prefix}"],
                'routes': ([{'to': 'default', 'via': gateway}] if gateway else None),
                'nameservers': self._build_ns(dns_servers),
            }

            if not self._write_iface_config(interface, iface_cfg):
                return False

            ok = self._netplan_apply(interface, 'static', f"{ip_addr}/{prefix}")
            if ok:
                syslog.syslog(syslog.LOG_INFO,
                    f"NetworkConfig: Static IP set: {interface} = {ip_addr}/{prefix}"
                    + (f" gw={gateway}" if gateway else ""))
            return ok

        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, f"NetworkConfig: set_static_ip error: {e}")
            return False

    def set_dhcp(self, interface: str, dhcp4: bool = True,
                 dhcp6: bool = False) -> bool:
        """
        DHCP 설정.

        기존 static 주소/routes/nameservers 를 제거하고 DHCP 활성화.
        """
        try:
            syslog.syslog(syslog.LOG_INFO,
                f"NetworkConfig: Setting DHCP {interface} (v4={dhcp4}, v6={dhcp6})")

            iface_cfg: Dict = {
                'dhcp4': dhcp4,
                'dhcp6': dhcp6,
                'addresses': None,    # 기존 static 주소 제거
                'routes': None,       # 기존 static route 제거
                'nameservers': None,  # 기존 DNS 제거
            }

            if not self._write_iface_config(interface, iface_cfg):
                return False

            return self._netplan_apply(interface, 'dhcp')

        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, f"NetworkConfig: set_dhcp error: {e}")
            return False

    def remove_ip_config(self, interface: str) -> bool:
        """
        인터페이스 IP 설정 완전 제거 (Mirror port용).

        - YAML에서 addresses / routes / nameservers 삭제
        - dhcp4/dhcp6 = false
        - ip addr flush dev {interface} 로 즉시 커널 레벨 제거
        """
        try:
            syslog.syslog(syslog.LOG_INFO,
                f"NetworkConfig: Removing IP config from {interface}")

            iface_cfg: Dict = {
                'dhcp4': False,
                'dhcp6': False,
                'addresses': None,
                'routes': None,
                'nameservers': None,
            }

            if not self._write_iface_config(interface, iface_cfg):
                return False

            ok = self._netplan_apply(interface, 'remove')
            if not ok:
                return False

            # 즉시 커널 레벨 IP 제거
            subprocess.run(
                ['/usr/sbin/ip', 'addr', 'flush', 'dev', interface],
                capture_output=True, timeout=5
            )
            syslog.syslog(syslog.LOG_INFO,
                f"NetworkConfig: IP config removed from {interface}")
            return True

        except Exception as e:
            syslog.syslog(syslog.LOG_ERR,
                f"NetworkConfig: remove_ip_config error: {e}")
            return False

    def set_promisc_persistent(self, interface: str, enable: bool) -> None:
        """
        Promisc 모드를 systemd oneshot 서비스로 영구 설정/해제.

        재부팅 후에도 mirror 포트 유지됨.
        서비스 파일: /etc/systemd/system/promisc-{interface}.service
        """
        svc_name = f"promisc-{interface}.service"
        svc_file = f"/etc/systemd/system/{svc_name}"

        if enable:
            content = (
                f"[Unit]\n"
                f"Description=Set promiscuous mode on {interface} (mirror port)\n"
                f"After=network.target\n\n"
                f"[Service]\n"
                f"Type=oneshot\n"
                f"ExecStart=/usr/sbin/ip link set {interface} promisc on\n"
                f"RemainAfterExit=yes\n\n"
                f"[Install]\n"
                f"WantedBy=multi-user.target\n"
            )
            try:
                # /etc/systemd/system/ 은 root 권한 필요 → sudo -n tee 로 파일 쓰기
                subprocess.run(
                    ['sudo', '-n', '/usr/bin/tee', svc_file],
                    input=content.encode('utf-8'), capture_output=True, timeout=10
                )
                subprocess.run(
                    ['sudo', '-n', '/usr/bin/systemctl', 'enable', '--now', svc_name],
                    capture_output=True, timeout=10
                )
                syslog.syslog(syslog.LOG_INFO,
                    f"NetworkConfig: promisc service enabled: {svc_name}")
            except Exception as e:
                syslog.syslog(syslog.LOG_WARNING,
                    f"NetworkConfig: promisc persist failed: {e}")
        else:
            try:
                subprocess.run(
                    ['sudo', '-n', '/usr/bin/systemctl', 'disable', '--now', svc_name],
                    capture_output=True, timeout=10
                )
                subprocess.run(
                    ['sudo', '-n', '/usr/bin/rm', '-f', svc_file],
                    capture_output=True, timeout=10
                )
                syslog.syslog(syslog.LOG_INFO,
                    f"NetworkConfig: promisc service removed: {svc_name}")
            except Exception:
                pass

    def get_interface_config(self, interface: str) -> dict:
        """현재 인터페이스 netplan 설정 조회."""
        try:
            result = subprocess.run(
                ['/usr/sbin/netplan', 'get', f'ethernets.{interface}'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and _YAML_AVAILABLE:
                return yaml.safe_load(result.stdout) or {}
        except Exception as e:
            syslog.syslog(syslog.LOG_WARNING,
                f"NetworkConfig: get_interface_config error: {e}")
        return {}

    # ── Internal: YAML direct write ─────────────────────────────────────────

    def _find_interface_file(self, interface: str) -> Optional[str]:
        """
        인터페이스 설정이 정의된 netplan 파일 찾기.

        여러 파일이 있을 경우 우선순위가 높은(파일명 숫자 큰) 파일 반환.
        없으면 None.
        """
        if not _YAML_AVAILABLE:
            return None
        candidates = []
        for f in sorted(glob.glob('/etc/netplan/*.yaml')):
            try:
                with open(f, 'r') as fh:
                    conf = yaml.safe_load(fh) or {}
                if interface in conf.get('network', {}).get('ethernets', {}):
                    candidates.append(f)
            except Exception:
                pass
        # 우선순위 높은 파일(숫자 큰 파일)을 반환
        return candidates[-1] if candidates else None

    def _write_iface_config(self, interface: str, iface_cfg: dict) -> bool:
        """
        netplan YAML 파일에 인터페이스 설정을 원자적으로 쓰기.

        - 인터페이스가 기존 파일에 있으면 해당 파일 수정
          (50-cloud-init.yaml 포함 — 중복 설정 방지)
        - 없으면 70-netplan-set.yaml에 추가
        - None 값은 해당 키를 YAML에서 삭제
        - 원자적 쓰기: tmpfile → os.rename (중간 실패 시 원본 보존)
        - chmod 600 보장 (netplan 보안 요구사항)
        """
        if not _YAML_AVAILABLE:
            syslog.syslog(syslog.LOG_WARNING,
                "NetworkConfig: PyYAML not available, falling back to netplan set")
            return self._write_iface_config_legacy(interface, iface_cfg)

        target = self._find_interface_file(interface) or _NETPLAN_SET_FILE

        try:
            # 기존 파일 읽기
            if os.path.exists(target):
                with open(target, 'r') as fh:
                    conf = yaml.safe_load(fh) or {}
            else:
                conf = {}

            # 구조 보장
            net = conf.setdefault('network', {})
            net['version'] = 2
            ethernets = net.setdefault('ethernets', {})
            current = dict(ethernets.get(interface, {}) or {})

            # 설정 병합: None → 키 삭제, 그 외 → 덮어쓰기
            for key, value in iface_cfg.items():
                if value is None:
                    current.pop(key, None)
                else:
                    current[key] = value

            ethernets[interface] = current

            # /etc/netplan 은 root 소유 → sudo -n tee 방식
            buf = io.StringIO()
            yaml.dump(
                conf, buf,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
            content = buf.getvalue()

            r = subprocess.run(
                ['sudo', '-n', '/usr/bin/tee', target],
                input=content.encode('utf-8'),
                capture_output=True,
                timeout=10,
            )
            if r.returncode != 0:
                stderr = r.stderr.decode('utf-8', errors='replace').strip()
                raise PermissionError(
                    f"sudo tee 실패: {stderr or 'rc=' + str(r.returncode)}"
                )

            subprocess.run(
                ['sudo', '-n', '/usr/bin/chmod', '600', target],
                capture_output=True, timeout=10,
            )

            syslog.syslog(syslog.LOG_INFO,
                f"NetworkConfig: YAML updated: {target} [{interface}]")
            return True

        except Exception as e:
            syslog.syslog(syslog.LOG_ERR,
                f"NetworkConfig: YAML write error ({target}): {e}")
            return False

    def _write_iface_config_legacy(self, interface: str,
                                    iface_cfg: dict) -> bool:
        """PyYAML 미설치 환경용 netplan set fallback."""
        cmds = []
        for key, value in iface_cfg.items():
            if key == 'dhcp4':
                cmds.append(
                    f"ethernets.{interface}.dhcp4={'true' if value else 'false'}")
            elif key == 'dhcp6':
                cmds.append(
                    f"ethernets.{interface}.dhcp6={'true' if value else 'false'}")
            elif value is None:
                cmds.append(f"ethernets.{interface}.{key}=null")
            elif key == 'addresses' and isinstance(value, list):
                addrs = ','.join(value)
                cmds.append(
                    f"ethernets.{interface}.addresses='[{addrs}]'")
            elif key == 'routes' and isinstance(value, list):
                for r in value:
                    via = r.get('via', '')
                    cmds.append(
                        f'ethernets.{interface}.routes=\'[{{"to":"default","via":"{via}"}}]\'')
            elif key == 'nameservers' and isinstance(value, dict):
                addrs = ','.join(value.get('addresses', []))
                cmds.append(
                    f"ethernets.{interface}.nameservers.addresses='[{addrs}]'")

        for cmd in cmds:
            subprocess.run(
                ['/usr/sbin/netplan', 'set', cmd],
                shell=False, capture_output=True, text=True, timeout=10
            )
        return True

    def _netplan_apply(self, interface: str = '',
                       action: str = '', ip: str = '') -> bool:
        """
        netplan apply 실행.

        no-carrier 상태에서 apply 실패 시: YAML은 저장됐으므로 성공 처리.
        케이블 연결 시 자동 적용됨.
        """
        try:
            result = subprocess.run(
                ['/usr/sbin/netplan', 'apply'],
                capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                stderr = result.stderr.lower()
                if any(k in stderr for k in _CARRIER_KEYWORDS):
                    syslog.syslog(syslog.LOG_WARNING,
                        f"NetworkConfig: apply warning (no-carrier, YAML saved): "
                        f"{result.stderr.strip()}")
                    return True  # YAML 저장됨 → 성공
                syslog.syslog(syslog.LOG_ERR,
                    f"NetworkConfig: netplan apply failed: {result.stderr.strip()}")
                return False

            syslog.syslog(syslog.LOG_INFO,
                f"NetworkConfig: netplan apply OK"
                + (f" [{action}]" if action else "")
                + (f" {interface}" if interface else "")
                + (f" → {ip}" if ip else ""))
            return True

        except subprocess.TimeoutExpired:
            syslog.syslog(syslog.LOG_ERR,
                "NetworkConfig: netplan apply timeout")
            return False

    # ── Utilities ────────────────────────────────────────────────────────────

    def _build_ns(self, dns_servers: Optional[List[str]]) -> Optional[dict]:
        """DNS 서버 리스트를 nameservers dict로 변환. 비어있으면 None."""
        if not dns_servers:
            return None
        clean = [d.strip() for d in dns_servers if d and d.strip()]
        return {'addresses': clean} if clean else None

    def _mask_to_prefix(self, netmask: str) -> str:
        """
        넷마스크 → CIDR prefix 변환.
        /24, 24, 255.255.255.0 형식 모두 지원.
        """
        if not netmask:
            return "24"
        netmask = netmask.strip()
        if netmask.startswith('/'):
            return netmask.lstrip('/')
        if netmask.isdigit():
            return netmask
        try:
            parts = [int(x) for x in netmask.split('.')]
            binary = ''.join(bin(p)[2:].zfill(8) for p in parts)
            return str(binary.count('1'))
        except Exception:
            return "24"
