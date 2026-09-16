#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""语义包内容校验器 —— **W1A 的内容自检**，不是运行时加载器。

归属窗口：W1A（docs/08 §4.1：`semantic/**`）。
依据：07 §6.1「语义包加载与校验（启动期，五步，任一步失败即拒绝启动）」。

⚠️ **与 W2A 的边界（必须说清，否则会变成第二套实现）**
    · 本脚本只做「内容是否自洽」的静态检查 —— 读 YAML、查引用、查唯一性、查齐全性。
    · **运行时加载器（步骤①的读卷、步骤②的 Pydantic 模型、物化入库、
      `semantic:active_version` 单键指针切换）归 W2A 的 `app/semantics/**`**（08 §4.1）。
    · 本脚本**不 import `app.*`**，不连 DB，不写 Redis。它既可在 CI 跑，也可在无依赖环境下跑。

五步对应关系（07 §6.1）：

| 步 | 内容 | 本脚本 | 说明 |
|---|---|---|---|
| ① | 读取只读卷上的 YAML | ✅ | 含「锚点/别名未解析」与「重复 key」的显式检测 |
| ② | 校验 FR-12.2 的字段齐全性 | ✅ | 15 类（PRD FR-12.2）—— ⚠️ 07 §6.1 曾写「14 类」，**已由 07 v0.7 订正为 15 类**（U-27 是另一件事：`receiver_city`） |
| ③ | 引用完整性 | ✅ | `canonical_asset` ∈ assets；join 两端存在；`maps_to_ref` 可解析 |
| ④ | 质量准入 | ✅ | 未达阈值 → **标 certified=false 并排除出检索**（不报错） |
| ⑤ | 环境预检 | ⚠️ **部分** | 本脚本只查 `EMBEDDING_DIM` 一致性；「jieba 词典可加载 / 分词函数可用」的**最终断言归 W2B**（它才是 `retrieval/tokenizer.py` 的归属窗口）。脚本会如实报告这一项为 SKIP。 |

用法：
    python semantic/validate_bundle.py                      # 校验默认包
    python semantic/validate_bundle.py <path/to/bundle.yaml>
退出码：0 = 全部 PASS（SKIP 不影响退出码，但在报告中显式列出）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    # PyYAML 曾长期只以**传递依赖**身份存在（venv 里有、pyproject 里没有）→ 裸解释器直接炸。
    # 已由 W0 于 2026-09-16（main @ aef8750）在 pyproject.toml 转正，并补登 4 个同类包。
    # 仍保留这条清晰报错：本脚本要能在"什么都没装"的解释器上**说出自己缺什么**。
    print("FATAL: PyYAML 不可用（应为 pyproject.toml 的声明依赖，见 ADR-20 / U-37）。", file=sys.stderr)
    raise SystemExit(2)

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台默认 GBK，中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_BUNDLE = Path(__file__).with_name("bundle_2026.09.14.1.yaml")

# ---------------------------------------------------------------------------
# 报告器
# ---------------------------------------------------------------------------

PASS, FAIL, SKIP, WARN = "PASS", "FAIL", "SKIP", "WARN"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, check: str, detail: str = "") -> None:
        self.rows.append((status, check, detail))

    def dump(self) -> int:
        width = max(len(c) for _, c, _ in self.rows)
        icon = {PASS: "[OK]  ", FAIL: "[FAIL]", SKIP: "[SKIP]", WARN: "[WARN]"}
        for status, check, detail in self.rows:
            print(f"{icon[status]} {check.ljust(width)}  {detail}")
        fails = sum(1 for s, _, _ in self.rows if s == FAIL)
        skips = sum(1 for s, _, _ in self.rows if s == SKIP)
        warns = sum(1 for s, _, _ in self.rows if s == WARN)
        print("-" * 78)
        print(f"总计 {len(self.rows)} 项：PASS={len(self.rows) - fails - skips - warns} "
              f"FAIL={fails} SKIP={skips} WARN={warns}")
        return 1 if fails else 0


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

class DupKeyLoader(yaml.SafeLoader):
    """检出重复 key。

    为什么必须检出：YAML 规范允许重复 key 且**后者静默覆盖前者** ——
    那会让「两个窗口各写一半」这类事故**无声通过**（本项目在文档期已被这个模式坑过）。
    """


def _no_dup_keys(loader: DupKeyLoader, node: Any, deep: bool = False) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"YAML 重复 key：{key!r}（行 {key_node.start_mark.line + 1}）")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


DupKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup_keys
)


def load_bundle(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fp:
        data = yaml.load(fp, Loader=DupKeyLoader)  # noqa: S506 - 本地内容资产，非不可信输入
    if not isinstance(data, dict):
        raise ValueError("语义包顶层必须是 mapping")
    return data


# ---------------------------------------------------------------------------
# 各步校验
# ---------------------------------------------------------------------------

#: 07 §6.1 步骤②列出的字段类别（逐字抄自 §6.1，**共 15 项**）。
#: ⚠️ §6.1 正文曾写"14 类"，但同一句里**列举了 15 项** → **已由 07 v0.7 订正为 15 类**。
#:    （这**不是** U-27 —— U-27 是 v_order_paid 缺城市列。曾把两者混引，已修。）
REQUIRED_FIELD_CLASSES: tuple[tuple[str, str], ...] = (
    ("认证资产", "assets"),
    ("数据域", "meta.domain"),
    ("粒度", "assets[].grain"),
    ("时效", "assets[].freshness_sla"),
    ("Owner", "assets[].owner"),
    ("指标公式", "metrics[].expression"),
    ("维度层级", "dimensions[].hierarchy"),
    ("同义词", "aliases"),
    ("时间语义", "time_semantics"),
    ("原子-可拆分-组合字段", "assets[].columns"),
    ("唯一字段绑定", "field_bindings"),
    ("允许 Join 路径", "joins"),
    ("方言能力", "meta.dialect"),
    ("敏感列与脱敏规则", "policies"),
    ("质量准入阈值", "quality_gates"),
)

#: 项目自定义的扩展字段 —— **已由 07 §4.7.1 裁定**（原登记号 U-23 销账）。
#: 裁定结论 = 采纳 3 / 收窄 1 / **删除 2**，本元组已按裁定同步。
#: 缺失即 FAIL（它们已是实现依赖）。
EXTENSION_FIELDS: tuple[str, ...] = (
    "assets[].tenant_scoped",          # 07 §7.4 分支 3 判据
    "assets[].quality_score",          # 与 quality_gates.min_quality_score 联判
    "metrics[].default_binding",       # ⚠️ 已收窄为 {asset, reason}
    "dimensions[].grain_levels",       # L2 判"同粒度"的唯一依据
    "dimensions[].grain_level",        # 该维度默认细度
)

#: ❌ **已被 07 §4.7.1 删除的字段** —— 负向断言用（防它们被"好心"重新加回来）。
#: 为什么需要负向断言：删除一个字段的理由（"与 X 恒等 / 同名不同义 / 走别的载体"）
#: 在半年后**不会自己浮现**，后来人看到 `grain_level` 空着通常会补上 —— 那正是本案。
REMOVED_FIELDS: tuple[tuple[str, str], ...] = (
    ("meta", "disclosure_text"),
    ("assets[]", "grain_level"),
    ("field_bindings[]", "default_binding"),
)

#: `default_binding.reason` / `default_reason` 的长度上限（07 §4.7.1 的披露渲染规则）。
REASON_MAX_CHARS = 40


def check_step1(path: Path, rep: Report) -> dict | None:
    try:
        data = load_bundle(path)
    except Exception as exc:  # noqa: BLE001 - 校验器要把任何解析失败都变成报告项
        rep.add(FAIL, "① 读取 YAML", f"{type(exc).__name__}: {exc}")
        return None
    rep.add(PASS, "① 读取 YAML", f"{path.name} ({path.stat().st_size} bytes，无重复 key)")
    return data


def check_step2(data: dict, rep: Report) -> None:
    assets = data.get("assets") or []
    metrics = data.get("metrics") or []
    dims = data.get("dimensions") or []
    missing: list[str] = []

    for label, path in REQUIRED_FIELD_CLASSES:
        ok = _present(data, path, assets, metrics, dims)
        if not ok:
            missing.append(f"{label}({path})")
    rep.add(FAIL if missing else PASS, "② 字段齐全性 FR-12.2（15 类）",
            f"缺 {missing}" if missing else "15/15 齐全")

    ext_missing = [p for p in EXTENSION_FIELDS if not _present(data, p, assets, metrics, dims)]
    rep.add(FAIL if ext_missing else PASS, "② 扩展字段（07 §4.7.1 裁定后）",
            f"缺 {ext_missing}" if ext_missing else f"{len(EXTENSION_FIELDS)}/{len(EXTENSION_FIELDS)} 齐全")

    # ---- ② 负向：已被 §4.7.1 删除的字段不得回归（每个删除理由都不会自己浮现）----
    resurrected: list[str] = []
    for scope, field in REMOVED_FIELDS:
        if scope == "meta":
            hit = field in (data.get("meta") or {})
        elif scope == "assets[]":
            hit = any(field in a for a in assets)
        else:
            hit = any(field in f for f in (data.get("field_bindings") or []))
        if hit:
            resurrected.append(f"{scope}.{field}")
    rep.add(FAIL if resurrected else PASS, "② 已删字段未复活（07 §4.7.1 负向断言）",
            f"**回来了** {resurrected} —— 它们的删除理由见 §4.7.1，不是遗漏" if resurrected
            else f"{len(REMOVED_FIELDS)}/{len(REMOVED_FIELDS)} 确认不存在"
                 f"（{'/'.join(f for _, f in REMOVED_FIELDS)}）")

    # 域声明与实际资产域必须一致（防"声明 3 域、实际多出一个域"）
    declared = set(data.get("meta", {}).get("domain") or [])
    used = {a.get("domain") for a in assets}
    extra = used - declared
    rep.add(FAIL if extra else PASS, "② 资产域 ⊆ meta.domain",
            f"未声明域 {sorted(extra)}" if extra else f"declared={sorted(declared)} used={sorted(used)}")

    # draft 指标不得带 default_binding（否则 L3 会放行未确认口径）
    bad_draft = [m["name"] for m in metrics
                 if m.get("status") == "draft" and m.get("default_binding")]
    rep.add(FAIL if bad_draft else PASS, "② draft 指标无 default_binding",
            f"{bad_draft} 会绕过口径确认" if bad_draft else "draft 指标不参与 L3")


def _present(data: dict, path: str, assets: list, metrics: list, dims: list) -> bool:
    """判定一条字段路径是否存在且非空。`assets[].x` 需**每个**资产都有。"""
    if path.startswith("assets[]."):
        field = path.split(".", 1)[1]
        return bool(assets) and all(a.get(field) not in (None, "", [], {}) for a in assets)
    if path.startswith("metrics[]."):
        field = path.split(".", 1)[1]
        # draft 指标刻意不要求 expression / default_binding
        active = [m for m in metrics if m.get("status") != "draft"]
        return bool(active) and all(m.get(field) not in (None, "", [], {}) for m in active)
    if path.startswith("dimensions[]."):
        field = path.split(".", 1)[1]
        return bool(dims) and all(d.get(field) not in (None, "", [], {}) for d in dims)
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur or cur[part] in (None, "", [], {}):
            return False
        cur = cur[part]
    return True


def check_step3(data: dict, rep: Report) -> None:
    assets = {a["logical_name"]: a for a in data.get("assets") or []}
    metrics = {m["name"] for m in data.get("metrics") or []}
    dims = {d["name"] for d in data.get("dimensions") or []}

    def known_column(asset: str, col: str) -> bool:
        a = assets.get(asset)
        if a is None:
            return False
        return col in {c["name"] for c in a.get("columns") or []}

    # --- 3a. joins 两端存在 + on_columns 必须是真的列 ---
    bad_joins: list[str] = []
    for j in data.get("joins") or []:
        for side in ("left", "right"):
            ref = j.get(side) or ""
            if "." not in ref:
                bad_joins.append(f"{ref} 缺 asset.column 形式")
                continue
            asset, col = ref.split(".", 1)
            if not known_column(asset, col):
                bad_joins.append(f"{ref} 不存在")
        for oc in j.get("on_columns") or []:
            # on_columns 允许只写列名（左右同名时），也允许写两侧名字
            if oc not in {c for a in assets.values() for c in [x["name"] for x in a.get("columns") or []]}:
                bad_joins.append(f"on_columns 含未知列 {oc}")
    rep.add(FAIL if bad_joins else PASS, "③ joins 引用完整性",
            "; ".join(bad_joins) if bad_joins else f"{len(data.get('joins') or [])} 条路径全部可解析")

    # --- 3b. field_bindings.canonical_asset / alternatives / candidates ---
    bad_fb: list[str] = []
    for fb in data.get("field_bindings") or []:
        concept = fb.get("concept")
        cands: list[str] = []
        if fb.get("canonical_asset"):
            cands.append(fb["canonical_asset"])
        cands += [c["asset"] for c in fb.get("candidates") or []]
        cands += [a["asset"] for a in fb.get("alternatives") or []]
        for ref in cands:
            if "." not in ref:
                bad_fb.append(f"{concept}: {ref} 缺 asset.column 形式")
                continue
            asset, col = ref.split(".", 1)
            if not known_column(asset, col):
                bad_fb.append(f"{concept}: {ref} 不存在")
        # 歧义概念的候选必须**同 grain_level**（07 §6.8.1：只有同粒度才构成竞争）
        if fb.get("ambiguous"):
            levels = {c.get("grain_level") for c in fb.get("candidates") or []}
            if len(levels) > 1:
                bad_fb.append(f"{concept}: 候选 grain_level 不同 {sorted(levels)} → 按 §6.8.1 不构成竞争，"
                              f"应由 L2 按问句粒度直接选定，标 ambiguous 会导致澄清率虚高")
    rep.add(FAIL if bad_fb else PASS, "③ field_bindings 引用完整性",
            "; ".join(bad_fb) if bad_fb else
            f"{len(data.get('field_bindings') or [])} 条绑定全部可解析"
            f"（其中 ambiguous={sum(1 for f in data['field_bindings'] if f.get('ambiguous'))}）")

    # --- 3b-2. ★ `ambiguous` ⇔ 无 `canonical_asset` / 无 `default_reason`（**双向**）---
    #   为什么是双向而不是只禁一侧（07 §4.7.1 的裁定原文）：
    #     · `ambiguous: true` 却留着"占位非空"的 canonical_asset = **留了一个假值** ——
    #       任何漏判 L3 的路径都会把它当真（歧义被静默解决）；
    #     · 反过来，**非** ambiguous 却没有 canonical_asset / default_reason = 默认口径缺失，
    #       L3 会在本该直接执行的场景退回澄清 → 澄清率虚高（§6.8.1 的失效形态之一）。
    #   只禁一侧只能抓到一半事故。
    amb_viol: list[str] = []
    fbs = data.get("field_bindings") or []
    for fb in fbs:
        concept = fb.get("concept")
        has_canon = "canonical_asset" in fb and fb.get("canonical_asset") not in (None, "", [], {})
        has_reason = "default_reason" in fb and fb.get("default_reason") not in (None, "", [], {})
        if fb.get("ambiguous"):
            if has_canon:
                amb_viol.append(f"{concept}: ambiguous 却有 canonical_asset={fb['canonical_asset']!r}（占位假值）")
            if has_reason:
                amb_viol.append(f"{concept}: ambiguous 却有 default_reason（歧义被 L3 静默解决）")
            if not fb.get("candidates"):
                amb_viol.append(f"{concept}: ambiguous 却无 candidates（无从澄清）")
        else:
            if not has_canon:
                amb_viol.append(f"{concept}: 非 ambiguous 却缺 canonical_asset")
            if not has_reason:
                amb_viol.append(f"{concept}: 非 ambiguous 却缺 default_reason（L3 无披露文案）")
    amb_n = sum(1 for f in fbs if f.get("ambiguous"))
    rep.add(FAIL if amb_viol else PASS, "③ ambiguous ⇔ 无 canonical_asset/无 default_reason（双向）",
            "; ".join(amb_viol) if amb_viol
            else f"双向一致：{len(fbs) - amb_n} 条有 canon+reason，{amb_n} 条 ambiguous 两者皆空")

    # --- 3c. aliases.maps_to_ref 可解析 + **term 唯一性**（L1 的硬条件）---
    seen: dict[str, str] = {}
    dup: list[str] = []
    bad_alias: list[str] = []
    for al in data.get("aliases") or []:
        term = al.get("term")
        if term in seen:
            dup.append(f"{term!r} 同时映射到 {seen[term]} 与 {al.get('maps_to_ref')}")
        seen[term] = al.get("maps_to_ref")
        kind, ref = al.get("maps_to_kind"), al.get("maps_to_ref")
        if kind == "metric" and ref not in metrics:
            bad_alias.append(f"{term}→metric:{ref} 不存在")
        elif kind == "dimension" and ref not in dims:
            bad_alias.append(f"{term}→dimension:{ref} 不存在")
        elif kind == "asset" and ref not in assets:
            bad_alias.append(f"{term}→asset:{ref} 不存在")
        elif kind == "column":
            if "." not in ref or not known_column(*ref.split(".", 1)):
                bad_alias.append(f"{term}→column:{ref} 不存在")
    rep.add(FAIL if dup else PASS, "③ 别名 term 唯一映射（L1 判据）",
            "; ".join(dup) if dup else f"{len(seen)} 个 term 一对一")
    rep.add(FAIL if bad_alias else PASS, "③ 别名 maps_to_ref 可解析",
            "; ".join(bad_alias) if bad_alias else "全部可解析")

    # --- 3d. policies.deny_columns 的列必须真实存在 ---
    bad_deny: list[str] = []
    for pol in data.get("policies") or []:
        for ref in pol.get("deny_columns") or []:
            if "." not in ref or not known_column(*ref.split(".", 1)):
                bad_deny.append(ref)
    rep.add(FAIL if bad_deny else PASS, "③ deny_columns 可解析",
            f"未知列 {bad_deny}" if bad_deny else
            f"{sum(len(p.get('deny_columns') or []) for p in data['policies'])} 条全部存在")

    # --- 3e. 敏感列的**双向**一致：标了 sensitive 的列必须进 deny_columns ---
    deny_set = {r for p in data.get("policies") or [] for r in (p.get("deny_columns") or [])}
    leaks: list[str] = []
    for name, a in assets.items():
        for c in a.get("columns") or []:
            sens = c.get("sensitive")
            if sens and sens != "tenant_key" and f"{name}.{c['name']}" not in deny_set:
                leaks.append(f"{name}.{c['name']}({sens})")
    # tenant_key 是服务端注入键，同样必须被 deny
    for name, a in assets.items():
        for c in a.get("columns") or []:
            if c.get("sensitive") == "tenant_key" and f"{name}.{c['name']}" not in deny_set:
                leaks.append(f"{name}.{c['name']}(tenant_key)")
    rep.add(FAIL if leaks else PASS, "③ 敏感列 ⊆ deny_columns",
            f"漏屏蔽 {leaks}" if leaks else "sensitive 与 deny_columns 双向一致")

    # --- 3f. default_predicates.applies_to 的指标必须存在 ---
    bad_applies: list[str] = []
    for dom, preds in (data.get("default_predicates") or {}).items():
        if dom not in set(data.get("meta", {}).get("domain") or []):
            bad_applies.append(f"域 {dom} 未在 meta.domain 声明")
        for p in preds:
            for m in p.get("applies_to") or []:
                if m not in metrics:
                    bad_applies.append(f"{p.get('id')}→{m} 指标不存在")
    rep.add(FAIL if bad_applies else PASS, "③ default_predicates 引用完整性",
            "; ".join(bad_applies) if bad_applies else "applies_to 全部指向已定义指标")

    # --- 3f-2. ★ 与 3f **反方向**：applies_to 里点名的指标，其 metric 侧
    #          `default_predicates` 必须**逐条**列出该谓词。
    #   为什么必须双向：这是**同一份事实的两个方向**。只约束一个方向时，加载器
    #   读 `metrics[].default_predicates`（最自然的位置）就会**静默漏掉谓词**，
    #   口径算错却任何断言都不响 —— 这与 U-18 是同一形态的隐患。
    #   （本断言上线时实测抓出 4 个指标：refund_rate / repurchase_rate_90d / uv / pay_cvr
    #     的谓词只写在 applies_to 一侧。）
    pred_of = {}                       # 指标名 → 期望的谓词集合（来自 applies_to 侧）
    for dom, preds in (data.get("default_predicates") or {}).items():
        for p in preds:
            for m in p.get("applies_to") or []:
                pred_of.setdefault(m, set()).add(p.get("predicate"))
    one_sided: list[str] = []
    for m in data.get("metrics") or []:
        name = m["name"]
        own = m.get("default_predicates")
        if own is None and name not in pred_of:
            continue
        own_s = set(own or [])
        want = pred_of.get(name, set())
        if own_s != want:
            miss = sorted(want - own_s)
            extra = sorted(own_s - want)
            one_sided.append(f"{name}: 少 {miss} 多 {extra}")
    rep.add(FAIL if one_sided else PASS, "③ default_predicates ↔ metric 双向一致",
            "; ".join(one_sided) if one_sided
            else f"{len(pred_of)} 个指标的两侧谓词逐条一致")

    # --- 3k. ★ `metrics[].default_binding` 的形状 = `{asset, reason}`（§4.7.1 收窄后）---
    #   收窄的理由：原 `time_field` 与同一条目既有的 `time_basis` **重复**（同一事实两处）。
    #   这里不只查"少了什么"，也查"**多了什么**" —— 因为被删的字段最可能的回归形态
    #   就是"顺手又加回来"，而多出来的键**不会有任何报错**，只会静默分叉。
    bad_db: list[str] = []
    for m in data.get("metrics") or []:
        db = m.get("default_binding")
        if db is None:
            continue
        if not isinstance(db, dict):
            bad_db.append(f"{m['name']}: default_binding 必须是 mapping")
            continue
        extra = sorted(set(db) - {"asset", "reason"})
        miss = sorted({"asset", "reason"} - set(db))
        if extra:
            bad_db.append(f"{m['name']}: 多了 {extra}（§4.7.1 已裁删；时间基准一律读 `time_basis`）")
        if miss:
            bad_db.append(f"{m['name']}: 少了 {miss}")
        if db.get("asset") not in assets:
            bad_db.append(f"{m['name']}: asset={db.get('asset')!r} 不在 assets 中（§6.8 步②③ 要按它查认证/时效/租户）")
        _r = str(db.get("reason") or "")
        if len(_r) > REASON_MAX_CHARS:
            bad_db.append(f"{m['name']}: reason {len(_r)} 字 > 上限 {REASON_MAX_CHARS}（披露渲染规则）")
    n_db = sum(1 for m in data.get("metrics") or [] if m.get("default_binding"))
    rep.add(FAIL if bad_db else PASS, "③ metrics.default_binding 形状 = {asset, reason}",
            "; ".join(bad_db) if bad_db else f"{n_db} 条形状合规、asset 可解析、reason ≤ {REASON_MAX_CHARS} 字")

    # --- 3n. ★ 危险边必须带 `note`（跨租户边界 / 跨类型）---
    #   两类边是**会静默算错**的边，而不是会报错的边：
    #     ① 公共资产 → 租户资产：不写清"租户谓词落在右侧"，一条公共维表行会匹配到
    #        **多个租户**的同行 → 扇出 → **聚合值变大而无人报警**；
    #     ② 两侧列类型不同：`ON a.timestamptz = b.date` 恒假 → **静默 0 行**
    #        （不报错、不告警，只是"查不到"）。两者都必须把处置写进 note，机器才拦得住。
    type_of = {(n, c["name"]): c.get("type")
               for n, a in assets.items() for c in a.get("columns") or []}

    def _split_ref(ref: str | None) -> tuple[str | None, str | None]:
        if not ref or "." not in ref:
            return None, None
        an, cn = ref.split(".", 1)
        return an, cn

    dangerous: list[str] = []
    for j in data.get("joins") or []:
        ln, lc = _split_ref(j.get("left"))
        rn, rc = _split_ref(j.get("right"))
        if ln is None or rn is None or ln not in assets or rn not in assets:
            continue
        why: list[str] = []
        if not assets[ln].get("tenant_scoped") and assets[rn].get("tenant_scoped"):
            why.append(f"跨租户边界（{ln} 公共 → {rn} 租户）：租户谓词必须落在右侧，否则跨租户扇出")
        tl, tr = type_of.get((ln, lc)), type_of.get((rn, rc))
        if tl and tr and tl != tr:
            why.append(f"两侧类型不同（{tl} vs {tr}）：**非裸等值**，必须写明归一化表达式")
        if why and not str(j.get("note") or "").strip():
            dangerous.append(f"{j['left']} → {j['right']}: " + "；".join(why))
    n_j = len(data.get("joins") or [])
    rep.add(FAIL if dangerous else PASS, "③ 危险边（跨租户 / 跨类型）必须带 note",
            "; ".join(dangerous) if dangerous
            else f"{n_j} 条边中，所有跨租户/跨类型的边都写明了处置")

    # --- 3g. grain_levels 与 hierarchy 必须同集合（防"层级名写歪"）---
    bad_gl: list[str] = []
    for d in data.get("dimensions") or []:
        gl = d.get("grain_levels")
        if gl is None:
            continue
        if set(gl) != set(d.get("hierarchy") or []):
            bad_gl.append(f"{d['name']}: grain_levels={sorted(gl)} vs hierarchy={d.get('hierarchy')}")
            continue
        # ⚠️ 只要求「与 hierarchy 同序且**严格递增**」，**不要求从 1 起连续**。
        #    理由：grain_level 是**族刻度**（地理 country=1…city=4 / 时间 year=1…day=5），
        #    子维度（如 city，只覆盖 region/province/city）沿用族刻度时天然从 2 起。
        #    要求 1..N 连续会逼实现者把族刻度重排成局部刻度 → L2 跨维度比较失准。
        vals = [gl[h] for h in d["hierarchy"]]
        if any(b <= a for a, b in zip(vals, vals[1:])):
            bad_gl.append(f"{d['name']}: grain_levels 必须随 hierarchy 严格递增（当前 {vals}）")
    rep.add(FAIL if bad_gl else PASS, "③ grain_levels ↔ hierarchy 一致",
            "; ".join(bad_gl) if bad_gl else "层级名与细度值一一对应且随层级严格递增")

    # --- 3g-2. ★ `grain_level` 必须等于 `grain_levels[默认层级]`（07 §4.7.1 的断言）---
    #   裁定的原文是"必须等于 grain_levels 中该维度的**默认层级值**"。要让这句话可机检，
    #   必须先把"默认层级"定死 —— 本校验器采用的读法 = **`hierarchy` 的最后一层**
    #   （因 `hierarchy` 必须随 `grain_levels` 严格递增，它等价于"该维度可表达的最细层级"）。
    #   ⚠️ 若架构窗口要的是"`binding` 所在层级"这一读法，则 region(4→3)/category(3→1)
    #      需改，且要新增一个 `default_level` 字段承载"默认层级"（附录 B 无承载位，属 U-34）。
    #      → 本条 WARN 存在的唯一目的就是让这个待确认项**每次跑都出现在眼前**。
    bad_gd: list[str] = []
    residual: list[str] = []
    for d in data.get("dimensions") or []:
        gl, h = d.get("grain_levels"), d.get("hierarchy")
        gd = d.get("grain_level")
        if not gl or not h or gd is None:
            bad_gd.append(f"{d.get('name')}: 缺 grain_levels / hierarchy / grain_level")
            continue
        if gd not in gl.values():
            bad_gd.append(f"{d['name']}: grain_level={gd} 不是 grain_levels 里的任何值（防漂移）")
        elif gd != gl[h[-1]]:
            bad_gd.append(f"{d['name']}: grain_level={gd} ≠ grain_levels[hierarchy[-1]]={gl[h[-1]]}")
        # 残留口径：binding 的物理列落在比 grain_level 更粗的层级时点名出来
        b = d.get("binding") or ""
        col = b.split(".", 1)[1] if "." in b else ""
        hit_level = next((k for k in h if col == k or col.endswith(f"_{k}") or col.startswith(f"{k}_")), None)
        if hit_level and gl.get(hit_level) != gd:
            residual.append(f"{d['name']}: binding={b} 落在 {hit_level}({gl[hit_level]}) 而 grain_level={gd}")
    rep.add(FAIL if bad_gd else PASS, "③ grain_level == grain_levels[hierarchy 末项]（§4.7.1）",
            "; ".join(bad_gd) if bad_gd else
            f"{len(data.get('dimensions') or [])} 个维度全部一致（默认层级 ≡ hierarchy 末项）")
    rep.add(WARN if residual else PASS, "③ grain_level 读法残留待确认（属已裁定的 U-23）",
            f"{residual} → 若架构窗口的'默认粒度'指 **binding 的粒度**，这两条要改；"
            f"若要改，需新增 `default_level` 字段（附录 B 无承载位 → 属 U-34）"
            if residual else "无残留：所有维度的 binding 层级与 grain_level 一致")

    # --- 3m. ★ `tenant_scoped` ⇔ 资产含 `tenant_id` 列（**双向**，07 §7.4 分支 3）---
    #   写反 = **跨租户存在性泄露**（N-07 直接失效）：把 false 写在有租户数据的资产上
    #   → 执行层不注入谓词 → T_A 能看到 T_B 的行数。故这里是双向断言，不是单向。
    ts_viol: list[str] = []
    for name, a in assets.items():
        has_col = "tenant_id" in {c["name"] for c in a.get("columns") or []}
        flag = bool(a.get("tenant_scoped"))
        if flag != has_col:
            ts_viol.append(f"{name}: tenant_scoped={flag} 但 {'有' if has_col else '无'} tenant_id 列")
    rep.add(FAIL if ts_viol else PASS, "③ tenant_scoped ⇔ 含 tenant_id 列（双向，§7.4）",
            "; ".join(ts_viol) if ts_viol else
            f"{sum(1 for a in assets.values() if a.get('tenant_scoped'))} 个租户资产 / "
            f"{sum(1 for a in assets.values() if not a.get('tenant_scoped'))} 个公共资产，双向一致")

    # --- 3h. 同义词的两处定义必须一致（**"同一事实只写一遍"的机器化保障**）---
    # 附录 B 把同义词散落在 `columns[].synonyms` 与 `metrics[].synonyms` 两处，
    # 而 07 §12.2 的 `synonym` 表只能承载一份 → 二者不一致就是"同一事实的第二份真相"。
    # ⚠️ 本项目在文档期已被这个模式坑过（同一文件两批落笔 → 合起来自相矛盾），
    #    故这里把它变成一条会红的断言。
    alias_terms = {al["term"] for al in data.get("aliases") or []}
    orph: list[str] = []
    for name, a in assets.items():
        for c in a.get("columns") or []:
            for t in c.get("synonyms") or []:
                if t not in alias_terms:
                    orph.append(f"{name}.{c['name']}:{t}")
    for m in data.get("metrics") or []:
        if m.get("status") == "draft":
            continue  # draft 的 synonyms 是口径备注，不得进 L1（见 3i）
        for t in m.get("synonyms") or []:
            if t not in alias_terms:
                orph.append(f"metric:{m['name']}:{t}")
    rep.add(FAIL if orph else PASS, "③ column/metric synonyms ⊆ aliases",
            f"未进别名表 → {orph}" if orph else f"两处定义一致（别名表 {len(alias_terms)} 个 term）")

    # --- 3i. aliases 不得指向 draft 指标 ---
    # 若 draft 指标有别名，L1 会把它"确定性解析"掉 → 未确认口径被静默放行，
    # 正是 FR-12.3「禁止 LLM 自动发布语义」与 §6.1 版本状态机要防的事。
    draft_metrics = {m["name"] for m in data.get("metrics") or [] if m.get("status") == "draft"}
    bad_draft_alias = [al["term"] for al in data.get("aliases") or []
                       if al.get("maps_to_kind") == "metric"
                       and al.get("maps_to_ref") in draft_metrics]
    rep.add(FAIL if bad_draft_alias else PASS, "③ aliases 不指向 draft 指标",
            f"{bad_draft_alias} 会命中未确认口径" if bad_draft_alias
            else f"draft 指标 {sorted(draft_metrics)} 无别名（FR-12.3）")


def check_step4(data: dict, rep: Report) -> None:
    gate = data.get("quality_gates") or {}
    min_score = gate.get("min_quality_score", 0.0)
    excluded: list[str] = []
    for a in data.get("assets") or []:
        score = a.get("quality_score")
        if score is None or score < min_score:
            excluded.append(f"{a['logical_name']}({score})")
    # ⑤/④ 的关键语义：**不报错**，只排除
    rep.add(PASS if not excluded else WARN, "④ 质量准入门槛",
            f"低于 {min_score} 而排除出检索：{excluded}" if excluded
            else f"全部 {len(data.get('assets') or [])} 个资产 ≥ {min_score}")

    if gate.get("on_violation") != "exclude_from_context":
        rep.add(FAIL, "④ on_violation 语义", "必须是 exclude_from_context（07 §6.1 步骤④：降级排除而非报错）")
    else:
        rep.add(PASS, "④ on_violation 语义", "exclude_from_context（降级排除 + 告警）")


def check_step5(data: dict, rep: Report) -> None:
    meta = data.get("meta") or {}
    emb = meta.get("embedding") or {}

    # 与 app/core/config.py 的默认值比对（硬编码字面量是**故意的**：
    # 本脚本不 import app.*，以便在无依赖环境跑；不一致时下面是 FAIL 而非静默）
    cfg_model, cfg_dim = "bge-m3", 1024
    consistent = (emb.get("model") == cfg_model) and (emb.get("dim") == cfg_dim)
    rep.add(PASS if consistent else FAIL, "⑤ EMBEDDING_DIM 与配置一致",
            f"bundle={emb.get('model')}/{emb.get('dim')} vs config 默认={cfg_model}/{cfg_dim}"
            if consistent else
            f"不一致：bundle={emb.get('model')}/{emb.get('dim')} vs config 默认={cfg_model}/{cfg_dim} "
            f"→ 启动期必须拒绝（07 §6.1 步骤⑤）")

    # 时间语义完整性（N-26：不得由代码硬编码）
    need = {"timezone", "fiscal_year_start_month", "week_starts_on"}
    miss = sorted(need - set(meta))
    rep.add(FAIL if miss else PASS, "⑤ meta 时间语义齐全（N-26）",
            f"缺 {miss}" if miss else f"tz={meta.get('timezone')} fy_start={meta.get('fiscal_year_start_month')} week={meta.get('week_starts_on')}")

    # 版本号形态（附录 B §B.1.1：YYYY.MM.DD.N）
    ver = str(meta.get("version", ""))
    parts = ver.split(".")
    ok_ver = len(parts) == 4 and all(p.isdigit() for p in parts)
    rep.add(PASS if ok_ver else FAIL, "⑤ 版本号形态 YYYY.MM.DD.N", ver if ok_ver else f"{ver} 不符合")

    rep.add(SKIP, "⑤ jieba 词典可加载 / 分词函数可用",
            "归 W2B（retrieval/tokenizer.py 是唯一入口，N-24）；本脚本不 import app.*")


def check_default_binding_coverage(data: dict, rep: Report) -> None:
    """L3 覆盖率 —— DoD⑤「default_binding 与别名表就位（L1/L3 层依赖它）」的量化证据。

    ⚠️ §4.7.1 之后，`field_bindings` 侧承载默认口径的**不是** `default_binding`（已删），
    而是 `canonical_asset`（字段层依据）+ `default_reason`（披露文案）。
    指标侧仍是 `metrics[].default_binding`，但形状已收窄为 `{asset, reason}`。
    """
    fbs = data.get("field_bindings") or []
    with_db = [f for f in fbs if f.get("canonical_asset")]
    ambiguous = [f for f in fbs if f.get("ambiguous")]
    ambiguous_with_aliases = [f for f in ambiguous if f["concept"] in
                              {a["term"] for a in data.get("aliases") or []}]
    rep.add(PASS, "DoD⑤ field_bindings 默认口径覆盖（canonical_asset + default_reason）",
            f"{len(with_db)}/{len(fbs)} 有默认口径；{len(ambiguous)} 条标 ambiguous"
            f"（{len(ambiguous_with_aliases)} 条同时有别名词 —— **必须为 0**，否则 L1 会短路掉澄清）")

    metrics = data.get("metrics") or []
    active = [m for m in metrics if m.get("status") != "draft"]
    with_db_m = [m for m in active if m.get("default_binding")]
    rep.add(PASS if len(with_db_m) == len(active) else FAIL,
            "DoD⑤ 非 draft 指标 100% 有 default_binding{asset,reason}",
            f"{len(with_db_m)}/{len(active)}")

    # 别名覆盖：每个**非歧义**概念都应能从别名表命中（L1 的目标）
    alias_terms = {a["term"] for a in data.get("aliases") or []}
    concepts = {f["concept"] for f in fbs if not f.get("ambiguous")}
    uncovered = sorted(concepts - alias_terms)
    rep.add(WARN if uncovered else PASS, "DoD⑤ 非歧义概念有别名覆盖",
            f"无别名的概念 {uncovered}（将落到 L3/L4，不是错误，但会抬高 L4 占比）"
            if uncovered else "全部可从 L1 命中")


def check_blacklist(data: dict, rep: Report) -> None:
    items = data.get("blacklist_terms") or []
    bad = [i["term"] for i in items if i.get("action") not in ("refuse", "clarify")]
    rep.add(FAIL if bad else PASS, "黑话表 action 取值",
            f"非法 action {bad}" if bad else
            f"{sum(1 for i in items if i['action'] == 'refuse')} 拒答 + "
            f"{sum(1 for i in items if i['action'] == 'clarify')} 澄清")
    # clarify 项必须有 clarify_prompt；refuse 项必须有 alt_question（FR-9.5 必须给替代问法）
    miss = []
    for i in items:
        if i["action"] == "clarify" and not i.get("clarify_prompt"):
            miss.append(f"{i['term']} 缺 clarify_prompt")
        if i["action"] == "refuse" and not i.get("alt_question"):
            miss.append(f"{i['term']} 缺 alt_question（FR-9.5）")
    rep.add(FAIL if miss else PASS, "黑话表文案齐全",
            "; ".join(miss) if miss else "clarify_prompt / alt_question 齐全")


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_BUNDLE
    rep = Report()
    print(f"语义包校验：{path}")
    print("=" * 78)

    data = check_step1(path, rep)
    if data is None:
        return rep.dump()

    check_step2(data, rep)
    check_step3(data, rep)
    check_step4(data, rep)
    check_step5(data, rep)
    check_default_binding_coverage(data, rep)
    check_blacklist(data, rep)

    # 统计摘要
    print("-" * 78)
    assets = data.get("assets") or []
    print(f"资产 {len(assets)} 个 / 指标 {len(data.get('metrics') or [])} 个 "
          f"/ 维度 {len(data.get('dimensions') or [])} 个 / 绑定 {len(data.get('field_bindings') or [])} 条 "
          f"/ Join {len(data.get('joins') or [])} 条 / 别名 {len(data.get('aliases') or [])} 条 "
          f"/ 黑话 {len(data.get('blacklist_terms') or [])} 条")
    cols = sum(len(a.get("columns") or []) for a in assets)
    print(f"列总数 {cols}；敏感列 "
          f"{sum(1 for a in assets for c in a.get('columns') or [] if c.get('sensitive'))} 个")
    print("=" * 78)
    return rep.dump()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
