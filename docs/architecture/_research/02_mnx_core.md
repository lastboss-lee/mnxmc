# 02 — MNX Core Data-Plane (`/opt/mnx`) — Packet Capture, Parsers, Plugins

> Architecture handover research. Every claim is grounded in on-box evidence with `file:line`
> or command output. Items that could not be fully verified are marked **추정(unverified)**.
> Investigation host: `sands-test`. Date: 2026-07-10.

---

## 0. TL;DR / What this subsystem actually is

`/opt/mnx` is **Arkime 5.8.2, rebranded as "MNX"** (formerly Moloch). This is proven by:
- `/opt/mnx/include/mnxconfig.h:68` → `#define PACKAGE_STRING "mnx 5.8.2"`, `:56 #define PACKAGE "mnx"`.
- `config.ini:60 httpRealm=Moloch` (original Moloch realm left in place).
- `wise.js:4 Copyright 2012-2014 AOL Inc.` (Moloch's original AOL authorship).
- Directory layout (`bin/capture`, `parsers/*.so`, `plugins/*.so`, `db/db.pl`, `viewer`, `wise`, `cont3xt`, `parliament` systemd units) is the canonical Arkime layout.

The data plane is the **`capture`** process: a compiled C/ELF binary that sniffs a mirror
(SPAN) port, writes raw pcap to disk, extracts session metadata via compiled `.so` protocol
parsers, indexes sessions into OpenSearch/Elasticsearch, and hands sessions/pcap off to the
separate **mnxdpi** engine (via the `libmnxdpi.so` plugin) for deep payload analysis.

**⚠️ Current runtime state is BROKEN (see §1 and §11):** `capture` is wedged in an infinite
startup retry loop because the ES `mnx_sequence_v30` index is under a `read-only-allow-delete`
block (flood-stage disk watermark). It is **not currently capturing** — newest pcap is from
2026-07-01, newest session index is `mnx_sessions3-260630`.

---

## 1. Overview — role, importance, running status

**Role:** Core NDR sensor / data plane. Turns mirrored network traffic into (a) full-packet
pcap on disk and (b) structured session records in Elasticsearch, and feeds the DPI/payload
analysis chain.

**Importance:** Highest. Everything downstream (mnxdpi, payload_analysis, scanengine, AI file
analysis, the web UI's session search) depends on `capture` producing pcap + session records.
If `capture` stops, the whole NDR stops seeing traffic.

**Running status (as observed):**
- Service: `mnxcapture.service` — `active (running) since Fri 2026-07-10 10:11:24 KST`, `enabled`.
- Process tree (`systemctl status mnxcapture`):
  - PID 18352 `/bin/sh -c "/opt/mnx/bin/capture -c /opt/mnx/etc/config.ini >> /logs/mnxcapture/capture.log 2>&1"`
  - PID 18353 `/opt/mnx/bin/capture -c /opt/mnx/etc/config.ini` (runs as user `nobody`, `ps` confirms).
- **But functionally dead:** `capture.log` (head + tail identical) is an unbroken flood of:
  `db.c:1948 mnx_db_get_sequence_number_sync(): ERROR - Couldn't fetch sequence: 415 ... index [mnx_sequence_v30] blocked by: [TOO_MANY_REQUESTS/12/disk usage exceeded flood-stage watermark, index has read-only-allow-delete block]`.
- Corroborating evidence it never finished init:
  - `ps -T -p 18353` shows **1 thread** despite `packetThreads=2`/`tpacketv3NumThreads=2` (config.ini:308-309). Packet threads are spawned *after* DB init, which is looping.
  - `/proc/18353/fd` shows **no open pcap file** — only `/dev/null`, `capture.log`, an eventfd, and sockets (fd 10 = ES connection). It never opened a capture file.
  - Newest pcap `/data/raw/sands-test-260628-00000418.pcap` is dated **Jul 1 06:47**; newest ES session index is **`mnx_sessions3-260630`** (`_cat/indices`). Capture has produced nothing since the disk filled.

---

## 2. `capture` binary — type, launch, options, env, user, cwd

**Type:** Compiled native binary, NOT a script and NOT node.
`file /opt/mnx/bin/capture` → `ELF 64-bit LSB pie executable, x86-64 ... dynamically linked ... with debug_info, not stripped`. Size 17,943,120 bytes.

**Launch (systemd, `/etc/systemd/system/mnxcapture.service`):**
```
Type=simple, Restart=on-failure
EnvironmentFile=-/opt/mnx/etc/capture.env      # '-' prefix => optional; file does NOT exist
ExecStartPre=-/opt/mnx/bin/mnx_config_interfaces.sh -c /opt/mnx/etc/config.ini -n default
ExecStart=/bin/sh -c '/opt/mnx/bin/capture -c /opt/mnx/etc/config.ini ${OPTIONS} >> /logs/mnxcapture/capture.log 2>&1'
WorkingDirectory=/opt/mnx
LimitCORE=infinity
LimitMEMLOCK=infinity
Requires=elasticsearch.service ; After=elasticsearch.service
Wants=mnxdpi.service ; After=mnxdpi.service
```

**Decoded `${OPTIONS}` (from `capture.env`):** **empty.** `/opt/mnx/etc/capture.env` **does not
exist** (confirmed by `find` + `cat` failure); the only reference template is
`/opt/mnx/etc/env.example`. Because `EnvironmentFile` is prefixed with `-`, systemd treats it as
optional and `${OPTIONS}` expands to nothing. So the effective command line is exactly
`/opt/mnx/bin/capture -c /opt/mnx/etc/config.ini`. Per `env.example`, if it existed OPTIONS could
add `--insecure`, `--debug`, `-n <nodename>`, `-o <key>=<value>` overrides, `--host <hostname>`.

**User / privileges:** started as root, drops to `dropUser=nobody` / `dropGroup=daemon`
(config.ini:144,147). `ps` confirms PID 18353 runs as `nobody`. `LimitMEMLOCK=infinity` +
`LimitCORE=infinity` for locked packet ring buffers / core dumps.

**Working dir:** `/opt/mnx`.

**Node identity:** node name defaults to `default`/hostname `sands-test` (seen in the ES doc id
`fn-sands-test` and pcap filename prefix `sands-test-`).

---

## 3. Interface configuration — `mnx_config_interfaces.sh` + `config.ini`

**Capture NIC:** `interface=ens192` (config.ini:63), tagged `interfaceOps=tags=Net-1` (:64).
This is the mirror/SPAN port. A separate unit sets promisc at boot:
`promisc-ens192.service` → `ExecStart=/usr/sbin/ip link set ens192 promisc on` (active/exited).

**BPF filter:** `bpf = not broadcast and not multicast` (config.ini:65) — drops L2 broadcast/multicast noise before capture.

**`ExecStartPre` NIC prep (`bin/mnx_config_interfaces.sh`):** parses the `[default]` (or node)
section of config.ini for `interface=`, splits on `;`, and for each real NIC (skips `dummy`):
- `ip link set <if> up`
- `ip link set <if> promisc on`
- `ethtool -G <if> rx 4096 tx 4096` — **ring buffers set to 4096** rx/tx.
- Loops `ethtool -K <if> {rx tx sg tso ufo gso gro lro} off` — **disables all NIC offloads**
  (essential so the sensor sees real on-wire packets, not coalesced/segmented frames).

**Capture read path / ring config (config.ini "High Performance" block, :303-321):**
- `pcapReadMethod=tpacketv3` (kernel TPACKET_V3 mmap ring)
- `tpacketv3BlockSize=8388608` (8 MB blocks), `tpacketv3NumThreads=2`
- `packetThreads=2` (2 packet-processing threads)
- `maxPacketsInQueue=350000`
- `packetsPerPoll=50000` (:283)
- `magicMode=none` (:305 — skip libmagic content-type guessing for speed)

Multi-interface is possible (commented example `interface=ens5f0;ens5f1` at :68) but not used.

---

## 4. Config files — every meaningful key

### 4a. `/opt/mnx/etc/config.ini` (Arkime capture+viewer INI, tiered `[node]→[nodeClass]→[default]`)

| Key (line) | Value | Effect |
|---|---|---|
| `elasticsearch` (19) | `http://localhost:9200` | ES/OpenSearch endpoint for session indexing + config. |
| `rotateIndex` (29) | `daily` | New ES index per day (`mnx_sessions3-YYMMDD` observed). |
| `authMode` (30) | `anonymous` | Viewer auth mode; no login enforced. |
| `passwordSecret` (52) | `toswm#0501` | **Hardcoded** secret encrypting stored password hashes / S2S. Risk (§12). |
| `httpRealm` (60) | `Moloch` | HTTP digest realm (unchanged Moloch default). |
| `interface` (63) | `ens192` | Capture NIC (see §3). |
| `interfaceOps` (64) | `tags=Net-1` | Tags every session from this IF with `Net-1`. |
| `bpf` (65) | `not broadcast and not multicast` | Capture BPF filter. |
| `pcapDir` (81) | `/pipeline/raw` | Where raw pcap is written. (Dir holds **symlinks** to `/data/raw` — see §7.) |
| `simpleCompression` (82) | `none` | pcap written uncompressed. |
| `tcpTimeout` (94) | `600` | Write session record after 600s TCP inactivity. |
| `tcpSaveTimeout` (98) | `720` | Force session record every 720s regardless. |
| `udpTimeout` (102) | `30` | UDP session end after 30s idle. |
| `icmpTimeout` (106) | `10` | ICMP session end after 10s idle. |
| `maxPackets` (112) | `30000` | Write session record after 30000 packets (matches DPI `payload.packets=30000`). |
| `freeSpaceG` (118) | `5%` | Delete oldest pcap when free space < 5% (does NOT delete ES records). |
| `rirFile` (133) | `/opt/mnx/etc/ipv4-address-space.csv` | IANA RIR assignment lookup. |
| `ouiFile` (137) | `/opt/mnx/etc/oui.txt` | MAC OUI vendor lookup (3 MB file present). |
| `rulesFiles` (141) | `/opt/mnx/etc/mnx.rules` | MNX action rules file. |
| `dropUser`/`dropGroup` (144,147) | `nobody`/`daemon` | Privilege drop target. |
| `parseSMTP` (186) | `true` | Extra SMTP parsing on. |
| `parseSMB` (189) | `false` | SMB extra parsing off. |
| `parseQSValue` (192) | `false` | Don't index HTTP query-string values. |
| `supportSha256` (195) | `false` | Don't hash bodies with sha256. |
| `maxReqBody` (198) | `64` | Only index HTTP request bodies < 64 bytes. |
| `reqBodyOnlyUtf8` (201) | `true` | Store request bodies only if UTF-8. |
| `smtpIpHeaders` (204) | `X-Originating-IP:;X-Barracuda-Apparent-Source-IP:` | SMTP headers carrying client IPs. |
| `parsersDir` (207) | `/opt/mnx/parsers` | Where `.so` parsers are loaded from. |
| `pluginsDir` (210) | `/opt/mnx/plugins` | Where plugins are loaded from. |
| **`plugins`** (214) | `suricata.so;libmnxdpi.so` | **The two active data-plane plugins** (load order). |
| `suricataAlertFile` (215) | `/logs/suricata/eve.json` | Suricata EVE JSON that `suricata.so` tails (file present, 5.9 MB, live). |
| `libmnxdpi_method` (217) | `json` | Handoff serialization format to mnxdpi. |
| `libmnxdpi_workspace` (218) | `/pipeline` | Shared workspace dir with mnxdpi. |
| `libmnxdpi_sock` (219) | `/var/run/` | Unix-socket dir for mnxdpi handoff (`/var/run/mnxdpi.sock` present). |
| `libmnxdpi_addr`/`_port` (220,221) | `localhost` / `9500` | Configured TCP addr/port for mnxdpi (not observed listening — uses unix socket, see §10). |
| `spiDataMaxIndices` (241) | `4` | Cap indices for SPI-graph queries. |
| `maxESConns` (275) | `30` | Max ES connections. |
| `maxESRequests` (278) | `500` | Max outstanding ES bulk requests. |
| `packetsPerPoll` (283) | `50000` | Packets per libpcap poll. |
| `logEveryXPackets` (291) | `1000000` | Status log cadence. |
| `magicMode` (305) | `none` | No libmagic classification. |
| `pcapReadMethod` (306) | `tpacketv3` | Kernel mmap ring read. |
| `tpacketv3BlockSize` (307) | `8388608` | 8 MB ring blocks. |
| `packetThreads` (308) | `2` | Packet processing threads. |
| `tpacketv3NumThreads` (309) | `2` | Ring reader threads. |
| `pcapWriteMethod` (310) | `simple` | O_DIRECT, one file per packet thread. |
| `pcapWriteSize` (311) | `4194304` | 4 MB write chunks (RAID/xfs stripe aligned). |
| `maxPacketsInQueue` (312) | `350000` | Packet queue depth. |
| `compressES` (313) | `true` | gzip ES requests. |
| `dbEsHealthCheck` (314) | `false` | Skip ES health precheck. |
| `maxStreams` (315) | `4000000` | Max tracked concurrent sessions. |
| `dbBulkSize` (316) | `500000` | ES bulk batch size (bytes). |
| `createStatsIndex`/`stats` (318,319) | `false` | No stats index/collection. |
| `maxFileSizeG` (321) | `3` | **3 GB max per pcap file** (matches observed 3.0 GB files). |
| `[headers-http-request]` (350-354) | referer/authorization/content-type/origin | Extra HTTP request headers indexed. |
| `[headers-http-response]` (357-360) | location/server/content-type | Extra response headers indexed. |
| `[headers-email]` (363-365) | x-priority/authorization | Extra email headers indexed. |

Notably commented-out/unused: TLS certFile/keyFile (running **http**), wiseHost, netflow*,
remote-clusters, override-ips, uploadCommand, packetThreads low-bandwidth block.

Encoding note: comment lines 67-68 contain mojibake (broken Korean in a non-UTF8/legacy
codepage), e.g. line 67 `(... multi-interface...)`. Cosmetic only.

### 4b. `/opt/mnx/etc/capture.env`
**Does not exist.** Optional (`EnvironmentFile=-`). Template: `env.example`. `${OPTIONS}` is empty.

### 4c. `/opt/mnx/etc/mnx_config.json` — the **shared config for the C++/Python NDR stack**
This is NOT read by `capture` (Arkime uses config.ini). It is the config for the *other* `/opt`
modules (`mnxdpi`, `payload_analysis`, `scanengine`, `service_control`, `file_analysis_ai`,
`regression_api`, `syslog`) — all invoked as `-c /opt/mnx/etc/mnx_config.json` (see `ps`). Key
sections (relevant to the data-plane handoff):

- `global.elasticsearch` (5-18): ES `127.0.0.1:9200`, session index prefix **`mnx_sessions3`**,
  file-analysis index prefix `payload_`, AI `ai_content-`, mail `mail_content-`.
- `global.kafka` (20-27): broker `127.0.0.1:9092`; payload analysis via Kafka topic
  **`request-file-analysis`**, consumer group `mnx`, `enable:true`.
- `global.manage_web` (29-34): core API `https://127.0.0.1:8443`, heartbeat `/api/server/module/save`.
- `global.base_path` (36-46): `log=/logs`, `pid=/var/run/`, `unixsocket=/var/run/`,
  **`pcap=/pipeline/raw`**, `data=/data`, `dpi_workspace=/dir_cache`,
  **`payload_binary=/data/payload`**, `payload_mail_content=/data/payload/mail_content`,
  `payload_ai_content=/data/payload/ai_content`.
- `mnxdpi` (55-227): `worker_count=64`, `subworkers_count=3`, `queue_size=10000`,
  `libmnxdpi_method=json`, **`port=9500`**, ES consumer tuning block (49-107),
  `http_content_types` list of file types to carve (Office/zip/PE/ELF/HWP…),
  `simple_magic_words` (PDF/office/PE/APK/ELF/7z magic), `pcap.path=/data/raw`,
  `pcap.file_size_g=12`, `pcap.mode=direct`, `payload.enabled=true`, `payload.packets=30000`,
  `payload.ai_contents=["chatgpt"]`, heartbeat to `https://localhost:8443` every 30s.
- `payload_analysis` (229-276): reads http/http2/ftp/mail/smb payloads, scanengine
  `bitdefender` via `/var/run/payload_scanengine.sock`, AI via
  `/var/run/payload_ai_analysis.sock`, yara custom rules `/data/custom-rule/yara`.
- `service_control` (310-352): supervises `ai_dga`, `ai_file`, `payload_analysis`, `scanengine`,
  `suricata`; `pcap_storage_config.post_path=/data/raw/`, `pcap_raw_cycle=4`,
  `file_count_key=packetThreads` — i.e. it post-processes the raw pcap Arkime writes.
- `regression_api` (354-364): `http://0.0.0.0:8000`, drives suricata for rule regression.
- `syslog` (366-385): syslog forwarding (all servers `enable:false`).

---

## 5. Parser architecture

- **Location:** `/opt/mnx/parsers` (config `parsersDir=/opt/mnx/parsers`, config.ini:207).
- **Language:** Compiled **C shared objects** (`.so`), Arkime's native parser ABI declared in
  `/opt/mnx/include/mnx.h` (60 KB API header) + `mnxconfig.h`. **NOT JavaScript, NOT node.**
- **Counts (measured):** **47 `.so` parsers**, **17 `.jade` templates**.
- **How invoked:** `capture` `dlopen`s every `*.so` in `parsersDir` at startup; each registers a
  classifier/callback into the packet pipeline (Arkime `moloch_parsers_init` pattern). Parsers
  run in-process on the 2 packet threads, per session, keyed by protocol classification (TCP/UDP
  port + payload heuristics). The `.jade` files are **not parsers** — they are Pug/Jade HTML
  templates (e.g. `dns.detail.jade`, `tls.detail.jade`) rendered by the **viewer** (node) to show
  protocol detail in the web UI. Their presence in `parsers/` is an Arkime packaging convention.
- **Protocols covered (from `.so` filenames):** L2/L3/tunnel: arp, lldp, mpls, ppp, gre, geneve,
  vxlan, nsh, erspan, ciscometadata, isis, ospf, pim, igmp, ah, esp, gtp, sctp. Core:
  tcp, udp, icmp. App/protocol: dns, http, http2, quic, tls, dtls, certs, ssh, smtp, smb, ldap,
  krb5, radius, snmp, bgp, dhcp, irc, socks, nfs, rpc. DB protocols: mysql, oracle, postgresql,
  tds (MSSQL), modbus (ICS/SCADA). Fallback/misc: misc.so.
- **Config format:** parsers are config-less shared objects; behavior is toggled by config.ini
  keys (e.g. `parseSMTP`, `parseSMB`, `parseQSValue`, `maxReqBody`) and the `headers-*` sections.
- **Sample walkthrough — `tls.so` (183 KB, the largest parser):** classifies TLS/SSL sessions,
  extracts SNI/server name, cert chain (paired with `certs.so`), JA3/JA3S-style fingerprints,
  cipher/version; results become session fields and drive `tls.detail.jade` in the UI. (The
  `.so` is compiled/binary; behavior inferred from Arkime's known `tls.c` parser and the paired
  `tls.detail.jade` field list — **추정(unverified)** at the byte level.)

---

## 6. Plugin architecture

- **Location:** `/opt/mnx/plugins` (`pluginsDir=/opt/mnx/plugins`, config.ini:210).
- **Active plugins (config.ini:214):** **`plugins = suricata.so;libmnxdpi.so`** — only these two
  are loaded, in this order. Everything else in the dir is present-but-unused (see §12).
- **Available (measured):** **13 `.so` plugins** + 3 `.js` (viewer-side) + jade templates:
  - `.so`: `suricata.so`, `libmnxdpi.so`, `chad.so`, `garland.so`, `lua.so`, `netflow.so`,
    `scrubspi.so`, `tagger.so`, `tcphealthcheck.so`, `unkEthernet.so`, `unkIpProtocol.so`,
    `wise.so`, `writer-s3.so`.
  - `.js` (viewer plugins, run by **node**, not capture): `garland.js`, `wise.js`,
    `writer-s3/index.js`.
- **How invoked:** same `dlopen` mechanism as parsers; each `.so` registers hooks (session
  create/save, packet, ethernet/IP-protocol handlers). Load list + order comes from the
  `plugins=` key.
- **`suricata.so` (active):** tails `suricataAlertFile=/logs/suricata/eve.json` (live, 5.9 MB) and
  attaches Suricata IDS alerts to the matching MNX session record; `suricata.detail.jade` renders
  them in the UI. This is how IDS alerts join NDR session metadata.
- **`libmnxdpi.so` (active) — the critical handoff:** the bridge from the Arkime data plane to
  the in-house **mnxdpi** engine. Config keys `libmnxdpi_method=json`,
  `libmnxdpi_sock=/var/run/`, `libmnxdpi_addr=localhost`, `libmnxdpi_port=9500`,
  `libmnxdpi_workspace=/pipeline`. On session completion it serializes the session (JSON) and
  notifies mnxdpi (unix socket `/var/run/mnxdpi.sock`, present) pointing at the pcap in the shared
  `/pipeline` workspace. mnxdpi then does deep inspection / payload carving.
- **Unused-but-present plugins:** `netflow.so`, `tagger.so`, `wise.so`, `chad.so`, `lua.so`,
  `scrubspi.so`, `tcphealthcheck.so`, `writer-s3.so`, `unkEthernet.so`, `unkIpProtocol.so`,
  `garland.so` — none in the `plugins=` list, so not loaded by capture (§12 risk: dead weight /
  supply-chain surface).

---

## 7. Data in / out — traced

**INPUT:** Live packets from NIC **`ens192`** (mirror/SPAN port, promisc, offloads off), filtered
by BPF `not broadcast and not multicast`, read via TPACKET_V3 mmap ring.

**OUTPUTS:**
1. **Raw pcap → `/pipeline/raw`** (config `pcapDir`). Observation: `/pipeline/raw/` contains
   **symlinks** (e.g. `sands-test-260628-00000409.pcap -> /data/raw/sands-test-260628-00000409.pcap`).
   Actual pcap bytes live in **`/data/raw`** (10 files, 3 GB each, one open per packet thread,
   `maxFileSizeG=3`). `service_control.pcap_storage_config` (`post_path=/data/raw/`,
   `pcap_raw_cycle=4`, `pcap_raw_postprocess_flag=true`) manages this raw→/data/raw relationship.
   **추정(unverified):** exact symlink-creation ownership (capture writes to /pipeline/raw and a
   post-processor relocates to /data/raw, or vice-versa) — both dirs are referenced; the symlink
   direction shows canonical storage is `/data/raw` and `/pipeline/raw` is the working view.
2. **Session metadata → Elasticsearch** at `http://localhost:9200`, index family
   **`mnx_sessions3-YYMMDD`** (confirmed via `_cat/indices`: `mnx_sessions3-260626/27/28/30`,
   ~500 MB–7.5 GB each). Sequence/counter index **`mnx_sequence_v30`**. Capture holds one ES
   socket (`/proc/18353/fd/10` → `[::1]:9200`).
3. **Session/pcap handoff → mnxdpi** via `libmnxdpi.so` (JSON over `/var/run/mnxdpi.sock`,
   workspace `/pipeline`). mnxdpi reads pcap from `/data/raw` (`mnxdpi.pcap.path=/data/raw`),
   carves payloads to **`/data/payload`** (`payload_binary`), and publishes file-analysis jobs to
   **Kafka topic `request-file-analysis`** (`127.0.0.1:9092`) consumed by `payload_analysis` →
   `scanengine`(bitdefender) / `file_analysis_ai`.
4. **Suricata alerts IN** (not an output): `suricata.so` ingests `/logs/suricata/eve.json`.

**Capture does NOT use Kafka directly** — `strings /opt/mnx/bin/capture | grep -i kafka` returns
nothing; no librdkafka in `ldd`. Kafka is a downstream (mnxdpi/payload) concern. The
capture→downstream coupling is pcap-on-disk + the libmnxdpi unix socket + ES.

---

## 8. Threads / processes / IPC / queues / shared memory / sockets / signals

- **Process model:** single `capture` process (PID 18353) under a `/bin/sh` wrapper (PID 18352)
  under systemd. Runs as `nobody`.
- **Threads (designed):** `packetThreads=2` + `tpacketv3NumThreads=2` + ES/DB writer threads.
  **Observed: only 1 thread** because init is wedged (§1) — designed multithreading never
  reached. **추정(unverified):** normal healthy thread count (~6-10) not observable in current
  broken state.
- **Packet queue:** in-process ring, `maxPacketsInQueue=350000`, `packetsPerPoll=50000`.
- **Shared memory:** TPACKET_V3 mmap ring shared with kernel (`tpacketv3BlockSize=8 MB`).
  `LimitMEMLOCK=infinity` to lock it.
- **IPC / sockets (from `/proc/18353/fd` + `ss`):**
  - ES: TCP `[::1]:9200` (fd 10, ESTAB).
  - eventfd (fd 3) for thread wakeups; several anon sockets (fd 4-9).
  - mnxdpi handoff: unix socket `/var/run/mnxdpi.sock` (present; owned by mnxdpi).
- **Signals:** standard systemd `Restart=on-failure` on crash. No custom signal handling observed
  externally.

---

## 9. Dependencies

**Shared libs (`ldd /opt/mnx/bin/capture`):** libuuid, libpcre.3, **libssl.3 / libcrypto.3**
(TLS/cert parsing + hashing), libyaml-0.2 (suricata.yaml / config), libm, **libmagic.1** (file
type ID), libffi.8, libz.1, liblzma.5, libbz2.1.0, libc. (Notably `mnxconfig.h` shows
`HAVE_LIBCURL`/`HAVE_LIBLUA`/`HAVE_LIBNET` **undef** — built without curl/lua/libnet; uses its own
HTTP client `http.c`.) `HAVE_ZSTD 1` (zstd compression compiled in).

**node (`/opt/mnx/node-v20.19.4-linux-x64`, symlinked as `bin/node`,`npm`,`npx`,`corepack`):**
Bundled Node.js v20.19.4 runtime. **It does NOT run parsers or plugins for capture.** Its role is
the **JavaScript web/enrichment tier** — the Arkime viewer, WISE (`mnxwise`), Cont3xt
(`mnxcont3xt`), and Parliament (`mnxparliament`) services, whose systemd unit files ship in
`/opt/mnx/etc/*.systemd.service`. The `.js` files under `plugins/` (`garland.js`, `wise.js`,
`writer-s3/index.js`) are **viewer** plugins run by node, and the `.jade` files are viewer HTML
templates. Evidence: `garland.js` calls `api.getPcap()`/`Pcap.setEtherCB` (viewer pcap API);
`wise.js:2` is literally "wiseService viewer plugin". No MNX capture-path process was observed
running node (`ps` shows node only for VS Code remote server, unrelated).

**perl:** `db/db.pl` (263 KB) — the ES index init/upgrade/expire tool (see README steps 5).
`bin/taggerUpload.pl`. Not in the live packet path.

**No Python in the capture data plane.** (Python processes belong to the separate
payload/AI/regression modules.)

---

## 10. Ports

- **capture LISTENS on:** nothing (no `ss` LISTEN owned by capture; it is a sensor/writer).
- **capture CONNECTS to:** `127.0.0.1:9200` (Elasticsearch, `[::1]:9200` observed).
- **Configured but not observed:** `libmnxdpi_port=9500` (mnxdpi TCP) — mnxdpi is NOT listening on
  9500 (`ss` shows nothing on 9500); the handoff uses unix socket `/var/run/mnxdpi.sock` instead.
  **추정(unverified):** 9500 is a fallback/legacy TCP path unused in this deployment.
- **Neighbouring listeners (context, `ss -tlnp`):** ES `:9200` (java 15810), Kafka `:9092` (java
  17016), core web/API `:8443` (java 2294, the mnx_web app), regression_api `:8000` (python),
  DPI/payload use unix sockets (`/var/run/*.sock`).

---

## 11. Failure impact & recovery

**Impact if capture is down:** no new pcap, no new session records, no feed to mnxdpi/payload/AI,
no live IDS-alert correlation. The NDR is blind. **This is the current state.**

**Restart / order:** `Restart=on-failure`. `Requires=elasticsearch.service` (hard dep — capture
won't run without ES) and `Wants=mnxdpi.service` (soft). `ExecStartPre` re-applies NIC settings
each start. Boot order: elasticsearch → (mnxdpi) → mnxcapture; `promisc-ens192.service` sets
promisc independently at boot.

**⚠️ ACTIVE INCIDENT (root cause):** ES tripped its **flood-stage disk watermark** (default 95%),
which set a `read-only-allow-delete` block on indices including `mnx_sequence_v30`. On its 10:11
restart, capture calls `mnx_db_get_sequence_number_sync()` (db.c:1948) to get its file sequence
number *before* starting packet threads; ES returns HTTP 429 `cluster_block_exception`; capture
retries in a **tight infinite loop** (thousands of lines/second → `capture.log` grew to **8.7 GB**
across current + one rotated file). Disk has since been freed (`/data` now 77%, below flood
stage) **but the ES read-only block was never cleared**, so capture stays wedged. **Recovery:**
clear the block, e.g.
`curl -XPUT localhost:9200/_all/_settings -H content-type:application/json -d '{"index.blocks.read_only_allow_delete":null}'`,
then restart mnxcapture; also truncate/rotate `capture.log`. **추정(unverified):** whether an
operator or a cron already attempts this.

---

## 12. Code quality / operational risks (cited)

1. **Capture is currently wedged / blind** — infinite `mnx_db_get_sequence_number_sync` retry loop
   on an ES `read-only-allow-delete` block; no backoff, no crash (so `Restart=on-failure` never
   triggers). Newest pcap `Jul 1`, newest session index `mnx_sessions3-260630`. **Highest risk.**
   (`/logs/mnxcapture/capture.log`, `_cat/indices`.)
2. **Runaway log growth / no rate limiting** — the retry loop produced **8.7 GB** of identical
   error lines (`/logs/mnxcapture/`: `capture.log` 1.3 GB + `capture.log-2026-07-10-...` 7.7 GB).
   Can itself fill `/logs` (30 GB, currently 36%). No log throttling on the sync error path.
3. **Hardcoded secret in config** — `passwordSecret=toswm#0501` (config.ini:52) committed in
   plaintext; the comment says it should be RANDOM. Also `authMode=anonymous` (:30) and running
   **plain HTTP** (certFile/keyFile commented out, :37/:44) → viewer/API unauthenticated + cleartext.
4. **Stale editor swap files left in prod** — `/logs/mnxcapture/.capture.log.swp` and `.swp`
   (0-byte, Jul 6) indicate someone `vi`-ed the live log directory; a live `suricata.yaml.bak`
   (83 KB) sits in `/opt/mnx/etc`. Config-hygiene/drift smell.
5. **Config drift / dual config systems** — `config.ini` (Arkime) vs `mnx_config.json` (in-house
   stack) both define pcap dir & ES; `pcapDir=/pipeline/raw` but actual bytes in `/data/raw` via
   symlinks and mnxdpi reads `/data/raw` directly. Two sources of truth for the same paths; easy
   to misconfigure. `libmnxdpi_port=9500` configured but unused (socket used instead).
6. **Large set of unused plugins/parsers shipped** — only `suricata.so;libmnxdpi.so` loaded, yet
   11+ other plugins (`lua.so`, `netflow.so`, `tagger.so`, `wise.so`, `writer-s3.so`, `chad.so`…)
   and possibly several parsers are dead weight in the load dir — maintenance + attack surface.
7. **Mojibake / broken i18n comments** in config.ini (lines 67-68, 77) — legacy non-UTF8 Korean
   comments; cosmetic but signals uncontrolled edits.
8. **`dbEsHealthCheck=false`** (:314) — capture won't pre-check ES health, contributing to the
   blind retry-loop failure mode in §11 (starts hammering a sick ES instead of waiting).

---

## 13. Cross-references

- **mnxdpi** (see doc 03) — downstream deep-inspection engine; fed by `libmnxdpi.so` via
  `/var/run/mnxdpi.sock` + `/pipeline` workspace; reads pcap from `/data/raw`; carves to
  `/data/payload`. PID 18076, 8.3 GB RAM, `-c /opt/mnx/etc/mnx_config.json`.
- **Elasticsearch/OpenSearch** (see doc: ES) — `:9200`; session indices `mnx_sessions3-*`,
  sequence `mnx_sequence_v30`; the flood-stage block here is what broke capture.
- **Kafka** (see doc: kafka) — `:9092`, topic `request-file-analysis`; NOT touched by capture,
  used by mnxdpi→payload_analysis.
- **payload_analysis / scanengine / file_analysis_ai** (see doc: payload) — consume mnxdpi output;
  sockets `/var/run/payload_scanengine.sock`, `/var/run/payload_ai_analysis.sock`; output to ES
  `payload_`/`ai_content-`/`mail_content-` indices.
- **Suricata** — writes `/logs/suricata/eve.json`, ingested by `suricata.so` into MNX sessions;
  also driven by `regression_api` (`:8000`).
- **Web / core API** (see doc: web) — mnx_web java on `:8443`; mnxdpi/service_control heartbeat to
  `https://localhost:8443/api/server/module/save`. Arkime **viewer/wise/cont3xt/parliament**
  (node) are the JS UI tier bundled under `/opt/mnx` with the vendored node-v20.19.4 runtime.

---
*End of research doc 02.*
