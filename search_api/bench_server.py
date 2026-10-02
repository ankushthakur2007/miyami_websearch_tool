"""Benchmark harness entrypoint: same app, caching disabled.

Cache TTLs are 1800-3600s, so the first request in a load burst warms the key
for every concurrent sibling and the run measures diskcache instead of the
pipeline. Stub it out here rather than editing production code.
"""

import main


class _NoCache:
    def get(self, *a, **k):
        return None

    def set(self, *a, **k):
        return True

    def delete(self, *a, **k):
        return True


main.cache = _NoCache()
app = main.app