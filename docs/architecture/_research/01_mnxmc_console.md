# 01. MNX Management Console (`/mnxmc`) — 아키텍처 인수인계 문서

> 조사 대상: `/mnxmc` 전체 트리
> 조사 일자: 2026-07-10
> 모든 주장은 `file:line` 또는 실행 명령 증거에 근거. 미검증 항목은 "추정(unverified)"로 표기.

---

## 1. Overview — 역할, 중요도, 실행 여부

**역할:** MNX NDR 어플라이언스의 **로컬 시스템 관리 콘솔(TUI)**. XenServer 스타일의 텍스트 기반 관리 인터페이스로, 어플라이언스에 물리 콘솔(tty1) 또는 SSH로 접속한 운영자에게 시스템 상태 조회 / 네트워크 설정 / 서비스 제어 / 로그 조회 / MNX 설정 편집 / 방화벽 관리 / 셸 접근을 제공한다.
- 자기 소개 문자열: `main_app.py:5` "XenServer 스타일의 TUI 기반 시스템 관리 콘솔", `main-login.py:3` "MNX Management Console - TTY1 Entry Point".
- 프레임워크: **Textual (TUI)** — `main_app.py:24` `from textual.app import App`. HTTP 웹 서버가 **아님**.

**중요도: High (Critical 아님).**
- 이유: 데이터 평면(capture/dpi/kafka/es/payload)과 독립적. 콘솔이 죽어도 트래픽 수집·분석은 계속된다. 그러나 운영자의 유일한 로컬 관리 UI(tty1 자동 로그인 대상)이며, 네트워크/서비스/방화벽/설정을 여기서 바꾸므로 운영 관점에서는 High.

**현재 실행 중인가? → 예 (tty1 콘솔 프로세스로 실행 중).**
- `ps aux`: `root 4020 ... /usr/bin/python3.12 /mnxmc/main-login.py` (tty1, 실행 시각 09:58, ELAPSED 38분+ — `ps -o pid,etime,cmd -p 4020`).
- cwd = `/` (`/proc/4020/cwd -> /`), 사용자 = root.

**질문에 대한 명확한 답 — 8000/44114 포트 소유자는 mnxmc가 아니다:**
- `ss -tlnp`: `0.0.0.0:8000` = `python3.12 pid=18814` = `/opt/regression_api/app.py /opt/mnx/etc/mnx_config.json` (`/proc/18814/cmdline` 확인). → **mnxmc 아님, regression_api(별도 컴포넌트)**.
- `ss -tlnp`: `127.0.0.1:44114` = `MainThread pid=23619` = VSCode 서버 확장 호스트 `.vscode-server/.../node ... --type=extensionHost` (`/proc/23619/cmdline` 확인). → **mnxmc 아님, 개발용 VSCode 서버**.
- **mnxmc(main-login.py)는 어떤 TCP 포트도 LISTEN하지 않는다** — TUI 콘솔 앱이므로 소켓 서버가 없다. `ss` 출력의 python 리스너 중 mnxmc는 존재하지 않음.

---

## 2. Executables & launch — 기동 방식

**진입점 2개:**
| 파일 | 용도 | skip_login | 특이사항 |
|---|---|---|---|
| `/mnxmc/main-login.py` | tty1 물리 콘솔 (로그인 화면 표시) | False (`main-login.py:376`) | **현재 실행 중인 것** |
| `/mnxmc/main.py` | SSH 접속 (로그인 건너뛰고 대시보드 직행) | True (`main.py:638`) | PTS 세션 자동 정리 로직 포함 |

**tty1 자동 기동 = systemd getty override (수동/cron 아님):**
- 호스트 실파일 `/etc/systemd/system/getty@tty1.service.d/override.conf` (Bash로 확인):
  ```
  [Service]
  ExecStart=
  ExecStartPre=/bin/clear
  ExecStart=/usr/bin/python3.12 /mnxmc/main-login.py
  StandardInput=tty / StandardOutput=tty / TTYPath=/dev/tty1
  User=root
  Restart=on-failure / RestartSec=1
  ```
- 이 override는 설치 스크립트가 생성: `packages/install_packages.sh:383-416` ([6/8] getty@tty1 설정), 원본 템플릿 `packages/config/getty_override.conf:1-` 및 `readme_install_mnxmc.txt:238-244`.
- 정확한 실행 명령: `/usr/bin/python3.12 /mnxmc/main-login.py` (인자 없음). 작업 디렉토리 `/`, 사용자 **root**, `Restart=on-failure`로 크래시 시 자동 재기동.

**SSH 경로:** `readme_install_mnxmc.txt:534` 및 `install_packages.sh:438-440`가 `/mnxmc/main.py`를 SSH 로그인 셸 대체로 exec (추정: sshd ForceCommand/셸 설정 — `install_packages.sh` 참조). `main.py` 자체는 `python3.12 main.py`로도 수동 실행 가능(`readme:534`).

**환경 변수:**
- `MNX_DEBUG` — 설정 시 콘솔 로그 핸들러 활성화 (`main-login.py:72`, `main.py:69`).
- `TERM` — 미설정 시 tty1은 `linux`(`main-login.py:130`), SSH는 `xterm-256color`(`main.py:100`)로 강제.
- `LANG` — tty1에서 미설정/`unknown`이면 `C.UTF-8` 강제 (`main-login.py:135`).

---

## 3. Config files consumed — 설정 파일

| 경로 | 읽는 코드 | 실제 사용 여부 | 키/기본값 |
|---|---|---|---|
| `/opt/mnx/etc/mnxmc_console.json` | `main.py:140,142-159` `read_mnxmc_config()` | **사용됨(SSH 경로만)** | `session.timeout`(기본 15분), `session.max_sessions`(기본 5). 파일 없으면 `(15,5)` |
| `/opt/mnx/etc/mnx_config.json` | `app/screens/mnx_config.py:34` `JSON_PATH` | 사용됨(MNX Config 화면) | ES/base_path/mnxdpi/pcap 설정 편집 (`mnx_config.py:5`) |
| `/opt/mnx/etc/config.ini` | `mnx_config.py:35` `INI_PATH` | 사용됨 | capture interface/interfaceOps (`mnx_config.py:6`) |
| `/etc/suricata/suricata.yaml` | `mnx_config.py:38` `SURICATA_YAML` | 사용됨 | config.ini 인터페이스 변경 시 af-packet/pcap 동기화 (`mnx_config.py:1889-1907`) |
| `styles/theme.tcss` | `main_app.py:52` `CSS_PATH` | 사용됨 | Textual CSS 테마 |

- **중요:** tty1 진입점 `main-login.py`는 `mnxmc_console.json`을 **읽지 않는다**(세션 정리·타임아웃 로직은 SSH `main.py`에만 존재). tty1 세션은 idle timeout이 0(비활성)로 동작.
- `mnx_config.py:770-803`는 `/opt/mnx/etc/` 및 기본 설정 파일이 없으면 `sudo -n mkdir`/`sudo tee`로 생성.

---

## 4. HTTP/API surface — 웹/API 표면

**해당 없음 (No HTTP server).** mnxmc는 Textual TUI이며 자체적으로 어떤 host:port도 LISTEN하지 않는다(§1 `ss` 근거). 노출 "API"는 REST가 아니라 **키 바인딩 + 화면 네비게이션**이다.

**전역 키 바인딩** (`main_app.py:61-71`):
`F1`=Help, `F5`=Refresh, `F7`=Rescan System, `F8`=Rescan Network, `F10`=Exit, `ESC`=Back, `Ctrl+Q`/`Ctrl+P`=무시(noop). Command Palette 비활성(`main_app.py:58`).

**메인 메뉴 7항목** (`dashboard.py:110-118` `MAIN_MENU`, 라우팅 `dashboard.py:263-286`):
| 메뉴 | 화면 클래스 | 파일 |
|---|---|---|
| System Overview | `SystemScreen` | `app/screens/system.py` (1012줄) |
| Performance Monitor | `PerformanceScreen` | `app/screens/performance.py` (941줄) |
| Log Monitoring | `LogsScreen` | `app/screens/logs.py` (1137줄) |
| Service Status | `ServiceScreen` | `app/screens/service.py` (1011줄) |
| Network Management | `NetworkScreen` | `app/screens/network.py` (1692줄) |
| MNX Config | `MnxConfigAuthScreen`→`MnxConfigScreen` | `app/screens/mnx_config.py` (2981줄) |
| Command Shell | `ShellScreen` | `app/screens/shell.py` (513줄) |

**아웃바운드 "API" 클라이언트 호출**(콘솔이 소비하는 외부 서비스):
- Elasticsearch REST: `GET http://localhost:9200/_cluster/health`, `/_cat/indices?format=json` (`elasticsearch_monitor.py:20,25,53,167`). requests 우선, 실패 시 `curl` fallback(`:90`).
- Kafka: `kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list/--describe --group mnx` (`kafka_monitor.py:13,23-24,40-42`).

---

## 5. Internal structure — 모듈 맵 & 호출 그래프

**디렉토리 구조 (our code):**
- `main-login.py`, `main.py` — 진입점.
- `app/` — Textual UI. `main_app.py`(MNXApp), `screens/`(11개 화면), `widgets/`(CustomHeader, MenuList, TwoPanelLayout), `styles/theme.tcss`.
- `modules/` — 백엔드 로직(UI 무관): `base_module.py`, `system_info.py`, `performance_monitor.py`, `kafka_monitor.py`, `elasticsearch_monitor.py`, `log_viewer.py`, `disk_monitor.py`, `firewall_manager.py`.
- `network_management/` — `network_management.py`(NetworkManagement/NetworkInterface), `network_config.py`(netplan 적용).
- `utils/` — `auth.py`, `helpers.py`, `__init__.py`.
- `infra_audit/` — 보안 점검 셸 스크립트 모음(별개 유틸, 앱 런타임과 무관). `packages/` — deb 빌드/오프라인 설치. `test-tool/` — pcap 재생/대역폭 셸 스크립트.

**MNXApp 핵심** (`main_app.py:29`):
- 백엔드 모듈 **lazy-init** property (`main_app.py:117-164`): `system_info, perf_monitor, kafka_monitor, es_monitor, log_viewer, network_mgmt, disk_monitor`. 각 `_init_*`(`:170-260`)는 import 실패해도 `None`으로 저장하고 계속(방어적).
- `on_mount`(`:285`): 폭 100컬럼 미만 경고 → skip_login이면 `_push_dashboard`, 아니면 `_push_login`(`:302-309`) → idle timeout>0이면 60초 간격 타이머(`:313`).
- idle timeout: `_check_idle_timeout`(`:351`), 키/마우스 활동 시각 갱신(`:341-349`). **단, tty1(main-login.py)은 idle_timeout=0으로 생성되어 비활성**.

**메인 흐름 (call graph):**
```
getty@tty1 → python3.12 main-login.py
  main() [main-login.py:306]
   ├ check_python_version/terminal/dependencies (textual,rich)
   ├ setup_logging → /var/log/mnx/mnx_console.log, mnx_auth.log
   ├ check_root_privileges (geteuid==0 또는 /etc/shadow 읽기)
   ├ dmesg -n 1 (커널 콘솔 메시지 억제) [subprocess]
   └ MNXApp(skip_login=False).run() [main_app.py:29]
        on_mount → _push_login → LoginScreen [login.py:188]
          _login → AuthenticationManager.authenticate [login.py:54]
            _verify_shadow (spwd + crypt) [login.py:94]
          성공 → switch_screen(DashboardScreen) [dashboard.py]
            메뉴 선택 → 각 Screen → 각 modules/*.py
              KafkaMonitor → subprocess(kafka-consumer-groups.sh) → localhost:9092
              ElasticsearchMonitor → requests/curl → localhost:9200
              NetworkManagement → subprocess(ip/ethtool) ; network_config → netplan
              FirewallManager → subprocess(ufw)  (sudo -n if not root)
              ServiceScreen → subprocess(systemctl status/start/stop ...)
              ShellScreen → app.suspend() → subprocess(/bin/bash --login)
```

SSH 경로(`main.py:545`)는 추가로 `cleanup_old_pts_sessions()`(`:166-391`, pkill -HUP로 오래된/초과 PTS 세션 종료) + `SessionManager`(`:398`, `/tmp/mnx_session_<uid>.lock` 중복 실행 방지)를 수행한 뒤 `MNXApp(skip_login=True, idle_timeout=timeout).run()`.

---

## 6. Data in/out — 입출력

**읽기 (파일/proc/sys):**
- `/proc/cpuinfo, /proc/meminfo, /proc/stat, /proc/loadavg, /proc/net/dev, /proc/diskstats`, `/sys/block/*` (`performance_monitor.py`, `system_info.py`, `disk_monitor.py` grep 확인).
- `/proc/uptime` (login 화면 footer, `login.py:359`).
- `/etc/passwd`(pwd 모듈), `/etc/shadow`(직접 파싱 또는 spwd) — 인증.
- 로그 파일 tail: `/logs/mnxcapture, /logs/mnxdpi, /logs/suricata, /logs/payload_analysis, /logs/service_control, /logs/file_analysis_ai, /logs/dga_analysis_ai, /var/log/syslog`(`log_viewer.py:21-28`), `/var/log/messages`(`logs.py:1118`).

**쓰기:**
- 로그: `/var/log/mnx/mnx_console.log`, `/var/log/mnx/mnx_auth.log` (`main-login.py:35-36`, `auth.py:51`).
- 세션 락: `/tmp/mnx_session_<uid>.lock` (SSH 전용, `main.py:402`).
- 설정 파일: `sudo tee`로 `config.ini`, `mnx_config.json`, `mnxmc_console.json`, `suricata.yaml`, netplan yaml 등 (`mnx_config.py:789` `_sudo_tee_write`, sudoers 화이트리스트 §8).
- suricata.yaml 백업: `/opt/mnx/etc/suricata.yaml.bak` (`mnx_config.py:1907`).
- 방화벽 변경 시 syslog 기록: `syslog.syslog(... "[MNXMC][UFW] ...")` (`firewall_manager.py:183`).

**외부 서비스:**
- Elasticsearch `localhost:9200` (HTTP), Kafka `localhost:9092` (kafka CLI). MariaDB **미사용**(아래).
- **MariaDB `mnx_db` 접근 없음:** `grep -niE "mnx_db|mariadb|mysql|pymysql|3306"`가 mnxmc 코드에서 0건. 콘솔은 DB를 직접 건드리지 않는다.

**subprocess 호출 바이너리:** `ip, ethtool, netplan`(네트워크), `ufw`(방화벽), `systemctl`(서비스), `curl`(ES fallback), `kafka-consumer-groups.sh`(Kafka), `dmidecode`(system_info hw), `dmesg`(콘솔 억제), `su`/`sudo`(인증), `ps/who/pkill`(SSH 세션 정리), `/bin/bash`(셸), `clear`. RAID/디스크 도구 `storcli64/perccli64/smartctl/fio`는 sudoers에 허용됨(§8) — disk/performance 화면에서 호출(추정, 화면 파일 미정독).

---

## 7. Threads/processes/IPC

- **스레드:** 명시적 threading 없음(추정). Textual 이벤트 루프(asyncio) 기반. UI 주기 갱신은 `set_interval`(예: `main_app.py:313` 60초 idle 체크, `dashboard.py:154` 1초 상태 갱신, `login.py:373` 1초 footer). 블로킹 subprocess가 이벤트 루프 내에서 동기 실행됨(잠재적 UI 프리즈, §11).
- **subprocess/Popen:** 다수 — `auth.py:367`(su), `:422`(sudo -S -v), `login.py:158`(su), `base_module.py:25/41`, `helpers.py:27`, 각 modules. `shell.py:477-479` `subprocess.call(['/bin/bash','--login'])` in `app.suspend()`.
- **소켓:** `login.py:316` UDP 소켓으로 로컬 IP 탐지(8.8.8.8:80 connect, 실제 전송 없음).
- **시그널:** SIGINT/SIGTERM/SIGHUP 핸들러(`main-login.py:249-253`, `main.py:508-512`). `main.py`의 SIGHUP은 세션 정리에 의한 종료로 간주하여 메시지 없이 `os._exit(0)`(`main.py:493-496`) — asyncio 우회.
- **락/큐:** `SessionManager`(`main.py:398`) 파일 기반 락. 큐 사용 없음. `atexit` + `_cleanup_handlers` 리스트로 종료 정리(`main-login.py:218-232`).
- **IPC:** getty→앱은 tty stdin/stdout. 앱→외부는 subprocess + HTTP.

---

## 8. Dependencies — 의존성

**Python 패키지 (`requirements.txt`):** TUI 코어 `textual==8.2.1`, `rich==14.3.3`, `pygments`, `markdown-it-py` 등. HTTP `requests==2.33.1`, `urllib3`, `certifi`, `idna`, `charset-normalizer`. 암호 `cryptography>=43,<46`(Fernet — mnx_config 비밀번호 암호화용). 표준 라이브러리: `pwd, spwd, crypt, termios, signal, subprocess, socket, syslog, json, logging, pathlib`.
- 오프라인 설치: `packages/pip/*.whl` (`requirements.txt` 주석, `install_packages.sh`).
- `passlib`는 `utils/auth.py`가 시도하지만(`auth.py:31`) requirements.txt에 없음 → utils/auth.py의 passlib 경로는 실환경에서 미설치 가능(추정, 어차피 dead code §11).

**외부 바이너리 (런타임 필수):** `python3.12`, `ip/ethtool/netplan`(iproute2), `ufw`, `systemctl`, `curl`, `/usr/local/kafka/bin/kafka-consumer-groups.sh`, `dmidecode`, `dmesg`. RAID: `storcli64/perccli64`(`packages/storcli`, `packages/perccli`), `smartctl`, `fio`, `graidctl`.
- Java/ES JDK 경로 하드코딩: `kafka_monitor.py:12` `JAVA_HOME=/usr/share/elasticsearch/jdk/`.

**sudoers 권한** (`packages/sudoers_mnxmc`, 사용자 `sands` NOPASSWD): `dmidecode, storcli64, perccli64, graidctl, smartctl, ip, netplan, systemctl, ethtool, ufw, fio, reboot, shutdown -h now`, 그리고 특정 경로 한정 `tee`(config.ini/mnx_config.json/mnxmc_console.json/settings.json/suricata.yaml/sshd_config.d/netplan yaml), `rm -f promisc-*.service` 등. → 앱이 root가 아닐 때 `sudo -n`으로 이들 실행(`firewall_manager.py:48`, `mnx_config.py:774`). **운영에서는 앱이 root로 실행되므로 sudo 불필요.**

---

## 9. Ports — 포트

- **LISTEN: 없음.** mnxmc는 서버 포트를 열지 않는다(§1, §4).
- **아웃바운드(로컬):** `localhost:9200`(ES, requests/curl), `localhost:9092`(Kafka CLI). `login.py:316`의 8.8.8.8:80 UDP connect는 라우팅 조회용(패킷 미전송).
- 참고(같은 호스트의 타 컴포넌트, mnxmc 아님): 8000 regression_api, 9200/9300 ES(java), 9092/2181 Kafka/ZK(java), 3306 mariadb, 80/443/8090 nginx, 8443 mnx_web(java), 44114 vscode.

---

## 10. Failure impact & recovery — 장애 영향/복구

**죽으면 무엇이 깨지나:**
- 데이터 평면(capture/dpi/kafka/es/payload) 영향 **없음** — 완전 독립.
- tty1 로컬 관리 콘솔이 사라짐. 단 `Restart=on-failure, RestartSec=1`(getty override)로 크래시 시 systemd가 1초 후 자동 재기동. 정상 종료(F10)나 로그아웃 시에는 getty가 재-spawn.
- SSH 관리(main.py)는 세션별 프로세스라 한 세션 죽어도 타 세션 무관.

**복구/재시작:**
- tty1: `systemctl restart getty@tty1.service` (`install_packages.sh:413`).
- 수동: `sudo /usr/bin/python3.12 /mnxmc/main-login.py` (tty에서) 또는 `python3.12 main.py`.
- 의존성 미충족 시 진입점이 조기 종료하며 안내(`main-login.py:322-326` textual/rich 누락 검사).

**의존 관계:** UI 자체는 ES/Kafka가 죽어도 동작(각 모니터가 실패를 잡아 "not running" 표시). 백엔드 모듈 import 실패해도 앱은 뜸(lazy-init None 처리). 즉 **콘솔은 견고하게 degrade**된다.

---

## 11. Code quality — 품질/위험

**(A) 중복 인증 구현 3곳 (심각) — 유지보수·보안 위험:**
- `utils/auth.py`의 `AuthenticationManager`(passlib+crypt fallback, 3.13 대응) — **실제로는 dead code**. `grep` 결과 어떤 화면도 import 안 함; `utils/__init__.py:7`에서 re-export만 됨.
- `app/screens/login.py:39`의 `AuthenticationManager`(spwd+crypt) — **실사용(tty1 로그인)**.
- `app/screens/service.py:50-77`의 또 다른 `AuthenticationManager`(spwd+crypt) — MNX Config 접근 인증(`dashboard.py:407` import)에서 실사용.
- 세 구현이 정책(잠금 30s/3회)만 같고 서로 다르게 진화 중.

**(B) Python 3.13 시한폭탄 (High):** 실사용 인증 경로(`login.py:102-103,121`, `service.py:51,73,77`)가 `import spwd` / `import crypt`를 직접 사용. 두 모듈은 **Python 3.13에서 제거됨**. 현재 호스트는 `Python 3.12.13`(검증)이라 동작하나, 3.13 업그레이드 시 **tty1 로그인·Config 인증이 즉시 붕괴**. (역설적으로 dead code인 `utils/auth.py`만 3.13 대응이 되어 있음.)

**(C) root 환경 su 우회 인지 처리 (양호):** `login.py:82-92,153-155`가 "root로 실행 시 su는 비밀번호 검사 안 함"을 알고 root면 su fallback 차단, shadow 인증만 사용. 올바른 보안 판단. 단 `utils/auth.py:311-313`는 이 구분이 없어 root에서 su fallback을 그대로 사용(dead code라 실피해 없음).

**(D) Command Shell = root 셸 부여 (설계상 위험, 의도된 것으로 보임):** `shell.py:409` `app.suspend()` 후 `subprocess.call(['/bin/bash','--login'])`(`:477-479`). 앱이 root로 도니 인증 통과 시 **root 셸**. 감사/제한 없음.

**(E) 이벤트 루프 블로킹:** 모든 subprocess가 동기(`subprocess.run` timeout 5~30s). ES/Kafka/systemctl 지연 시 TUI가 최대 수십 초 프리즈 가능. asyncio worker 미사용. (성능 위험, race는 아님)

**(F) 예외 처리 과다 광범위 `except Exception: pass`:** `network_management.py:82,116,138,155,197`, `elasticsearch_monitor.py` 다수, `auth.py:352` 등. 실패가 조용히 삼켜져 디버깅 난이도↑. 인증 `_verify_shadow`가 어떤 예외든 False 반환(`auth.py:352`, `login.py:142`) — fail-safe이나 로깅 부재.

**(G) 죽은/중복 코드:**
- `utils/auth.py` 전체(≈600줄) 사실상 미사용(§A).
- `main_app.py:536-546` `action_show_help`가 `app.screens.help` import하나 `help.py` 파일 부재(§파일 목록에 없음) → 항상 ImportError→notify fallback. 즉 F1 도움말 화면은 존재하지 않음.
- `base_module.run()` 및 각 모듈의 터미널 모드 `run()`(예: `kafka_monitor.py:114`, `elasticsearch_monitor.py:253`)은 TUI에서 미사용(구 CLI 호환용 잔재).
- `network_management.py:250-289` "기존 코드 호환용" 메서드(`get_all_interfaces_info` 등) — 호출처 불명(추정 미사용).

**(H) 잠재 버그:**
- tty1 세션은 idle timeout 미적용(`main-login.py`가 `idle_timeout_minutes`를 넘기지 않음 → 기본 0). 물리 콘솔이 무한정 로그인 상태로 방치될 수 있음. 반면 SSH만 타임아웃.
- `main.py:583` 세션 정리에서 `pkill -HUP -t <tty>`로 타 사용자 pts를 종료 — 안전 규칙(주석 `:177-186`)은 있으나 `who -u` 파싱(`:256-270`)이 로캘/포맷 의존적이라 오탐 시 정상 세션 종료 가능(추정).
- `SessionManager.acquire`(`main.py:405-419`)는 실패 시 `return True`(예외를 성공으로 처리) → 락 목적 약화.

**(I) 하드코딩 값:** `JAVA_HOME=/usr/share/elasticsearch/jdk/`(`kafka_monitor.py:12`), `localhost:9200`(`elasticsearch_monitor.py:20`), `localhost:9092`(`kafka_monitor.py:24`), `8.8.8.8`(`login.py:318`), 잠금정책 3회/30초 여러 파일. **평문 비밀번호/시크릿 하드코딩은 발견되지 않음**(grep 0건). 단 비밀번호가 `su`/`sudo`에 `process.communicate(input=password+'\n')`로 전달됨(`auth.py:376-378,429`, `login.py:166`) — 메모리 상 평문이나 파일 기록은 없음.

---

## 12. Cross-references — 타 컴포넌트 연동

mnxmc는 **관측/제어 평면**으로서 다음을 모니터링·제어하나, 데이터는 주고받지 않는다:
- **Elasticsearch** (`localhost:9200`): 클러스터 헬스 + 인덱스 조회(`arkime_sessions3-*`, `mnx_sessions3-*`, `net-stats-*`, `payload_*`, `ai_content-*`, `mail_content-*`, `playbook-*`, `mnx_dstats`, `mnx_hunts`) — `elasticsearch_monitor.py:66-69`.
- **Kafka/Zookeeper** (`localhost:9092`): consumer group `mnx`의 lag/offset 조회 — `kafka_monitor.py`.
- **서비스 제어 (systemctl)** — `service.py`가 관리하는 대상: `mnx_service_control, mnx_payload, mnx_payload_ai, mnx_payload_scan, mnxcapture, mnxdpi, suricata, elasticsearch, kafka, zookeeper, eng_monitor`(`service.py:276-287,918-948`). 이들은 각각 capture/dpi/payload/scanengine/AI 데이터 평면 컴포넌트.
- **capture/dpi**: 직접 통신 없음. 로그 tail(`/logs/mnxcapture`, `/logs/mnxdpi`)과 systemctl 상태로만 관측. 설정은 `config.ini`(capture interface)·`suricata.yaml`을 통해 간접 반영.
- **payload / AI**: 로그(`/logs/payload_analysis`, `/logs/file_analysis_ai`, `/logs/dga_analysis_ai`) 관측 + 서비스 제어.
- **web/api docker, mnx_web(java 8443), regression_api(8000)**: mnxmc 코드에서 직접 참조 없음. 동일 호스트에 공존할 뿐 연동 코드 부재(추정).
- **MariaDB mnx_db(3306)**: 연동 없음(§6 확인).
- **네트워크/방화벽/OS**: `ip/ethtool/netplan`(NIC, static IP, mirror/promisc), `ufw`(방화벽 룰), `dmidecode/storcli/perccli/smartctl/fio`(HW/RAID/디스크), `reboot/shutdown`.

---

## 부록 — 패키징 & 버전

- **빌더:** `packages/build_deb.sh`(v2.4) — `/mnxmc`에 소스+`packages/`를 푸는 아카이브 deb 생성. 산출물 기본 위치 `/data`(`build_deb.sh:12`). control: `Package: mnxmc, Maintainer: SANDS LAB Inc. <admin@sandslab.kr>, Depends: bash`. postinst는 권한만 조정하고 실제 설치는 `sudo bash /mnxmc/packages/install_packages.sh` 수동 안내.
- **빌드 스테이징:** `/home/sands/mnxmc_deb_build/` (DEBIAN/, etc/, mnxmc/ — Apr 13 빌드 잔여물).
- **산출 deb (`/data`):** `mnxmc-2.1.3.deb`(5/15), `mnxmc-2.1.4.deb`(5/15), `mnxmc-2.2.0.deb`(6/4, 132MB — 최신). deb가 큰 이유: `packages/apt/*.deb` + `packages/pip/*.whl` + RAID 바이너리 오프라인 번들 포함.
- **버전 불일치(경미):** 코드 버전 표기가 혼재 — `main.py`/`main-login.py`/`main_app.py` docstring "2.2.0", `login.py` "v2.4.0"(`:8,329`), `requirements.txt` 주석 "v2.1.0", deb 최신 2.2.0. UI에 노출되는 로그인 화면은 v2.4.0으로 표기.

---

### 검증 방법 요약
- `ss -tlnp` (포트 소유자), `ps aux`, `/proc/<pid>/cmdline`, `/proc/<pid>/cwd` (프로세스 신원).
- `python3.12 --version` → 3.12.13 (spwd/crypt 아직 동작).
- 전 소스 `grep`/`Read` (인증·설정·subprocess·DB 참조).
- 호스트 `/etc/systemd/system/getty@tty1.service.d/override.conf` 실파일 확인.
