# Phase 8 — 설정(Configuration) 분석

> 근거: 실제 파일 직접 판독(`config.ini`, `mnx_config.json`, systemd, nginx, compose 등).
> 각 항목: **실제 사용 여부 / 기본값 / 변경 가능 여부 / 영향 범위**.

---

## 1. 설정 파일 인벤토리 (마스터 표)

| 설정파일 | 형식 | 사용 주체 | 실사용 | 변경 시 적용 | 영향 범위 |
|---|---|---|---|---|---|
| `/opt/mnx/etc/config.ini` | INI | capture | ✅ | capture 재시작 | 캡처 전반(NIC/ES/BPF/플러그인) |
| `/opt/mnx/etc/mnx_config.json` | JSON | mnxdpi/payload/ai/scan/service_control/regression/syslog | ✅ | 각 서비스 재시작 | **엔진 공통 — 가장 광범위** |
| `/opt/mnx/etc/capture.env` | env | mnxcapture 유닛 | ❌ **부재** | (있으면 OPTIONS 주입) | capture CLI 옵션 오버라이드 |
| `/opt/mnx/etc/mnx.rules` | capture rules | capture | ✅ | capture 재시작 | 캡처측 룰 |
| `/etc/suricata/suricata.yaml` | YAML | suricata | ✅ | suricata 재시작 | IDS 스니핑/출력 |
| `/application/custom-rule/suricata/*.rules` (SANDS_*) | Suricata rules | suricata | ✅ | 룰 리로드 | 탐지 시그니처 |
| `application.yml` + `application-{1g,10g}.yml` (jar 내부) | YAML | Core API(Spring) | ✅(프로파일 택1) | 컨테이너 재시작 | API 전반(DB/ES/JWT/스케줄) |
| `/opt/mnx_web/docker-compose-{api,web}-{1g,10g}.yml` | YAML | dockerd | ✅(택1) | 컨테이너 재생성 | 컨테이너 기동/시크릿/볼륨 |
| `/etc/nginx/conf.d/default.conf` (컨테이너 내) | nginx | nginx | ✅ | nginx reload | 프록시/TLS/라우팅 |
| `env.js` (웹 컨테이너) | JS | Vue SPA | ✅ | 컨테이너 재시작 | UI 트래픽 티어 |
| `web_config.ini` (웹) | INI | (표시) | ⚠ stale | — | `max-traffic=10G`(실행값 1g와 불일치) |
| `/usr/local/kafka/config/server.properties` | properties | kafka | ✅ | kafka 재시작 | 브로커(파티션/보존/RF) |
| `/usr/local/kafka/config/zookeeper.properties` | properties | zookeeper | ✅ | zk 재시작 | ZK |
| `/etc/elasticsearch/elasticsearch.yml`,`jvm.options` | YAML | ES | ✅ | ES 재시작 | 힙/네트워크/워터마크 |
| `/opt/file_analysis_ai/settings.py` | Python | file_analysis_ai | ✅ | 서비스 재시작 | AI 워커/모델 경로 |
| `/opt/scanengine/pattern_path.conf` | conf | scanengine | ✅ | 재시작 | AV 시그니처 경로 |
| `/etc/logrotate.d/mnx` | logrotate | logrotate(cron 30m) | ✅ | 즉시 | 로그 회전 |
| root crontab | cron | cron | ✅ | 즉시 | 스케줄 전반 |
| `/opt/service_control/settings.json` | JSON | — | ⚠ 미참조(추정) | — | 없음(dead 추정) |
| `/opt/syslog/settings.py` | Python | syslog.py | 부분 | 재시작 | syslog(현재 inert) |

---

## 2. `/opt/mnx/etc/config.ini` (캡처) — 핵심 키

| 키 | 실제값 | 기본/권장 | 영향 |
|---|---|---|---|
| `elasticsearch` | `http://localhost:9200` | — | 세션 색인 대상 |
| `rotateIndex` | `daily` | daily | `mnx_sessions3-YYMMDD` 회전 주기 |
| `authMode` | `anonymous` | 🔴 인증 없음 | ES 접근제어 공백 |
| `passwordSecret` | `toswm#0501` | 🔴 하드코딩 | 뷰어 인증 시크릿 |
| `interface` | `ens192` | — | **캡처 NIC(하드코딩)** |
| `interfaceOps` | `tags=Net-1` | — | 센서 태그(망 이름) |
| `bpf` | `not broadcast and not multicast` | — | 캡처 필터 |
| `pcapDir` | `/pipeline/raw` | — | pcap 1차 저장 |
| `maxPackets` | `30000` | — | 세션당 최대 패킷 |
| `freeSpaceG` | `5%` | — | 캡처 자체 여유공간 임계 |
| `dropUser`/`dropGroup` | `nobody`/`daemon` | — | 캡처 권한 강등 |
| `parsersDir`/`pluginsDir` | `/opt/mnx/parsers`,`/opt/mnx/plugins` | — | 파서/플러그인 로드 경로 |
| `plugins` | `suricata.so;libmnxdpi.so` | — | 로드 플러그인(2개) |
| `suricataAlertFile` | `/logs/suricata/eve.json` | — | **eve.json→세션 결합 소스(확정)** |
| `libmnxdpi_sock`/`_port` | `/var/run/`,`9500` | — | mnxdpi 연동 소켓/포트 |
| `spiDataMaxIndices` | `4` | — | SPI 인덱스 |
| `maxESConns`/`maxESRequests` | `30`/`500` | — | ES 동시성 |
| `tcpTimeout`/`udpTimeout` | `600`/`30` | — | 세션 타임아웃 |
| `parseSMTP`/`parseSMB` | `true`/`false` | — | 프로토콜 파싱 토글 |

> **핵심 확정:** `suricataAlertFile` + `plugins=suricata.so`로 **Suricata alert가 capture(suricata.so)를 통해 `mnx_sessions3` 세션에 결합**된다(Phase 5·7의 "추정" 브리지가 여기서 확정). `libmnxdpi.so`도 선언되어 있으나 실행 capture의 실제 로드는 core 에이전트가 미확인으로 보고(추정) — 인수 시 `/proc/<capture>/maps`로 확인 권장.

---

## 3. `/opt/mnx/etc/mnx_config.json` (엔진 공통) — 섹션별

`config_version=2026041001`. 최상위 8섹션: `global`, `mnxdpi`, `payload_analysis`, `payload_scanengine`, `payload_ai_analysis`, `service_control`, `regression_api`, `syslog`.

### 3.1 `global` (모든 서비스 공유)
| 키 | 값 | 영향 |
|---|---|---|
| `elasticsearch.address` | (배열) | 전 서비스 ES 엔드포인트 |
| `elasticsearch.tls`/`auth_id`/`auth_pw` | `false`/공백/공백 | 🔴 무인증·평문 |
| `elasticsearch.incex_session_prefix` | `mnx_sessions3` | 세션 인덱스 접두 |
| `elasticsearch.index_file_analysis_prefix` | `payload_` | 페이로드 인덱스 |
| `elasticsearch.index_ai_content_prefix`/`index_mail_content_prefix` | `ai_content-`/`mail_content-` | LLM/메일 인덱스 |
| `kafka.address` | `127.0.0.1:9092` | 버스 |
| `manage_web.core_api_url` | `https://127.0.0.1:8443` | heartbeat/제어 대상 API |
| `manage_web.core_api_cert_verify` | `false` | 자기서명 인증서 무검증 |
| `manage_web.heartbeat_path` | `/api/server/module/save` | 모듈 heartbeat 엔드포인트 |
| `base_path.pcap` | `/pipeline/raw` | pcap 1차 |
| `base_path.data` | `/data` | 데이터 루트 |
| `base_path.dpi_workspace` | `/dir_cache` | DPI 작업공간 |
| `base_path.payload_binary` | `/data/payload` | 추출 파일 |

### 3.2 `mnxdpi`
| 키 | 값 | 영향 |
|---|---|---|
| `worker_count` | **64** | DPI 병렬도(고부하 설계) |
| `subworkers_count` | 3 | 서브워커 |
| `queue_size` | 10000 | 백프레셔 큐 |
| `port` | 9500 | libmnxdpi 연동 |
| `pcap.path` | `/data/raw` | **입력 소스** |
| `pcap.mode` | `direct` | 직접읽기 |
| `pcap.exclusive_read` | `true` | 배타 읽기 |
| `pcap.files` | 4 | 동시 처리 파일수 |
| `pcap.file_size_g` | 12 | 파일 단위 |
| `payload.enabled` | `true` | payload carving 활성 |
| `payload.packets` | 30000 | 세션당 payload 패킷 |
| `heartbeat.url` | `https://localhost:8443/api/server/module/save` | 상태 보고 |
| `elasticsearch.consumer` | (16스레드) | bulk 색인 튜닝 |

### 3.3 `payload_analysis` / `payload_scanengine` / `payload_ai_analysis`
| 키 | 값 | 영향 |
|---|---|---|
| `payload_analysis.worker_count` | 8 | 오케스트레이터 병렬 |
| `payload_analysis.ai_analysis_socket_path` | `/var/run/payload_ai_analysis.sock` | AI 팬아웃 |
| `payload_analysis.dga_analysis_flag` | **`false`** | DGA 휴면 |
| `payload_analysis.custom_rule_path` | `/data/custom-rule/yara` | 커스텀 YARA |
| `payload_analysis.aiinsight_alarm_flag.*` | 전부 `false` | AI/AV/YARA/DGA 알람 비활성 |
| `payload_scanengine.worker_count` | 16 | AV 병렬 |
| `payload_ai_analysis.log_level` | `INFO` | AI 로깅 |

### 3.4 `service_control`
| 키 | 값 | 영향 |
|---|---|---|
| `worker_count`/`mode` | 2/1 | 제어 데몬 |
| `pcap_storage_config.post_path` | `/data/raw/` | 스테이징 목적지 |
| `pcap_storage_config.pcap_raw_cycle` | 4 | 이동 주기 |
| `service_list` | `ai_dga, ai_file, payload_analysis, scanengine, suricata` | **제어 대상 모듈 목록** |

> ⚠ `service_list.ai_dga = /opt/dga_analysis_ai/dga_analysis_ai.py` 참조하나 **해당 디렉터리 부재**(DGA 미배포). service_control이 기동 시도 시 실패 로그 가능(추정).

### 3.5 `regression_api` / `syslog`
| 키 | 값 | 영향 |
|---|---|---|
| `regression_api.api_url` | `http://0.0.0.0:8000` | 🔴 전 인터페이스 바인딩 |
| `regression_api.eve_types` | `["alert"]` | 재검증 대상 이벤트 |
| `syslog.execution_interval` | 5 | (분) |
| `syslog.sessioninfo_send_enable` | `false` | 세션정보 전송 비활성 |
| `syslog.syslog_server[*].enable` | 전부 `false` | 🔴 **syslog 전면 비활성(inert)** |

---

## 4. 트래픽 프로파일 (1g vs 10g)

- compose/Spring 프로파일로 선택. 두 파일의 **유일한 차이**는 `SPRING_PROFILES_ACTIVE`(1g/10g) 및 웹 `--traffic` 인자.
- 현재 실행: **1g** (`env.js VUE_APP_TRAFFIC:1g`, API `SPRING_PROFILES_ACTIVE=1g`).
- ⚠ **설정 불일치**: `web_config.ini max-traffic=10G` vs 실행 1g. stale 값으로 추정 — UI 표기 혼선 가능.
- 스케줄러 시각도 프로파일별 상이(대시보드 집계 1g 06:00 / 10g 04:00 등, Phase 6 참조).

---

## 5. 변경 위험도 등급

| 위험 | 설정 | 이유 |
|---|---|---|
| 🔴 고 | `config.ini interface=ens192` | NIC 하드코딩 — 하드웨어 교체/이름변경 시 캡처 실명 |
| 🔴 고 | `mnx_config.json global.elasticsearch/kafka.address` | 오설정 시 전 서비스 색인/버스 붕괴 |
| 🔴 고 | Spring `jwt.secret`, `JASYPT_PASSWORD` | 시크릿 노출 — 교체 필요 |
| 🟠 중 | `mnxdpi.worker_count=64` | 저사양 호스트에서 과할당 |
| 🟠 중 | `logrotate rotate 1` | 로그 유실 |
| 🟠 중 | ES `jvm.options -Xmx4g`, API `-Xmx80g` | 메모리 압박 |
| 🟡 저 | `web_config.ini` stale | 표시 혼선 |

---

## 6. 인수인계 핵심 포인트

1. **`mnx_config.json`이 엔진의 단일 진실원**(7개 서비스 공유). 여기 한 곳만 바꿔도 광범위 영향 — 변경 전 백업/버전관리 필수(`config_version` 존재).
2. `capture.env` 부재로 `mnxcapture`의 CLI 튜닝 여지가 실제로는 미사용 — 캡처 튜닝은 `config.ini`에서만.
3. **비활성 플래그 다수**: syslog(전 서버 false), DGA(false), AI/AV/YARA 알람(false) — 기능이 코드상 존재하나 설정으로 꺼져 있음. "안 된다"고 판단하기 전 설정 먼저 확인.
4. `service_control.service_list`에 **미배포 모듈(ai_dga)** 참조 잔존 — 정리 대상.
5. Spring 실제 설정은 **jar 내부**(`BOOT-INF/classes/application.yml`) — 변경하려면 이미지 재빌드 또는 외부 프로파일 마운트 필요.
