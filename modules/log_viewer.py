#!/usr/bin/env python3
"""
Log Viewer Module

로그 파일을 탐색하고 내용을 표시하는 모듈입니다.
"""

import os
import subprocess
import time
from modules.base_module import BaseModule


class LogViewer(BaseModule):
    """로그 뷰어 클래스."""
    
    # 로그 소스별 경로 매핑
    # 디렉토리인 경우: 해당 디렉토리 내 최신 로그 파일 검색
    # 파일인 경우: 해당 파일 직접 사용
    LOG_PATHS = {
        "dga_analysis_ai": "/logs/dga_analysis_ai",
        "file_analysis_ai": "/logs/file_analysis_ai",
        "mnxcapture": "/logs/mnxcapture",
        "mnxdpi": "/logs/mnxdpi",
        "mnx_service_control": "/logs/service_control",
        "payload_analysis": "/logs/payload_analysis",
        "suricata": "/logs/suricata",
        "syslog": "/var/log/syslog",  # 시스템 로그는 /var/log에 위치
    }
    
    def __init__(self):
        super().__init__("Enhanced Log Viewer")
        self.log_base_dir = "/logs"
        self.expanded_dirs = set()
        self.menu_items = []
        self.selected_log_file = None
        
    def scan_log_structure(self):
        """로그 디렉토리 구조 스캔."""
        structure = {}
        
        for log_id, log_path in self.LOG_PATHS.items():
            if os.path.isfile(log_path):
                # 단일 파일인 경우 (예: syslog)
                try:
                    stat_info = os.stat(log_path)
                    structure[log_id] = [{
                        'name': os.path.basename(log_path),
                        'type': 'file',
                        'path': log_path,
                        'size': stat_info.st_size,
                        'mtime': stat_info.st_mtime
                    }]
                except:
                    structure[log_id] = []
            elif os.path.isdir(log_path):
                # 디렉토리인 경우
                structure[log_id] = self._scan_directory(log_path)
            else:
                structure[log_id] = []
        
        return structure
    
    def _scan_directory(self, dir_path):
        """단일 디렉토리 스캔."""
        items = []
        
        try:
            for item in os.listdir(dir_path):
                item_path = os.path.join(dir_path, item)
                
                if os.path.isfile(item_path):
                    if self._is_log_file(item):
                        try:
                            stat_info = os.stat(item_path)
                            items.append({
                                'name': item,
                                'type': 'file',
                                'path': item_path,
                                'size': stat_info.st_size,
                                'mtime': stat_info.st_mtime
                            })
                        except:
                            items.append({
                                'name': item,
                                'type': 'file',
                                'path': item_path,
                                'size': 0,
                                'mtime': 0
                            })
                
                elif os.path.isdir(item_path):
                    subitems = self._scan_directory(item_path)
                    items.append({
                        'name': item,
                        'type': 'dir',
                        'path': item_path,
                        'items': subitems
                    })
        
        except (PermissionError, FileNotFoundError):
            pass
        
        # 파일들을 수정시간 순으로 정렬
        files = [item for item in items if item['type'] == 'file']
        dirs = [item for item in items if item['type'] == 'dir']
        
        files.sort(key=lambda x: x['mtime'], reverse=True)
        
        return dirs + files
    
    def _is_log_file(self, filename):
        """로그 파일 여부 확인."""
        log_extensions = ['.log', '.json', '.txt']
        log_keywords = ['log', 'eve', 'fast', 'stats', 'syslog', 'capture']
        
        for ext in log_extensions:
            if filename.endswith(ext):
                return True
        
        filename_lower = filename.lower()
        for keyword in log_keywords:
            if keyword in filename_lower:
                return True
        
        return False
    
    def get_latest_log_file(self, directory):
        """특정 로그 소스의 최신 로그 파일 가져오기."""
        # 먼저 LOG_PATHS에서 직접 경로 확인
        log_path = self.LOG_PATHS.get(directory)
        
        if log_path and os.path.isfile(log_path):
            # 단일 파일인 경우 직접 반환
            return log_path
        
        # 디렉토리인 경우 스캔
        structure = self.scan_log_structure()
        dir_items = structure.get(directory, [])
        
        log_files = [item for item in dir_items if item['type'] == 'file']
        if log_files:
            latest = max(log_files, key=lambda x: x['mtime'])
            return latest['path']
        
        return None
    
    def toggle_directory(self, directory_name):
        """디렉토리 확장/축소 토글."""
        if directory_name in self.expanded_dirs:
            self.expanded_dirs.remove(directory_name)
        else:
            self.expanded_dirs.add(directory_name)
    
    def get_log_content(self, log_path, lines=20):
        """로그 파일 내용 가져오기."""
        if not log_path or not os.path.exists(log_path):
            return ["Log file not found"]
        
        try:
            result = subprocess.run(
                ['tail', '-n', str(lines), log_path],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip().split('\n')
            else:
                return ["Unable to read log file"]
                
        except subprocess.TimeoutExpired:
            return ["Log read timeout"]
        except Exception as e:
            return [f"Error reading log: {str(e)}"]
    
    def format_file_size(self, size_bytes):
        """파일 크기 포맷."""
        if size_bytes == 0:
            return "0 B"
        
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        
        return f"{size_bytes:.1f} TB"
    
    def build_menu_items(self, structure):
        """계층적 메뉴 아이템 생성."""
        items = []
        
        for dir_name in sorted(structure.keys()):
            dir_items = structure[dir_name]
            
            is_expanded = dir_name in self.expanded_dirs
            items.append({
                'type': 'directory',
                'name': dir_name,
                'path': self.LOG_PATHS.get(dir_name, os.path.join(self.log_base_dir, dir_name)),
                'level': 0,
                'expanded': is_expanded,
                'has_files': len(dir_items) > 0
            })
            
            if is_expanded:
                self._add_directory_items(items, dir_items, dir_name, 1)
        
        # 특별 모니터 항목들 추가
        items.extend([
            {
                'type': 'special',
                'name': 'Kafka Monitor',
                'path': 'kafka_monitor',
                'level': 0,
                'expanded': False
            },
            {
                'type': 'special', 
                'name': 'Elasticsearch Monitor',
                'path': 'elasticsearch_monitor',
                'level': 0,
                'expanded': False
            }
        ])
        
        return items
    
    def _add_directory_items(self, items, dir_items, parent_name, level):
        """디렉토리 하위 항목들 추가."""
        for item in dir_items:
            if item['type'] == 'file':
                items.append({
                    'type': 'file',
                    'name': item['name'],
                    'path': item['path'],
                    'parent': parent_name,
                    'level': level,
                    'size': item['size'],
                    'mtime': item['mtime'],
                    'is_latest': False
                })
            
            elif item['type'] == 'dir':
                subdir_path = f"{parent_name}/{item['name']}"
                is_expanded = subdir_path in self.expanded_dirs
                
                items.append({
                    'type': 'subdirectory',
                    'name': item['name'], 
                    'path': item['path'],
                    'parent': parent_name,
                    'level': level,
                    'expanded': is_expanded,
                    'has_files': len(item['items']) > 0
                })
                
                if is_expanded:
                    self._add_directory_items(items, item['items'], subdir_path, level + 1)
    
    def mark_latest_files(self, items):
        """각 디렉토리에서 최신 파일 표시."""
        dir_files = {}
        
        for item in items:
            if item['type'] == 'file':
                parent = item.get('parent', 'root')
                if parent not in dir_files:
                    dir_files[parent] = []
                dir_files[parent].append(item)
        
        for parent, files in dir_files.items():
            if files:
                latest_file = max(files, key=lambda x: x['mtime'])
                latest_file['is_latest'] = True
    
    def format_menu_item(self, item, is_selected=False):
        """메뉴 아이템 포맷팅."""
        indent = "  " * item['level']
        
        if item['type'] == 'directory':
            expand_char = "▸" if item['expanded'] else "▶" if item['has_files'] else " "
            return f"{indent}{expand_char}{item['name']}"
            
        elif item['type'] == 'subdirectory':
            expand_char = "▸" if item['expanded'] else "▶" if item['has_files'] else " "
            return f"{indent}├─{expand_char}{item['name']}/"
            
        elif item['type'] == 'file':
            latest_marker = "●" if item.get('is_latest', False) else " "
            if item['level'] > 0:
                return f"{indent}├─{latest_marker}{item['name']}"
            else:
                return f"{indent}{latest_marker}{item['name']}"
                
        elif item['type'] == 'special':
            return f"{indent}{item['name']}"
        
        return f"{indent}{item['name']}"
    
    def get_log_info(self, item):
        """선택된 아이템의 로그 정보."""
        if item['type'] == 'file':
            return {
                'type': 'file',
                'name': os.path.basename(item['path']),
                'path': item['path'],
                'size': self.format_file_size(item['size']),
                'mtime': time.ctime(item['mtime']),
                'content': self.get_log_content(item['path'])
            }
        
        elif item['type'] in ['directory', 'subdirectory']:
            latest_file = self.get_latest_log_file(item['name'])
            if latest_file:
                return {
                    'type': 'directory',
                    'name': item['name'],
                    'path': latest_file,
                    'content': self.get_log_content(latest_file)
                }
            else:
                return {
                    'type': 'directory',
                    'name': item['name'],
                    'path': 'No log files',
                    'content': ['No log files found in directory']
                }
        
        elif item['type'] == 'special':
            return {
                'type': 'special',
                'name': item['name'],
                'path': 'Special monitor',
                'content': [f"{item['name']} - Select to view detailed information"]
            }
        
        return {'type': 'unknown', 'content': ['Unknown item type']}
    
    def run(self):
        """TUI에서 실행."""
        self.clear_screen()
        print("=== Enhanced Log Viewer ===")
        print("Scanning log structure...")
        
        structure = self.scan_log_structure()
        menu_items = self.build_menu_items(structure)
        self.mark_latest_files(menu_items)
        
        print(f"\nFound {len(menu_items)} log items")
        print("\nLog Directory Structure:")
        
        for item in menu_items[:20]:
            formatted = self.format_menu_item(item)
            print(formatted)
        
        self.wait_for_key()
