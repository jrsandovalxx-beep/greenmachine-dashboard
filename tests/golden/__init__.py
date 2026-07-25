"""GM-008 golden-test harness package.

Test infrastructure only — nothing here is production GreenMachine code, and
nothing under ``src/`` may import it. The harness lives in
:mod:`tests.golden.runner`; the deliberately synthetic stub scorer lives in
:mod:`tests.golden.stub_scorer`; the committed golden cases live under
``tests/golden/cases/``.

Import these modules as ``tests.golden.runner`` / ``tests.golden.stub_scorer``
(the repository root is placed on ``sys.path`` by ``tests/conftest.py``, and
``scripts/update_goldens.py`` inserts it itself). Using one canonical import
name keeps every consumer bound to the same module objects.
"""
