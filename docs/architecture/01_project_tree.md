# Phase 1 — 프로젝트 트리 (Project Tree)

> 분석 기준: 2026-07-10, 운영 어플라이언스 실 파일시스템.
> 모든 항목은 실제 파일/프로세스/systemd/디스크 확인 결과에 근거한다. 확신이 없는 항목은 **(추정)** 표기.
> 근거 스냅샷: `_research/00_runtime_snapshot.md`, 서브시스템 상세: `_research/01~08_*.md`.

---

## 1. 시스템 정체성 요약

| 항목 | 값 | 근거 |
|---|---|---|
| 제품 | MNX NDR (Network Detection & Response) 어플라이언스 | 디렉터리/서비스 전반 |
| 관리 콘솔 버전 | **MNXMC v2.3.1** (deb 패키지 트랙) | `/mnxmc/.claude/CLAUDE.md`, `/data/mnxmc-2.3.1.deb` |
| NDR 엔진(Web/API) 버전 | **Docker `v23.5.1.2`** (별도 트랙) | `docker images`: `mnx-api-v23`, `mnx-web-v23` |
| 캡처 엔진 | **자체 캡처 엔진(패키지 버전 5.8.2)** | `/opt/mnx/include/mnxconfig.h:68` `PACKAGE_STRING "mnx 5.8.2"` |
| DPI 엔진 | 자체 `mnxdpi` (PACE2/ipoque + PcapPlusPlus 임베드) | `strings /opt/mnxdpi/mnxdpi` |
| IDS | Suricata 8.0.4 | `suricata -V`, `/etc/suricata/suricata.yaml` |
| Web/API 스택 | **Spring Boot(Java 17) + Vue SPA** (FastAPI 아님) | `mnx_api_server` 컨테이너 `app.jar`, `mnx_web_server` nginx+Vue |
| 데이터 저장소 | Elasticsearch **7.17.29**(단일노드), Kafka 3.8.0(RF=1), MariaDB (`mnx_db`, 63테이블) | `_research/07`. **Redis·PostgreSQL 미사용 확정** |
| 메시지 버스 | Kafka 토픽 `request-file-analysis` (단일 핵심 토픽) | `_research/02,03,04` |

> **주의(사용자 요구사항 대비 정정):** 요구서에는 PostgreSQL·FastAPI·React가 언급되었으나, 실제 운영 시스템은 **MariaDB + Spring Boot(Java) + Vue** 조합이다. Redis·PostgreSQL·React·FastAPI는 이 어플라이언스에서 **사용되지 않는다**(실 프로세스·컨테이너 라이브러리·설정에서 미발견).

---

## 2. 물리 배치(파일시스템 마운트) 개관

`df -h` 근거 (`_research/00_runtime_snapshot.md`):

| 마운트 | 크기 | 사용률 | 용도 |
|---|---|---|---|
| `/` (sda3) | 187G | 21% | OS + `/opt/*` 엔진 바이너리 + `/mnxmc` 콘솔 |
| `/application` (sdd1) | 20G | **91% ⚠** | Web/API 산출물 데이터(리포트/대시보드/자산/커스텀룰/ES 템플릿) |
| `/data` (sdd2) | 40G | **77% ⚠** | raw pcap(31G), payload, 설치 deb |
| `/logs` (sdb4) | 30G | 35% | 전 컴포넌트 로그 |
| `/pipeline` (sdc1) | 49G | 59% | 캡처 raw 작업공간(pcap 심볼릭 원본) |
| `/docker` (sdb3) | 15G | 3% | 컨테이너 overlay |
| `/dir_cache` (sdb2) | 9.8G | 1% | (추정) 디렉터리 캐시 |

> `/application` 91%, `/data` 77%는 현재 **핵심 장애의 근원**(Phase 12·13 참조): ES가 flood-stage 워터마크로 인덱스를 `read-only-allow-delete`로 잠갔고, 이로 인해 캡처가 시퀀스번호 획득 무한 재시도에 빠져 **7/1 이후 pcap 생성이 중단**됨.

---

## 3. 컴포넌트 트리 & 속성표

범례 — **중요도**: 필수(Critical)/높음/중간/낮음 · **실행**: 상시(데몬)/스케줄(cron)/온디맨드/컨테이너/미실행 · **사용**: 사용중/부분/미사용 · **DeadCode**: 예/아니오/부분

### 3.1 `/mnxmc` — 관리 콘솔 (MNXMC v2.3.1, Python/Textual TUI)

```
/mnxmc
├── main-login.py         # tty1 진입점 (getty override로 기동, root, pid 4020 실행중)
├── main.py               # SSH 진입점
├── app/
│   ├── main_app.py       # MNXApp (Textual App)
│   ├── screens/          # 11개 화면(dashboard/login/service/mnx_config/log/firewall/shell 등)
│   ├── widgets/          # 커스텀 위젯
│   └── styles/           # TCSS 스타일
├── modules/              # 백엔드 로직(system_info/performance_monitor/disk_monitor/
│   │                     #   kafka_monitor/elasticsearch_monitor/firewall_manager/log_viewer)
│   └── base_module.py
├── network_management/   # network_config.py, network_management.py (netplan/방화벽)
├── utils/
│   ├── auth.py           # ⚠ DEAD: 미사용 AuthenticationManager
│   └── helpers.py
├── packages/             # 설치/패키징 자산: build_deb.sh, install_packages.sh,
│   │                     #   sudoers_mnxmc, apply_sudoers.sh, storcli/perccli/mnx_fio, pip/apt
│   └── sudoers_mnxmc.bak # ⚠ 백업 잔재
├── infra_audit/reports/  # 감사 리포트 산출물
├── test-tool/            # pcap_bw_calc.sh, raw_usage_monitor.sh, pcap_replay_console_all.sh
├── requirements.txt      # Python 의존성
├── readme_install_mnxmc.txt
├── clean_cache.sh
├── storcli.log           # ⚠ 잔재 로그(2.4MB) — DeadCode/오염
├── tmp/                  # 임시
└── docs/architecture/    # ← 본 분석 산출물
```

| 경로 | 역할 | 중요도 | 실행 | 사용 | DeadCode |
|---|---|---|---|---|---|
| `main-login.py` | tty1 로그인/콘솔 진입 | 높음 | 상시(tty1) | 사용중 | 아니오 |
| `main.py` | SSH 콘솔 진입 | 높음 | 온디맨드 | 사용중 | 아니오 |
| `app/screens/` | TUI 화면 11종 | 높음 | 온디맨드 | 사용중 | 아니오 |
| `modules/` | 시스템/ES/Kafka/디스크/방화벽 모니터 | 높음 | 온디맨드 | 사용중 | 아니오 |
| `utils/auth.py` | 인증 매니저(구현체) | — | 미실행 | **미사용** | **예** — `login.py`/`service.py`가 각자 별도 인증 사용(3중 중복) |
| `packages/` | 설치·sudoers·펌웨어툴 | 중간 | 온디맨드 | 사용중 | 부분(`.bak`,`.swp`,`storcli.log`) |
| `test-tool/`, `tmp/`, `storcli.log` | 시험/잔재 | 낮음 | — | 부분 | 부분 |

근거: `_research/01_mnxmc_console.md`. **주의**: 이 콘솔은 **어떤 TCP 포트도 LISTEN하지 않음**(TUI). 아웃바운드로 ES(9200)·Kafka CLI만 사용, MariaDB 미접근.

### 3.2 `/opt/mnx` — 캡처 엔진 (자체 캡처 엔진(패키지 버전 5.8.2)) **[데이터 플레인 핵심]**

```
/opt/mnx
├── bin/
│   ├── capture                 # ELF 네이티브 캡처 데몬(pid 18353, user=nobody 실행중)
│   └── mnx_config_interfaces.sh# NIC/promisc/offload/ring 설정(ExecStartPre)
├── etc/
│   ├── config.ini              # 캡처 핵심 설정(ES주소/인덱스/BPF/스레드/plugins)
│   ├── mnx_config.json         # 엔진 공통 설정(dpi/payload/ai/scan/kafka/es) — 다수 서비스 공유
│   └── (capture.env 부재 → OPTIONS 빈값)
├── parsers/  (*.so ×47)        # 프로토콜 파서: dns/http/tls/smb/quic/mysql/postgresql/
│   │                           #   oracle/radius/snmp/modbus/socks/gre/vxlan/... + *.detail.jade
├── plugins/                    # suricata.so, libmnxdpi.so (설정상 로드 대상)
│   │                           # + netflow/wise/lua/tagger/scrubspi/writer-s3/... (.so, 미로드)
│   │                           # + wise.js, garland.js, *.jade (node 뷰어용)
├── db/db.pl                    # ES 스키마/인덱스 초기화 Perl 스크립트
├── include/*.h                 # 빌드 헤더(mnxconfig.h 등) — 런타임 미사용
├── node-v20.19.4-linux-x64/    # 번들 Node 20 — 레거시 viewer/wise/cont3xt/parliament용
└── LICENSE, README.txt
```

| 경로 | 역할 | 중요도 | 실행 | 사용 | DeadCode |
|---|---|---|---|---|---|
| `bin/capture` | 라이브 패킷 캡처→pcap+ES 세션 | **필수** | 상시(nobody) | 사용중(현재 stall) | 아니오 |
| `bin/mnx_config_interfaces.sh` | 캡처 NIC 사전 설정 | 필수 | 부팅 시 1회 | 사용중 | 아니오 |
| `etc/config.ini` | 캡처 설정 | 필수 | — | 사용중 | 아니오 |
| `etc/mnx_config.json` | 엔진 공통 설정(공유) | 필수 | — | 사용중 | 아니오 |
| `parsers/*.so` (47) | 프로토콜 파싱 | 필수 | in-process | 사용중 | 아니오(일부 프로토콜 트래픽 미출현 시 idle) |
| `plugins/suricata.so` | eve.json 알럿 흡수 | 높음 | in-process | 사용중(설정상) | 아니오 |
| `plugins/libmnxdpi.so` | 세션→mnxdpi 연동 | 높음 | (설정 선언) | **실제 미로드**(추정) | 부분 — 실행 capture가 로드하지 않음 |
| `plugins/*.so`(netflow/wise/lua/tagger/writer-s3 등) | 확장 | 낮음 | 미로드 | **미사용** | 예(이 배포 기준) |
| `node-v20.../` + `wise.js`/`*.jade` | 레거시 JS 뷰어/enrichment | 낮음 | 미실행(추정) | **미사용**(웹이 Docker Vue/Spring으로 대체) | 예(추정) |
| `db/db.pl` | ES 인덱스 초기화 | 중간 | 온디맨드(설치/업그레이드) | 사용중 | 아니오 |
| `include/*.h` | 컴파일 헤더 | 낮음 | — | 런타임 미사용 | 부분(배포 잔재) |

근거: `_research/02_mnx_core.md`.

### 3.3 `/opt/mnxdpi` — DPI 엔진

```
/opt/mnxdpi
├── mnxdpi          # ELF64 stripped 15MB (pid 18076 실행중, PACE2+PcapPlusPlus 임베드)
├── mnxdpi.debug    # 57MB 디버그심볼 — 런타임 미사용(배포 잔재)
└── storcli.log     # ⚠ 잔재 로그
```

| 경로 | 역할 | 중요도 | 실행 | 사용 | DeadCode |
|---|---|---|---|---|---|
| `mnxdpi` | 오프라인 pcap DPI 분류→ES+Kafka | **필수** | 상시(부팅 disabled, 상위 Requires로 기동) | 사용중(현재 idle) | 아니오 |
| `mnxdpi.debug` | 디버그 심볼 | 낮음 | — | 미사용 | 예(잔재) |
| `storcli.log` | 잔재 | 낮음 | — | 미사용 | 예 |

근거: `_research/03_dpi_suricata.md`.

### 3.4 페이로드 분석 계열

```
/opt/payload_analysis
├── payload_analysis   # C++ ELF 데몬(pid 17833). Kafka소비→YARA→AI/AV 팬아웃→ES
├── file_type.yar      # YARA 파일타입 규칙
├── start.sh / stop.sh # start.sh는 인자 stale(추정 DeadCode)
/opt/file_analysis_ai
├── file_analysis_ai.py# Python 마스터(pid 16936) + 워커 16
├── daemon.py, mp_manager.py, settings.py
└── model/{exe,dll,pdf,doc,docx,xls,xlsx,ppt,pptx,hwp}/  # 타입별 악성탐지 모델(2.1GB, XGBoost/RF)
/opt/scanengine
├── scanengine_bitdefender  # C++ ELF(pid 16374). BitDefender ThreatScanner SDK 래퍼
├── updater_bitdefender     # 시그니처 갱신기(cron 4h)
├── lib/{libbdscan,libbdupdatesdk,libbdquar}.so
├── Update1/, Update2/      # 엔진코어(bdcore.so)+시그니처
├── pattern_path.conf
└── start.sh / stop.sh
```

| 컴포넌트 | 역할 | 중요도 | 실행 | 사용 | DeadCode |
|---|---|---|---|---|---|
| `payload_analysis` | 파이프라인 오케스트레이터(Kafka→AI/AV→ES) | 높음 | 상시 | 사용중 | 아니오 |
| `file_analysis_ai.py` | ML 악성 파일 분류(소켓 서버) | 높음 | 상시(16워커) | 사용중 | 아니오 |
| `model/*` (2.1GB) | 타입별 모델 | 높음 | 로드 | 사용중 | 아니오 |
| `scanengine_bitdefender` | AV 시그니처 스캔(소켓 서버) | 높음 | 상시 | 사용중 | 아니오 |
| `updater_bitdefender` | AV 시그니처 갱신 | 중간 | 스케줄(4h) | 사용중 | 아니오 |
| `payload_analysis/start.sh` | 수동 기동 스크립트 | 낮음 | 온디맨드 | 미사용(추정) | 부분 |

근거: `_research/04_payload_ai_scan.md`. DGA 계열(`dga_analysis`)은 **휴면**(`dga_analysis_flag=false`, `/opt/dga_analysis_ai` 부재, `/data/dga_result` 비어있음).

### 3.5 제어·모니터링·지원 서비스

```
/opt/service_control
├── service_control   # C++ ELF "MNX v23 Service Control"(pid 15585, 4스레드).
│                     #   모듈 start/stop/restart(UNIX소켓 /var/run/service_control.sock),
│                     #   웹(:8443)에 heartbeat/patch/version, /pipeline/raw→/data/raw 60s 이동
├── settings.json     # ⚠ stale/미사용(추정 DeadCode)
└── start.sh / stop.sh
/opt/regression_api    # Python http.server + 5프로세스 풀(pid 18814, :8000)
├── app.py            # 진입점/라우팅
├── suricata_runner.py# 저장 pcap에 Suricata 룰 재실행
├── session_mapper.py, es_client.py, worker_pool.py, job_state.py,
├── status_store.py, paths.py, config.py, logger.py
/opt/server_check
├── server_check.py   # psutil CPU/mem/disk → 웹 /api/server/status/save (cron ~30s)
├── save_server.py    # ⚠ DEAD(미사용)
└── log/
/opt/syslog
├── syslog.py         # 탐지 syslog 포워딩(cron 5m) — 현재 inert(모든 서버 enable:false)
├── settings.py, mp_manager.py
```

| 컴포넌트 | 역할 | 중요도 | 실행 | 사용 | DeadCode |
|---|---|---|---|---|---|
| `service_control` | 엔진 모듈 오케스트레이션/헬스/pcap 스테이징 | **필수** | 상시 | 사용중 | 아니오 |
| `regression_api` | 내부 REST(룰 재검증/세션 enrich), :8000 | 중간 | 상시 | 사용중 | 아니오 |
| `server_check.py` | 서버 리소스 수집→웹 | 중간 | 스케줄(~30s) | 사용중 | 아니오 |
| `save_server.py` | (구)저장 로직 | — | 미실행 | 미사용 | **예** |
| `syslog.py` | 탐지 syslog 전송 | 낮음 | 스케줄(5m) | **inert**(설정 비활성) | 부분(코드는 살아있음) |
| `service_control/settings.json` | 설정 | — | — | 미사용(추정) | 예(추정) |

근거: `_research/06_support_services.md`.

### 3.6 Web/API (Docker) 및 프론트 데이터

```
/opt/mnx_web/                         # 컨테이너 기동 정의만 존재
├── docker-compose-api-1g.yml  / -10g.yml
└── docker-compose-web-1g.yml  / -10g.yml   # 1g/10g는 SPRING_PROFILES_ACTIVE/--traffic만 상이

컨테이너(호스트 network=host):
├── mnx_api_server  (mnx-api-v23:v23.5.1.2)  # Spring Boot/Java17 app.jar, :8443 HTTPS,
│                                             #   ~244 endpoint/37 controller, MariaDB+ES
└── mnx_web_server  (mnx-web-v23:v23.5.1.2)  # nginx(1.28.2)+Vue SPA, :80/:443/:8090

/application/mnx_web/                  # ← 코드 아님, Web/API 산출 데이터
├── apikey/<HASH>          # 외부 API 키
├── dashboard/Net-1, monitor/Net-1     # 센서별 대시보드/모니터 데이터
├── mitre_attack/{mitre_attack.json, update_mitre_attack.sh}  # MITRE CTI(cron 01:00)
├── asset/ipv4             # 자산 인벤토리
├── report/{data,pdf}      # 리포트 산출
└── blackbox/per_day       # 블랙박스 로그
/application/custom-rule/suricata/     # SANDS_* 커스텀 룰(한국형 PII/DLP 포함)
/application/es/                       # ES 인덱스 템플릿/파이프라인(추정)
/application/kafka/                    # Kafka 관련(추정)
```

| 컴포넌트 | 역할 | 중요도 | 실행 | 사용 | DeadCode |
|---|---|---|---|---|---|
| `mnx_api_server` | 백엔드 API(Spring Boot) | **필수** | 컨테이너 상시 | 사용중 | 아니오 |
| `mnx_web_server` | 프론트(Vue)+리버스프록시 | **필수** | 컨테이너 상시 | 사용중 | 아니오 |
| `docker-compose-*-{1g,10g}.yml` | 트래픽 프로파일별 기동 | 필수 | 온디맨드 | 사용중(택1) | 아니오(미사용 프로파일 파일은 보관) |
| `/application/mnx_web/*` | 웹 산출 데이터 | 높음 | — | 사용중 | 아니오 |
| `/mnx/api → :8005` nginx 라우트 | (구)경로 | — | 미실행 | **미사용** | **예**(리스너 없음, dead route) |

근거: `_research/05_web_api_docker.md`.

### 3.7 데이터스토어 & 미들웨어

```
/usr/local/kafka/           # Kafka 3.8.0 + Zookeeper 3.8.4 (config/{server,zookeeper}.properties)
/usr/share/elasticsearch/   # Elasticsearch 8.x (Xms/Xmx 4g)
/var/lib/mysql/mnx_db/      # MariaDB 데이터(:3306 localhost)
/application/es/            # ES 인덱스 템플릿(추정)
```
(상세 스키마/인덱스/토픽은 Phase 7 및 `_research/07_datastores.md`에서 다룸 — 해당 분석 진행 중)

### 3.8 운영 도구 & 스케줄 (`/data/tools`, cron, systemd)

```
/data/tools/
├── MNX_all_start_service.sh / MNX_all_stop_service.sh / without_db_MNX_all_stop_service.sh
├── MNX_check_stop_order.sh / MNX_status_check.sh / MNX_Reset.sh
├── docker_run_1g.sh / docker_run_10g.sh        # 컨테이너 기동
├── eng_monitor.sh                              # NIC 처리량→ES(net-stats-YYYYMM) [systemd]
├── pcap_delete.py    (cron 10m, /data/raw ≥80% 삭제)
├── payload_delete.sh (cron 03:30, RETENTION_DAY=1) — ⚠ crontab 중복 등록
├── check_index.sh / check_kafka.sh / check_slowlog.sh / cleanup_es.sh
├── es_dynamic_sharding_v2.sh / rdb_clear.sh / log_clear.sh / monitor_logs.sh
```

| 항목 | 역할 | 중요도 | 실행 | 사용 | DeadCode |
|---|---|---|---|---|---|
| `MNX_all_start/stop_service.sh` | 전체 기동/정지 오케스트레이션 | 높음 | 온디맨드 | 사용중 | 아니오 |
| `eng_monitor.sh` | NIC 처리량 모니터 | 중간 | 상시(systemd) | 사용중 | 아니오 |
| `pcap_delete.py` | pcap 보존관리 | 높음 | 스케줄(10m) | 사용중 | 아니오 |
| `payload_delete.sh` | payload 보존관리 | 중간 | 스케줄(03:30) | 사용중 | 부분(**중복 등록**) |
| `check_*/cleanup_es/es_dynamic_sharding` | ES/Kafka 점검·정리 | 중간 | 온디맨드 | 부분 | 부분 |
| `rdb_clear.sh`/`log_clear.sh` | 초기화/정리 | 낮음 | 온디맨드 | 부분 | 부분(추정) |

### 3.9 설치/패키징 자산

| 항목 | 역할 | 근거 |
|---|---|---|
| `/data/mnxmc-{2.1.3,2.1.4,2.2.0,2.3.0,2.3.1}.deb` | 콘솔 설치 패키지(버전 이력) | `ls /data` |
| `/home/sands/mnxmc_deb_build/` | deb 빌드 작업트리 | `find` |
| `/mnxmc/packages/build_deb.sh`, `install_packages.sh` | 빌드/설치 스크립트 | 트리 |
| `/mnxmc/readme_install_mnxmc.txt` | 설치/업그레이드 절차서 | 파일 |
| `/data/tools/docker_run_{1g,10g}.sh` | 엔진 컨테이너 배포 | 트리 |

---

## 4. Dead Code / 미사용 자산 요약 (Phase 14 상세)

| 분류 | 항목 | 판정 근거 |
|---|---|---|
| 확정 Dead | `/mnxmc/utils/auth.py` | 실사용 인증은 `login.py`/`service.py`가 별도 구현. import 안됨 |
| 확정 Dead | `/opt/server_check/save_server.py` | 어디서도 호출 안됨 |
| 확정 Dead | `mnxdpi.debug`, 각 디렉터리 `storcli.log`, `*.bak`, `*.swp` | 배포/편집 잔재 |
| 확정 Dead | nginx `/mnx/api → :8005` 라우트 | 리스너 없음 |
| 부분/추정 | `/opt/mnx/plugins/*` (suricata·libmnxdpi 외), `node-v20`/`wise.js`/`*.jade` | 실행 capture가 미로드, 웹은 Docker로 대체 |
| 부분/추정 | `syslog.py` | 코드 정상이나 설정상 전부 비활성(inert) |
| 부분/추정 | `service_control/settings.json`, `payload_analysis/start.sh`, `scanengine/start.sh` | stale 인자/미참조 |
| 운영 결함 | `payload_delete.sh` crontab 중복 | 동일 시각(03:30) 2회 실행 |

---

## 5. 중요도 기준 Top 컴포넌트 (인수인계 우선순위)

1. **`/opt/mnx/bin/capture`** — 모든 세션 메타/pcap의 원천. 죽으면 NDR 실명(失明).
2. **`mnx_api_server` (Spring Boot)** — UI/외부연동/데이터 조회의 단일 게이트웨이(:8443).
3. **Elasticsearch** — 모든 세션/알럿/리포트의 저장·조회 기반. 현재 장애 근원(디스크).
4. **`service_control`** — 엔진 모듈 수명주기 + pcap 스테이징의 중추.
5. **`mnxdpi` + `payload_analysis` + `file_analysis_ai` + `scanengine`** — 위협 분석 체인.
6. **Kafka** — 캡처/DPI → 페이로드 분석 사이의 유일한 비동기 버스.
7. **`mnx_web_server` (Vue+nginx)** — 사용자 접점 및 TLS 종단.
8. **MariaDB `mnx_db`** — 사용자/설정/자산 등 관계형 상태.
9. **`/mnxmc` 콘솔** — 로컬 운영/복구 인터페이스.

> Phase 2(부팅), Phase 3(프로세스), Phase 12(장애)에서 위 컴포넌트 간 의존·기동 순서를 상술한다.
