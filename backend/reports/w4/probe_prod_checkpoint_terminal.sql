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

-- 🔴 本轮实测（2026-10-01 11:31:23Z）：**不带 `ON_ERROR_STOP` 时，⑩b 报错、整份文件的 psql rc 仍然 = 0**（三条语句静默没跑）⇒ 本文件自带下面这行，任何复算都必须看到 rc=0 **且**行数对得上。
\set ON_ERROR_STOP on

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
--   🔴 W8 接手（2026-10-02，@ `f485ffe`，验收窗 T-12 的覆盖面延伸）：本件 ⑥/⑦/⑧/⑨ 四处 `wrote`/`wrote_terminal`
--     此前**没有**排除 `task_path` 第二段 = `__start__` 的入口复位写行 ⇒ 与 W7 `r23` 同一形状的潜伏假绿（修复后任何 run 走到入口都留一条 terminal 写行）。
--     现测（全库）：`channel='terminal'` = **825 行**／其中 `__start__` = **6 行 / 3 个 thread**，这 6 行的 ts 全部落在 **2026-10-01T12:55:28Z–12:56:27Z**
--     ⇒ **本件历史读数（06:17Z / 11:26Z / 11:27Z 三批）作用域内 `__start__` 行数 = 0 ⇒ 加排除不推翻任何已登记的数**，只防下一次重跑。
--     换式不改动读数的 A/B 对照与复算命令见 `backend/reports/w8/RELAY.md` §一。
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         (checkpoint->>'ts')::timestamptz as ts
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%'
), runs as ( select thread_id, tk, min(ts) as first_seen from ck group by 1,2 ),
rn as ( select thread_id, tk, first_seen,
               row_number() over (partition by thread_id order by first_seen) as turn from runs ),
wr as ( select c.tk,
               bool_or(w.channel = 'terminal' and split_part(w.task_path, ', ', 2) <> '__start__') as wrote_terminal,
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
               bool_or(w.channel = 'terminal' and split_part(w.task_path, ', ', 2) <> '__start__') as wrote_terminal
        from ck c join lg.checkpoint_writes w
          on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id
        group by 1 )
select r.turn as turn,
       count(*) filter (where w.routed_supp) as runs_routed_audit_supp,
       count(*) filter (where w.routed_supp and w.wrote_terminal) as routed_and_wrote_terminal,
       count(*) filter (where w.routed_supp and not w.wrote_terminal) as routed_but_NO_terminal_write
from rn r left join wr w on w.tk = r.tk
group by 1 order by 1;


-- ============ ⑧⑨⑩⑪ 回 W7 第三十轮的四条（2026-10-01 11:25–11:29Z，零额度、只读）============
-- ⚠️ 本轮我自己踩到并纠出的形状：**`not (x like 'tk_%')` 在 `x` 为 NULL 时得 NULL** ⇒ `count(*) filter (where …)` / `where` 静默丢行。
--    第一稿 B4/B5 因此报出 `non_tk_rows = 0`（看着像"每条检查点都带 tk"，其实是"NULL 行全没被算"）。
--    正解 = `coalesce(checkpoint->'channel_values'->>'task_id' like 'tk_%', false)`，或干脆走集合差。
--    ⇒ 与本机既有坑「『没有 X』用集合差、不用 is null」同族：**否定式谓词碰到 NULL 就是空集**。

-- ⑧ 家族级 vacuity 表（W7 ② 那条假绿条件，我自己量）
--   实测（2026-10-01 11:27:04Z，全库 turn>=2，分母 = run）：
--     u_f 23 条 / 18 条路由到终态出口 / 格2p 反例 18 / 格2 反例 5 / 零审计行 5 / max_routes 3
--     u_l 15 / 15 / 15 / 0 / 0 / 3      u_g 11 / 11 / 11 / 0 / 0 / 3      u_h 4 / 4 / 4 / 0 / 0 / 3
--     u_b  8 / **0** / 0 / 0 / 8 / **2** ⇒ session-lock 那一族**根本不走到出口** ⇒ 对它 格2 与 格2p 都恒为 0（= 假绿，不是达成）
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         (checkpoint->>'ts')::timestamptz as ts
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%'
), runs as ( select thread_id, tk, min(ts) as first_seen from ck group by 1,2 ),
rn as ( select thread_id, tk, first_seen, left(split_part(thread_id,':',2),3) as fam,
               row_number() over (partition by thread_id order by first_seen) as turn from runs ),
wr as ( select c.tk,
               bool_or(w.channel = 'terminal' and split_part(w.task_path, ', ', 2) <> '__start__') as wrote,
               bool_or(w.channel = 'branch:to:audit_supp') as supp,
               bool_or(w.channel in ('branch:to:present','branch:to:refuse_out','branch:to:clarify_out','branch:to:error_out')) as exitnode,
               count(distinct w.channel) filter (where w.channel like 'branch:to:%') as n_routes
        from ck c join lg.checkpoint_writes w
          on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id
        group by 1 ),
j as ( select r.fam, r.turn, coalesce(w.wrote,false) as wrote, coalesce(w.supp,false) as supp,
              coalesce(w.exitnode,false) as exitnode, coalesce(w.n_routes,0) as n_routes,
              (a.task_id is not null) as has_row
       from rn r left join wr w on w.tk = r.tk left join app.audit_log a on a.task_id = r.tk )
select '⑧ 家族级 turn>=2 覆盖面' as k, fam, count(*)::text as t2_runs,
       count(*) filter (where exitnode)::text as t2_exit_routed,
       count(*) filter (where exitnode and not wrote)::text as ge2p_exit_but_no_write,
       count(*) filter (where supp and not wrote)::text as ge2_supp_but_no_write,
       count(*) filter (where not has_row)::text as t2_zero_audit_row,
       max(n_routes)::text as max_routes
from j where turn >= 2 group by fam order by ge2p_exit_but_no_write desc, fam;

-- ⑨ ★ 按轮：被路由到终态出口 ⟺ 本轮自己写了 terminal —— 这是格2 的**放大版**（格2p），也是判据② 最硬的一格
--   实测（2026-10-01 11:26:32Z，全库，分母 = run）：
--     turn1 = 1,317 条 run / 813 条路由到出口 / **813 条写了 terminal / 反例 0**
--     turn2 = 39 / 28 / 反例 28；turn3 = 15 / 14 / 14；turn4 = 6 / 5 / 5；turn5 = 1 / 1 / 1
--     ⇒ turn>=2 的反例合计 = **48**（= 有审计行的那 48 条，见 ⑨b）；pre-fix 全库"走到出口但没写终态"= 48，修复后期望 **0**
--   ⇒ 比格2（只在 u_f 有 5 条）覆盖大一个数量级，且**用现有数据就能出 pre-fix 基线**，不需要为它花一分钱。
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         (checkpoint->>'ts')::timestamptz as ts
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%'
), runs as ( select thread_id, tk, min(ts) as first_seen from ck group by 1,2 ),
rn as ( select thread_id, tk, row_number() over (partition by thread_id order by min(ts)) as turn
        from ck group by 1,2 ),
wr as ( select c.tk,
               bool_or(w.channel = 'terminal' and split_part(w.task_path, ', ', 2) <> '__start__') as wrote,
               bool_or(w.channel in ('branch:to:present','branch:to:refuse_out','branch:to:clarify_out','branch:to:error_out')) as exitnode
        from ck c join lg.checkpoint_writes w
          on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id
        group by 1 )
select r.turn::text as turn, count(*)::text as runs,
       count(*) filter (where coalesce(w.exitnode,false))::text as routed_terminal_exit,
       count(*) filter (where coalesce(w.exitnode,false) and coalesce(w.wrote,false))::text as exit_and_wrote,
       count(*) filter (where coalesce(w.exitnode,false) and not coalesce(w.wrote,false))::text as exit_but_NO_write,
       count(*) filter (where coalesce(w.wrote,false))::text as wrote_any
from rn r left join wr w on w.tk = r.tk
group by r.turn order by r.turn;

-- ⑨b 恒等式（turn>=2）：「有审计行」⟺「被路由到终态出口」⇒ 13 条零行崩臂 = 13 条**根本没走到出口**的 run
--   实测（2026-10-01 11:27:33Z）：t2_runs=61 / with_row=48 / exit_routed=48 / row_equiv_exit=**61** / row_no_exit=0 / exit_no_row=0
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         (checkpoint->>'ts')::timestamptz as ts
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%'
), runs as ( select thread_id, tk, min(ts) as first_seen from ck group by 1,2 ),
rn as ( select thread_id, tk, row_number() over (partition by thread_id order by min(ts)) as turn
        from ck group by 1,2 ),
wr as ( select c.tk, bool_or(w.channel in ('branch:to:present','branch:to:refuse_out','branch:to:clarify_out','branch:to:error_out')) as exitnode
        from ck c join lg.checkpoint_writes w
          on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id group by 1 ),
j as ( select r.turn, coalesce(w.exitnode,false) as exitnode, (a.task_id is not null) as has_row
       from rn r left join wr w on w.tk = r.tk left join app.audit_log a on a.task_id = r.tk )
select '⑨b 恒等式 turn>=2' as k, count(*)::text as t2_runs,
       count(*) filter (where has_row)::text as with_row,
       count(*) filter (where exitnode)::text as exit_routed,
       count(*) filter (where has_row = exitnode)::text as row_equiv_exit,
       count(*) filter (where has_row and not exitnode)::text as row_no_exit,
       count(*) filter (where exitnode and not has_row)::text as exit_no_row
from j where turn >= 2;

-- ⑩ run 边界三面（W7 ③ 交我定义，她只量了路由行的时间形状；这三条把她的边界缺口补掉）
--   实测（2026-10-01 11:27:33Z / 11:28:28Z / 11:29:41Z）：
--     B1 `checkpoint_ns` 分布 = **全部为空**（12,004 行里 0 行非空）⇒ 本库无 subgraph 旁路；代码侧同轮现测：`app/graph/build.py` 只有一个 `CompiledStateGraph`、不传 `checkpoint_ns`
--     B2 同一个 `tk` 出现在 >=2 个 thread 上 = **0** ⇒ run 归属唯一
--     B3 同一 thread 上两个 run 的 `min(ts)` 平局 = **0**（run 组 1,378 / 有 tk 的 thread 1,317）⇒ turn 序不会退化成任意序
--     B4/B5 无 `task_id` 键的检查点行 = **1,325**，其中落在本 thread 首个 tk 行**之后**的 = **0** 条 ⇒「建线期行恒在 run 之前」是全称句
--         ⇒ 所以"数检查点 = 数 run"必然 off-by-one（12,004 行 / 10,679 条带 tk / 1,378 个 run），W7 那句警告成立且更强
select '⑩a checkpoint_ns 是否全空' as k, count(*)::text as ck_rows,
       count(*) filter (where checkpoint_ns is distinct from '')::text as non_empty_ns
from lg.checkpoints;

select '⑩b tk 跨 thread / first_seen 平局' as k,
       (select count(*) from (
          select checkpoint->'channel_values'->>'task_id' tk, count(distinct thread_id) n
          from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1 having count(distinct thread_id) > 1) x)::text as tk_on_2plus_threads,
       (select count(*) from (
          select thread_id, fs from (
             select thread_id, checkpoint->'channel_values'->>'task_id' tk, min((checkpoint->>'ts')::timestamptz) fs
             from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2) b
          group by 1, fs having count(*) > 1) y)::text as tie_groups,
       (select count(distinct checkpoint->'channel_values'->>'task_id')
          from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%')::text as run_groups;

select '⑩c 无 tk 行的时间形状（NULL-safe 谓词）' as k, count(*)::text as non_tk_rows,
       count(distinct thread_id)::text as threads_with_non_tk,
       count(*) filter (where exists (select 1 from (
           select thread_id, min((checkpoint->>'ts')::timestamptz) ft from lg.checkpoints
           where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1) tf
           where tf.thread_id = lg.checkpoints.thread_id and (checkpoint->>'ts')::timestamptz < tf.ft))::text as before_first_tk,
       count(*) filter (where exists (select 1 from (
           select thread_id, min((checkpoint->>'ts')::timestamptz) ft from lg.checkpoints
           where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1) tf
           where tf.thread_id = lg.checkpoints.thread_id and (checkpoint->>'ts')::timestamptz >= tf.ft))::text as at_or_after_first_tk
from lg.checkpoints
where coalesce(checkpoint->'channel_values'->>'task_id' like 'tk_%', false) = false;

-- ⑪ 三面 distinct thread 对撞（W7 ④ 报 1,322 / 1,319 / 1,318 ⇒ 我这面逐字复现）
--   实测（2026-10-01 11:29:41Z）：checkpoints 1,322 / blobs 1,319 / writes 1,318；blobs 行 17,118 / writes 行 46,460
select '⑪ 三面 distinct thread' as k,
       (select count(distinct thread_id) from lg.checkpoints)::text as ck_threads,
       (select count(distinct thread_id) from lg.checkpoint_blobs)::text as blob_threads,
       (select count(distinct thread_id) from lg.checkpoint_writes)::text as write_threads,
       (select count(*) from lg.checkpoint_blobs)::text as blob_rows,
       (select count(*) from lg.checkpoint_writes)::text as write_rows;
