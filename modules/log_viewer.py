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
