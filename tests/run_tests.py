"""
Run the test suites, one process per file, and print a summary.

    python tests/run_tests.py              Python suites
    python tests/run_tests.py --js         + frontend suites (needs Node 18+ and `npm install` in the repo root)
    python tests/run_tests.py --quick      skip the heavy production-workflow suite
    python tests/run_tests.py -k cop       only files whose name contains "cop"

Suites that need a real, running ComfyUI (test_*_e2e.py) are skipped unless --e2e is given.
Each suite is its own script that prints PASS/FAIL lines and "N/M passed", and exits non-zero on failure.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
E2E = ("test_panel_e2e.py", "test_wires_e2e.py")
HEAVY = ("test_prod_workflows.py",)
# test_panel.py writes panel_fixture.json, which test_panel.mjs reads, so Python runs first.


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--js", action="store_true", help="also run the Node (jsdom) frontend suites")
    ap.add_argument("--quick", action="store_true", help="skip " + ", ".join(HEAVY))
    ap.add_argument("--e2e", action="store_true", help="also run the suites that need a running ComfyUI")
    ap.add_argument("-k", default="", help="only run files whose name contains this text")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per suite (default 1800)")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    if a.js:
        files += sorted(glob.glob(os.path.join(HERE, "test_*.mjs")))
    sel = []
    for f in files:
        b = os.path.basename(f)
        if a.k and a.k not in b:
            continue
        if b in E2E and not a.e2e:
            continue
        if b in HEAVY and a.quick:
            continue
        sel.append(f)

    results, t_all = [], time.time()
    for f in sel:
        b = os.path.basename(f)
        cmd = ["node", f] if f.endswith(".mjs") else [sys.executable, "-B", f]
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=a.timeout)
            out, rc = p.stdout + p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            out, rc = "timed out", -1
        m = re.findall(r"(\d+)/(\d+) passed", out)
        score = f"{m[-1][0]}/{m[-1][1]}" if m else "-"
        ok = rc == 0
        results.append((b, ok, score))
        print(f"{'ok  ' if ok else 'FAIL'}  {b:<40} {score:>9}  {time.time() - t0:6.1f}s", flush=True)
        if not ok:
            lines = [ln for ln in out.splitlines() if "FAIL" in ln or "Error" in ln or "error" in ln]
            for ln in (lines or out.splitlines())[-12:]:
                print("        " + ln)

    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} suites passed in {time.time() - t_all:.0f}s")
    if bad:
        print("failed: " + ", ".join(r[0] for r in bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
