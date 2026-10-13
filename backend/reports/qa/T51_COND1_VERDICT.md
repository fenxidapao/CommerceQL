# T-51 条件①（L4 触发率）· QA 验收件（第 31 轮 R31m）

> 落笔现读：**2026-10-13 16:26 ＋0800** ｜ 起点 HEAD **`d7037ff`／515 笔** ｜ 本窗 **零出站**（未调用任何模型）
> 被验对象：W8 第 30 轮（提交 `d7037ff`）＝ 冲突整理两处 🔻 ＋「取 L4 触发率」零成本取证
> 裁定范围：只裁「执行与证据是否一致」。不裁判据措辞、不发号、不改单。

---

## 一、W8 的两条主张 ↔ 本窗复算

| # | W8 主张 | 本窗现读 | 判 |
|---|---|---|---|
| A1 | `app.query_plan` **355 行**：L1=36／L3=319／L2=0／L4=0 ⇒ **L4 触发率 0.0% < 10%** | ✅ **逐位复现**（`L1\|unresolved\|36`、`L3\|resolved_default\|319`，合计 355）；`count(distinct task_id)`=355 ⇒ **一任务一行，无重复膨胀** | ✅ 成立 |
| A2 | 尺自检：CHECK 域含 `L4`、`NULL`=0 行、单 `bundle_version` | ✅ 现读 `CHECK (binding_layer = ANY (ARRAY['L1','L2','L3','L4']))` ⇒ **尺能看见 L4**；三列 `NULL` 计数 **0/0/0**；`bundle_version` 唯一值 `2026.09.14.1`（355/355） | ✅ 成立 |
| B1 | 口径证成：`eval/harness.py:758` `query_plan_writer=None` ⇒ 评测不写该表，355 行只来自活体路径 | ✅ 现读 `harness.py:758 = query_plan_writer=None`；全仓 `query_plan_writer=` **仅两处**：`deps.py:829`（生产传 `QueryPlanStore`）／`harness.py:758`（传 `None`）⇒ **写面唯一** | ✅ 成立 |
| B2 | `bind` 走**在线** `score_l4` ⇒ 真实四层判定，L4=0 非构造性结果 | ✅ 现读 `bind.py:95` `await _online_l4(...)`（唯一调用点，**无注入分支**）；四层顺序 `L1→L2→L3→L4`（`four_layer.py:237-291`）；`L3` 拒收条件现读 `:335` `if resolution.declared_ambiguous or not resolution.default_reason: return None` ⇒ 「城市」`ambiguous=True` ⇒ **L4 可达** | ✅ 成立 |
| C | 「355 行只来自**活体路径**」 | ⚠️ **前提成立、但该面只是下界**（§二） | 🔻 收窄 |

---

## 二、🔴 本窗认定：该面是**下界**，且「0」的**主因不是 L4 不发生**

W8 的 4 条证成链**全部成立**，但它们合起来证的是「**这 355 行不是注入产生的**」，**不能**证「**L4 在生产不发生**」。本窗用**同一路径的自产证据**把边界钉死：

### 2.1 `bind` 自己的落库面里，`ambiguous` ＝ 0

| 面 | 行数 | `binding_state` 构成 | L4 |
|---|---|---|---|
| `app.query_plan`（**bind 的产物**） | 355 | `resolved_default 319` ＋ `unresolved 36` | **0** |
| `app.audit_log` 中 `outcome='clarify'` | **139** | — | — |

⇒ 现读 `bind.py:153` 的 `_write_query_plan` 调用**在** `if result.state is AMBIGUOUS` 分支**之外**（`:140-153` 逐行现读：AMBIGUOUS 分支只填 `binding_ambiguity`，随后**无条件**写盘）⇒ **落库面不会漏 `ambiguous` 行**。既然审计面有 139 条澄清而 `query_plan` 里 `ambiguous` ＝ **0/355** ⇒ **这些澄清全部产生在 `bind` 之前**。

### 2.2 决定性证据：`clarify` 的**来源节点全部早于 bind**

现读 `eval/results_v2_live_20261003T1632Z.json`（166 records）：

| 现读量 | 值 |
|---|---|
| `terminal_event` 分布 | `refuse 87`／`complete 48`／`clarify **30**`／`error 1` |
| 30 条 clarify 的 `nodes` 末两位 | **全部** `… → intent → clarify_out`（`intent 29`／`normalize 1`） |
| 30 条 clarify 里 `nodes` 含 `bind` 的 | **0** |
| 走到 `bind` 的 73 条，其终态 | `complete 48`／`refuse 24`／`error 1` ⇒ **无一条 `clarify`** |
| `C-CITY-01..04`（唯一带真竞争对的 4 条）的 `nodes` | `trusted_context → normalize → intent → **clarify_out**` ⇒ **在 `intent` 被截胡，从未进 `bind`** |
| 同 4 条的 `binding_status` | `None`（**从未到过 bind** —— bind 是唯一写该字段的节点） |
| 现读题面 0/355 提及「城市/city」 | ⇒ 样本里**也没有** `city_ambiguity` 题 |

⇒ **「bind 从不出 `ambiguous`」的主因 ＝ 意图/时间窗层的澄清在 `intent` 就把话题截走，`bind` 拿不到会触发 L4 的题**。旁证（同一路径、独立读数）：**166 条里 63 条误拒中，39 条从未到过 `bind`**（现读 `nodes` 不含 `bind`，`execute` 期望被判 `refuse`）⇒ 「过早终止」是**系统性**形状，不是本 4 条的孤例。

### 2.3 由此产生的**常驻口径**（本窗新立）

> **`query_plan` 面的 `binding_layer` 分布 = L4 触发率的「下界」，不是全集。**
> 覆盖差（**同窗**可复算，🔴 必须同窗比 —— 全表比会把窗口外的行算进来）：
> 取 `audit_log.timestamp >= 2026-09-22`（`query_plan` 最早行所在日）⇒ 审计面 **839 行**，其中带 `query_plan` 的 **355 行** ⇒ **覆盖率 42.3%**（`round(100*355/839,1)`）。该窗内 `outcome` 构成 ＝ `refuse 397`／`failed 235`／`success 109`／`clarify **98**`。
> ⇒ 该面只覆盖**走到 `bind` 的请求**；`intent`／`normalize`／`link`／`plan` 四处的澄清/拒答**都不进该面** ⇒ **同窗内 484 行（57.7%）不在面上**。
> ⇒ **引用纪律**：报「L4 触发率」必须**同时报三样** —— (a) 观测面（`query_plan`／`binding_layer_total`／审计面）＋ (b) **该面覆盖的图阶段**＋ (c) **样本里是否存在该概念的题**。三缺一即不得单独引用。

---

## 三、裁决（分两段）

| 段 | 判 |
|---|---|
| **读数段** | ✅ **`app.query_plan` 面上，L4 ＝ 0/355 ＝ 0.0%**（L1 36／L3 319／L2 0／L4 0），复算逐位一致 ⇒ **PRD §12.9 条件①「L4 触发率 > 10%」在该面上 = 不满足** |
| **制度段（🔴 保留）** | ⚠️ **不宜一步定案为「全系统不满足」**：① 该面是**下界**（§2.3）；② 我 R31l 具名的零代码出口 **`binding_layer_total`（`deps.py:571`）覆盖面更宽** —— 现读 `service.py:421` `self._observer.on_binding(event)` 在 `_emit` 内、由 `resolve_detailed` 的**主路径**调用（`:349`），覆盖**每一次四层判定**；③ 一个更宽的观测面**尚未读** |

⇒ **处置建议（不代裁）**：

1. **可立即落**：把「`query_plan` 面 L4 ＝ 0/355」登记为**条件① 的现读下界**；**判据措辞不动**。
2. **补一步再定案（零成本）**：读一次 `/metrics` 的 **`binding_layer_total`**（现读 `deps.py:768 observer=MetricsBindingObserver()` 已接真实观测者，端点已注册）。
   🔴 **但必须同时报该计数器的采样窗**：计数器随进程重启归零，现读容器 `Up` 仅 **33 min** 量级，而 `query_plan` 的 355 行跨 **2026-09-22 → 10-07（15 天）** ⇒ **两个面的时间窗不可比**；不报窗口就是拿 33 分钟比 15 天。
3. **不建议**：为条件① 花钱跑批（下界已给；条件②③ 未取 ⇒ 三前置不可能凑齐，钱买不到可用结论）。

---

## 四、`PROMPT_新窗` 两处 🔻 验收（冲突整理）

| 处 | 现读 | 判 |
|---|---|---|
| §2 查5 G-6 | 🔻 块现读「两把不可互换：门禁面 **7,268.4 ms**（数值上 ≤ 8,000）｜自费面 **8,887.4 ms**（`n=18<20` ⇒ 不可引用）⇒ G-6 维持 **UNVERIFIED**；🚫 不得引 8,887.4 作达标证据，🚫 也不得写死『够格即 FAIL』；引用 p95 须同报「文件名＋样本数＋分母口径」」 | ✅ **与 QA `RELAY §34`／`PROMPT_新窗 §4.1` 逐句一致** |
| §2 查1 远端 | 🔻 块现读「`8cbb58d`／514 笔已 push，远端 ＝ 本地齐平；上面『远端停在 `00bb620`』属起草时快照」 | ✅ 成立（本窗现读 `d7037ff`／515／`origin/main` 同点） |
| 冲突④ docstring | 现读已含「按 QA `RELAY §37.4` 订正理由」＋「`float("0.005305")` **能解析、不抛**」 | ✅ **已闭，勿再改** |
| 冲突③ 容器件数 | QA `§12` 已自订正为六件 | ✅ 无需动作 |
| 冲突⑤ 取号行 | `docs/07:1090` 现读 `U-141` | ✅ 无动作 |

---

## 五、复算命令（零成本，全只读）

```
# 1) query_plan 层分布（含尺自检）
docker exec -i commerceql-pg-1 psql -U postgres -d ecom -q -t -A -F'|' -c \
 "begin; select binding_layer,binding_state,count(*) from app.query_plan group by 1,2 order by 1,2; rollback;"
# 期望：L1|unresolved|36 / L3|resolved_default|319

# 2) 尺能看见 L4 吗
docker exec -i commerceql-pg-1 psql -U postgres -d ecom -q -t -A -c \
 "begin; select pg_get_constraintdef(oid) from pg_constraint where conrelid='app.query_plan'::regclass and contype='c'; rollback;"

# 3) 反证：审计面澄清量 vs query_plan 覆盖
docker exec -i commerceql-pg-1 psql -U postgres -d ecom -q -t -A -F'|' -c \
 "begin; select a.outcome, count(*) filter (where q.task_id is not null) with_qp, count(*) filter (where q.task_id is null) no_qp from app.audit_log a left join app.query_plan q on q.task_id=a.task_id group by 1; rollback;"
# 期望：clarify|0|139

# 4) 决定性：eval 里 clarify 的来源节点（30 条全部止于 intent）
#   读 eval/results_v2_live_20261003T1632Z.json 的 records
```

---

> 🔴 **本件不构成的结论**：① 不得说「L4 在生产从不发生」（该面是**下界**）② 不得说「条件① 已定案为不满足」（建议先读更宽的 `binding_layer_total`，并同报采样窗）③ 不得说「方案 A 可以装」（三前置现读 1/3，条件① 未定案）④ 不得说「τ 已校准」。


## 二、2026-10-13 追加（R31m）：QA 独立复算与两条口径

> 追加现读：**2026-10-13 16:26 ＋0800** ｜ 起点 HEAD **`d7037ff`／515 笔** ｜ 本窗 **零出站**

### 2.1 「355 行只来自活体路径」的**独立复核结论**

W8 第 30 轮的 4 条证成链**逐条成立**（`harness.py:758=None` 写面唯一／`bind.py:95` 唯一在线调用点无注入分支／`CHECK` 域含 `L4`／三列 `NULL`=0），**但该面是 L4 触发率的下界**：

| 现读 | 值 |
|---|---|
| `app.query_plan` 的 `ambiguous` | **0 / 355** |
| `app.audit_log` 的 `outcome='clarify'` | **139** |
| 同窗（`timestamp >= 2026-09-22`）审计面 / 带 `query_plan` | **839 / 355** ⇒ 覆盖率 **42.3%** |
| `eval` 166 records 里 `terminal_event=clarify` 的 **30 条**来源节点 | **全部 `intent → clarify_out`**（含 `bind` ＝ **0**） |
| 走到 `bind` 的 **73 条**终态 | `complete 48`／`refuse 24`／`error 1` ⇒ **无 `clarify`** |
| `C-CITY-01..04` 的 `nodes` | `trusted_context → normalize → intent → clarify_out`，`binding_status=None` |

⇒ **主因 ＝ 意图/时间窗层的澄清在 `intent` 截走话题**，不是「L4 不发生」。
⇒ 🔴 **新增常驻口径**：报「L4 触发率」必须同报 **(a) 观测面 ＋ (b) 该面覆盖的图阶段 ＋ (c) 样本里是否有该概念的题**；三缺一不得引用。
⇒ **`query_plan` 面的 `binding_layer` 分布 ＝ 下界**；更宽的 `binding_layer_total` 面**尚未读**。

### 2.2 🔴 本窗口径订正（自曝一则）

| # | 原表述 | 现读 | 处置 |
|---|---|---|---|
| 1 | 12.3 首版写「审计面 937 行 － `query_plan` 355 行 ＝ 582 行（62.1%）不在该面」 | 🔴 **该减法跨了窗口**：`audit_log` 最早 **2026-09-19**，而 `query_plan` 最早 **2026-09-22** ⇒ 前 3 天的行**本来就不可能**有 `query_plan` 行，把那 3 天算进差量 = **拿不同窗口比**。**同窗**正确值 ＝ `>= 2026-09-22` 的 **839 行** ⇒ 覆盖率 **42.3%**、不在面 **484 行（57.7%）** | 🔻 **订正**（原文已改，不再引用 582／62.1%） |

> 该订正是本项目既有纪律「**先量节边界再量差**」的又一次复发：范围否定/差量必须先对齐窗口。

### 2.3 澄清两来源（不得混判）

| 来源节点 | 类型 | `reason` |
|---|---|---|
| `intent`／`normalize` → `clarify_out` | **时间/意图型** | `time_ambiguous` |
| `bind` → `clarify_out` | **字段绑定型**（经 `binding_ambiguity`） | `ambiguous_field_binding` |

现读铁证：`eval` 166 条里 **30 条 `clarify` 全部止于 `intent`** ⇒ **绑定型澄清路径在冻结集上从未被走到**（本窗只陈述现象，**不判为缺陷**；立号与否待总控点名）。


## 三、2026-10-13 追加（R31m · 续）：**`binding_layer_total` 面已实测** ＋ 一条**双向确认的零触达**

> 追加现读：**2026-10-13 16:32 ＋0800** ｜ 起点 HEAD **`d7037ff`／515 笔** ｜ 本窗 **零出站**（唯一外部动作 ＝ `curl` 本机回环只读端点）

### 3.1 🔴 `binding_layer_total` 实测（QA 自己读，不是转述）

```
curl -s http://127.0.0.1:8000/api/v1/metrics   ⇒ http=200 bytes=20825
```

| 指标 | 现读 |
|---|---|
| `binding_layer_total{layer="L1"}` | **0** |
| `binding_layer_total{layer="L2"}` | **0** |
| `binding_layer_total{layer="L3"}` | **0** |
| `binding_layer_total{layer="L4"}` | **0** |
| `binding_state_total{state="ambiguous"}` | **0**（另三态亦全 0） |
| `binding_tau_calibrated` | **0** |

⇒ **两个独立面（`query_plan` 落库面 ＋ `/api/v1/metrics` 计数面）现读都是 L4 ＝ 0**。

### 3.2 ⚠️ 但该面**不可独立引用**：采样窗 = 0

- 🔴 **四值全 0 ⇒「零样本」，不是「零发生」** —— 全 0 意味着 **自本进程启动以来没有任何一次绑定判定被计数**（若真的跑过判定，L1/L3 不可能是 0）。
- 旁证：同一次抓取里 `binding_tau_calibrated = 0`（该值由启动时设置、与流量无关，故可读）；而计数类全 0。
- 旁证二：本轮 `query_plan` **355 行**（同一栈、同一镜像），说明**历史上确实跑过大量判定** ⇒ 计数器为 0 **只能是重启归零 + 重启后零流量**。
- ⇒ **本窗 R31m §38.4 立的「必须同报采样窗」正是为此**：该面现读 **窗 = 0**，**不得**用它作条件① 的第二独立证据。

### 3.3 🔴 一条**双向确认**的零触达（本窗最终形态）

| 方向 | 现读 |
|---|---|
| **口径面**：`app.query_plan` 的 `ambiguous` | **0 / 355** |
| **面**：`/api/v1/metrics` 的 `binding_state_total{state="ambiguous"}` | **0**（窗 = 0，独立价值有限，但方向一致） |
| **判据面**：冻结集 18 条 `expected_behavior='clarify'` 里，实际 `outcome='clarify'` | **9 条**（另 5 条判 `refuse`／3 条判 `success`／1 条 `failed`） |
| 其中 **触达 `bind`** 的 | **0 条** —— 9/9 全部止于 **`intent`** |
| 全 166 条里 **触达 `bind` 且 `binding_status='ambiguous'`** 的 | **0 条** |
| 期望 clarify 且实际 clarify 且触达 `bind` 的 | **0 条** |

⇒ **「绑定型澄清」路径（`bind` → `ambiguous` → `clarify_out`）在冻结集 166 条上从未被走到**；**9 条成功的澄清全部是 `intent` 层的时间/意图型**。
⇒ 该路径是 **FR-9.1／N-27** 与 **门禁 G-8** 的关键输入 ⇒ 本窗**只陈述事实与读数**，**不判为缺陷**（是否缺陷由 W8 取号裁定）；但 **必须防越线**：🚫 不得写「绑定型澄清已验证」。

### 3.4 🔴 与之配套的**第二条**常驻口径（本窗新立）

> **澄清的两类不可混算。** `intent`／`normalize` 层产出的是**时间/意图型**澄清（`reason='time_ambiguous'`，文案为**占位常量** —— 现读 `clarify_out.py:20` 登记「模型给的澄清提示在这一版**丢失**」：`UnderstandOutcome.clarify_hint` 存在（`engine.py:428` 已赋值），但 `state_payload()`（`engine.py:257-267`）**不把它写进 state**）；`bind` 层产出的是**字段绑定型**澄清（`reason='ambiguous_field_binding'`，经 `binding_ambiguity.prompt`，含真实候选）。
> ⇒ 统计/引用「澄清率（G-8／NFR-7.1）」时，**必须区分两类**并说明**各自样本量**；把两者合算会**掩盖绑定型样本 = 0** 这一事实。
