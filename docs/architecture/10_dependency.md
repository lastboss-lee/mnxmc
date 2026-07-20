# Phase 10 — 의존성(Dependency) 분석

> 근거: `requirements.txt`, 소스 import 실측, `ldd`(공유 라이브러리), `docker image inspect`, `lsmod`(커널 모듈), `_research/05·07`.
> 대상: 외부 라이브러리 · Python 패키지 · 공유 라이브러리 · Docker 이미지 · 커널 모듈 · 외부 SaaS.

---

## 1. 런타임/언어 스택

| 런타임 | 버전 | 위치 | 사용처 |
|---|---|---|---|
| Python | **3.12.13** | 시스템 | mnxmc, file_analysis_ai, regression_api, syslog, server_check |
| OpenJDK | 17.0.18 | API 컨테이너 | Core API(Spring) |
| JDK(번들) | ES/Kafka 내장 | `/usr/share/elasticsearch/jdk` | ES·Kafka·ZK |
| Node.js | v20.19.4 | `/opt/mnx/node-v20.19.4-linux-x64` | 레거시 뷰어(**미사용 추정**) |
| C/C++ | glibc(Ubuntu 22.04) | — | capture/mnxdpi/payload/scanengine/service_control |

> ⚠ **Python 3.13 마이그레이션 위험**: mnxmc `login.py`/`service.py`가 3.13 제거 예정 `spwd`/`crypt` 직접 사용. 현재 3.12.13에서만 동작.

---

## 2. Python 패키지

### 2.1 mnxmc 콘솔 (`requirements.txt`, 오프라인 whl)
| 패키지 | 버전 | 용도 |
|---|---|---|
| textual | 8.2.1 | TUI 프레임워크 |
| rich | 14.3.3 | 터미널 렌더링 |
| requests / urllib3 | 2.33.1 / 2.6.3 | ES 모니터 HTTP |
| cryptography | >=43,<46 | mnx_config Fernet 암호(시스템 패키지 의존) |
| pygments, markdown-it-py, mdit-py-plugins, linkify-it-py, platformdirs, typing_extensions | (핀) | 렌더/유틸 |

> 오프라인 설치: `pip install --no-index --find-links ./packages/pip`. **cryptography는 시스템 설치 의존**(whl 미포함) → 설치 환경 차이 시 실패 위험.

### 2.2 file_analysis_ai (ML)
| 패키지 | 용도 | 근거 |
|---|---|---|
| **filekit** (사내) | 파일 파싱/특징추출 | import 실측 |
| **modelcore** (사내) | 모델 로딩/추론 래퍼 | `_research/04` |
| **XGBoost** | 타입별 악성 분류 | `_research/04` |
| **scikit-learn**(RandomForest) | 분류 | `_research/04` |
| **torch** | (CPU 전용, cuda 미사용) → `pt_main_thread` | `_research/04` |
| stdlib | multiprocessing, socket, threading, logging | import |

### 2.3 지원 스크립트
| 서비스 | 의존 |
|---|---|
| regression_api | **stdlib 중심**(http.server, socketserver, multiprocessing, ssl, subprocess) + requests/urllib3 |
| syslog | requests, ssl, socket, multiprocessing |
| server_check | **psutil**, requests |

---

## 3. 공유 라이브러리 (C/C++, `ldd`)

| 바이너리 | 링크 라이브러리(핵심) | 임베드/전용 |
|---|---|---|
| **capture** | libpcre3, libssl/libcrypto3, **libmagic**, libz (+ capture는 파서 `.so` 47개 dlopen) | GeoIP/glib은 dlopen(추정) |
| **mnxdpi** | **libpcap0.8**, libcurl4, **librdkafka++/librdkafka**, **libspdlog**, libstdc++6, libssl3 | **PACE2(ipoque)** + **PcapPlusPlus** 임베드(정적 추정) |
| **payload_analysis** | librdkafka, libcurl4, **libyara.so.10**(`/usr/local/lib`), libssl3 | YARA 엔진 |
| **scanengine_bitdefender** | **libbdscan.so**(`/opt/scanengine/lib`) → dlopen `Update{1,2}/bdcore.so`, `libbdupdatesdk.so`, `libbdquar.so` | **BitDefender ThreatScanner SDK** |
| service_control | libstdc++, libc(추정) | — |

> `libyara.so.10`, `libbdscan.so`는 **비표준 경로**(`/usr/local/lib`, `/opt/scanengine/lib`) — `LD_LIBRARY_PATH`/`ldconfig` 의존. 이미지/호스트 이전 시 주의.

---

## 4. Java 의존성 (Core API `app.jar` `BOOT-INF/lib`)

| 라이브러리 | 버전 | 용도 |
|---|---|---|
| Spring Boot / Web MVC | (17 기반) | 프레임워크 |
| Spring Security | 5.6.3 | 인증/인가 |
| Spring Data Elasticsearch | 4.3.4 | ES ORM |
| elasticsearch-java / rest-high-level-client | 8.3.3 / 7.15.2 | ES 클라이언트(**혼재**) |
| MariaDB JDBC + HikariCP | — | DB 풀(300) |
| Hibernate/JPA | — | ORM(`ddl-auto: update`) |
| jjwt | 0.11.2 | JWT |
| jasypt-spring-boot-starter | 3.0.5 | 설정 암호 |
| gson | 2.9.0 | JSON |
| **Selenium** + chromedriver | 4.18.1 (+레거시 3.141.59) | 리포트 HTML→PDF 렌더 |
| pcap4j | 1.8.2 | pcap 파싱 |

> ⚠ ES 클라이언트 **버전 혼재**(8.3.3 + 7.15.2) — ES 서버가 7.17.29이므로 rest-high-level 7.15.2 경로 사용 추정. 업그레이드 시 정합성 주의. Selenium/chromedriver + 레거시 드라이버는 이미지 공격면 확대.

---

## 5. 미들웨어 / 데이터스토어

| 컴포넌트 | 버전 | 비고 |
|---|---|---|
| Elasticsearch | 7.17.29 | 번들 JDK, heap 4g, 단일노드 |
| Kafka | 3.8.0 (Scala 2.13) | ZK 모드, heap 1g |
| Zookeeper | 3.8.4 | Kafka 번들, heap 512m |
| MariaDB | (10.x 계열) | `mnx_db` |
| nginx | 1.28.2 | 웹 컨테이너(Alpine) |
| Suricata | 8.0.4 | af-packet |

---

## 6. Docker 이미지

| 이미지 | 베이스 | 크기 | 주요 |
|---|---|---|---|
| `mnx-api-v23:v23.5.1.2` | Ubuntu 22.04.5 + OpenJDK 17.0.18 | ~1.95GB | Spring `app.jar`(252MB), Selenium+Chrome |
| `mnx-web-v23:v23.5.1.2` | Alpine + nginx 1.28.2 | ~331MB | 빌드된 Vue SPA + Storybook |

- 빌드일 2026-03-25. `network_mode: host`. `restart: always`(compose).
- 웹 SPA는 이미지에 baked(런타임 `env.js`만 주입). API 설정은 jar 내부 `application.yml`.

---

## 7. 커널 모듈 / OS 의존

| 모듈 | 용도 |
|---|---|
| **af_packet**(+af_packet_diag) | capture(TPACKET_V3) + suricata AF_PACKET 캡처 |
| bridge / stp / llc | Docker 브리지 네트워크 |
| nf_tables / nf_conntrack / nf_nat / nft_* / ip_set | 방화벽(nftables) + Docker NAT |
| NIC 드라이버(ens192) | **VMware vmxnet3 추정**(ens192 명명 = 가상 어플라이언스). 모듈 목록 미노출 → 빌트인 또는 미표기(추정) |

> **가상 어플라이언스**로 판단(ens192, 디스크 다중 vmdk). 물리 배포 시 NIC 드라이버·오프로드 튜닝(`mnx_config_interfaces.sh`) 재검증 필요.

---

## 8. 외부 SaaS / 네트워크 의존 (아웃바운드)

| 대상 | 용도 | 사용 주체 | 주기 |
|---|---|---|---|
| VirusTotal (`virustotal.com/api/v3`) | 파일 평판 | Core API TI | 온디맨드 |
| CTX/Cont3xt (`mnx-proxy.ctx.io`) | IP/도메인 인텔 | Core API + `ctx_feed_*` | 온디맨드 |
| malwares.com (`public.api.malwares.com`) | 악성 판정 | Core API | 온디맨드 |
| idpw.io (`mnx-api.idpw.io`) | 계정 유출 조회 | Core API | 온디맨드 |
| MITRE CTI (github raw) | ATT&CK 매핑 | `update_mitre_attack.sh` | 매일 01:00 |
| BitDefender 업데이트 서버 | AV 시그니처 | `updater_bitdefender` | 4시간 |
| MaxMind GeoLite2 | GeoIP | Core API/capture | (DB 파일 마운트) |
| SMTP/Slack/Splunk HEC | 알림/전달 | Core API | 설정 시 |

> **폐쇄망 배포 시**: 위 아웃바운드가 막히면 TI enrichment·MITRE·AV 갱신 실패(코어 캡처/탐지는 지속). 프록시/오프라인 미러 정책 필요.

---

## 9. 의존성 리스크 요약

| 리스크 | 항목 | 영향 |
|---|---|---|
| 🔴 | Python 3.13 시 `spwd`/`crypt` 제거 | mnxmc 로그인 붕괴 |
| 🟠 | 사내 패키지(filekit/modelcore) 소스 미확보 | AI 모듈 유지보수 불가 |
| 🟠 | PACE2/BitDefender **상용 SDK 라이선스** | 만료/갱신 관리 필요 |
| 🟠 | ES 클라이언트 버전 혼재 | 업그레이드 정합성 |
| 🟠 | 비표준 lib 경로(libyara/libbdscan) | 이전 시 로드 실패 |
| 🟡 | node/레거시 뷰어 미사용 잔존 | 이미지 비대·혼선 |
| 🟡 | Selenium+Chrome 번들 | 공격면·이미지 크기 |

---

## 10. 인수인계 핵심 포인트

1. **상용 SDK 2종**(ipoque PACE2, BitDefender)의 **라이선스·갱신 경로**를 최우선 인수 — 만료 시 DPI/AV 정지.
2. **사내 Python 패키지**(filekit, modelcore) 소스 저장소 확보 — 없으면 AI 분석 유지보수 불가.
3. C/C++ 바이너리 **소스·빌드 저장소 부재**(어플라이언스엔 산출물만) — 반드시 확보.
4. 폐쇄망 정책 하 **외부 TI/AV/MITRE 갱신 경로** 사전 설계.
