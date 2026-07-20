# 06 — Support / Control / Monitoring Services + Cron Tools

> Architecture handover research. Every claim is grounded in source/config/runtime with `file:line`.
> Host: `sands-test`. Data captured live on 2026-07-10 (system booted 09:57 KST).
> Config consumed by most services: `/opt/mnx/etc/mnx_config.json` (9464 bytes, keys: `config_version, global, mnxdpi, payload_analysis, payload_scanengine, payload_ai_analysis, service_control, regression_api, syslog`).

---

## 1. Overview

| # | Service | Type | Unit / Schedule | Running now | Role (one line) |
|---|---------|------|-----------------|-------------|-----------------|
| 1 | `service_control` | C++ ELF daemon | `mnx_service_control.service` (enabled, Type=forking) | YES pid 15585 | Controls (start/stop/restart) other mnx_* modules over a UNIX socket; sends module heartbeats to mnxweb; post-processes raw PCAP files |
| 2 | `regression_api` | Python 3.12 stdlib HTTP server | `mnx_regression_api.service` (enabled, Type=simple) | YES pid 18814 (+5 worker procs) | Internal REST API to re-run Suricata rules against stored PCAPs and map alerts back onto ES sessions ("regression" = rule testing) |
| 3 | `server_check.py` | Python cron script | crontab `* * * * *` ×2 (staggered +30s) | On-demand (runs each minute) | Reads host CPU/MEM/HDD, POSTs to mnxweb `/api/server/status/save` |
| 4 | `syslog.py` | Python cron script | crontab `*/5 * * * *` | On-demand (every 5 min) | Pulls detections (+optional sessions) from mnxweb/ES, forwards them as RFC5424/6587 syslog to configured SIEM servers |
| 5 | `eng_monitor.sh` | Bash daemon (while-true) | `eng_monitor.service` (enabled, Restart=always) | YES pid 16120 | Samples capture NIC (`ens192`) throughput (Mbps/PPS) every 1s → ES `net-stats-YYYYMM` |
| 6a | `pcap_delete.py` | Python cron script | crontab `*/10 * * * *` | On-demand (every 10 min) | Deletes oldest `/data/raw` PCAPs (+`/pipeline/raw` symlinks) when disk ≥ 80% |
| 6b | `payload_delete.sh` | Bash cron script | crontab `30 3 * * *` (DUPLICATED — 2 entries) | On-demand (daily 03:30) | Deletes payload date-folders older than 1 day |

**Naming note:** the four `mnx_*` background modules that `service_control` manages (mnxdpi, payload_analysis, scanengine, file_analysis_ai, etc.) are a *different* subsystem; this doc covers only the control/monitor/cron layer.

---

## 2. `service_control`

### 2.1 Type & provenance
- **Binary**, not a script. `/opt/service_control/service_control` — `ELF 64-bit LSB pie executable, x86-64 … with debug_info, not stripped` (2.1 MB).
- C++ (jsoncpp + libcurl). Source tree baked into debug info: `/root/projects/service_control/` — `service_control/main.cpp`, `service_control/CDaemonMain.cpp`, `CommonCode/{CDaemonBase,CurlWrapper,custom_thread_pool,JsoncppWrapper,LogFile,Utils}.cpp`.
- Banner string: `MNX v23 Service Control`.
- Started as `/opt/service_control/service_control -d -c /opt/mnx/etc/mnx_config.json` (`-d` = daemon mode; help string `-d, --daemon Run Daemon Mode`).
- Unit: `/etc/systemd/system/mnx_service_control.service` — `Type=forking`, `KillSignal=SIGQUIT`, `TimeoutStopSec=infinity`, `SendSIGKILL=no`, `Restart=on-failure`, PID file `/run/service_control.pid` (removed by `ExecStopPost`).
- Runtime: pid 15585, 4 OS threads (`/proc/15585/task` = 4), Memory ~1.9 M.
- Helper scripts `start.sh`/`stop.sh` exist but are NOT used by systemd. **Caveat:** `start.sh:10` passes `/opt/service_control/settings.json`, while systemd passes `/opt/mnx/etc/mnx_config.json`. `settings.json` uses OLD key names (`pcap_raw_path`, `mnxweb_info`, `pcap_raw_proc_flag`) that differ from the live config (`pcap_storage_config`, `manage_web`). Treat `start.sh`/`settings.json` as stale/dev leftovers.

### 2.2 What it controls (the UNIX-socket control server)
- Listens on **UNIX domain socket `/var/run/service_control.sock`** (confirmed: `ss -xlnp` → `u_str LISTEN … /var/run/service_control.sock … pid=15585`; socket path built from `global.base_path.unixsocket` = `/var/run/` + `service_control` + `.sock`). NOT a TCP port.
- A thread pool (`custom_thread_pool`, `worker_count=2` in config) accepts client connections and parses JSON requests (`Socket_WaitForEvent`, `Socket_SendResultToClient`; log strings `Connect Client (%d)`, `Client (%d) Recv Data : %s`, `Client (%d) Control Success/Fail: %s`).
- Three control request types (`Control_Service`, `Control_IPSet`, `Control_RebootSystem`):
  - **Service control** — start / stop / restart a module by name. Names come from config `service_control.service_list` (see below). Failure log: `Client (%d) service {start|stop|restart}: no match name (%s)`.
  - **IP set** — `Control_IPSet`: applies IP/DHCP config and runs `systemctl restart network` (strings: `IP Setting Fail`, `DHCP configuration applied for interface %s`, `systemctl restart network`, `Failed to restart network service.`).
  - **Reboot system** — `Control_RebootSystem`.
- `service_control.service_list` (from `mnx_config.json`) — the modules it can control and *how*:
  | key | target | `type` | meaning |
  |-----|--------|--------|---------|
  | `ai_dga` | `/opt/dga_analysis_ai/dga_analysis_ai.py` | `python3.12` | launch via python interpreter |
  | `ai_file` | `/opt/file_analysis_ai/file_analysis_ai.py` | `python3.12` | launch via python interpreter |
  | `payload_analysis` | `/opt/payload_analysis/` | `run` | run dir's start/stop scripts |
  | `scanengine` | `/opt/scanengine/` | `run` | run dir's start/stop scripts |
  | `suricata` | `suricata` | `service` | systemctl-managed unit |
  - **推정(unverified):** the exact dispatch per `type` (`python3.12` vs `run` vs `service`) is inferred from the config schema + `ProcessControl`/`systemctl` strings; the binary is closed-source so the precise command for each type is not line-verified.

### 2.3 Heartbeat + patch + version (outbound to mnxweb, via libcurl)
- `CDaemonMain::HeartbeatModule` / `Thread_Heartbeat` thread. Interval = config `module_heartbeat_interval_second` (=60).
- Endpoints (curl POST to `global.manage_web.core_api_url` = `https://127.0.0.1:8443`, `core_api_cert_verify=false`; heartbeat path `global.manage_web.heartbeat_path` = `/api/server/module/save`):
  - `/api/server/module/save` — module status/heartbeat (payload keys `moduleInfo`, `module_name`, `moduleName`).
  - `/api/server/version/check` — version check (`current_version`, `new_version`).
  - `/api/server/patch/result` — patch result reporting (`patch_result`, `patch_version`, `old_version`; patch staging at `/mnx_patch`, `/tmp/mnx_patch_`, log `Patch Update Call`).
- **Runtime note:** live log `/logs/service_control/service_control.log` shows only `PCAPRawHandler Start/End` every 60 s (20,613 lines). Heartbeat/patch/version calls do not log at info level here, so their actual firing is **推정(unverified)** from binary strings + config, though the mechanism is confirmed present.

### 2.4 PCAP raw post-processing (`PCAPRawHandler`)
- Runs every 60 s (log-confirmed). Driven by config `service_control.pcap_storage_config`: `pcap_raw_postprocess_flag=true`, `dpi_mode="mnx"`, `file_count_key="packetThreads"`, `post_path="/data/raw/"`, `pcap_raw_cycle=4`.
- Moves/symlinks raw PCAP files from the capture pipeline into `/data/raw/` (strings: `PCAP File Move Start/End: %s%s -> %s%s`, `PCAP File symbolic link Create Success`, `No Target PCAP File`). Reads capture INI for `packetThreads`/raw path (`Core INI PCAP Thread Value Get Fail`, `Core INI PCAP Raw Path Value Get Fail`).
- This is the producer of the files that `pcap_delete.py` later prunes (`/data/raw` + `/pipeline/raw` symlinks) — see §7.

---

## 3. `regression_api`

### 3.1 Framework, port, processes
- **Framework:** Python **standard library only** — `http.server.BaseHTTPRequestHandler` + `socketserver.ThreadingMixIn` (`app.py:11,69`). No Flask/FastAPI. JSON hand-encoded.
- **Port 8000 OWNER (confirmed):** `ss -tlnp` → `LISTEN 0.0.0.0:8000 users:(("python3.12",pid=18814…))`; systemd `Main PID 18814`; startup log `Listening on 0.0.0.0:8000`. Bind host/port derived from config `regression_api.api_url` = `http://0.0.0.0:8000` (`app.py:324-327`).
- Process model: 1 HTTP server process (pid 18814) + a **multiprocessing worker pool of 5** (`init_pool(5)` at `app.py:336`; workers pids 18900-18906) fed by a `multiprocessing.Queue` (`worker_pool.py:10-33`). HTTP threads are per-request (ThreadingMixIn, daemon threads).
- Unit `/etc/systemd/system/mnx_regression_api.service`: `Type=simple`, `After=elasticsearch.service`, PID `/var/run/regression_api.pid`, logs to journal (`SyslogIdentifier=regression_api`).
- Live `/health` returned `status 200, pcap_dir_ok/output_dir_ok/suricata_yaml_ok all true, queue_size 0, max_workers 5, elasticsearch_url http://127.0.0.1:9200`.

### 3.2 Endpoints

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| GET | `/health` | `_handle_health` (`app.py:96,113`) | Checks `pcap_dir`, `output_dir`, `suricata_yaml_path` exist; returns queue_size/max_workers/es_url. Always HTTP 200 with internal `status` code (200 / -2 / -9). |
| GET | `/status/{job_id}` | `_handle_status` (`app.py:98,155`) | Globs `output_dir/*/{job_id}/job_status.json`; 404 if none. |
| POST | `/analyze` | `_handle_analyze` (`app.py:106,167`) | Body `{"rule_url": ...}`. Creates job (uuid4 hex), writes QUEUED `job_status.json`, submits to worker pool. Returns `{status, job_id, message}`. |
| POST | `/cancel/{job_id}` | `_handle_cancel` (`app.py:108,250`) | Writes `cancel_flag` file in job root; sets CANCELED (if QUEUED) or requests cancel (if ANALYZING). |
| any | other | — | `404 {"detail":"not found"}` (`app.py:101,111`). |

### 3.3 Purpose / job pipeline (Suricata rule regression)
`suricata_runner.run_job` (`suricata_runner.py:401`) per job:
1. Resolve `suricata` bin, `suricata -V` (`:201`).
2. Download `rule_url` (http/https/**file**; self-signed TLS accepted, `:73-89`) → build a job-specific `suricata.yaml` from base `/etc/suricata/suricata.yaml` by rewriting `default-rule-path` + `rule-files` (`:92-131`).
3. `suricata -T` validate (`:231`).
4. For each `.pcap` in `pcap_dir` (min age 60 s, newest-first, `:49-70`): `suricata -r <pcap> -c job.yaml -l tmp` → append enriched events (adds `mnx_pcap, rule_name, job_id, worker_id`) to `eve.json` (`:134-164`); honour `cancel_flag`.
5. **Session mapping** (`session_mapper.py`): group `alert` events by 5-tuple+date, search ES index `mnx_sessions3-{YYMMDD}` (bidirectional query `:28-65`), merge suricata signature fields into the matched session doc via `_update` (`:190-245`).
6. Compute top-200 signature_id stats, write `summary.json`, mark DONE/FAILED; `tmp_out` always removed (`:516`).
- Job state machine `QUEUED→ANALYZING→DONE|FAILED|CANCELED` (`job_state.py`). On restart, `_recover_stale_jobs` marks stuck ANALYZING/QUEUED jobs FAILED (`app.py:296-311`).

### 3.4 Config keys consumed (`config.py`)
- From `regression_api.*`: `module_name, api_url, suricata_bin, suricata_yaml_path, eve_types` (live: `suricata_yaml_path=/etc/suricata/suricata.yaml`, `eve_types=["alert"]`).
- Derived from `global.base_path` + `global.elasticsearch`: `pcap_dir=/pipeline/raw` (base_path.pcap), `output_dir=/data/regression_api/result` (base_path.data + module + "result"), `log_dir=/logs/regression_api`, `pid_file=/var/run/regression_api.pid`, `elasticsearch_url=http://127.0.0.1:9200`.
- `output_dir`/`log_dir` are created lazily on first request (dirs did not exist at boot; `/logs/regression_api` was created by the `/health` probe during this research).

---

## 4. `server_check.py`

- Path `/opt/server_check/server_check.py`. Cron: **two** entries, `* * * * *` and `* * * * * sleep 30; …`, both `--cpu_interval 5 --hdd_path /data` → effectively samples every ~30 s.
- Metrics via `psutil`: CPU % (`cpu_percent(interval=5)`), memory %, disk % of `/data` (`server_check.py:20-32`).
- **Output sink:** HTTPS POST to **mnxweb `https://127.0.0.1:8443/api/server/status/save`** with `{"hdd","cpu","mem"}` (rounded ints), `verify=False` (`:37-47`). NOT ES, NOT MariaDB directly — it hands metrics to mnx_web, which persists them.
- Logs to `/opt/server_check/log/server_check.log` (TimedRotating, 7-day backup); errors to `/opt/server_check/log/error.log`.
- **`save_server.py`** (sibling): standalone helper that POSTs total mem / total hdd / cpu=0 to `https://localhost:8443/api/server/status/server`. Not referenced by cron or `server_check.py` → run manually only (likely a one-time registration helper). Possibly dead; see §13.

---

## 5. `syslog.py`

- Path `/opt/syslog/syslog.py`. Cron `*/5 * * * * python3.12 /opt/syslog/syslog.py --config /opt/mnx/etc/mnx_config.json`. Short-lived (runs, forwards one 5-min window, exits).
- **Function:** MNX → external SIEM syslog **forwarder** (egress), not an ingest/collector.
- Config via `settings.load_from_config` (`settings.py:33`) reading `syslog.*` + `global.*`:
  - `EXECUTION_INTERVAL=5` min, `SESSIONINFO_SEND_ENABLE=false`, `WORKER_NUM=1`, log `/logs/syslog/` at level `INFO`.
  - `MNX_CORE_API=https://127.0.0.1:8443` (from `global.manage_web.core_api_url`), cert verify false.
  - `ELASTICSEARCH_HOST=http://127.0.0.1:9200` (from `global.elasticsearch.address[0]`).
  - `SYSLOG_SERVER` = only entries with `enable:true`. **Live config: both entries `enable:false` → zero destinations → `syslog.py:388-390` logs "mnx syslog server not set" and `sys.exit(1)`. So in the current install this cron is effectively a no-op.**
- **Inputs:** (a) detections from mnxweb `POST /api/syslog/detect/contents` for the window (`ai_detect`, `playbook_detect`, `network_blackbox_detect`, `malware_file_detect`) (`:236-258, 495-521`); (b) optional session docs from ES `arkime_sessions3-{YYMMDD}` where field `mnx` exists (`:261-304`), only if `SESSIONINFO_SEND_ENABLE` (currently off).
- Destination list fetched from mnxweb `POST /api/syslog/list` (`:30-73`) and merged with config.
- **Output:** RFC6587 octet-counted framing over TCP / TLS, or UDP datagrams (`send_to_server` `:131-233`); PRI computed facility=4 severity=1 (`:492`). TLS supports client cert + CA (`tls_cert/key/ca_path`, default `/path/to/*.pem` placeholders). Reconnect w/ up to 5 retries then aborts.
- Window logic `_compute_window_mnx` (`:468-482`): aligns to interval boundary and processes the *previous* completed interval.
- `mp_manager.py` (23 KB, authored 2017, "Isaac Park") is a generic prefork multiprocessing framework; imported (`syslog.py:22`) but with `WORKER_NUM=1`/`parallel_index=0` the code path is essentially single-process. Largely legacy scaffolding — see §13.

---

## 6. `eng_monitor.sh`

- Path `/data/tools/eng_monitor.sh`. Unit `/etc/systemd/system/eng_monitor.service` — `Requires/After=elasticsearch.service`, `Restart=always`, stdout/err → `/logs/eng_monitor/eng_monitor.log`. Running pid 16120.
- **What it monitors:** despite the name, it monitors **network capture interface throughput**, not a software "engine." Reads `/opt/mnx/etc/config.ini` for `interface=` and `interfaceOps=` (`eng_monitor.sh:16-24`). Live config.ini (ISO-8859 encoded): `interface=ens192`, `interfaceOps=tags=Net-1`, `elasticsearch=http://localhost:9200`.
- **How:** infinite `while true` loop (`:47`): snapshot `/proc/net/dev` bytes+packets for the matched iface, `sleep 1`, snapshot again, compute Mbps (`bytes*8/t/1e6`) and PPS with overflow/reset guards (`:94-110`).
- **Output sink:** ES `_bulk` NDJSON POST to `$es_url/_bulk`, index `net-stats-$(date +%Y%m)` → `net-stats-YYYYMM`, doc `{interface(label), original_interface, mbps, pps, timestamp}` (`:118-134`).
- **Verified live:** log shows `Net-1 (ens192): … Mbps / … PPS` every second; ES has `net-stats-202604..202607` (`net-stats-202607` = 6631 docs). **RISK flag:** every bulk response reports `WARNING: Partial errors in bulk response!` (`:145`) — i.e. some/all docs are being rejected (likely an ES type-mapping conflict on `mbps`/`pps`), yet the script only logs a warning and continues.

---

## 7. Retention tools

### 7.1 `pcap_delete.py` (raw PCAP disk-pressure GC)
- Path `/data/tools/pcap_delete.py`. Cron `*/10 * * * * python3 /data/tools/pcap_delete.py` (every 10 min).
- Hardcoded (`__main__`, `:63-68`): `raw_directory=/data/raw`, `pipeline_raw_directory=/pipeline/raw`, `target_usage=80`.
- **Threshold/logic:** uses **filesystem usage of `/data/raw`** via `shutil.disk_usage` (`:21`). If used% < 80% → no-op. Else deletes files oldest-first by mtime (`:29-34`); for each deleted file it also `unlink`s the same relative path under `/pipeline/raw` (the capture symlink, `:43-54`); re-checks usage after each delete and stops once below 80% (`:56-61`).
- Note: `get_directory_size()` (`:5`) is defined but unused — it measures whole-partition usage, not just the dir.

### 7.2 `payload_delete.sh` (payload age-based GC)
- Path `/data/tools/payload_delete.sh`. Cron `30 3 * * *` — **appears TWICE in crontab** (confirmed `crontab -l | grep -c payload_delete` = 2) → **runs twice at 03:30 daily** (harmless but redundant; likely accidental duplicate).
- **Threshold:** `RETENTION_DAY=1` (`:3`) — delete date-folders whose date is older than `now - 1*86400 s`.
- Paths & structure:
  - `NORMAL_DIRS` = `/data/payload` and `/data/payload/mail_content`, pattern `YYYY/MM/DD` at depth 3 (`:7-45`); old dirs removed via `find "$dir" -delete`.
  - `AI_DIR` = `/data/payload/ai_content`, pattern `<category>/YYYY/MM/DD` at depth 4 (`:53-73`); old dirs removed via `rm -rf`.
- These paths align with `global.base_path`: `payload_binary=/data/payload`, `payload_mail_content=/data/payload/mail_content`, `payload_ai_content=/data/payload/ai_content`.
- **Caveat:** `/data/payload/mail_content` is a subdir of `/data/payload`; scanning both with depth-3 `YYYY/MM/DD` means `mail_content` date-dirs are only matched under the explicit `mail_content` base (its `YYYY/MM/DD` is at depth 4 relative to `/data/payload`, so not double-processed) — behavior is consistent, just worth noting.

---

## 8. Data in/out per service

| Service | Reads | Writes / sends to |
|---------|-------|-------------------|
| service_control | `mnx_config.json`; capture INI (packetThreads/raw path); UNIX-socket JSON requests; `/pipeline` raw PCAPs; patch files `/mnx_patch`,`/tmp/mnx_patch_` | UNIX socket replies; mnxweb `https://127.0.0.1:8443` (`/api/server/module/save`, `/version/check`, `/patch/result`); moves PCAPs → `/data/raw/`; `systemctl restart network`; log `/logs/service_control/service_control.log` |
| regression_api | HTTP requests :8000; `mnx_config.json`; `pcap_dir=/pipeline/raw` PCAPs; rule_url (http/https/file); base `/etc/suricata/suricata.yaml`; ES `mnx_sessions3-*` (read) | `output_dir=/data/regression_api/result/<date>/<job>/` (job_status.json, eve.json, summary.json); ES `mnx_sessions3-*` `_update`; log `/logs/regression_api/regression_api.log` |
| server_check.py | `psutil` (CPU/mem/disk of `/data`) | mnxweb `POST https://127.0.0.1:8443/api/server/status/save`; log `/opt/server_check/log/` |
| syslog.py | mnxweb `/api/syslog/list`,`/api/syslog/detect/contents`; ES `arkime_sessions3-*` (if enabled) | External syslog servers (TCP/TLS/UDP); log `/logs/syslog/syslog.log` |
| eng_monitor.sh | `/opt/mnx/etc/config.ini`; `/proc/net/dev` | ES `net-stats-YYYYMM` `_bulk`; log `/logs/eng_monitor/eng_monitor.log` |
| pcap_delete.py | `/data/raw` fs usage + file mtimes | deletes in `/data/raw` + `/pipeline/raw`; stdout (cron mail) |
| payload_delete.sh | `/data/payload{,/mail_content,/ai_content}` dir dates | deletes old date dirs; stdout (cron mail) |

---

## 9. Threads / processes / IPC

- **service_control:** single daemon process, 4 threads (main; thread-pool workers `worker_count=2`; `Thread_Heartbeat`). **IPC = UNIX stream socket `/var/run/service_control.sock`** (server side). Clients (presumably mnx_web / CLI tools) connect and send JSON control commands. Outbound IPC to mnxweb via HTTPS/libcurl. Controls child modules via process launch / `systemctl`.
- **regression_api:** 1 HTTP process + 5 `multiprocessing.Process` workers; IPC = `multiprocessing.Queue`; per-request daemon threads (ThreadingMixIn). Job coordination via files (`job_status.json`, `cancel_flag`) on disk. SIGTERM handled by spawning a shutdown thread (`app.py:340`).
- **syslog.py:** transient process; `mp_manager` prefork framework imported but effectively single-worker (`WORKER_NUM=1`). Network sockets to syslog servers.
- **eng_monitor.sh:** 1 bash process in a busy loop with 1 s `sleep` + `curl` per second; `awk`/`bc` subprocesses.
- **server_check / pcap_delete / payload_delete:** transient single-process cron invocations, no IPC.

---

## 10. Dependencies

| Service | Hard deps | Soft/among-subsystem |
|---------|-----------|----------------------|
| service_control | mnx_web `:8443` (heartbeat/patch); capture pipeline (`/pipeline`→`/data/raw`); the managed modules in `service_list`; `network` unit | jsoncpp/libcurl (bundled) |
| regression_api | `suricata` binary; `/etc/suricata/suricata.yaml`; Elasticsearch `:9200` (`After=elasticsearch.service`); `pcap_dir` (=`/pipeline/raw`) fed by capture | mnx_config.json |
| server_check.py | mnx_web `:8443`; python `psutil`,`requests` | — |
| syslog.py | mnx_web `:8443` (detect/list); ES `:9200` (session mode); external syslog servers; `requests`,`urllib3` | mp_manager, settings |
| eng_monitor.sh | Elasticsearch `:9200` (`Requires=elasticsearch.service`); `/opt/mnx/etc/config.ini`; capture NIC up | `curl`,`awk`,`bc` |
| pcap_delete.py | `/data/raw` (produced by service_control PCAPRawHandler + capture) | — |
| payload_delete.sh | `/data/payload*` (produced by payload_analysis subsystem) | `date`,`find` |

Shared infra: **mnx_web `https://127.0.0.1:8443`** (service_control, server_check, syslog) and **Elasticsearch `127.0.0.1:9200`** (regression_api, eng_monitor, syslog).

---

## 11. Ports

| Port | Bind | Owner (verified) | Notes |
|------|------|------------------|-------|
| **8000** | `0.0.0.0:8000` (TCP) | **regression_api** — `python3.12` pid 18814 (`ss -tlnp`; systemd Main PID; `Listening on 0.0.0.0:8000`) | Internally reachable REST API; bound to all interfaces (not localhost-only). |
| **44114** | `127.0.0.1:44114` (TCP) | **VS Code Remote server** — `node` pid 23619 (extensionHost, `/root/.vscode-server/.../out/bootstrap-fork --type=extensionHost`) | **NOT service_control.** The task hypothesis is incorrect. This is an IDE/dev artifact and should not exist on a production box. |
| n/a | `/var/run/service_control.sock` (UNIX) | service_control pid 15585 (`ss -xlnp`) | service_control uses a UNIX socket, no TCP port. |

Other UNIX sockets present (owned by sibling subsystems, for context): `/run/mnxdpi.sock`, `/run/payload_ai_analysis.sock`, `/run/payload_scanengine.sock`.

---

## 12. Failure impact & recovery per service

| Service | If it dies | Recovery | Blast radius |
|---------|-----------|----------|--------------|
| service_control | No module start/stop/restart from UI; no heartbeats (web shows modules "down"); **raw PCAPs stop being moved to `/data/raw`** → `/pipeline/raw` backs up | systemd `Restart=on-failure` (5 s). `KillSignal=SIGQUIT`, `TimeoutStopSec=infinity`, `SendSIGKILL=no` → **a hung shutdown can block indefinitely** (no forced kill). | High — orchestration + PCAP retention chain |
| regression_api | Rule-regression API unavailable; in-flight jobs lost | systemd `Restart=on-failure` (5 s); `_recover_stale_jobs` fails stuck jobs on restart | Low/medium — feature service, not on capture data path |
| server_check.py | No host CPU/mem/disk metrics in mnx_web | next cron minute re-runs | Low — monitoring gap only |
| syslog.py | SIEM stops receiving detections/sessions | next 5-min cron re-runs | Low here (no enabled destinations); Medium if SIEM integration active. On send failure retries 5× then aborts the run |
| eng_monitor.sh | No live throughput graph (`net-stats`) | systemd `Restart=always` | Low — dashboard metric only. **Note: bulk writes already partially failing (§6).** |
| pcap_delete.py | `/data/raw` can fill to 100% → capture/DPI write failures | next 10-min cron | **High if disk fills** — silent until full; only guards `/data` fs |
| payload_delete.sh | `/data/payload*` grows unbounded | next daily 03:30 (runs 2×) | Medium — disk growth over days |

---

## 13. Dead / unused assessment

- **Port 44114 / VS Code server (pid 23619, ppid 23570):** dev tooling running as root on the host. Not part of the product. **Recommend removal from production images.**
- **`/opt/service_control/start.sh` + `settings.json`:** not used by systemd; `settings.json` carries a stale config schema (`pcap_raw_path`,`mnxweb_info`) superseded by `mnx_config.json` (`pcap_storage_config`,`manage_web`). Dev/legacy leftover.
- **`/opt/server_check/save_server.py`:** not invoked by cron or `server_check.py`; separate endpoint `/api/server/status/server`. Likely a manual one-shot registration helper — **推정(unverified)** dead in normal operation.
- **`payload_delete.sh` duplicate crontab line:** redundant second run at 03:30 — remove one.
- **`syslog.py` + `mp_manager.py`:** functional but currently inert (all syslog servers `enable:false`); `mp_manager` (2017 prefork lib) is heavy scaffolding effectively unused at `WORKER_NUM=1`.
- **`pcap_delete.py get_directory_size()`:** dead function (defined, never called).
- **`/data/tools` extras** (not in scope but present): `MNX_all_start_service.sh`, `MNX_all_stop_service.sh`, `MNX_status_check.sh`, `es_dynamic_sharding_v2.sh`, `cleanup_es.sh`, `check_*.sh`, `docker_run_*.sh` — operator helper scripts, not wired to systemd/cron (except the retention ones).
- **`net-stats` bulk partial errors (§6):** not dead, but a live latent bug worth fixing.

---

## 14. Cross-references

- **PCAP lifecycle:** capture (`/opt/mnx/bin/capture`) → `/pipeline/raw` → **service_control `PCAPRawHandler`** moves to `/data/raw/` → **regression_api** reads `pcap_dir=/pipeline/raw` for analysis → **pcap_delete.py** GCs `/data/raw`+`/pipeline/raw` at 80%. (See DPI/capture subsystem doc.)
- **ES sessions:** **regression_api** enriches `mnx_sessions3-*` with suricata signatures; **syslog.py** reads `arkime_sessions3-*`. (See Elasticsearch/indexing subsystem doc.)
- **mnx_web `:8443`** is the control-plane hub for service_control heartbeats, server_check metrics, and syslog detection pulls. (See mnx_web / core-API subsystem doc — `/mnxmc`, `main-login.py`, `app.jar`.)
- **service_control `service_list`** modules (dga_analysis_ai, file_analysis_ai, payload_analysis, scanengine, suricata) are documented in the AI-analysis / payload subsystem docs.
- **Config:** all services key off `/opt/mnx/etc/mnx_config.json` `global.base_path` + `global.{elasticsearch,manage_web}`; eng_monitor + capture use `/opt/mnx/etc/config.ini` (Arkime/MNX-style, ISO-8859).

---

### Appendix — evidence commands run
`systemctl status {mnx_service_control,mnx_regression_api,eng_monitor}`, `crontab -l`, `ps aux`, `ss -tlnp`/`ss -xlnp`, `strings -n service_control`, `curl :8000/health`, `curl :9200/_cat/indices/net-stats*`, `python3 -c "json.load(mnx_config.json)"`, plus `Read` of all Python/shell sources listed above.
