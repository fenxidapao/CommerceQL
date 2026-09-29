-- ★ 靶子 = 三个变量：命令行给了就用命令行的（\if :{?var} 守卫），没给才落默认（第二十轮 A 档）
--   复算别的格（**值里不要再套单引号** —— `:'win_a'` 自己会加引号，套两层会静默 0 行）：
--     psql ... -v win_a='2026-09-29 12:26:53+00' -v win_b='2026-09-29 12:26:59+00' -v upref='u_g%' -f - < 本文件
--   ⚠️ 覆盖生效的自检：② 那行的 audit_rows 必须 > 0；报 0 先怀疑变量写法而不是"这一格没数据"。
\if :{?win_a}
\else
\set win_a '2026-09-29 06:17:00+00'
\endif
\if :{?win_b}
\else
\set win_b '2026-09-29 06:19:30+00'
\endif
\if :{?upref}
\else
\set upref 'u_f%'
\endif


-- r23_thread_from_checkpoints.sql —— 把第二十轮 A 档从 **user 尺** 升到 **thread 尺**，判 W4 `316ef37` §② 的可判伪预言：
--   「同一 thread 上 `refuse` 行与 `failed` 行不会相邻交替」⇒ 我原先那 4 条 `prev=refuse ⇒ 本轮 failed` 应当改判。
-- 原理（本轮新连的免费面，零额度）：`lg.checkpoints.checkpoint->'channel_values'->>'task_id'` 带着**我们自己的 `tk_…`**
--   ⇒ `thread_id = {tenant}:{user}:{session}` 与每条 run 可以直接 join，不需要重跑、不需要新量具。
-- 用法：
--   MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'|' -f - < deploy/loadtest/r23_thread_from_checkpoints.sql
-- ⚠️ 三条前提都做成读数放在下面，不接受默认成立：① `tk → thread` 唯一 ② 审计行全部映射得上 ③ 该 thread 在窗口前没有历史（否则"首轮"不成立）。

-- ① 尺自检：`task_id → thread_id` 是不是 1:1（多线 = 映射不可用，后面全部作废）
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
)
select '①唯一性' as k, count(*) as pairs, count(distinct tk) as distinct_tk,
       count(*) filter (where tk in (select tk from ck group by tk having count(distinct thread_id) > 1)) as multi_thread_tk
from ck;

-- ② 覆盖率 + thread 尺的规模（对照：A 档只有 12 个 user）
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
), a as (
  select task_id, user_id, outcome, "timestamp"
  from app.audit_log
  where user_id like :'upref' and user_id <> 'u_f00'
    and "timestamp" >= :'win_a' and "timestamp" < :'win_b'
)
select '②覆盖' as k, count(*) as audit_rows, count(ck.thread_id) as mapped,
       count(*) - count(ck.thread_id) as unmapped, count(distinct ck.thread_id) as threads,
       count(distinct a.user_id) as users
from a left join ck on ck.tk = a.task_id;

-- ③ 前提③：这些 thread 有没有窗口前的历史（有 ⇒ "首轮"这个词不能用）
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
), t as (
  select thread_id, min(first_seen) as thread_first from ck group by 1
)
select '③thread 起点' as k,
       count(*) filter (where thread_first >= :'win_a') as first_in_window,
       count(*) filter (where thread_first <  :'win_a') as had_history
from t
where thread_id in (
  select ck.thread_id from ck join app.audit_log a on a.task_id = ck.tk
  where a.user_id like :'upref' and a.user_id <> 'u_f00'
    and a."timestamp" >= :'win_a' and a."timestamp" < :'win_b');

-- ④ ★ 判伪主件：thread 尺上所有**相邻 outcome 跳变**的种类计数
--     W4 的预言 = `refuse→failed` 与 `failed→refuse` 都应当是 **0**；只要有一条非零 ⇒ 它的机制不完备（存在第二条翻转路径）
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
), j as (
  select ck.thread_id, ck.first_seen, a.task_id, a.outcome, (a.latency_ms ? 'gen_sql') as deep
  from app.audit_log a
  join ck on ck.tk = a.task_id
  where a.user_id like :'upref' and a.user_id <> 'u_f00'
    and a."timestamp" >= :'win_a' and a."timestamp" < :'win_b'
), seq as (
  select j.*,
         lag(outcome) over (partition by thread_id order by first_seen) as prev_outcome,
         row_number() over (partition by thread_id order by first_seen) as turn
  from j
)
select coalesce(prev_outcome, '(thread 首条)') as prev, outcome as cur, count(*) as n
from seq
where prev_outcome is not null
group by 1,2
order by n desc;

-- ⑤ ★★ 单一判据：只问 W4 点名的那两种相邻跳变各几条
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
), j as (
  select ck.thread_id, ck.first_seen, a.task_id, a.outcome
  from app.audit_log a
  join ck on ck.tk = a.task_id
  where a.user_id like :'upref' and a.user_id <> 'u_f00'
    and a."timestamp" >= :'win_a' and a."timestamp" < :'win_b'
), seq as (
  select j.*, lag(outcome) over (partition by thread_id order by first_seen) as prev_outcome from j
)
select 'refuse→failed' as jump, count(*) as n from seq where prev_outcome = 'refuse' and outcome = 'failed'
union all
select 'failed→refuse', count(*) from seq where prev_outcome = 'failed' and outcome = 'refuse'
union all
select '任意→failed(浅失败族)', count(*) from seq where outcome = 'failed';

-- ⑥ 13 条浅失败在 **thread 尺** 上的"上一条"（对照我第二十二轮 user 尺的 `failed 9 / refuse 4`）
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
), j as (
  select ck.thread_id, ck.first_seen, a.task_id, a.user_id, a.outcome, (a.latency_ms ? 'gen_sql') as deep
  from app.audit_log a
  join ck on ck.tk = a.task_id
  where a.user_id like :'upref' and a.user_id <> 'u_f00'
    and a."timestamp" >= :'win_a' and a."timestamp" < :'win_b'
), seq as (
  select j.*,
         lag(coalesce(outcome,'?')) over (partition by thread_id order by first_seen) as prev_outcome,
         row_number() over (partition by thread_id order by first_seen) as turn
  from j
)
select coalesce(prev_outcome, '(thread 首条)') as prev_on_thread, count(*) as n
from seq
where outcome = 'failed' and deep is false
group by 1 order by 2 desc;

-- ⑦ thread 尺的"首轮 vs 第 2 轮+"对照臂（我上一轮给的是 user 尺的 0/12 vs 17/96 —— 那条要按这把尺重读）
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
), j as (
  select ck.thread_id, ck.first_seen, a.task_id, a.outcome, (a.latency_ms ? 'gen_sql') as deep
  from app.audit_log a
  join ck on ck.tk = a.task_id
  where a.user_id like :'upref' and a.user_id <> 'u_f00'
    and a."timestamp" >= :'win_a' and a."timestamp" < :'win_b'
), seq as (
  select j.*, row_number() over (partition by thread_id order by first_seen) as turn from j
)
select case when turn = 1 then 'thread 首轮' else 'thread 第 2 轮+' end as arm,
       count(*) as runs,
       count(*) filter (where outcome = 'failed' and deep is false)          as shallow_failed,
       count(*) filter (where outcome = 'failed' and deep)                   as deep_failed,
       count(*) filter (where outcome = 'success')                           as ok,
       count(*) filter (where outcome = 'refuse')                            as refuse,
       count(*) filter (where outcome = 'clarify')                           as clarify
from seq
group by 1 order by 1;

-- ⑧ 每条 thread 上有几轮（直方图）⇒ "同 thread 多轮"这一维在 A 档里到底占多少
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
), j as (
  select ck.thread_id, a.task_id
  from app.audit_log a
  join ck on ck.tk = a.task_id
  where a.user_id like :'upref' and a.user_id <> 'u_f00'
    and a."timestamp" >= :'win_a' and a."timestamp" < :'win_b'
), per_thread as (
  select thread_id, count(*) as runs from j group by 1
)
select case when runs = 1 then '1 轮' when runs = 2 then '2 轮' when runs = 3 then '3 轮' else '4 轮+' end as depth,
       count(*) as threads, sum(runs) as runs
from per_thread group by 1 order by 1;

-- ⑨ 崩臂（审计面 0 行的那 4 条 run）在 thread 尺上的位置 —— 它们没有审计行 ⇒ 只能靠 checkpoints 定轮
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints
  where checkpoint->'channel_values'->>'task_id' like 'tk_%'
  group by 1,2
), seq as (
  select thread_id, tk, first_seen,
         row_number() over (partition by thread_id order by first_seen) as turn
  from ck
)
select s.tk, s.thread_id, s.turn, (a.task_id is null) as no_audit_row
from seq s
left join app.audit_log a on a.task_id = s.tk
where s.tk in ('tk_6a1a6c029be7427cb41c7dac2ce736e1','tk_a1e54c1d5d8c49bb8cd7117703020f45',
               'tk_9f575a098ecf4ac6be50649f20a18b23','tk_398fa097c589466ba6b61c35a2b633cb')
order by s.turn;
