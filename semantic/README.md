# semantic —— 语义包（指标口径的唯一来源）

> 语义层回答一个问题：**"GMV"到底算什么** —— 公式、默认过滤、时间口径、粒度、同义词、拒答黑话。
> 它被 L1（`app/semantics/`）加载、被 L2 绑定层与 L3 规划层消费，并在启动时过五步校验。

## 1. 目录

| 文件 | 作用 | 能不能手改 |
|---|---|---|
| `bundle_2026.09.14.1.yaml` | **语义包本体**（assets / metrics / dimensions / field_bindings / joins / default_predicates / time_semantics / policies / quality_gates / aliases / blacklist_terms） | 能改，但必须走 PR + 审批并递增 `meta.version` |
| `SCHEMA_v1.md` | 字段契约（**v1.1**，已按 `docs/07 §4.7.1` 裁定同步）：每个字段什么形状、谁依赖、依据哪条 | 能改（契约文档） |
| `validate_bundle.py` | 作者侧独立校验器（**34 项结构校验**），CI 直接跑 | 是工具 |
| `render_metric_dictionary.py` | 从 YAML 渲染口径字典 | 是工具 |
| `metric_dictionary.md` | **自动生成物**（首行 `GENERATED FILE - DO NOT EDIT BY HAND`） | ❌ **禁止手改**，改 YAML 后重跑生成器 |

## 2. ⚠️ 版本真相：只看 YAML 里的 `meta.version`

**文件名与版本号是刻意解耦的，二者不相等是设计，不是漂移：**

- 文件名恒为 `bundle_2026.09.14.1.yaml` —— 因为约 40 处硬编码引用它（`eval/_bootstrap.py`、`deploy/.env.example` 的 `SEMANTIC_BUNDLE_PATH`、config 默认值、探针、文档）。
- **版本真相 = YAML 的 `meta.version`**（现 `2026.10.16.2`）。
- 依据：`SCHEMA_v1.md §9 纪律 1`（内容变更必须递增版本号）＋ `§5 纪律 3`（本文件与 YAML 不一致时以 YAML 为准）。
- `SCHEMA_v1.md` 的文件名是 `v1`、标题是 `v1.1`，同理：**以标题为准**。

改包流程：改 YAML → 递增 `meta.version` → 重跑字典 → 跑校验器 → 依赖该包的缓存 / few-shot 索引必须失效（附录 B §B.4.1）。

## 3. 命令

```bash
# 结构校验（CI 用的就是这一条；34 项）
python semantic/validate_bundle.py
python semantic/validate_bundle.py path/to/bundle.yaml

# 重新生成口径字典（禁止手改产物）
python semantic/render_metric_dictionary.py            # 默认 bundle → 默认 out
python semantic/render_metric_dictionary.py --check    # CI 用：只校验是否已同步
```

## 4. 谁在读它

| 消费方 | 用什么 |
|---|---|
| `app/semantics/loader.py` + `runtime.py` + `materialize.py` | 加载 / 运行时查询 / 物化到 8 张检索表 |
| `app/binding/` | 表列 → 指标 → 粒度 → 精排的绑定依据 |
| `app/guard/policy_gate.py` | 口径版本一致性（`G2-ASSET`） |
| `app/main.py` lifespan | 启动时五步校验（含 `validate_bundle_path` 注入） |
| `eval/` 金标与门禁 | `results_w77_full166_applicability.json` 等的指标面 |

⚠️ 已知缺口（不隐瞒）：冻结集 124 条 `execute` 用例里有 **63 条（50.8%）**要的指标在语义包里根本不存在 ⇒ 计划层按契约拒答是**正确行为**，是考卷标错。详见 `OVERVIEW.md` §9.3。
