# Phase 13 — 성능 분석 (Performance)

> 근거: `ps`(%CPU/%MEM/RSS), `free`, `nproc`, `uptime`, MariaDB `max_connections`, 설정값(worker/heap/Hikari), 디스크(Phase 1).
> 대상: CPU · Memory · Disk IO · Network IO · 병목 · Thread 경합 · Lock · Queue.

---

## 1. 호스트 리소스 기준선 (2026-07-10 11:21)

| 리소스 | 값 | 비고 |
|---|---|---|
| CPU | **12 vCPU** | 가상 어플라이언스 |
| RAM | **50 GB**, available 30 GB, **swap 0** | 스왑 없음 → OOM 시 즉시 kill |
| Load avg | 1.89 / 1.93 / 1.99 | 12코어 대비 여유(현재 stall 상태) |
| buff/cache | 23 GB | pcap/파일 IO 캐시 |

---

## 2. 프로세스별 자원 사용 (실측)

| 프로세스 | %CPU | RSS | 평가 |
|---|---|---|---|
| **elasticsearch** | **70.5%** | 5.0 GB | 최대 소비자. 색인/머지/GC. heap 4g |
| **capture** | **30.0%** | 1.1 GB | 🔴 **stall 상태인데 30% 스핀**(무한 재시도 = 순수 낭비) |
| **mnxdpi** | 12.0% | **8.7 GB** | 최대 메모리(PACE2 상태+mmap). 현재 idle인데도 높은 상주 |
| suricata | 6.0% | 372 MB | 라이브 스니핑 |
| Core API(java) | 1.7% | 1.37 GB | 현재 저부하(트래픽 없음) |
| kafka/zk(java) | ~0.7% | 400 MB | 저부하 |
| payload/ai/scan | ~0% | 소량 | 입력 아사로 idle |

> 정상 트래픽 시엔 capture/mnxdpi/ES가 CPU·IO를 지배할 것으로 예상(현재는 파이프라인 정지로 비대표적).

---

## 3. 🔴 즉시 시정 필요한 성능 결함 (실측 확정)

### 3.1 MariaDB 커넥션 고갈 (Critical)
- **MariaDB `max_connections = 151`**, 그러나 **Core API Hikari 풀 = 300**(application-1g/10g.yml).
- 부하 시 Hikari가 151을 초과 요청 → **`Too many connections` 오류**로 API 대량 실패 가능.
- **조치**: Hikari `maximum-pool-size`를 `max_connections`(-여유) 이하로 낮추거나 MariaDB `max_connections` 상향(메모리 고려).

### 3.2 JVM 힙 과할당 (Critical)
- Core API `-Xmx80g`, 그러나 **호스트 RAM 50GB + swap 0**.
- 80GB 힙은 물리적으로 도달 불가. 힙이 커지면 **OOM-killer가 컨테이너를 kill**(무한 재시작 루프 가능). heapdump 경로도 80GB를 `/application`(여유 1.8GB)에 쓰려다 실패.
- ES(4g) + mnxdpi(8.7g) + Kafka(1g) + ZK(0.5g) 합산만으로도 상당 → **메모리 예산 재설계 필요**.
- **조치**: 1g 프로파일에선 `-Xmx`를 호스트에 맞게(예: 8~16g) 축소.

### 3.3 capture stall 스핀 (High)
- 재시도 루프가 backoff 없이 30% CPU 소모 + `capture.log` **4.4GB↑** 지속 증가(디스크 추가 압박).
- **조치**: 제품측 재시도 backoff + 로그 억제. 운영측 워치독.

---

## 4. Disk IO 분석

| 경로 | 부하 | 이슈 |
|---|---|---|
| `/pipeline/raw`(sdc1) | capture pcap **쓰기** | 10Gbps 시 고대역 순차쓰기 |
| `/data/raw`(sdd2) | service_control **복사쓰기** + mnxdpi **읽기** | 🟠 **이중 쓰기**: capture가 `/pipeline`에 쓴 pcap을 service_control이 `/data/raw`로 재복사 → 동일 데이터 2배 IO |
| `/data/payload` | mnxdpi carving 쓰기 + payload 읽기 | 소파일 다수 |
| `/logs`(sdb4) | 전 로그 + logrotate `copytruncate` | copytruncate는 회전 시 대용량 재쓰기 유발 |
| ES `/application/es`(sdd1) | 색인/머지 | 🔴 **91% 포화** → 머지·색인 성능 저하 + flood-stage |

> **핵심 IO 병목**: (1) ES 디스크 포화, (2) pcap 이중 쓰기(`/pipeline`→`/data`). 10Gbps 캡처 시 pcap 쓰기가 디스크 대역을 지배 → mnxdpi 읽기와 경합 가능.

---

## 5. Network IO

- **캡처 대역**: ens192 미러 트래픽(1g/10g 프로파일). 10g 프로파일은 mnxdpi `worker_count=64`, ES consumer 16스레드로 고처리 설계.
- **내부 통신**: 대부분 loopback(ES/Kafka/DB/소켓) → 네트워크 스택 부하는 낮으나 **loopback 대량 bulk(ES)**가 CPU/메모리 카피 유발.
- **eng_monitor**가 ens192 Mbps/PPS를 1초 주기로 ES 색인 → 저부하.

---

## 6. Thread 경합 / Lock / Queue 병목

| 지점 | 유형 | 병목 가능성 |
|---|---|---|
| **Kafka 단일 파티션** | Queue 병렬성 | 🔴 consumer 병렬화 불가(파티션1) → 파일분석 처리량 상한. 고트래픽 시 백로그 |
| file_analysis_ai in_queue | multiprocessing.Queue | full 시 payload_analysis 블록(백프레셔) |
| **torch CPU 전용 추론** | CPU 경합 | 🟠 GPU 없이 16워커 CPU 추론 → 대량 파일 시 CPU 포화·지연 |
| ES bulk(capture+mnxdpi 16스레드) | ES write 경합 | 색인 큐·머지 스레드 경합, 디스크 포화 시 악화 |
| Hikari 300 vs DB 151 | 커넥션 락 | §3.1 고갈 |
| service_control pcap 이동(60s) | 파일 락/타이밍 | mnxdpi `exclusive_read`와 이동 타이밍 경합 가능(추정) |
| capture packetThreads=2 | 캡처 스레드 | 10Gbps엔 2스레드가 부족할 수 있음(추정, 튜닝 여지) |

---

## 7. 확장성(스케일) 관점

| 축 | 현재 | 한계 |
|---|---|---|
| 캡처 | capture 2 packet threads | 10Gbps 라인레이트 시 드롭 가능(ring 4096, 튜닝 필요) |
| DPI | mnxdpi 64 worker | CPU 12개 대비 과다 스레드 → 컨텍스트 스위치 오버헤드(추정) |
| 파일분석 | Kafka 파티션1 + payload 8 worker | 수평 확장 불가(단일 소비자) |
| 저장 | ES 단일노드 | 샤드/노드 확장 필요 |
| DB | 커넥션 151 | 동시 사용자/스케줄러 증가 시 부족 |

---

## 8. 성능 튜닝 우선순위 (인수 후)

1. 🔴 **Hikari 풀 ↔ MariaDB max_connections 정합** (즉시).
2. 🔴 **API `-Xmx` 호스트 메모리에 맞게 축소** (즉시).
3. 🔴 **ES 디스크 확보 + 보존정책(ILM)** — 색인 성능·안정성 직결.
4. 🟠 **pcap 이중 쓰기 제거/최적화** — `/pipeline`→`/data` 이동을 하드링크/이동(rename)으로(동일 FS면), 또는 캡처 직접 `/data` 쓰기 검토.
5. 🟠 **Kafka 파티션 증설** — 파일분석 수평확장.
6. 🟠 **mnxdpi worker_count를 vCPU에 맞게 재조정**.
7. 🟡 GPU 도입 검토(AI 추론) 또는 배치 크기 튜닝.

---

## 9. 인수인계 핵심 포인트

1. **현재 수치는 비대표적**(파이프라인 정지 상태) — 정상 트래픽 복구 후 재측정 필요.
2. **메모리 예산이 위태**: 80g 힙 설정 + swap 0 + 50GB RAM은 언젠가 OOM. 최우선 점검.
3. **DB 커넥션 정합 오류는 부하 테스트 없이도 확정적 장애 요인**.
4. 디스크가 CPU만큼 중요한 자원 — pcap 이중쓰기·ES 포화가 실질 병목.
