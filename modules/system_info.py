#!/usr/bin/env python3
import os
import subprocess
import time
import re
import json
from modules.base_module import BaseModule

class SystemInfo(BaseModule):
    def __init__(self):
        super().__init__("System Information")
        self.cache_file = "/tmp/mnx_system_info.json"
        self.cache_timeout = 3600  # 1ì‹œê°„ (í•˜ë“œì›¨ì–´ ì •ë³´ëŠ” ìžì£¼ ë°”ë€Œì§€ ì•ŠìŒ)
    
    def _run_command(self, command, timeout=10):
        """ì•ˆì „í•œ ëª…ë ¹ì–´ ì‹¤í–‰"""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, 
                text=True, timeout=timeout
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return None
        except (subprocess.TimeoutExpired, Exception):
            return None

    def _collect_system_info(self):
        """ì‹œìŠ¤í…œ ì •ë³´ ì „ì²´ ìˆ˜ì§‘ - í•œ ë²ˆë§Œ ì‹¤í–‰"""
        print("Scanning system information...")
        
        info = {
            'scan_time': time.time(),
            'hostname': self._get_hostname(),
            'uptime': self._get_uptime(),
            'system': self._get_system_info(),
            'cpu': self._get_cpu_info(),
            'memory': self._get_memory_info(),
            'disk': self._get_disk_usage(),
            'network': self._get_network_interfaces(),
            'load': self._get_load_average()
        }
        
        return info

    def _get_hostname(self):
        """í˜¸ìŠ¤íŠ¸ëª…"""
        return self._run_command('hostname') or 'Unknown'

    def _get_uptime(self):
        """ì—…íƒ€ìž„"""
        uptime_str = self._run_command('uptime -p')
        if uptime_str:
            return uptime_str.replace('up ', '')
        return 'Unknown'

    def _get_system_info(self):
        """ì‹œìŠ¤í…œ ê¸°ë³¸ ì •ë³´"""
        info = {
            'kernel': 'Unknown',
            'os_version': 'Unknown',
            'product_name': 'Unknown',
            'current_user': 'Unknown',
            'main_ip': 'Unknown'
        }
        
        # ì»¤ë„ ë²„ì „
        kernel = self._run_command('uname -r')
        if kernel:
            info['kernel'] = kernel
        
        # OS ë²„ì „
        os_ver = self._run_command('cat /etc/os-release | grep PRETTY_NAME | cut -d"=" -f2')
        if os_ver:
            info['os_version'] = os_ver.strip('"')
        elif os.path.exists('/etc/redhat-release'):
            os_ver = self._run_command('cat /etc/redhat-release')
            if os_ver:
                info['os_version'] = os_ver
        
        # ì‹œìŠ¤í…œ ì œí’ˆëª… (Dell PowerEdge ë“±)
        product = self._run_command('sudo dmidecode -s system-product-name 2>/dev/null')
        if product and product != 'System Product Name':
            info['product_name'] = product
        
        # í˜„ìž¬ ì‚¬ìš©ìž
        user = self._run_command('whoami')
        if user:
            info['current_user'] = user
        
        # ë©”ì¸ IP
        main_ip = self._run_command("hostname -I | awk '{print $1}'")
        if main_ip:
            info['main_ip'] = main_ip
        
        return info

    def _get_cpu_info(self):
        """CPU ì •ë³´ ìˆ˜ì§‘"""
        cpu_info = {
            'model': 'Unknown',
            'cores': 0,
            'threads': 0,
            'architecture': 'Unknown',
            'frequency': 'Unknown'
        }
        
        # CPU ëª¨ë¸ëª…
        model = self._run_command("grep 'model name' /proc/cpuinfo | head -1 | cut -d':' -f2")
        if model:
            cpu_info['model'] = model.strip()
        
        # ë¬¼ë¦¬ ì½”ì–´ ìˆ˜
        physical_cores = self._run_command("grep 'cpu cores' /proc/cpuinfo | head -1 | cut -d':' -f2")
        if physical_cores:
            cpu_info['cores'] = int(physical_cores.strip())
        
        # ë…¼ë¦¬ í”„ë¡œì„¸ì„œ ìˆ˜
        logical_cores = self._run_command("nproc")
        if logical_cores:
            cpu_info['threads'] = int(logical_cores)
        
        # ì•„í‚¤í…ì²˜
        arch = self._run_command("uname -m")
        if arch:
            cpu_info['architecture'] = arch
            
        # CPU ì£¼íŒŒìˆ˜
        freq = self._run_command("grep 'cpu MHz' /proc/cpuinfo | head -1 | cut -d':' -f2")
        if freq:
            try:
                freq_ghz = float(freq.strip()) / 1000
                cpu_info['frequency'] = f"{freq_ghz:.2f} GHz"
            except Exception:
                cpu_info['frequency'] = freq.strip() + " MHz"
        
        return cpu_info

    def _get_memory_info(self):
        """ë©”ëª¨ë¦¬ ì •ë³´ ìˆ˜ì§‘"""
        mem_info = {
            'total_gb': 0,
            'total_slots': 'Unknown',
            'installed_modules': 'Unknown'
        }
        
        try:
            # ì´ ë©”ëª¨ë¦¬ ìš©ëŸ‰
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            
            total_kb = int(re.search(r'MemTotal:\s+(\d+)', meminfo).group(1))
            mem_info['total_gb'] = round(total_kb / 1024 / 1024, 1)
            
            # dmidecodeë¡œ ë©”ëª¨ë¦¬ ìŠ¬ë¡¯ ì •ë³´
            result = subprocess.run(['sudo', 'dmidecode', '-t', '17'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                dmidecode_out = result.stdout
                
                # ì„¤ì¹˜ëœ ë©”ëª¨ë¦¬ ëª¨ë“ˆ ìˆ˜
                size_pattern = r'Size:\s+(\d+)\s*GB'
                sizes = re.findall(size_pattern, dmidecode_out)
                installed_modules = len([s for s in sizes if int(s) > 0])
                
                # ì´ ë©”ëª¨ë¦¬ ìŠ¬ë¡¯ ìˆ˜
                total_slots = dmidecode_out.count('Memory Device')
                
                mem_info['installed_modules'] = installed_modules
                mem_info['total_slots'] = total_slots
                
        except Exception:
            pass
        
        return mem_info

    def _get_network_interfaces(self):
        """ë„¤íŠ¸ì›Œí¬ ì¸í„°íŽ˜ì´ìŠ¤ ì •ë³´"""
        interfaces = []
        
        # PCI ë„¤íŠ¸ì›Œí¬ ì»¨íŠ¸ë¡¤ëŸ¬ ì •ë³´
        pci_output = self._run_command("lspci | grep -i 'ethernet\\|network'")
        if pci_output:
            for line in pci_output.split('\n'):
                if line.strip():
                    parts = line.split(': ', 1)
                    if len(parts) == 2:
                        pci_addr = parts[0].strip()
                        controller = parts[1].strip()
                        
                        # ì œì¡°ì‚¬ ë° ì†ë„ ë¶„ë¥˜
                        if 'Intel' in controller:
                            vendor = 'Intel'
                            if 'I350' in controller:
                                speed = '1GbE'
                            elif 'X710' in controller:
                                speed = '10GbE'
                            else:
                                speed = 'Unknown'
                        elif 'Broadcom' in controller:
                            vendor = 'Broadcom'
                            speed = '1GbE' if 'Gigabit' in controller else 'Unknown'
                        else:
                            vendor = 'Unknown'
                            speed = 'Unknown'
                        
                        interfaces.append({
                            'pci_addr': pci_addr,
                            'vendor': vendor,
                            'controller': controller,
                            'speed': speed
                        })
        
        return interfaces

    def _get_disk_usage(self):
        """ë””ìŠ¤í¬ ì‚¬ìš©ëŸ‰ (ì •ì  ì •ë³´ëŠ” ì €ìž¥, ë™ì  ì •ë³´ëŠ” ì‹¤ì‹œê°„)"""
        disk_info = {
            'total_gb': 0,
            'filesystem': 'Unknown'
        }
        
        df_output = self._run_command("df -hT / | tail -1")
        if df_output:
            fields = df_output.split()
            if len(fields) >= 2:
                disk_info['filesystem'] = fields[1]  # íŒŒì¼ì‹œìŠ¤í…œ íƒ€ìž…
                
                # ì´ ìš©ëŸ‰ (ì •ì  ì •ë³´)
                if len(fields) >= 3:
                    total_str = fields[2].replace('G', '').replace('M', '').replace('K', '')
                    try:
                        if 'G' in fields[2]:
                            disk_info['total_gb'] = float(total_str)
                        elif 'M' in fields[2]:
                            disk_info['total_gb'] = round(float(total_str) / 1024, 1)
                    except Exception:
                        pass
        
        return disk_info

    def _get_load_average(self):
        """ë¡œë“œ í‰ê·  (ì‹¤ì‹œê°„ ì •ë³´)"""
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

    def _save_cache(self, data):
        """ìºì‹œ íŒŒì¼ì— ì €ìž¥"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Cache save error: {e}")

    def _load_cache(self):
        """ìºì‹œ íŒŒì¼ì—ì„œ ë¡œë“œ"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Cache load error: {e}")
        return None

    def _is_cache_valid(self, cached_data):
        """ìºì‹œ ìœ íš¨ì„± ê²€ì‚¬"""
        if not cached_data or 'scan_time' not in cached_data:
            return False
        
        age = time.time() - cached_data['scan_time']
        return age < self.cache_timeout

    def rescan_system(self):
        """ì‹œìŠ¤í…œ ìž¬ìŠ¤ìº” (F7 í‚¤ í˜¸ì¶œ)"""
        info = self._collect_system_info()
        self._save_cache(info)
        return info

    def get_system_overview(self):
        """ì‹œìŠ¤í…œ ê°œìš” ì •ë³´ (ìºì‹œ ìš°ì„ )"""
        # ìºì‹œëœ ì •ë³´ í™•ì¸
        cached_data = self._load_cache()
        
        if self._is_cache_valid(cached_data):
            # ì‹¤ì‹œê°„ ì •ë³´ë§Œ ì—…ë°ì´íŠ¸
            cached_data['uptime'] = self._get_uptime()
            cached_data['load'] = self._get_load_average()
            cached_data['system']['current_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
            return cached_data
        else:
            # ì „ì²´ ìž¬ìŠ¤ìº”
            info = self.rescan_system()
            return info

    def get_memory_usage(self):
        """ì‹¤ì‹œê°„ ë©”ëª¨ë¦¬ ì‚¬ìš©ëŸ‰"""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            
            total_kb = int(re.search(r'MemTotal:\s+(\d+)', meminfo).group(1))
            available_kb = int(re.search(r'MemAvailable:\s+(\d+)', meminfo).group(1))
            
            usage_percent = round((total_kb - available_kb) / total_kb * 100, 1)
            used_gb = round((total_kb - available_kb) / 1024 / 1024, 1)
            available_gb = round(available_kb / 1024 / 1024, 1)
            
            return {
                'usage_percent': usage_percent,
                'used_gb': used_gb,
                'available_gb': available_gb
            }
        except Exception:
            return {'usage_percent': 0, 'used_gb': 0, 'available_gb': 0}

    def get_disk_usage(self):
        """ì‹¤ì‹œê°„ ë””ìŠ¤í¬ ì‚¬ìš©ëŸ‰"""
        df_output = self._run_command("df -h / | tail -1")
        if df_output:
            fields = df_output.split()
            if len(fields) >= 5:
                try:
                    usage_str = fields[4].replace('%', '')
                    return f"{usage_str}%"
                except Exception:
                    pass
        return "Unknown"

    def get_basic_info(self):
        """ê¸°ì¡´ í˜¸í™˜ì„±ì„ ìœ„í•œ ê¸°ë³¸ ì •ë³´"""
        overview = self.get_system_overview()
        memory_usage = self.get_memory_usage()
        
        return {
            'hostname': overview.get('hostname', 'Unknown'),
            'uptime': overview.get('uptime', 'Unknown'),
            'memory_usage': memory_usage['usage_percent'],
            'disk_usage': self.get_disk_usage(),
            'load_avg': f"{overview['load']['1min']:.2f}, {overview['load']['5min']:.2f}, {overview['load']['15min']:.2f}"
        }

    def get_comprehensive_info(self):
        """ìƒì„¸ ì •ë³´ (dashboard í˜¸í™˜)"""
        overview = self.get_system_overview()
        memory_usage = self.get_memory_usage()
        
        # ë©”ëª¨ë¦¬ ì •ë³´ì— ì‹¤ì‹œê°„ ì‚¬ìš©ëŸ‰ ì¶”ê°€
        overview['memory'].update(memory_usage)
        
        return overview

    def run(self):
        """í…ŒìŠ¤íŠ¸ ì‹¤í–‰"""
        self.clear_screen()
        print("=== System Information Manager ===\n")
        
        info = self.get_system_overview()
        
        print(f"System: {info['system']['product_name']}")
        print(f"Hostname: {info['hostname']}")
        print(f"Uptime: {info['uptime']}")
        print(f"CPU: {info['cpu']['model'][:50]}")
        print(f"Memory: {info['memory']['total_gb']:.1f} GB")
        print(f"Network Interfaces: {len(info['network'])}")
        print(f"Last scan: {time.ctime(info['scan_time'])}")
        
        print("\nPress F7 to rescan system information...")
        self.wait_for_key()