# 05 · Web UI + API (Docker) + Nginx Reverse Proxy

> Subsystem architecture handover. Every claim is grounded in on-box evidence (`file:line` or command output). Items that could not be verified are marked **추정(unverified)**.
> Investigated: 2026-07-10 on the live host. Product: MNX NDR v23.

---

## 1. Overview

Two Docker containers plus a host-visible nginx (which is actually the web container's nginx, see below) make up the presentation + API tier.

| Component | Image | Framework | Listen | Status | Evidence |
|---|---|---|---|---|---|
| `mnx_web_server` | `mnx-web-v23:v23.5.1.2` | Nginx serving a **built Vue SPA** (static) | 80, 443, 8090 | Up (restart=always) | `docker ps`; `docker inspect mnx_web_server` |
| `mnx_api_server` | `mnx-api-v23:v23.5.1.2` | **Spring Boot** (Java 17, `app.jar`) — NOT FastAPI | 8443 (HTTPS) | Up (restart=always) | `docker exec … ps aux` → `java … -jar app.jar`; `application.yml server.port: 8443` |

Key correction vs. the initial hypothesis: the API server is a **Spring Boot / Java** application, not a Python/FastAPI service. The only Python REST service on the box is a *separate* host process `regression_api` (see §4/§8), not one of the two containers.

- Both containers run `network_mode: host` — they share the host network namespace, so their listening sockets appear directly on the host (this is why nginx master pid 2254 is visible on the host though it lives inside `mnx_web_server`). Evidence: `docker-compose-*.yml` `network_mode: host`; `readlink /proc/2254/exe → /usr/sbin/nginx` returns "No such file" on the host (binary only exists in the container mount ns).
- Image build date 2026-03-25 (`docker image inspect`). Both started 2026-07-10T00:57:50 (`docker inspect … .State.StartedAt`).
- Active traffic profile at time of survey: **1g** (`SPRING_PROFILES_ACTIVE=1g` in API env; `env.js` `VUE_APP_TRAFFIC:"1g"`). Note inconsistency: `web_config.ini` says `max-traffic=10G` (see §6/§11).

Base images:
- API: **Ubuntu 22.04.5 LTS**, OpenJDK **17.0.18**, image size ~1.95 GB (`docker exec mnx_api_server cat /etc/os-release`; `java -version`; `docker image inspect`).
- Web: **Alpine Linux**, nginx **1.28.2**, image size ~331 MB (`docker exec mnx_web_server nginx -v`).

---

## 2. Nginx (reverse proxy + SPA host)

Nginx runs **inside `mnx_web_server`** (Alpine, nginx 1.28.2). Master process appears on host as pid 2254 with 12 workers (pids 2282–2293) due to host networking. Config lives in the container at `/etc/nginx/`.

- `/etc/nginx/nginx.conf` — standard http block, `include /etc/nginx/conf.d/*.conf;`. Log format `main`, `keepalive_timeout 65`, gzip off at http level (enabled per-server).
- `/etc/nginx/conf.d/default.conf` — all server blocks (4694 bytes).
- No `sites-enabled/`; single conf file.

### Server blocks (from `docker exec mnx_web_server cat /etc/nginx/conf.d/default.conf`)

**Block A — port 80 (plain HTTP):**
```
listen 80; listen [::]:80; server_name localhost;
return 301 https://$host$request_uri;
```
→ Unconditionally redirects all HTTP to HTTPS.

**Block B — port 8090 (TLS, the actual SPA host):**
- `location /` → `root /usr/share/nginx/html; try_files $uri $uri/ /index.html;` — serves the built Vue SPA.
- `location /mnx-ui-guide` → alias to Storybook static build.
- gzip on for text/js/css/json/svg.
- TLS: `server.crt` / `server.key` / password file `ssl.pass`.

**Block C — port 443 (TLS, `default_server`, the public front door):**
- `client_max_body_size 150M`.
- `location /` → `proxy_pass https://127.0.0.1:8090;` (loops back to Block B to serve the SPA).
- `location /api` → `proxy_pass https://127.0.0.1:8443;` (the Spring Boot API). Streaming-tuned: `proxy_buffering off`, `proxy_request_buffering off`, `proxy_http_version 1.1`, `Connection ''`, timeouts 900s. Sets `Host`, `X-Real-IP`, `X-Forwarded-For`.
- `location /mnx/api` → `rewrite ^/mnx/api(/.*)?$ /api$1 break;` then `proxy_pass http://127.0.0.1:8005;` (plain HTTP). Adds permissive CORS (`Access-Control-Allow-Origin *`, methods GET/POST/OPTIONS) and handles OPTIONS preflight. **NOTE: nothing is currently listening on 8005** (`ss -tlnp` shows no `:8005`) — this route is dead/optional at present. 추정(unverified): likely an auxiliary/dev API.
- There is a commented-out earlier `location /api` variant retained in the file.

### Port routing map (nginx)
| Ingress | Handler | Backend |
|---|---|---|
| **80** | redirect | → 301 `https://$host` |
| **443** `/` | proxy | → `https://127.0.0.1:8090` (SPA via same nginx) |
| **443** `/api` | proxy (streaming) | → `https://127.0.0.1:8443` (Spring Boot API) |
| **443** `/mnx/api` | rewrite→proxy + CORS `*` | → `http://127.0.0.1:8005` (no listener — dead) |
| **8090** `/` | static | SPA files `/usr/share/nginx/html` |
| **8090** `/mnx-ui-guide` | static | Storybook build |

### TLS certificates (`/etc/nginx/ssl/`)
Files: `certificate.pfx`, `server.crt`, `server.key`, `server.csr`, `ssl.pass`.
- `ssl.pass` content: **`mnx#123`** (private-key passphrase, world-readable in image — plaintext secret).
- Certificate is a **self-signed placeholder** and **EXPIRED**:
  - subject/issuer = `C=AU, ST=Some-State, O=Internet Widgits Pty Ltd` (OpenSSL default demo cert)
  - `notBefore=Oct 16 2023`, `notAfter=Oct 15 2024` — **expired ~21 months ago**. Evidence: `openssl x509 -in server.crt -noout -subject -issuer -dates`.
- Java API keystore is a separate `classpath:certificate.pfx` (inside the jar) with jasypt-encrypted password (§4).

### 8443 (java) vs 8000 (python) relationships
- **8443** = the Spring Boot API container (`java … app.jar`, host pid 2294). Nginx `/api` proxies here.
- **8000** = a **separate host Python service** `python3.12 /opt/regression_api/app.py /opt/mnx/etc/mnx_config.json` (host pid 18814). It is NOT proxied by this nginx's `/mnx/api` (that points at 8005). Instead, the **Spring API calls it internally**: `application.yml` sets `regression.api.base-url: http://localhost:8000` and `secui.base-url: http://localhost:8000`. So 8000 is a backend-of-a-backend (regression/replay analysis + SECUI integration), reached server-to-server from the Java app, not from the browser.

---

## 3. Docker Compose files

Location: `/opt/mnx_web/` — four files (there are **no** compose files under `/application/mnx_web/`; that tree holds runtime data dirs: `apikey/ asset/ blackbox/ dashboard/ mitre_attack/ monitor/ report/`).

### API compose — `docker-compose-api-{1g,10g}.yml`
```yaml
services:
  mnx_api_server:
    image: mnx-api-v23:v23.5.1.2
    container_name: mnx_api_server
    network_mode: host
    restart: always
    environment:
      - JASYPT_PASSWORD=Toswm#0501
      - SPRING_PROFILES_ACTIVE=1g   # (10g file: =10g)
      - SPRING_APPLICATION_JSON={"logging.level.root":"WARN"}
    volumes:
      - /application:/application
      - /logs:/logs
      - /etc/hostname:/etc/hostname:ro
      - /var/run:/var/run
      - /pipeline/raw:/pipeline/raw:ro
      - /data:/data:ro
      - /var/lib/GeoIP/GeoLite2-Country.mmdb:/var/lib/GeoIP/GeoLite2-Country.mmdb:ro
```
- **Only difference 1g vs 10g:** `SPRING_PROFILES_ACTIVE` (`1g` vs `10g`), selecting the bundled `application-1g.yml` / `application-10g.yml` profile.
- No `ports:` (host networking). `JASYPT_PASSWORD=Toswm#0501` is the jasypt master key used to decrypt all `ENC(...)` config values — a plaintext secret in the compose file.
- `/var/run` mount gives access to the Unix control socket `/var/run/service_control.sock` (§4).

### Web compose — `docker-compose-web-{1g,10g}.yml`
```yaml
services:
  mnx_web_server:
    image: mnx-web-v23:v23.5.1.2
    container_name: mnx_web_server
    network_mode: host
    restart: always
    logging: { driver: "none" }
    command: ["--traffic", "1g"]   # (10g file: "10g")
```
- **Only difference 1g vs 10g:** the `--traffic` arg.
- `logging: driver none` → container logs discarded.
- No volumes (SPA is baked into the image).
- Entrypoint `/entrypoint.sh` (from `docker inspect`): parses `--traffic`/`--non-active-menu`, writes `window.__ENV__ = { VUE_APP_TRAFFIC, VUE_APP_NON_ACTIVE_MENU }` to `/usr/share/nginx/html/env.js`, then `exec nginx -g 'daemon off;'`. So the traffic tier is injected into the SPA at container start via `env.js`.

Volumes exposed to the API container (evidence of data coupling): `/application` (rules, reports, insight, apikey, mitre, dashboard, asset, blackbox, backup), `/data` (payloads, ro), `/pipeline/raw` (ro), `/logs`, GeoIP DB.

---

## 4. API server (Spring Boot)

- **Framework:** Spring Boot (Spring Web MVC + Spring Security 5.6.3 + Spring Data Elasticsearch 4.3.4 + JPA/Hibernate). Package root `sandslab.mnx.api`.
- **Entrypoint / launch:** container CMD `sh -c "ldconfig && java $JAVA_OPTS -jar app.jar"` (via `/__cacert_entrypoint.sh`). `JAVA_OPTS=-Dpcap4j.useDummyNif=true -Xmx80g -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/application/mnx_web/heapdump.hprof -Duser.timezone=Asia/Seoul`. Heap max **80 GB**. `app.jar` = 252 MB fat jar at `/app.jar`.
- **Listen port:** `8443` HTTPS (`server.port: 8443`, `server.ssl.enabled: true`, `key-store: classpath:certificate.pfx`). Confirmed by `ss` (java pid 2294 on `*:8443`).
- **Config source:** `BOOT-INF/classes/application.yml` + profile `application-{1g,10g}.yml` (also `-dev/-kisa/-local` exist). Secrets are jasypt-encrypted `ENC(...)` decrypted with `JASYPT_PASSWORD` env (jasypt-spring-boot-starter 3.0.5).

### Datastore & external connections (config evidence, all from `application.yml`)
| Target | Config | Notes |
|---|---|---|
| **MariaDB** | `spring.datasource.url: jdbc:mariadb://localhost/mnx_db?characterEncoding=utf-8`, driver `org.mariadb.jdbc.Driver`, user/pass `ENC(...)` | HikariCP pool: base 150/idle50 (application.yml); **300/idle100 in both 1g & 10g profiles**. `max-lifetime 25m`, leak-detection 5m. JPA `ddl-auto: update`. Host MariaDB confirmed `127.0.0.1:3306` (mariadbd pid 1347). |
| **Elasticsearch** | `spring.elasticsearch.hosts: localhost`, `port: 9200`, `secure: false`, user/pass `ENC(...)` | Confirmed host ES on `*:9200` (java pid 15810). Indices: `payload_`, `net-stats-` (traffic), `mnx_sessions3-`, `mnx_files_v30`, `playbook-`, `mail_content-`, `ai_content-`. Clients: elasticsearch-java 8.3.3 + rest-high-level 7.15.2. |
| **Kafka** | **None** | No `kafka` config keys; **no kafka client jars** in `app.jar` (`jar tf | grep -i kafka` empty). Host Kafka on `*:9092` (java pid 17016) is used by *other* subsystems, not this API. |
| **Redis** | **None** | No redis/jedis/lettuce jars or config. The API does **not** use Redis. (Explicitly checked per task.) |
| **regression_api / SECUI** | `regression.api.base-url` & `secui.base-url: http://localhost:8000` | Server-to-server HTTP to the host Python service (§2). |
| **Unix socket** | `unix.socket-path: /var/run/service_control.sock` | Module/service control IPC to host daemon(s). `/var/run` bind-mounted. |
| **Threat-intel (outbound)** | `ti-path.*`: VirusTotal (`virustotal.com/api/v3`), CTX (`mnx-proxy.ctx.io`), criminal-ip/malwares (`public.api.malwares.com`), idpw (`mnx-api.idpw.io`) | External SaaS enrichment. |
| **GeoIP** | `country_code…: /var/lib/GeoIP/GeoLite2-Country.mmdb` | MaxMind country DB (mounted ro). |
| **SMTP/mail** | `mail-send.*` test config (from `d89745@gmail.com`) | Report/alert mail. |

Notable libs (`jar tf`): jjwt 0.11.2 (JWT), **Selenium 4.18.1 + `/chromedriver`** (headless-browser report/PDF rendering), pcap4j 1.8.2 (pcap parsing), gson 2.9.0 (preferred JSON mapper).

### Auth scheme (Spring Security)
Classes under `sandslab.mnx.api.filter` / `infrastructure.config`:
- `WebSecurityConfig`, `JwtFilter`, `JwtTokenProvider`, `JwtAuthenticationEntryPoint`, `JwtAccessDeniedHandler`, `ApiKeyAuthFilter`, `ApiKeyAuthenticationToken`, `HybridSecurityContextRepository`.
- **Hybrid auth:** JWT bearer token **and** servlet session (`JSESSIONID` cookie, `http-only`, `secure`, `same-site=none`, timeout 30m) coexist via `HybridSecurityContextRepository`.
- **JWT:** header `Authorization: Bearer <token>`, HMAC signing key `jwt.secret` (base64, hardcoded in yml — the value decodes to a "silvernine-tech-spring-boot-jwt-tutorial-secret…" tutorial string, a weak/known secret). `token-validity-in-seconds: 7200000` (ambiguous: literally ~83 days as seconds; likely treated as ms→2h — 추정(unverified), needs code confirmation).
- **API-key auth:** `ApiKeyAuthFilter` reads `X-API-KEY` or `Authorization: Bearer`, grants `ROLE_EXTERNAL_API` (client id `external-api-client`) for `/api/external/**`. Keys stored under `/application/mnx_web/apikey`.
- **Roles:** `ROOT`, `SUPER_ADMIN`, `ADMIN`, `MANAGER`, `EXTERNAL_API` (string constants in `WebSecurityConfig`).
- **Login:** RSA-assisted — `GET /api/auth/publickey` returns a public key; client encrypts the password; `POST /api/login` authenticates against `mnx_db` and issues the JWT (see §6 login flow).
- **permitAll (public) matchers** (from `WebSecurityConfig` constants): `/api/login**`, `/api/auth/publickey`, `/api/hostname`, `/api/logo/**`, `/api/packet/**`, `/api/collect/pcap/file/**`, `/api/license/check`, `/api/license/mnx-date`, `/api/license/ti-info/ctx`, `/api/insight/ai/detect`, `/api/insight/mitre/attack/all/tactics`, `/api/stat/report/data/**`, `/api/syslog/detect/contents`, `/api/syslog/list`, `/api/server/module/save`, `/api/server/module/save/list`, `/api/server/status/save`, `/api/server/status/server`, `/api/user/root/save`, `/application/regression/**`, `/error`. `/api/external/**` + `/api/ctx/**` are gated by API-key filter.

---

## 5. API endpoints

Base context path `/api`. Enumerated from decompiled controller annotations (`javap -v` on the 37 `*Controller.class` files). ~**244 mapped endpoints across 37 controllers**. Auth = authenticated (JWT/session) unless listed in the permitAll set in §4 (marked *public* / *apikey*). Table shows base path + representative/high-value routes per controller; full per-method list was extracted (counts below).

| Controller | Base | # | Auth | Purpose / notable routes |
|---|---|---|---|---|
| CommonController | `/api` | 1 | public | `GET /hostname` |
| AuthController | `/api/auth` | 2 | mixed | `GET /publickey` (public, RSA), `GET /refresh` (token refresh) |
| LoginController | `/api/login` | 1 | public | `POST /` — login, issues JWT |
| UserController | `/api/user` | 8 | auth | `POST list`, `POST save`, `POST root/save` (public bootstrap), `GET me`, `POST id-check`, `POST /opt`, `GET detail/{idx}`, `POST delete/{idx}` |
| AuditController | `/api/audit` | 2 | auth | `POST list`, `GET menu` (audit log) |
| BackupController | `/api/backup` | 6 | auth | `POST /execute`, `GET /status`, `GET /history`, `GET /file/download/{backup_idx}` |
| RestoreController | `/api/restore` | 5 | auth | `POST /environment/{backup_idx}`, `POST /environment/file/upload`, `GET /status` |
| DashboardController | `/api/dashboard` | 2 | auth | `GET /stat-all/{nif}`, `POST /3d/chart/{nif}` |
| MonitorController | `/api/monitor` | 1 | auth | `GET stat-all/{nif}` |
| DetectController | `/api/detect` | 13 | auth | snort/suricata/yara rule CRUD + validate (`POST rule/list`, `POST /rule/save`, `POST /suricata/rule/save/multi`, `PUT/DELETE /suricata/rule/{idx}`) |
| InsightController | `/api/insight` | 27 | auth | issues, scenarios, playbooks, MITRE mapping, LLM test (`POST /list`, `PUT /issue/status`, `POST /scenario`, `POST /playbook`, `POST /temp/llm/test`, `GET /mitre/attack/{idx}`) |
| InsightAssetController | `/api/insight/asset` | 12 | auth | asset/device/IP clustering stats (`POST /ipv4/list`, `POST /cluster/device/list/{nif}`) |
| BlackboxController | `/api/blackbox` | 10 | auth | per-day detection stats, `GET /file/download`, `GET /sid/contents/{sid}` |
| StatController | `/api/stat` | 14 | auth | traffic/app/protocol/file/IP statistics (`POST /protocols`, `POST /detect-src-ip`, `POST /file/download`) |
| ReportController | `/api/stat/report` | 4 | mixed | `POST /list`, `GET /download/{idx}`, `GET /data/{nif}` (public), `DELETE /{idx}` |
| CollectController | `/api/collect` | (0 parsed)* | mixed | pcap file endpoints exist under `/api/collect/pcap/file/**` (public) — parser missed (see note) |
| PacketController | `/api/packet` | 2 | public | `GET /{sessionId}/payload`, `GET /{sessionId}/pcap/file` |
| ContentsController | `/api/contents` | 3 | auth | `GET /mail/detail/{id}`, `POST /ai/list`, `GET /ai/detail/{id}` |
| InfoController | `/api/info` | 6 | auth | `GET /installation`, network interface list/detail (`GET/PUT /network/interface/...`), `POST /es-mapping` |
| ServerController | `/api/server` | 9 | mixed | module control + server spec/status (`GET module`, `POST module/save`, `GET spec`, `GET status/now`) — several save endpoints public |
| VersionController | `/api/version` | 2 | auth | `GET /list`, `POST /release/save` |
| LicenseController | `/api/license` | 27 | mixed | license + TI + CTX-feed + idpw aggregation (`GET /check` public, `POST ti-info`, `POST /ctx/feed/data`, `POST /idpw/domain/list`) |
| MaliciousIpController | `/api/malicious` | 12 | auth | malicious-IP detection stats (`POST /list`, country/reputation/risk `GET .../{topN}/{nif}`) |
| PrivateIpController | `/api/privateIp` | 3 | auth | `POST /list`, `POST /save`, `POST delete/{idx}` |
| UserIpController | `/api/user-ip` | 4 | auth | user-IP mapping incl. CSV bulk (`POST /save/multi/csv/{nif}`) |
| LogoController | `/api/logo` | 2 | public | `PUT ` (upload), `GET /{category}` |
| MailController | `/api/mail` | 8 | auth | mail server config + report mail (`POST save`, `POST mail-test`, `POST /report`) |
| RegressionAnalysisController | `/api/regression` | 7 | auth | replay/regression jobs (`POST /analysis/save`, `GET /analysis/{idx}/status`, `PUT /analysis/{idx}/cancel`) → backs onto :8000 |
| ExternalController | `/api/external` | 12 | apikey | external partner API (issues, mitre, payload, pcap, ti-info) |
| ExternalContentsController | `/api/external/contents` | 3 | apikey | mail/ai detail for external |
| ExternalCtxFeedController | `/api/external/ctx` | 16 | apikey | CTX feed ingest + detection statistics |
| ExternalFileController | `/api/external/file` | (0 parsed)* | apikey | file download for external (parser missed) |
| ExternalIdpwController | `/api/external/idpw` | 6 | apikey | idpw domain/email leak queries |
| SecuiController | `/api/secui` | 4 | auth | SECUI firewall integration (`POST /auth`, `POST /unblock`, `GET /blacklist/all`) |
| SnsController | `/api/sns` | 2 | auth | `POST /slack`, `GET /slack` (Slack notify) |
| SplunkHecController | `/api/splunk` | 2 | auth | `GET /env`, `POST /env/save` (Splunk HEC forwarding) |
| SyslogController | `/api/syslog` | 6 | mixed | syslog forwarding config; `POST /list`, `GET/PUT/DELETE /{idx}`, `POST /detect/contents` (public) |

\* Parser note: `CollectController` and `ExternalFileController` returned 0 methods because they use `@RequestMapping(method=...)` at method level (not the `@Get/PostMapping` shorthand the annotation parser matched). Their routes exist (e.g. `/api/collect/pcap/file/**` per the security config) but exact signatures were not decoded — 추정(unverified).

---

## 6. Web server

- **Framework:** **Vue.js** SPA, webpack-built. Evidence: `index.html` loads `/chunk-vendors.js` + `/app.js` + numbered `*.chunk.js`; runtime config `window.__ENV__ = { VUE_APP_TRAFFIC, VUE_APP_NON_ACTIVE_MENU }` in `env.js`; `<title>MNX</title>`, `lang="ko"`, meta description "IT/OT 트래픽 분석 및 APT 공격 탐지 NDR". A Storybook build ships at `/mnx-ui-guide`.
- **Build/serve model:** **static files served by nginx**, NOT Node SSR. Files under `/usr/share/nginx/html` (`app.js`, `chunk-vendors.js`, `css/`, `static/`, `icons/`, `favicon.ico`, `env.js`, `web_config.ini`). No node process in the container (`ps` shows only nginx master + workers).
- **Runtime config injection:** entrypoint rewrites `env.js` from the `--traffic` compose arg on every start.
- **API base URL:** the SPA is served from and calls the **same origin over 443**; nginx routes `/api/*` to the Java backend (8443) and `/` back to the SPA (8090). So the browser talks only to `https://<host>/api/...`; it never contacts 8443/8000 directly. (No absolute API host baked into `env.js`; only traffic tier + inactive-menu flags.)
- `web_config.ini`: `max-traffic=10G` (note: mismatches the running `--traffic 1g`; likely stale/baked default — 추정(unverified) which one wins in the UI).
- **Login/auth flow (end-to-end):**
  1. Browser loads SPA over `https://host/` (nginx 443 → 8090 static).
  2. SPA fetches `GET /api/auth/publickey` (public) → RSA public key.
  3. User submits credentials; SPA RSA-encrypts the password and calls `POST /api/login` (public).
  4. Spring `LoginController` authenticates against `mnx_db`, `JwtTokenProvider` mints a JWT (HS, `jwt.secret`), and a `JSESSIONID` session cookie is set (`secure`, `http-only`, `same-site=none`).
  5. Subsequent calls carry `Authorization: Bearer <jwt>` (and/or the session cookie via `HybridSecurityContextRepository`); `JwtFilter` validates per request. `GET /api/auth/refresh` renews the token.
  6. External integrators instead present `X-API-KEY`/`Bearer` handled by `ApiKeyAuthFilter` → `ROLE_EXTERNAL_API`, limited to `/api/external/**`.

---

## 7. Data in / out

**Inbound (to this subsystem):**
- Browser HTTPS (443) → SPA + `/api` calls.
- External partner systems → `/api/external/**` (API-key), CTX feed ingest → `/api/external/ctx/feed/data`.
- Syslog/detection callbacks → public `/api/syslog/...`, `/api/server/status/...`, `/api/server/module/save`.

**Outbound / internal (from the Java API):**
- MariaDB `mnx_db` (JPA) — config/users/rules/licenses/metadata.
- Elasticsearch `:9200` — sessions, payloads, traffic stats, files, mail/AI content, playbooks.
- Host Python `regression_api` `:8000` (regression/replay + SECUI).
- Unix socket `/var/run/service_control.sock` — module/service control.
- Filesystem `/application/**` (rules, reports, insight, apikey, mitre, dashboard/monitor aggregates, asset, blackbox, backup, logo), `/data/payload` (ro), `/pipeline/raw` (ro), `/releases`, GeoIP mmdb.
- External SaaS TI: VirusTotal, CTX (`mnx-proxy.ctx.io`), malwares.com, idpw.io; SMTP mail; Slack; Splunk HEC.
- Selenium + Chrome → renders HTML reports to PDF (report scheduler).

**Scheduled jobs (from `application.yml scheduler.*`):** backup daily 00:00, report daily 00:00, mitre-attack daily 03:00, insight every 10 min, dashboard-aggs (1g 06:00 / 10g 04:00), monitoring-aggs (1g 02:00 / 10g 01:00), asset IPv4 purge daily 00:05 (>30d, profiles only), regression cron daily 01:00, malicious-ip retention 5 days.

---

## 8. Ports — full map

| Port | Proto | Owner (pid) | Scope | Role |
|---|---|---|---|---|
| 80 | HTTP | nginx / web container (2254) | 0.0.0.0 | → 301 redirect to 443 |
| 443 | HTTPS | nginx / web container | 0.0.0.0 | Public front door (SPA + `/api` proxy) |
| 8090 | HTTPS | nginx / web container | 0.0.0.0 | SPA static host (also exposed publicly) |
| 8443 | HTTPS | Java API container (2294) | `*` (all ifaces) | Spring Boot REST API |
| 8000 | HTTP | host `python3.12` regression_api (18814) | 0.0.0.0 | Regression/SECUI backend (called by Java) |
| 8005 | — | (none) | — | nginx `/mnx/api` target — no listener (dead) |
| 3306 | TCP | mariadbd (1347) | 127.0.0.1 | MariaDB `mnx_db` (localhost-only ✅) |
| 9200 | HTTP | ES java (15810) | `*` | Elasticsearch (used by API) |
| 9092 | TCP | kafka java (17016) | `*` | Kafka (other subsystems, not this API) |

Exposure risk: 443, **8090**, **8443**, **8000**, **9200**, **9092** all bind `0.0.0.0`/`*` (reachable off-host unless a host firewall blocks them). Only 3306 is safely bound to loopback.

---

## 9. Dependencies

**API (Java, `app.jar` `BOOT-INF/lib`):** Spring Boot, Spring Security 5.6.3, Spring Data Elasticsearch 4.3.4, elasticsearch-java 8.3.3 / rest-high-level-client 7.15.2 / es 7.15.2, MariaDB JDBC, HikariCP, Hibernate/JPA, jjwt 0.11.2 (api/impl/jackson), jasypt-spring-boot-starter 3.0.5, gson 2.9.0, Selenium 4.18.1 (+ chromedriver, legacy 3.141.59 drivers), pcap4j 1.8.2. Runtime: OpenJDK 17.0.18 on Ubuntu 22.04.

**Web (Node build artifacts):** Vue SPA (webpack `chunk-vendors.js`/`app.js`), Storybook static (`/mnx-ui-guide`). No `package.json` in the runtime image (build-time only). Runtime: nginx 1.28.2 on Alpine.

**Base images:** API `ubuntu:22.04`-derived (~1.95 GB); Web `alpine`-derived nginx (~331 MB).

---

## 10. Failure impact & recovery

| Failure | Impact | Recovery |
|---|---|---|
| `mnx_web_server` down | No UI, no `/api` reverse proxy → entire web tier unreachable (nginx also fronts 443). | `restart: always` auto-restarts; else `docker compose -f /opt/mnx_web/docker-compose-web-{1g,10g}.yml up -d`. Static SPA in image, stateless. |
| `mnx_api_server` down | All REST APIs down; UI loads but is non-functional; schedulers (backup/report/mitre/aggs) stop. | `restart: always`; heap OOM dumps to `/application/mnx_web/heapdump.hprof` (80 GB heap — host RAM pressure risk). |
| MariaDB down | API config/auth/rules unavailable; login fails; Hikari leak logging after 5 min. | Restore host MariaDB (localhost:3306). |
| Elasticsearch down | Detections/sessions/stats/payloads unavailable; most dashboards empty. | Restore ES on 9200. |
| regression_api (:8000) down | Regression analysis + SECUI features fail; core NDR unaffected. | Restart host `python3.12 /opt/regression_api/app.py`. |
| TLS cert expired (already true) | Browsers show cert warnings; strict clients/API integrations may refuse. | Replace `/etc/nginx/ssl/server.{crt,key}` + jar keystore; currently a self-signed demo cert. |
| Control socket `/var/run/service_control.sock` missing | Module control/orchestration calls fail. | Ensure host control daemon running; `/var/run` mounted. |

No orchestration beyond Docker `restart: always`; no health checks defined in compose (추정(unverified) — none present in the four files).

---

## 11. Code quality / security risks

1. **TLS cert expired + self-signed placeholder** — `O=Internet Widgits Pty Ltd`, expired 2024-10-15. HTTPS on 443/8090/8443 is effectively untrusted. (High)
2. **Plaintext secrets committed to images/compose:**
   - `JASYPT_PASSWORD=Toswm#0501` in compose (the master key that decrypts every `ENC(...)` DB/ES/keystore credential) → renders jasypt encryption moot.
   - TLS key passphrase `mnx#123` in `/etc/nginx/ssl/ssl.pass` (world-readable).
   - JWT signing secret hardcoded in `application.yml` and it is a **well-known public tutorial value** ("silvernine-tech…") → JWTs are forgeable by anyone. (Critical)
3. **Permissive CORS** on `/mnx/api`: `Access-Control-Allow-Origin: *` with credentials-style headers allowed (though backend 8005 is currently dead). (Medium)
4. **Broadly exposed ports** — 8090, 8443, 8000, 9200, 9092 bind to all interfaces; 8090 duplicates the SPA publicly, 8443 exposes the API directly (bypassing the nginx `/api` layer and its `X-Forwarded-For` handling). ES (9200) and Kafka (9092) reachable off-host. (High)
5. **Numerous public (permitAll) endpoints** including state-changing ones: `/api/user/root/save`, `/api/server/module/save`, `/api/server/status/save`, `/api/syslog/list` — potential for unauthenticated privilege/state manipulation. Warrants review. (High)
6. **`ddl-auto: update`** in production — Hibernate can alter schema on deploy; risky for prod data. (Medium)
7. **80 GB JVM heap** (`-Xmx80g`) — sized for 10g traffic; on a smaller host can OOM the box; heap dump path writes 80 GB dumps to shared `/application`. (Medium)
8. **JWT validity ambiguity** — `token-validity-in-seconds: 7200000`; if literally seconds, tokens live ~83 days. Verify code multiplier. (Medium, unverified)
9. **`SPRING_APPLICATION_JSON` sets root log level WARN** and web logging `driver: none` — minimal audit/observability at the container layer. (Low)
10. **Config inconsistency:** running API profile `1g` vs `web_config.ini max-traffic=10G` vs `env.js 1g` — deployment templating may be mismatched. (Low)
11. **Old/duplicated Selenium drivers (3.141.59) + bundled chromedriver** enlarge attack surface in the API image. (Low)

---

## 12. Cross-references

- **MariaDB (`mnx_db`, :3306)** — see DB subsystem doc; API is the primary writer/reader via JPA.
- **Elasticsearch (:9200)** — see data-store/ES subsystem; indices `payload_`, `net-stats-`, `mnx_sessions3-`, `mnx_files_v30`, `playbook-`, `mail_content-`, `ai_content-`.
- **Kafka (:9092)** — owned by the ingest/pipeline subsystem; NOT consumed by this API (documented here to prevent mis-attribution).
- **regression_api / SECUI (host Python, :8000)** — `/opt/regression_api/app.py`, config `/opt/mnx/etc/mnx_config.json`; consumes ES + Suricata; called server-to-server by the Java API. Belongs to the analysis/regression subsystem.
- **Capture/pipeline** — `/pipeline/raw`, `/data/payload`, packet/pcap endpoints (`/api/packet`, `/api/collect/pcap/file`) tie into the sensor/capture subsystem.
- **MITRE ATT&CK cron** — see §below; feeds `InsightController`/`ExternalController` mitre endpoints.
- **Service control daemon** — Unix socket `/var/run/service_control.sock`; see module-orchestration subsystem.

### Appendix — `update_mitre_attack.sh` (cron)
`/application/mnx_web/mitre_attack/update_mitre_attack.sh` (mode 0755). Cron: **`0 1 * * *`** (daily 01:00) in `/var/spool/cron/crontabs/root`.
Behavior: `curl -fsSL` downloads MITRE CTI enterprise-attack JSON from
`https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json`
to a `mktemp` temp file, and on success **atomically** `mv -f` it onto `/application/mnx_web/mitre_attack/mitre_attack.json` (kept via `trap … EXIT` cleanup); on failure it logs to stderr and **keeps the existing file**. Current file present, ~47 MB, last updated 2026-07-10 01:00 (cron ran). The Spring API reads it via `storage.mitre_attack.mitre_attack_file_path`. Note the app *also* has its own `scheduler.mitre-attack.cron: 0 0 3 * * ?` (03:00) — 추정(unverified) whether the in-app job re-parses this file or performs a separate refresh (two independent daily MITRE refresh mechanisms exist).

---
*Report generated from live-host inspection (docker inspect/exec, jar/javap decompilation, ss, openssl, nginx confs, compose files). Java endpoint list derived by parsing compiled annotations; two controllers' method-level `@RequestMapping` routes were not fully decoded (noted in §5).*
