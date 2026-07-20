# Phase 14 — 코드 품질 (Code Quality)

> 근거: 소스 실측(Python), 설정/런타임 관측, `_research/01~08`.
> **한계 명시**: capture/mnxdpi/payload/scanengine/service_control는 **컴파일 바이너리(소스 부재)** → 내부 코드품질(누수/레이스)은 정적분석 불가, **런타임 증상 기반 추정**으로 표기.
> 대상: Dead Code · 중복 · 미사용 함수/API · 잠재 버그 · Race Condition · Memory Leak · 예외처리 부족.

---

## 1. Dead Code (확정)

| 항목 | 위치 | 근거 | 조치 |
|---|---|---|---|
| 미사용 인증 매니저 | `/mnxmc/utils/auth.py` | 어디서도 import 안됨(실인증은 login.py/service.py) | 삭제 또는 단일화 |
| 구 저장 로직 | `/opt/server_check/save_server.py` | 호출 없음 | 삭제 |
| 디버그 심볼 | `/opt/mnxdpi/mnxdpi.debug`(57MB) | 런타임 미사용 | 별도 보관 |
| 잔재 로그 | 각 디렉터리 `storcli.log`(mnxmc 2.4MB 등) | 편집/설치 잔재 | 삭제 |
| 백업/스왑 파일 | `packages/sudoers_mnxmc.bak`, `.install_packages.sh.swp` | 편집 잔재 | 삭제 |
| dead 라우트 | nginx `/mnx/api → :8005` | 리스너 없음 | 제거 |
| 미배포 참조 | `mnx_config.service_list.ai_dga → /opt/dga_analysis_ai/...` | 디렉터리 부재 | 참조 제거 |
| 레거시 뷰어 스택 | `/opt/mnx/node-v20`, `wise.js`, `*.jade`, 미로드 `plugins/*.so` | 웹이 Docker Vue/Spring로 대체 | 미사용 확인 후 정리(추정) |
| stale 스크립트 | `payload_analysis/start.sh`, `scanengine/start.sh`, `service_control/settings.json` | 인자 stale/미참조 | 검토 후 정리 |

---

## 2. 중복 코드 / 중복 설정

| 항목 | 내용 | 영향 |
|---|---|---|
| **인증 3중 구현** | mnxmc `utils/auth.py`(dead) + `login.py:102` + `service.py:51` 각기 `AuthenticationManager` | 보안 로직 분산, 수정 누락 위험 |
| **payload_delete cron 중복** | crontab에 `03:30` 동일 잡 2회 등록 | 03:30 2회 실행(경합/부하) |
| **MITRE 갱신 이중** | cron `01:00`(`update_mitre_attack.sh`) + Spring 스케줄 `03:00` | 동일 데이터 2메커니즘 |
| **ES 클라이언트 중복** | Spring: elasticsearch-java 8.3.3 + rest-high-level 7.15.2 | 유지보수 혼선 |
| **Selenium 드라이버 중복** | 4.18.1 + 레거시 3.141.59 | 이미지 비대·공격면 |
| **web 트래픽 설정 불일치** | 실행 1g vs `web_config.ini 10G` | 표시 혼선 |

---

## 3. 미사용 함수 / 미사용 API

| 항목 | 근거 |
|---|---|
| syslog.py 전송 경로 | `syslog_server[*].enable` 전부 false → `get_syslog_server_list`가 조기종료, 전송 함수 실행 안됨 |
| AI/AV/YARA/DGA 알람 플래그 | `aiinsight_alarm_flag.* = false` → 알람 경로 비활성 |
| 다수 permitAll 엔드포인트 | 실제 UI 사용 여부 미확인(예: `/api/server/module/save`) — 감사 필요 |
| `mnx_hunts/lookups/views/notifiers` ES 인덱스 | 문서 0 → 기능 미사용(추정) |
| CollectController/ExternalFileController 라우트 | 디컴파일 미파싱 — 사용 여부 확인 필요 |

---

## 4. 잠재 버그 (High/Critical)

| 심각도 | 버그 | 근거 | 결과 |
|---|---|---|---|
| 🔴 | **capture 무한 재시도(backoff 없음)** | `mnx_db_get_sequence_number_sync` 스핀 | CPU 낭비 + 로그 폭증 + 자동복구 불가(crash 아님) |
| 🔴 | **Hikari 300 > MariaDB max_connections 151** | 설정 실측 | 부하 시 커넥션 고갈 오류 |
| 🔴 | **API -Xmx80g > 호스트 RAM 50GB(swap 0)** | 설정 vs `free` | OOM-kill 위험 |
| 🔴 | **JWT secret = 공개 튜토리얼 값** | application.yml | 토큰 위조 가능 |
| 🟠 | **TimeoutStopSec=infinity + SendSIGKILL=no** | payload/ai/scan/service_control 유닛 | 정지 hang 시 영구 대기 |
| 🟠 | **logrotate rotate 1** | `/etc/logrotate.d/mnx` | 로그 1세대만 → 장애원인 유실 |
| 🟠 | **무인증 상태변경 엔드포인트** | `/api/user/root/save` 등 permitAll | 권한/상태 조작 가능성 |
| 🟠 | **regression_api 무인증 + 0.0.0.0** | mnx_config `api_url` | 임의 pcap 재분석 트리거 |
| 🟡 | **ctx_feed pMax 미프루닝** | 파티션 정의 | 2030+ 데이터 정리 안됨 |
| 🟡 | **JWT validity 7200000 단위 모호** | application.yml | 토큰 수명 오해석 위험(추정) |
| 🟡 | **TLS 인증서 만료** | 2024-10-15 | HTTPS 신뢰 상실 |

---

## 5. Race Condition (추정 포함)

| 지점 | 유형 | 근거 |
|---|---|---|
| service_control pcap 이동 ↔ mnxdpi `exclusive_read` | 파일 이동/읽기 타이밍 | 60초 이동과 배타읽기 경합 가능(추정, 바이너리 미검증) |
| 파일시스템 큐(`/data/raw`,`/data/payload`) | 생산/소비 + 삭제(pcap_delete) 동시성 | pcap_delete가 처리 중 파일 삭제 시 경합(추정) |
| payload_delete cron 중복 | 동일 시각 2인스턴스 동시 삭제 | 파일 삭제 경합 |
| MP_MANAGER 워커 재생성 | 워커 사망↔watcher 재생성 | 큐 아이템 유실/중복 가능(추정, 코드 리뷰 필요) |

---

## 6. Memory Leak (증상 기반, 바이너리 소스 부재)

| 항목 | 관측 | 판정 |
|---|---|---|
| mnxdpi RSS 8.7GB | idle에도 높은 상주 | mmap/PACE2 상태로 추정 — **누수 단정 불가**, 장기 관측 필요 |
| `server_status_tbl` 230k행 무한증가 | purge 없음 | **데이터 누수(스토리지)** — 확정 |
| `capture.log` 4.4GB↑ | rotate가 못 따라감 | 로그 누수 — 확정 |
| `insight_*` 성장 | 앱 purge 의존 | 잠재 무한증가(추정) |

> C/C++ 힙 누수 여부는 소스+valgrind/ASan 필요. 현재는 판단 불가 → **인수 시 장기 RSS 추이 모니터링** 권장.

---

## 7. 예외 처리 부족

| 항목 | 근거 | 결과 |
|---|---|---|
| capture 재시도 루프 | 에러를 재시도로만 처리, 상위 알림 없음 | 조용한 실명 |
| eng_monitor ES bulk `Partial errors` | 매 사이클 오류 무시하고 계속 | net-stats 부분 유실(매핑충돌 추정) |
| 컨테이너 헬스체크 부재 | compose에 healthcheck 없음(추정) | 좀비 컨테이너 감지 불가 |
| syslog 조기종료 | 정상 흐름이나 알림 없음 | 비활성 상태 은폐 |

---

## 8. 보안 품질 요약 (Phase 6·11 상세)

| 심각도 | 항목 |
|---|---|
| 🔴 | JWT 공개 시크릿, JASYPT_PASSWORD 평문(compose), TLS 만료, ssl.pass `mnx#123`, config.ini `passwordSecret` 하드코딩 |
| 🔴 | ES/Kafka 익명·평문·전 인터페이스 노출 |
| 🟠 | mnxmc `shell.py` root `/bin/bash --login` 무제한, tty1 idle timeout 미적용 |
| 🟠 | 무인증 상태변경 API, regression_api 무인증 |

---

## 9. 코드 품질 총평 & 인수 우선순위

**총평**: 기능적으로 완성도 높은 상용 NDR이나, **운영 안전장치(백오프/헬스체크/보존/시크릿관리)와 리소스 정합성**에서 결함이 집중. Python 계층은 구조가 명확하나 인증 중복·dead code 존재. C/C++ 데이터플레인은 소스 부재로 내부 품질 검증 불가.

**인수 후 즉시(P0)**:
1. Hikari↔max_connections, -Xmx80g 정합 (성능 장애 확정 요인)
2. JWT secret·JASYPT·TLS 인증서 교체 (보안)
3. capture 워치독 + 디스크 알림 (실장애 재발 방지)

**단기(P1)**: dead code/중복 cron 정리, logrotate rotate 상향, 무인증 엔드포인트 잠금, 무한증가 테이블 purge.

**중기(P2)**: 인증 로직 단일화, C/C++ 소스 확보 후 정적분석, Kafka 파티션·ES 노드 확장.
