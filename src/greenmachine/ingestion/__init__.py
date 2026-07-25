"""Provider ingestion: impure, isolated, injected, and append-only in spirit.

Populated by GM-020 with the thin production ingestion vertical slice: one
selected slate, one game, one hitter, the expected pitcher — prospectively
archived raw responses, provider-neutral normalized records, and the two
profile-specific ``InputSnapshot``s, replayable offline from exact bytes.

All provider vocabulary, parsing, retry logic, and schema-change detection
stops at this boundary (ARCHITECTURE §4.7/§8). Dependency direction: provider
clients build requests; the injected transport retrieves bytes; parsers emit
provider-neutral records; mapping composes the frozen domain and evaluation
contracts; orchestration wires the injected pieces together. Nothing here is
imported by ``domain`` or ``common``, and nothing here imports scoring or
reporting.
"""
