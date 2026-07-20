# 03 · DPI Engine (mnxdpi) + Suricata IDS — Architecture Handover

Subsystem research for the MNX NDR product. Every claim is grounded in observed
code/config/runtime state with `file:line` or the exact command used. Items that
could not be proven from evidence are marked **추정(unverified)**.

Host: `sands-test` · Date of capture: 2026-07-10 (~10:11–10:43 KST) · Suricata 8.0.4.

---

## 1. Overview

| Component | Binary / unit | systemd state | Runtime state | Role |
|-----------|---------------|---------------|---------------|------|
| **mnxdpi** | `/opt/mnxdpi/mnxdpi` | `mnxdpi.service` — **disabled** | **active (running)**, PID 18076, 8.3 GB RSS, 29 threads | Offline (file-based) Deep Packet Inspection engine. Reads captured pcap files, classifies sessions/applications with the PACE2 DPI library, writes session records to Elasticsearch and pushes file/payload-analysis jobs to Kafka. |
| **suricata** | `/usr/bin/suricata` | `suricata.service` — **enabled** | **active (running)**, PID 18585, ~325 MB RSS, 17 threads | Signature IDS. Sniffs the monitoring NIC live via AF_PACKET, matches SANDS rule sets, writes alerts to `eve.json`/`fast.log`. |

Supporting context (adjacent subsystems, needed to explain the pipeline):
- **capture** (`/opt/mnx/bin/capture`, PID 18353, user `nobody`) — a rebranded
  **Arkime/Moloch** packet-capture daemon. Live-sniffs `ens192`, writes rolling
  3 GB pcap files, and indexes session metadata into Elasticsearch. Evidence:
  `httpRealm=Moloch` in `/opt/mnx/etc/config.ini:` and Moloch-style keys; process
  line `/opt/mnx/bin/capture -c /opt/mnx/etc/config.ini`.
- **service_control**, **payload_analysis**, **payload_scanengine**,
  **payload_ai_analysis**, **regression_api**, **syslog** — MNX modules configured
  in `/opt/mnx/etc/mnx_config.json` (downstream of DPI; touched only where relevant).

Both DPI and Suricata are **live and important**: Suricata is the real-time
detection path; mnxdpi is the enrichment/DPI path. See §11 for why "disabled" does
**not** mean mnxdpi is dead.

Status evidence:
```
# systemctl status mnxdpi   -> Loaded: ...; disabled;  Active: active (running) since 2026-07-10 10:11:24
#   Main PID: 18076 (mnxdpi)  Memory: 8.3G  Tasks: 29
# systemctl status suricata -> Loaded: ...; enabled;   Active: active (running) since 2026-07-10 10:11:24
#   Main PID: 18585 (Suricata-Main)  Memory: 325.3M  Tasks: 17
# ps aux:
#   root 18076 /opt/mnxdpi/mnxdpi -c /opt/mnx/etc/mnx_config.json -s
#   suricata 18585 /usr/bin/suricata --af-packet -c /etc/suricata/suricata.yaml --pidfile /run/suricata.pid --user suricata --group suricata
```

---

## 2. mnxdpi binary

### 2.1 Type / size
`file /opt/mnxdpi/mnxdpi`:
```
ELF 64-bit LSB pie executable, x86-64, dynamically linked,
interpreter /lib64/ld-linux-x86-64.so.2, BuildID[sha1]=58ece0d4..., for GNU/Linux 3.2.0, stripped
```
`ls -la /opt/mnxdpi/`:
- `mnxdpi` — 15,437,152 bytes (~15 MB), stripped, dated Apr 20 13:22.
- `mnxdpi.debug` — 59,688,896 bytes (~57 MB) separated debug symbols (not stripped).
- `storcli.log` — unrelated storage-controller log (14 KB).

The "~72 MB" in the brief = stripped binary (15 MB) + `.debug` (57 MB) together.

### 2.2 Launch / options
systemd unit `/etc/systemd/system/mnxdpi.service`:
```
ExecStart=/opt/mnxdpi/mnxdpi -c /opt/mnx/etc/mnx_config.json -s
ExecStop=/opt/mnxdpi/mnxdpi -c /opt/mnx/etc/mnx_config.json -K
ExecStopPost=/bin/rm -f /run/mnxdpi.pid
WorkingDirectory=/opt/mnxdpi  · User/Group=root · Restart=on-failure · RestartSec=5s
LimitNOFILE=524288 · MALLOC_ARENA_MAX=32, MALLOC_TRIM/MMAP_THRESHOLD_=131072
Requires=elasticsearch.service, kafka.service  (After= both)
```
Option meanings, from the binary's own usage strings (`strings /opt/mnxdpi/mnxdpi`):
```
%s [options]
  -s : silent mode
  -K : stop service
```
- `-c <file>` — config file path (`config file(%s) may be corrupted`, `use -K option`).
- `-s` — silent mode (suppresses console; the daemon still logs to file — see §3 logger).
- `-K` — stop the running service (talks to the control socket; see §9).

Note: an embedded string references a legacy path — `ExecStop=/root/mnxdpi/mnxdpi
-c /root/mnxdpi/config.json -K` — i.e. an older packaging. **추정**: benign leftover.

### 2.3 Embedded engine & evidence (strings)
- **PACE2 DPI engine** (Rohde & Schwarz / ipoque): thousands of protocol-attribute
  strings plus enum tokens `PACE2_PROTOCOL_KAFKA`, `PACE2_APPLICATION_BOOTSTRAPCDN`.
  This is the classification core (application/protocol identification).
- **PcapPlusPlus** (`pcpp`) for packet parsing: symbols `N4pcpp10IPv4OptionE`,
  `N4pcpp17IPv4OptionBuilderE`, `pcpp::TLVRecordReader...`.
- **libpcap** for reading pcap files (linked, see §8).
- **librdkafka++** Kafka producer: `N6mnxdpi5KafkaE`, `RdKafka::Producer::create`,
  `Kafka conf set bootstrap.server error(%s)`, `Kafka create producer error(%s)`,
  `message delivered topic(%s)[%d] offset(%ld)`.
- **Elasticsearch bulk client** over libcurl: `/_bulk`, and the consumer thread
  strings `[MAIN] elasticsearch bulk thread init fail`, `elasticsearch_consumer: ...
  broker=%s`, `[STAT] ... elasticsearch: pending_items=%s, pending_bytes=%s`.
- **moodycamel::ConcurrentQueue** work queues keyed by internal types
  **`pcapfile_work_item`** and **`_MNX_SESSION_PROCESS`** — direct proof the daemon's
  unit of work is a *pcap file* and a *session*, i.e. it processes files, not a
  live NIC.
- Content/mail handling: EUC-KR→UTF-8 fallback conversion strings; HTTP multipart.

No DPDK and no `af_packet`/live-interface strings were found — consistent with a
file-reading design.

---

## 3. mnxdpi configuration (`/opt/mnx/etc/mnx_config.json`)

Top-level keys: `config_version` (`2026041001`), `global`, `mnxdpi`,
`payload_analysis`, `payload_scanengine`, `payload_ai_analysis`, `service_control`,
`regression_api`, `syslog`.

### 3.1 `global` (shared by all modules)
- `base_path`: `data=/data`, `log=/logs`, `pcap=/pipeline/raw`,
  `dpi_workspace=/dir_cache`, `payload_binary=/data/payload`, `pid=/var/run/`,
  `unixsocket=/var/run/`.
- `elasticsearch`: `address=["127.0.0.1:9200"]`, `tls=false`, no auth,
  `incex_session_prefix="mnx_sessions3"` (session index prefix — note the typo
  "incex"), `index_file_analysis_prefix="payload_"`, `index_ai_content_prefix`,
  `index_mail_content_prefix`, `Index_refresh_time=60`.
- `kafka`: `address="127.0.0.1:9092"`; `payload_config.enable=true`,
  `payload_analysis_topic="request-file-analysis"`, group `mnx`.
- `manage_web`: `core_api_url=https://127.0.0.1:8443`,
  `heartbeat_path=/api/server/module/save`, cert verify off.

### 3.2 `mnxdpi` section (the DPI daemon)
- `pcap`: **`path="/data/raw"`**, `mode="direct"`, **`exclusive_read=true`**,
  `file_size_g=12`, `files=4`, `idle_ms=1000`, `read_tail_wait_ms=15000`,
  `page_size_k=256`, `symbolic_pcap_pass=true`. → reads pcap files from `/data/raw`.
  (Note the mismatch vs `global.base_path.pcap=/pipeline/raw`; see §6/§11.)
- Concurrency: `worker_count=64`, `worker_count_extra=4`, `subworkers_count=3`,
  `worker_idle_timeout=60000`, `queue_size=10000`.
- `elasticsearch.consumer`: `consumer_threads=16`, adaptive back-pressure knobs
  (`soft_max_items=3000`, `safe_max_items=5000`, `hard_http_max_bytes=25165824`,
  EMA slow/fast thresholds, etc.).
- `payload`: `enabled=true`, `http_request=true`, `packets=30000`,
  `ai_contents=["chatgpt"]`, `ftp_payload=false`, `smb_payload=false`.
- `http_content_types`: office/hwp/zip/7z/PE/ELF/APK types selected for extraction.
- `simple_magic_words`: magic-byte signatures (PDF, OLE office, OOXML, MZ/PE, PK/APK,
  ELF, 7z) used to detect files in reassembled streams.
- `heartbeat`: `enabled=true`, `url=https://localhost:8443/api/server/module/save`,
  `send_every=30`, name `"MNX DPI"`, info `"MNX v23"`.
- `logger`: file logger `mnx_logger`, level `info`, `console=false`, rotate
  `max_size_mb=100`, `max_files=10` → `/logs/mnxdpi/mnxdpi.log` (+ `.1..10`).
- `port=9500` (see §9), `libmnxdpi_method="json"`, `module_name="mnxdpi"`,
  `version="2026041001"`.

### 3.3 Related downstream keys
- `payload_analysis`: consumes payloads (`http/http2/ftp/mail/smb`), calls scan
  engine (`bitdefender` at `/var/run/payload_scanengine.sock`), AI analysis at
  `/var/run/payload_ai_analysis.sock`; `custom_rule_path="/data/custom-rule/yara"`
  (**does not exist on disk — see §5/§10**).
- `service_control.pcap_storage_config`: `dpi_mode="mnx"`, `post_path="/data/raw/"`,
  `pcap_raw_postprocess_flag=true`, `pcap_raw_cycle=4`, `file_count_key="packetThreads"`
  — the module that stages pcaps from the capture output into `/data/raw` for mnxdpi.
- `regression_api`: reads Suricata — `suricata_yaml_path=/etc/suricata/suricata.yaml`,
  `suricata_bin=suricata`, `eve_types=["alert"]`, `api_url=http://0.0.0.0:8000`.

---

## 4. Suricata configuration (`/etc/suricata/suricata.yaml`, 81 KB)

- **Version**: `suricata -V` → `Suricata version 8.0.4 RELEASE`.
- **Network vars** (`:18`, `:24`): `HOME_NET="[192.168.0.0/16,10.0.0.0/8,172.16.0.0/12]"`,
  `EXTERNAL_NET="!$HOME_NET"`.
- **af-packet** (`:620`):
  ```
  af-packet:
    - interface: ens192
      threads: auto
      cluster-id: 99
      cluster-type: cluster_flow
      defrag: yes
  ```
  Confirmed live capture: `ss -0` shows Suricata-Main (PID 18585) holding multiple
  `p_raw ... *:ens192` AF_PACKET sockets (fd 7–16+). Startup log: `threads:
  Threads created -> W: 12 FM: 1 FR: 1`.
- **Command line** actually running: `--af-packet -c /etc/suricata/suricata.yaml
  --pidfile /run/suricata.pid --user suricata --group suricata`.
- **Threading** (`:1668`): `set-cpu-affinity: no` (worker threads = auto from
  cluster_flow). `max-pending-packets` left at default (commented `:1203`).
- **Outputs** (`outputs:` at ~`:82`), `default-log-dir: /logs/suricata` (`:61`):
  - `fast:` **enabled**, `fast.log`, append.
  - `eve-log:` **enabled**, `filetype: regular` (plain file — **not** redis/kafka/
    unix socket), `filename: eve.json`. Under `types:` **only `- alert:` is enabled**;
    http/dns/tls/flow/fileinfo/anomaly are all commented out. Verified at runtime:
    `head -5000 eve.json | grep event_type` → 5000/5000 = `"alert"`.
  - `stats:` enabled → `stats.log`. `http-log`, `tls-log`, `tls-store`,
    `alert-debug`, `pcap-log`, `file-store` all `enabled: no`.
- **Runtime control socket FAILED**: startup log `unix-manager: failed to create
  socket directory /var/run/suricata/: Permission denied` → `Unable to create unix
  command socket`. So `suricatasc` (live rule reload / stats) is **not available**;
  rule changes require a service restart. (See §10 risk.)

---

## 5. Suricata rules & `/application/custom-rule` + update flow

- **default-rule-path** (`suricata.yaml:2093`): `/application/custom-rule/suricata`
  (MNX-specific; **not** the distro default `/var/lib/suricata`).
- **rule-files** (`:2095`):
  ```
  - SANDS_CRITICAL.rules
  - SANDS_APPLICATION.rules   <-- LISTED BUT MISSING ON DISK
  - SANDS_DNS.rules
  - SANDS_ETC.rules
  - SANDS_MALWARE.rules
  - SANDS_RESPONSE.rules
  - SANDS_SCAN.rules
  - USER.rules
  - EXCEPTION.rules
  ```
- On-disk `/application/custom-rule/suricata/` (all dated Apr 20 13:23):
  `SANDS_CRITICAL.rules` (17 KB), `SANDS_DNS.rules` (12 KB), `SANDS_ETC.rules`
  (1.7 KB), `SANDS_MALWARE.rules` (**2.76 MB**, the bulk), `SANDS_RESPONSE.rules`
  (34 KB), `SANDS_SCAN.rules` (16 KB), `USER.rules` (2.8 KB),
  `EXCEPTION.rules` (0 bytes). **`SANDS_APPLICATION.rules` is absent** →
  Suricata loads with a warning; that signature category is effectively unused.
- Rule content confirms MNX/SANDS custom detection: `USER.rules` contains Korean
  PII/DLP signatures (resident-registration-number, phone `010-####-####`, credit
  card, passport `M########`, email leak; sids 13000x/14000x). `SANDS_CRITICAL.rules`
  has hunting/threat rules (e.g. `"SANDS_CRITICAL_Lulzsec_Attack"`, suspicious EXE
  download). Multiple custom `classtype`s (`trojan2`, `riskware1/2/3`, `adware1/2`)
  are not declared in `classification.config` → startup warnings
  `detect-classtype: signature sid:... uses unknown classtype ...` (cosmetic;
  falls back to default priority 3).
- Config files alongside: `classification.config`, `reference.config`,
  `threshold.config` in `/etc/suricata/`.
- **YARA** custom rules (used by the payload path, not Suricata):
  `/application/custom-rule/yara/` → `hiddencobra_rifdoor_custom.yar`,
  `mimikatz test.yar`. Note `payload_analysis.custom_rule_path` in mnx_config points
  at `/data/custom-rule/yara`, which **does not exist** (`ls` → No such file).
  **추정**: yara rules are read from `/application/custom-rule/yara` and the
  `/data/custom-rule` path is stale/misconfigured, or symlinked at deploy time.
- **Update flow**: **No automated rule-update mechanism was found.** No `suricata-update`
  install, no cron entry, no updater script references SANDS rules
  (`grep -rl ... /etc/cron*`, `crontab -l`, `find ... *rule*update*` → empty). Rules
  are static since the Apr 20 build/deploy. `regression_api` (port 8000) holds
  `suricata_bin`/`suricata_yaml_path` and may drive validation/reload via API.
  **추정**: rule updates are delivered by re-deploying files + restarting the service
  (no live reload possible — unix socket failed, §4).

---

## 6. Data in / out

### mnxdpi
- **Input**: pcap **files** in `/data/raw` (`mnxdpi.pcap.path`, `mode=direct`,
  `exclusive_read=true`). At capture time `/data/raw` held 3 GB rolling files
  `sands-test-260628-*.pcap` (newest Jul 1). It does **not** open the NIC — no
  AF_PACKET socket in `/proc/18076/fd`; work items are `pcapfile_work_item` (§2.3).
- **Outputs**:
  1. **Elasticsearch** `127.0.0.1:9200` via libcurl `/_bulk`, session index prefix
     **`mnx_sessions3`** (`global.elasticsearch`), plus payload/mail/ai_content
     indices. Consumer pool of 16 threads.
  2. **Kafka** `127.0.0.1:9092`, topic **`request-file-analysis`** — file/payload
     analysis job requests to the payload_analysis pipeline.
  3. **Heartbeat** HTTPS `https://localhost:8443/api/server/module/save` every 30 s.
- **Runtime proof of I/O intent**: `mnxdpi.log` STAT lines show the ES consumer and
  session/pcap pipeline; currently all zero (idle — §7/§11).

### Suricata
- **Input**: live packets from **`ens192`** via AF_PACKET (`cluster_flow`, id 99).
  Sample eve record: `"in_iface":"ens192","pkt_src":"wire/pcap"`.
- **Outputs** (files under `/logs/suricata/`): `eve.json` (alert events only, ~5.9 MB
  live, rotated daily+gzip e.g. `eve.json-2026-06-26.gz`), `fast.log`, `stats.log`
  (large — 48 MB current, 215 MB rotated), `suricata.log`. **No** Kafka/Redis/ES
  output from Suricata directly.
- **eve.json consumers** (downstream, not Suricata's job): `regression_api`
  (`eve_types=["alert"]`) parses it; Arkime `capture` is *configured* to ingest it via
  a `suricata.so` plugin (`suricataAlertFile=/logs/suricata/eve.json`) **but that
  plugin is not loaded in the running capture** — see §11. Only Suricata itself holds
  `eve.json` open at capture time (`/proc/18585/fd`); no filebeat/logstash/vector
  process is running.

---

## 7. Threads / processes

- **mnxdpi** (PID 18076): `Tasks: 29` (`ls /proc/18076/task | wc -l` = 29). Config
  requests `worker_count=64`, `worker_count_extra=4`, `subworkers_count=3`,
  `elasticsearch.consumer.consumer_threads=16`; actual live thread count is lower
  because the daemon is idle (workers spun down / not all engaged). RSS 8.3 GB.
- **suricata** (PID 18585): `Tasks: 17` (`/proc/18585/task` = 17). Startup:
  `W: 12` worker + `FM:1 FR:1` management/flow-recycler threads. RSS ~325 MB.

---

## 8. Dependencies (shared libraries, `ldd /opt/mnxdpi/mnxdpi`)

Notable:
- `libpcap.so.0.8` — pcap file reading.
- `librdkafka++.so.1` + `librdkafka.so.1` — Kafka producer.
- `libcurl.so.4` (+ nghttp2, idn2, rtmp, ssh, psl, ldap, krb5, sasl, brotli,
  zstd, lz4) — HTTP client to Elasticsearch / heartbeat.
- `libcrypto.so.3`, `libssl.so.3`, `libgnutls.so.30` — TLS/crypto.
- `libspdlog.so.1` + `libfmt.so.8` — logging.
- `libsystemd.so.0` — journald / sd_notify.
- `libstdc++`, `libz`, `libuuid`, `libdbus-1`, `libm`, `libgcc_s`, `libc`.
- PACE2 and PcapPlusPlus are **statically linked / vendored** (no `libpace*`/
  `libpcpp*` in `ldd`, but their symbols/strings are in the binary — §2.3).

Suricata: distro package `/usr/bin/suricata` (v8.0.4); runs as user/group
`suricata`; requires the rule/config files in §4–5. `systemd` unit at
`/lib/systemd/system/suricata.service`.

---

## 9. Ports / sockets

- **mnxdpi**: config `port=9500`, but **not listening on TCP 9500** (`ss -lntup |
  grep 9500` → empty). Instead it exposes a **UNIX control socket
  `/var/run/mnxdpi.sock`** (created 10:11 by the daemon) and pidfile
  `/var/run/mnxdpi.pid`. The `-K` stop command and Arkime's `libmnxdpi_*` client keys
  target this. No client is currently connected to it (`ss -xp | grep mnxdpi` shows
  only the daemon's own stdio-to-journald socket). **추정**: `port 9500` is a
  legacy/optional TCP listener not enabled in this build.
- **Suricata**: no TCP listener; its intended unix command socket
  (`/var/run/suricata/`) **failed to create** (§4).
- **regression_api**: LISTEN `0.0.0.0:8000` (python3.12, PID 18814).
- **Arkime capture** (context): outbound ES client to `[::1]:9200`
  (`/proc/18353/fd`), and Arkime `libmnxdpi_port=9500`/`libmnxdpi_sock=/var/run/`.

---

## 10. Failure impact & recovery

- **mnxdpi**: `Restart=on-failure`, `RestartSec=5s`. Graceful stop via
  `ExecStop=... -K` then `rm /run/mnxdpi.pid`. **But the unit is `disabled`** — it
  will **not** restart on host reboot via systemd (§11). If mnxdpi dies: no DPI
  session enrichment and no `request-file-analysis` Kafka jobs → the file/AV/AI
  payload-analysis pipeline stops receiving work. Suricata detection is unaffected.
- **Suricata**: `enabled`, standard unit; dies → real-time alerting stops (no eve/
  fast alerts). Live rule reload is impossible (unix cmd socket failed, §4), so any
  rule change needs a full `systemctl restart suricata`, which briefly drops capture.
- **Active operational fault at capture time — Elasticsearch flood-stage block**:
  `capture.log` is flooding with HTTP 429
  `cluster_block_exception ... index [mnx_sequence_v30] blocked by:
  [TOO_MANY_REQUESTS/12/disk usage exceeded flood-stage watermark, index has
  read-only-allow-delete block]`. ES rejected writes because a disk crossed the
  flood-stage watermark; the read-only block persists until cleared even after space
  frees. Disk at capture time: `/ 21%`, `/logs 41%`, `/pipeline 59%`, `/data 77%`
  (`df -h`) — so the block is likely **stale / not auto-cleared** (추정), yet still
  failing writes. This blocks capture's session indexing and would block mnxdpi's ES
  bulk writes too. **Recovery**: raise/clear the ES `read_only_allow_delete` block
  after freeing disk.
- **No fresh pcaps since Jul 1**: newest file in both `/pipeline/raw` and `/data/raw`
  is dated Jul 1, although `eng_monitor.log` shows live traffic on ens192 right now
  (`"original_interface":"ens192","mbps":9.75,"pps":4027`). **추정**: capture stopped
  persisting pcaps around Jul 1 (disk/ES watermark), which is *why* mnxdpi has no work
  (§11).

---

## 11. Is mnxdpi dead / unused? — **No. It is alive but idle, and it is the operative DPI path.**

Evidence it is **NOT** dead:
- Process running (PID 18076, 8.3 GB, 29 threads) and **actively logging now**:
  `/logs/mnxdpi/mnxdpi.log` mtime 2026-07-10 10:41, emitting STAT lines every ~2 s:
  ```
  [STAT] active_pcap_group=0 (per worker=3) || session: submitted_total=0,
         submitted_rate=0.0/s, completed_total=0, pending_now=0 || elasticsearch: pending_items=0 ...
  [STAT] CPU user(8.x) sys(6.x) idle(83.x) iowait(0.00)
  ```
  → it is polling for pcap files but has **zero work** because no new pcaps exist
  since Jul 1 (§10). Idle, not dead.

Why "service disabled" is a red herring:
- `disabled` only means systemd won't auto-start it at boot. All MNX processes
  (mnxdpi, suricata, capture, payload_*) came up together at **10:11:24** — indicating
  an external orchestrator/boot script starts mnxdpi explicitly despite the disabled
  unit. **추정**: `service_control` or an MNX bootstrap starts it (mnxdpi is *not* in
  `service_control.service_list`, which lists payload_analysis/scanengine/ai_dga/
  ai_file/suricata — so the starter is something else, unverified).

Is it superseded by an in-capture DPI plugin? **No, not in the running system:**
- Arkime `capture` config (`/opt/mnx/etc/config.ini`) **declares** DPI+IDS plugins:
  ```
  pluginsDir=/opt/mnx/plugins
  plugins = suricata.so;libmnxdpi.so
  suricataAlertFile=/logs/suricata/eve.json
  libmnxdpi_method=json · libmnxdpi_workspace=/pipeline
  libmnxdpi_sock=/var/run/ · libmnxdpi_addr=localhost · libmnxdpi_port=9500
  ```
  and the plugin exists on disk: `/opt/mnx/plugins/libmnxdpi.so`.
- **But the running capture (PID 18353) loaded NEITHER plugin** — its memory map
  (`/proc/18353/maps`) contains no `libmnxdpi.so` and no `suricata.so` (only standard
  libs: libmagic, libyaml, libpcre, libssl…). So the plugin-based inline DPI /
  eve-ingest integration is **inactive** in this instance. **추정**: the plugins
  failed to load or the build ships without them.
- Therefore the **standalone file-based mnxdpi daemon is the actual DPI path** (reads
  `/data/raw` → ES `mnx_sessions3` + Kafka `request-file-analysis`), and it is
  *complemented*, not replaced, by the (currently unloaded) `libmnxdpi.so` client.

Conclusion: mnxdpi is a **live, load-bearing component that is temporarily idle** due
to the upstream pcap/ES stoppage — not dead code.

---

## 12. Cross-references

- **Capture → DPI pipeline** (file-based): Arkime `capture` sniffs `ens192`
  (`config.ini: interface=ens192`, `bpf = not broadcast and not multicast`,
  `interfaceOps=tags=Net-1`) → writes 3 GB pcaps to **`/pipeline/raw`**
  (`config.ini:81 pcapDir=/pipeline/raw`) → `service_control` post-processes/stages
  them to **`/data/raw`** (`mnx_config service_control.pcap_storage_config.post_path`,
  `pcap_raw_postprocess_flag=true`) → **mnxdpi reads `/data/raw`** and enriches. The
  `/pipeline/raw` vs `/data/raw` split reconciles the two pcap paths in config
  (`global.base_path.pcap` vs `mnxdpi.pcap.path`). **추정** on the exact copy/move step.
- **Capture, Suricata, mnxdpi all derive from `ens192`, but via two independent taps**:
  1. Arkime `capture` and **Suricata** each open their **own live AF_PACKET capture**
     on `ens192` (capture writes pcap+ES sessions; Suricata writes alerts). They do
     **not** share a socket.
  2. **mnxdpi is offline** — it never touches the NIC; it reads the pcap files Arkime
     produced. So the effective topology is: `ens192` → {Arkime live, Suricata live};
     Arkime pcap files → mnxdpi (offline DPI).
- **Downstream of mnxdpi**: Kafka `request-file-analysis` → `payload_analysis` →
  `payload_scanengine` (Bitdefender) + `payload_ai_analysis` (file-type AI models);
  results and DPI sessions land in Elasticsearch (`mnx_sessions3*`, `payload_*`).
- **eve.json** → `regression_api` (`eve_types=["alert"]`, port 8000) and *intended*
  Arkime `suricata.so` correlation (currently not loaded).
- Related units/configs: `/etc/systemd/system/mnxdpi.service`,
  `/lib/systemd/system/suricata.service`, `/opt/mnx/etc/mnx_config.json`,
  `/opt/mnx/etc/config.ini` (Arkime), `/etc/suricata/suricata.yaml`,
  `/application/custom-rule/{suricata,yara}`, logs under `/logs/{mnxdpi,suricata,
  mnxcapture,eng_monitor,regression_api}`.

### Open items / risks summary
1. **ES read-only flood-stage block** stalling ingest (§10) — highest-impact live fault.
2. **Pcap production stopped ~Jul 1** while traffic still flows → mnxdpi idle (§10/§11).
3. **`SANDS_APPLICATION.rules` missing** though referenced in `rule-files` (§5).
4. **mnxdpi.service disabled** → no systemd auto-start on reboot; relies on an
   unidentified starter (§11) — 추정.
5. **Suricata unix command socket failed** → no live rule reload; restart required (§4).
6. **No automated rule-update mechanism** found; rules static since Apr 20 (§5).
7. **`payload_analysis.custom_rule_path=/data/custom-rule/yara` does not exist**
   (actual yara rules at `/application/custom-rule/yara`) (§5).
8. **Declared Arkime plugins (`suricata.so`, `libmnxdpi.so`) not loaded** by the
   running capture — inline DPI/eve-correlation inactive (§11).
9. mnxdpi holds **8.3 GB RAM while idle** — memory footprint worth reviewing (§1/§7).
10. Suricata `stats.log` grew to hundreds of MB (215 MB rotated) — log-volume watch.
