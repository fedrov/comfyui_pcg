"""
pcg66: guard rails for the SOP mapping table (sop_map.py).

The table itself is the result of an inventory; the test makes sure it **doesn't silently go stale**:
  · every PCG_ node written in the table is really registered (goes red on renaming / deleting a node)
  · conversely, every geometry-side node of the plugin (non-COP) is either referenced by the table or listed in EXTRA
    (plugin-specific, with no one-to-one Houdini equivalent) -- if a todo node is implemented later without coming back
    to update the table, it goes red
  · no duplicate keys in the dict literals (Python silently keeps the later one and the earlier entry is lost)
  · each row has the right shape: valid status; todo carries P1 / P2 / P3 and a plan; partial says what is missing;
    oos / platform give a reason
  · negative control: adding a nonexistent node to the table, or removing a referenced node, must be reported by the check functions
"""
import ast
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import sop_map as S                                     # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def rows(m, fam):
    return list(m.items()) + [(k, v[0]) for k, v in fam.items()]


def referenced(m, fam):
    out = set()
    for _, v in rows(m, fam):
        out |= {x for x in v[1:] if isinstance(x, str) and x.startswith("PCG_")}
    return out


def problems(m, fam, extra, registry):
    """Returns (in the table but not registered, registered but not in the table, wrong shape)."""
    ref = referenced(m, fam)
    missing = sorted(x for x in ref if x not in registry)
    geo_nodes = {k for k, c in registry.items()
                 if getattr(c, "CATEGORY", "") != "PCG/cop"}
    orphan = sorted(k for k in geo_nodes if k not in ref and k not in extra)
    bad = []
    for k, v in rows(m, fam):
        st = v[0]
        if st not in S.STATUSES:
            bad.append((k, "status"))
        elif st == "todo" and (len(v) != 3 or v[1] not in ("P1", "P2", "P3")
                               or len(v[2]) < 6):
            bad.append((k, "todo needs (P?, plan)"))
        elif st == "partial" and (len(v) != 3 or len(v[2]) < 4):
            bad.append((k, "partial must say what is missing"))
        elif st in ("oos", "platform", "bridge") and len(v[1]) < 4:
            bad.append((k, "needs a reason"))
        elif st in ("done", "new") and not str(v[1]).startswith("PCG_"):
            bad.append((k, "done / new needs a node name"))
    return missing, orphan, bad


sec("Mapping table matches the registry")
missing, orphan, bad = problems(S.M, S.FAMILY, S.EXTRA, MAP)
check("all PCG_ nodes written in the table are registered", not missing, missing)
check("every geometry-side node is either referenced by the table or in EXTRA", not orphan, orphan)
check("every row has the right shape", not bad, bad[:5])
dup_extra = sorted(set(S.EXTRA) & referenced(S.M, S.FAMILY))
check("EXTRA and table references don't overlap (each node documented in one place only)", not dup_extra, dup_extra)
check("everything in EXTRA is registered and geometry-side",
      all(k in MAP and MAP[k].CATEGORY != "PCG/cop" for k in S.EXTRA))

sec("No duplicate keys in the literals")
src = open(S.__file__, encoding="utf-8").read()
tree = ast.parse(src)
dups = []
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) \
            and node.targets and getattr(node.targets[0], "id", "") in (
                "M", "FAMILY", "EXTRA"):
        keys = [k.value for k in node.value.keys
                if isinstance(k, ast.Constant)]
        seen = set()
        for k in keys:
            if k in seen:
                dups.append((node.targets[0].id, k))
            seen.add(k)
check("keys of M / FAMILY / EXTRA are all unique", not dups, dups)

sec("Negative control: the check functions really report")
m2 = dict(S.M)
m2["Zzz Fake"] = ("done", "PCG_NoSuchNode")
check("adding a nonexistent node -> reports missing",
      problems(m2, S.FAMILY, S.EXTRA, MAP)[0] == ["PCG_NoSuchNode"])
m3 = {k: v for k, v in S.M.items() if "PCG_Revolve" not in v}
m3 = {k: v for k, v in m3.items() if v != ("done", "PCG_Skin")}
check("removing the only row referencing Skin -> reports orphan",
      "PCG_Skin" in problems(m3, S.FAMILY, S.EXTRA, MAP)[1])
m4 = dict(S.M)
m4["Revolve"] = ("todo", "P9", "x")
check("wrong priority -> reports shape", any(k == "Revolve" for k, _ in
                                  problems(m4, S.FAMILY, S.EXTRA, MAP)[2]))

sec("Inventory result")
b = S.by_status()
n = {s: len(b[s]) for s in S.STATUSES}
fam_n = sum(c for _, c in S.FAMILY.values())
print(f"  {len(S.M)} listed individually: {n}")
print(f"  {len(S.FAMILY)} rows merged by family, about {fam_n} nodes")
pr = S.todo_by_priority()
print("  todo:" + ",".join(f"{p} {len(v)}" for p, v in pr.items()))
check(f"P1 is a minority (priorities discriminate; P1 completed since pcg68, P2 since pcg71: "
      f"P1 {len(pr['P1'])} / P2 {len(pr['P2'])})",
      len(pr["P1"]) <= 10 and len(pr["P1"]) <= len(pr["P2"])
      <= len(pr["P3"]))
check("at least 300 listed individually (no big chunk of the core families missing)", len(S.M) >= 300)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
