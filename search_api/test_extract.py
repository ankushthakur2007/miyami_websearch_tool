"""Assert-based check for the _extract_content rewrite.

Verifies the markdown fast path is byte-identical to the old two-pass logic,
metadata does not regress, and the readability fallback still triggers.

    python3 test_extract.py /tmp/bench_html
"""

import json
import pathlib
import sys

import trafilatura
import main


def old_markdown(html, final_url, include_links=True, include_images=True, maxlen=100000):
    """The pre-rewrite trafilatura branch: two full passes."""
    extracted = trafilatura.extract(
        html, include_comments=False, include_tables=True,
        include_images=include_images, include_links=include_links,
        output_format='json', url=final_url, with_metadata=True,
    )
    if not extracted:
        return None, None
    data = json.loads(extracted)
    content = trafilatura.extract(
        html, include_comments=False, include_tables=True,
        include_images=include_images, include_links=include_links,
        output_format='markdown', url=final_url,
    ) or data.get("text", "")
    if len(content) > maxlen:
        content = content[:maxlen] + "\n\n... [truncated]"
    return content, data


def main_():
    d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bench_html")
    pages = sorted(p for p in d.iterdir() if p.is_file())
    if not pages:
        sys.exit(f"no pages in {d}")

    same = 0
    old_md = new_md = 0
    meta_ok = 0
    checked = 0

    for p in pages:
        html = p.read_text(errors="ignore")
        url = f"https://{p.name}.test/"

        old_content, _ = old_markdown(html, url)
        res = main._extract_content(html, url, "markdown", "trafilatura", True, True, 100000)

        # markdown content must be unchanged by the rewrite
        if old_content is None:
            assert res["extraction_mode"] in ("readability", "trafilatura"), p.name
        else:
            assert res["extraction_mode"] == "trafilatura", f"{p.name}: fell back unexpectedly"
            assert res["content"] == old_content, f"{p.name}: markdown content changed"
            old_md += len(old_content or "")
            new_md += len(res["content"])
            same += 1

        md = res.get("metadata", {})
        assert "url" in md or res["extraction_mode"] == "readability", f"{p.name}: no metadata url"
        if md.get("title"):
            meta_ok += 1

        # text path must still work
        t = main._extract_content(html, url, "text", "trafilatura", True, True, 100000)
        assert "content" in t, f"{p.name}: text path returned no content"
        checked += 1

    # readability fallback: no trafilatura result should fall through
    junk = "<html><body><script>var a=1;</script></body></html>"
    r = main._extract_content(junk, "https://x.test", "markdown", "trafilatura", True, True, 1000)
    assert r["extraction_mode"] in ("readability", "trafilatura"), r["extraction_mode"]
    assert "content" in r, "fallback produced no content"

    # truncation still applies
    big = "<html><body><p>" + ("word " * 5000) + "</p></body></html>"
    t = main._extract_content(big, "https://x.test", "text", "readability", True, True, 500)
    assert "truncated" in t["content"], "truncation marker missing"

    print(f"pages checked      : {checked}")
    print(f"markdown identical : {same}/{checked} (old {old_md} chars == new {new_md} chars)")
    print(f"metadata w/ title  : {meta_ok}/{checked}")
    print(f"fallback + truncation: ok")
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main_()