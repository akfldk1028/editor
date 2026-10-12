"""협업 장부 — one durable record per agent-to-agent call in the network.

Every A2A hop (the editor's own calls, the Orchestrator's calls, calls between agents) lands here once, keyed by
W3C trace ids and the conversation it belongs to, with the request and reply texts, so the 협업 view draws what
actually happened — live, after restarts, and scoped to one conversation. Field names follow the OpenTelemetry
GenAI semantic conventions (`invoke_agent`/`execute_tool`, `gen_ai.conversation.id`, GenAI message JSON);
A2A-only facts (task id, run id, hop) are kept under their own names. SQLite (WAL, single writer: this backend)
is the record; a daily NDJSON mirror under the ledger folder is for people and tails.
"""
from .schema import HopRecord, from_hop_log, from_otlp_payload, message_text, text_message
from .service import Ledger
from .store import LedgerStore

__all__ = ['HopRecord', 'Ledger', 'LedgerStore', 'from_hop_log', 'from_otlp_payload', 'message_text', 'text_message']
