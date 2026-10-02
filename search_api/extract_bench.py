"""CPU-only throughput of the real _extract_content(), no network.

Answers: is content extraction the ceiling, and does it scale with processes
(GIL-bound) or not? Compares the markdown path against the text path, since
main.py:278 and main.py:300 call trafilatura.extract twice on the same HTML
when format=markdown.

    python3 extract_bench.py /tmp/bench_html --mode markdown
"""

import argparse
import pathlib
import sys
import time
import main


def run(paths, mode, extraction_mode, rounds, include_links, include_images):
    # warmup: lxml/trafilatura lazy-init and OS page cache
    for p in paths[:3]:
        main._extract_content(p.read_text(errors="ignore"), "https://x.test",
                              mode, extraction_mode, include_links, include_images, 100000)

    best = 0.0
    total_chars = 0
    for _ in range(rounds):
        t0 = time.perf_counter()
        chars = 0
        for p in paths:
            r = main._extract_content(p.read_text(errors="ignore"), "https://x.test",
                                      mode, extraction_mode, include_links, include_images, 100000)
            chars += len(r.get("content") or "")
        el = time.perf_counter() - t0
        best = max(best, len(paths) / el)
        total_chars = chars
    return best, total_chars


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default="/tmp/bench_html")
    ap.add_argument("--mode", default="markdown", choices=["markdown", "text", "html"])
    ap.add_argument("--extraction", default="trafilatura", choices=["trafilatura", "readability"])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--no-links", action="store_true")
    ap.add_argument("--no-images", action="store_true")
    a = ap.parse_args()

    paths = sorted(p for p in pathlib.Path(a.dir).iterdir() if p.is_file())
    if not paths:
        sys.exit(f"no pages in {a.dir}")
    pps, chars = run(paths, a.mode, a.extraction, a.rounds,
                     not a.no_links, not a.no_images)
    kb = sum(p.stat().st_size for p in paths) / len(paths) / 1024
    print(f"pages={len(paths)} avg={kb:.0f}KB mode={a.mode}/{a.extraction} "
          f"pages_per_sec={pps:.2f} ms_per_page={1000/pps:.1f} avg_out_chars={chars//len(paths)}")


if __name__ == "__main__":
    main_()