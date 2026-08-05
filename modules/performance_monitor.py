#!/usr/bin/env python3
import subprocess
import threading
import time
import os
import re
from modules.base_module import BaseModule

class PerformanceMonitor(BaseModule):
    def __init__(self):
        super().__init__("Performance Monitor")
        self._lock = threading.Lock()
        self.last_cpu_stats = None
        self.last_cpu_total_stats = None
        self.last_network_stats = {}
        self.last_time = None
        self.sar_available = self.check_sar_available()

    def check_sar_available(self):
        """SAR 명령어 사용 가능 여부 확인"""
        try:
            result = subprocess.run(['which', 'sar'], capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False

    def get_cpu_count(self):
        """CPU 코어 수 조회"""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                lines = f.readlines()
            return len([l for l in lines if l.startswith('processor')])
        except Exception:
            return 1

    def get_cpu_usage_per_core(self):
        """코어별 CPU 사용률 조회 - 128 코어까지 지원"""
        try:
            with open('/proc/stat', 'r') as f:
                lines = f.readlines()
            
            cpu_stats = []
            for line in lines:
                if line.startswith('cpu') and line[3:4].isdigit():
                    # cpu0, cpu1, cpu2, ... 라인들
                    parts = line.split()
                    core_id = int(parts[0][3:])
                    # user nice system idle iowait irq softirq steal guest guest_nice
                    stats = [int(x) for x in parts[1:8]]
                    cpu_stats.append((core_id, stats))
            
            # Lock으로 공유 상태 원자적 교체
            with self._lock:
                prev_cpu_stats = self.last_cpu_stats
                self.last_cpu_stats = cpu_stats

            # 이전 측정값이 있으면 변화율 계산 (Lock 밖에서)
            if prev_cpu_stats is not None:
                usage_per_core = []
                for i, (core_id, current_stats) in enumerate(cpu_stats):
                    if i < len(prev_cpu_stats):
                        _, prev_stats = prev_cpu_stats[i]

                        deltas = [current_stats[j] - prev_stats[j] for j in range(len(current_stats))]
                        total_delta = sum(deltas)

                        if total_delta > 0:
                            # idle = idle + iowait
                            idle_delta = deltas[3] + deltas[4] if len(deltas) > 4 else deltas[3]
                            cpu_usage = ((total_delta - idle_delta) / total_delta) * 100
                            usage_per_core.append((core_id, max(0, min(100, cpu_usage))))
                        else:
                            usage_per_core.append((core_id, 0.0))
                    else:
                        usage_per_core.append((core_id, 0.0))
                return usage_per_core
            else:
                # 첫 측정: 기준값만 저장하고 0.0 반환
                # 다음 타이머 사이클(1초 후)에 정확한 델타 계산됨
                return [(core_id, 0.0) for core_id, _ in cpu_stats]
                
        except Exception as e:
            return [(i, 0.0) for i in range(self.get_cpu_count())]

    def get_cpu_usage_total(self):
        """전체 CPU 사용률 — 직전 측정 대비 delta로 현재 사용률 계산"""
        try:
            with open('/proc/stat', 'r') as f:
                line = f.readline()  # 첫 번째 줄이 전체 cpu 합산

            current = [int(x) for x in line.split()[1:8]]

            with self._lock:
                prev = self.last_cpu_total_stats
                self.last_cpu_total_stats = current

            if prev is None:
                return 0.0

            deltas = [current[i] - prev[i] for i in range(len(current))]
            total_delta = sum(deltas)
            if total_delta <= 0:
                return 0.0
            idle_delta = deltas[3] + (deltas[4] if len(deltas) > 4 else 0)
            return max(0.0, min(100.0, ((total_delta - idle_delta) / total_delta) * 100))
        except Exception:
            return 0.0

    def get_memory_usage(self):
        """메모리 사용량 정보"""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.readlines()
            
            mem_total = 0
            mem_free = 0
            mem_available = 0
            mem_buffers = 0
            mem_cached = 0
            
            for line in meminfo:
                if line.startswith('MemTotal:'):
                    mem_total = int(line.split()[1])
                elif line.startswith('MemFree:'):
                    mem_free = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    mem_available = int(line.split()[1])
                elif line.startswith('Buffers:'):
                    mem_buffers = int(line.split()[1])
                elif line.startswith('Cached:'):
                    mem_cached = int(line.split()[1])
            
            # KB를 GB로 변환
            total_gb = mem_total / 1024 / 1024
            free_gb = mem_free / 1024 / 1024
            available_gb = mem_available / 1024 / 1024 if mem_available > 0 else free_gb
            used_gb = total_gb - available_gb
            
            usage_pct = (used_gb / total_gb) * 100 if total_gb > 0 else 0
            
            return {
                'total_gb': total_gb,
                'used_gb': used_gb,
                'free_gb': available_gb,
                'usage_pct': usage_pct
            }
            
        except Exception as e:
            return {
                'total_gb': 0,
                'used_gb': 0,
                'free_gb': 0,
                'usage_pct': 0,
                'error': str(e)
            }

    def get_enhanced_network_stats(self):
        """대폭 강화된 네트워크 통계 - 실시간 전송률, 인터페이스 상세정보, 에러통계 포함"""
        try:
            current_time = time.time()
            current_stats = {}
            
            # /proc/net/dev 파싱 - 기본 통계
            with open('/proc/net/dev', 'r') as f:
                lines = f.readlines()
            
            # 데이터 파싱
            for line in lines[2:]:  # 헤더 건너뛰기
                parts = line.split()
                if len(parts) >= 16:
                    if_name = parts[0].rstrip(':')
                    
                    # RX: bytes packets errs drop fifo frame compressed multicast
                    rx_bytes = int(parts[1])
                    rx_packets = int(parts[2])
                    rx_errs = int(parts[3])
                    rx_drop = int(parts[4])
                    rx_fifo = int(parts[5]) if len(parts) > 5 else 0
                    rx_frame = int(parts[6]) if len(parts) > 6 else 0
                    rx_multicast = int(parts[8]) if len(parts) > 8 else 0
                    
                    # TX: bytes packets errs drop fifo colls carrier compressed
                    tx_bytes = int(parts[9])
                    tx_packets = int(parts[10])
                    tx_errs = int(parts[11])
                    tx_drop = int(parts[12])
                    tx_fifo = int(parts[13]) if len(parts) > 13 else 0
                    tx_colls = int(parts[14]) if len(parts) > 14 else 0
                    tx_carrier = int(parts[15]) if len(parts) > 15 else 0
                    
                    current_stats[if_name] = {
                        # 기본 카운터
                        'rx_bytes': rx_bytes,
                        'tx_bytes': tx_bytes,
                        'rx_packets': rx_packets,
                        'tx_packets': tx_packets,
                        
                        # 에러 카운터
                        'rx_errors': rx_errs,
                        'tx_errors': tx_errs,
                        'rx_drops': rx_drop,
                        'tx_drops': tx_drop,
                        'rx_fifo': rx_fifo,
                        'tx_fifo': tx_fifo,
                        'rx_frame': rx_frame,
                        'tx_colls': tx_colls,
                        'tx_carrier': tx_carrier,
                        'rx_multicast': rx_multicast,
                        
                        # 실시간 전송률 (초기값)
                        'rx_rate_bps': 0,    # bytes per second
                        'tx_rate_bps': 0,
                        'rx_rate_kbps': 0,   # KB per second  
                        'tx_rate_kbps': 0,
                        'rx_rate_mbps': 0,   # MB per second
                        'tx_rate_mbps': 0,
                        'rx_rate_pps': 0,    # packets per second
                        'tx_rate_pps': 0,
                        
                        # 패킷 크기 평균
                        'rx_avg_size': 0,
                        'tx_avg_size': 0,
                        
                        # 인터페이스 상태 정보
                        'status': 'UNKNOWN',
                        'speed': 'Unknown',
                        'driver': 'Unknown',
                        'duplex': 'Unknown',
                        'mac': 'Unknown',
                        
                        # 사용률 (%)
                        'rx_utilization': 0.0,
                        'tx_utilization': 0.0
                    }
            
            # Lock으로 공유 상태 원자적 읽기
            with self._lock:
                prev_network_stats = self.last_network_stats
                prev_time = self.last_time

            # 전송률 계산 (이전 측정과 비교, Lock 밖에서)
            if prev_network_stats and prev_time:
                time_diff = current_time - prev_time

                if time_diff > 0:
                    for if_name in current_stats:
                        if if_name in prev_network_stats:
                            last = prev_network_stats[if_name]
                            curr = current_stats[if_name]
                            
                            # 바이트 전송률 계산
                            rx_diff = max(0, curr['rx_bytes'] - last['rx_bytes'])  
                            tx_diff = max(0, curr['tx_bytes'] - last['tx_bytes'])
                            
                            curr['rx_rate_bps'] = rx_diff / time_diff
                            curr['tx_rate_bps'] = tx_diff / time_diff
                            curr['rx_rate_kbps'] = curr['rx_rate_bps'] / 1024
                            curr['tx_rate_kbps'] = curr['tx_rate_bps'] / 1024
                            curr['rx_rate_mbps'] = curr['rx_rate_kbps'] / 1024
                            curr['tx_rate_mbps'] = curr['tx_rate_kbps'] / 1024
                            
                            # 패킷 전송률 계산
                            rx_pkt_diff = max(0, curr['rx_packets'] - last['rx_packets'])
                            tx_pkt_diff = max(0, curr['tx_packets'] - last['tx_packets'])
                            
                            curr['rx_rate_pps'] = rx_pkt_diff / time_diff
                            curr['tx_rate_pps'] = tx_pkt_diff / time_diff
                            
                            # 패킷 평균 크기 계산
                            if curr['rx_rate_pps'] > 0:
                                curr['rx_avg_size'] = int(curr['rx_rate_bps'] / curr['rx_rate_pps'])
                            if curr['tx_rate_pps'] > 0:
                                curr['tx_avg_size'] = int(curr['tx_rate_bps'] / curr['tx_rate_pps'])
            
            # 인터페이스 상세 정보 수집 (ethtool, ip 등)
            for if_name in current_stats:
                interface_info = self._get_detailed_interface_info(if_name)
                current_stats[if_name].update(interface_info)
                
                # 대역폭 사용률 계산
                speed_info = interface_info.get('speed_numeric', 0)
                if speed_info > 0:  # Mbps 단위
                    max_bps = speed_info * 1024 * 1024 / 8  # bits to bytes
                    curr = current_stats[if_name]
                    curr['rx_utilization'] = min(100.0, (curr['rx_rate_bps'] / max_bps) * 100)
                    curr['tx_utilization'] = min(100.0, (curr['tx_rate_bps'] / max_bps) * 100)
            
            # Lock으로 공유 상태 원자적 교체
            with self._lock:
                self.last_network_stats = {
                    name: {
                        'rx_bytes': stats['rx_bytes'],
                        'tx_bytes': stats['tx_bytes'],
                        'rx_packets': stats['rx_packets'],
                        'tx_packets': stats['tx_packets']
                    }
                    for name, stats in current_stats.items()
                }
                self.last_time = current_time
            
            return current_stats
            
        except Exception as e:
            return {'error': str(e)}

    def _get_detailed_interface_info(self, interface):
        """인터페이스 상세 정보 (ethtool, ip link 사용)"""
        details = {
            'status': 'UNKNOWN',
            'speed': 'Unknown',
            'speed_numeric': 0,  # Mbps 단위 숫자값
            'driver': 'Unknown',
            'duplex': 'Unknown',
            'mac': 'Unknown',
            'mtu': 'Unknown'
        }
        
        try:
            # 상태 및 MAC 주소 확인 (ip link)
            result = subprocess.run(['ip', 'link', 'show', interface],
                                  capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                output = result.stdout
                if 'state UP' in output:
                    details['status'] = 'UP'
                elif 'state DOWN' in output:
                    details['status'] = 'DOWN'
                
                # MAC 주소 추출
                import re
                mac_match = re.search(r'link/ether ([a-f0-9:]{17})', output)
                if mac_match:
                    details['mac'] = mac_match.group(1)
                
                # MTU 추출
                mtu_match = re.search(r'mtu (\d+)', output)
                if mtu_match:
                    details['mtu'] = mtu_match.group(1)
            
            # DOWN 상태면 ethtool 정보 수집하지 않음
            if details['status'] == 'DOWN':
                return details
            
            # ethtool로 속도/듀플렉스 정보
            result = subprocess.run(['ethtool', interface], 
                                  capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('Speed:'):
                        speed_str = line.split(':')[1].strip()
                        details['speed'] = speed_str
                        # 숫자값 추출 (Mbps)
                        speed_match = re.search(r'(\d+)', speed_str)
                        if speed_match:
                            details['speed_numeric'] = int(speed_match.group(1))
                    elif line.startswith('Duplex:'):
                        details['duplex'] = line.split(':')[1].strip()
            
            # 드라이버 정보
            result = subprocess.run(['ethtool', '-i', interface],
                                  capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('driver:'):
                        details['driver'] = line.split(':')[1].strip()
                        break
                        
        except Exception:
            pass
        
        return details

    def get_network_stats(self):
        """기존 호환성을 위한 간단한 네트워크 통계 (dashboard.py에서 사용)"""
        enhanced_stats = self.get_enhanced_network_stats()
        
        # 기본 형태로 변환
        simple_stats = {}
        for if_name, stats in enhanced_stats.items():
            if isinstance(stats, dict):
                simple_stats[if_name] = {
                    'rx_bytes': stats['rx_bytes'],
                    'tx_bytes': stats['tx_bytes'],
                    'rx_packets': stats['rx_packets'],
                    'tx_packets': stats['tx_packets'],
                    'rx_errors': stats['rx_errors'],
                    'tx_errors': stats['tx_errors'],
                    'rx_drops': stats['rx_drops'],
                    'tx_drops': stats['tx_drops']
                }
        
        return simple_stats

    def get_top_processes(self, count=15):
        """CPU 사용량이 높은 프로세스들 - 향상된 파싱"""
        try:
            result = subprocess.run(['ps', 'aux', '--sort=-%cpu'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                processes = []
                
                # 헤더 건너뛰기
                for line in lines[1:count+1]:
                    parts = line.split(None, 10)  # 최대 11개로 분할
                    if len(parts) >= 11:
                        try:
                            cpu_pct = float(parts[2])
                            mem_pct = float(parts[3])
                            
                            processes.append({
                                'user': parts[0][:10],  # 사용자명 10자 제한
                                'pid': parts[1],
                                'cpu': f"{cpu_pct:.1f}",
                                'mem': f"{mem_pct:.1f}",
                                'vsz': parts[4],
                                'rss': parts[5], 
                                'tty': parts[6],
                                'stat': parts[7],
                                'start': parts[8],
                                'time': parts[9],
                                'command': parts[10][:50]  # 명령어 50자로 제한
                            })
                        except (ValueError, IndexError):
                            continue
                
                return processes
            else:
                return []
                
        except Exception as e:
            return [{'error': str(e)}]

    def get_disk_io_stats(self):
        """디스크 I/O 통계"""
        try:
            disk_stats = {}
            
            with open('/proc/diskstats', 'r') as f:
                lines = f.readlines()
            
            for line in lines:
                parts = line.split()
                if len(parts) >= 14:
                    device = parts[2]
                    
                    # 주요 디스크만 (sda, nvme 등)
                    if not re.match(r'(sd[a-z]|nvme\d+n\d+|vd[a-z])$', device):
                        continue
                    
                    reads = int(parts[3])
                    read_sectors = int(parts[5])
                    writes = int(parts[7]) 
                    write_sectors = int(parts[9])
                    
                    disk_stats[device] = {
                        'reads': reads,
                        'writes': writes,
                        'read_bytes': read_sectors * 512,  # sectors * 512 bytes
                        'write_bytes': write_sectors * 512
                    }
            
            return disk_stats
            
        except Exception as e:
            return {'error': str(e)}

    def get_performance_summary(self):
        """전체 성능 정보 요약"""
        try:
            summary = {
                'cpu_total': self.get_cpu_usage_total(),
                'cpu_per_core': self.get_cpu_usage_per_core(),
                'memory': self.get_memory_usage(),
                'network': self.get_enhanced_network_stats(),  # 강화된 네트워크 통계 사용
                'disk': self.get_disk_io_stats(),
                'load_avg': self._get_load_average()
            }
            return summary
        except Exception as e:
            return {'error': str(e)}

    def _get_load_average(self):
        """로드 평균"""
        try:
            with open('/proc/loadavg', 'r') as f:
                load_data = f.read().strip().split()
                return {
                    '1min': float(load_data[0]),
                    '5min': float(load_data[1]),
                    '15min': float(load_data[2])
                }
        except Exception:
            return {'1min': 0.0, '5min': 0.0, '15min': 0.0}
