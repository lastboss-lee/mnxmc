# MNXMC 메뉴별 정보/데이터소스/연관파일 — 웹 구현 인계 문서

> **목적:** MNXMC(관리 콘솔, Python/Textual TUI, v2.3.2)의 각 메뉴가 **무엇을 표시하는지**,
> 그 정보를 **어떻게 수집하는지**(명령/파일/모듈), 그리고 설정 변경 시 **어떤 파일이 수정되는지**를
> 정리한다. **대상 독자: 웹(GUI) 버전을 구현하는 개발자.** 웹에서 동일 화면을 만들 때
> 어떤 데이터를 어디서 가져오고 어떤 파일을 써야 하는지에 대한 단일 레퍼런스.
>
> 근거: `/mnxmc/app/screens/*.py`, `/mnxmc/modules/*.py`, `/mnxmc/network_management/*.py` 코드 분석
> (2026-07-29 기준). 실제 데이터/설정 파일은 **엔진(어플라이언스) 런타임 경로**이며 콘솔 리포에는 없다.

---

## 0. 공통 아키텍처 (모든 메뉴 공통 전제)

| 항목 | 내용 |
|---|---|
| **실행 권한** | getty@tty1 콘솔 = **root** / SSH 접속 = **비root(sands)** (`/etc/bash.bashrc`가 접속 사용자로 `exec main.py`). |
| **권한 분기** | 파일 쓰기/특권 명령은 root면 직접 실행, 비root면 **`sudo -n <cmd>`** (NOPASSWD, `/etc/sudoers.d/mnxmc`). 웹 백엔드도 동일 패턴 필요. |
| **root 전용 파일 읽기** | `/etc/suricata/suricata.yaml` 등 root-only 파일은 비root에서 `Path.exists()`가 EACCES를 raise → 반드시 EAFP + `sudo -n cat` 폴백. (참고 커밋 `fd96297`) |
| **데이터 수집 방식** | 대부분 `/proc`·`/sys` 직접 read + `subprocess`(shell=False 권장, 일부 `shell=True`) + 시스템 CLI. **DB/REST 없음** — 대부분 로컬 명령·파일 기반. |
| **갱신 모델** | 화면별 `set_interval` 폴링 + 무거운 수집은 `threading.Thread` 오프로드 후 `call_from_thread`로 UI 반영. 웹은 동일 주기의 폴링/SSE/WebSocket으로 대체. |
| **rate 계산** | CPU/네트워크/디스크 사용률은 **직전 측정 대비 delta/시간**. 첫 샘플은 0 → 최소 2회 샘플 필요. |

### 메인 메뉴(Dashboard) 개요

| 메뉴 | 화면 클래스 / 파일 | 성격 | 쓰기 |
|---|---|---|---|
| System Overview | `SystemScreen` `system.py` | 하드웨어/OS/스토리지/RAID 조회 | 읽기전용 |
| Performance Monitor | `PerformanceScreen` `performance.py` | 실시간 CPU/메모리/디스크IO/네트워크/프로세스 | 읽기전용 |
| Log Monitoring | `LogsScreen` `logs.py` | 서비스 로그 tail + Kafka/ES + 점검요약 | 읽기전용 |
| Service Status | `ServiceScreen` `service.py` | systemd 서비스 상태·제어 | **systemd 상태 변경** |
| Network Management | `NetworkScreen` `network.py` | NIC 상태 + IP/미러 설정 | **netplan/promisc 파일** |
| MNX Config | `MnxConfigScreen` `mnx_config.py` (인증 게이트) | 엔진/콘솔 설정 편집 | **다수 설정 파일** |
| Command Shell | `ShellScreen` `shell.py` | 실제 bash 셸 진입 | (셸 활동) |

> MNX Config 진입 전 `MnxConfigAuthScreen`(confirm → 시스템 비밀번호) 2단계 인증. Service 제어도 동일.

---

## 1. System Overview (`system.py` + `modules/system_info.py`)

**서브메뉴:** All Information · System Info · CPU Info · Memory Info · Storage Info · Disk Info · Network Devices (우측 패널 1초 자동 갱신, F7=강제 재수집)

### 출력 정보
- **System**: Product Name, OS Version, Kernel, Hostname, Main IP, Current User, Uptime, Load(1/5/15)
- **CPU**: Model, Physical Cores, Logical CPUs, Arch, Base Freq, 실시간 사용률 바
- **Memory**: Total/Used/Available, 사용률 바, 설치 DIMM 수/슬롯 수
- **Storage**: 고정 마운트(`/`,`/docker`,`/logs`,`/pipeline`,`/application`,`/data`,`/dir_cache`)별 Type/Size/Used/Avail/Use%/Status(OK≤80%, WARNING>80%, FAULT=미마운트)
- **Disk Info**: RAID Type/CLI + VD/PD(또는 graid DG/VD/PD) 리스트
- **Network Devices**: 컨트롤러 수, IF별 PCI/Vendor/Speed(모델명 추정) + 활성 IF(name/status/IP/MAC)

### 정보 수집 방법 (`system_info.py`, 결과 `/tmp/mnx_system_info.json` 1시간 캐시)
| 필드 | 수집 |
|---|---|
| Hostname / Uptime / Kernel / Arch | `hostname` · `uptime -p` · `uname -r` · `uname -m` |
| OS Version | `/etc/os-release`(PRETTY_NAME), fallback `/etc/redhat-release` |
| Product Name | `sudo dmidecode -s system-product-name` |
| Main IP / User | `hostname -I \| awk '{print $1}'` · `whoami` |
| CPU model/cores/freq | `/proc/cpuinfo` · 논리 CPU `nproc` |
| Memory | `/proc/meminfo` · DIMM `sudo dmidecode -t 17` |
| Load | `/proc/loadavg` |
| NIC 컨트롤러 | `lspci \| grep -i 'ethernet\|network'` (Vendor/Speed는 모델명 하드코딩 매핑) |
| Storage | `df -hT` / `df -h /` |
| RAID(Disk Info) | `/mnxmc/raid.cfg`(RAID_TYPE/RAID_CLI) 우선 → 없으면 CLI 자동탐지. `sudo storcli64/perccli64 /c0 /vall show`·`/eall /sall show`, 또는 `sudo graidctl list drive_group\|virtual_drive\|physical_drive`(ANSI strip) |

### 연관 파일(쓰기)
**읽기전용.** 유일한 쓰기 = 캐시 `/tmp/mnx_system_info.json`. `raid.cfg`는 읽기만(생성은 `install_packages.sh`).

### 웹 재구현 노트
- `_run_command`가 **`shell=True`** — 웹 이식 시 인자 배열(shell=False)로 재작성 권장(인젝션 표면).
- NIC "Speed"는 실제 링크 속도가 아닌 모델명 추정값 → 웹에서는 `ethtool` 실제값 사용 권장.
- RAID CLI(storcli64/perccli64/graidctl)는 벤더 종속 → 웹 백엔드에서 동일 CLI 호출 필요.

---

## 2. Performance Monitor (`performance.py` + `modules/performance_monitor.py`, `modules/disk_monitor.py`)

**서브메뉴:** All · CPU Usage · Memory Usage · Disk I/O Stats · Network I/O · Top Processes (**1초 자동 갱신**)

### 출력 정보
- **CPU**: 전체 사용률% + Load(1/5/15) + 코어별 사용률%
- **Memory**: Total/Used/Available(GB), Usage%
- **Disk I/O**: 마운트별 Device/Read·Write(MB/s)/IOPS/Await(ms)/Util%/State(NORMAL/BUSY≥50/SATURATED≥80/UNMOUNTED)
- **Network I/O**: NIC별 Status, RX/TX Rate(Gbps/Mbps/Kbps 자동), RX/TX Total, MAC, Speed, RX/TX Errors
- **Top Processes**: USER/PID/%CPU/%MEM/VSZ/RSS/COMMAND

### 정보 수집 방법 (source→field, **sudo 미사용**)
| 지표 | 소스 |
|---|---|
| CPU 전체/코어 | `/proc/stat` delta (idle=idle+iowait), 코어수 `/proc/cpuinfo` |
| Load | `/proc/loadavg` |
| Memory | `/proc/meminfo` (used=total−available) |
| Network rate | `/proc/net/dev` byte delta / time delta |
| NIC 상세 | `ip link show <if>`(status/MAC/MTU), `ethtool <if>`(Speed/Duplex), `ethtool -i <if>`(driver) — DOWN이면 생략 |
| Disk 매핑 | `findmnt -n -o TARGET,SOURCE,FSTYPE -l`, LVM=`dmsetup`/`/sys/block/dm-*`, ZFS=`zpool iostat -Hp` |
| Disk 통계 | `/proc/diskstats`(sectors×512, io_time_ms) → IOPS/await/util delta (첫 호출 0.3s sleep) |
| Processes | `ps aux --sort=-%cpu` |

### 연관 파일(쓰기)
**완전 읽기전용.** `/proc`·`/sys` read + 조회성 subprocess만. 상태는 메모리 내(직전 stats, `threading.Lock`).

### 웹 재구현 노트
- 모든 rate는 delta 기반 → 웹 백엔드가 직전 샘플을 세션/메모리에 보관해야 함.
- 대상 마운트 7종 고정(위 Storage와 동일). Kafka/ES 지표는 여기 없음(순수 시스템 지표).

---

## 3. Log Monitoring (`logs.py` + `modules/log_viewer.py`, `kafka_monitor`, `es_monitor`)

**서브메뉴:** Inspection Summary / (System Logs) File Analysis AI · MNX Capture · MNX DPI · MNX Service Control · Payload Analysis · Suricata · Syslog / (Monitoring) Kafka Monitor · Elasticsearch Monitor

### 출력 정보
- 일반 로그: `File: <경로>` + **tail 마지막 50줄**. 색상: ERROR/FAIL→red, WARN→yellow, INFO→green
- Kafka: consumer group 테이블(Partition/Offset/End/**Lag**), running 여부
- Elasticsearch: cluster health(status/nodes/shards/unassigned), 인덱스 수, 세션 인덱스
- Inspection Summary: 11개 점검 항목 STATUS/CATEGORY/CHECK/DETAIL + ✓/⚠/✗ 종합

### 정보 수집 방법 (`LOG_PATHS` 매핑, 디렉토리면 mtime 최신 파일 → `tail -n 50`)
| 로그 소스 | 경로 |
|---|---|
| File Analysis AI | `/logs/file_analysis_ai/` |
| MNX Capture | `/logs/mnxcapture/` |
| MNX DPI | `/logs/mnxdpi/` |
| MNX Service Control | `/logs/service_control/` |
| Payload Analysis | `/logs/payload_analysis/` |
| Suricata | `/logs/suricata/` |
| Syslog | `/var/log/syslog` (fallback `/var/log/messages`) |

- **Inspection 개별 점검:** capture drop=`grep -i drop`, DPI queue=`grep -i stat`(q=n/n), dir_cache=`find /dir_cache -name '*.dir' -mtime +1`, CPU/Mem=`/proc/stat`·`/proc/meminfo`, Storage=`df --output=target,pcent`, Network=`/proc/net/dev`, SMART=`lsblk` → `sudo smartctl -H /dev/<disk>`, system=`tail -n 200 /var/log/syslog`
- Kafka/ES는 `app.kafka_monitor`/`app.es_monitor` 모듈(백그라운드 스레드)
- **follow(`-f`) 없음.** 폴링: 일반 로그 3s, Kafka 5s, ES 10s, Inspection 60s

### 연관 파일(쓰기)
**완전 읽기전용.** 로그 rotate/delete 없음.

### 웹 재구현 노트
- journald 미사용(파일 tail 기반) → 웹도 파일 tail 또는 `journalctl` 중 택1(현재는 파일).
- 웹에서는 로그 실시간 스트리밍(SSE/WebSocket + `tail -f`)으로 개선 여지.

---

## 4. Service Status (`service.py`) — **상태 변경 있음**

**서브메뉴:** Back · Overview · 서비스 15종(아래). Overview 5초 자동 갱신.

**관리 대상 서비스 15종(`SERVICES`):** `mnx_service_control`, `eng_monitor`, `mnx_regression_api`, `mnx-thirdparty`, `mnx_payload`, `mnx_payload_ai`, `mnx_payload_scan`, `mnxcapture`, `mnxdpi`, `suricata`, `elasticsearch`(래퍼), `elasticsearch-node-1`, `elasticsearch-node-2`, `kafka`, `zookeeper`

### 출력 정보
- **Overview**: 서비스별 상태 아이콘(●active/○inactive/◐기타) + status + Uptime, Running/Stopped/Other 카운트
- **서비스 상세**: `systemctl status` 출력(색상 하이라이트)

### 정보 수집 방법 (shell=False)
| 데이터 | 명령 |
|---|---|
| 상태 | `systemctl is-active <svc>` |
| 기동시각 | `systemctl show <svc> --property=ActiveEnterTimestamp` → 경과시간 계산 |
| 상세 | `systemctl status <svc> --no-pager --lines=30` |

### 연관 파일/상태 변경 (systemd)
- 제어: Restart(R)/Start(S)/Stop(X)/All Start(A)/All Stop(Z) → `_systemctl_cmd(action, svc)` = root 직접 또는 **`sudo -n systemctl <action> <svc>`**
- **인증 필수**: 제어 실행 전 confirm + 시스템 비밀번호(`AuthenticationManager`, `/etc/shadow` 직접 비교 — root 전제. 비root fallback `su`는 금지)
- 설정 파일 쓰기는 없음 — systemd 유닛 상태만 변경. All Start/Stop은 의존성 순서 배열 사용(래퍼 elasticsearch는 일괄제어 제외)

### 웹 재구현 노트
- 웹 백엔드도 `systemctl is-active/show/status` + 제어는 인증 후 `sudo -n systemctl`. 비밀번호 검증은 PAM/shadow 방식 유지 필요(root 전제).

---

## 5. Network Management (`network.py` + `network_management/`) — **파일 쓰기 있음**

**메뉴:** 사이드바 = 발견된 NIC 목록(가상 IF 제외: lo/docker/veth/br-/virbr/vnet). 설정 모달 `NetworkConfigModal`.
**키:** Enter=Configure IP, U=Link Up/Down, F8=Rescan

### 출력 정보 (NIC당)
Interface, Status(UP/DOWN/NO-CARRIER), MAC, MTU, IP, Netmask, Gateway, DNS, DHCP, Speed, Duplex, Driver, Promiscuous(Mirror Port), RX/TX Bytes·Packets. 미러(promisc) IF는 IP 대신 `— (mirror port)`.
설정 모달: Protocol(IPv4/IPv6), Assign(Mirror/DHCP/Static/Disable), IP/Netmask(`/24` 지원)/Gateway/DNS.

### 정보 수집 방법
| 필드 | 명령 |
|---|---|
| status/promisc/mac/mtu/ip/netmask | `ip -j addr show <if>` (JSON) |
| speed/duplex/driver | `ethtool <if>` · `ethtool -i <if>` |
| rx/tx | `ip -j -s link show <if>` |
| gateway | `ip route show dev <if>` |
| IF 발견 | `ip -j link show` |
| DHCP/DNS/gateway | `netplan get ethernets.<if>` + PyYAML (2초 주기 백그라운드 갱신) |

### 연관 파일(쓰기) — **핵심**
쓰기 대상 결정: `/etc/netplan/*.yaml` 파싱 → 해당 IF가 이미 정의된 파일 수정(예 `50-cloud-init.yaml`), 없으면 **`/etc/netplan/70-netplan-set.yaml`** 추가.
| 동작 | 쓰기/명령 |
|---|---|
| YAML 저장 | `sudo -n tee <target.yaml>` → `sudo -n chmod 600 <target.yaml>` |
| 적용 | `netplan apply` (no-carrier 실패는 성공 처리) |
| Static | dhcp4/6=false, addresses `[ip/prefix]`, routes `[{to:default,via:gw}]`, nameservers |
| DHCP | dhcp4/6 on, addresses/routes/nameservers 제거 |
| Disable/Mirror 전처리 | IP 전부 제거 + `ip addr flush dev <if>` |
| **Mirror(promisc)** | `ip link set <if> promisc on` + 영속화 `sudo -n tee /etc/systemd/system/promisc-<if>.service`(oneshot) → `systemctl enable --now`. 해제 시 `systemctl disable --now` + `sudo -n rm -f` |
| Link toggle(U) | `sudo ip link set <if> up\|down` |

### 웹 재구현 노트
- netplan 렌더러(systemd-networkd/NM) 무관 — `netplan apply`에 위임. `nmcli` 미사용.
- PyYAML 없으면 `netplan set ethernets.<if>.KEY=VAL` fallback. 모든 변경 syslog 기록.

---

## 6. MNX Config (`mnx_config.py` + `modules/firewall_manager.py`) — **설정 파일 편집 핵심**

**상수 경로**

| 상수 | 값 |
|---|---|
| `JSON_PATH` | `/opt/mnx/etc/mnx_config.json` |
| `INI_PATH` | `/opt/mnx/etc/config.ini` |
| `MNXMC_PATH` | `/opt/mnx/etc/mnxmc_console.json` |
| `SVC_CTRL_PATH` | `/opt/service_control/settings.json` |
| `SURICATA_YAML` | `/etc/suricata/suricata.yaml` |

### 서브섹션 → 편집 필드 / 읽기 소스 / **쓰기 대상**

| 섹션 | 편집 필드(key) | 읽기 소스 | 쓰기 대상 & 방식 |
|---|---|---|---|
| **Elasticsearch** | address, tls, auth_id, auth_pw | `mnx_config.json`→`global.elasticsearch` | `mnx_config.json` `sudo -n tee`. address 콤마→list, tls→bool, **pw→`ENC:`base64** |
| **Base Paths** | log, pid, unixsocket, pcap, data, dpi_workspace, payload_binary, payload_mail_content, payload_ai_content | `mnx_config.json`→`global.base_path` | 동상(`global.base_path` 치환) |
| **DPI Workers** | worker_count, subworkers_count, worker_count_extra, worker_idle_timeout, queue_size, port | `mnx_config.json`→`mnxdpi` | 동상(정수키 int) |
| **PCAP** | exclusive_read, read_tail_wait_ms, path, files, idle_ms, mode, page_size_k, file_size_g, pre_pages_g | `mnx_config.json`→`mnxdpi.pcap` | 동상 |
| **Interfaces/Capture** | interface, interfaceOps (칩 UI: NIC↔Net태그) | `config.ini [capture]` 2줄 + `suricata.yaml`(현재값 표시) | **① `config.ini`** 2줄 regex 치환 `sudo -n tee`(interfaceOps에 `tags=` 자동). **② `suricata.yaml`** `_sync_suricata_yaml`: af-packet(interface별 threads/cluster-id 99-i/cluster-type/defrag, `- interface: default` 보존)·pcap 텍스트 치환 후 `sudo -n tee`. 백업 `/opt/mnx/etc/suricata.yaml.bak` |
| **Session Policy** | timeout, max_sessions | `mnxmc_console.json`→`session` | **① `mnxmc_console.json`** `sudo -n tee`. **② 부수효과** `/etc/ssh/sshd_config.d/mnxmc.conf` 생성(ClientAliveInterval/CountMax/MaxSessions) → `sudo -n systemctl reload ssh`(또는 `sshd`) |
| **Service Control** | thread_count_job, mode, log_path, log_level, module_heartbeat_interval_second, mnxweb_host(→`mnxweb_info.host`), pcap_raw_proc_flag, pcap_raw_dpi_mode/file_count_key/pre_path/post_path(→`pcap_raw_path.*`), pcap_raw_cycle | `settings.json` | `settings.json` `sudo -n tee` |
| **Disk Perf Test** | target(/application·/data·/pipeline), mode(quick/standard/stress) | — | 설정파일 없음. `sudo -n fio` 실행, `sudo -n install -d`, 결과 `/tmp/mnxmc_perf/*.json`, 정리 `sudo -n rm -rf` |
| **UFW (Status/Policy/Rules/ACL/Mgmt/Profile)** | 상태·정책(in/out)·포트룰·ACL·enable/disable/reset/logging | `ufw status verbose` · `ufw status numbered` | `ufw <...>` 실행(root 직접 or `sudo -n ufw`). pending 큐 → 일괄 실행. ufw가 `/etc/ufw/*` 관리, syslog 기록 |
| **Power Control** | Reboot / Shutdown (확인 입력) | — | `sudo -n /sbin/reboot` · `sudo -n /sbin/shutdown -h now` |

### 쓰기 공통 로직
- `_atomic_write_text`: root-소유 파일(`_SUDO_TEE_PATHS`)이면 `sudo -n tee`, 그 외 tempfile+`os.replace`.
- 최초 진입 `_ensure_config_files`: `/opt/mnx/etc` 생성 + JSON/INI/MNXMC 기본값 tee 생성.
- `auth_pw`는 저장 시 `ENC:`+base64(`_encode_pw`), 로드 시 `_decode_pw`.

### 웹 재구현 노트
- 웹은 위 "쓰기 대상" 파일을 그대로 갱신해야 엔진에 반영됨. **부수효과**(sshd reload, netplan apply, suricata sync)를 반드시 재현.
- Capture 저장은 `config.ini`와 `suricata.yaml`을 **함께** 갱신(둘 다 인터페이스 기준). 현재값 표시는 두 파일 모두 읽어 보여줌.

---

## 7. Command Shell (`shell.py`)

**서브메뉴:** Shell Info · Command History · Launch Shell
- **Shell Info**: 사용자(uid/gid/home/shell via `pwd`), 시스템(`os.uname()`), 환경변수 일부
- **Command History**: `~/.bash_history` 최근 20개
- **Launch Shell**: **실제 bash 진입**(제한/allowlist 없음). `app.suspend()` 후 대화형 셸
  - 실행(shell=False): root이고 대상≠root이면 `sudo -i -u <user>`(실패 시 `/bin/bash --login`), 아니면 `/bin/bash --login`. 종료 후 `reset`. 작업 디렉토리=대상 `$HOME`
- **쓰기**: 화면 자체는 읽기전용(단 spawn된 셸의 활동은 별개)

### 웹 재구현 노트
- 웹에서 "실제 셸"은 보안상 재검토 필요(ttyd/xterm.js + PTY, 감사로그·권한 제한 권장).

---

## 8. Dashboard & 상단 헤더 (`dashboard.py`, `app/ui/status.py`, `app/ui/screen.py:AppHeader`)

### 출력 정보
- **System Status 패널**: Logged in as, Hostname, Uptime, Memory Usage(바+%), Disk Usage, Load — `app.system_info.get_basic_info()`
- **헤더(모든 화면 상단)**: Hostname · User · Time · **SVC ok/total** · **ALARM n** · **HEALTH**(색상)

### 정보 수집 (`collect_service_status()`, 5초 캐시)
- 각 유닛 `systemctl is-active <unit>` (shell=False) → `svc_ok`=active 수
- **집계 대상 서비스 12종**(헤더/대시보드용): `mnx_service_control`, `eng_monitor`, `mnx_payload`, `mnx_payload_ai`, `mnx_payload_scan`, `mnxcapture`, `mnxdpi`, `suricata`, `elasticsearch-node-1`, `elasticsearch-node-2`, `kafka`, `zookeeper`
- **health**: down 0→ok; down 중 CRITICAL(`mnxcapture`/`mnxdpi`/`elasticsearch-node-1`/`kafka`) 포함→crit; 그 외→warn
- 갱신: 대시보드 패널 1초, 헤더 시계 1초·서비스/헬스 8초
- **쓰기**: 읽기전용

> ⚠ **불일치 주의(웹 이식 시):** 헤더 집계는 **12종**(`status.py`), Service Status 화면은 **15종**(`service.py` — regression_api/thirdparty/elasticsearch 래퍼 추가분 포함). 웹에서는 하나의 canonical 목록으로 통일 권장.

---

## 부록 A. 데이터/설정 파일 경로 인덱스

**읽기(상태):** `/proc/{stat,meminfo,loadavg,cpuinfo,net/dev,diskstats}`, `/sys/block/*`, `/etc/os-release`, `/etc/netplan/*.yaml`
**로그:** `/logs/{file_analysis_ai,mnxcapture,mnxdpi,service_control,payload_analysis,suricata}/`, `/var/log/{syslog,messages}`, `/dir_cache/*.dir`
**설정(쓰기):** `/opt/mnx/etc/{mnx_config.json,config.ini,mnxmc_console.json}`, `/opt/service_control/settings.json`, `/etc/suricata/suricata.yaml`(+`.bak`), `/etc/ssh/sshd_config.d/mnxmc.conf`, `/etc/netplan/{70-netplan-set.yaml, 50-cloud-init.yaml}`, `/etc/systemd/system/promisc-*.service`
**캐시/임시:** `/tmp/mnx_system_info.json`, `/tmp/mnxmc_perf/*.json`
**콘솔 설정:** `/mnxmc/raid.cfg`

## 부록 B. sudoers NOPASSWD 허용 (`/etc/sudoers.d/mnxmc`, 비root SSH 세션용)
- `/usr/bin/tee` → 위 설정 파일 경로 각각(임의 경로 쓰기 방지)
- `/usr/bin/cat /etc/suricata/suricata.yaml` (비root 읽기 폴백)
- `/usr/bin/systemctl`, `/usr/sbin/{ip,netplan,ethtool,ufw}`, `/usr/sbin/dmidecode`, `/usr/sbin/smartctl`, RAID CLI(storcli64/perccli64/graidctl)
- `/usr/bin/fio`, `/usr/bin/install -d ...`, `/usr/bin/rm -rf ...`
- `/sbin/reboot`, `/sbin/shutdown -h now`

## 부록 C. 웹 구현 체크리스트
1. 상태 조회 API는 명령/파일 소스를 그대로 감싸되, rate 지표는 서버가 직전 샘플 보관(2회 샘플).
2. 설정 저장 API는 "쓰기 대상" 파일 + **부수효과**(sshd reload / netplan apply / suricata sync)까지 원자적으로 처리.
3. 권한: root 직접 vs `sudo -n` 분기, sudoers 경로 제한 유지. root 전용 파일 읽기는 EAFP+`sudo cat`.
4. Capture 편집은 `config.ini`↔`suricata.yaml` 동기화 규칙 준수(af-packet cluster-id 99-i, default 블록 보존).
5. 인증 게이트(MNX Config / Service 제어)는 시스템 비밀번호 검증 유지.
6. 서비스 목록을 12/15종 불일치 없이 단일화.
