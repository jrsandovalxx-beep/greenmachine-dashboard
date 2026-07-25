# Invalid configuration fixtures

Small, standalone documents that must fail **before** schema validation — they
are about the YAML dialect itself, so a full configuration would only obscure
the point.

Everything that fails at the schema or semantic stage is generated in the tests
by mutating `../valid/complete_synthetic.yaml`. That keeps each invalid case a
one-line diff from a known-good file, which makes the expected key path obvious
and stops a fixture from drifting out of sync with the schema.

Every value here is synthetic. No production threshold appears in this tree.
