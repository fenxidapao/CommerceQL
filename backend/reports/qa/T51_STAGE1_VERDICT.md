# T-51 段 1 回执 · QA 验收件（第 31 轮 R31k）

> 落笔现读：**2026-10-13 10:47 ＋0800** ｜ 起点 HEAD **`4bca20c`／510 笔**（W8 回执提交）｜ 本窗 **零出站**（未调用任何模型）
> 被验对象：W8 回执（`backend/reports/w8/RELAY.md §廿五`，提交 `4bca20c`）＋ 4 件产物（`t51_collect.py`／`t51_scope.json`／`t51_stage1_city_only.json`／`t51_stage1_city_only_smoke.json`）
> 裁定范围：**只裁「执行与证据是否一致」**。不裁判据措辞、不发号、不改单（段 2 形态重裁属 W8／总控职权）。
> 下游落账：`RELAY §36`／`TASK_BOARD §41`／`QA_LEDGER R31k`／`COMPLETENESS §十`

---

## 一、六条回执逐条复算（全部现读，命令见 §六）

| # | W8 回执 | 本窗复算读数 | 判 |
|---|---|---|---|
| ① | A1 ＝ 4 条 × n3 ＝ 12 次；真候选对只有 `C-CITY-01..04` | `t51_scope.json`：`n_clarify=18`，`by_kind` = 绑定竞争 **4** ＋ 时间窗未定 6 ＋ 指标口径未定 3 ＋ 其它 3 ＋ 开放式 1 ＋ 值域未定义 1（合计 **14**）；4＋14 ＝ 18 ✅。`t51_stage1_city_only.json`：`n_samples=4`／`repeats=3`／每样本 `candidate_ids` len 2／`gold_candidate_id=None`／`failures=[]` | ✅ **一致** |
| ② | 台账增量 0；实付 ¥0.022931／15 次 | 台账现读 `1830\|3.025849\|2026-10-07 04:28:00.872275+00` **逐位不动** ✅；主跑 `spend_cny=0.017626` ＋ smoke `0.005305` ＝ **0.022931** ✅；调用数 4×3 ＋ 1×3 ＝ **15** ✅ | ✅ **一致**（归因须补精度，见 §三-1） |
| ③ | B1 ＝ `unstable`，`max_gap_std 0.2021`，`min_kendall 1.0` | 现读 `stability.verdict=unstable`；`max_gap_std=0.20207259421636903`；`min_kendall=1.0`；4 条样本 `kendalls` **全为 `[1.0,1.0,1.0]`**；阈值 `TAU_SWEEP_STEP = 0.05`（`calibration.py:58`），判据 `max_gap_std >= 0.05 ⇒ UNSTABLE`（`:288`） | ✅ **一致** |
| ④ | C1 拐点 τ=0.05；τ=0 安全侧错误 4/4、澄清率 0；τ≥0.05 澄清率 1.0 | `curve` 21 点 ✅（步长 0.05）。τ=0：`decided=4`／`should_clarify_but_did_not=1.0`（＝4/4）／`clarify_rate=0.0`；τ=0.05…1.00：`decided=0`／安全侧 0.0／`clarify_rate=1.0` | ✅ **一致**（曲线信息量须补注，见 §三-2） |
| ⑤ | 层分布 ＝ 缺（L4-only 路径拿不到） | 主跑 json 顶层 keys ＝ `scope／samples／failures／spend_cny／stability／curve`；**全文无 `binding_layer` 字段** ✅ | ✅ **一致** |
| ⑥ | 未碰冻结集／`app`／`tests`／`deploy`／容器；零取号 | `git show --stat 4bca20c` ＝ **仅 5 件**，全在 `backend/reports/w8/` ✅；`git log --oneline -3 -- eval/` 显示最近触碰 `eval/` 的提交为 `772eba9`（**非本轮**）✅；容器六件仍 `Up`（33 min，未 recreate）✅；残渣库 `ecom`／`ecom_u123_probe` 未变 ✅ | ✅ **一致** |
| 附 | 离线自证 `test_binding_calibration.py` ＝ 51 passed | **本窗独立复跑**：`51 passed in 0.20s` ✅ | ✅ **一致** |

⇒ **回执六条 ＋ 自证一条，逐条成立，未发现任何夸大或漏报。**

### 1.1 W8 两条「上呈发现」的独立复核

| 发现 | W8 依据 | 本窗复核 |
|---|---|---|
| **① A1 原样不可诚实构造** | 18 条中 14 条歧义不在「两个字段绑定竞争」上 | ✅ **成立且可逐字回溯**：W8 `t51_scope.json` 的 `why` 与冻结集 `clarify_expected.reason` **逐字相同**（抽验 `C-CITY-01`／`C-GMV-02`／`C-REG-02` 三处 verbatim）。另：`candidates` 字段在冻结集里 **仅 `C-CITY-01` 有 2 个**、余 17 条为空（与 `QA_LEDGER R31h` 第 3 行一致）⇒ W8 拒编候选是**正确的反伪造动作**，不是缩量 |
| **② 打分器噪声打在「差多少」上** | 4 条 `kendalls` 全 `[1.0,1.0,1.0]`，分差抖动 4.5 倍（0.10→0.45） | ✅ **成立**：`kendalls` 现读全同 ✅；4.5× 系 **`C-CITY-01` 样本内** 0.10→0.45 ✅（补：**全样本**量程 0.05→0.45 ＝ **9.0×**，比回执那句更强，非矛盾） |

---

## 二、独立清点：段 2 blocker ② 用「更强的尺」复核（**这是本件的关键增量**）

W8 的「只有 city 族有真实绑定竞争对」是**从 18 条题的 `reason` 反推**的 —— 那把尺**只看得见「冻结集已标注的歧义」**，看不见「语义包里还有多少可造竞争对」。按本窗纪律「**判缺数之前，先证明你的尺能看见它**」，本窗改用**语义包全量枚举**复核：

现读 `semantic/bundle_2026.09.14.1.yaml` 的 `field_bindings`（list，**7 条**）：

| concept | grain_level | ambiguous | canonical_asset | alternatives | candidates |
|---|---|---|---|---|---|
| `customer_name` | 1 | — | `shop.shop_name` | 1（带 `use_when`） | **0** |
| **城市** | **4** | **True** | — | 0 | **2**（`order_paid.receiver_city` ＋ `shop.city`，**同 grain 4**） |
| `商品名称` | 3 | — | `product.sku_name` | 1 | **0** |
| `渠道` | 1 | — | `traffic_daily.channel` | 0 | **0** |
| `类目` | 1 | — | `order_paid.category_l1` | 0 | **0** |
| `大区` | 2 | — | `region.region_name` | 0 | **0** |
| `支付时间` | 5 | — | `order_paid.pay_time` | 1 | **0** |

⇒ **全语义包中，候选数 ≥2 的 concept 恰好 1 个（「城市」），且是唯一 `ambiguous=True` 的条目。** 其余 6 条的 `alternatives` 是**带 `use_when` 条件的确定性替代**（主数据现值 vs 交易快照），**不构成需要澄清的竞争**。

⇒ **裁定**：W8 的 blocker ② **成立**，且本窗用独立尺给出**更强**的表述 —— **L4 的候选空间（需要「歧义竞争」才能进 `ScoreSample`）在全包里只有 1 个 concept、2 条 asset** ⇒ τ 校准的样本空间上界由**该 concept 的变体数**决定，与 3 轴配额**无交集**。⇒ 「3 轴配额 6:7:2 结构上凑不齐」不是工作量问题，是**形态冲突**。

> 🔻 **本窗对 R31j 自身结论的收窄（自曝第 2 则）**：`TASK_BOARD §40.2` 曾写「留出集下界 **15** 由现读钉死」。该句现读需**收窄**：15 是**「轴覆盖」下界**（`clarify ∩ fuzzy:*` 一一对应），**不是「L4 可测」下界**；后者的现读上界 ＝ **1 族（城市）**。两句不可混用。（原文不改，以本条为准。）

---

## 三、QA 追加裁读三条（W8 未明说，须补进对外口径）

| # | 事项 | 现读 | 后果 |
|---|---|---|---|
| 1 | **「台账未落库」的归因须写全** | W8 写「`build_gateway` 未传 `ledger` ⇒ 走 `InMemoryCostLedgerSink`」。**生产装配并非如此**：`backend/app/api/deps.py:723-728` 明确 `ledger=DbCostLedgerSink(settings.DATABASE_URL)` ⇒ **生产路径落库**。真因是 **`t51_collect.py:76` 这个调用点没传 `ledger=`**（`__init__.py:591` 形参默认 `None`、`:617` 兜底 in-memory） | 若只写「工厂默认 in-memory」，读者会误推「**生产台账有洞**」。**须分写**：工厂默认值 ≠ 生产装配 |
| 2 | **τ—响应曲线在本子集只有「一格」信息** | 21 点中 **20 点 `decided=0`**（τ≥0.05 全判澄清）＋ `binding_accuracy` 自 τ=0.05 起恒 `None`（子集为空；W8 已在 `§25.3` 自陈原因） | 「拐点 τ=0.05」**只能读作「唯一非平凡台阶」**，不得读作「τ=0.05 是最优点／已校准」。且 τ=0.05 **恰等于扫描步长下界** ⇒ 它是「第一个正 τ」，**不是被数据选出来的点** |
| 3 | **同名字段跨件类型不一致** | 主跑 `spend_cny = 0.017626`（**number**）；smoke `spend_cny = "0.005305"`（**string**） | 回执相加得 ¥0.022931 **算术正确**；但下游按 float 解析 smoke 时会**静默出错**（字符串相加＝拼串）。属**形状瑕疵**，不翻转读数，登记待修 |

---

## 四、🔴 本窗自曝两则

| # | 自曝 | 现读 |
|---|---|---|
| **1** | **本窗「零出站」这把尺有盲区** | 本窗 R31j 的零出站复核 = 「台账逐位不动」。**W8 本轮即反例**：花了 ¥0.022931（15 次真打），台账**一动没动**。⇒ 该尺**只能证「没有走落库路径的花费」，不能证「无人花钱」**。🔴 **新增常驻口径**：「零出站」判定须**双条件** —— ① 台账逐位不动 **且** ② 本轮无任何**未传 `ledger` 的** `build_gateway(...)` 调用点被执行。缺 ② 时一律写「台账面无花费」，不得写「零出站」 |
| **2** | **本窗派单块笔误：硬门槛条数写错** | `TASK_BOARD:1853` 写「`is_finalizable` **五条**硬门槛」—— 现读 **八条**（`calibration.py:443-451`：① 稳定性通过 ② 选出 τ 点 ③ NFR-7.1 ④ `model_id` ⑤ `prompt_version` ⑥ `calibrated_at` ⑦ `holdout_separated` ⑧ `layer_distribution`）。旁证：W8 `§25.3` 说「即便稳定性过了 `is_finalizable` 也会卡在**第 8 条**」，与八条制逐字对齐 ⇒ 误在**本窗**。原文不改，以本条为准 |

---

## 五、段 2 裁定

| 项 | 裁 |
|---|---|
| **未跑、零花费** | ✅ 成立（上界余 **¥0.577069**） |
| **blocker ①（B1 UNSTABLE ⇒ 停手）** | ✅ **依据成立**：`TAU_SWEEP_STEP=0.05`、`max_gap_std=0.2021 ≥ 0.05`；派单原句「判 UNSTABLE ⇒ 停手交回」＋ `calibration.py:500`「`UNSTABLE` 时不给 τ 候选（禁止定稿）」⇒ 定稿扫描跑了也必 `is_finalizable=False`（第 1 条即挂） |
| **blocker ②（3 轴配额凑不齐）** | ✅ **依据成立，且本窗以语义包全量枚举给出更强证据**（§二）。根因 ＝ **「3 轴配额」⊥「L4 可测」** —— 时间口径／指标口径／值域开放性三类歧义在该空间内**无候选对** |
| **W8 建议「段 2 与『L4 τ 校准』形态一并重裁」** | ✅ **本窗照录、不加裁**（形态重裁属 W8 取号／判据职权）。但本窗补一条**依据**：样本空间上界 ＝ **1 concept ／ 1 族 ／ 4 条**，任何「15–20 条」的配额在该形态下**结构不可达** |
| 🔴 **口径（防误读）** | **段 1 跑过 ≠ T-51 有进展**：`UNSTABLE` 的语义是**打分器不可信 ⇒ 必须升级方案 A**（换打分器），**不是**「τ 差了 0.05 就到手」。门禁 G-2／G-5／G-7 **判词不变（FAIL）**；`eval_metrics.json` 的 `tau.calibrated_under_eval_env` 现读仍 `false` |

---

## 六、复算命令（零成本，全只读）

前置：venv ＝ `CommerceQL/.venv/Scripts/python.exe`；`PYTHONUTF8=1`。

```
# 1) 回执 ①⑤ 与分数向量：读 t51_stage1_city_only.json 的 scope/samples/stability/curve
# 2) 回执 ③ 阈值：calibration.py:58  TAU_SWEEP_STEP = 0.05 ；:288 判据
# 3) 回执 ② 台账：容器内 select count(*),sum(cost_cny),max(created_at) from app.cost_ledger  （begin;…rollback;）
# 4) 回执 ⑥：git show --stat 4bca20c ；git log -3 --oneline -- eval/
# 5) §二 语义包清点：读 semantic/bundle_2026.09.14.1.yaml 的 field_bindings（7 条，候选数 ≥2 者 1 条）
# 6) 自证复跑：PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q backend/tests/unit/test_binding_calibration.py
```

> 🔴 **本件不构成的结论**：① 不得说「T-51 已完成」② 不得说「τ 已校准」③ 不得把 §三-2 的「拐点 τ=0.05」引作「最优 τ」④ 不得把 §三-1 的「台账未落库」引作「生产台账有洞」。
