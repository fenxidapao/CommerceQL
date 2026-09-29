-- r21_turn_index.sql —— ④′A 档（06:17:08Z–06:18:21Z，T_A / u_f01..u_f12）按"该 user 的第几轮"重切读数
-- 用法（只读、零额度）：
--   MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'|' -f - < deploy/loadtest/r21_turn_index.sql
-- ⚠️ 三条语句各自的判据不同，别只跑第一条：
--   ① 每个 outcome/深度桶落在第几轮（首轮 vs 第 2 轮+ 的分布）
--   ② 13 条浅失败的"上一轮是什么结论"
--   ③ 单变量对照臂：turn1 与 turn2plus 各自的浅失败数（**这条才是本轮的结论件**）
-- ⚠️ 时间窗必须与那一格回执的 started_at / finished_at 一致；换窗口 = 换被测对象。

-- ① 分布
with base as (
  select task_id, user_id, outcome, refusal_reason, "timestamp",
         (latency_ms ? 'gen_sql') as deep
  from app.audit_log
  where "timestamp" >= '2026-09-29 06:17:00+00' and "timestamp" < '2026-09-29 06:19:30+00'
), t as (
  select base.*, row_number() over (partition by user_id order by "timestamp") as turn
  from base
)
select outcome,
       coalesce(refusal_reason, '-') as reason,
       deep,
       count(*) as n,
       min(turn) as turn_min,
       max(turn) as turn_max,
       count(*) filter (where turn = 1)   as on_turn1,
       count(*) filter (where turn >= 2)  as on_turn2plus
from t
group by 1, 2, 3
order by n desc;

-- ② 浅失败的上一轮结论（turn 与 prev_outcome 分成两层 CTE：窗口函数不能嵌套）
with base as (
  select user_id, outcome, "timestamp", (latency_ms ? 'gen_sql') as deep
  from app.audit_log
  where "timestamp" >= '2026-09-29 06:17:00+00' and "timestamp" < '2026-09-29 06:19:30+00'
), t as (
  select base.*,
         row_number() over (partition by user_id order by "timestamp") as turn,
         lag(outcome)  over (partition by user_id order by "timestamp") as prev_outcome
  from base
)
select turn, coalesce(prev_outcome, '(none=首轮)') as prev_outcome, count(*) as n
from t
where outcome = 'failed' and deep is false
group by 1, 2
order by 1, 3 desc;

-- ③ 单变量对照：首轮臂 vs 第 2 轮+臂
with base as (
  select user_id, outcome, "timestamp", (latency_ms ? 'gen_sql') as deep
  from app.audit_log
  where "timestamp" >= '2026-09-29 06:17:00+00' and "timestamp" < '2026-09-29 06:19:30+00'
), t as (
  select base.*, row_number() over (partition by user_id order by "timestamp") as turn
  from base
)
select case when turn = 1 then 'turn1' else 'turn2plus' end as arm,
       count(*) as rows_total,
       count(*) filter (where outcome = 'failed' and deep is false) as shallow_failed,
       count(*) filter (where outcome = 'failed' and deep)          as deep_failed,
       count(*) filter (where outcome = 'success')                  as ok
from t
group by 1
order by 1;
