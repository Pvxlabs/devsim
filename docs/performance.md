# Performance Baseline

This is a functional baseline, not a load test. Measurements were taken on
September 5, 2026 in the local DevSim checkout with Python 3.11 and the
default JSONL artifact writer. Each run used 1,000 events and a high virtual
clock speed so wall time is dominated by runtime work.

| Workload | Wall time | Per event | Artifact |
| --- | ---: | ---: | ---: |
| `context.set` x1,000 | 2.965 s | 2.965 ms | 873,346 B |
| `value.generate integer` x1,000 | 2.975 s | 2.975 ms | 895,194 B |
| `command.run true` x1,000 | 7.033 s | 7.033 ms | 917,346 B |

Scheduler construction for 1,000 one-shot events measured 0.872 ms per build
(0.872 microseconds per event, averaged over 100 builds). The event loop and
artifact writes are included in the workload timings; no optimization is
claimed from these numbers. Re-run the benchmark on the target machine before
using them for capacity planning.
