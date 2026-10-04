# Editor integration: service lifecycle protection

The development launcher no longer starts the shared orchestrator gateway. It probes the existing gateway and reports unavailable or incompatible services without restarting them. Core product startup continues independently of that probe result.

`infra/config/services.json` assigns source ownership, lifecycle and management. Only explicitly created Editor session processes may be terminated. Reused processes, shared agents, persistent domain hosts and unknown ownership are excluded. Concurrent startup settles before failure cleanup, preventing late-starting siblings from escaping cleanup.

Validation: 18 tests passed across product-lifecycle, runtime, compose and structure suites. Tests inject process operations; no live services were terminated. Hidden Windows launch flags remain intact. This is not proof of live degraded UI behavior or whole-product integration.

Remaining Task0 work: register ARR using a verified health contract, probe domain before agent connections, and verify live startup/shutdown with isolated processes. ARR source relocation, full functional coverage and shared consumer isolation remain later gates. Existing ARR/AG/AG-frontend folders and all shared agent data remain unchanged.
