# 04 · Payload Analysis / File AI / AV Scan Subsystem

> Formal architecture handover research. Every claim cites `file:line` or a
> command output. Items that could not be fully verified are marked
> **추정(unverified)**. Host inspected: `sands-test`, date 2026-07-10.

---

## 1. Overview

This subsystem takes files/payloads reassembled from captured network traffic and
enriches them with three analyzers before indexing verdicts to Elasticsearch:

| # | Service (systemd unit) | Binary/entry | enabled? | active now? | Role |
|---|---|---|---|---|---|
| 1 | `mnx_payload.service` | `/opt/payload_analysis/payload_analysis` (ELF) | **enabled** | **active (PID 17833)** | Orchestrator: consumes Kafka jobs, reassembles/reads payload files, YARA file-typing, fans out to AI + AV + DGA, writes ES |
| 2 | `mnx_payload_ai.service` | `python3.12 /opt/file_analysis_ai/file_analysis_ai.py … start` | disabled | **active (PID 16936 + workers)** | ML file-malware classifier (per file-type models) over a UNIX socket |
| 3 | `mnx_payload_scan.service` | `/opt/scanengine/scanengine_bitdefender` (ELF) | disabled | **active (PID 16374)** | BitDefender AV signature scan over a UNIX socket |

### Are the two "disabled" services dead / optional? — **No, they are live dependencies.**

Despite `systemctl is-enabled` returning `disabled` for services 2 and 3, **both
are running right now** (`ps aux` shows PIDs 16374 and 16936+16 workers). The
reason is in the unit file: `/etc/systemd/system/mnx_payload.service` declares

```
Requires=mnx_payload_ai.service
After=mnx_payload_ai.service
Requires=mnx_payload_scan.service
After=mnx_payload_scan.service
```

(verified — unit file printed in research). `mnx_payload.service` **is** enabled
(`WantedBy=multi-user.target`), so at boot systemd pulls in the two `Requires=`
units even though they are not independently enabled. They are therefore
**mandatory runtime dependencies of the payload pipeline, not dead code**. A
second, redundant supervisor also knows them: `service_control` config lists
`ai_file` → `/opt/file_analysis_ai/file_analysis_ai.py` and `scanengine` →
`/opt/scanengine/` in its `service_list` (config `service_control.service_list`).

All three log actively under `/logs/{payload_analysis,payload_ai_analysis,payload_scanengine}/`
with fresh timestamps (10:11–10:39 on inspection day), and the orchestrator emits
`Heartbeat Call` every 60 s (`/logs/payload_analysis/payload_analysis.log`).

**Verdict:** subsystem is fully alive and load-bearing. The "disabled" flag is a
deploy convention (start via the parent's `Requires=`), *not* a sign of dead code.

---

## 2. payload_analysis (orchestrator)

### Type & launch
- **Binary:** `ELF 64-bit LSB pie executable, x86-64 … not stripped` with
  `debug_info` (`file` output). C++ (mangled symbols, `/root/projects/payload_analysis/…`).
  Size 3.3 MB. **Not a script.**
- **Launch:** `mnx_payload.service`, `Type=forking`, `ExecStartPre=/bin/sleep 10`,
  `ExecStart=/opt/payload_analysis/payload_analysis -d -c /opt/mnx/etc/mnx_config.json`,
  `PIDFile=/run/payload_analysis.pid`, `KillSignal=SIGQUIT`, `Restart=on-failure`,
  `TimeoutStopSec=infinity`, runs as root.
- `-d` = daemonize (double-fork; log shows `Child Process : [17833] - Parent Process : [17832]`).
  `-c` = config path. Manual `start.sh`/`stop.sh` exist (`stop.sh` sends `kill -3`
  = SIGQUIT to the PID file).
- **Why `sleep 10`:** the unit `Requires=` Elasticsearch, Kafka, and the AI + scan
  services (all `After=`). The 10 s pre-start delay gives those dependencies —
  especially the two socket servers and Kafka broker — time to finish binding
  their sockets/topics before the orchestrator tries to connect. **추정(unverified)**
  as to the exact race, but the ordering + sleep strongly implies dependency warm-up.

### What it does (I/O)
Confirmed via `strings` + config:

1. **Input = Kafka consumer.** Links `librdkafka.so.1` (`ldd`). Config
   `global.kafka` = `{address:"127.0.0.1:9092", payload_config:{enable:true,
   payload_analysis_topic:"request-file-analysis", payload_analysis_groupname:"mnx"}}`.
   Log strings: `queue (topic %s, group %s) connect success`, `queue (topic %s) get job: %s`.
   The producer of `request-file-analysis` is the DPI/capture engine (`mnxdpi`);
   payload_analysis is the **consumer**. (Note: a legacy default topic string
   `payload_analysis_topic` is also compiled in.)
2. **Reads payload files from disk.** `global.base_path.payload_binary=/data/payload`,
   `payload_mail_content=/data/payload/mail_content`, `payload_ai_content=/data/payload/ai_content`.
   Binary strings: `make_payload_path`, `payload_binary`, `Payload_CacheDIr_Delete`,
   `copyPayload/dupPayload/releasePayload`. `/data/payload/2026/…` (dated tree)
   confirmed on disk. The DPI engine writes the reassembled payload bytes here;
   the Kafka message carries metadata/path, the file bytes are read from `/data/payload`.
   **추정(unverified):** exact split of "bytes in Kafka msg vs. path reference" —
   directory layout `YYYY/MM/DD` + `make_payload_path` indicates path-based handoff.
3. **File typing = YARA.** Links `libyara.so.10` (`ldd`); loads
   `/opt/payload_analysis/file_type.yar` (string `/file_type.yar`,
   `MNX v23 AI, YARA Detector`, `~CYaraWrapper`). `file_type.yar` classifies by
   magic bytes into EXE/DLL/ELF/SO/HWP/DOC/PPT/XLS/APK/XLSX/DOCX/PPTX/HWPX/ZIP/PDF/
   GZIP/7Z/RAR/RAR5/TAR/BZIP2/XZ/ZSTD/LZ4/CAB/ISO. Unsupported types →
   `File Process Payload File Type Unsupport`. Also loads user YARA from
   `custom_rule_path=/data/custom-rule/yara`.
4. **Fan-out to analyzers (UNIX sockets):**
   - AI: config `payload_analysis.ai_analysis_socket_path=/var/run/payload_ai_analysis.sock`
   - AV: config `payload_analysis.scanengine=[{bitdefender:"/var/run/payload_scanengine.sock"}]`
   - DGA: `dga_analysis_socket_path=""` and `dga_analysis_flag=false` → **DGA disabled**.
5. **AI-content / ChatGPT handling.** `ai_content_flag=true`, `ai_content_list` with
   `ai_service:"ChatGPT"` over `http2_metadata/http_metadata`. Binary has
   `ai_contents_chatgpt_group_conversations`, `ai_contents_chatgpt_analysis` —
   it reconstructs ChatGPT conversation turns from captured HTTP/2 traffic.
6. **Output = Elasticsearch.** Links `libcurl`/`libssl`; `CElasticsearchWrapper`.
   Config `global.elasticsearch` = `127.0.0.1:9200`, indices
   `index_file_analysis_prefix="payload_"`, `index_ai_content_prefix="ai_content-"`,
   `index_mail_content_prefix="mail_content-"`. Also fires "AI Insight" alerts
   (strings `AI Insight Alarm Malware Detect`, `AI Insight DGA Detect Send`) gated
   by `aiinsight_alarm_flag{ai,av,yara,dga}` (all currently **false** in config).

### Key config keys (`payload_analysis` section)
`worker_count:8`, `subworker_count:2`, `module_heartbeat_interval_second:60`,
`payload_list:[http_payload,http2_payload,ftp_payload,mail_payload,smb_payload]`,
`mail_body_content_flag:true`, `ai_content_flag:true`, `ai_analysis_socket_path`,
`scanengine[].bitdefender`, `dga_analysis_flag:false`, `dga_analysis_result_path:/data/dga_result/`,
`custom_rule_path:/data/custom-rule/yara`, `aiinsight_alarm_flag{ai:false,av:false,yara:false,dga:false}`.

---

## 3. file_analysis_ai (ML file-malware classifier)

### Framework & model
- **Language:** Python 3.12. Entry `file_analysis_ai.py`; helper modules
  `daemon.py` (double-fork daemon), `mp_manager.py` (custom multiprocessing pool,
  authored 2017 by "Isaac Park", v0.3.0), `settings.py` (config loader).
- **ML library:** the classification lives in the **`filekit`** package
  (`/usr/local/lib/python3.12/dist-packages/filekit`) + its dep `modelcore`.
  `filekit` imports **xgboost, scikit-learn, joblib, numpy** (grep counts:
  xgboost×12, sklearn×9, numpy×24). `basekit` also imports **treelite**.
  Per-model `metadata.yaml`:
  - `model/exe/metadata.yaml`: `algorithm: XGBClassifier`, 120 features, artifacts
    `model.json` (XGBoost, 139 MB) + `model.tl` (treelite compiled, 164 MB),
    labels `{0:normal, 1:malware}`, `requirement.xgboost: 2.0.3`.
  - `model/pdf/metadata.yaml`: `algorithm: RandomForestClassifier` (sklearn 1.4.0),
    91 features, `model.pkl` (420 MB) + `model.tl` (519 MB).
- **torch present but CPU-only.** The main process shows as `pt_main_thread`
  (PyTorch renames the main thread on import), and `torch 2.4.1` is installed;
  `modelcore/alg/classification/{mlp,bigru}.py` import torch. `torch.cuda.is_available()`
  returned **False** — **runs on CPU** (no GPU on host). The file-malware models
  in use are tree-based (XGBoost/RF), not torch; torch is pulled in transitively
  via `modelcore`. **추정(unverified):** whether any active file-type model uses a
  torch `.pt` artifact — none of the 10 model dirs show `.pt` files (all `.json`/`.pkl`/`.tl`).

### Model coverage (2.1 GB total under `/opt/file_analysis_ai/model/`)
`ai_model_list` (config `payload_ai_analysis.ai_model_list`) = **EXE, DLL, PDF, HWP,
DOC, DOCX, XLS, XLSX, PPT, PPTX**. Dir sizes: pdf 896M, exe 289M, dll 289M, xls 212M,
docx 168M, doc 121M, xlsx 113M, pptx 22M, ppt 15M, hwp 4M. `filekit/kit` also ships
apk/elf/html/js/od/rtf/hwpx kits (loaded dynamically) but only the 10 above have
deployed models. **These are file-type-specific MALWARE classifiers (binary
normal/malware) — not a DGA model and not a generic file-type identifier** (typing
is done upstream by YARA in payload_analysis).

### I/O contract (verified in `file_analysis_ai.py`)
- **Server:** `AF_UNIX` `SOCK_STREAM` at `/var/run/payload_ai_analysis.sock`
  (module_name `payload_ai_analysis`, `PID_DIR=/var/run`) — file exists, owned by
  PID 16936. Accept loop with 2 s timeout (`file_analysis_ai.py:211-243`).
- **Request:** JSON `{"file_type": "...", "file_path": "..."}` (`:100-103`).
- **Processing:** lazily instantiates the matching `filekit.<Type>MalwareDetector`,
  `model.load(model_path)`, `model.predict_detail(file_path)`, maps class →
  `get_class_name` (`:107-157`).
- **Response:** JSON `{"label": <normal|malware|none>, "score": <float rounded 2, -1 on error>}`
  (`:159-181`), then closes the connection.

### Concurrency
Prefork pool via `MP_MANAGER(mode="PREFORK")`, `worker_count` from config = **16**
(`payload_ai_analysis.worker_count`; `settings.WORKER_NUM` default 16). Workers
restart after `worker_reuse_num=1000` jobs or `worker_timeout=3600 s`
(memory-leak guard). `ps aux` confirms 1 parent + 16 workers. Logs to
`/logs/payload_ai_analysis/payload_ai_analysis.log` (config `log_level: INFO`).

### /data/dga_result
Empty (`/data/dga_result/` has no files). It belongs to a **separate** DGA service,
not this one. `service_control.service_list.ai_dga` →
`/opt/dga_analysis_ai/dga_analysis_ai.py`, but **`/opt/dga_analysis_ai/` does not
exist on this host** and `dga_analysis_flag=false`. So DGA is configured-but-not-deployed;
`file_analysis_ai` never touches `/data/dga_result`. See §10/§11.

---

## 4. scanengine_bitdefender (AV scan)

### Type & role
- **Binary:** `ELF 64-bit LSB pie executable … not stripped`, C++ (symbols
  `/root/projects/scanengine_bitdefender/…`, `CDaemonMain`). 1.6 MB. **Not a script.**
- Wraps the **BitDefender ThreatScanner SDK**. Symbols:
  `ThreatScanner_CreateInstance`, `ThreatScanner_InitializeEx`,
  `ThreatScanner_ScanObject`, `ThreatScanner_SetIntOption`,
  `ThreatScanner_Uninitialize`. Links `/opt/scanengine/lib/libbdscan.so` (`ldd`).

### Launch
`mnx_payload_scan.service`:
`ExecStart=/opt/scanengine/scanengine_bitdefender -d -c /opt/mnx/etc/mnx_config.json`
(`-d` daemonize, `-c` config). Note `start.sh` uses a *different, stale* invocation
`-c start -s /opt/scanengine/settings.json` (no such `settings.json` exists) — the
**systemd path (`-c mnx_config.json`) is authoritative**; `start.sh` is legacy/manual.

### Engine, patterns, license
- **Engine core:** `Update1/bdcore.so`, `Update2/bdcore.so` (the loadable BD engine),
  plus `lib/{libbdscan.so, libbdquar.so (quarantine), libbdupdatesdk.so}`.
- **Signatures:** `Update1/Plugins/` and `Update2/Plugins/` hold `emalware.*`,
  `e_spyw.*`, `amml.cvd`, `hpe.cvd`, `pwshtok.cvd`, etc. + `versions.dat` /
  `versions.id` manifests. Active pattern set is selected by
  `/opt/scanengine/pattern_path.conf` = `./Update2` (relative to the working dir).
  Two update slots (Update1 562M / Update2 251M) support A/B hot-swap; binary logs
  `BitdefenderUpdateChecker`, `Bitdefender Reinit Scan Task Complete` (re-inits on
  pattern change). Total dir 818 MB.
- **Updater:** `/opt/scanengine/updater_bitdefender` (33 KB ELF), run by cron
  `/etc/cron.d/avupdate`: `0 */4 * * * root /opt/scanengine/updater_bitdefender`
  (every 4 hours). Uses `libbdupdatesdk.so`.
- **License:** no license file surfaced in the dir listing; **추정(unverified)** —
  likely embedded in `bdcore`/update SDK or fetched at update time.

### I/O contract
- **Server:** `AF_UNIX` at `/var/run/payload_scanengine.sock` (config
  `payload_analysis.scanengine[].bitdefender`; socket confirmed listening,
  PID 16374). `worker_count=16` (config `payload_scanengine.worker_count`).
- Receives a scan request (file path) from payload_analysis, calls
  `ThreatScanner_ScanObject`, returns a scan status/verdict
  (`ServiceWorkerThread client send scan result`, `ConvertScanStatusToString`,
  `scanStatus`, `SCAN FAILED`). Logs `/logs/payload_scanengine/`.

---

## 5. Data flow across the three services

```
   Network capture (mnxdpi / DPI engine)
        │  reassembles payloads, writes bytes →
        ▼
  /data/payload/<YYYY/MM/DD>/…            Kafka topic "request-file-analysis"
  (+ /mail_content, /ai_content)          (broker 127.0.0.1:9092, group "mnx")
        │                                      │  (job/metadata)
        └──────────────┬───────────────────────┘
                       ▼
        ┌───────────────────────────────────────────┐
        │  payload_analysis  (PID 17833, ENABLED)     │
        │  1. consume Kafka job                       │
        │  2. read payload file from /data/payload    │
        │  3. YARA file-type (file_type.yar)          │
        │     + custom YARA (/data/custom-rule/yara)  │
        │  4. fan-out ↓↓↓  (only supported types)     │
        └───────┬───────────────┬───────────────┬─────┘
                │ UNIX sock      │ UNIX sock     │ (disabled)
                ▼                ▼               ▼
   payload_ai_analysis   payload_scanengine   [DGA] dga_analysis_socket_path=""
   .sock (PID 16936)     .sock (PID 16374)    dga_analysis_flag=false → skipped
   {file_type,file_path} (BitDefender scan)   → /data/dga_result (empty)
   → {label,score}       → {scanStatus}
                │                │
                └───────┬────────┘
                        ▼
     payload_analysis merges verdicts (+ ChatGPT ai_content reconstruction)
                        ▼
     Elasticsearch @127.0.0.1:9200  indices: payload_* , ai_content-* , mail_content-*
                        │
                        └─ optional "AI Insight" alerts (aiinsight_alarm_flag = all false now)
```

`payload_list` scanned: http, http2, ftp, mail, smb payloads. Mail bodies →
`mail_content-*`; ChatGPT/LLM conversations → `ai_content-*`.

---

## 6. Threads / processes / IPC

- **payload_analysis:** single daemon process (PID 17833), 17 tasks (threads).
  Uses a lock-free `moodycamel::ConcurrentQueue` + `custom_thread_pool.cpp`
  thread pool. `worker_count=8`, `subworker_count=2` (config). Threads: Kafka
  consumer, ES writer, YARA, socket clients to AI/AV, heartbeat.
- **file_analysis_ai:** 1 parent (`pt_main_thread`) + **16 prefork worker
  processes** (`multiprocessing`); parent = UNIX-socket accept loop that hands the
  connection object into an `in_q` `multiprocessing.Queue`; workers `recv`/`predict`/
  `sendall`. Worker recycle at 1000 jobs / 3600 s.
- **scanengine_bitdefender:** single daemon (PID 16374), 19 tasks, custom thread
  pool, `worker_count=16`.
- **IPC:**
  - Kafka (TCP 9092) — job ingress to payload_analysis.
  - Elasticsearch (TCP 9200, HTTP via libcurl) — verdict egress.
  - UNIX domain sockets `/var/run/payload_ai_analysis.sock`,
    `/var/run/payload_scanengine.sock` — synchronous request/response
    (payload_analysis is client; AI & AV are servers). JSON framing on the AI socket.
  - Filesystem `/data/payload/**` — bulk payload bytes handoff from DPI.
  - Also present: `/var/run/mnxdpi.sock`, `/var/run/service_control.sock` (adjacent
    subsystems, see §12).

---

## 7. Dependencies

**payload_analysis (shared libs, `ldd`):** `librdkafka.so.1` (Kafka),
`libcurl.so.4` + `libssl.so.3` (ES/HTTP), `libyara.so.10` (`/usr/local/lib`,
YARA file typing + custom rules). Plus JSON (jsoncpp, per symbols).

**file_analysis_ai (Python 3.12 pkgs):** `filekit` (in-house) + `modelcore`
(in-house), `xgboost 2.0.3`, `scikit-learn 1.4.0`, `treelite`, `joblib 1.4.2`,
`numpy 1.26.4`, `torch 2.4.1` (transitive via modelcore, CPU), `pefile` (PE
parsing), `onnxruntime 1.23.2` + `lightgbm 4.5.0` (installed, not confirmed used
by active models). Model artifacts (2.1 GB) under `/opt/file_analysis_ai/model/`.

**scanengine_bitdefender:** `libbdscan.so` (linked), `libbdquar.so`,
`libbdupdatesdk.so`, `Update{1,2}/bdcore.so` (BD engine), signature plugins
(`*.cvd`, `emalware.*`). `libdl` for dynamic engine load.

---

## 8. Ports & sockets

| Endpoint | Type | Owner | Notes |
|---|---|---|---|
| `127.0.0.1:9092` | TCP (client) | payload_analysis | Kafka broker, topic `request-file-analysis` |
| `127.0.0.1:9200` | TCP (client) | payload_analysis | Elasticsearch |
| `/var/run/payload_ai_analysis.sock` | UNIX (server) | file_analysis_ai | listening (PID 16936) |
| `/var/run/payload_scanengine.sock` | UNIX (server) | scanengine_bitdefender | listening (PID 16374) |

**No listening TCP port is opened by any of the three services** (the only
`0.0.0.0:8000` LISTEN belongs to an unrelated `python3.12` PID 18814 — likely a web/API,
not this subsystem). AI & AV expose UNIX sockets only.

---

## 9. Failure impact

- **payload_analysis down:** the whole file/payload enrichment pipeline stops.
  Kafka jobs for `request-file-analysis` back up (consumer group `mnx` lags);
  no `payload_*` / `ai_content-*` / `mail_content-*` documents are written to ES;
  no AV/AI/YARA verdicts or AI-Insight alerts. `Restart=on-failure`, `RestartSec=5`
  gives auto-recovery. Highest-impact of the three.
- **file_analysis_ai down:** ML malware verdict unavailable. payload_analysis'
  socket `connect`/`recv` will fail/timeout; **추정(unverified)** whether it
  degrades gracefully (skips AI, still writes YARA+AV) or blocks — code path not
  in these files. Because `mnx_payload.service` `Requires=mnx_payload_ai.service`,
  a hard stop of the AI unit would also stop payload_analysis under systemd.
- **scanengine down:** same coupling (`Requires=mnx_payload_scan.service`) — AV
  verdict lost; stopping the scan unit tears down the orchestrator too.
- **Kafka or ES down:** unit `Requires=kafka.service` / `elasticsearch.service`;
  no jobs consumed / no output persisted.
- **Coupling risk:** the `Requires=` (not `Wants=`) on both analyzers means the
  three services are a single fate-shared unit — restarting/failing either leaf
  cascades to the orchestrator.

---

## 10. Retention / cleanup

- **`/data/tools/payload_delete.sh`** — cron `30 3 * * * /data/tools/payload_delete.sh`
  (in `/var/spool/cron/crontabs/root`; the entry appears **twice** — duplicate).
  `RETENTION_DAY=1`. Deletes date-partitioned dirs older than 1 day:
  - `/data/payload/<YYYY/MM/DD>` and `/data/payload/mail_content/<YYYY/MM/DD>`
    (depth-3 `YYYY/MM/DD`, `find … -delete`).
  - `/data/payload/ai_content/<category>/<YYYY/MM/DD>` (depth-4, `rm -rf`).
  So captured payload bodies are kept only **1 day** on disk (verdicts persist in
  ES per that index's own retention). `/data/payload/2026/...` exists on disk.
- **`/data/dga_result/`** — declared retention target (`dga_analysis_result_path`)
  but currently **empty**, and **not covered by `payload_delete.sh`** (script only
  touches `/data/payload*`). Since DGA is disabled and its service dir is absent,
  no cleanup is needed today; **if DGA is ever enabled, `/data/dga_result` has no
  retention job — potential unbounded growth (risk).**
- **AV signatures:** `updater_bitdefender` via `/etc/cron.d/avupdate` every 4 h
  (not a deletion job; refreshes `Update1/Update2`).

---

## 11. Dead / unused assessment

- **payload_analysis, file_analysis_ai, scanengine_bitdefender: LIVE** — all
  running, logging, and wired via `Requires=`. Not dead.
- **DGA path: configured but NOT deployed / disabled.** `dga_analysis_flag=false`,
  `dga_analysis_socket_path=""`, the referenced service
  `/opt/dga_analysis_ai/dga_analysis_ai.py` (`service_control.ai_dga`) **does not
  exist on this host**, and `/data/dga_result` is empty. DGA is dormant. Binary
  strings (`AI_DGA_Detect`, `DGA Process Prediction…`) show the code path is
  compiled in but never exercised with current config.
- **`start.sh` for scanengine is stale** — points to a non-existent
  `/opt/scanengine/settings.json` with old args; only the systemd invocation works.
- **Extra `filekit` kits (apk/elf/html/js/od/rtf/hwpx)** ship in the library but
  have **no deployed models** (only the 10 in `ai_model_list`) — latent capability,
  not used.
- **Unused-but-installed ML libs:** `onnxruntime`, `lightgbm`, and torch/GPU
  paths are present but the active file-malware models are XGBoost/RandomForest on
  CPU. **추정(unverified):** they may serve other model types (e.g. bigru/mlp in
  modelcore, or the DGA model) not active here.
- **Duplicate cron entry** for `payload_delete.sh` (harmless but sloppy).

---

## 12. Cross-references

- **Capture / DPI (`mnxdpi`)** — upstream producer. Writes reassembled payloads to
  `/data/payload` (`base_path.payload_binary`) and enqueues Kafka
  `request-file-analysis`. `mnxdpi` config `payload_match_timeout_ms`;
  `/var/run/mnxdpi.sock` present. `service_control.pcap_storage_config.post_path=/data/raw/`,
  `dpi_mode:"mnx"`. → see the capture/DPI subsystem doc.
- **Kafka** — `global.kafka` broker `127.0.0.1:9092`; only topic used here is
  `request-file-analysis` (group `mnx`). → messaging subsystem doc.
- **Elasticsearch** — `global.elasticsearch` `127.0.0.1:9200`; this subsystem owns
  indices `payload_*`, `ai_content-*`, `mail_content-*` (also `mnx_sessions3*` used
  by DPI). → ES/storage subsystem doc.
- **service_control** (`/var/run/service_control.sock`) — supervisor whose
  `service_list` includes `ai_file`, `scanengine`, `payload_analysis` (`type:"run"`),
  `ai_dga`, and `suricata`. Overlaps with systemd management of these units.
- **Web / manage_web** — `global.manage_web`; "AI Insight" alerts
  (`aiinsight_alarm_flag`) feed the management UI/alerting (all flags false now).
- **DGA AI service** (`/opt/dga_analysis_ai/`, not present) — would be the consumer
  of the DGA socket and writer of `/data/dga_result`. → separate/future subsystem.

---

### Appendix — quick evidence index
- Unit files: `/etc/systemd/system/mnx_payload.service` (Requires AI+scan+kafka+es).
- Config: `/opt/mnx/etc/mnx_config.json` → sections `global` (kafka/elasticsearch/
  base_path), `payload_analysis`, `payload_ai_analysis`, `payload_scanengine`,
  `service_control`.
- Code read in full: `/opt/file_analysis_ai/{file_analysis_ai.py,settings.py,daemon.py,mp_manager.py}`.
- Model metadata: `/opt/file_analysis_ai/model/{exe,pdf}/metadata.yaml`.
- ML lib: `/usr/local/lib/python3.12/dist-packages/filekit/` (+ `modelcore`).
- YARA: `/opt/payload_analysis/file_type.yar`.
- Cleanup: `/data/tools/payload_delete.sh`, crontab, `/etc/cron.d/avupdate`.
- AV engine: `/opt/scanengine/{lib/*.so, Update1, Update2, pattern_path.conf, updater_bitdefender}`.
