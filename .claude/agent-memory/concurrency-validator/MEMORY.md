# Concurrency Validator - MEMORY.md

## Project: MNXMC TUI Monitoring App

## ✅ v2.1.0 (2026-04-21) 에서 해결된 항목 — 재조사 금지
- ✅ #4 SessionManager TOCTOU race → main.py acquire() 가 os.O_CREAT|os.O_EXCL 사용
- ✅ Service all_start/all_stop 메인 스레드 블로킹 → @work(thread=True, exclusive=True,
     group="service_bulk") 로 이전. 단일 액션도 _run_service_action_worker() 로 분리.
- ✅ Dashboard F7/F8 rescan → @work(thread=True, exclusive=True, group="rescan_*")
- ✅ Logs inspection ad-hoc threading.Thread → @work(thread=True, exclusive=True,
     group="inspection") 로 이전. 화면 이탈 시 자동 취소되도록 Textual 라이프사이클에
     편입됨.
- ✅ shell=True 인젝션 경로 (base_module/system_info) 제거 — shlex.split + list argv

## ⚠ 미해결 (v2.1.x 후속 Sprint 대상)
- performance_monitor.py SIGINT/SIGTERM module-level 등록 (#1)
- performance_monitor.py time.sleep(1) inside event loop (#2)
- disk_monitor.py time.sleep(0.3) (#3)
- LogsScreen _refresh_handle 누수 (#5) — _show_inspection_summary 초기화 시
  기존 핸들 stop 후 재등록은 적용됐으나 화면 이탈 on_unmount 검토 필요
- elasticsearch_monitor 동기 requests.get (#6)
- PerformanceMonitor 공유 변수 lock 부재 (#7)

### Key Architecture Facts
- Single-process Textual TUI app; one asyncio event loop (Textual's internal loop).
- Backend modules (PerformanceMonitor, KafkaMonitor, etc.) are plain synchronous classes.
- Textual screens call blocking I/O (subprocess, requests, file reads) directly in timer callbacks on the event loop — primary risk pattern.
- threading.Thread is used in LogsScreen (_show_inspection_summary) and NetworkScreen (_update_stats) as the only true background thread usage.
- call_from_thread() is used correctly in those two cases to return results to the UI thread.

### Confirmed Critical Patterns

1. **SIGINT/SIGTERM overwritten at module import time** — performance_monitor.py line 14-15 calls signal.signal() at module-level. Overwrites Textual's signal handling before the app even starts.

2. **time.sleep(1) inside async context** — performance_monitor.py get_cpu_usage_per_core() line 84. Called from Textual timer (sync callback on event loop) → freezes event loop for 1 second every first CPU read cycle.

3. **time.sleep(0.3) inside sync timer callback** — disk_monitor.py get_disk_io_stats() line 326. Called from PerformanceScreen set_interval timer.

4. **Non-atomic TOCTOU on session lock file** — main.py SessionManager.acquire() lines 382-390: check-then-write with no OS-level lock; race with concurrent SSH logins possible.

5. **_refresh_handle timer leak** — LogsScreen: switching log sources creates a new set_interval() without guaranteed cancellation of the prior handle.

6. **requests (HTTP) blocking calls in event loop** — elasticsearch_monitor.py: all requests.get() calls are synchronous, called from Textual timer callbacks.

7. **Shared mutable state without lock** — PerformanceMonitor.last_cpu_stats / last_network_stats / last_time mutated by timer callbacks; no threading.Lock protecting these fields.

### Patterns NOT Present (confirmed safe)
- No asyncio.run_until_complete() inside coroutines.
- No asyncio.get_event_loop() misuse.
- No Thread.join() blocking on event loop.

### Severity Map
See concurrency-hazards.md for full file:line details and mitigation code.
