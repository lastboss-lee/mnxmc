#!/usr/bin/env python3
# modules/kafka_monitor.py
import subprocess
import os
import time
from datetime import datetime
from modules.base_module import BaseModule

class KafkaMonitor(BaseModule):
    def __init__(self):
        super().__init__("Kafka Monitor")
        self.java_home = "/usr/share/elasticsearch/jdk/"
        self.kafka_bin = "/usr/local/kafka/bin/kafka-consumer-groups.sh"
    
    def is_running(self):
        """Kafka 서비스 실행 상태 확인"""
        try:
            env = os.environ.copy()
            env['JAVA_HOME'] = self.java_home
            
            result = subprocess.run([
                self.kafka_bin,
                '--bootstrap-server', 'localhost:9092',
                '--list'
            ], env=env, capture_output=True, text=True, timeout=5)
            
            return result.returncode == 0
        except Exception:
            return False
    
    def get_mnx_group_realtime(self):
        """실시간 MNX consumer group 정보 - 요청 시마다 새로 조회"""
        try:
            env = os.environ.copy()
            env['JAVA_HOME'] = self.java_home
            
            # 실제 명령어 실행 (캐싱 없이 매번 fresh 데이터)
            result = subprocess.run([
                self.kafka_bin,
                '--bootstrap-server', 'localhost:9092',
                '--describe', '--group', 'mnx'
            ], env=env, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                output = result.stdout.strip()
                return {
                    'success': True,
                    'output': output,
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'raw_data': self._parse_kafka_output(output)
                }
            else:
                return {
                    'success': False,
                    'error': result.stderr.strip() or "Unable to connect to Kafka",
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'raw_data': []
                }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Connection timeout',
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'raw_data': []
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'raw_data': []
            }
    
    def _parse_kafka_output(self, output):
        """Kafka 출력 파싱"""
        parsed = []
        lines = output.split('\n')
        
        for line in lines:
            # 데이터 라인만 처리 (헤더 및 빈 줄 제외)
            if line and not line.startswith('GROUP') and not line.startswith('Consumer') and 'PARTITION' not in line:
                parts = line.split()
                if len(parts) >= 7:
                    try:
                        parsed.append({
                            'group': parts[0],
                            'topic': parts[1],
                            'partition': parts[2],
                            'current_offset': parts[3],
                            'log_end_offset': parts[4],
                            'lag': parts[5],
                            'consumer_id': parts[6] if len(parts) > 6 else '-',
                            'host': parts[7] if len(parts) > 7 else '-',
                            'client_id': parts[8] if len(parts) > 8 else '-'
                        })
                    except (ValueError, IndexError):
                        continue
        
        return parsed
    
    def get_kafka_status(self):
        """Kafka 전체 상태 정보 (UI에서 호출) — is_running() 중복 호출 없이 단일 요청"""
        realtime_data = self.get_mnx_group_realtime()
        is_running = realtime_data.get('success', False)

        return {
            'is_running': is_running,
            'success': is_running,
            'timestamp': realtime_data.get('timestamp', ''),
            'raw_data': realtime_data.get('raw_data', []),
            'error': realtime_data.get('error', '')
        }
    
    def run(self):
        """터미널 모드 실행 (기존 호환성)"""
        self.clear_screen()
        print("=== Kafka Monitor ===")
        
        if self.is_running():
            print("✓ Kafka 서비스가 실행 중입니다.\n")
            
            data = self.get_mnx_group_realtime()
            if data['success']:
                print(f"[MNX Consumer Group Status] - {data['timestamp']}\n")
                print(f"{'Partition':<12} {'Current':<15} {'End':<15} {'Lag':<10} {'Consumer ID':<20}")
                print("-" * 80)
                
                for item in data['raw_data']:
                    print(f"{item['partition']:<12} {item['current_offset']:<15} "
                          f"{item['log_end_offset']:<15} {item['lag']:<10} "
                          f"{item['consumer_id']:<20}")
            else:
                print(f"✗ 오류: {data.get('error', 'Unknown error')}")
        else:
            print("✗ Kafka 서비스에 연결할 수 없습니다.")
            print("  - localhost:9092 연결 확인 필요")
            print("  - Kafka 서비스 상태 확인 필요")
        
        self.wait_for_key()