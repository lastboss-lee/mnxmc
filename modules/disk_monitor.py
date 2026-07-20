#!/usr/bin/env python3
"""
Disk I/O Monitor Module

마운트 포인트별 디스크 I/O 통계를 수집합니다.
iostat 또는 /proc/diskstats를 사용하여 실시간 I/O 성능을 모니터링합니다.

Features:
    - 마운트 포인트 → 디바이스 자동 매핑
    - 읽기/쓰기 MB/s, IOPS, await, util% 측정
    - 상태 판단 (NORMAL, BUSY, SATURATED)
"""

import subprocess
import os
import time
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class DiskMonitor:
    """디스크 I/O 모니터링 클래스."""
    
    # 모니터링할 마운트 포인트
    IMPORTANT_MOUNTS = [
        '/',
        '/docker',
        '/logs', 
        '/pipeline',
        '/application',
        '/data',
        '/dir_cache',
    ]
    
    # 상태 임계값 (util %)
    THRESHOLD_BUSY = 50
    THRESHOLD_SATURATED = 80
    
    def __init__(self):
        self._prev_stats = {}
        self._prev_time = None
        self._mount_device_map = {}
        self._device_mount_map = {}
        self._zfs_mount_pool_map = {}  # ZFS: {mount_point: pool_name}
        self._zfs_prev_stats = {}      # ZFS: {pool_name: {'stats': ..., 'time': ...}}

        # 초기 매핑 및 통계 수집
        self._update_mount_mapping()
        self._collect_initial_stats()
    
    def _update_mount_mapping(self) -> None:
        """마운트 포인트 → 디바이스 매핑 업데이트."""
        self._mount_device_map = {}
        self._device_mount_map = {}
        self._zfs_mount_pool_map = {}

        try:
            # findmnt로 마운트 정보 가져오기 (FSTYPE 포함)
            result = subprocess.run(
                ['findmnt', '-n', '-o', 'TARGET,SOURCE,FSTYPE', '-l'],
                capture_output=True, text=True, timeout=5
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line.strip():
                        continue

                    parts = line.split()
                    if len(parts) < 2:
                        continue

                    mount_point = parts[0]
                    source = parts[1]
                    fstype = parts[2] if len(parts) >= 3 else ''

                    # 바인드 마운트 경로 어노테이션 제거: /dev/sdb1[/subpath] → /dev/sdb1
                    source = source.split('[')[0].strip()

                    if mount_point not in self.IMPORTANT_MOUNTS:
                        continue

                    # ZFS 파일시스템 처리
                    if fstype == 'zfs':
                        pool_name = source.split('/')[0]
                        self._zfs_mount_pool_map[mount_point] = pool_name
                        self._mount_device_map[mount_point] = f'zfs:{pool_name}'
                        continue

                    # 일반 블록 디바이스 처리
                    device = self._extract_device_name(source)
                    if device:
                        self._mount_device_map[mount_point] = device
                        self._device_mount_map[device] = mount_point

        except Exception:
            pass
    
    def _extract_device_name(self, source: str) -> Optional[str]:
        """소스에서 디바이스 이름 추출."""
        if not source:
            return None

        # /dev/xxx 형태 처리
        if source.startswith('/dev/'):
            dev = source[5:]  # /dev/ 제거

            # mapper 디바이스 처리 (LVM) - 실제 dm-X 이름 해석
            if dev.startswith('mapper/'):
                mapper_name = dev[7:]  # mapper/ 이후 이름

                # 방법 1: os.path.realpath (심볼릭 링크 완전 해석)
                try:
                    real_path = os.path.realpath(source)
                    if real_path.startswith('/dev/dm-'):
                        return real_path[5:]  # dm-0, dm-1 등
                except Exception:
                    pass

                # 방법 2: os.readlink (심볼릭 링크 원본 읽기)
                try:
                    link_target = os.readlink(source)
                    dm_name = os.path.basename(link_target)
                    if dm_name.startswith('dm-') and dm_name[3:].isdigit():
                        return dm_name
                except Exception:
                    pass

                # 방법 3: dmsetup minor 번호 조회
                try:
                    result = subprocess.run(
                        ['dmsetup', 'info', '-c', '--noheadings', '-o', 'minor', mapper_name],
                        capture_output=True, text=True, timeout=3
                    )
                    if result.returncode == 0:
                        minor = result.stdout.strip()
                        if minor.isdigit():
                            return f'dm-{minor}'
                except Exception:
                    pass

                # 방법 4: /sys/block/dm-X/dm/name 검색
                try:
                    for dm_dev in sorted(os.listdir('/sys/block/')):
                        if not dm_dev.startswith('dm-'):
                            continue
                        try:
                            with open(f'/sys/block/{dm_dev}/dm/name') as f:
                                if f.read().strip() == mapper_name:
                                    return dm_dev
                        except Exception:
                            continue
                except Exception:
                    pass

                return None

            # 파티션 번호 제거하여 기본 디바이스 이름 가져오기
            base_dev = self._get_base_device(dev)
            return base_dev

        return None
    
    def _get_base_device(self, dev: str) -> str:
        """파티션에서 기본 디바이스 이름 추출."""
        # nvme0n1p1 -> nvme0n1
        nvme_match = re.match(r'(nvme\d+n\d+)p?\d*', dev)
        if nvme_match:
            return nvme_match.group(1)

        # sda1 -> sda, sdb2 -> sdb
        sd_match = re.match(r'(sd[a-z]+)\d*', dev)
        if sd_match:
            return sd_match.group(1)

        # md0p1 -> md0, md1 -> md1 (mdadm RAID)
        md_match = re.match(r'(md\d+)(?:p\d+)?$', dev)
        if md_match:
            return md_match.group(1)

        # dm-0 등은 그대로
        return dev
    
    def _collect_initial_stats(self) -> None:
        """초기 통계 수집."""
        self._prev_stats = self._read_diskstats()
        self._prev_time = time.time()

    def _read_zfs_cumulative(self, pool_name: str) -> Optional[dict]:
        """
        ZFS 풀 누적 I/O 통계 즉시 읽기 (논블로킹).

        인터벌 없이 호출 → 풀 임포트 이후 누적 통계를 즉시 반환.
        두 번 호출하여 델타를 계산하는 방식으로 rMBps/IOPS 산출.
        """
        try:
            result = subprocess.run(
                ['zpool', 'iostat', '-Hp', pool_name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return None

            lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
            if not lines:
                return None

            # 형식: pool\talloc\tfree\tread_ops\twrite_ops\tread_bytes\twrite_bytes
            parts = lines[0].split('\t')
            if len(parts) >= 7:
                def _parse(s):
                    try:
                        return int(s) if s not in ('-', '') else 0
                    except ValueError:
                        return 0

                return {
                    'read_ops':    _parse(parts[3]),
                    'write_ops':   _parse(parts[4]),
                    'read_bytes':  _parse(parts[5]),
                    'write_bytes': _parse(parts[6]),
                }
        except Exception:
            pass
        return None
    
    def _read_diskstats(self) -> Dict[str, Dict]:
        """
        /proc/diskstats에서 디스크 통계 읽기.
        
        Returns:
            디바이스별 통계 딕셔너리
        """
        stats = {}
        
        try:
            with open('/proc/diskstats', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 14:
                        continue
                    
                    device = parts[2]
                    
                    # 우리가 관심있는 디바이스만
                    if device not in self._device_mount_map and \
                       device not in [d for d in self._mount_device_map.values()]:
                        # 기본 디바이스인지 확인
                        is_relevant = False
                        for mount_dev in self._mount_device_map.values():
                            if device == mount_dev or device.startswith(mount_dev):
                                is_relevant = True
                                break
                        if not is_relevant:
                            continue
                    
                    # 통계 파싱
                    # Field  1 -- major number
                    # Field  2 -- minor number
                    # Field  3 -- device name
                    # Field  4 -- reads completed successfully
                    # Field  5 -- reads merged
                    # Field  6 -- sectors read
                    # Field  7 -- time spent reading (ms)
                    # Field  8 -- writes completed successfully
                    # Field  9 -- writes merged
                    # Field 10 -- sectors written
                    # Field 11 -- time spent writing (ms)
                    # Field 12 -- I/Os currently in progress
                    # Field 13 -- time spent doing I/Os (ms)
                    # Field 14 -- weighted time spent doing I/Os (ms)
                    
                    stats[device] = {
                        'reads': int(parts[3]),
                        'reads_merged': int(parts[4]),
                        'sectors_read': int(parts[5]),
                        'read_time_ms': int(parts[6]),
                        'writes': int(parts[7]),
                        'writes_merged': int(parts[8]),
                        'sectors_written': int(parts[9]),
                        'write_time_ms': int(parts[10]),
                        'io_in_progress': int(parts[11]),
                        'io_time_ms': int(parts[12]),
                        'weighted_io_time_ms': int(parts[13]),
                    }
        
        except Exception as e:
            pass
        
        return stats
    
    def get_disk_io_stats(self) -> Dict:
        """
        마운트 포인트별 디스크 I/O 통계 반환.
        
        Returns:
            {
                "timestamp": "2026-01-19T14:21:30+09:00",
                "mounts": [
                    {
                        "mount": "/",
                        "device": "sdc",
                        "rMBps": 42.5,
                        "wMBps": 11.2,
                        "iops": 120,
                        "await_ms": 3.1,
                        "util": 12,
                        "state": "NORMAL"
                    },
                    ...
                ]
            }
        """
        # 매핑 업데이트
        self._update_mount_mapping()

        # 현재 통계 읽기
        current_stats = self._read_diskstats()
        current_time = time.time()

        # 시간 간격 계산
        if self._prev_time is None:
            self._prev_stats = current_stats
            self._prev_time = current_time
            time.sleep(0.3)  # 첫 호출 시 짧은 대기 (ZFS는 별도 누적 방식)
            current_stats = self._read_diskstats()
            current_time = time.time()

        interval = current_time - self._prev_time
        if interval <= 0:
            interval = 1.0

        # ZFS 풀 누적 통계 일괄 수집 (논블로킹 - sleep 없음)
        zfs_pools = set(self._zfs_mount_pool_map.values())
        current_zfs_stats = {}
        for pool in zfs_pools:
            stats = self._read_zfs_cumulative(pool)
            if stats:
                current_zfs_stats[pool] = stats

        mounts = []

        for mount_point in self.IMPORTANT_MOUNTS:
            device = self._mount_device_map.get(mount_point)

            if not device:
                # 마운트되지 않은 경우
                mounts.append({
                    'mount': mount_point,
                    'device': 'N/A',
                    'rMBps': 0,
                    'wMBps': 0,
                    'iops': 0,
                    'await_ms': 0,
                    'util': 0,
                    'state': 'UNMOUNTED'
                })
                continue

            # ZFS 풀 처리 - 누적 통계 델타 계산 (논블로킹)
            if device.startswith('zfs:'):
                pool_name = device[4:]
                curr_z = current_zfs_stats.get(pool_name)
                prev_entry = self._zfs_prev_stats.get(pool_name)

                if curr_z and prev_entry:
                    prev_z = prev_entry['stats']
                    z_interval = current_time - prev_entry['time']
                    if z_interval <= 0:
                        z_interval = 1.0

                    rMBps = max(0, curr_z['read_bytes']  - prev_z['read_bytes'])  / 1024 / 1024 / z_interval
                    wMBps = max(0, curr_z['write_bytes'] - prev_z['write_bytes']) / 1024 / 1024 / z_interval
                    iops  = max(0, (curr_z['read_ops'] + curr_z['write_ops'])
                                  - (prev_z['read_ops'] + prev_z['write_ops'])) / z_interval

                    mounts.append({
                        'mount': mount_point,
                        'device': pool_name,
                        'rMBps': round(rMBps, 1),
                        'wMBps': round(wMBps, 1),
                        'iops': int(iops),
                        'await_ms': 0,
                        'util': 0,
                        'state': 'NORMAL'
                    })
                else:
                    # 첫 호출 또는 zpool 명령 실패
                    mounts.append({
                        'mount': mount_point,
                        'device': pool_name,
                        'rMBps': 0,
                        'wMBps': 0,
                        'iops': 0,
                        'await_ms': 0,
                        'util': 0,
                        'state': 'NORMAL' if curr_z else 'NO_DATA'
                    })
                continue

            # 해당 디바이스 통계 찾기
            prev = self._prev_stats.get(device, {})
            curr = current_stats.get(device, {})
            
            if not prev or not curr:
                # 통계를 찾을 수 없는 경우
                mounts.append({
                    'mount': mount_point,
                    'device': device,
                    'rMBps': 0,
                    'wMBps': 0,
                    'iops': 0,
                    'await_ms': 0,
                    'util': 0,
                    'state': 'NO_DATA'
                })
                continue
            
            # 델타 계산
            reads_delta = curr.get('reads', 0) - prev.get('reads', 0)
            writes_delta = curr.get('writes', 0) - prev.get('writes', 0)
            sectors_read_delta = curr.get('sectors_read', 0) - prev.get('sectors_read', 0)
            sectors_written_delta = curr.get('sectors_written', 0) - prev.get('sectors_written', 0)
            io_time_delta = curr.get('io_time_ms', 0) - prev.get('io_time_ms', 0)
            read_time_delta = curr.get('read_time_ms', 0) - prev.get('read_time_ms', 0)
            write_time_delta = curr.get('write_time_ms', 0) - prev.get('write_time_ms', 0)
            
            # 계산 (sector = 512 bytes)
            rMBps = (sectors_read_delta * 512) / (1024 * 1024) / interval
            wMBps = (sectors_written_delta * 512) / (1024 * 1024) / interval
            iops = (reads_delta + writes_delta) / interval
            
            # await (평균 I/O 대기 시간)
            total_ios = reads_delta + writes_delta
            if total_ios > 0:
                await_ms = (read_time_delta + write_time_delta) / total_ios
            else:
                await_ms = 0
            
            # util (I/O 사용률 %)
            # io_time_ms는 I/O에 사용된 시간 (ms)
            interval_ms = interval * 1000
            util = (io_time_delta / interval_ms) * 100 if interval_ms > 0 else 0
            util = min(100, max(0, util))  # 0-100 범위
            
            # 상태 판단
            if util >= self.THRESHOLD_SATURATED:
                state = 'SATURATED'
            elif util >= self.THRESHOLD_BUSY:
                state = 'BUSY'
            else:
                state = 'NORMAL'
            
            mounts.append({
                'mount': mount_point,
                'device': device,
                'rMBps': round(rMBps, 1),
                'wMBps': round(wMBps, 1),
                'iops': int(iops),
                'await_ms': round(await_ms, 1),
                'util': int(util),
                'state': state
            })
        
        # ZFS 이전 통계 업데이트
        for pool, stats in current_zfs_stats.items():
            self._zfs_prev_stats[pool] = {'stats': stats, 'time': current_time}

        # 이전 통계 업데이트
        self._prev_stats = current_stats
        self._prev_time = current_time
        
        return {
            'timestamp': datetime.now().isoformat(),
            'mounts': mounts
        }
    
    def get_disk_stats_formatted(self) -> str:
        """
        포맷된 디스크 통계 문자열 반환 (TUI 표시용).
        """
        stats = self.get_disk_io_stats()
        
        lines = []
        lines.append("[bold cyan]═══ Disk I/O Statistics ═══[/]\n")
        lines.append(f"[dim]Updated: {stats['timestamp']}[/]\n")
        lines.append("")
        
        # 헤더
        header = f"  {'Mount':<15} {'Device':<10} {'Read':>10} {'Write':>10} {'IOPS':>8} {'Await':>8} {'Util':>6}  {'State':<10}"
        lines.append(f"[yellow]{header}[/]")
        lines.append(f"  {'─' * 15} {'─' * 10} {'─' * 10} {'─' * 10} {'─' * 8} {'─' * 8} {'─' * 6}  {'─' * 10}")
        
        for m in stats['mounts']:
            mount = m['mount']
            device = m['device']
            rMBps = f"{m['rMBps']:.1f} MB/s"
            wMBps = f"{m['wMBps']:.1f} MB/s"
            iops = str(m['iops'])
            await_ms = f"{m['await_ms']:.1f} ms"
            util = f"{m['util']}%"
            state = m['state']
            
            # 상태에 따른 색상
            if state == 'SATURATED':
                state_display = f"[red]● {state}[/]"
                util_display = f"[red]{util}[/]"
            elif state == 'BUSY':
                state_display = f"[yellow]● {state}[/]"
                util_display = f"[yellow]{util}[/]"
            elif state == 'UNMOUNTED':
                state_display = f"[red]● {state}[/]"
                util_display = f"[dim]{util}[/]"
            elif state == 'NO_DATA':
                state_display = f"[dim]● {state}[/]"
                util_display = f"[dim]{util}[/]"
            else:
                state_display = f"[green]● {state}[/]"
                util_display = f"[green]{util}[/]"
            
            line = f"  {mount:<15} {device:<10} {rMBps:>10} {wMBps:>10} {iops:>8} {await_ms:>8} {util_display:>6}  {state_display}"
            lines.append(line)
        
        lines.append("")
        lines.append("[yellow]Status Legend:[/]")
        lines.append("  [green]● NORMAL[/]    : Utilization < 50%")
        lines.append("  [yellow]● BUSY[/]      : Utilization 50-80%")
        lines.append("  [red]● SATURATED[/] : Utilization > 80%")
        
        return "\n".join(lines)


# 테스트용
if __name__ == "__main__":
    monitor = DiskMonitor()
    print(monitor.get_disk_stats_formatted())
