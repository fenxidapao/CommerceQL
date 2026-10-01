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


-- ============ ⑤⑥⑦ W4 独立复算 W7 第二十九轮的 ⑯/⑯b（2026-10-01，零额度、只读）============
-- 问题（W7 第 29 轮留给我的那一格）：`t2_with_terminal_write`（pre-fix = 0）到底是
--   ①「第 2 轮真的没自己持久化终态」（= U-129 的机制），还是
--   ②「写面对 terminal 黏在第一轮」（= W6 第十七轮 ⑤ 的量具警告）？
-- 判别读点：同一写面上 turn>=2 的 run **有没有别的通道写行**。有 ⇒ 该面切得出 run 边界 ⇒ 那个 0 是真读数。
-- 实测（2026-10-01 06:17Z，本机 `lg` 库，全库不分窗口）：
--   turn1 = 1,317 条 run / 1,316 条有写行 / 813 条有 terminal 写
--   turn2 = 39 / 39 / 39（有 branch 行）/ terminal 写 0；turn3 = 15、turn4 = 6、turn5 = 1 ⇒ 同形
--   ⇒ 解释 ② 在 terminal 这一通道上被现测**排除**（turn>=2 的 run 在该面确实有行，只是没有 terminal 行）。
-- ⚠️ 该面不是 run 级 1:1：身份通道（`session_id`/`user_id`/`task_id`/…）各 **1,992 行** > run 数 **1,378**
--   ⇒ 任何 run 级读数都必须先按 `checkpoint_id` 连回带 `tk_` 的检查点、再按 tk 归属聚合（⑥⑦ 即这么做）。
-- ⑤ 写面通道分布 + 覆盖面：terminal 是不是一个"真被写的通道"、四种终态是否都在该面有实例
--   实测（06:17Z）：writes_total=46,460 / channel='terminal'=813 / 'branch:to:%'=8,482（22 种节点）
--                   与 lg.checkpoint_blobs 的 terminal 行数（813，813 个 thread）**逐字同数**；
--                   terminal 写按 run 归属后的审计 outcome 组成 = refuse 423 / failed 206 / clarify 114 / success 70
--                   ⇒ 该面对**每一类终态**都有生产实例 ⇒ 修复后若第 2 轮自己写了终态，这一面必然看得见。
select 'terminal_rows' as k, count(*)::text as v from lg.checkpoint_writes where channel = 'terminal'
union all select 'branch_to_rows', count(*)::text from lg.checkpoint_writes where channel like 'branch:to:%'
union all select 'branch_to_node_kinds', count(distinct channel)::text from lg.checkpoint_writes where channel like 'branch:to:%'
union all select 'blobs_terminal_rows', count(*)::text from lg.checkpoint_blobs where channel = 'terminal'
union all select 'writes_total', count(*)::text from lg.checkpoint_writes
union all select 'identity_channel_rows', count(*)::text from lg.checkpoint_writes where channel = 'session_id';

-- ⑥ ★ 判别：按轮分桶看"该 run 有没有任何写行 / 有 branch 行 / 有其它通道行 / 有 terminal 写"
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         (checkpoint->>'ts')::timestamptz as ts
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%'
), runs as ( select thread_id, tk, min(ts) as first_seen from ck group by 1,2 ),
rn as ( select thread_id, tk, first_seen,
               row_number() over (partition by thread_id order by first_seen) as turn from runs ),
wr as ( select c.tk,
               bool_or(w.channel = 'terminal') as wrote_terminal,
               bool_or(w.channel like 'branch:to:%') as has_branch_rows,
               bool_or(w.channel <> 'terminal' and w.channel not like 'branch:to:%') as has_other_rows
        from ck c join lg.checkpoint_writes w
          on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id
        group by 1 )
select r.turn as turn_bucket, count(*) as runs,
       count(w.tk) as runs_with_any_write_row,
       count(*) filter (where w.has_branch_rows) as with_branch_rows,
       count(*) filter (where w.has_other_rows) as with_other_channel_rows,
       count(*) filter (where w.wrote_terminal) as with_terminal_write
from rn r left join wr w on w.tk = r.tk
group by 1 order by 1;

-- ⑦ ★ 蕴含式「被路由到 audit_supp ⇒ 本轮写了 terminal」的真值表（按轮）—— 判据② 的强化形状
--   实测（2026-10-01 06:19Z）：turn1 = 70 条被路由 / 70 条写了 terminal / **0 条反例**
--                    turn2 = 5 条被路由 / 0 条写了 terminal / **5 条反例**（turn3/4/5 = 0）
--   且这 5 条反例逐条 = 零审计行崩臂：u_f04 06:17:38Z / u_f07 06:17:54Z / u_f09 06:18:04Z /
--   u_f06 06:18:05Z / u_f00 06:40:33Z（09-29），与 ⑬ 的 prev=success 5 条同族。
--   ⇒ 修复后的验收不该只盯 `t2_with_terminal_write > 0`（要等第 2 轮恰好走到 complete 才有数）；
--     `t2_routed_audit_supp_without_terminal_write`（pre-fix = 5）**应 = 0**，这一格不依赖窗口里有没有成功轮。
--   ⚠️ 顺带交一条对 W7 不利的：她 ⑯ 注释"`audit_supp` 全库只有 70 条 run 被路由到，全在 turn1"里
--     "全在 turn1"不成立 ⇒ 全库 = **75**（turn1 的 70 + turn>=2 的 5），且她自己上一行写的正是那 5 条。
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         (checkpoint->>'ts')::timestamptz as ts
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%'
), runs as ( select thread_id, tk, min(ts) as first_seen from ck group by 1,2 ),
rn as ( select thread_id, tk, first_seen,
               row_number() over (partition by thread_id order by first_seen) as turn from runs ),
wr as ( select c.tk,
               bool_or(w.channel = 'branch:to:audit_supp') as routed_supp,
               bool_or(w.channel = 'terminal') as wrote_terminal
        from ck c join lg.checkpoint_writes w
          on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id
        group by 1 )
select r.turn as turn,
       count(*) filter (where w.routed_supp) as runs_routed_audit_supp,
       count(*) filter (where w.routed_supp and w.wrote_terminal) as routed_and_wrote_terminal,
       count(*) filter (where w.routed_supp and not w.wrote_terminal) as routed_but_NO_terminal_write
from rn r left join wr w on w.tk = r.tk
group by 1 order by 1;
