"""MLB Stats API adapter: request building and strict response parsing.

Provider-specific vocabulary — endpoint paths, JSON field names, status code
strings — lives only in this package. What leaves it are provider-neutral
ingestion records (``SlateRecord``, ``GameRecord``, ``ExpectedPitcherRecord``)
and plain values.
"""
