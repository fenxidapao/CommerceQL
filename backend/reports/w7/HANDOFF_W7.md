# W7 窗口交接文档（阶段 7 · 观测与部署）· 2026-09-21

> 用途：让一个新窗口**继承 / 成为** W7。本文只写"必须知道才知道得做事"的东西；读数细节一律给指针，不复抄（复抄会漂移）。
> 权威件是三份：本文件 + `backend/reports/w7/RELAY.md`（我写给别人的回执与订正）+ `backend/reports/w7/DELIVERY.md`（DoD 自验与 UNVERIFIED 清单）。

---

## 一、这个窗口是谁、边界在哪

**角色**：CommerceQL 阶段 7（观测与部署）责任窗口。总控（用户）按窗口派活；**不自开 U-xx 编号**；跨窗口只提需求、不动别人的文件。

**契约权威顺序（冲突时从高到低）**：`02 附录 A` > `01 PRD` > `06 UIUX` > `07 TDD` > `08 实施计划`。
设计文档在**仓库外**的项目根 `docs/01…08`（对本窗口**只读**；07 现 v1.6.4，由架构窗口维护）。

**独占可写**：`app/obs/**`（例外：`audit.py` → W1B、`logging.py` → W0）、`app/api/routers/health.py`、`deploy/loadtest/**`、`deploy/observability/**`、`deploy/runbook/**`、`backend/reports/w7/**`。
`app/main.py` **只追加**（本轮已登记一次 3 行 import 的例外，见 DELIVERY §五）。
**禁写**：`app/core/**`、`app/{llm,planner,binding,guard,exec,mask,retrieval}/**`、`app/graph/**`、`app/semantics/**`、其他 api routers、`frontend/**`、`eval/*` —— 要改只能提需求。
⚠️ `deploy/**` **名义归 W0**，分给本窗口的只有 `deploy/loadtest/`；动 `deploy/` 其他路径前先确认（例：pgbouncer 那一行 `AUTH_TYPE` 是请 W0 落的）。

**提交**：前缀 `feat(w7)` / `docs(w7)`；**只 stage 本窗口的文件**（每轮 `git status` 先核归属，跨窗口撞车要先报）。
**push：09-22 总控改规则 ⇒ 各窗口自行推自己那批，不必再等指令**（我已在转述块里对全窗口同步）。
⚠️ 但我的 commit 压在别人未推的提交之上时，一推就**连带**推上去 ⇒ 那要在 RELAY 点名"连带了哪几笔 + 依据哪句授权"
（09-22 我推 `2c18868..4e782b6` 连带了 W4 的 `c2f63cf`，依据是总控点名"将 W4 的一起 push"）。
**没有被点名的代推仍要先问**（09-21 我推 W2B 的 `9942753` 已被架构 v1.6.4 记为"下次先问"）。

**共享状态**：`commerceql-api-1` / 主栈 compose / PG / Redis 是**共用的**，不得单方面重启或重建。**唯一写者纪律**：同一时刻对同一份共享状态只能有一个窗口动手。

---

## 二、密钥与门禁纪律（binding，违反即事故）

1. `DRAIN_TOKEN` 只写本机 `deploy/.env`（已 gitignore），**不得进任何提交 / 文档 / 脚本**。
2. `MIGRATION_DATABASE_URL` **连 `deploy/.env` 也不写**，只在跑迁移的 shell 里 `export`；两者都不得进 `.env.example`。
3. DeepSeek API key 由总控提供，**绝不可出现在任何提交、文档或脚本**。
4. RS256 dev token 文件：放仓库外（本机用 `E:/tmp_w7/`），**用完即删**，永不入库。
5. Grafana 刻意不设管理员口令 ⇒ 任何"对外开放 3000"的改动**必须先设口令**。
6. **DSN 卫生门禁**：`tests/unit/test_migration_dsn_hygiene.py` **扫整个工作区**且**把"引用规则的模式串"等同于"触犯规则"** ⇒ 在任何报告里写那条 DSN 形态时必须**拆词形**（`` `postgresql+psycopg://` + `user:pass@` ``）。架构 v1.6.3 已裁：驳回"缩小扫描范围"，正确修法就是拆词形。09-21 W2B 和我各中过一次。

---

## 三、现在站在哪里（一句话 + 一张链）

**G-6（P95 ≤ 8s）从未有过分母：`outcome=ok` 至今 0 次。** 阻塞点今天换了四次形，每格都**不是负载问题**：

| 序 | 格 | 状态 | 出处 |
|---|---|---|---|
| 1 | `normalize` 超时 → `error(INTERNAL)` | ✅ 已修（U-107 落地：LLM 节点走客户端超时） | `app/graph/build.py` + README §三.0.1c |
| 2 | `app.embed_doc` 向量/tsv 全 NULL | ✅ 已灌（197/197/197）+ U-112 已修 | README §三.0.1d/e |
| 3 | PLAN 自拒（指标目录从未进 plan prompt） | ✅ W2A 已修并活体验证（`plan_summary` 由 `null` → 含 `"metrics":["gmv"]`） | README §三.0.1h |
| 4 | `bind` 0.2s 掐掉一次真 LLM 调用 | ✅ 架构裁 (B)、W4 落 `8202204`；实测 `l4_score` 三条 1,605–1,700ms 全部完成 | README §三.0.1h/i |
| 5 | **GATE1 把每条真 SQL 都拒（`GATE_AST_REJECTED` = U-121）** | ✅✅ **四处取用点已全换**（W0 形状 / W2A 实现 / W4 `357618f` gate1 / W2C `c76f701` gate2 三处同批）。09-22 我亲跑两份证据复现：**W2C 器件**（真 runtime 经 `guard_allowlist`）⇒ 干净 SQL `pass=True`、deny 三形态全 `G2-DENY`；**我复跑的 redteam 全链** ⇒ `leaked=0`、`PASS187/FAIL26/NOT_CHECKED25` 与 `failures` 集合同落地前逐格相同（零漂移；⚠️ 报告有个键被 W6 `899fffb` 改名：`gate2_visible_raise`→`gate2_on_port_raise`，引旧件别按新键找）。⚠️ **09-23 判据翻转**：架构 v1.7.1 撤销判据⑤、换**判据⑥**（deny 列裸写与带限定符都须 `R07`，仍禁 gate1 读 `all_columns`）⇒ 我探针那两条读数（档3a `R06/R06`、档3b `R07/R06`）**仍有效但解释翻转**：`R06/R06` 从"正确形态"变**待修面**（归 W2C 收回 `test_r07_deny_columns` 的 `{R06,R07}` 放宽）。见 `RELAY §三十二④` | `RELAY.md` §三十一①② · §三十二④ + `README §四.5` |
| 6/7 | **GATE3（真 EXPLAIN）与 EXECUTE（真 DB + 身份 GUC）** | ✅ **两格 09-23 都亮了**：`gate_passed`=3、`executing`=3、`query_outcome_total{success}`=3。09-22 那次 `executing`=1 而 `gate_passed`=0 **不是坏了** —— 当时 gate3 因 `EXPLAIN 不可用` 只能判 `warn`、按 §14.2 D6 不得算通过 ⇒ `events.py:55` 就不发该帧（**活体上最早的可穿透信号是 `executing`**）。U-124 落地后 EXPLAIN 真出计划 ⇒ 两格同时亮起（**同一因的两面，不是两件事**） | `README §三.0.1j/§三.0.1k` + `RELAY §三十二①` |
| 8 | `app.embed_doc` = `197\|0\|0`（U-114 第三次实锤） | ✅ **09-23 15:57 / 16:04 两次复测均 `197\|197\|197`**（W2B `d4ca203` 重灌 + 两道防线 W2A `5e47558`、W0 `36c782a`）。⚠️ 共享栈被外部重启过**两次**（09-22 19:18、09-23 15:55，`RestartCount=0` ⇒ 是 `restart` 非崩溃、**均非我所为**）。⚠️ **计数器归因口径已改**：干净重启**保留** `pg_stat` 统计（`stats_reset=NULL`，09-23 实测同一秒计数器不变）⇒ 只能用**两次带时刻读数的差分**：15:17→19:43 = **21 次全表重载**、19:43→09-23 15:57 = **0 次**。我上一版"重启清零 ⇒ 25 分钟内 52 次"是**错的**，已在 `RELAY §三十二②` 撤回 | `RELAY.md` §三十一① §三十二②③ + `DELIVERY.md` §四 |
| 9 | ~~🔴 当前真阻塞：`analytics` 连接的 `search_path` 里没有 `app`~~ ✅ **已解（U-124，W2A `d8eca02`）** | 修法 = 我建议的默认方案：照同文件 `lg` 先例给 analytics 池 `options="-c search_path=APP_SCHEMA"`（`analytics_connect_args()` 唯一构造点）。**我独立复测**：六臂件 **A 臂由红转绿**（生产池原样 `count=200000`、`EXPLAIN` 出计划）。⇒ ★ **连带效果**：gate3 从"EXPLAIN 不可用 ⇒ warn"变成真出计划 ⇒ `gate_passed` 第一次非 0 | `README §三.0.1k` + `scratch_searchpath_ab.out` |
| 10 | ★ **判据④ 已达成**（09-23 · `ok=3`、`codes={}`）⇒ 下一道门槛换了性质 | `stage_duration_seconds_count` 六档 `intent 6 / schema_linking 3 / plan_ready 3 / sql_ready 3 / **gate_passed 3** / **executing 3**`、`query_outcome_total{success}=3` ⇒ **链路第一次整条走通**。但 **`admitted=5 < MIN_ADMITTED_FOR_P95=20`** ⇒ `g6_p95_le_8s` 仍 `null`、**G-6 仍不得宣称**。⇒ 剩余门槛从"走不到执行"换成**"跑批的额度与对 §16.5 的偏离"**（默认方案与报价见 `RELAY §三十二⑤`，等总控点头） | `deploy/loadtest/preflight_r7.json` + `README §三.0.1k` |

⇒ **结论口径（写进任何汇报都要带）**：链路**已经走得到执行**（`ok=3` 实测），但**样本不足以判达标** ⇒
**G-6 仍 UNVERIFIED、不得宣称达标**；近期演示可用真结果，但**不得引 9,756ms 那格当 P95 结论**（`admitted=5`）。

---

## 四、待办与优先级（新窗口的第一屏）

### P0（阻塞 G-6，不由本窗口做，但由本窗口盯）
| # | 事项 | 归属 | W7 的动作 |
|---|---|---|---|
| ★ **P0-1：四场景跑批（唯一还挡着 G-6 的事）** | **等总控点头**（额度 + 对 §16.5 的偏离），不是等技术 | 报价与默认方案已给死在 `RELAY §三十二⑤`：新锚点 **一条 `ok` ≈ ¥0.0087** ⇒ `steady c=50/n=120` ¥1.0–1.6、`burst c=100/n=100` ¥0.8–1.3、`session-lock c=8/n=24` **≈¥0.05（多数 409，不打模型）**、`tenant-quota c=30/n=60` ¥0.3–0.5 ⇒ **合计 ≈¥2–3.5 + 15–25min**。**默认 = 先只跑 `session-lock`**（零额度、能独立判锁），三格等批。⚠️ 两条必须写进报告：① `n` 被上限截断 ≠ §16.5"持续 10min"（偏离待架构接受）；② 本机 Ollama 单条 embedding 4.5–5.0s ⇒ P95 含**压测环境瓶颈**，不是产品容量 |
| ★ **P0-2：U-125（rule_id 归因，架构 v1.7.1 已开）** | **W4 ①（`nodes/_shared.py::gate_update`）+ W7 ②③ 必须同批同推** | 我的两处：**②** 摘掉 `obs/instrumentation.py:448-455` 的反推路径（否则双计）、**③** 放宽 `obs/metrics.py:676` 的 `rule_id` 取值域（W4 补的第四处，成立且我认领：现在只有 gate1 字母表，`G2-*`/gate3 号会被"丢弃+计溢出"）。**排法**：我下一次开工写 ②③ → **只贴 diff 不单独提交** → 与 W4 同一批 push。判据 = 拒一条后 `/metrics` 的 `rule_id` 标签非空 |
| ✅ **已闭环（09-23）：`search_path` 死锁 = U-124** | W2A `d8eca02`（P0，架构定标：W1B 名下、W0 落常量、W2A 同批改引） | **我独立验收**：六臂件 A 臂转绿（`200000` + EXPLAIN 出计划）⇒ 判据④ 达成（`ok=3`）。四条禁止动作自查 W2A 已做（未改 R16 / 无连接内 SET / 未扩 metadata 池 / materialize 同因族不并入 ⇒ **那族仍开着**，别当已解） |
| U-121 | 闸门 allowlist 形状 | ✅ 四处取用点已全换 ⇒ **不再是 P0**。⚠️ 但**判据换成⑥**（见 §三 第 5 行）⇒ 等 W2C 收回放宽后我再复跑一次活体 |
| ✅ 已闭环 | `app.embed_doc`（U-114） | 09-23 跑前跑后仍 `197\|197\|197`；**每次预检前后各测一次**照做（差分口径，见 §三 第 8 行） |
| U-119 | 生产端口直连闸门的契约测试 | ✅ 09-22 复跑 = 2 passed。⚠️ 旧纪律句"全量恒有 1 条刻意红"**只对 `8a4121a..357618f` 成立**，引用必带区间 |

### P1（本窗口的活）
1. ✅ **U-120 已落（09-22 第十轮）**：`g6_p95_le_8s` 改**三态**（`p95` 无值 / 无 `admission` / `admitted<20` ⇒ `null`），
   判定点收在 `driver._g6_boolean()`；`--self-check` 加 7 情形 + **`_summarize` 调用点双向**；
   变异检查入库 `backend/reports/w7/scratch_g6_mutation_check.py` ⇒ **6/6 被抓**。⚠️ **教训**：第一版 M1 逃跑，
   因为用例只测助手函数、而变异打在调用点上（"断言打错对象"）。W6 的两条守卫复跑 PASSED（三态没打断读端）。
2. ✅ **A-1（架构 v1.6.6，不占 U 号）代码已落**：`--roll-up` 同时重算两个派生量 + `g6_derived_audit` before/after，
   并修掉就地补算漏传 `admission` 的缺陷（有对照）。**待办 = 那 11 份归档件要不要就地降档，等总控点头**
   （演示读数已在副本上跑过；`receipt.json` 是 W6 的 G-6 默认输入）。
3. ✅ **RL-2 降级率已改挂 `degraded_total`**（四处同步：`RL-2` §22/§132、`runbook/README.md`、`alert.rules.yml` 注释、看板 `description`）；
   两个假分母逐处点名禁用。**接线需求仍在 W2B**（一行 `observe_retrieval_mode()`）⇒ 接线前它不得当证据引用。
4. ✅ **U-122 归我那半已写**（`README §四.4`：`truncated` 是客户端流截断 ≠ §8.6 行数截断；L 无出口 ⇒ 压测判不了服务端截断）。
   ⚠️ **仍欠**：判据④ 落地后回一条可复制的读法 —— **UNVERIFIED**，别引成"已有"。
5. **新窗口第一屏（09-23 判据④ 达成之后）**：① 问总控 P0-1 的额度与 §16.5 偏离（不点头就只跑 `session-lock`，零额度）→
   ② 落 U-125 的 ②③（`instrumentation` 摘反推 + `metrics` 放宽取值域），**写完贴 diff 给 W4、与他 ① 同批 push，不单独推** →
   ③ 判据⑥ 落地（W2C 收回 `test_r07_deny_columns` 放宽）后：**重建镜像 + 复跑我的探针与 redteam**，看 `RT-R07-001…004` 是否自行转绿 →
   ④ 每次动手前后：前置三查（`embed_doc` `197|197|197`、`git status` 只别人的文件、`git fetch` 核追踪 ref）+ **跑批先报规模与花费**；
   ⑤ 归档件 A-1 就地降档仍**等总控点头**（默认不改写、只列清单）。
6. **可观测缺口两条（都是需求，不是本窗口的代码）**：① 闸门拒绝的 `rule_id` **今天到不了任何归因面**
   （error 帧无该字段、`gate_reject_total{rule_id=""}` 实测恒空）⇒ **已由架构 v1.7.1 定号 U-125、W4 拆成三处两窗**（见 P0-2）；
   另：W4 #6 提醒成立 —— `exec/errors.py:136-140` 把五类压成 `SQL_SYNTAX_ERROR` ⇒ 帧上永远看不出 `unknown_table`，
   区分只能靠 `exec_failure_total{error_class}` ⇒ **`README §四.5` 待加这一行**（已登记）。② 共享 `commerceql-api-1` 的 `/healthz` 把 `llm`/`embedding`
   报成"阶段 0 探针未接线"，而**我新建的镜像里同一项是 `true`** ⇒ 那是 5 天前的旧镜像，不是探针缺陷（别照它判 RL-2）。

### P2（DoD 收尾，未跑就标 UNVERIFIED）
- RL-1/RL-3 的 `DB_UNAVAILABLE` 活体行为；Grafana 面板渲染 + nginx `/metrics` 404（本机无镜像）；`exec_failure_total` 读数。
- 六条 runbook 全部可执行性已在 DELIVERY 记账，复跑成本高，收口时引用即可。

### 明确不做
- 不换题集绕开阻塞（架构已否决"换题集/补语义层"）；不"修"U-119 那条红；不碰 `backend/reports/w2-int/e2e_stage2_check.py`（别人的脏文件，架构已要求认领，每轮 `git status` 会看见，**不 stage 不还原不删除**）。

---

## 五、怎么跑起来（一次预检的全套命令，逐字用过）

```bash
# 0) 前置三查（缺一不可，09-21 我各失手过一次）
docker ps --format '{{.Names}}'                      # 期望 commerceql-pg-1 / -redis-1 / -pgbouncer-1 在
docker exec commerceql-pg-1 psql -U postgres -d ecom -tAc "select count(*),count(embedding),count(tsv) from app.embed_doc;"   # 必须 197|197|197
git status --porcelain | grep -v '^??'               # 必须只看见别人的文件
```

```bash
# 1) 从 commit 建被测镜像（⚠️ 构建上下文**必须是仓库根 `.`**，不是 backend：
#    Dockerfile 里 `COPY backend/app` 与 `COPY deploy/entrypoint.sh` 都相对仓库根写。
#    09-22 我按本文件旧版写"上下文 = backend"跑过一次 ⇒ `ERROR "/deploy/entrypoint.sh": not found`。
#    别再改回去。）
cd CommerceQL && docker build -f deploy/Dockerfile -t w7load-api:MMDDrN .
```

```bash
# 2) 起被测容器：两条只读挂载一条都不能少（缺了会 503/500，报错还指向别处）+ 外部网络 + Windows 形态绝对路径
docker run -d --name w7load-api --network commerceql_default --env-file deploy/.env -p 18000:8000 \
  -e EMBEDDING_BASE_URL=http://host.docker.internal:11434 \
  -v "E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL/semantic:/semantic:ro" \
  -v "E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL/deploy/secrets/jwt_public.pem:/run/secrets/jwt_public.pem:ro" \
  w7load-api:MMDDrN
# 放行：/api/v1/healthz 的 status=ok 且 7 项 checks 全 true、degraded_dependencies 为空
# ⚠️ 路径带 /api/v1 前缀 —— 打 /healthz 会 404（我白试一轮）
```

```bash
# 3) 铸 dev token（租户必须是 T_A/T_B/T_C —— 写成 tenant_a 会让 RLS 滤光、P95 假性很好）
cd CommerceQL/backend && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe \
  scripts/mint_dev_token.py --tenant-id T_A --user-id u_load --role analyst > E:/tmp_w7/tok.txt
# 用完删：rm -f E:/tmp_w7/tok.txt   （永不入库）
```

```bash
# 4) c=1 预检（判据④ = 至少 1 条 outcome=ok；不满足 ⇒ 不跑批）
cd CommerceQL/deploy/loadtest && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../../.venv/Scripts/python.exe \
  driver.py --target http://127.0.0.1:18000/api/v1 --scenario steady --no-async --concurrency 1 \
  --max-requests 5 --questions-file questions_T_A_time.txt --tokens E:/tmp_w7/tok.txt \
  --out E:/tmp_w7/preflight_rN.json
```

```bash
# 5) 取证三件套（全部零额外配额，别用模型调用去猜）
docker logs w7load-api --since 10m > E:/tmp_w7/all.log    # 数 httpx 200 vs "event": "llm_call" vs task 分布
curl -sS http://127.0.0.1:18000/api/v1/metrics            # stage_duration_seconds_count 六档 + degraded/binding 族
docker exec commerceql-pg-1 psql -U postgres -d ecom -c "select task_id,count(*),sum(cost_cny) from app.cost_ledger where created_at>now()-interval '20 min' group by 1;"
```

**四场景跑批（判据④ 过了才准做，且先报告规模与花费再跑）**：命令在 `deploy/loadtest/README.md` §七，最后一步必须 `--roll-up` 合成 W6 唯一认的 `receipt.json`。

---

## 六、本机的坑（每一条都真烧过时间）

- 编码：任何 Python/psql/mypy 前缀 `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`（GBK 会崩，且失败形态长得像被测代码的 bug）。
- `lint-imports` 必须用 `.venv/Scripts/lint-imports.exe` 且在 `backend/` 下跑，否则**假绿**或读到 1 退出码。
- Git Bash 改容器内路径 ⇒ `docker exec` 里读文件加 `MSYS_NO_PATHCONV=1`；`docker run -v "$PWD/…"` 会被静默改成 MSYS 路径 ⇒ 用 `E:/…` 绝对形态。
- **`/tmp` 不是同一个**：Git Bash 写的 `/tmp/x` Windows Python 打不开 ⇒ scratch 一律 `E:/tmp_w7/`。
- **退出码会被吞**：`cmd | tail`、`cmd > f; echo "exit=$?"`（$? 是 echo 的）都不作数 ⇒ 重定向到文件后再 `echo $?`，或读 `${PIPESTATUS[0]}`。
- `*.log` 被 `.gitignore:47` 全局忽略 ⇒ 证据要落 `.json`/`.txt` 才能入库（W2A 本轮也踩，改存 `_gates_*.txt`）。
- **绝禁**：对共享 `ecom` 跑迁移套件或 `tests/integration`（后者会**静默清空 `embed_doc` 向量** = U-114）。每次预检前重核 `197|197|197`。
  ⚠️ **09-22 加一条**：这条要**跑前 + 跑后各测一次**（W6 教的方法：不测后一次，就无法把自己排除在因果链外）。
  当天实测共享前置被人反复清 —— `embed_doc` 的 `ins/del` 四小时内从 `1970/1970` 涨到 `6107/6107`（**21 次全表重载**），
  `cost_ledger` 留下 `ins=24/del=0/count=0` 的 **TRUNCATE 签名** ⇒ 别人跑一次集成套件就能毁掉所有人的复现前置（U-114/U-113/U-123 同一个门）。
- **同一工作副本被多窗口共用 ⇒ `git` 索引是共享的**（09-22 实锤：W4 三处改动在它 `add` 后、`commit` 前的两分钟里，被 W2B 的 `0f3f125` 一并卷走并推送）。
  自防三条（照 W4 的 §十七）：**`git add` 与 `git commit` 写同一条命令、零间隔**；提交前一刻查索引（`git diff --cached --name-only`）；**提交后立刻 `git show --stat` 复核**。
- 报价口径：成本由 **DeepSeek prompt cache 冷/暖**决定，不由条数决定 ⇒ 按"首条 +（n−1)×稳态"报，别把首条摊进平均。
  **09-22 第九轮实测锚点**：`c=1 / n=5`（`questions_T_A_time.txt`）= **9 次调用 / ¥0.014471**（暖缓存、含一次 `repair` ¥0.006592）。
  ⚠️ 先前那句"≈13 次 / ¥0.021–0.042"是**多条 SQL 一起死在 gate1 的第八轮**形态（那时 3 条各跑 4 次调用）；
  链路走通到执行面之后**调用数会变小、单条变贵**（`repair` 一次顶三次 `normalize_intent`）⇒ 报备要按"当前卡在哪一格"换锚点。
- `docker exec` 进被测容器跑临时脚本：两处**必须同时**带上，否则一个是"路径不存在"、一个是 `ModuleNotFoundError: app`：
  `MSYS_NO_PATHCONV=1 docker exec -e PYTHONPATH=/srv -w /srv w7load-api python /tmp/ab.py`
  （`-w /srv` 不加 `MSYS_NO_PATHCONV` 会被 Git Bash 改写成宿主路径 ⇒ `OCI runtime exec failed: Cwd must be an absolute path`；
  脚本放 `/tmp` 时 `sys.path[0]=/tmp`，`app` 在 `/srv/app` ⇒ 非显式 `PYTHONPATH=/srv` 不可）。
- **A/B 对照脚本别让两条语句共用一条连接/一次事务**：第一条失败后 PG 对同一事务里的第二条只回
  `current transaction is aborted, commands ignored until end of transaction block` ⇒ 那是**量具假读数**，
  长得却极像"被测系统的第二个缺陷"（我第一版的 E 臂就是这样，改成一语句一连接后才读出真形态）。
- **`pg_stat_user_tables` 的 `n_tup_*` 是累计量，不是速率**（09-23 我自己判错过一次）：干净 `docker restart` **不会**清零统计（PG 落盘/回载），且 `stats_reset=NULL` 只表示"没人显式 reset 过"、**不给起点日期**。
  ⇒ 唯一可用形态 = **两次带时刻读数的差分**（我 09-22 那句"重启清零 ⇒ 25 分钟 52 次重灌"就是这么错的，撤回见 `RELAY §三十二②`）。
  复测命令（只读）：`select (select stats_reset from pg_stat_database where datname='ecom'), n_tup_ins, n_tup_del, now(), pg_postmaster_start_time() from pg_stat_user_tables s join pg_class c on c.oid=s.relid where c.relname='embed_doc' and c.relnamespace='app'::regnamespace`
- **报价锚点要按"链路走到哪一格"取**（09-23 实测校准）：一条走完全链的 `ok` ≈ **4 次调用 / ¥0.0087**（14 次 / ¥0.030397 ÷ 3 条 ok），
  而"死在 `gen_sql` 之后"的那轮只有 9 次 / ¥0.0145 ⇒ **成功比失败贵 3–5 倍**。⇒ 拿失败路径的单价外推跑批预算 = **系统性低估**（我今天就这么超了自己报备上限一次）。
- 冷容器第一条会吃掉整个 p95（本轮实测 187,728.9ms，**未做单变量对照 ⇒ 不写成成因**，只登记）。

---

## 七、证据指针（别再从头找）

| 主题 | 位置 |
|---|---|
| 放行判据（四条，含"判据④ 必须有 ok"） | `deploy/loadtest/README.md` §三.0.1 |
| 被测容器正确启动形态（两条挂载 + healthz 全清单） | 同上 §三.0.1b |
| 第一~八轮预检读数（逐轮，含被撤回的说法） | 同上 §三.0.1c–i |
| 探针门限常量的取数口径（U-108） | 同上 §三.0.2 |
| `g6_caveat` 是降档开关 / P95 只算准入样本 / c=1 先行 | 同上 §四.1 / §四.2 / §九 |
| 回执原件 | `deploy/loadtest/preflight_r4.json`、`preflight_r5.json`、`receipt_*.json` |
| U-110（并行 worker 少算）关闭证据与只读读法 | `deploy/loadtest/rls_parallel_evidence.sql` + RELAY §十九 |
| 我给别人的回执与**我自己的订正/撤回** | `backend/reports/w7/RELAY.md` §十九 ~ §二十七 |
| DoD 自验、UNVERIFIED 清单、越界声明 | `backend/reports/w7/DELIVERY.md` §三 ~ §六 |
| 看板/告警/停机/断言的落地状态 | 同上 §二、§三 + `deploy/runbook/README.md` |

**读别人结论的纪律**：本项目几乎每个读数都是某次 run 的快照 ⇒ **引用前先复测**（09-21 我自己有两次："三族零调用点"已被 W4 接线推翻；架构 v1.6.2 那句"`bind` 本次未被走到"被我的活体推翻）。**撤回报错要留痕，不改历史文本，在最新一节登记作废。**

---

## 八、跨窗口当前关系图（09-21 收尾时）

- **我在等**：U-121（W0→W2A→W2C）→ 之后重建镜像复跑预检 → 才有第六/七格（GATE3/EXECUTE）的读数；τ 校准（W3C/W4 侧）在**更后面**，不是当前卡点。
- **等我的**：U-117 已用我的读数结案；W4 的 U-119 需要我在 U-121 落地后回报"预检是否走通"；架构需要我确认 U-120 的修法口径；W6 需要我 U-120 改完后的三态布尔打招呼。
- **别混淆**：G-6（压测）**≠** 评测（eval/gates），两条数据分开归档（DELIVERY §一已登记）。
- 编号：下一可用 = **U-122**。取号前三查：07 §4.8 表 + `git grep -n "U-<next>"` + `git log --all --grep="U-<next>"`（09-21 的撞车就是缺后两条）。

---

## 附、开新窗口的提示词（正文，可直接复制粘贴）

```
你是 CommerceQL 项目（仓库 E:\01_实训\项目\基于Text2SQL的电商数据分析Agent\CommerceQL\）的 W7 窗口，负责阶段 7「观测与部署」，接替上一个 W7 窗口继续工作。

第一步（必做，不许跳过）：完整读完 backend/reports/w7/HANDOFF_W7.md —— 它是本窗口的角色、所有权边界、密钥纪律、当前卡点、待办优先级、跑起来的命令、本机的坑、证据指针。你的所有工作以它为唯一交接件，不要凭猜测开工。

三条立刻生效的纪律：
1) 先理清现状、再列执行计划、再动手；需求不明确先问总控，不要猜。压测四场景必须先报告规模与花费再跑批。
2) 只写你自己的地盘（HANDOFF §一列了可写/禁写清单）；跨窗口只提需求、不改别人的文件；不得自行开 U-xx 编号（下一可用 = U-122，取号前三查：07 §4.8 表 + git grep 代码 + git log --all --grep）。只 stage 本窗口文件；push 已获长期授权，但代推别人的 commit 要先问。
3) 只报实测：未跑的写 UNVERIFIED；因果句必须有对照实验；撤回报错要在最新一节留痕、不改历史文本；引用别人的读数前先复测（读数都是快照）。

当前状态一句话：G-6（P95 ≤ 8s）至今 0 条 outcome=ok ⇒ 没有分母、跑批不准跑。阻塞现在在 U-121（闸门 allowlist 形状，归 W0+W2A+W2C，你不改代码），你手上的活是 HANDOFF §四 的 P1 第 1 条 U-120（driver 的 MIN_ADMITTED_FOR_P95 未真正生效），以及每次开工前照 §五 做"前置三查"。

密钥纪律按 HANDOFF §二 逐字执行（DRAIN_TOKEN 只进本机 deploy/.env；MIGRATION_DATABASE_URL 连 .env 也不写；DeepSeek key 绝不出现在任何提交/文档/脚本；报告里引用 DSN 模式串必须拆词形）。

每轮收尾三件事：把实测/未实测写进 backend/reports/w7/RELAY.md（新增一节，不复抄旧文）与 DELIVERY.md 的对应行、只提交本窗口文件并推 main、最后给总控一段可直接转发给其他窗口的粘贴块。
```

