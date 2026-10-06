"""T-43 A／B／C 的取证件（零额度、零出站、零容器动作：只 `docker exec`／`inspect`／`ps -a` 读 ＋ 只读 CQ）。
四件事：
① 装配件**跑两遍**的递归 diff ⇒ 幂等尺（只许差时钟字段）；
② 装配件对**入库版**（`git show HEAD:…`）的递归 diff ⇒ 逐处归类，并回答"除 A 的措辞与 f 格跟上之外，有没有任何一格判定词变了"；
③ 三把 ruff 计数（三门整目录命令面 ／ 单件 ／ `deploy` 整面）⇒ B 选乙的实测面；
④ 靶子三格（镜像 id／时刻／`ast_gate.py` 容器面与 HEAD 面 md5）＋ 台账／审计／残渣三条零花费自证。

复算（cwd = 仓库根）：
    PYTHONUTF8=1 PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/reports/w8/t43_readings.py
产物：backend/reports/w8/evidence/t43/t43_readings.json
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
W8 = ROOT / "backend" / "reports" / "w8"
OUT = W8 / "evidence" / "t43" / "t43_readings.json"
ASSEMBLED = W8 / "t38_assembled.json"
ASSEMBLER = W8 / "t38_assemble.py"
PY = sys.executable
CLOCKS = ("/generated_at_utc", "/identity/captured_at_utc", "/identity/rev", "/identity/rev_short", "/identity/commit_count")
FIX_WORDS = ("原写", "原命令", "作废", "换代", "订正")


def sh(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(args, cwd=str(cwd or ROOT), capture_output=True)
    text = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, text


def git_show(rev_path: str) -> str:
    rc, out = sh(["git", "show", rev_path])
    if rc != 0:
        raise SystemExit(f"git show 失败 {rev_path} rc={rc}")
    return out


def walk(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}/{k}"
            if k not in a or k not in b:
                out.append((p, "缺失" if k not in a else "在", "缺失" if k not in b else "在"))
            else:
                out += walk(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path + "/len", len(a), len(b)))
        out += [x for i, (u, v) in enumerate(zip(a, b, strict=False)) for x in walk(u, v, f"{path}[{i}]")]
    elif a != b:
        out.append((path, str(a)[:60], str(b)[:60]))
    return out


def ruff(targets: list[str]) -> dict:
    """三门那把的整目录面 ⟷ 单件 ⟷ deploy 整面，同一条命令形状（cwd = backend/ ＋ `--config pyproject.toml`）。

    🔴 计数只认 `--output-format=json` 的 finding 条数：文本模式下 ruff 会把 help 段再印一遍规则名 ⇒ 手数会虚高
    （本窗第一版就把整面的 **25** 条数成 44 条）。
    """
    rc, text = sh([PY, "-m", "ruff", "check", "--config", "pyproject.toml", "--output-format=json", *targets],
                  cwd=ROOT / "backend")
    body = text.strip()
    findings = json.loads(body[body.find("["):]) if body.startswith("[") or "[" in body[:2] else []
    hist = collections.Counter(item.get("code", "?") for item in findings)
    files = sorted({str(item.get("filename", "")).replace(str(ROOT), "") for item in findings})
    return {"命令": "ruff check --config pyproject.toml --output-format=json " + " ".join(targets),
            "rc": rc, "条数": len(findings),
            "汇总": "All checks passed" if not findings else f"Found {len(findings)} errors",
            "规则分布": dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0]))),
            "涉及文件": files[:8]}


def psql_read(sql: str) -> str:
    rc, out = sh(["docker", "exec", "-i", "commerceql-pg-1", "psql", "-U", "postgres", "-d", "ecom",
                  "-q", "-t", "-A", "-c", f"begin; {sql} rollback;"])
    if rc != 0:
        raise SystemExit(f"psql 失败 rc={rc}: {out[-200:]}")
    return out.strip()


def main() -> int:
    before = ASSEMBLED.read_text(encoding="utf-8")
    rc_asm, _ = sh([PY, str(ASSEMBLER)])
    after = ASSEMBLED.read_text(encoding="utf-8")
    twice = walk(json.loads(before), json.loads(after))

    committed = git_show("HEAD:backend/reports/w8/t38_assembled.json")
    vs_head = walk(json.loads(committed), json.loads(after))
    cls: collections.Counter = collections.Counter()
    for p, _a, _b in vs_head:
        if p in CLOCKS:
            cls["装配时刻身份格（件内自报 ⟷ 现 HEAD）"] += 1
        elif p.startswith("/hard_requirements/c_build_identity"):
            cls["A 件本轮措辞（两链换代）"] += 1
        elif p.startswith("/hard_requirements/f_p0_summary_current"):
            cls["f 格跟上盘上取证件（第 16 轮 f7bf106 已当期化）"] += 1
        else:
            cls["⚠️ 未归类（必须人工看）"] += 1
    other_verdicts = [p for p, _a, _b in vs_head if p.endswith("/verdict")
                      and "/c_build_identity/" not in p and "/f_p0_summary_current/" not in p]

    art = json.loads(after)
    c = art["hard_requirements"]["c_build_identity"]
    blob_text = json.dumps(art, ensure_ascii=False)
    sm = []
    for m in re.finditer("三面", blob_text):
        seg = blob_text[max(0, m.start() - 46):m.start() + 46]
        sm.append({"上下文": seg, "在订正或原句引用语境": any(k in seg for k in FIX_WORDS)})
    raw_command_left = [x for x in sm if not x["在订正或原句引用语境"]]

    _rc, docker_out = sh(["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.Image}}"])
    images = {}
    for name in ("commerceql-api:latest", "w7load-api:latest"):
        rc2, o = sh(["docker", "image", "inspect", name, "--format", "{{.Id}} {{.Created}}"])
        images[name] = o.strip() if rc2 == 0 else "UNVERIFIED（镜像不在场）"
    rc3, cont = sh(["docker", "exec", "commerceql-api-1", "md5sum", "/srv/app/guard/ast_gate.py"])
    in_container = cont.split()[0] if rc3 == 0 and cont.strip() else "UNVERIFIED（容器内取不到）"
    raw = subprocess.run(["git", "show", "HEAD:backend/app/guard/ast_gate.py"], cwd=str(ROOT), capture_output=True).stdout
    head_md5 = hashlib.md5(raw.replace(b"\r\n", b"\n")).hexdigest()
    _rc4, landing = sh(["git", "log", "-1", "--format=%h %cI %s", "--", "backend/app/guard/ast_gate.py"])

    out = {
        "artifact": "commerceql.w8.t43_readings/1",
        "taken_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "装配件重跑rc": rc_asm,
        "边界自证": {"零出站": True,
                   "零容器动作": "只 docker ps/inspect/exec 读 ⇒ 没 build、没 up/down、没 start（派单禁）",
                   "共享库": "全部 begin; … rollback;",
                   "台账": psql_read("select count(*), to_char(sum(cost_cny),'FM999990.000000'), max(created_at) from app.cost_ledger;"),
                   "审计行": psql_read("select count(*), max(\"timestamp\") from app.audit_log;"),
                   "残渣": psql_read("select datname from pg_database where datname like 'ecom%' order by 1;").splitlines()},
        "A_装配件两遍递归diff": {"差异处数": len(twice), "路径": [p for p, _a, _b in twice],
                              "判": "只差时钟字段 ⇒ 幂等成立" if all(p in CLOCKS for p, _a, _b in twice) else "⚠️ 出现非时钟差异"},
        "A_对入库版递归diff": {"差异处数": len(vs_head), "分类计数": dict(cls),
                            "除c与f之外还有verdict变吗": bool(other_verdicts), "那些路径": other_verdicts,
                            "逐处": [{"path": p, "入库版": a, "现版": b} for p, a, b in vs_head]},
        "A_三面字样": {"次数": len(sm), "全部在订正或原句引用语境": not raw_command_left,
                    "命令句残留数": len(raw_command_left), "上下文": sm},
        "A_两链句现读": {"verdict": c["verdict"], "当期性写法": c["当期性写法"],
                       "旧键与键面未动": {"aggregate_three_way_equal": c["读数"]["aggregate_three_way_equal"],
                                      "读数键数": len(c["读数"]), "键名": sorted(c["读数"].keys())}},
        "B_ruff三把": {"三门整目录命令面": ruff(["reports/w8", "tests/contract", "app"]),
                     "单件": ruff(["../deploy/loadtest/attest_build_identity.py"]),
                     "deploy整面": ruff(["../deploy"])},
        "C_靶子三格": {"U-137落地笔": landing.strip()[:120], "镜像id与时刻": images,
                    "容器内ast_gate_md5": in_container, "HEAD_blob_LF_md5": head_md5,
                    "链一判定": "DIFF（容器 ≠ HEAD）" if in_container != head_md5 else "SAME",
                    "容器在场": {"commerceql-api-1": [x for x in docker_out.splitlines() if x.startswith("commerceql-api-1")],
                              "w7load系": [x for x in docker_out.splitlines() if "w7load" in x]}},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print("A 两遍 diff =", out["A_装配件两遍递归diff"]["差异处数"], out["A_装配件两遍递归diff"]["判"])
    print("A 对入库版 =", out["A_对入库版递归diff"]["差异处数"], out["A_对入库版递归diff"]["分类计数"],
          "｜别的 verdict 变 =", out["A_对入库版递归diff"]["除c与f之外还有verdict变吗"])
    print("A 三面 =", out["A_三面字样"]["次数"], "命令句残留 =", out["A_三面字样"]["命令句残留数"])
    for k, v in out["B_ruff三把"].items():
        print(f"B {k}: rc={v['rc']} 条数={v['条数']} {v['汇总']}")
    print("C ast_gate 容器 =", in_container, "｜HEAD =", head_md5, "｜", out["C_靶子三格"]["链一判定"])
    print("边界 台账 =", out["边界自证"]["台账"], "｜残渣 =", out["边界自证"]["残渣"])
    print("产物 =", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
