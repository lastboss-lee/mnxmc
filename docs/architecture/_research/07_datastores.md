# 07 — Data Stores (MariaDB · Elasticsearch · Kafka · Zookeeper · Redis)

> Formal architecture handover research. Every claim is grounded in a command/file cited inline.
> Items that could not be directly verified are marked **추정(unverified)**.
> Collected: 2026-07-10. Host node: `node-1` / `10.10.1.116`.

---

## 1. Overview

| Store | Process (evidence) | Bind / Port | On-disk size | Status |
|---|---|---|---|---|
| **MariaDB** | `mariadbd` pid 1347 (`ps aux`) | `127.0.0.1:3306` (`ss -tlnp`) | datadir `/var/lib/mysql` = **243 MB** (`du -sh`); `mnx_db` logical = **41.8 MB** | Running |
| **Elasticsearch** | `java … org.elasticsearch.bootstrap.Elasticsearch` pid 15810, `-Xms4g -Xmx4g` | `*:9200` (REST) + `*:9300` (transport) | `/application/es/data` = **18 GB**; cluster alloc **18.1 GB used / 1.8 GB avail = 90%** (`_cat/allocation`) | Running, cluster `mnx`, **green**, v**7.17.29** (single node) |
| **Kafka** | `java … kafka.Kafka …/server.properties` pid 17016, `-Xmx1G` | `*:9092` | logs `/logs/kafka/kafka-logs` | Running, broker.id 0, v**3.8.0** (Scala 2.13) |
| **Zookeeper** | `java … QuorumPeerMain …/zookeeper.properties` pid 16373, `-Xmx512M` | `*:2181` | `/logs/kafka/zookeeper` | Running, v3.8.4 (bundled with Kafka) |
| **Redis** | — | — | — | **NOT PRESENT** (see §6) |

**Data-plane summary:** Elasticsearch is the primary high-volume store (network session/flow metadata, ~16 M docs, growing daily). MariaDB `mnx_db` is a small relational config/state DB for the management application (users, playbooks, issues, blacklists, settings). Kafka carries a single work-queue topic for asynchronous file/payload analysis. Zookeeper exists only to support this Kafka broker.

**Elasticsearch v7 vs. Arkime lineage:** the ES metadata index names (`mnx_sessions3`, `mnx_fields`, `mnx_files`, `mnx_sequence`, `mnx_hunts`, `mnx_views`, `mnx_lookups`, `mnx_stats`, `mnx_dstats`), the `config.ini` keys (`rotateIndex`, `passwordSecret`, `httpRealm=Moloch`), and the `/opt/mnx/bin/capture` binary show MNX's capture/viewer layer is an **Arkime/Moloch-derived** engine (rebranded `mnx_*`). Evidence: `/opt/mnx/etc/config.ini`, `ps aux` (`/opt/mnx/bin/capture -c /opt/mnx/etc/config.ini`).

---

## 2. MariaDB — `mnx_db`

- **Server:** MariaDB, `mariadbd` on `127.0.0.1:3306`, datadir `/var/lib/mysql`.
- **Databases** (`mysql -N -e 'show databases'`): `information_schema`, **`mnx_db`**, `mysql`, `performance_schema`, `sys`.
- **Auth / access:** local `root` via **unix-socket auth** (verified: `mysql -uroot` works with no password). Application account is **`mnx`@`%`** — the only grantee on `mnx_db` (`information_schema.schema_privileges`). The `mnx` password is Jasypt-encrypted inside the API jar; the Jasypt master key is exposed as `JASYPT_PASSWORD=Toswm#0501` in `/opt/mnx_web/docker-compose-api-10g.yml` (see §2.3). **推定(unverified):** the plaintext `mnx` DB password (not decrypted here).
- **Engine/charset:** every table `ENGINE=InnoDB`, `utf8mb4 / utf8mb4_general_ci`.
- **63 tables**, total 41.8 MB. Only three tables are large; the rest are config/lookup with 0–few-thousand rows.

### 2.1 Which service uses it
The **Spring Boot core API** container `mnx_api_server` (image `mnx-api-v23:v23.5.1.2`, `app.jar`, `-Xmx80g`, listening `*:8443`) is the MariaDB client — Hibernate/JPA idioms are visible in the schema (`FKnti3ie21qir4x4dhmjq179lg8` FK names, `updated_at datetime(6)` audit columns). Evidence: `ps -o args -p 2294` → `java … -jar app.jar`; `docker ps`; `mnx_config.json` `manage_web.core_api_url = https://127.0.0.1:8443`. The `mnxmc` TUI (this repo) does **not** connect to MariaDB — it shells out to monitor Kafka/ES/system only (`/mnxmc/modules/kafka_monitor.py`, `elasticsearch_monitor.py`). **推定:** the web UI container `mnx_web_server` talks to the API, not directly to the DB.

### 2.2 Table catalog

Row counts from `information_schema.tables` (approximate for InnoDB); DDL from `mysqldump --no-data`. Purposes inferred from name + column comments (Korean comments are authoritative; inference marked 추정).

#### Users, auth, audit
| Table | Rows | Key columns | Purpose |
|---|---|---|---|
| `user_tbl` | 0* | PK `idx`; `m_id`,`m_pw`,`m_name`,`m_email`,`supervisor`,`api_key`,`m_start_ip`/`m_end_ip`,`login_attempt_count` | Console user accounts, role (`supervisor`), per-user API key, IP allow-range, login lockout. (*0 rows = app-managed elsewhere or seeded at runtime; 추정) |
| `user_network_interface_mapping` | 1 | FK `user_idx`→`user_tbl`, FK `network_interface_idx`→`network_interface_info` | Which network(s)/interfaces a user may view (multi-tenant/망 separation). |
| `secui_auth` | 0 | PK `idx`, uniq `client_id`; `client_pw`,`duration` | Credentials + block-duration for **SECUI firewall** blocking integration (추정 from `duration` "차단 기간"). |
| `audit_tbl` | 83 | PK `log_idx`; `menu_no`,`m_id`,`exps`,`m_ip`,`reg_time`,`detail_type`,`audit_cat` | Audit log of console actions (create/modify/delete, severity category). |
| `audit_menu_tbl` | 13 | PK `idx`; `menu_no`,`menu_name`,`menu_order`,`menu_cat` | Lookup of audit menu numbers → names. |

#### Insight / detection (the SOC core)
| Table | Rows | Key columns | Purpose |
|---|---|---|---|
| `insight_tbl` | 4,380 | PK `idx`; `network_interface_idx`,`playbook_name`,`detect_key`,`detect_condition`,`issue_date`,`issue_status`(1 new/2 in-progress/3 done/4 stat),`detect_type`(1 AI/2 SIGNATURE/3 CTX/4 CUSTOM/5 FILE),`risk_level` | **Detected issues / alerts** (the case queue). Indexed on issue_date/status. |
| `insight_issue_item_tbl` | 3,829 | PK `insight_idx`→`insight_tbl`; `issue_item longtext` | Heavy payload of each issue (detection JSON). 1:1 with issue. Largest metadata table (~9.7 MB). |
| `insight_detect_ip_tbl` | 16,060 | PK `idx`; `insight_idx`,`ip_type`(1 src/2 dst),`ip_address`(bigint long),`is_private`,`country_code` | Src/dst IPs per issue. **Highest-row table (16 k).** |
| `insight_suricata_signature_tbl` | 217 | `insight_idx`,`suricata_signature` | Suricata signatures that fired for an issue. |
| `insight_status_log_tbl` | 0 | `issue_idx`,`issue_status`,`issue_changer`,`issue_change_date` | Issue status-change history. |
| `insight_playbook_tbl` | 97 | PK `idx`; `playbook_name`,`grace_period`,`action`(notify/slack/mail/syslog),`is_active`,`risk_level`,`detect_type` | Playbook definitions (detection rules → actions). |
| `insight_scenario_tbl` | 97 | PK `idx`; `scenario_name`,`detect_condition`,`expression`(filter),`is_ai_model`,`exception_expression`,`detect_range`,`session_count`,`t_id_list`(MITRE ATT&CK T-IDs) | Scenario/rule bodies referenced by playbook steps. |
| `insight_playbook_step_tbl` | 97 | PK `idx`; FK `playbook_idx`→`insight_playbook_tbl` (CASCADE), FK `scenario_idx`→`insight_scenario_tbl` | Ordered scenario steps of a playbook. **Only real FK-constrained pair in DB.** |
| `insight_playbook_ai_comment` | 84 | PK `playbook_idx`; `ai_comment` | LLM-generated commentary per playbook. |
| `insight_playbook_exception_detect_keys_tbl` | 0 | `detect_key`,`playbook_idx` | Suppression keys (dedupe/exception) per playbook. |
| `insight_asset_ipv4_tbl` | 246 | PK `idx`; uniq(`network_interface_idx`,`ip_address`),`os_type`,`browser_type`,`c_class_network` | Discovered internal IPv4 assets + fingerprint. |

#### Threat intel / blacklists / feeds
| Table | Rows | Notes |
|---|---|---|
| `blacklist_ip_tbl` | 0 | PK `idx`; `start_ip`/`end_ip` + numeric range, indexed `idx_ip_range`. User IP blacklist (range-capable). |
| `blacklist_domain_tbl` | 0 | domain blacklist, indexed `idx_domain`. |
| `blacklist_hash_tbl` | 16 | PK `binary(32)` sha256, **PARTITION BY KEY 16**. File-hash blacklist. |
| `blacklist_ip_detect_tbl` / `blacklist_domain_detect_tbl` / `blacklist_hash_detect_tbl` | 0 | Per-interface last-detection tracking for each blacklist type. |
| `malicious_ip_query_tbl` | 0 | Cache of malicious/normal IP verdicts by date. |
| `external_ti_log` | 0 | PK `idx`; `ti_name`,`req_type`(1 hash/2 ip),`param_json`,`ti_result`(JSON-valid), `result_code`. Log of external threat-intel API calls. |
| `ctx_feed_ip_query_tbl` | 13 | **CTX (Cont3xt) feed** IP enrichment cache. **PARTITION BY RANGE(to_days(query_date))** into half-year partitions p2025h1…p2030h2 + pMax. |
| `ctx_feed_ports_query_tbl` / `ctx_feed_tags_query_tbl` / `ctx_feed_reasons_query_tbl` / `ctx_feed_reasons_reputation_query_tbl` | 13 each | Same partitioning; per-facet CTX enrichment (ports/tags/reasons/reputation). |
| `email_domain_leak_tbl` / `service_domain_leak_tbl` | 0 | Credential/email-leak counts by email+domain. |

#### Server / license / module state
| Table | Rows | Notes |
|---|---|---|
| `server_status_tbl` | **230,120** | PK `idx`; `hdd`,`cpu`,`mem`,`reg_time`,`email_send`. **Time-series health samples — largest table by row count/growth (~20 MB, no purge visible → growth risk).** |
| `server_module_tbl` | 2 | Per-module heartbeat + counters (drop/packet/session/tcp/udp counts). Written by module heartbeats (`mnx_config` `heartbeat_path=/api/server/module/save`). |
| `server_tbl` | 0 | Total mem/cpu/hdd capacity of host. |
| `server_license_tbl` / `set_license_tbl` | 0 | License key/type/dates, TI daily quota. |
| `network_interface_info` | 0* | PK `idx`, uniq `interface_name`; interface → nickname (망 이름). Referenced by many `network_interface_idx` columns. (*seeded at runtime; 추정) |
| `private_address_range` | 2 | Per-interface private-IP CIDR definitions. |
| `installation_info` / `version_tbl` | 0 | Install date; product version history + release-note/manual paths. |

#### Settings & jobs
| Table | Rows | Notes |
|---|---|---|
| `set_mail_tbl` | 0 | SMTP server/port/secure/id/**pw** (mail relay for reports/alerts). |
| `set_syslog_tbl` | 0 | Syslog forward target (TCP/UDP, `security_event` bitmask of which detections to forward). |
| `set_backup_tbl` / `set_backup_history_tbl` | 0 | Backup schedule (daily/monthly/weekly) + run history. |
| `set_data_reset_tbl` / `set_data_reset_history_tbl` | 0 | Data-purge (all/collected/analysis) state + history. |
| `set_detect_rule_tbl` | 0 | User detection-rule definitions (`rule_contents longtext`). |
| `set_logo_tbl` | 0 | Whitelabel logos + company text. |
| `set_user_ip_tbl` | 0 | Named IP groups (user-defined asset groups). |
| `set_report_mail_list_tbl` | 0 | Auto-report recipient list. |
| `suricata_rule_tbl` | **5,468** | PK `idx`, uniq `sid`; `rule_contents`,`rule_group`(1 default/2 user/3 exception),`rule_category`,`is_active`. **The Suricata ruleset of record** (~4.6 MB) — mirrored to `/etc/suricata` rules / `/application/custom-rule/suricata`. |
| `csv_history_tbl` | 0 | Async CSV export jobs (status/path/type). |
| `regression_analysis` | 0 | PCAP regression-test jobs for a Suricata rule (RESERVED/QUEUED/ANALYZING/DONE…), `job_id`,`pcap_progress`. Tied to the `regression_api` service (§7). |
| `stat_report_tbl` | 77 | Scheduled statistics-report jobs (status + effective date). |
| `sllm_report_tbl` | 0 | sLLM (small-LLM) generated report jobs. |
| `search_assistant` | 0 | Per-user saved AI search-assistant state (`longtext`). |
| `sns_slack_tbl` | 0 | Slack webhook config. |
| `splunk_env_tbl` / `splunk_hec_response_tbl` | 0 | Splunk HEC forward config + response log. |
| `*_auto_complete_tbl` (application/protocol/file_type/yara) | 442 / 39 / 0 / 0 | Search-box autocomplete dictionaries, populated from observed traffic. |

### 2.3 Relationships (ER)
The schema is **largely denormalized** — most cross-references are logical `*_idx` columns without DB-level FKs. Only two enforced FK relationships exist (`information_schema.key_column_usage`):
- `insight_playbook_step_tbl.playbook_idx` → `insight_playbook_tbl.idx` (CASCADE), `.scenario_idx` → `insight_scenario_tbl.idx`.
- `user_network_interface_mapping.user_idx` → `user_tbl.idx`, `.network_interface_idx` → `network_interface_info.idx`.

Logical hubs (join by convention, not FK):
- **`insight_tbl.idx`** ← `insight_issue_item_tbl`, `insight_detect_ip_tbl`, `insight_suricata_signature_tbl`, `insight_status_log_tbl` (all via `insight_idx`).
- **`network_interface_info.idx`** ← ~a dozen tables via `network_interface_idx` (multi-network/망 partitioning of nearly all data).
- **`user_tbl.m_id`** ← `audit_tbl.m_id`, `insight_status_log_tbl.issue_changer`, various `registered_by`/`user_id` string columns.

### 2.4 Notable design points
- **Partitioning:** `blacklist_hash_tbl` (KEY, 16 parts) and all `ctx_feed_*` tables (RANGE by half-year through 2030) — good for the intended write pattern but **`ctx_feed_*` has a `pMax` catch-all**, so post-2030 rows won't fail but won't be pruned automatically (추정 maintenance concern).
- **No visible retention/purge** for the two growth tables `server_status_tbl` (230 k rows) and `insight_*`; purge is app-driven via `set_data_reset_*` (推定).

---

## 3. Elasticsearch

- Single node `node-1`, cluster `mnx`, **green**, v7.17.29, heap 4 GB. Anonymous auth (`config.ini authMode=anonymous`, `mnx_config.json` `auth_id/auth_pw` empty, `tls:false`).
- **Writers:** `/opt/mnx/bin/capture` (Arkime engine) and `/opt/mnxdpi/mnxdpi` write session/flow docs; `mnxdpi` also has a tuned ES bulk consumer (`mnx_config.json` → `mnxdpi.elasticsearch.consumer`, 16 threads). `mnxdpi` strings confirm `%s/mnx_sessions3-%s/_search` and `mnx_sessions3-%02d%02d%02d`.
- **Readers:** the `mnx_api_server` Spring app (queries sessions to build insights/reports) and the `mnx_web` viewer.

### 3.1 Index catalog (`_cat/indices`, `_mapping`)

| Index / pattern | Purpose | Docs | Size | Key fields |
|---|---|---|---|---|
| **`mnx_sessions3-YYMMDD`** (daily) | **Primary session/flow (SPI) records** — the core NDR data. Prefix from `mnx_config` `incex_session_prefix=mnx_sessions3`. Rotation `daily` (`config.ini rotateIndex=daily`). | 260601: 19,872 · 260626: 6.78 M · 260627: 6.85 M · 260628: 1.86 M · 260630: 474,805 (**~16.0 M total**, `_cat/count`) | ~17.6 GB (7.3–7.5 GB per busy day) | **115 top-level fields**: `source`,`destination`,`network`,`http`,`dns`,`tls`(`cert`),`krb5`,`ldap`,`dhcp`,`bgp`,`irc`,`oracle`,`mysql`,`icmp`,`email`,`file`,`fileId`,`firstPacket`,`lastPacket`,`ipProtocol`,`initRTT`,`length`,`asset`,`event`,`mnx`,`@timestamp` (ECS + Arkime hybrid). |
| **`payload_YYMM`** (monthly) | **Extracted-file / payload analysis results.** Prefix `index_file_analysis_prefix=payload_`. Written by the file-analysis consumer (§4/§7). 6 primary shards. | 2604: 2,503 · 2605: 309 · 2606: 5,120 | ≤7 MB | `md5`,`sha1`,`sha256`,`payload_type`,`payload_size`,`classification`,`av`,`vt`(VirusTotal),`yara`,`ai`,`ctx`,`url`,`session_id`,`source`,`destination`,`tags`. |
| **`net-stats-YYYYMM`** (monthly) | **Interface throughput time-series** (network-stats template). | 202604: 134 k · 202605: 464 k · 202606: 190 k · 202607: 6,631 | ≤33 MB | `interface`,`original_interface`,`mbps`,`pps`,`timestamp`,`@timestamp`. |
| **`playbook-YYYY`** (yearly) | **Playbook detection hits** linked to MariaDB `insight_tbl` via `insight_idx`. | 47,859 | 6.3 MB | `insight_idx`,`playbook_risk_level`,`session_id`,`source`,`destination`,`firstPacket`,`lastPacket`,`tags`,`mnx`. |
| `mnx_fields_v30` (alias `mnx_fields`) | Arkime field definitions/UI metadata. | 409 | 100 KB | — |
| `mnx_files_v30` (`mnx_files`) | **PCAP file registry** (which raw pcap files exist on disk). | 289 | 162 KB | — |
| `mnx_sequence_v30` (`mnx_sequence`) | Monotonic sequence/ID counters. | 1 | 3 KB | — |
| `mnx_stats_v30` / `mnx_dstats_v30` | Node stats / detailed time-series stats. | 1 / 3,442 | 15 KB / 1.5 MB | — |
| `mnx_hunts_v30` (`mnx_hunts`) | Packet-hunt (deep search) jobs. | 0 | — | — |
| `mnx_lookups_v30` (`mnx_lookups`) | Shared value lookups (WISE-style). | 0 | — | — |
| `mnx_views_v40` (`mnx_views`) | Saved search views. | 0 | — | — |
| `mnx_notifiers_v40` (`mnx_notifiers`) | Notifier definitions. | 0 | — | — |
| `.geoip_databases` | ES GeoIP DB store. | 0 | 250 B | — |
| `.ml-*`, `.monitoring-*`, `ilm-history-*`, `.logs-deprecation.*`, `.watcher-*`, `.slm-*` | ES/X-Pack internal (ML, monitoring, ILM history, deprecation logs). | small | — | — |

**Templates present but no live index yet (推定 — feature enabled, no data):** `email-template` → `mail_content-*` and `ai-content-template` → `ai_content-*` (prefixes `index_mail_content_prefix=mail_content-`, `index_ai_content_prefix=ai_content-` in `mnx_config`; `payload_analysis` binary strings show `ai_contents_chatgpt_group_conversations` → extracts AI-chat / email content from payloads).

### 3.2 Templates (`_cat/templates`)
MNX-specific legacy (v1) templates: `mnx_sessions3_template` (order 99) + `mnx_sessions3_ecs_template` (order 1) for `mnx_sessions3-*`; `network-stats` for `net-stats-*`; `payload` for `payload_*`; `playbook-template` for `playbook-*`; `email-template`, `ai-content-template`, `mnx_history_v1_template`. Remainder are stock ES/X-Pack composable templates.

### 3.3 ILM / rollover
- **MNX data indices are NOT ILM-managed.** All 15 ILM policies present (`7/30/90/180/365-days-default`, `metrics`, `logs`, `ml-*`, etc.) are **built-in ES defaults**, and `_ilm/policy` shows their `in_use_by.indices` is empty except for ES-internal data streams (`ilm-history-5`, `.logs-deprecation…`). An `_ilm/explain` on `mnx_sessions3/payload/net-stats/playbook` returns no managed policy.
- **Retention is instead handled by the Arkime layer**: `config.ini rotateIndex=daily` creates a new `mnx_sessions3-*` per day; old-index deletion is done by MNX cron/expire logic (推定 — no ILM, and no explicit expire setting seen in the truncated `config.ini`; the `set_data_reset_*` tables suggest app-driven purge).

---

## 4. Kafka

- Broker v3.8.0, `broker.id=0`, single node, **Zookeeper mode** (not KRaft): `zookeeper.connect=localhost:2181`. Config `/usr/local/kafka/config/server.properties`.
- Log dir `/logs/kafka/kafka-logs`. `num.partitions=1`. All replication factors **=1** (`offsets.topic.replication.factor=1`, `transaction.state.log.replication.factor=1`) — **no redundancy** (single-node).
- **Default retention `log.retention.hours=168` (7 days)**; check interval 5 min.

### 4.1 Topic catalog (`kafka-topics.sh --describe`)
| Topic | Partitions | RF | Configs | Producer (evidence) | Consumer (evidence) |
|---|---|---|---|---|---|
| **`request-file-analysis`** | 1 | 1 | (defaults → 7-day retention) | **`mnxdpi`** — binary strings show `librdkafka++`, `RdKafka::Producer`, `localhost:9092`, `request-file-analysis`. Config `mnx_config.json` `kafka.payload_config.payload_analysis_topic`, `enable:true`. | **`payload_analysis`** service, consumer **group `mnx`** — `mnx_config` `payload_analysis_groupname=mnx`; `kafka-consumer-groups --describe --group mnx` shows one consumer on this topic (CURRENT=LOG-END=**4263, lag 0**), host 127.0.0.1. |
| `__consumer_offsets` | 50 | 1 | `compact`, `segment.bytes=104857600` | Kafka internal | Kafka internal |

**Flow:** `mnxdpi` extracts files/payloads from captured traffic (`mnx_config` `payload.enabled=true`, `payload_binary=/data/payload`) and **produces a "please analyze this file" message** to `request-file-analysis`. The single-threaded C++ **`payload_analysis`** daemon (`/opt/payload_analysis/payload_analysis -d -c …mnx_config.json`, via `start.sh`) consumes them, runs AV/YARA/VirusTotal/AI (`/opt/file_analysis_ai` models exe/dll, `/opt/payload_analysis/file_type.yar`) and **writes results to ES `payload_*`** (and `ai_content-*`/`mail_content-*` when applicable). 4,263 files processed lifetime, no backlog.

---

## 5. Zookeeper role
Single Zookeeper (`QuorumPeerMain`, v3.8.4, bundled with the Kafka distribution) exists **only to back this Kafka broker** — it holds broker registration, topic/partition metadata, controller election, and consumer-group coordination for the 3.8.0 broker running in ZK (non-KRaft) mode (`server.properties zookeeper.connect=localhost:2181`; `zookeeper.properties dataDir=/logs/kafka/zookeeper clientPort=2181`). No MNX application data is stored in Zookeeper. Because Kafka carries only the low-volume file-analysis queue, ZK is a low-criticality dependency of that one pipeline.

---

## 6. Redis — NOT USED
**Evidence of absence:**
- No process: `ps aux | grep redis` → none.
- Nothing listening on 6379: `ss -tlnp | grep 6379` → none.
- Only references to "redis" anywhere in configs are **commented-out samples**: `/opt/mnx/etc/wise.ini.sample` (optional WISE cache, commented), and `/opt/mnx/etc/suricata.yaml.bak` (eve-log `redis` output type, commented; active output is `filetype: regular`).

**Conclusion: Redis is not deployed or used by MNX on this host.** It is only mentioned as an *optional* cache in upstream (Arkime WISE / Suricata) sample files.

---

## 7. Log-shipping pipeline (Suricata / capture → Kafka / ES)

**No Logstash and no Filebeat exist** (`ls /etc/logstash /etc/filebeat /opt/logstash` → none; `ps aux` → none). Ingestion is done entirely by MNX-native binaries.

```
                 ┌───────── ens192 (mirror/tap, af-packet) ─────────┐
                 ▼                                                   ▼
        /opt/mnx/bin/capture (Arkime)                    suricata --af-packet
        + /opt/mnxdpi/mnxdpi  (DPI)                       (/etc/suricata/suricata.yaml)
                 │                                                   │
   ┌─────────────┼───────────────────────────┐              writes eve.json
   ▼             ▼                            ▼              /logs/suricata/eve.json
 ES mnx_sessions3-*   Kafka topic          ES net-stats-*      (regular file, ~6 MB)
 (session/flow SPI)   request-file-analysis  (throughput)             │
                          │                                           ▼
                          ▼                                (ingested into sessions/
                 payload_analysis (group mnx)               alerts by MNX engine — 추정)
                          │
                          ▼
                 ES payload_* / ai_content-* / mail_content-*
```

- **Sessions → ES:** verified via `mnxdpi` strings (`mnx_sessions3-*`, `_search`) + Arkime `capture` process + `mnx_config` ES consumer tuning.
- **Raw pcap:** `capture`/`mnxdpi` read `/pipeline/raw` & `/data/raw` (`mnx_config` `pcap.path=/data/raw`, base_path `pcap=/pipeline/raw`); pcap file inventory tracked in ES `mnx_files_v30`.
- **Files → Kafka → ES payload_*:** verified (§4).
- **Suricata eve.json → ES:** Suricata writes `/logs/suricata/eve.json` as a plain file (`default-log-dir: /logs/suricata`, `eve-log filetype: regular`). The **only process holding eve.json open is suricata itself** (checked every `/proc/*/fd`). **推定(unverified):** the eve.json alerts are folded into ES sessions/`insight` by an MNX component (likely `mnxdpi`/`capture` or the API on a cron) — no `eve.json` string was found in `mnxdpi`/`capture`/`config.ini`, so the exact reader was not confirmed. The strong link is that Suricata signatures end up in `insight_suricata_signature_tbl` and `mnx_sessions3` carries `event`/`message` fields, implying alert correlation happens downstream.
- **Regression testing:** `python3.12 /opt/regression_api/app.py /opt/mnx/etc/mnx_config.json` (port 8000) replays pcaps against Suricata rules; state in MariaDB `regression_analysis`.
- **Outbound:** syslog (`set_syslog_tbl`), Slack (`sns_slack_tbl`), Splunk HEC (`splunk_env_tbl`/`splunk_hec_response_tbl`), email (`set_mail_tbl`) — all driven by the API.

---

## 8. Failure impact per store

| Store | If it goes down | Blast radius |
|---|---|---|
| **Elasticsearch** | **Critical / total.** All session, payload, net-stats, playbook data + Arkime metadata (fields/files/sequence/views) become unreadable/unwritable. Capture/mnxdpi bulk writes fail → ingest backpressure & data loss once buffers fill. UI search, insights, reports all break. **Single node = no HA; currently at 90% disk (1.8 GB free) → imminent write-block risk (flood-stage watermark 95%).** |
| **MariaDB** | **High.** API cannot load users/login, playbooks, scenarios, issue queue, blacklists, settings, Suricata ruleset of record. Detection config and case management stop; live packet capture to ES continues (capture doesn't use MariaDB). |
| **Kafka** | **Medium/localized.** Only the file-analysis queue. `mnxdpi` producer sends fail → new files not queued (payload analysis stalls / possible drop after 7-day retention or producer buffer limits). Session capture, net-stats, and detection on non-file signals continue. |
| **Zookeeper** | **Medium (== Kafka).** Kafka broker cannot elect controller / serve metadata → same effect as Kafka down. No other subsystem depends on ZK. |
| **Redis** | None (not used). |

Aggravating factor across all: **every store is single-instance, RF=1, no replication** — any node/disk loss is unrecoverable without backups.

---

## 9. Backup & retention

| Store | Retention | Backup |
|---|---|---|
| **ES `mnx_sessions3-*`** | Daily index rotation (`config.ini rotateIndex=daily`); deletion app/cron-driven (推定 — **no ILM bound**). | ES `_state/snapshot_cache` dir exists but **no snapshot repository/SLM policy is in use** (all SLM history empty). **推定: no ES snapshots configured.** |
| **ES `payload_*`/`net-stats-*`/`playbook-*`** | Monthly/yearly indices; no ILM. | Same — none verified. |
| **MariaDB `mnx_db`** | Growth tables (`server_status_tbl`, `insight_*`) have no visible auto-purge. | Schedule table `set_backup_tbl` (cycle daily/monthly/weekly) + `set_backup_history_tbl` exist and are app-driven; **both currently empty (0 rows) → 推定 no backup schedule is active.** `csv_history_tbl` has `backup_path/backup_target` columns (export archival). |
| **Kafka** | `log.retention.hours=168` (7 days) default. | Not backed up (transient queue). |

**Data-reset tooling:** `set_data_reset_tbl` / `set_data_reset_history_tbl` (all/collected/analysis purge) is the operator-facing purge mechanism. `/mnxmc/infra_audit/backup_*` dirs are mnxmc's own config backups, not datastore backups.

---

## 10. Cross-references

- **Credentials/config sources:** `/opt/mnx/etc/mnx_config.json` (ES+Kafka endpoints, prefixes, payload topic), `/opt/mnx/etc/config.ini` (Arkime capture/viewer, ES URL, rotateIndex, passwordSecret), `/opt/mnx_web/docker-compose-api-10g.yml` (`JASYPT_PASSWORD`), `/etc/suricata/suricata.yaml` (eve.json outputs).
- **Producers/consumers of ES:** `/opt/mnx/bin/capture`, `/opt/mnxdpi/mnxdpi`, `/opt/payload_analysis/payload_analysis`, `mnx_api_server` (8443), `mnx_web_server`.
- **MariaDB client:** `mnx_api_server` (Spring Boot `app.jar`, user `mnx`@`%`).
- **Related handover docs:** capture/DPI pipeline (mnxdpi, payload, suricata) and the API/web tier are covered in their own subsystem reports; this doc is authoritative for **schema, index catalog, topic catalog, and retention/backup posture**.
- **Full DDL dump** captured to scratch: `mnx_schema.sql` (all 63 `CREATE TABLE` statements) — regenerate with `mysqldump -uroot --no-data --skip-comments --compact mnx_db`.

### Top risks (for handover attention)
1. **ES disk at 90% (1.8 GB free), single node, no snapshots** — highest operational risk; will hit the read-only flood watermark soon.
2. **No replication anywhere (ES/Kafka/MariaDB RF=1)** — no HA, no automatic recovery from disk/node loss.
3. **No verified backups** for ES or MariaDB (backup schedule tables empty; no SLM).
4. **MNX data indices not ILM-managed** — retention relies on app/cron logic that was not directly evidenced; risk of unbounded growth if that logic fails.
5. **Unbounded MariaDB growth tables** (`server_status_tbl` 230 k rows and climbing; `insight_*`) with no visible purge.
6. **Anonymous ES + plaintext HTTP** on 9200/9300 (bound to all interfaces `*`) — access-control gap (mitigated only if network-isolated).
