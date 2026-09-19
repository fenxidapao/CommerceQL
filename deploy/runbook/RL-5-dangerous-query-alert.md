# RL-5 · 危险查询告警（`ui_contract_violation` / 闸门放行 / 跨租户）

> 归属窗口：**W7** ｜ 日期：**2026-09-18**
> 依据：07 §18.7 第 5 行 · §7.1–§7.6（三道闸门）· §14.3（事件序列约束）· §14.5 · §15.3/§15.4 · §18.5（版本回滚）· §13.3/§13.7（隔离七道）· N-03 / N-04 / N-09 / N-16 · 门禁 G-4
> 共用命令与端口约定见同目录 `README.md` §五。

---

## 0. 一句话定性：这是**两个**不同的 P0，处置方向相反

§18.7 把这一条写成一行（判据"`ui_contract_violation` 或红队项异常"→「**P0**；冻结相关会话；核对闸门规则」）。落到实现上它是**两类毫无共同处置动作**的事：

| 类别 | 真实信号 | 破了什么 | 第一动作 |
|---|---|---|---|
| **A. 契约违规**（帧序列错了） | `ui_contract_violation_total{kind}` 非零 | 前端会停在"加载中"/渲染矛盾（N-08、§14.3） | **保现场、抓帧**，服务可以继续跑 |
| **B. 危险 SQL 放行 / 跨租户** | `gate_reject_total` **突降**、红队用例本应拒却通过、RLS 命中数异常 | **安全边界**（N-03 闸门不可跳过 / PRD §11.2 隔离） | **先止血（缩小暴露面）**，再定位 |

**把 B 当 A 处理（先去抓帧）或把 A 当 B 处理（先去关服务）都是错的。**

---

## 1. 触发信号（真实名字）

### A 类 · 契约违规

| 类型 | 信号 |
|---|---|
| 指标 | `ui_contract_violation_total{kind}`，`kind` **恰好 5 值**（`app/obs/metrics.py:UI_CONTRACT_VIOLATION_KINDS`）：`terminal_after_terminal`（§14.3 约束 3）/ `duplicate_terminal`（N-08：一条流恰有 1 个 `terminal:true`）/ `terminal_missing_flag`（§14.3 约束 1）/ **`non_terminal_claims_terminal`**（§14.3 约束 2：**非**终止事件声称 `terminal=true`，`degraded` 最容易犯）/ `stream_without_terminal`（流结束却没有终态帧）。⚠️ 中间两条**修法在相反的代码路径**上（漏打标志 vs 多打标志），合并成一个值会把值班人支到反方向 |
| 级别 | **非零即 P0**（§15.3 契约行 + §15.4 第 3 行）。它不是"性能有点差"，是"后端发了自相矛盾的序列，前端的互斥表前提没了" |
| 采集方 | W7 的帧观测器在**出口字节层**独立复核（不信任产出方的自检） |

### B 类 · 闸门与隔离

| 类型 | 信号 |
|---|---|
| 间接探测 | `gate_reject_total`（`gate_no` 为 1/2/3，另有 `rule_id` 标签）速率**突降甚至归零**，而 `query_outcome_total{outcome="success"}` 没跟着降 → 闸门"变松"。⚠️ **§15.4 明写生产侧靠这条间接探测**，"危险 SQL 放行"**没有直接指标**（红队集只在 CI 有断言） |
| 规则号 | `rule_id` 取值域 = `AstRule` **R01–R20**（`app/core/enums.py:684`）；实体判据在 `app/guard/rules.py`（W2C）。阻断级 14 条 / 改写级 `R04`+`R15` / **告警级 `R17`–`R20`** |
| 端点行为 | 本应出现的 `error{code="GATE_AST_REJECTED"}`（422）/ `GATE_POLICY_REJECTED`（422）/ `COST_TOO_HIGH`（422）消失 |
| 隔离 | `meta.scope.level`（`tenant_isolated`/`role_limited`/`unrestricted`，C-07）异常；`FORBIDDEN_SCOPE`(403)/`PII_BLOCKED`(403) 计数骤降而请求量不变 |
| 评测侧 | 红队集 `eval/red_team_cases_v1.json`（**W1A 资产**）；执行器与门禁判定归 **W6**；`backend/tests/redteam/test_redteam_guard.py` |
| 告警（§15.4） | 「危险 SQL 放行 >0 P0」「跨租户泄露 >0 P0」（后者实现 = 专项渗透 + 门禁 G-4）；`ui_contract_violation >0 P0` |

> ⚠️ **`rule_id` 基数**：域 = `("", R01…R20)` = **21 个取值**，`BOUNDED_ALLOWED_LABELS["rule_id"]` 已同步为 **21**（曾经写 20 ⇒ 第 21 个取值会被基数闸门**丢弃并计进 `metric_label_overflow_total`**，表现只是"看板少一条线"——§15.3 纪律② 要防的那种静默）。空值 = "本轮载体没给规则号"，**刻意不填 `"unknown"`**：看到 `gate_reject_total{rule_id=""}` 涨，先怀疑**载体缺字段**，不是"出现了一条叫 unknown 的规则"。
> ⚠️ **别把告警级当放行事故**：`R17`–`R20` 命中**本就应该继续执行**（U-16 裁定：写成拒绝是实现缺陷，会误杀正常查询）。它们的计数不是"危险查询"。

---

## 2. 判定

```bash
BASE=http://127.0.0.1:8000/api/v1
# 2.1 分诊第一步：是"帧错"还是"闸门松"？两者信号互不重叠
#     ✅ /metrics 已注册（README §四-4）。走宿主映射 8000 直读；⚠️ 经 80 端口会被 nginx **故意 404**
#        （`location = /api/v1/metrics`），那是设计不是故障 —— 别在 80 上试完就断定"端点坏了"。
curl -sS "$BASE/metrics" | grep -E '^ui_contract_violation_total|^gate_reject_total|^refuse_total'
#     读不到（api 未起 / 500）→ 转 §2.2 / §2.3 的日志路径；**不要用"没有线"当"没有事"**
#     （恒 0 线 = 该族**声明了标签取值域**（或无标签），与接没接线、有没有流量无关；
#       整族缺席 = 有无域标签**且从未被观测**，既可能是没接线也可能是还没流量 —— README §四-6）
```

```bash
cd deploy
# 2.2 A 类：抓一条违规流（拿到 trace_id / task_id / session_id 再去查现场）
docker compose logs --since 15m api | grep -E "ui_contract_violation|terminal" | tail -30
#     字段名以 §15.1 契约为准：trace_id / task_id / session_id / node / stage / outcome / error_code / rule_id
#     ⚠️ node 只进日志、绝不进 SSE（06 D2 红线）—— 所以图内定位**只能靠日志**

# 2.3 B 类：闸门拒绝率突降的现场
docker compose logs --since 30m api | grep -oE '"rule_id":"R[0-9]{2}"' | sort | uniq -c | sort -rn
docker compose logs --since 30m api | grep -cE "GATE_AST_REJECTED|GATE_POLICY_REJECTED|COST_TOO_HIGH"

# 2.4 配置面核对（只读，不改）：闸门相关项有没有被人动过
docker compose exec -T api python -c "import os;\
print({k:os.getenv(k) for k in ('GATE_REJECT_SELECT_STAR','GATE_MAX_REPAIR_ROUNDS','GATE3_COST_REJECT','GATE3_ROWS_REJECT','EXEC_MAX_ROWS','EXEC_STATEMENT_TIMEOUT_MS','SEMANTIC_REQUIRE_CERTIFIED','SEMANTIC_BUNDLE_PATH','APP_ENV')})"
```

```bash
# 2.5 跨租户：只能在库侧证（RLS 是最终强制边界，§13.3）—— 需真 PG，SQLite 沙箱判不了
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select relname, relrowsecurity, relforcerowsecurity from pg_class
     where relname in ('audit_log','query_task','session','cost_ledger') order by 1;"
docker compose exec -T pg psql -U postgres -d ecom -c \
  "select polname, polrelid::regclass, polqual is not null as has_qual from pg_policy;"
# 存在性泄露的判据在应用侧：scope.level 三值是否被正确降为 role_limited/tenant_isolated（§13.5 禁 LLM 参与）
```
✅ **2026-09-19 真机读数**（两条 SQL 均可执行，迁移 head=`0005`）：

| 读数 | 判读 |
|---|---|
| 承载租户数据的 **6 张业务底表**（`order_paid` 494,249 行 / `order_refund` 23,116 / `traffic_daily` 1,500,556 / `product` 6,000 / `shop` 12 / `campaign` 84）**全部** `relrowsecurity=t` **且** `relforcerowsecurity=t`，各挂 **1 条** `p_*_tenant` 策略且 `polqual is not null = t` | ✅ "RLS 是最终强制边界"在**业务表**上成立，且 `FORCE` 也开着 ⇒ 表 owner 也绕不过去 |
| `audit_log`、`cost_ledger`、`query_plan`：`relrowsecurity=f`、0 条策略 | ⚠️ **别把上一行的判据外推到这三张**。它们的边界不是 RLS：`audit_log` 靠 `trg_audit_log_immutable` + `app_rw` 无 UPDATE/DELETE（见 `RL-1` §2.5 实测），`cost_ledger`/`query_plan` 靠**只有应用能写**。“跨租户读审计会被 RLS 挡住”是**错的** |
| 其余 `rls=f` 的表（`metric_def`/`dimension`/`synonym`/`join_path`/`region`/`policy`/`semantic_bundle`/`embed_doc`/`asset`/`default_predicate`/`feedback`/`gold_query`） | 语义层/配置面，按 §6.1 是**全局共享**的 ⇒ 无租户策略是当前设计，不是漏配 |
| 2.5a 按名字点了 4 张表，只回 2 行 | ⚠️ 因为 **`query_task` 与 `session` 在任何 schema 下都不存在**（全库按 `table_name` 搜 = 0 行）。这**不是**"迁移没跑"——`alembic_version=0005` 就是 head。会话面在 Redis/检查点侧。定性要不要建这两张表归 W1B |

⇒ 本条的存在性泄露判据仍然在**应用侧**（`scope.level` 三值是否被正确降为 `role_limited`/`tenant_isolated`，§13.5 禁 LLM 参与）；库侧这组读数只证明"最后一道墙在位"，不证明"上游没漏"。

**分流结论** → A 类走 §3-A，B 类走 §3-B，**两类都做 §3-C 的禁止清单**。

---

## 3. 处置动作

### 3-A · A 类（契约违规：保现场，别停服务）

1. **保存现场**（帧序列一旦被覆盖就无法复现，这是唯一的证据）：
   ```bash
   cd deploy && docker compose logs --since 30m --timestamps api > ../backend/reports/w7/rl5_frames_$(date +%Y%m%d%H%M).log
   ```
   ⚠️ 该文件落 `backend/reports/w7/`（**W7 自己的子目录**，08 §4.1），不得落到别人目录。
2. **按 `kind` 定位责任层**：`terminal_missing_flag` / `duplicate_terminal` / `terminal_after_terminal` / `stream_without_terminal` 全部指向 **帧产出点**（`app/graph/events.py` 是唯一产出点，归 **W4**）。观测器只负责"发现"，不负责"修"。
3. **确认客户端不会卡死**：`data.terminal === true` 是前端**唯一**判据（附录 A §A.1.4，N-16 前端零判断权）。若 `stream_without_terminal`，前端会停在"加载中" → 通知 **W5** 只做展示兜底，**不得**在前端补判据（那是第二份真相）。
4. **不做**任何重启：帧序列 bug 是确定性的，重启只是换个时间再犯，还会打断在途流。

### 3-B · B 类（闸门松 / 跨租户：先止血）

1. **缩小暴露面（可执行的手段只有这几个，都不是"冻结会话"）**：
   ```bash
   cd deploy && docker compose stop web          # 挡新会话，api 与在途流不动
   ```
   ⚠️ **§18.7 的"冻结相关会话"当前无实现**：没有任何运维侧的会话冻结/禁用接口（`app/api/routers/session.py` 只有创建与读历史）。最接近的**单流**手段是用户侧 `POST /api/v1/query/{task_id}/cancel`（`app/api/routers/query.py:255`，幂等），它是**取消**不是冻结，且取消也要写审计 `outcome=failed`（§18.3 步 5 / §8.3 要求②）。缺能力 → **待架构窗口分配编号**，不自创端点。
2. **靠配置收紧，不靠改代码**（`deploy/.env`；改前 `cp .env .env.bak-$(date +%Y%m%d%H%M)`）：
   ```
   GATE_REJECT_SELECT_STAR=true      # 若被改成 false，这是第一嫌疑（R03 的开关）
   GATE3_COST_REJECT=200000          # 原 500000：收紧成本闸门
   GATE3_ROWS_REJECT=2000000         # 原 5000000
   EXEC_MAX_ROWS=5000                # 原 10000
   SEMANTIC_REQUIRE_CERTIFIED=true   # 若被改成 false，未认证口径会进 prompt
   ```
   生效需重启：`docker compose stop --timeout 45 api && docker compose up -d api`（§18.3 姿势；drain 第 1~3 步已实装并用桩实测过顺序，但真实 `app.main:app` 上的 SSE 链路未测 ⇒ **仍挑空载**；停机后 `Exited (143)` 属正常产物，`137` 才是被 SIGKILL。见 README §四-2）。
3. **回滚语义包（最常见根因：包换版把 `policy.deny_columns` / `allowed_assets` 改松了）**。§18.5 口径：`bundle_version` **不灰度**（语义一致性要求全量原子切换），回滚 = **`active_version` 指针回指旧版本，旧版本保留 7 天**。落地方式：`deploy/.env` 的 `SEMANTIC_BUNDLE_PATH=/semantic/bundle_<旧版>.yaml` + 重启；宿主挂载是 `../semantic:/semantic:ro`（`docker-compose.yml:94`），**语义包升级/回退只改宿主文件 + 重启 api，不改 compose**。
4. **核对规则实体与编号有没有漂**（只读比对，不改）：
   ```bash
   cd ../backend
   ../.venv/Scripts/python.exe -m pytest tests/redteam/test_redteam_guard.py -q   # 红队断言（W2C/W4 共建）
   ```
   ⚠️ 本次事件处置中**不建议**顺手跑全量 pytest（另一窗口可能在用这套栈，且本条只需红队断言）。跑前先确认。
   若红队用例**本地全绿但生产没拒** → 方向是"配置/包不一致"，回到 §3-B-2/3。
5. **跨租户已确认成立时**：这是门禁 **G-4** 级事件。除止血外必须留证（`trace_id`、命中的 `scope.level`、该次结果行数），并**立刻上呈架构窗口 + W1B（RLS 归 `app/repo/**`）**。**不得**用"给该角色加白名单"的方式"修复"。

### 3-C · 两类共同的禁止清单

* ⛔ **不得为了让告警消失而放宽 τ 或关闸门**：调 `BINDING_TAU` 降澄清率是 N-25 明令禁止的方向（补救应回看语义包）；关闸门破坏 N-03（三道闸门顺序不可变、不可跳过）。
* ⛔ **不得关闭审计或临时绕过 fail-closed**（N-09 / NFR-3.4）。审计写不进去时**拒绝下发结果**是正确行为。
* ⛔ **不得 `docker kill` / `kill -9`**（§18.3；README §三-2）。
* ⛔ **不得把 A 类误报成安全事件**（会引发不必要的停服），也**不得**把 B 类当成"只是帧序问题"继续放量。
* ⛔ **429 与 409 都不是本条**：`429 RATE_LIMITED` 只表示配额；`409 SESSION_CONFLICT` 是会话串行冲突，处置完全不同（见 RL-4 §2 分流表）。不要因为看到 4xx 就以为"闸门在起作用"。

**回滚**：① `docker compose start web` 恢复入口；② `.env` 从时间戳备份还原 + 按 §3-B-2 姿势重启；③ 语义包回滚是**双向可逆**的指针操作（`active_version` 回指即可，旧包 7 天内不删）；④ 若为诊断加过 nginx 规则，`git checkout -- deploy/nginx.conf`（该文件在版本控制内）。

---

## 4. 验证恢复

| 类别 | 判据 | 位置 |
|---|---|---|
| A | `ui_contract_violation_total` **增量 = 0**，连续 ≥15min（§15.3 的口径是"任何非零都是 P0"，所以恢复判据必须是**增量为零**，不是"比昨天低"） | 指标已可读：`/metrics` 已注册，宿主 `curl -sS "$BASE/metrics"`（8000）；容器内退回 `python -c urllib`（精简镜像无 curl，见 README §四-4）。本族 `kind` 有声明域 ⇒ 冷启就有 5 条恒 0 线，"增量为零"是**实测**不是猜。**但注意读法**：0 行只表示"没有新违规"，不表示"观测缺席"；真要否定违规，还要 §4-A 的帧序列判据共同成立 |
| A | 一次真实 `/query` 的帧序列：恰有 **1** 个 `terminal:true`，且它之前无终态事件（§14.3 约束 1–3） | SSE 原始流（`curl -N` 直连 8000 或经 80 各看一次，nginx 缓冲会掩盖症状：`nginx.conf` 的 SSE 三件套必须完好） |
| B | `gate_reject_total` 速率**回到基线带**（不是越高越好：回不去 = 还没修对；异常高 = 收紧过头会误杀） | 指标 / 日志 |
| B | 红队断言全绿且**逐条 rule_id 可追**：`tests/redteam/test_redteam_guard.py`；R17–R20 必须是"产生告警且查询继续"的断言方向 | `backend/tests/redteam/`（W2C/W4） |
| B | `refuse_total{reason}` 与 `clarify_total{reason}` 没有出现异常塌陷（收紧过头的第一个信号） | §15.3 语义指标 |
| B | 语义包版本确认是预期的那一个：`curl -sS $BASE/healthz/ready` 的 `bundle_version` 与 §3-B-3 指定值一致 | readiness payload（`bundle_version` 在 `ready` 与 `/healthz` 里都有） |
| 共同 | 告警复位、事件单归档：结论 + 命中的 `rule_id`/`kind` + 处置动作 + 回滚记录写进 `backend/reports/w7/`（W7 子目录） | 交付目录 |

**不得声称的部分**：CI 红队断言绿 ≠ 生产闸门没松。§15.4 的实现方式明写生产侧只有"闸门拒绝率突降"这一间接探针；**"危险 SQL 放行"缺直接指标**这一事实要如实写进事件单（待架构窗口分配编号）。

---

## 5. 升级 / 联系（归属见 08 §4.1）

| 议题 | 找谁 |
|---|---|
| AST/策略/成本闸门实体（`app/guard/rules.py`、`ast_gate.py`、`policy_gate.py`、`cost_gate.py`） | **W2C** |
| SSE 帧序列与事件产出（`app/graph/events.py`、`app/graph/**`、`app/api/ratelimit.py`、`app/api/errors.py`） | **W4** |
| `AstRule` / `GateNo` / `ScopeLevel` 取值集（改它走 08 §4.3 四步） | **W0**（`app/core/enums.py`） |
| 语义包内容与版本物化（`semantic/**`、`app/semantics/**`） | **W1A**（内容资产）/ **W2A**（加载与物化） |
| RLS / 角色 / 迁移 / `audit_log` 权限 | **W1B** |
| 前端展示兜底（不得补判据） | **W5** |
| 红队集执行与门禁 G-4/G-6 判定 | **W6**（`eval/**` 执行器），红队集本身归 **W1A** |
| `ui_contract_violation` 采集器、`gate_reject_total` 本体、`/metrics`、告警规则与看板、`deploy/**` | **W7（本窗口）** |
| **不一致上呈**：① §18.7 要求的"冻结相关会话"**无任何实现手段**；② §15.3 的「图节点耗时 `node`(≤20)」指标不存在（只有 `stage` 口径），A 类图内定位只能靠日志；③ §15.4「危险 SQL 放行」无直接指标 | **架构窗口** → **待架构窗口分配编号** |
