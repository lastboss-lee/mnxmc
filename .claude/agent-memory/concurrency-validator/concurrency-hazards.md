# MNXMC Concurrency Hazards - Detailed Reference

## H1: Module-level signal override (performance_monitor.py:14-15)
Severity: RACE CONDITION / signal handler conflict
signal.signal() at import time before Textual's loop starts.

## H2: time.sleep(1) in event loop timer (performance_monitor.py:84)
Severity: PERFORMANCE DEGRADATION (event loop freeze 1s)
First CPU measurement cycle sleeps 1s inside a sync callback on the Textual event loop.

## H3: time.sleep(0.3) in disk stats timer (disk_monitor.py:326)
Severity: PERFORMANCE DEGRADATION
get_disk_io_stats() first-call path sleeps 300ms inside set_interval callback.

## H4: TOCTOU session lock (main.py:382-393)
Severity: RACE CONDITION
exists() + write_text() with no atomic lock between concurrent SSH logins.

## H5: Timer handle leak on log switch (logs.py:452-454, 503-504, 591-592)
Severity: PERFORMANCE DEGRADATION (unbounded timer accumulation)
Each log source switch creates new set_interval without guaranteed stop of previous.

## H6: Blocking HTTP in event loop (elasticsearch_monitor.py:25,33,52,152,165,185,203)
Severity: PERFORMANCE DEGRADATION (event loop freeze up to 10s timeout)
requests.get() with timeout=10 called from Textual timer callbacks.

## H7: Shared mutable state without lock (performance_monitor.py:59,79,243,290,299)
Severity: DATA CORRUPTION RISK
last_cpu_stats, last_network_stats, last_time mutated from timer callback; no Lock.

## H8: subprocess.run blocking in timer callbacks (multiple files)
Severity: PERFORMANCE DEGRADATION
ethtool/ip/ps/kafka-consumer-groups.sh called synchronously on event loop.
