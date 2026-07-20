#!/usr/bin/env python3
# network_management/network_management.py - 완전한 코드

import subprocess
import json
import re
from typing import List, Optional, Dict

class NetworkInterface:
    """네트워크 인터페이스 정보"""

    def __init__(self, name: str):
        self.name = name
        self.status = "UNKNOWN"
        self.ip = "No IP"
        self.netmask = ""
        self.gateway = ""
        self.mac = ""
        self.mtu = 0
        self.speed = ""
        self.duplex = ""
        self.driver = ""
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.rx_packets = 0
        self.tx_packets = 0
        self.promisc = False  # Promiscuous mode 상태
        self.is_mirror = False  # Mirror port 설정 여부

    def update_info(self):
        """인터페이스 정보 업데이트"""
        try:
            # ip 명령으로 정보 수집
            result = subprocess.run(
                ['/usr/sbin/ip', '-j', 'addr', 'show', self.name],
                capture_output=True, text=True, check=True, timeout=5
            )
            data = json.loads(result.stdout)

            if data:
                iface_data = data[0]

                # 상태 (물리적 링크 상태 기준)
                flags = iface_data.get('flags', [])
                if "LOWER_UP" in flags:
                    self.status = "UP"        # 물리적 링크 연결됨
                elif "UP" in flags:
                    self.status = "NO-CARRIER" # 관리적 UP이지만 물리적 연결 없음
                else:
                    self.status = "DOWN"       # 인터페이스 비활성

                # Promiscuous mode 확인
                self.promisc = "PROMISC" in flags

                # MAC 주소
                self.mac = iface_data.get('address', 'N/A')

                # MTU
                self.mtu = iface_data.get('mtu', 0)

                # IP 주소
                addr_info = iface_data.get('addr_info', [])
                for addr in addr_info:
                    if addr.get('family') == 'inet':
                        self.ip = addr.get('local', 'No IP')
                        prefix = addr.get('prefixlen', 24)
                        self.netmask = self._prefix_to_netmask(prefix)
                        break

                # is_mirror: promisc이고 IP 없는 경우
                self.is_mirror = self.promisc and (not self.ip or self.ip == 'No IP')

            # ethtool로 추가 정보
            self._update_ethtool_info()

            # 통계 정보
            self._update_statistics()

            # Gateway
            self._update_gateway()

        except Exception:
            pass

    def _update_ethtool_info(self):
        """ethtool로 속도/duplex/driver 정보"""
        try:
            # Speed & Duplex
            result = subprocess.run(
                ['/usr/sbin/ethtool', self.name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                output = result.stdout

                # Speed
                speed_match = re.search(r'Speed:\s*(\d+\w+/s)', output)
                if speed_match:
                    self.speed = speed_match.group(1)

                # Duplex
                duplex_match = re.search(r'Duplex:\s*(\w+)', output)
                if duplex_match:
                    self.duplex = duplex_match.group(1)

            # Driver
            result = subprocess.run(
                ['/usr/sbin/ethtool', '-i', self.name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                driver_match = re.search(r'driver:\s*(\S+)', result.stdout)
                if driver_match:
                    self.driver = driver_match.group(1)

        except Exception:
            pass

    def _update_statistics(self):
        """네트워크 통계 정보"""
        try:
            result = subprocess.run(
                ['/usr/sbin/ip', '-j', '-s', 'link', 'show', self.name],
                capture_output=True, text=True, check=True, timeout=5
            )
            data = json.loads(result.stdout)

            if data:
                stats = data[0].get('stats64', {})
                rx = stats.get('rx', {})
                tx = stats.get('tx', {})

                self.rx_bytes = rx.get('bytes', 0)
                self.rx_packets = rx.get('packets', 0)
                self.tx_bytes = tx.get('bytes', 0)
                self.tx_packets = tx.get('packets', 0)

        except Exception:
            pass

    def _update_gateway(self):
        """게이트웨이 정보"""
        try:
            result = subprocess.run(
                ['/usr/sbin/ip', 'route', 'show', 'dev', self.name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'default via' in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            self.gateway = parts[2]
                            break
        except Exception:
            pass

    def _prefix_to_netmask(self, prefix: int) -> str:
        """프리픽스를 넷마스크로 변환"""
        mask = (0xffffffff >> (32 - prefix)) << (32 - prefix)
        return f"{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}"


class NetworkManagement:
    """네트워크 관리 클래스"""

    def __init__(self):
        self.interfaces: List[NetworkInterface] = []
        self.selected_index = 0
        self.list_offset = 0
        self._interfaces_dict = {}

    def discover_interfaces(self) -> bool:
        """시스템의 모든 네트워크 인터페이스 검색"""
        try:
            result = subprocess.run(
                ['/usr/sbin/ip', '-j', 'link', 'show'],
                capture_output=True, text=True, check=True, timeout=5
            )
            data = json.loads(result.stdout)

            self.interfaces = []
            for iface_data in data:
                name = iface_data['ifname']
                # loopback 제외
                if name != 'lo':
                    ni = NetworkInterface(name)
                    ni.update_info()
                    self.interfaces.append(ni)

            # 선택 인덱스 초기화
            if self.selected_index >= len(self.interfaces):
                self.selected_index = 0

            return True

        except Exception:
            self.interfaces = []
            return False

    def move_selection(self, direction: int):
        """선택 이동 (순환)"""
        if not self.interfaces:
            return

        new_index = self.selected_index + direction

        # 순환 (맨 위 → 맨 아래, 맨 아래 → 맨 위)
        if new_index < 0:
            new_index = len(self.interfaces) - 1
        elif new_index >= len(self.interfaces):
            new_index = 0

        self.selected_index = new_index

    def move_selection_up(self):
        """선택을 위로 이동"""
        self.move_selection(-1)

    def move_selection_down(self):
        """선택을 아래로 이동"""
        self.move_selection(1)

    def reset_selection(self):
        """선택 초기화"""
        self.selected_index = 0
        self.list_offset = 0

    def get_selected_interface(self) -> Optional[NetworkInterface]:
        """현재 선택된 인터페이스 반환"""
        if 0 <= self.selected_index < len(self.interfaces):
            return self.interfaces[self.selected_index]
        return None

    def get_interface(self, name: str) -> Optional[NetworkInterface]:
        """이름으로 인터페이스 검색"""
        for iface in self.interfaces:
            if iface.name == name:
                return iface
        return None

    def refresh_interface(self, name: str) -> bool:
        """특정 인터페이스 정보 갱신"""
        iface = self.get_interface(name)
        if iface:
            iface.update_info()
            return True
        return False

    # ===== 기존 코드 호환용 메서드 =====

    def get_all_interfaces_info(self) -> Dict:
        """
        기존 코드 호환용 메서드
        모든 인터페이스 정보를 딕셔너리 형태로 반환
        """
        if not self.interfaces:
            self.discover_interfaces()

        result = {}
        for iface in self.interfaces:
            result[iface.name] = {
                'name': iface.name,
                'status': iface.status,
                'ip_addresses': [iface.ip] if iface.ip != "No IP" else [],
                'mac': iface.mac,
                'mtu': iface.mtu
            }
        return result

    def get_interface_info(self, interface_name: str) -> Optional[Dict]:
        """
        기존 코드 호환용 메서드
        특정 인터페이스 정보 반환
        """
        iface = self.get_interface(interface_name)
        if iface:
            iface.update_info()
            return {
                'name': iface.name,
                'status': iface.status,
                'ip_addresses': [iface.ip] if iface.ip != "No IP" else [],
                'mac': iface.mac,
                'mtu': iface.mtu,
                'speed': iface.speed,
                'duplex': iface.duplex,
                'driver': iface.driver
            }
        return None
        # network_management.py에 추가 (기존 NetworkManagement 클래스 내)
    def configure_static_ip(self, interface_name, ip_addr, netmask, gateway, dns_servers=None):
        """Static IP 설정 적용 (netplan set 방식)"""
        try:
            from network_management.network_config import NetworkConfig

            config = NetworkConfig()
            success = config.set_static_ip(interface_name, ip_addr, netmask, gateway, dns_servers)

            if success:
                # 인터페이스 정보 갱신
                self.refresh_interface(interface_name)

            return success

        except Exception as e:
            print(f"Static IP configuration failed: {e}")
            return False
