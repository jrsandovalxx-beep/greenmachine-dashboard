"""Baseball Savant adapter: statcast-search CSV requests, strict parsing, metrics.

Provider-specific vocabulary — CSV column names, endpoint shapes, null-cell
conventions — lives only in this package (ENGINEERING_GUIDELINES I1).
Savant-specific behaviour remains prohibited in ``domain``, ``scoring``,
``validation``, ``evaluation``, and evaluation records. What leaves this
package are provider-neutral ingestion records and exact-Decimal metric
computations. Populated by GM-020.
"""
