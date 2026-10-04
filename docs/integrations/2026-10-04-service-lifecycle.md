# Editor integration: service lifecycle protection

The development launcher no longer starts the shared orchestrator gateway. It probes the existing gateway and reports unavailable or incompatible services without restarting them. Core product startup continues independently of that probe result.

`infra/config/services.json` assigns source ownership, lifecycle and management. Only explicitly created Editor session processes may be terminated. Reused processes, shared agents, persistent domain hosts and unknown ownership are excluded. Concurrent startup settles before failure cleanup, preventing late-starting siblings from escaping cleanup.

Validation: 21 tests passed across product-lifecycle, runtime, compose and structure suites. Two tests start isolated real HTTP child processes and prove shutdown/startup-failure cleanup leaves reused, domain-host and agent-host processes responding while stopping the created session process. Shared operational services were not terminated. Hidden Windows launch flags remain intact. This is not proof of live degraded UI behavior or whole-product integration.

ARR is now explicitly registered as a persistent probe-only domain host. Product startup probes ARR before the shared orchestrator and session services. Its `/law/health/` contract is grounded in `ARR/backend/law/views.py:health`: Django reachability is separate from law dependency readiness. Source ownership is the Editor destination; `source_status: legacy-pending-relocation` states that source relocation has not occurred.

Read-only live probes on 2026-10-04: ARR18320 accepted the Django contract and reported law dependency ready. Default orchestrator8791 returned HTTP404 for `/editor/v1/health`; this is incompatible, not verified healthy. The launcher reports the connection unavailable without restarting it. No settings/permission cause has been inferred.

Remaining Task0 work: full product startup and degraded UI verification with isolated dependencies. ARR source relocation, full functional coverage and shared consumer isolation remain later gates. Existing ARR/AG/AG-frontend folders and all shared agent data remain unchanged.
