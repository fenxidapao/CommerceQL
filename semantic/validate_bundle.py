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
| ② | 校验 FR-12.2 的字段齐全性 | ✅ | 15 类（PRD FR-12.2）—— ⚠️ 07 §6.1 写「14 类」，**PRD 更多**，见 U-27 |
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

try:  # PyYAML 当前是 venv 里的**传递依赖**（见交付说明「转达清单」T-3）
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    print("FATAL: PyYAML 不可用。它不是 ADR-20 白名单项，当前靠传递依赖存在。", file=sys.stderr)
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
#: ⚠️ §6.1 正文写的是"14 类"，但同一句里**列举了 15 项**。以列举为准（15）→ 登记 U-27。
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

#: 项目自定义的扩展字段（U-23）—— 07 §12.2 的物化表与 §6.8.1 / §7.4 依赖它们，
#: 但附录 B 的结构示例里没有定义。缺失即 FAIL（它们已是实现依赖）。
EXTENSION_FIELDS: tuple[str, ...] = (
    "assets[].grain_level",
    "assets[].tenant_scoped",
    "assets[].quality_score",
    "metrics[].default_binding",
    "dimensions[].grain_level",
)


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
    rep.add(FAIL if ext_missing else PASS, "② 扩展字段（U-23）",
            f"缺 {ext_missing}" if ext_missing else f"{len(EXTENSION_FIELDS)}/{len(EXTENSION_FIELDS)} 齐全")

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
            if fb.get("default_binding"):
                bad_fb.append(f"{concept}: ambiguous 不得有 default_binding（会被 L3 静默解决）")
            levels = {c.get("grain_level") for c in fb.get("candidates") or []}
            if len(levels) > 1:
                bad_fb.append(f"{concept}: 候选 grain_level 不同 {sorted(levels)} → 按 §6.8.1 不构成竞争，"
                              f"应由 L2 按问句粒度直接选定，标 ambiguous 会导致澄清率虚高")
    rep.add(FAIL if bad_fb else PASS, "③ field_bindings 引用完整性",
            "; ".join(bad_fb) if bad_fb else
            f"{len(data.get('field_bindings') or [])} 条绑定全部可解析"
            f"（其中 ambiguous={sum(1 for f in data['field_bindings'] if f.get('ambiguous'))}）")

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
    """L3 覆盖率 —— DoD⑤「default_binding 与别名表就位（L1/L3 层依赖它）」的量化证据。"""
    fbs = data.get("field_bindings") or []
    with_db = [f for f in fbs if f.get("default_binding")]
    ambiguous = [f for f in fbs if f.get("ambiguous")]
    ambiguous_with_aliases = [f for f in ambiguous if f["concept"] in
                              {a["term"] for a in data.get("aliases") or []}]
    rep.add(PASS, "DoD⑤ field_bindings 的 default_binding 覆盖",
            f"{len(with_db)}/{len(fbs)} 有默认口径；{len(ambiguous)} 条标 ambiguous（{len(ambiguous_with_aliases)} 条同时有别名词）")

    metrics = data.get("metrics") or []
    active = [m for m in metrics if m.get("status") != "draft"]
    with_db_m = [m for m in active if m.get("default_binding")]
    rep.add(PASS if len(with_db_m) == len(active) else FAIL,
            "DoD⑤ 非 draft 指标 100% 有 default_binding",
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
