-- W4 只读探针（零额度）：`complete` 残留那一支**只在 MemorySaver 夹具里成立吗**？
--
-- 由来（2026-09-29，W7 第二十三轮 ③）：她在生产路径"打不中"这一支（n=1）⇒ 要我核它是不是
-- `MemorySaver` 的产物；若是，"两种症状同一根"的归并理由要换支点。
--
-- 🔴 本件第一稿读错了面并已当场订正（不删）：`terminal` **不在** `checkpoints.checkpoint->'channel_values'`
--    里（那里 12,004 行全部读不到 terminal ⇒ 会让人误判"生产不持久化终态"）。
--    它落在 **`lg.checkpoint_blobs`**（`channel='terminal'`，msgpack）。⇒ 判"存不存"必须读 blobs。
--
-- 判法（纯 SQL、零解码）：残留**事件**用"前一条 run 的审计 `outcome`"当代理 ——
-- 等价性 = W4 扫 22 处 `terminal_update(event=…, outcome=…)` 实测：`complete↔SUCCESS`、
-- `refuse↔REFUSE`、`error↔FAILED`、`clarify↔CLARIFY`，**无一交叉**（`reports/w4/RELAY.md §26.2`）。
-- 崩臂自己 0 审计行 ⇒ 它读到的残留只可能来自**同 thread 的前一条 run**。
--
-- 跑法：
--   MSYS_NO_PATHCONV=1 docker exec -i commerceql-pg-1 psql -U postgres -d ecom -A -F'|' \
--     -f - < backend/reports/w4/probe_prod_checkpoint_terminal.sql

-- ① `terminal` 到底存不存在（读对的面上）+ 有多少 thread 带着它 ⇒ 残留的生产面规模
select
    '①blobs 里的 terminal' as k,
    count(*) as rows,
    count(distinct thread_id) as threads_with_terminal,
    (select count(distinct thread_id) from lg.checkpoints) as threads_total
from lg.checkpoint_blobs
where channel = 'terminal';

-- ② run 序列：每个 thread 上按时间排出的 tk（含它自己有没有留下 terminal 版本）
with run as (
    select
        thread_id,
        checkpoint -> 'channel_values' ->> 'task_id' as tk,
        min((checkpoint ->> 'ts')::timestamptz) as first_ts,
        bool_or((checkpoint -> 'channel_versions') ? 'terminal') as terminal_versioned
    from lg.checkpoints
    where checkpoint -> 'channel_values' ->> 'task_id' like 'tk_%'
    group by 1, 2
), seq as (
    select
        r.*,
        row_number() over (partition by thread_id order by first_ts) as turn,
        lag(tk) over (partition by thread_id order by first_ts) as prev_tk,
        lag(terminal_versioned) over (partition by thread_id order by first_ts) as prev_versioned
    from run r
)
select
    s.turn,
    count(*) as runs,
    count(*) filter (where a.task_id is null) as no_audit_row,
    count(*) filter (where s.terminal_versioned) as ended_with_terminal
from seq s
left join app.audit_log a on a.task_id = s.tk
group by 1
order by 1;

-- ③ ★ 决定性一条：W7 那 4 条崩臂，其 thread 上**前一条 run** 的审计 outcome（= 残留事件代理）
with run as (
    select
        thread_id,
        checkpoint -> 'channel_values' ->> 'task_id' as tk,
        min((checkpoint ->> 'ts')::timestamptz) as first_ts
    from lg.checkpoints
    where checkpoint -> 'channel_values' ->> 'task_id' like 'tk_%'
    group by 1, 2
), seq as (
    select
        thread_id, tk, first_ts,
        lag(tk) over (partition by thread_id order by first_ts) as prev_tk,
        row_number() over (partition by thread_id order by first_ts) as turn
    from run
)
select
    s.tk as crash_tk,
    s.thread_id,
    s.turn,
    coalesce(s.prev_tk, '(thread 首条)') as prev_tk,
    coalesce(pa.outcome, '(前一条无审计行)') as prev_outcome,
    coalesce(ca.outcome, '(本条无审计行)') as own_outcome
from seq s
left join app.audit_log pa on pa.task_id = s.prev_tk
left join app.audit_log ca on ca.task_id = s.tk
where s.tk in (
    'tk_6a1a6c029be7427cb41c7dac2ce736e1',
    'tk_a1e54c1d5d8c49bb8cd7117703020f45',
    'tk_9f575a098ecf4ac6be50649f20a18b23',
    'tk_398fa097c589466ba6b61c35a2b633cb'
)
order by s.turn;

-- ④ 规模：所有"第 2 轮及以后且 0 审计行"的 run（崩臂指纹），按前一条 outcome 分组
with run as (
    select
        thread_id,
        checkpoint -> 'channel_values' ->> 'task_id' as tk,
        min((checkpoint ->> 'ts')::timestamptz) as first_ts
    from lg.checkpoints
    where checkpoint -> 'channel_values' ->> 'task_id' like 'tk_%'
    group by 1, 2
), seq as (
    select
        thread_id, tk,
        lag(tk) over (partition by thread_id order by first_ts) as prev_tk,
        row_number() over (partition by thread_id order by first_ts) as turn
    from run
)
select
    coalesce(pa.outcome, '(前一条无审计行)') as prev_outcome,
    count(*) as crashed_runs
from seq s
left join app.audit_log ca on ca.task_id = s.tk
left join app.audit_log pa on pa.task_id = s.prev_tk
where s.turn > 1 and ca.task_id is null
group by 1
order by 2 desc;
