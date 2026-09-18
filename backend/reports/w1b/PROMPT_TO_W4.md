# 开工指令 → W4：T5.3 `POST /feedback` 接线（W1B 侧阻塞已解除）

> 来源 = `backend/reports/w1b/RELAY.md §12.1`（W1B 窗口，2026-09-18）。本文件是**独立可用的开工指令文本**，不需要回读 W1B 的会话上下文。
> 授权人 = 用户（2026-09-18）：**开工**。

---

## 0 前提：你现在缺的东西全都有了

| W4 需要 | 状态 | 落点（可自行核实） |
|---|---|---|
| `app.feedback` / `app.gold_query` 两张表 | ✅ 已建 | W1B `7f205e2`；迁移 `backend/app/repo/migrations/versions/0005_feedback_and_gold_query.py` |
| `FeedbackStore`（写入 + 幂等回读） | ✅ 已交付 | `backend/app/repo/feedback.py` |
| `FeedbackReasonCode`（10 值） | ✅ 已落地 | W0 `c31f9b9`；`backend/app/core/enums.py:486` |
| `fb_` id 前缀 | ✅ 已登记 | `backend/app/obs/trace.py:32` |
| `POST /feedback` 端点本体 | ⏳ **归你**（你上窗自标 T5.3「未开工」） | `backend/app/api/routers/` |

⇒ 你上窗 HANDOFF §四 里「**T5.3 枚举落点待裁**」这条**已闭**：枚举 W0 落、表结构 W1B 落。**你只剩接线**，不再有前置阻塞。

---

## 1 接线片段（照做即可）

```python
# 装配（lifespan 或端点依赖）：复用元数据池，**不要**新建连接资源
store = FeedbackStore(pools.metadata)

# 端点内（幂等的正确形态：先回读，再写）
ctx = deps.get_identity()                      # IdentityContext（app/core/contracts.py:67）
user_id = ctx.user_id                          # ⚠️ 该字段就是 JWT 的 sub
                                               #    链路：JWT.sub → VerifiedToken.subject(tokens.py:78)
                                               #        → IdentityContext.user_id(contracts.py:79)
                                               #    ⚠️ 别传 tenant_id（会静默造出"跨租户的同一个人"）
existing = await store.find_feedback_id(
    task_id=body.task_id, user_id=user_id, reason_code=body.reason_code
)
if existing is not None:
    feedback_id = existing                     # 幂等命中：返回**同一条**
    queued_for_review = ...                    # 见 §3.2（口径归你定）
else:
    feedback_id = new_id("feedback")           # → `fb_<32 位 hex>`（§A.6 明文；W0 已登记前缀）
    await store.insert_feedback(
        feedback_id=feedback_id, task_id=body.task_id, user_id=user_id,
        is_correct=body.is_correct, reason_code=body.reason_code,
        corrected_sql=body.corrected_sql, comment=body.comment,
        correct_result_hint=body.correct_result_hint,
    )
```

> ⚠️ **W1B 首版笔误已订正**：`identity.subject` 是**错的** —— `subject` 是 `VerifiedToken`（`app/auth/tokens.py:78`）的字段名，
> `IdentityContext`（`app/core/contracts.py:79`）上叫 **`user_id`**。端点内拿到的通常是后者，照抄旧文会 `AttributeError`。

---

## 2 逐参数契约

| 参数 | 列 | 约束 / 注意 |
|---|---|---|
| `feedback_id` | `feedback_id` | PK，**你生成**（`new_id("feedback")`）；本层不造 id（id 唯一来源 = `app.obs.trace`） |
| `task_id` / `user_id` | 同 | NOT NULL；`user_id` **必须**是 `deps.get_identity().user_id`（= JWT `sub`）。**别传 `tenant_id`** |
| `is_correct` | `is_correct` | bool（传 `1` 会被本层拒） |
| `reason_code` | `reason_code` | **枚举入参** `FeedbackReasonCode` 或 `None`；裸字符串在调用点就红 |
| `corrected_sql` / `comment` / `correct_result_hint` | 同 | 可空 |

---

## 3 三条边界（踩了会静默出错）

### 3.1 `correct_result_hint` 有列了

§A.6 请求里有这个字段、§12.3 表行漏写 ⇒ 迁移 0005 已补列。之前「收到只能丢」的情况不存在了，**别丢**。

### 3.2 `queued_for_review` 的口径**归你定**（W1B 不替你选）

表里没有 status 列，审核接口也不存在。两种都能自圆其说：

- `not body.is_correct` —— 任何「结果有误」都进池等归因；
- `not body.is_correct and body.corrected_sql is not None` —— 只有带修正的才进池。

**唯一硬约束：别谎报 `true`** —— 行真的落了才 `true`。

### 3.3 幂等**别靠捕异常**

- 撞唯一约束 = `sqlalchemy.exc.IntegrityError`（`.orig` 才是 `psycopg.errors.UniqueViolation`）。
- **捕到了也拿不到已有 id** ⇒ 必须用 `find_feedback_id` **先回读**。
- 并发下仍可能撞（两请求同时回读到 `None`）⇒ 那时捕 `IntegrityError` 再回读一次即可。
- ⚠️ `reason_code` 可为 `None`：唯一键用了 `UNIQUE NULLS NOT DISTINCT`（PG16 实测 `indnullsnotdistinct = t`），
  读回用了 `IS NOT DISTINCT FROM` —— **两处必须成对**。少一处则「重复提交 null reason」永远查不到
  （`= NULL` 恒 UNKNOWN）。

---

## 4 验收要件（回执必须给实证，不接受「应该幂等」）

| # | 断言 | 取证方式 |
|---|---|---|
| ① | 首次提交 → 落行成功，`feedback_id` 形如 `fb_…` | `SELECT * FROM app.feedback WHERE feedback_id='fb_…'` 的实际输出 |
| ② | 同 `(task_id, user_id, reason_code)` 再提交 → **返回同一条 `feedback_id`，且行数不变** | 第二次响应 + `SELECT count(*)` |
| ③ | `reason_code = null` 的重复提交**也命中** | 同上，两次 `null` |
| ④ | 非枚举 `reason_code` 在**调用点**就红（`FeedbackStore` 拒），DB CHECK 只是兜底 | 单测即可 |
| ⑤ | `is_correct` 传 `1` 被拒（要 bool） | 单测即可 |

测试纪律（**踩过，别重复**）：

- DSN 必须**双向**归一（正向 `_sqla()` + 反向 `_libpq()`）—— CI 注入 libpq 形态、本地缺省 SQLAlchemy 形态，
  只写一边就是「本地绿 CI 红」（W1B `90fc312` 实锤）。
- **不要写 `async def test_`**：pytest-asyncio 1.4 自建循环不认 `set_event_loop_policy`，
  Windows 撞 `psycopg.InterfaceError: ProactorEventLoop`；惯例 = 同步用例内 `asyncio.run(...)`。
- 取准确计数用 `pytest -q --basetemp=.w4tmp`（收尾会被 harness safe-delete 守卫杀掉 ⇒ 摘要行不刷、exit=1，
  但进度条全 `.` = 零失败），跑完 `rm -rf .w4tmp`。

---

## 5 明确**不在**本次范围（别顺手做）

1. **`gold_query` 有表无写入通道** —— §A.6 只定义了 `POST /feedback`，审核状态机 / 审核端点不存在 ⇒ **没有合法写入方**。
   这不是遗漏，**别自行发明审核接口**。
2. **`iat` 未来时刻的归因改动** —— 会牵动 contract 计数，已登记待架构裁；裁前**别动** `app/auth/tokens.py`
   （W1B 文件，要改请先提需求）。
3. **`app/cache/` CachePort 归属未裁** —— 别在 `POST /feedback` 里顺手引入缓存。
4. `app/main.py` 是 **W1B 的组装根**（lifespan 六步）—— **你只追加，不得另立第二根**。

---

## 6 顺手项（优先级你自己判）

- **T7**：`QueryPlanStore` 写一行 —— W1B `251d866` 已交付，装配片段 = `RELAY §10.1`。
  这是 **W3C DoD① 的最后一步**，一行的事。
- **T6**：`main.py` 追加装配 —— 解「**端点当前 500**」（`GraphRuntime` 未进 lifespan）。
  不装配，上面 ①②③ 的 HTTP 层取证根本跑不起来。

---

## 7 一句别信的话

「令牌能签出来 ⇒ 端到端通了」—— **不成立**。令牌只在 `TokenVerifier` 层证过
（W1B 用被交付方自己的校验器自验，抓出过 2 个真 bug）；**HTTP 层截至 2026-09-18 无人证过**：
本地 `commerceql-api-1` 跑的是 6 小时前镜像，`/api/v1/sessions` 与 `/docs` 均 404。

要真令牌：

```bash
python backend/scripts/mint_dev_token.py --tenant-id tenant_a --role analyst --scope "query:read"
```

（详见 `RELAY §12.4`；容器内差异与重启失效问题见 `RELAY §12.2`）

---

**回执去向**：把要件 ①②③ 的实证贴进 `backend/reports/w4/RELAY.md`。本文件作者 = W1B；
与 `RELAY.md §12.1` 若有出入，以本文件为准（§12.1 的 `subject` 笔误已在此处订正）。
