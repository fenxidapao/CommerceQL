-- r22_lag_runseq.sql —— 还 W4 的账：上一版 `lag` 跑在**审计行序列**上（0 行的崩溃臂被跳过），
-- 本版把序列换成**run 序列**，且序列取「审计面 ∪ 入账面」的并集而不是只用 `cost_ledger`。
-- 为什么不用纯 ledger 法：`cost_ledger` 只有**发生过 LLM 调用**的 run，0 次调用的 run（例如
-- 在任何调用前就被拒）会整条消失 ⇒ 它的后继会被误判成"上一轮 = 再前面那条"。两侧互补，故并集。
-- 用法（只读、零额度）：
--   MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'|' -f - < deploy/loadtest/r22_lag_runseq.sql
-- ⚠️ 定轮**不加时间过滤**（u_f01..u_f12 的全部历史就在本轮内），但**输出只限 A 档窗口** ⇒ 换窗口 = 换被测对象。
-- ⚠️ `app.audit_log` 有 `uq_audit_log_task_id` ⇒ 每 run 至多 1 行；本轮实测该窗口 95 行 / 95 个 task_id（不重复）。

-- ① 尺自检：并集序列里两侧各贡献多少 run（"只在账面无审计" = 崩溃臂；"只在审计面无账面" = 0 次调用）
with aud as (
  select task_id, user_id, min("timestamp") as ts
  from app.audit_log where user_id like 'u_f%' and user_id <> 'u_f00' group by 1,2
), led as (
  select task_id, user_id, min(created_at) as ts
  from app.cost_ledger where user_id like 'u_f%' and user_id <> 'u_f00' group by 1,2
)
select case when a.task_id is not null and l.task_id is not null then 'both'
            when a.task_id is not null then 'audit_only(0 次调用)'
            else 'ledger_only(无审计行 = 崩溃臂)' end as face,
       count(*) as runs,
       count(*) filter (where a.ts < '2026-09-29 06:17:00+00' or a.ts >= '2026-09-29 06:19:30+00') as outside_a_win,
       count(*) filter (where l.ts < '2026-09-29 06:17:00+00' or l.ts >= '2026-09-29 06:19:30+00') as outside_a_win_by_ledger_ts
from aud a full outer join led l using (task_id)
group by 1 order by 2 desc;

-- ② 主件：A 档窗口内的浅失败，其**上一条 run** 的结论（run 序列 + 崩溃臂占位）
with aud as (
  select task_id, user_id, min("timestamp") as ts, max(outcome) as outcome,
         bool_or(latency_ms ? 'gen_sql') as deep, max(refusal_reason) as reason
  from app.audit_log where user_id like 'u_f%' and user_id <> 'u_f00' group by 1,2
), led as (
  select task_id, user_id, min(created_at) as ts, count(*) as calls, round(sum(cost_cny)::numeric, 6) as cny
  from app.cost_ledger where user_id like 'u_f%' and user_id <> 'u_f00' group by 1,2
), runs as (
  select coalesce(a.task_id, l.task_id) as task_id,
         coalesce(a.user_id, l.user_id) as user_id,
         least(coalesce(a.ts, l.ts), coalesce(l.ts, a.ts)) as ts,
         a.outcome, a.deep, a.reason,
         (a.task_id is null) as no_audit_row,
         coalesce(l.calls, 0) as calls,
         l.cny
  from aud a full outer join led l using (task_id)
), seq as (
  select runs.*,
         row_number() over (partition by user_id order by ts) as turn,
         lag(coalesce(outcome, '(无审计行)')) over (partition by user_id order by ts) as prev_outcome,
         lag(ts)                             over (partition by user_id order by ts) as prev_ts
  from runs
)
select turn, coalesce(prev_outcome, '(none=该 user 首条)') as prev_on_runseq, count(*) as n
from seq
where outcome = 'failed' and deep is false
  and ts >= '2026-09-29 06:17:00+00' and ts < '2026-09-29 06:19:30+00'
group by 1,2 order by 1, 3 desc;

-- ③ 逐条可核对清单（交给 W4 对第五档）：每条浅失败的 run / 上一条 / 间隔 / 自身调用数与花费
with aud as (
  select task_id, user_id, min("timestamp") as ts, max(outcome) as outcome,
         bool_or(latency_ms ? 'gen_sql') as deep
  from app.audit_log where user_id like 'u_f%' and user_id <> 'u_f00' group by 1,2
), led as (
  select task_id, user_id, min(created_at) as ts, count(*) as calls, round(sum(cost_cny)::numeric, 6) as cny
  from app.cost_ledger where user_id like 'u_f%' and user_id <> 'u_f00' group by 1,2
), runs as (
  select coalesce(a.task_id, l.task_id) as task_id,
         coalesce(a.user_id, l.user_id) as user_id,
         least(coalesce(a.ts, l.ts), coalesce(l.ts, a.ts)) as ts,
         a.outcome, a.deep, coalesce(l.calls, 0) as calls, l.cny
  from aud a full outer join led l using (task_id)
), seq as (
  select runs.*,
         row_number() over (partition by user_id order by ts) as turn,
         lag(coalesce(outcome, '(无审计行)')) over (partition by user_id order by ts) as prev_outcome,
         extract(epoch from ts - lag(ts) over (partition by user_id order by ts))::numeric(10,2) as gap_s
  from runs
)
select user_id, turn, task_id, prev_outcome, gap_s, calls, cny
from seq
where outcome = 'failed' and deep is false
  and ts >= '2026-09-29 06:17:00+00' and ts < '2026-09-29 06:19:30+00'
order by user_id, turn;

-- ④ 对照臂（防"并集序列"本身把结论带偏）：**纯 ledger 定轮法**（W4 指定的原始口径）的同一张表
with led as (
  select task_id, user_id, min(created_at) as ts
  from app.cost_ledger where user_id like 'u_f%' and user_id <> 'u_f00' group by 1,2
), seq as (
  select led.*, a.outcome, (a.latency_ms ? 'gen_sql') as deep, a."timestamp" as aud_ts,
         row_number() over (partition by led.user_id order by led.ts) as turn,
         lag(coalesce(a.outcome, '(无审计行)')) over (partition by led.user_id order by led.ts) as prev_outcome
  from led left join app.audit_log a using (task_id)
)
select coalesce(prev_outcome, '(none=该 user 首条)') as prev_on_ledgerseq, count(*) as n
from seq
where outcome = 'failed' and deep is false
  and ts >= '2026-09-29 06:17:00+00' and ts < '2026-09-29 06:19:30+00'
group by 1 order by 2 desc;

-- ⑤ 免费判别面：残留若是"上一轮的 refuse 终态"，审计面最可能留痕的形状 = `failed` 行却带 refusal_reason。
--    这条只交形状、不下结论（0 行命中也是一条读数：但前提是该列**不是恒空**，故同表带出 refuse 行的命中率）。
select outcome,
       (latency_ms ? 'gen_sql') as deep,
       (refusal_reason is not null) as has_refusal_reason,
       count(*) as n
from app.audit_log
where user_id like 'u_f%' and user_id <> 'u_f00'
  and "timestamp" >= '2026-09-29 06:17:00+00' and "timestamp" < '2026-09-29 06:19:30+00'
group by 1,2,3 order by 1, 4 desc;
-- 实测：failed|f|f = 13、failed|t|f = 43、refuse|f|t = 18、clarify|f|f = 8、success|t|f = 13
--   ⇒ `failed` 行 **0/56 带 refusal_reason**，而 `refuse` 行 18/18 带 ⇒ 该列非恒空 ⇒ 0 命中是一条读数。

-- ⑥ 浅失败 13 条 vs 深失败：latency_ms 键集到底差在哪（把最后一个可读面交给 W4 的通道矩阵）
with a as (
  select task_id, (latency_ms ? 'gen_sql') as deep,
         string_agg(k, ',' order by k) as keys
  from app.audit_log, lateral jsonb_object_keys(latency_ms) as k
  where user_id like 'u_f%' and user_id <> 'u_f00' and outcome = 'failed'
    and "timestamp" >= '2026-09-29 06:17:00+00' and "timestamp" < '2026-09-29 06:19:30+00'
  group by 1,2
)
select deep, keys, count(*) as n from a group by 1,2 order by 1 desc, 3 desc;
