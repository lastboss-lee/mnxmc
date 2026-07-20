#!/usr/bin/env python3
# modules/elasticsearch_monitor.py
import subprocess
import requests
import json
from datetime import datetime
from modules.base_module import BaseModule

class ElasticsearchMonitor(BaseModule):
    """
    Elasticsearch 모니터링 모듈
    
    주요 모니터링 대상:
    - Arkime Session Indices (arkime_sessions3-*): 네트워크 트래픽 캡처 세션
    - Network Statistics (net-stats-*): 네트워크 통계 데이터
    - Cluster Health: 클러스터 상태 및 샤드 정보
    """
    def __init__(self):
        super().__init__("Elasticsearch Monitor")
        self.es_url = "http://localhost:9200"
    
    def is_running(self):
        """Elasticsearch 서비스 실행 상태 확인"""
        try:
            response = requests.get(f"{self.es_url}/_cluster/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def get_cluster_health(self):
        """클러스터 헬스 정보"""
        try:
            response = requests.get(f"{self.es_url}/_cluster/health", timeout=5)
            if response.status_code == 200:
                health = response.json()
                health['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return health
            else:
                return None
        except Exception:
            return None
    
    def get_session_indices_realtime(self):
        """
        Arkime 세션 및 통계 인덱스 정보 - 실시간 조회
        Primary: arkime_sessions3-* (운영 환경 - Arkime 캡처 세션)
        Secondary: net-stats-* (개발/테스트 환경 - 네트워크 통계)
        """
        try:
            # Method 1: requests 라이브러리 사용 (더 안정적)
            try:
                response = requests.get(
                    f"{self.es_url}/_cat/indices?format=json", 
                    timeout=10
                )
                
                if response.status_code == 200:
                    all_indices = response.json()
                    # 모니터링 대상 인덱스 필터링
                    # 1) mnx_sessions3-*  : 일별 세션
                    # 2) net-stats-*      : 월별 네트워크 통계
                    # 3) payload_*        : 월별 DPI payload
                    # 4) ai_content-*     : AI 분석 결과
                    # 5) mail_content-*   : 메일 콘텐츠
                    # 6) playbook-*       : 플레이북
                    _PATTERNS = [
                        'session', 'net-stats', 'mnx_dstats', 'mnx_hunts',
                        'payload', 'ai_content', 'mail_content', 'playbook',
                    ]
                    session_indices = [
                        idx for idx in all_indices
                        if any(pattern in idx.get('index', '').lower()
                               for pattern in _PATTERNS)
                    ]

                    # 인덱스 이름 내림차순 정렬 (최신 인덱스 먼저)
                    session_indices.sort(key=lambda x: x.get('index', ''), reverse=True)

                    return {
                        'success': True,
                        'indices': session_indices,
                        'count': len(session_indices),
                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'method': 'requests'
                    }
            except Exception:
                pass

            # Method 2: curl 사용 (fallback)
            curl_result = subprocess.run([
                'curl', '-s', '-XGET',
                f'{self.es_url}/_cat/indices?format=json'
            ], capture_output=True, text=True, timeout=10)

            if curl_result.returncode == 0:
                try:
                    all_indices = json.loads(curl_result.stdout)
                    # 모니터링 대상 인덱스 필터링 (Method 1과 동일 패턴)
                    _PATTERNS = [
                        'session', 'net-stats', 'mnx_dstats', 'mnx_hunts',
                        'payload', 'ai_content', 'mail_content', 'playbook',
                    ]
                    session_indices = [
                        idx for idx in all_indices
                        if any(pattern in idx.get('index', '').lower()
                               for pattern in _PATTERNS)
                    ]

                    # 인덱스 이름 내림차순 정렬 (최신 인덱스 먼저)
                    session_indices.sort(key=lambda x: x.get('index', ''), reverse=True)
                    
                    return {
                        'success': True,
                        'indices': session_indices,
                        'count': len(session_indices),
                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'method': 'curl'
                    }
                except json.JSONDecodeError:
                    return {
                        'success': False,
                        'error': 'Failed to parse JSON response',
                        'indices': [],
                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
            
            return {
                'success': False,
                'error': 'Failed to execute curl command',
                'indices': [],
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
                
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Connection timeout',
                'indices': [],
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'indices': [],
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    
    def get_all_indices_realtime(self):
        """모든 인덱스 정보 - 실시간 조회 (디버깅용)"""
        try:
            response = requests.get(
                f"{self.es_url}/_cat/indices?format=json", 
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                return []
        except Exception:
            return []
    
    def get_unhealthy_indices(self):
        """yellow/red 상태인 인덱스 목록 반환 (최신 순)."""
        try:
            response = requests.get(
                f"{self.es_url}/_cat/indices?format=json", timeout=10
            )
            if response.status_code == 200:
                all_indices = response.json()
                unhealthy = [
                    idx for idx in all_indices
                    if idx.get('health', 'green').lower() in ('yellow', 'red')
                ]
                unhealthy.sort(key=lambda x: x.get('index', ''), reverse=True)
                return unhealthy
            return []
        except Exception:
            return []

    def get_all_indices_sorted(self):
        """모든 인덱스 정보 - 최신 순 정렬."""
        try:
            response = requests.get(
                f"{self.es_url}/_cat/indices?format=json", timeout=10
            )
            if response.status_code == 200:
                indices = response.json()
                indices.sort(key=lambda x: x.get('index', ''), reverse=True)
                return indices
            return []
        except Exception:
            return []

    def get_session_indices(self):
        """기존 메서드 - 호환성 유지"""
        result = self.get_session_indices_realtime()
        return result.get('indices', [])
    
    def get_all_indices_info(self):
        """모든 인덱스 기본 정보"""
        try:
            response = requests.get(f"{self.es_url}/_cat/indices?format=json", timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                return []
        except Exception:
            return []
    
    def get_elasticsearch_status(self):
        """Elasticsearch 전체 상태 정보 (UI에서 호출)"""
        is_running = self.is_running()
        
        if not is_running:
            return {
                'is_running': False,
                'success': False,
                'error': 'Elasticsearch service is not running',
                'cluster_health': None,
                'session_indices': [],
                'all_indices_count': 0
            }
        
        # 클러스터 헬스
        health = self.get_cluster_health()
        
        # 세션 인덱스 (실시간)
        session_result = self.get_session_indices_realtime()

        # 전체 인덱스 수
        all_indices = self.get_all_indices_realtime()

        # YELLOW/RED 문제 인덱스
        cluster_status = (health or {}).get('status', 'green').lower()
        unhealthy_indices = []
        if cluster_status in ('yellow', 'red'):
            unhealthy_indices = self.get_unhealthy_indices()

        return {
            'is_running': True,
            'success': session_result.get('success', False),
            'cluster_health': health,
            'session_indices': session_result.get('indices', []),
            'session_count': session_result.get('count', 0),
            'all_indices_count': len(all_indices),
            'unhealthy_indices': unhealthy_indices,
            'timestamp': session_result.get('timestamp', ''),
            'error': session_result.get('error', ''),
            'method': session_result.get('method', 'unknown')
        }
    
    def run(self):
        """터미널 모드 실행 (기존 호환성)"""
        print("=== Elasticsearch Monitor ===")
        
        if self.is_running():
            print("✓ Elasticsearch 서비스가 실행 중입니다.\n")
            
            # 클러스터 헬스 정보
            health = self.get_cluster_health()
            if health:
                print(f"[Cluster Health] - {health.get('timestamp', '')}")
                print(f"  Status: {health.get('status', 'unknown').upper()}")
                print(f"  Nodes: {health.get('number_of_nodes', 0)}")
                print(f"  Active Shards: {health.get('active_shards', 0)}")
                print(f"  Relocating: {health.get('relocating_shards', 0)}")
                print(f"  Initializing: {health.get('initializing_shards', 0)}")
                print(f"  Unassigned: {health.get('unassigned_shards', 0)}\n")
            
            # 전체 인덱스 수
            all_indices = self.get_all_indices_realtime()
            print(f"  Total Indices: {len(all_indices)}\n")
            
            # 세션 관련 인덱스 (실시간)
            session_result = self.get_session_indices_realtime()
            
            if session_result['success']:
                indices = session_result['indices']
                print(f"[Session Indices] ({len(indices)}개) - {session_result['timestamp']}")
                print(f"  Method: {session_result.get('method', 'unknown')}")
                
                if indices:
                    print(f"\n{'Health':<8} {'Status':<8} {'Index':<45} {'Docs':<12} {'Size':<10}")
                    print("-" * 90)
                    
                    for idx in indices[:20]:  # 최대 20개 표시
                        health_val = idx.get('health', 'unknown')
                        status_val = idx.get('status', 'unknown')
                        index_name = idx.get('index', 'unknown')
                        docs = idx.get('docs.count', '0')
                        size = idx.get('store.size', '0b')
                        
                        health_symbol = '●' if health_val == 'green' else ('◐' if health_val == 'yellow' else '○')
                        print(f"{health_symbol} {health_val:<6} {status_val:<8} "
                              f"{index_name:<45} {docs:>10}  {size:>8}")
                else:
                    print("  세션 인덱스가 없습니다.")
                    print(f"  (전체 인덱스: {len(all_indices)}개)")
            else:
                print(f"✗ 세션 인덱스 조회 실패: {session_result.get('error', 'Unknown error')}")
            
        else:
            print("✗ Elasticsearch 서비스에 연결할 수 없습니다.")
            print("  - localhost:9200 연결 확인 필요")
            print("  - Elasticsearch 서비스 상태 확인 필요")