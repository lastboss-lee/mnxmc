# Phase 4 — 소스 콜 그래프 (Source Call Graph)

> 근거: Python 소스는 `grep -n 'def/class'` 실측(파일:라인 인용). C/C++ 바이너리(capture/mnxdpi/payload_analysis/scanengine/service_control)는 stripped ELF이므로 **함수 단위 정적 콜그래프 추출 불가** → `strings`/설정/런타임 동작 기반의 **모듈·흐름 수준** 그래프로 대체하며 **(추정)** 표기.

---

## 1. mnxmc 콘솔 (Python/Textual) — 실측 콜 그래프

`main-login.py` 진입점 흐름 (`main-login.py:306` `main()`):

```mermaid
flowchart TD
    M["__main__ (main-login.py:401)"] --> MAIN["main() :306"]
    MAIN --> CPV["check_python_version() :112"]
    MAIN --> CT["check_terminal() :122"]
    MAIN --> CD["check_dependencies() :140"]
    MAIN --> CR["check_root_privileges() :157"]
    MAIN --> SL["setup_logging() :46 / setup_auth_logging() :81"]
    MAIN --> SH["setup_signal_handlers() :249"]
    MAIN --> TSM["TerminalStateManager :179"]
    MAIN --> APP["MNXApp(...).run()  (app/main_app.py:29)"]

    APP --> OM["on_mount() :285"]
    OM --> PL["_push_login() :315"]
    PL --> LOGIN["screens/login.py (AuthenticationManager)"]
    LOGIN -->|성공| PD["_push_dashboard() :324"]
    PD --> DASH["screens/dashboard.py"]

    APP --> INIT["init_all_modules() :262"]
    INIT --> M1["_init_system_info() :170 → modules/system_info.py"]
    INIT --> M2["_init_perf_monitor() :183 → modules/performance_monitor.py"]
    INIT --> M3["_init_kafka_monitor() :196 → modules/kafka_monitor.py (Kafka CLI)"]
    INIT --> M4["_init_es_monitor() :209 → modules/elasticsearch_monitor.py (ES :9200)"]
    INIT --> M5["_init_log_viewer() :222 → modules/log_viewer.py"]
    INIT --> M6["_init_network_mgmt() :235 → network_management/*.py"]
    INIT --> M7["_init_disk_monitor() :249 → modules/disk_monitor.py"]

    APP --> IDLE["_check_idle_timeout() :351"]
    APP --> LOGOUT["logout() :608 / action_quit_app() :380"]
```

**화면(screens) → 모듈 매핑** (`app/screens/`):

| Screen | 대응 모듈/동작 | 외부 접근 |
|---|---|---|
| `login.py` | 자체 `AuthenticationManager`(PAM/`spwd`/`crypt`) | 로컬 계정 |
| `service.py` | 서비스 상태/제어(자체 인증 재구현) | `systemctl`, service_control |
| `dashboard.py` | 종합 상태 | — |
| `elasticsearch.py` | `modules/elasticsearch_monitor` | ES :9200 |
| `kafka.py` | `modules/kafka_monitor` | Kafka CLI :9092 |
| `performance.py`/`system.py`/`logs.py`/`network.py`/`firewall.py`/`mnx_config.py`/`shell.py` | 각 modules/* | psutil, netplan, iptables, `/bin/bash` |

> ⚠ `utils/auth.py`의 `AuthenticationManager`는 **미사용**(dead). 실제 인증은 `login.py`·`service.py`가 각기 재구현(3중 중복). `login.py:102`/`service.py:51`가 Python 3.13 제거 예정 `spwd`/`crypt` 직접 사용 → 업그레이드 시 로그인 붕괴 위험.

---

## 2. regression_api (Python http.server) — 실측 콜 그래프

`app.py:314` `__main__` → HTTP 요청 처리 흐름:

```mermaid
flowchart TD
    MAIN["__main__ (app.py:314)"] --> CFG["config.set_config_path()/load_config() (config.py:10,18)"]
    MAIN --> POOL["worker_pool.init_pool(max_workers=5) (worker_pool.py:15)"]
    MAIN --> REC["_recover_stale_jobs() (app.py:296)"]
    MAIN --> SRV["ThreadingHTTPServer (app.py:69) serve_forever"]

    SRV --> RH["RequestHandler (app.py:73)"]
    RH --> GET["do_GET() :93"]
    RH --> POST["do_POST() :103"]
    GET --> HHEALTH["_handle_health() :113"]
    GET --> HSTAT["_handle_status(job_id) :155 → status_store.read_json"]
    POST --> HANALYZE["_handle_analyze() :167"]
    POST --> HCANCEL["_handle_cancel(job_id) :250"]

    HANALYZE --> SUBMIT["worker_pool.submit_job() :29"]
    SUBMIT --> WLOOP["_worker_loop() :88 (Queue 소비)"]
    WLOOP --> RUNJOB["suricata_runner.run_job() :401"]

    RUNJOB --> SETUP["_setup_suricata() :201 → resolve_suricata_bin() :38"]
    RUNJOB --> PREP["_prepare_rule_and_config() :211"]
    PREP --> DLRULE["download_rule() :73 (rule_url)"]
    PREP --> BUILDYAML["build_job_suricata_yaml_from_base() :92"]
    RUNJOB --> VALIDATE["_validate_rule_config() :231"]
    RUNJOB --> PROCESS["_process_pcaps() :252"]
    PROCESS --> LISTPCAP["list_pcaps() :49 (/data/raw)"]
    PROCESS --> RUNCMD["run_cmd() :30 → suricata 서브프로세스"]
    PROCESS --> MERGE["merge_eve_append() :134"]
    RUNJOB --> SUMMARY["_build_and_write_summary() :353 → compute_by_signature_id() :167"]
    RUNJOB --> MAP["session_mapper.map_alerts_to_sessions() :140"]
    MAP --> QRY["_build_session_search_query() :28"]
    MAP --> MERGEF["_merge_suricata_fields() :68"]
    MAP --> ESREQ["es_client._es_json_request() :8 (ES :9200)"]
    RUNJOB --> STATUS["status_store.update_status()/atomic_write_json() :30,22"]
```

**외부 의존:** `suricata`(서브프로세스), Elasticsearch(`mnx_sessions3-*` 조회/갱신), 파일시스템(`/data/raw` pcap, job 산출물).

---

## 3. file_analysis_ai (Python 멀티프로세스) — 실측 콜 그래프

```mermaid
flowchart TD
    MAIN["__main__ (file_analysis_ai.py:273)"] --> ARGS["_parse_args() :257 (start|stop)"]
    MAIN --> DM["DAEMON_MAIN(Daemon) :184"]
    DM --> DZ["daemon.py Daemon.daemonize() :24 / start() :84"]
    DM --> RUN["DAEMON_MAIN.run() :196"]
    RUN --> MPM["MP_MANAGER (mp_manager.py:87)"]
    MPM --> SPAWN["WORKER_PROCESS(Process) :517 ×16 prefork"]
    SPAWN --> WF["WORKER.worker_function(sock_client) :36"]
    WF --> RECV["UNIX sock /var/run/payload_ai_analysis.sock 수신 {file_type,file_path}"]
    WF --> MODEL["model/<type>/ 로드 (XGBoost/RandomForest, filekit/modelcore)"]
    WF --> INFER["추론 → {label, score}"]
    WF --> SEND["소켓 응답"]
    MPM --> WATCH["__default_mode_worker_watcher() :467 / __reuse_worker_watcher() :401 (워커 감시/재생성)"]
    MPM --> Q["put()/get()/get_bulk() :308,318,334 (in/out Queue)"]
```

**IPC:** `MP_MANAGER`가 `multiprocessing.Queue`(in/out) + 워커 프로세스 풀 관리. 외부 인터페이스는 UNIX 소켓. **호출자:** `payload_analysis`(C++).

---

## 4. syslog.py / server_check.py (cron) — 실측 콜 그래프

```mermaid
flowchart LR
    subgraph syslog["syslog.py (cron 5m)"]
      SB["bootstrap_and_run() :371"] --> GL["get_syslog_server_list() :30"]
      GL -->|enable:false 전부| EXIT["조기 종료(inert)"]
      SB --> WIN["_compute_window_mnx() :468"]
      SB --> RUNM["_run_mnx() :485"]
      RUNM --> DETECT["get_detect_contents() :236"]
      RUNM --> EQ["execute_query() :261 (ES 조회)"]
      RUNM --> SS["syslog_send_sessioninfo() :307 → send_to_server() :131 (RFC6587/TLS/UDP)"]
    end
    subgraph schk["server_check.py (cron ~30s)"]
      SM["main(cpu_interval,hdd_path) :18"] --> CSC["call_server_check(hdd,cpu,mem) :36"]
      CSC --> POST["POST 웹 /api/server/status/save"]
    end
```

---

## 5. C/C++ 데이터 플레인 (모듈·흐름 수준, 추정)

바이너리는 stripped이므로 함수 심볼 기반 콜그래프 없음. `strings`/설정/런타임 동작으로부터 도출한 **흐름 콜그래프**:

```mermaid
flowchart TD
    subgraph capture["capture (네이티브 C)"]
      CMAIN["main → config.ini 로드"] --> RDR["packet reader(TPACKET_V3, 2 threads)"]
      RDR --> PARSE["parser .so ×47 (dns/http/tls/...)"]
      RDR --> WRITER["pcap writer → /pipeline/raw"]
      PARSE --> ESIDX["mnx_db_* → ES /_bulk (mnx_sessions3)"]
      ESIDX -.현재 stall.-> SEQ["mnx_db_get_sequence_number_sync (무한 재시도)"]
      PARSE --> PLUG["plugins: suricata.so(eve.json), libmnxdpi.so(선언, 미로드 추정)"]
    end
    subgraph dpi["mnxdpi (C++, PACE2+PcapPlusPlus)"]
      DMAIN["main(-c json -s)"] --> WI["pcapfile_work_item (mode=direct)"]
      WI --> CLASS["_MNX_SESSION_PROCESS 분류"]
      CLASS --> DES["ES /_bulk (mnx_sessions3)"]
      CLASS --> DKAF["Kafka produce (request-file-analysis)"]
      CLASS --> CARVE["payload carving → /data/payload"]
    end
    subgraph pay["payload_analysis (C++)"]
      PMAIN["main(-d -c json)"] --> KCON["Kafka consume (group mnx)"]
      KCON --> YARA["YARA file_type.yar 타이핑"]
      YARA --> FANOUT["UNIX sock 팬아웃"]
      FANOUT --> AISOCK["→ file_analysis_ai.sock"]
      FANOUT --> AVSOCK["→ scanengine.sock"]
      FANOUT --> PES["ES payload_*/ai_content-*/mail_content-*"]
    end
    subgraph sc["service_control (C++)"]
      SMAIN["main(-d -c json)"] --> CTLSOCK["UNIX sock /var/run/service_control.sock"]
      SMAIN --> MOVE["/pipeline/raw → /data/raw (60s)"]
      SMAIN --> HB["heartbeat/patch/version → 웹 :8443"]
      SMAIN --> SYSCTL["systemctl 모듈 제어"]
    end
```

> 정밀 함수 콜그래프가 필요하면 `mnxdpi.debug`(디버그심볼) 또는 원본 소스 저장소가 있어야 함(어플라이언스에는 소스 부재). **인수인계 시 빌드 저장소 확보 필요**.

---

## 6. Spring Boot API (Java) — 아키텍처 콜 계층 (추정, 디컴파일 근거)

```mermaid
flowchart LR
    REQ["HTTPS :8443 /api/**"] --> SEC["Spring Security 필터<br/>(JWT/JSESSIONID/X-API-KEY)"]
    SEC --> CTRL["37 @RestController (~244 endpoint)"]
    CTRL --> SVC["@Service 비즈니스 계층"]
    SVC --> REPO["Spring Data Repository"]
    REPO --> MDB[(MariaDB mnx_db, Hikari 300)]
    SVC --> ESC["ES RestClient :9200"]
    SVC --> EXT["→ regression_api :8000 / service_control sock / SECUI"]
```

세부 엔드포인트·인증은 **Phase 6(REST API)**, 테이블 매핑은 **Phase 7(DB)** 참조.

---

## 7. 진입점 총괄표

| 컴포넌트 | 진입점(파일:라인) | 런타임 형태 |
|---|---|---|
| 콘솔 | `main-login.py:306 main()` / `main.py` | Textual App |
| regression_api | `app.py:314 __main__` | ThreadingHTTPServer + 5 proc pool |
| file_analysis_ai | `file_analysis_ai.py:273 __main__` | Daemon + 16 worker proc |
| syslog | `syslog.py:371 bootstrap_and_run()` | cron oneshot |
| server_check | `server_check.py:18 main()` | cron oneshot |
| capture | `main`(C, 네이티브) | 네이티브 데몬 |
| mnxdpi | `main`(C++) | 네이티브 데몬 |
| payload_analysis | `main`(C++) | 네이티브 데몬 |
| service_control | `main`(C++) | 네이티브 데몬 |
| API | Spring Boot `app.jar` | JVM |
