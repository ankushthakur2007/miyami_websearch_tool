"""Probe: does an in-flight /crawl-site stall unrelated endpoints?

Fires concurrent crawls, then measures /health latency while they run.
If /health inflates toward the crawl queue depth, the blocking subprocess
in main.py:931 is starving the whole event loop, not just crawlers.
"""

import asyncio
import subprocess
import sys
import time
import httpx

CRAWL = "/crawl-site?start_url=https://example.com&max_pages=2&max_depth=0"
HEALTH = "/health"


async def crawl_hold(client, n):
    await asyncio.gather(*[client.get(CRAWL) for _ in range(n)], return_exceptions=True)


async def health_probe(client, label, seconds=6.0):
    lat = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        t0 = time.monotonic()
        try:
            r = await client.get(HEALTH)
            await r.aread()
            lat.append((time.monotonic() - t0) * 1000)
        except Exception:
            pass
    lat.sort()
    if lat:
        print(f"  {label:<28} n={len(lat):<4} p50={lat[len(lat)//2]:8.1f}ms  p95={lat[int(len(lat)*.95)]:8.1f}ms")
    return lat


async def main():
    conc = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    limits = httpx.Limits(max_connections=256, max_keepalive_connections=256)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=400, limits=limits) as client:
        print(f"\n### Starvation probe: {conc} concurrent /crawl-site")
        await health_probe(client, "idle (control)")

        task = asyncio.create_task(crawl_hold(client, conc))
        await asyncio.sleep(1.5)  # let crawls reach the blocking call
        await health_probe(client, f"while {conc} crawls in flight")
        await task
        await health_probe(client, "after crawls finished")


if __name__ == "__main__":
    asyncio.run(main())