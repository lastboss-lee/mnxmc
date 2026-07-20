# 08 · 인프라 / 부팅 / 패키징 (systemd · 네트워크 · logrotate · cron · 설치/업그레이드)

> 조사 대상: MNX NDR 제품의 부팅 오케스트레이션, 모니터링 NIC 준비, 로그 로테이션, cron, deb 설치/업그레이드.
> 모든 주장은 실제 파일 `file:line` 로 근거를 제시한다. 확인 불가 항목은 **추정(unverified)** 로 표기.
> 수집 일자: 2026-07-10 (라이브 시스템, Ubuntu 22.04, VMware, systemd)

---

## 1. Overview

- 이 호스트는 단일 노드 올인원 MNX NDR 어플라이언스이다. 캡처/DPI/페이로드 분석 엔진은 `/opt/*` 네이티브 바이너리 + systemd 로 구동되고, Web/API 는 Docker 컨테이너(`mnx-web-v23`, `mnx-api-v23`, 태그 `v23.5.1.2`)로 구동된다 (`docker ps`).
- MNX 커스텀 systemd 유닛은 **13개**: elasticsearch, kafka, zookeeper, mnxcapture, mnxdpi, mnx_payload, mnx_payload_ai, mnx_payload_scan, mnx_regression_api, mnx_service_control, eng_monitor, promisc-ens192, suricata.
- 부팅 정책은 `Requires=`(하드 의존) + `After=`(순서) + `ExecStartPre` 슬립으로 조합되어 있고, 다수 유닛이 `elasticsearch.service` 와 `kafka.service` 에 하드 의존한다 → 단일 실패점.
- 데이터/로그 레이아웃: `/data`(31G raw pcap, 77% 사용), `/logs`(엔진 로그, 35% 사용), `/pipeline`, `/application`(91% 사용, 경고 수준), `/docker`.
- 패키지 버전 체계가 이원화되어 있음: **콘솔(MNXMC TUI) deb = 2.1.3/2.1.4/2.2.0**, **NDR 엔진 Docker 이미지 = v23.5.1.2**. 서로 다른 버저닝 트랙 (§8 참조).

---

## 2. systemd 유닛 카탈로그

`is-enabled` / `is-active` 는 라이브 조회 결과. **모든 13개 유닛이 현재 active(running)** 이다. "disabled" 유닛도 상위 유닛의 `Requires=`/`Wants=` 로 인해 부팅 시 자동으로 끌려온다.

| 유닛 | Type | 주요 Exec | 순서/의존 (After / Requires·Wants) | Restart | User | enabled |
|---|---|---|---|---|---|---|
| **elasticsearch** (`/etc/systemd/system/elasticsearch.service`) | notify | ExecStart=`systemd-entrypoint` (:23) | After=network-online.target; Wants=network-online (:5-6) | (없음) | elasticsearch (:20) | **enabled** |
| **zookeeper** (`zookeeper.service`) | simple | Start `zookeeper-server-start.sh` (:14); Stop `-stop.sh` (:15) | Requires+After network.target, remote-fs.target (:5-9) | on-abnormal (:16) | root(기본) | **disabled** |
| **kafka** (`kafka.service`) | simple | Start `kafka-server-start.sh` (:14); Stop `-stop.sh` (:15) | Requires+After zookeeper (:5-6); **ExecStartPre=sleep 5** (:12) | (없음) | root(기본) | **disabled** |
| **mnxdpi** (`mnxdpi.service`) | simple | ExecStart=`/opt/mnxdpi/mnxdpi -c mnx_config.json -s` (:12); Stop `-K` (:13) | Requires+After elasticsearch(:4-5), kafka(:7-8) | on-failure, 5s (:21-22) | root (:16) | **disabled** |
| **mnxcapture** (`mnxcapture.service`) | simple | **ExecStartPre=`mnx_config_interfaces.sh`** (:15); ExecStart=`/opt/mnx/bin/capture` → `/logs/mnxcapture/capture.log` (:17) | Requires+After elasticsearch(:4-5); **Wants+After mnxdpi**(:7-8) | on-failure (:12) | root(기본) | **enabled** |
| **mnx_payload_ai** (`mnx_payload_ai.service`) | forking | ExecStart=`python3.12 file_analysis_ai.py … start` (:13) | Wants+After network-online (:4-5) | on-failure, 5s (:27-28) | root (:30) | **disabled** |
| **mnx_payload_scan** (`mnx_payload_scan.service`) | forking | ExecStart=`/opt/scanengine/scanengine_bitdefender -d` (:13) | Wants+After network-online (:4-5) | on-failure, 5s (:26-27) | root (:29) | **disabled** |
| **mnx_payload** (`mnx_payload.service`) | forking | **ExecStartPre=sleep 10**(:21); ExecStart=`/opt/payload_analysis/payload_analysis -d` (:24) | Requires+After elasticsearch, kafka, **mnx_payload_ai, mnx_payload_scan** (:4-14) | on-failure, 5s (:37-38) | root (:40) | **enabled** |
| **mnx_regression_api** (`mnx_regression_api.service`) | simple | ExecStart=`python3.12 /opt/regression_api/app.py` (:11) | After network-online.target **elasticsearch** (:4); Wants network-online (:3) | on-failure, 5s (:12-13) | root (:8) | **enabled** |
| **mnx_service_control** (`mnx_service_control.service`) | forking | ExecStart=`/opt/service_control/service_control -d` (:13) | Wants+After network-online (:4-5) | on-failure, 5s (:25-26) | root (:28) | **enabled** |
| **eng_monitor** (`eng_monitor.service`) | simple(기본) | ExecStart=`/data/tools/eng_monitor.sh` (:8) → `/logs/eng_monitor/eng_monitor.log` | Requires+After elasticsearch (:4-5) | **always** (:9) | root (:10) | **enabled** |
| **promisc-ens192** (`promisc-ens192.service`) | oneshot | ExecStart=`ip link set ens192 promisc on` (:7); RemainAfterExit=yes (:8) | After network.target (:3) | (oneshot) | root(기본) | **enabled** |
| **suricata** (`/lib/systemd/system/suricata.service`) | (simple) | ExecStartPre=`rm -f /run/suricata.pid`(:13); ExecStart=`suricata --af-packet` (:14); Stop `suricatasc -c shutdown` (:16) | Requires network-online; After network.target network-online.target (:3-4) | on-failure (:17) | suricata (via `--user`, :14) | **enabled** |

보조 유닛/드롭인:
- `elasticsearch.service.d/*.conf`: `LimitMEMLOCK=infinity` 오버라이드.
- `mariadb.service.d/*.conf`: `# empty placeholder` (내용 없음). MariaDB 는 Web/API 스택용으로 추정(unverified).
- `is-enabled` 원본: elasticsearch/mnxcapture/mnx_payload/mnx_regression_api/mnx_service_control/eng_monitor/promisc-ens192/suricata = **enabled**; kafka/zookeeper/mnxdpi/mnx_payload_ai/mnx_payload_scan = **disabled** (전부 현재 active).
- `multi-user.target.wants/` 심볼릭 링크로 enabled 8개 확인(위 목록과 일치). suricata 만 `/lib/systemd/system/` 원본을 가리킴.

---

## 3. 부팅 시퀀스 (After/Requires 로부터 도출 — 부팅 다이어그램 입력)

의존성 그래프 (`→` = "…뒤에 시작", 괄호=하드 Requires):

```
network.target / remote-fs.target / network-online.target
        │
        ├─▶ promisc-ens192  (oneshot: ip link set ens192 promisc on)
        ├─▶ suricata        (af-packet IDS)
        ├─▶ zookeeper       (network+remote-fs)
        │        │
        │        └─(Requires)─▶ kafka  [+ExecStartPre sleep 5]
        │                          │
        └─▶ elasticsearch (network-online)
                 │                 │
                 ├──(Req)──────────┼─▶ mnxdpi  (Req: ES + kafka)
                 │                 │       │
                 │                 │       └─(Wants)─▶ mnxcapture
                 │                 │             [ExecStartPre: mnx_config_interfaces.sh]
                 │                 │             (Req: ES)
                 ├─(Req)─▶ eng_monitor
                 ├─(After)─▶ mnx_regression_api
                 │
                 └─(Req)──┐
   network-online ─▶ mnx_payload_ai  ─┐
   network-online ─▶ mnx_payload_scan ─┤
   kafka ───────────────────────────────┼─(Req)─▶ mnx_payload [+ExecStartPre sleep 10]
   elasticsearch ────────────────────────┘
   network-online ─▶ mnx_service_control   (독립)
```

**해석된 부팅 순서(레이어):**
1. `network.target`, `remote-fs.target`, `network-online.target`
2. (병렬) `promisc-ens192`(oneshot), `suricata`, `zookeeper`
3. `kafka` — zookeeper 이후 + 5초 슬립 (`kafka.service:5-6,12`)
4. `elasticsearch` — network-online 이후 (`elasticsearch.service:5-6`)
5. `mnxdpi` — ES + kafka 이후 (`mnxdpi.service:4-8`)
6. `mnxcapture` — ES + mnxdpi 이후, **NIC 설정 스크립트 선실행** (`mnxcapture.service:4-8,15`)
7. (병렬) `mnx_payload_ai`, `mnx_payload_scan`, `mnx_regression_api`, `mnx_service_control`, `eng_monitor`
8. `mnx_payload` — ES + kafka + payload_ai + payload_scan 이후 + 10초 슬립 (`mnx_payload.service:4-14,21`)
9. (systemd 밖) Docker 컨테이너 `mnx_api_server`, `mnx_web_server` — `docker.service` 경유 (별도 트랙)

주의: capture 와 payload 사이에는 명시적 순서 제약이 없어 병렬 기동됨.

---

## 4. 네트워크 준비 (promisc · NIC · 인터페이스 설정)

- **NIC 역할** (`ip -br link`/`ip -br addr`):
  - `ens160` — **관리(management)**, UP, `10.10.1.116/24` 할당.
  - `ens192` — **모니터링/미러(mirror) 포트**, UP + **PROMISC** 플래그, IP 없음(L2 캡처 전용).
  - `ens224` — DOWN, IP 없음 (예비/미사용).
  - `docker0` — `20.20.0.1/24`, NO-CARRIER (Docker 브릿지).
- **`promisc-ens192.service`** (oneshot, RemainAfterExit): 부팅 시 `ip link set ens192 promisc on` 1회 실행 (`promisc-ens192.service:7`). ens192 만 하드코딩 → NIC 이름 종속.
- **`mnx_config_interfaces.sh`** (`/opt/mnx/bin/mnx_config_interfaces.sh`, mnxcapture 의 ExecStartPre): config.ini 의 `[node]/[default]` 섹션에서 `interface=` 값을 파싱(`:41,45`), 각 NIC 에 대해 `ip link set up` + `promisc on`, `ethtool -G rx/tx 4096`, 오프로드(rx/tx/sg/tso/ufo/gso/gro/lro) 전부 off (`:57-63`). NIC 미존재 시 경고만 출력하고 진행.
- **config.ini** (`/opt/mnx/etc/config.ini`): `[default]` 섹션에 `elasticsearch=http://localhost:9200`, `rotateIndex=daily`, `authMode=anonymous`, `passwordSecret=toswm#0501`(하드코딩 시크릿 — 보안 이슈), `httpRealm=Moloch`(Arkime 기반) 존재. **주의: 활성 `interface=` 라인은 발견되지 않음** (grep 무결과) → 실제 캡처 인터페이스는 `interfaceOps` 또는 커맨드라인/env(`capture.env`)로 지정되는 것으로 추정(unverified). 즉 config.ini 기반 자동 NIC 설정은 현재 no-op 가능성.

---

## 5. logrotate (로그별 규칙)

`/etc/logrotate.d/mnx` — cron 으로 30분마다 실행 (§6). 두 블록:

**블록 1 (일반 엔진 로그, `:1-23`)** — 대상 파일:
`/logs/mnxcapture/capture.log`, `/logs/syslog/syslog.log`, `/logs/payload_scanengine/…`, `/logs/payload_ai_analysis/…`, `/logs/payload_analysis/…`, `/logs/service_control/…`, `/logs/eng_monitor/…`, `/logs/regression_api/…`, `/logs/suricata/*.log`
- 규칙: `su root root`, `daily` + `size 100M`(둘 중 먼저 충족 시 회전), **`rotate 1`(1세대만 보관)**, `notifempty`, `copytruncate`, `missingok`, `dateext`, `dateformat -%Y-%m-%d-%s`. postrotate 없음, 압축 없음.

**블록 2 (Suricata/Arkime JSON, `:26-40`)** — 대상: `/logs/suricata/*.json`
- 규칙: `daily`+`size 100M`, `rotate 1`, `copytruncate`, `dateext` `-%Y-%m-%d`, **`compress` + `delaycompress`**.

리스크: `rotate 1` 로 보관 세대가 1개뿐 → 30분 주기로 100M 초과 시 이전 로그가 빠르게 소실됨. `copytruncate` 사용으로 회전 중 쓰기 유실 가능(작은 창).

---

## 6. cron 카탈로그

**root crontab** (`crontab -l`, 원본 `/var/spool/cron/crontabs/root`):

| 스케줄 | 명령 | 목적 |
|---|---|---|
| `* * * * *` | `python3.12 /opt/server_check/server_check.py --cpu_interval 5 --hdd_path /data` | 서버 리소스(CPU/HDD) 상태 점검 (매분) |
| `* * * * *` | `sleep 30; …server_check.py …` | 위와 동일 명령을 30초 오프셋 → 사실상 30초 주기 |
| `0 1 * * *` | `/application/mnx_web/mitre_attack/update_mitre_attack.sh` | MITRE ATT&CK 데이터 갱신 (매일 01:00) |
| `*/10 * * * *` | `python3 /data/tools/pcap_delete.py` | 오래된 PCAP 정리 (10분) |
| `*/5 * * * *` | `python3.12 /opt/syslog/syslog.py --config …mnx_config.json` | syslog 처리/전송 (5분) |
| `30 3 * * *` | `/data/tools/payload_delete.sh` | 페이로드 파일 정리 (매일 03:30) — **중복 등록됨** |
| `*/30 * * * *` | `/usr/sbin/logrotate /etc/logrotate.d/mnx` | MNX 로그 로테이션 (30분) |

주의: `payload_delete.sh` 가 crontab 에 **두 번** 등록되어 있음(동시 실행 가능).

**/etc/cron.d**:
- `avupdate`: `0 */4 * * * root /opt/scanengine/updater_bitdefender` — Bitdefender 백신 시그니처 4시간마다 갱신.
- `geoipupdate`, `sysstat`, `e2scrub_all` — OS 기본(비MNX).

**systemd 타이머** (`timers.target.wants/`): `logrotate.timer`(OS 기본 daily), `geoipupdate.timer`, `fstrim.timer` 등. → MNX logrotate 는 cron(30분)과 OS 타이머(daily)가 **이중** 동작 가능. 다만 둘 다 동일 상태파일(`/var/lib/logrotate/status`)을 참조하는 것은 cron 쪽이 config 파일을 직접 지정하므로 별개 처리 추정(unverified).

---

## 7. 로그 디렉터리 레이아웃 + 디스크 사용량

**`df -h` 요약:**
| 마운트 | 크기 | 사용 | 사용률 | 비고 |
|---|---|---|---|---|
| `/` (sda3) | 187G | 37G | 21% | OS + overlay |
| `/data` (sdd2) | 40G | 31G | **77%** | raw pcap 저장 |
| `/application` (sdd1) | 20G | 19G | **91%** | mnx_web 등 — 경고 |
| `/logs` (sdb4) | 30G | 9.7G | 35% | 엔진 로그 |
| `/pipeline` (sdc1) | 49G | 28G | 59% | 파이프라인 데이터 |
| `/docker` (sdb3) | 15G | 414M | 3% | Docker 스토리지 |
| `/dir_cache` (sdb2) | 9.8G | 160K | 1% | |
| `/boot` (sda2) | 9.8G | 133M | 2% | |
| `/dev/shm` | 25G | — | 1% | 대용량 tmpfs |

**`/logs` 하위** (`du -sh`): mnxcapture 8.5G(최대), mnxdpi 459M, kafka 385M, suricata 260M, eng_monitor 123M, mnx_web 52M, payload_* 각 5-7M, service_control 2.9M, syslog 664K.
**`/data` 하위**: `raw` 31G(pcap), 그리고 설치 아카이브 `mnxmc-2.2.0.deb`(127M)/`2.1.4.deb`/`2.1.3.deb`(각 109M) 보관, `tools` 108K.

**추가 로그 위치:**
- `/var/log/mnx/` — `mnx_auth.log`, `mnx_console.log` (MNXMC TUI 콘솔/인증 로그).
- `/var/log/mnx_install/` — 설치 단계별 로그(analysis, docker, elasticsearch, suricata, yara, mariadb, services 등 28개 파일).
- `/logs-new/` — `/logs` 와 동일한 하위 구조(mnxcapture, mnxdpi, kafka, suricata, payload_*, syslog…)를 가진 **병렬/차기 로그 트리**. 현재 유닛/logrotate 는 `/logs` 를 참조하므로 `/logs-new` 는 신규 레이아웃으로의 마이그레이션 대상으로 추정(unverified).

---

## 8. 설치 / 패키징 (deb 레이아웃, postinst/preinst, 버전)

**빌드 트리** `/home/sands/mnxmc_deb_build/`:
- `DEBIAN/control` — `Package: mnxmc`, **`Version: 1.0`**(빌드 소스), `Architecture: amd64`, `Depends: bash`, `Maintainer: SANDS LAB <admin@sandslab.com>`, 설명: "MNX Management Console … Getty@tty1, SSH 접근 제어, RAID CLI, SNMP, NTP, Python3.12 오프라인 설치".
- `DEBIAN/postinst` (존재, `preinst` 없음) — 주요 동작:
  - [A] `/mnxmc/packages/install_packages.sh` 실행(apt/pip/storcli/perccli/sudoers 오프라인 설치).
  - [B1] `systemd-networkd-wait-online.service` **disable + mask** (`:31-32`) — 부팅 지연 방지.
  - [B2] timezone `Asia/Seoul` (`:37`). [B3] editor→vim.
  - [C] `/etc/bash.bashrc` 에 SSH 세션 시 `exec python3.12 /mnxmc/main.py` 블록 삽입 (`:63-82`) — SSH 로그인 시 MNXMC TUI 강제 실행.
  - [D] root/sands `.bashrc` 배포. [E] NTP enable. [F] SNMP enable+백업.
  - [G] `/data/tools/*.sh` → `/usr/local/bin` 심볼릭 링크(`check_index`, `check_kafka`, `MNX_all_start_service`, `MNX_all_stop_service`, `MNX_check_stop_order`, `MNX_status_cheack`[오타] 등, `:156-162`).
  - [H] `systemctl daemon-reload` + `getty@tty1` 재시작.
  - 이 deb 는 `etc/systemd/system/` 아래 `getty@tty1.service.d` 만 포함 → **엔진 유닛(mnxcapture/mnxdpi/payload…)은 이 deb 소산이 아님** (별도 엔진 설치 경로).
- `mnxmc/` — TUI 소스(main.py, app/, modules/, packages/) 및 오프라인 패키지(apt/pip/storcli/perccli/config).

**배포 아카이브** `/data/mnxmc-{2.1.3,2.1.4,2.2.0}.deb` (`dpkg-deb -f`):
- 모두 `Package: mnxmc`, Maintainer `SANDS LAB Inc. <admin@sandslab.kr>`, Description "MNX Management Console Archive — Extracts MNXMC source and offline packages to /mnxmc. After install run install_packages.sh".
- 버전 2.1.3 → 2.1.4 (Installed-Size 149116, 동일) → **2.2.0 (Installed-Size 181508, 증가)**.

**버전 체계 및 deb-vs-docker 정합성:**
- **MNXMC 콘솔(TUI)** = deb 버전 트랙 `2.1.x → 2.2.0` (관리 콘솔 소스+오프라인 패키지). readme 헤더는 "버전 2.1.4" (`readme:3`), CLAUDE.md 는 "v2.2.0".
- **MNX NDR 엔진(Web/API)** = Docker 이미지 `mnx-api-v23:v23.5.1.2`, `mnx-web-v23:v23.5.1.2` (별도 `v23.5.x` 트랙).
- 두 값이 다른 것은 **오류가 아니라 별개 컴포넌트의 독립 버저닝**으로 판단: 콘솔 관리도구(2.2.0) vs NDR 엔진 릴리스(v23.5.1.2). 캡처/DPI/페이로드 네이티브 엔진의 정확한 버전은 별도 확인 필요 — 추정(unverified).

---

## 9. 업그레이드 플로우 (readme + 스크립트)

출처 `/mnxmc/readme_install_mnxmc.txt` (538줄):
1. **전송**: `scp mnxmc-2.1.4.deb sands@<IP>:~` (`:88`).
2. **설치**: `sudo dpkg -i mnxmc-2.1.4.deb` → `/mnxmc` 에 소스/오프라인 패키지 압축 해제 (`:94`).
3. **환경 구성**: `sudo bash /mnxmc/packages/install_packages.sh` (`:105`) — 13단계:
   [0] timezone → [1] apt 오프라인(.deb, 실패 시 3회 재시도) → [2] pip(.whl, py3.12) → [3] StorCLI → [4] PercCLI → … → [13] 로그인 경고 배너(/etc/issue) → [검증] timezone/python/textual/rich/storcli/perccli/raid.cfg 자동 점검 (`:117-320`).
4. **보안 조치** `/mnxmc/infra_audit/` — `infra_audit.sh`(KISA U-01~U-67 점검) + `infra_remediate.sh`(조치, 백업 디렉터리 생성) (`:322-437`).
5. **U-64 특이사항**: `apt-get upgrade` 시 Suricata 설정 덮어쓰기 충돌 방지 위해 `apt-mark hold suricata` → `apt-get upgrade --force-confold` → `apt-mark unhold suricata` 순서 (`:415-426`). 추가 보호는 `HOLD_PKGS` 변수.
- 업그레이드는 동일 `dpkg -i` 재설치 + `install_packages.sh` 재실행 방식(멱등: 동일버전 이상 skip, `readme:136`). 롤백/버전 다운그레이드 절차는 문서에 명시 없음 — 추정(unverified).
- 설정 파일 위치(`readme:463-468`): `config.ini`(캡처 INI), `mnx_config.json`(ES/DPI/PCAP JSON), `mnxmc_console.json`(콘솔 세션), `/opt/service_control/settings.json`.

---

## 10. 실패 영향 (부팅 순서 취약성)

- **elasticsearch 단일 실패점**: mnxdpi, mnxcapture, mnx_payload, eng_monitor 가 `Requires=elasticsearch` → ES 기동 실패 시 이 4개(및 mnxcapture 가 Wants 하는 체인) 전부 기동 불가. ES `TimeoutStartSec=900`(15분)까지 하위 유닛 대기.
- **kafka/zookeeper 체인**: mnxdpi·mnx_payload 가 `Requires=kafka`, kafka 가 `Requires=zookeeper`. zookeeper 실패 → kafka 실패 → mnxdpi/mnx_payload 실패로 캐스케이드. kafka 는 `Restart` 정책 없음(수동 개입 필요), `ExecStartPre=sleep 5` 만으로 zookeeper 준비를 보장 → 경합 조건 가능.
- **mnx_payload 다중 하드 의존**: ES+kafka+payload_ai+payload_scan 4개 `Requires` → 이 중 하나라도 실패 시 payload 미기동. `sleep 10` 하드코딩으로 하위 준비 추정.
- **NIC 이름 종속**: `promisc-ens192.service` 와 mirror 로직이 `ens192` 하드코딩(`promisc-ens192.service:7`). NIC 재명명/하드웨어 변경 시 미러 캡처 침묵 실패.
- **config.ini interface 미설정**: `mnx_config_interfaces.sh` 가 파싱할 `interface=` 라인 부재 → 오프로드/링버퍼 튜닝 미적용 가능(캡처 성능 저하). 확인 필요.
- **disabled 유닛의 암묵 기동**: kafka/zookeeper/mnxdpi/payload_ai/payload_scan 은 `is-enabled=disabled` 이나 상위 Requires 로만 기동 → 상위 유닛을 stop/disable 하면 함께 내려가 운영자가 놓치기 쉬움.
- **로그 보존 리스크**: logrotate `rotate 1` + 30분 cron → 트래픽 폭주 시 capture.log(8.5G 디렉터리) 회전 세대 1개만 남아 근거 로그 유실 가능.
- **디스크 압박**: `/application` 91%, `/data` 77% → pcap_delete/payload_delete cron 이 멈추면 단시간 내 포화 위험.

---

## 11. 상호 참조

- 캡처/DPI/페이로드 엔진 상세 → 캡처·DPI·페이로드 서브시스템 문서(별도).
- ES/Kafka/Zookeeper 데이터 플레인 → 데이터 저장/스트리밍 문서.
- Web/API Docker(v23.5.1.2) → 애플리케이션/컨테이너 문서.
- MNXMC TUI(main.py, install_packages.sh, infra_audit) → 관리 콘솔 문서.
- 보안(하드코딩 secret, KISA 조치) → 보안 서브시스템 문서.

### 근거 파일 목록
- systemd 유닛: `/etc/systemd/system/{elasticsearch,kafka,zookeeper,mnxcapture,mnxdpi,mnx_payload,mnx_payload_ai,mnx_payload_scan,mnx_regression_api,mnx_service_control,eng_monitor,promisc-ens192}.service`, `/lib/systemd/system/suricata.service`
- 드롭인: `/etc/systemd/system/elasticsearch.service.d/`, `mariadb.service.d/`
- 네트워크: `/opt/mnx/bin/mnx_config_interfaces.sh`, `/opt/mnx/etc/config.ini`, `ip link/addr`
- logrotate: `/etc/logrotate.d/mnx`
- cron: `crontab -l` (`/var/spool/cron/crontabs/root`), `/etc/cron.d/avupdate`
- 패키징: `/home/sands/mnxmc_deb_build/DEBIAN/{control,postinst}`, `/data/mnxmc-{2.1.3,2.1.4,2.2.0}.deb`, `/mnxmc/readme_install_mnxmc.txt`, `/var/log/mnx_install/`
- 런타임: `docker ps` / `docker images`, `df -h`, `du -sh /data/* /logs/*`
