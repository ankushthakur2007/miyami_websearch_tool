"""Load test harness for the search API.

asyncio + httpx, both already installed. Reports throughput and latency
percentiles plus process CPU so blocking work can be told apart from upstream
latency. No new dependencies.

    python3 bench.py --base http://localhost:8001 --conc 1,8,32 --endpoints health,fetch
"""

import argparse
import asyncio
import subprocess
import time
import sys
import httpx

ENDPOINTS = {
    "health": "/health",
    "search": "/search-api?query=open+source+web+scraping+tools&language=en",
    "fetch": "/fetch?url=https://example.com/&format=markdown",
    "deep": "/deep-research?queries=python+web+scraping+libraries,open+source+crawlers&breadth=2",
    "crawl": "/crawl-site?start_url=https://example.com&max_pages=3&max_depth=1",
}


def _pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, int(len(sorted_vals) * p / 100))
    return sorted_vals[i]


def _tree_cpu(pid):
    """Sum %CPU across pid and all descendants. Returns None if unavailable."""
    if not pid:
        return None
    try:
        out = subprocess.run(
            ["ps", "-Ao", "pid=,ppid=,%cpu="],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return None
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            try:
                rows.append((int(parts[0]), int(parts[1]), float(parts[2])))
            except ValueError:
                pass
    kids = {}
    for c, p, _ in rows:
        kids.setdefault(p, []).append(c)
    total, stack, seen = 0.0, [pid], set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for c, _, cpu in rows:
            if c == cur:
                total += cpu
        stack.extend(kids.get(cur, []))
    return total


async def _cpu_sampler(pid, stop, out):
    while not stop.is_set():
        v = _tree_cpu(pid)
        if v is not None:
            out.append(v)
        await asyncio.sleep(0.5)


async def burst(client, path, conc, duration, max_requests):
    lat, errs = [], 0
    deadline = time.monotonic() + duration
    inflight = set()

    async def one():
        nonlocal errs
        t0 = time.monotonic()
        try:
            r = await client.get(path)
            r.raise_for_status()
            await r.aread()
            lat.append((time.monotonic() - t0) * 1000)
        except Exception:
            errs += 1

    # keep `conc` requests in flight for `duration`
    async def spawn():
        inflight.add(asyncio.create_task(one()))

    for _ in range(conc):
        await spawn()
    t_start = time.monotonic()
    while time.monotonic() < deadline and (max_requests == 0 or len(lat) + errs < max_requests):
        done, _ = await asyncio.wait(inflight, timeout=0.05, return_when=asyncio.FIRST_COMPLETED)
        for d in done:
            inflight.discard(d)
            if time.monotonic() < deadline and (max_requests == 0 or len(lat) + errs < max_requests):
                await spawn()
    await asyncio.gather(*inflight, return_exceptions=True)
    elapsed = time.monotonic() - t_start
    return lat, errs, elapsed


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--conc", default="1,8,32")
    ap.add_argument("--endpoints", default="health,fetch")
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--max-requests", type=int, default=0, help="0 = no cap (time-bounded only)")
    ap.add_argument("--pid", type=int, default=0, help="uvicorn master pid for CPU sampling")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    names = [e.strip() for e in args.endpoints.split(",") if e.strip()]
    concs = [int(c) for c in args.conc.split(",") if c.strip()]

    if args.label:
        print(f"\n### {args.label}")
    print(f"{'endpoint':<9}{'conc':>5}{'n':>6}{'thr/s':>9}{'p50':>9}{'p95':>9}{'p99':>9}{'err':>6}{'cpu%':>8}")

    limits = httpx.Limits(max_connections=256, max_keepalive_connections=256)
    async with httpx.AsyncClient(base_url=args.base, timeout=args.timeout, limits=limits) as client:
        for name in names:
            path = ENDPOINTS[name]
            for conc in concs:
                cpu_samples, stop = [], asyncio.Event()
                sampler = asyncio.create_task(_cpu_sampler(args.pid, stop, cpu_samples))
                lat, errs, elapsed = await burst(client, path, conc, args.duration, args.max_requests)
                stop.set()
                await sampler

                lat.sort()
                thr = (len(lat) + errs) / elapsed if elapsed else 0
                cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
                print(f"{name:<9}{conc:>5}{len(lat)+errs:>6}{thr:>9.2f}"
                      f"{_pct(lat,50):>9.1f}{_pct(lat,95):>9.1f}{_pct(lat,99):>9.1f}"
                      f"{errs:>6}{cpu:>8.1f}", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)