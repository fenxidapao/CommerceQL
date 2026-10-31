# EX v2 诊断（Olist 60 题 / v1 读数现算）

> 窗口：EX v2 提升窗（`docs/07` v1.7.40，取号 `U-150` / `U-151` / `U-152`）
> 基准：`HEAD = efd744e`（开工时 `git status --short` 为空）
> 日期：2026-10-31
> 本件只做**量化**，不预写"能涨到多少"。所有读数均为**现算**，命令见 §8。

---

## 1. 五条开工读数（开工时现读，非转述）

| 项 | 读数 |
|---|---|
| `git rev-parse --short HEAD` | `efd744e` |
| `git status --short` | 空 |
| `docs/07` §4.8 指针行行首 | `下一个可用号 = U-150`（取号后已抬到 `U-153`） |
| `SQL_SYNTAX_ERROR` 的 case | `g01, o01, o04, o05, o16, o24, c03`（7 条；`c03` 是 clarify，**不计 EX 分母**） |
| `gate1_reject_rule == R14` 的 case | `g02, g06, g10, o02, o09, o13, o17, o22, o29, o34, o39, o44`（12 条，**本窗不修**） |

## 2. `AS order` 保留字：归因是**实测复原**的，不是抄报告

v1 批次记录里 `sql_text` 为 `None`、`terminal_error_detail` 为空 ⇒ **记录本身不含 SQL，无法自证归因**。
故从 `eval/olist/cassettes/olist_v1_r1.jsonl`（239 条）按"请求体里出现该 case 原问题"反查模型响应报文，逐条读它自己生成的 SQL：

| case | 命中匣带记录 | 含 `AS order` | 片段（模型原文） |
|---|---|---|---|
| `g01` | 5 | 2 | `FROM v_o_orders AS order JOIN v_o_payments AS payment …` |
| `o01` | 5 | 2 | 同上 |
| `o04` | 5 | 2 | `… AS order_cnt FROM v_o_orders AS order JOIN …` |
| `o05` | 5 | 2 | 同上 |
| `o16` | 5 | 2 | `… / NULLIF(COUNT(DISTINCT order.order_id),0) AS aov FROM v_o_orders AS order …` |
| `o24` | 5 | 2 | `… JOIN v_o_orders AS order ON order.order_id = order_item.order_id …` |
| `c03` | 5 | 2 | 同 `o16` 形状 |
| **合计** | 35 | **14** | 全带 239 条里共 **18** 条响应含 `AS order` |

**结论**：7 条 `SQL_SYNTAX_ERROR` **全部**由「订单表别名写成保留字 `order`」造成，且 `gen_sql` 与 `repair` 两轮各犯一次（每 case 2 条）—— 这正是"提示词改在 SQL 侧、`repair` 也必须改"的实测依据。

## 3. 三类 + R14 的分桶核算（三批，等式闭合）

桶定义（与 `eval/olist/report_olist.py::case_buckets` 同口径，判据只看 v1 记录与数据集）：

- `as_order`：`terminal_code == "SQL_SYNTAX_ERROR"`
- `round`：gold SQL 含 `ROUND(` **且** v1 判不等价
- `delivery`：`metrics` 含 `delivery_late_rate`（与 `round` **相交**，见下）
- `r14`：`gate1_reject_rule == "R14"`

| 批 | scored | 等价 | 非等价 | as_order（分母内） | round | delivery（含于 round） | r14 | 残差 |
|---|---|---|---|---|---|---|---|---|
| `w2_r1` | 54 | 23 | 31 | 6（另 `c03` 单列） | 13 | 5 | 12 | **0** |
| `w2_r2` | 55 | 23 | 32 | 5（另 `c03` 单列） | 14 | 5 | 12 | 1（`o15`） |
| `w2_r3` | 55 | 22 | 33 | 5（另 `c03` 单列） | 15 | 5 | 12 | 1（`o31`） |

**闭合验证**：`r1` 的 31 条非等价 = 6 + 13 + 12（`delivery` 5 条全部落在 `round` 内，不重复计）⇒ **r1 的非等价 100% 落入三类，无残差**；`r2` / `r3` 各有 1 条不属于任何一类（`o15` / `o31`），属模型自身差异，**不归因于本窗三次修复**。

逐批明细：

- `round`（r1）：`g05, g08, g09, o18, o20, o36, o37, o38, o40, o41, o42, o43, o45`
- `delivery`（三批一致）：`g09, o41, o42, o43, o45`
- `r14`（三批一致，不修）：`g02, g06, g10, o02, o09, o13, o17, o22, o29, o34, o39, o44`

## 4. `verdict.diffs` 的形状（决定修复是否真能改判）

`round` 桶内部的差异分三类，**不能一概而论**：

| 形状 | case | 说明 |
|---|---|---|
| 纯精度差（列级） | `g08`, `o20`, `o40` | `4.194` vs `4.1940298507462686`、`264.63` vs `264.63195856873824` ⇒ 去 gold 的 `ROUND` 后两侧同精度 |
| 纯精度差（行元组级） | `g05`, `o18`, `o36`, `o37`, `o38`, `o41`, `o42` | 差异写成「行多重集差异 / 金标行找不到：`(160.56,)`」—— 因为**整行元组**参与比较，任一小数位差异就变成"新行"；本质仍是精度差 |
| 精度差 **+ 排序分歧** | `g09`, `o45` | 除 `delivery_late_rate` 金标 `23.9295` vs 预测 `0` 外，`state` 列顺序也不一致（`AL` vs `TO`）—— 预测侧比率恒 0 ⇒ 排序全并列 ⇒ 顺序随机。**×100 修好后排序可能随之对齐，但不保证**（不预写结论） |
| 列无法配对 | `o43` | 「列数相同但内容不匹配」，需在 v2 实测后另行观察 |

## 5. 每条修复的预期影响面（只写**范围**，不写"能涨到多少"）

| 修复 | 直接影响面（r1 现算） | 不包含 |
|---|---|---|
| `U-150` 保留字别名规则 | 6 条 EX 分母内 `SQL_SYNTAX_ERROR`（+ `c03` 单列）；影响 `gen_sql` 与 `repair` 两个出口 | 不改闸门；不改 `DIALECT_NOTE`（它被 10 个模板注入） |
| `U-151` 去 gold 的 `ROUND` | 13 条 `round` 桶（r1）；55 条 execute 里 **37 条** gold 含 `ROUND(`（源文件 39 处出现） | **不改** `REL_TOL=1e-6`、不改排序口径；`o43` 的列配对问题不在其内 |
| `U-152` `delivery_late_rate` ×100 | 5 条 `delivery` 桶（三批一致，其中 `g09`/`o45` 另带排序分歧） | 不改 v1 bundle；`meta.dialect: sqlite` 保持 |
| （对照，**不做**）R14 / 方言 | 12 条，三批完全一致 | 本窗不修；若 v2 仍为 12 条，说明缺口未变，不得写成"模型能力问题" |

**上限口径（不是预测）**：若三类修复均完全生效且无副作用，`r1` 的理论上限 = `23 + 6 + 13 = 42 / 54`。此数**只作分母核算用**，不写进任何对外口径 —— 实际读数以 v2 三批实测为准（`report_v2.md`）。

## 6. 剩余缺口（单列，不归因模型）

- **R14 / 方言缺口 12 条**（`g02/g06/g10/o02/o09/o13/o17/o22/o29/o34/o39/o44`）：三批完全稳定。成因见 `PROMPT_EXV2 §0`：`ast_gate.py` 的 R14 只认"语义包声明常量"，Olist bundle 没有字面量白名单字段；且 SQLite 没有 `to_char`/`date_trunc`，即使放行 R14 仍会死在方言上。**本窗不动**。
- 残差 1 条/批（`o15` / `o31`）：模型自身差异，非三类修复对象。

## 7. 已知代价与口径（必须同框，不粉饰）

1. **匣带预期失效**：提示词改动会改出站报文，而匣带 key = `sha256(path + canonical_json(body))`（`eval/cassette.py:69-77`）⇒
   - `eval/cassettes/*.jsonl`（166 路径）与 `eval/olist/cassettes/olist_v1_*` 的**手工回放会 miss**；
   - ⇒ v1 的「零成本回放复核」（`results_v1_r1_replay.json` 那条）**从此不可复现**；
   - **不重录、不补录、不花钱**；`eval/reporter.py:295-318` 会把"匣带可复算"翻成 miss 说明，属**预期失效**，不是回归退化；
   - 匣带相关的**契约测试**用 tmp 合成匣带（`backend/tests/contract/test_replay_bound_contract.py:23-37`），不受影响。
2. **预算闸门是累计值**：`eval/runner.py:920-929` 的 `_breached()` 比较 `prior_usage + 本批`，`run_olist.py` 把共享账本 totals 读进 prior ⇒
   - 冒烟与三批统一传 `--max-cost-cny 3 --max-calls 1800`（**累计**上限，不是每批上限），共用 `eval/olist/budget_v2.json`；
   - 若按"每批 ¥1"写，批 3 会在开跑前触顶、一条不跑。
3. **模型价表只有两档**：`backend/app/llm/budget.py:120-134` 的 `PRICES` 只含 `deepseek-flash` 与 `deepseek-v4-pro`，未知模型按最贵档兜底并打 `price_guess`。
   - v1 单批实测：`calls=251` / `tokens=943,940` / `cost_cny=0.510667`（按 flash 价）；
   - 若被迫回退到 `deepseek-v4.1-flash`，账本价 ≈ ¥2.3/批 ⇒ 三批 ≈ ¥7 ⇒ **¥3 上限不成立，必须停并交裁定**（不硬跑，否则批被中途截断、读数作废）。
4. **提示词三份 `.txt` 原地改、不升版本号**：
   - 升版（新建 `gen_sql_v2.txt`）会让 `test_llm_prompts.py:64-65`、`test_planner_engine.py:1203`、`test_llm_gateway.py:451,945` 四处 `prompt_version == "gen_sql_v1"` 断言变红，违反"只允许既有 5 失败"；
   - 故原地改 + 登记新 `content_hash`（§9）。
5. **v1 记录本身不含失败 SQL**（`sql_text=None`、`terminal_error_detail={}`）⇒ 后续任何"某条失败是什么 SQL"的问题，只能从匣带复原（§2 做法），不能从 `results_v1_*.json` 读。

## 8. 复算命令（零 LLM / 零出站）

```bash
# ① syntax / R14 清单
python -c "import json;d=json.load(open('eval/olist/results_v1_r1.json',encoding='utf-8'));print([r['case_id'] for r in d['records'] if r.get('terminal_code')=='SQL_SYNTAX_ERROR'])"
python -c "import json;d=json.load(open('eval/olist/results_v1_r1.json',encoding='utf-8'));print([r['case_id'] for r in d['records'] if r.get('gate1_reject_rule')=='R14'])"

# ② 分桶：本窗在 eval/olist/report_olist.py 落一个纯函数 case_buckets(case, record)，
#    分桶口径的唯一真相在那里；本件 §3 的读数即由它现算（同一函数，不另写第二份）

# ③ 匣带复原（AS order 归因）
python -c "import json,re;recs=[json.loads(l) for l in open('eval/olist/cassettes/olist_v1_r1.jsonl',encoding='utf-8') if l.strip()];print(sum(1 for r in recs if re.search(r'\bAS\s+order\b', json.dumps(r.get('response'),ensure_ascii=False), re.I)))"
```

## 9. 三份 SQL 侧提示词的新 `content_hash`（改动后回填）

| 文件 | 改前 `content_hash` | 改后 `content_hash` | 版本号 |
|---|---|---|---|
| `backend/app/llm/prompts/gen_sql_v1.txt` | `7e1e48cc26fd7124` | `e58e1a6bdbf942fb` | `gen_sql_v1`（**未升**，理由见 §7.4） |
| `backend/app/llm/prompts/gen_sql_complex_v1.txt` | `ce0968f4fa823315` | `2fde3d5598e49413` | `gen_sql_complex_v1`（未升） |
| `backend/app/llm/prompts/repair_v1.txt` | `fbbb656b30f2bba1` | `7d7cc53ee4626a99` | `repair_v1`（未升） |

> 两列都用 `load_prompt(...).content_hash` 现算（与 `backend/app/llm/prompts/loader.py:197` 同口径：`sha256(utf-8 文本)[:16]`）。
> 改前值取自**改动前**的工作区（未提交状态，已与 `HEAD` 对照一致），改后值取自改动后。

## 10. 提示词改动后的回归读数（2026-10-31 现跑）

| 项 | 基线（PROMPT_EXV2 §2，`efd744e`） | 本窗改后 | 判定 |
|---|---|---|---|
| 全量 pytest（`--ignore=tests/integration`） | 2908 passed / 5 failed | **2909 passed / 5 failed**（431.07s） | 净 **+1 passed** = 本窗新增的单测；失败集合与前 5 条完全一致 |
| 既有 5 条失败 | `test_admin_eval_report_contract`×1、`test_shape_guard_faces`×2、`test_consistency_reporter`×1、`test_gate_inputs_p0_merge_two_state`×1 | 同左，**逐条同名** | 未新增、未修复（不属本窗） |

## 11. 去 ROUND 的对称风险（必须同框，不是缺陷登记）

去掉 gold 的 `ROUND` 后，两侧都是**原始精度**。若模型自己写了 `ROUND(...,2)`，则同样会出现 1e-5 量级的相对差 > `REL_TOL=1e-6` ⇒ 仍判不等（**方向相反的同一成因**）。
- 依据：v1/v2 金标对撞实测最大相对差 **3.094e-5**（`g05`），`rel>1e-3` 的条数 = 0，且**无结构变化、无零/非零翻转**（`git diff --no-index` 之外的对撞脚本见 §8② 同族做法）。
- 判据不变、容差不调；若 v2 出现"因模型主动舍入而判不等"的题，按 `U-151` 的备选 (a)（gold 除法显式 `1.0 *`）或 (b)（提示词精度规则）另行裁定，本窗不预改。
