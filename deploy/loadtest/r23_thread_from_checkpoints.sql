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

-- ⑩ 🔴 「0 审计行 = 崩臂」必须限定 **turn>=2**（W4 ②′ 的警告，本轮我自己数过）。
--    ⚠️ 本段与 ⑪⑫ 是**全库诊断**：不按窗口/前缀过滤，只按 `task_id like 'tk_%'` 取 run 序列。
--    ⚠️ 第一稿我在这里写了 `like :'upref' or true` ⇒ 放进了 1,322 个 `task_id` 为 NULL 的检查点组，
--       它们 join 不上审计面、还把 window 排序的 turn1 整排占掉 ⇒ 报出「turn1 全部无行」的**假读数**（已修，教训：过滤式 hack 不要写在诊断段里）。
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2
), y as (
  select ck.thread_id, ck.tk,
         row_number() over (partition by ck.thread_id order by ck.first_seen) as turn,
         (a.task_id is null) as no_row
  from ck left join app.audit_log a on a.task_id = ck.tk
)
select case when turn = 1 then 'turn1' else 'turn2plus' end as arm,
       count(*) as runs, count(*) filter (where no_row) as no_audit_row
from y group by 1 order by 1;

-- ⑪ turn>=2 的无行 run 按「前一条 outcome」分桶 ⇒ W4 两因子判据的可否证面（他们的分类表在此面被检验）
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2
), seq as (
  select ck.thread_id, ck.tk,
         row_number() over (partition by thread_id order by first_seen) as turn,
         (a.task_id is null) as no_row,
         lag(case when a.task_id is null then '(前一条也无行)' else a.outcome end)
           over (partition by thread_id order by first_seen) as prev
  from ck left join app.audit_log a on a.task_id = ck.tk
)
select coalesce(prev, '(thread 首条)') as prev_outcome, count(*) as no_row_turn2plus
from seq where no_row and turn >= 2 group by 1 order by 2 desc;

-- ⑫ 落库面直读：残留的 terminal 通道到底存不存在于生产 saver（W4 ③ 的面，我自己数）
select 'checkpoint_blobs channel=terminal' as k, count(*) as rows_, count(distinct thread_id) as threads_
from lg.checkpoint_blobs where channel = 'terminal';
select '全库 thread 数' as k, count(distinct thread_id) as rows_, 0 as threads_ from lg.checkpoints;
-- ⑫b 🔴 「1,322」必须连谓词一起报（W6 第二十六轮第 4 条：同一个数两种谓词差 5，别留下"两跑矛盾"）
--      实测（09-30）：无谓词 = 1,322 / 带 `tk like 'tk_%'` = 1,317 / **无任何 tk_ 组** = 5 ⇒ 1,317 + 5 = 1,322 闭合
select '⑫b 无谓词 thread' as k, count(distinct thread_id) as n from lg.checkpoints;
select '⑫b 带 tk_ 谓词 thread' as k, count(distinct thread_id) as n
from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%';
with t_all as (select distinct thread_id from lg.checkpoints),
     t_tk as (select distinct thread_id from lg.checkpoints
              where checkpoint->'channel_values'->>'task_id' like 'tk_%')
select '⑫b 无任何 tk_ 组的 thread' as k, count(*) as n from t_all
where thread_id not in (select thread_id from t_tk);

-- ⑬ ★★ turn>=2 的「崩率」按前一条 outcome **交叉**（不是只数崩的那批）⇒ 架构问的「必崩 vs 偶发」在零额度面上第一次有分母。
--     ⚠️ 读法三条，缺一条就会把这张表读过：
--     (1) no_row_pct 只是「**同一靶子群体内**的频率」，不是随机样本 ⇒ 必须同看 users_bear / users_clean 两列有没有**重叠**；
--     (2) 若某桶的崩行全部来自一批 user 前缀、而同一桶的不崩行全部来自**另一些**前缀 ⇒ 该桶的 pct 是**靶子混淆**，不得当缺陷频率引用；
--     (3) 桶内**没有不崩的对照**（users_clean=0）时，pct=100 只说明「撞上的都崩了」，**不构成「必崩」的判定**（那需要同题同人的对照臂）。
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2
), seq as (
  select ck.thread_id, ck.tk, ck.first_seen,
         split_part(ck.thread_id, ':', 2) as usr,
         row_number() over (partition by ck.thread_id order by ck.first_seen) as turn,
         (a.task_id is null) as no_row,
         lag(case when a.task_id is null then '(前一条也无行)' else a.outcome end)
           over (partition by ck.thread_id order by ck.first_seen) as prev
  from ck left join app.audit_log a on a.task_id = ck.tk
)
select coalesce(prev, '(thread 首条)') as prev_outcome,
       count(*) as turn2plus_runs,
       count(*) filter (where no_row) as no_row,
       round(100.0 * count(*) filter (where no_row) / nullif(count(*), 0), 1) as no_row_pct,
       count(distinct usr) filter (where no_row) as users_bear,
       count(distinct usr) filter (where not no_row) as users_clean
from seq where turn >= 2 group by 1 order by 2 desc;

-- ⑬b 同一交叉按**小时 + user 前缀**归因 ⇒ 让上面第 (2) 条的靶子混淆可见（崩的是谁的靶子、不崩的是谁的靶子）
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2
), seq as (
  select ck.thread_id, ck.tk, ck.first_seen,
         split_part(ck.thread_id, ':', 2) as usr,
         row_number() over (partition by ck.thread_id order by ck.first_seen) as turn,
         (a.task_id is null) as no_row,
         lag(case when a.task_id is null then '(前一条也无行)' else a.outcome end)
           over (partition by ck.thread_id order by ck.first_seen) as prev
  from ck left join app.audit_log a on a.task_id = ck.tk
)
select coalesce(prev, '(thread 首条)') as prev_outcome,
       to_char(date_trunc('hour', first_seen), 'MM-DD HH24') as hour_bucket,
       no_row, count(*) as runs, string_agg(distinct usr, ',' order by usr) as users
from seq where turn >= 2 and (no_row or prev in ('success', '(前一条也无行)'))
group by 1, 2, 3 order by 1, 2, 3 desc;

-- ⑭ ★★ 「按前缀 + 窗口限定」的验收读数（W4 §二十八 第 6 条的请求：全库面混着 u_f*/u_b*/后续家族 ⇒ 修复后的 gate 必须限定，否则假红/假绿）
--     ⚠️ 四条措辞纪律，缺一条这条判据就会打人：
--     (1) **判据分子只许写 `crash_turn2plus = 0`**。不要把架构 v1.7.12 那句字面式 `terminal − 审计行(turn>=2)` 直接实现 ——
--         字面式的被减数**没有限定**，会被 turn1 的行放大（本轮实测三域：A 档子窗 字面 = 81 / 正确 = 4；
--         session-lock 格 字面 = 16 / 正确 = 8；全库 字面 = 1,330 / 正确 = 13）。两式只在「runs 全是 turn>=2」时才相等。
--     (2) **轮次必须按 thread 全历史算，再按窗口过滤**（本段就是这么写的）。反过来「先按窗口过滤、再算 turn」会把
--         窗口内的第 2 轮读成 turn1 ⇒ `crash_turn2plus` 静默变 0 ⇒ **假绿**。下方 ⑭b 就是这个陷阱的守卫。
--     (3) 默认靶子 = 第二十轮 A 档子窗 ⇒ `crash_turn2plus = 4` 是**修复前**的基线，**不是**修法失败的证据。
--         修复后请**换新令牌前缀 + 新时间窗**（-v upref='u_x%' -v win_a=... -v win_b=...），并且要求 ② 行 > 0 以自证覆盖生效。
--     (4) turn1 的零行（全库 **504** 条）结构性不进本判据 ⇒ 别把它当崩臂数报。
--     (5) 🔴 **分母纪律**（W6 第十五轮第 1 条，本轮采纳）：本段的 `runs_all` 按 **run** 数（= `lg.checkpoints` 里带 `tk_` 的组），
--         而 W6 的 `terminal` 按**发了终止事件的 run** 数 ⇒ 两个同名 `gap` **不可互认、不可相加**。
--         我这面历史上引过 gap 的四格实测 **terminal == runs**（A 档 99/99、`session-lock` 16/16、X1 4/4、X2 4/4 ⇒ 取回执 `admission.admitted` 与 `outcomes` 里终止类事件求和）
--         ⇒ **旧读数不受该差异影响**；但今后任何跨窗引用必须写明自己数的是哪个分母。
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2
), seq as (  -- turn 在**全历史**上算（纪律 2）
  select ck.thread_id, ck.tk, ck.first_seen, split_part(ck.thread_id, ':', 2) as usr,
         row_number() over (partition by ck.thread_id order by ck.first_seen) as turn,
         (a.task_id is not null) as has_row
  from ck left join app.audit_log a on a.task_id = ck.tk
), scoped as (  -- 算完才按前缀 + 窗口过滤
  select * from seq
  where first_seen between :'win_a'::timestamptz and :'win_b'::timestamptz
    and usr like :'upref'
)
select '⑭验收(按前缀+窗)' as k, count(*) as runs_all,
       count(*) filter (where turn = 1) as runs_turn1,
       count(*) filter (where turn >= 2) as runs_t2,
       count(*) filter (where turn >= 2 and has_row) as rows_t2,
       count(*) filter (where turn >= 2 and not has_row) as crash_turn2plus,
       count(*) - count(*) filter (where turn >= 2 and has_row) as gap_literal_DO_NOT_USE,
       count(*) filter (where turn >= 2) - count(*) filter (where turn >= 2 and has_row) as gap_both_restricted,
       count(distinct usr) as users_n,
       (count(*) = 0) as scope_empty__if_true_suspect_vars
from scoped;

-- ⑭b 纪律 2 的守卫：窗口内这些 thread 里，有多少**其实有窗口前历史**（>0 ⇒ 任何"先过滤再算 turn"的写法都不可信）
--   ★ 第二十八轮升级成三态（W6 第十六轮 ⑤ 已放行；三条件都守住：本标签仍以 `-- ⑭b` 行首出现、
--     `checkpoint->'channel_values'->>'task_id'` / `min((checkpoint->>'ts')::timestamptz` 两串原样保留、**列名与列数一字未动**）。
--   原缺陷：`window_turn_would_be_wrong` 是布尔 ⇒ 空作用域下读成 **`f`**，与"这一族 thread 确实没有窗口前历史"**分不开**（假绿方向，比 ⑭c 那个假红更危险）。
--   ⇒ 现在 `threads_in_win = 0` 时给 **NULL**：**只有 `= f` 才许说"这批 thread 的 turn 没被窗口截断"**；`t` = 被截断（不可信），`NULL` = 无从判定（先修窗口/前缀，并看 ⑭ 的 `scope_empty`）。
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2
), per_thread as (
  select thread_id, min(first_seen) as thread_first,
         min(first_seen) filter (where first_seen between :'win_a'::timestamptz and :'win_b'::timestamptz) as win_first,
         bool_or(first_seen < :'win_a'::timestamptz) as has_prehistory,
         count(*) filter (where first_seen between :'win_a'::timestamptz and :'win_b'::timestamptz) as runs_in_win
  from ck group by 1
)
select '⑭b turn 计算顺序守卫' as k, count(*) as threads_in_win,
       coalesce(sum(runs_in_win), 0) as runs_in_win,
       count(*) filter (where has_prehistory) as threads_with_prehistory,
       case when count(*) = 0 then null                                  -- NULL = 作用域为空 ⇒ 无从判定（第二十八轮）
            when count(*) filter (where has_prehistory) > 0 then true    -- t = 有 thread 带窗口前历史 ⇒ "窗口内重算 turn"不可信
            else false end as window_turn_would_be_wrong
from per_thread where runs_in_win > 0;

-- ⑭c 🔴 「读得太早」守卫（W6 第二十六轮第 3 条逼出来的；我这面独立复测：审计行写入延迟 n=861，p50 = 10.428s / p99 = 40.824s / **max = 187.623s**，负延迟 0 条）
--     机理与本尺形状的关系，说清两面：
--     · **本尺不需要 pad**：窗口只作用在 `first_seen`（检查点 ts），审计行按 `task_id` join、不带时间谓词 ⇒ 晚 188s 写的行照样落到它自己的 run 上 ⇒
--       W6 那种"pad 只 1 秒 ⇒ crash_turn1 < gap"的**漏计方向**在这里结构性不存在（他们的窗口 pad 作用在**审计行那一侧**）。
--       🔻 **第二十七轮就地订正（撤回括号里那句）**：「他们的 pad 作用在审计行那一侧」**是我从 W6 的散文推的、不是复算** ⇒ 作废。他们自复算 39/39：`audit_rows == runs_in_window` 全等、恒等式
--       `gap − crash1 − crash2p == terminal − matched` 成立 ⇒ **残差在 `terminal − matched`，成因是分母不同源（他们按 terminal、我按 run）**。
--       ⚠️ 本行前半句（**本尺的窗口只作用在 `first_seen`、审计 join 不带时间谓词 ⇒ 我这个方向结构性免疫**）仍然成立且是我自己量的 ⇒ 保留；**只是不再据此解释别人器件**。
--     · ⚠️ **但反方向的坑是真的**：一条 run "审计行还没写"与"永远不会有"在只读面上**长得一模一样** ⇒ 刚跑完的格读得太早，会把在途 run 计入 `crash_turn2plus`（**假红**，不是假绿）。
--       ⇒ 我引的 4 / 8 / 13 都是**历史窗**（读数年龄 ≫ max lag：现测 ≈30.6h = ≈586 倍、≈50.5h = ≈969 倍 ⇒ **引倍数别引秒数，秒数每秒在涨**）⇒ 不受影响；**修复后的新格必须先过这一条守卫**。
--     ⇒ 用法（★ 第二十七轮升级为三态）：**只有 `too_soon_to_read = f` 才许引 `crash_turn2plus`**；`t` = 读太早（假红），**`NULL` = 作用域为空 ⇒ 无从判定**（须并看 ⑭ 的
--       `scope_empty__if_true_suspect_vars = t`，且此时 `crash_turn2plus = 0` 是**最容易读成"验收通过"的假形状**）⇒ **`t` 与 `NULL` 一律不引**（与 W6 第十五轮第 4 条同形纪律）。
--     🔧 形状修复（本轮）：原来写 `from scoped, lagobs group by …` ⇒ 空作用域下**整段返回 0 行**（守卫自己没行 = 判据无法执行）⇒ 改 `agg` 使空集也出一行 + `case` 给 NULL。**列名与列数一字未动**（W6 已锚定 ⑭c）。
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2
), seq as (
  select ck.thread_id, ck.tk, ck.first_seen, split_part(ck.thread_id, ':', 2) as usr,
         row_number() over (partition by ck.thread_id order by ck.first_seen) as turn,
         (a.task_id is not null) as has_row
  from ck left join app.audit_log a on a.task_id = ck.tk
), scoped as (
  select * from seq
  where first_seen between :'win_a'::timestamptz and :'win_b'::timestamptz
    and usr like :'upref'
), lagobs as (
  select max(extract(epoch from (a."timestamp" - ck.first_seen))) as max_lag_s,
         count(*) as n_obs
  from ck join app.audit_log a on a.task_id = ck.tk
), agg as (  -- 🔧 第二十七轮修：原来写 `from scoped, lagobs group by ...` ⇒ **作用域为空时整段返回 0 行**（我上一轮交的守卫在"窗口写错/前缀不存在"时**根本没有行可判**）
  select count(*) as runs_in_scope,
         max(first_seen) as last_run,
         count(*) filter (where turn >= 2 and not has_row) as crash_turn2plus
  from scoped
)
select '⑭c 读数年龄与静默期' as k, agg.runs_in_scope,
       agg.crash_turn2plus,
       to_char(agg.last_run, 'MM-DD HH24:MI:SS') as last_run_in_scope,
       round(extract(epoch from (now() - agg.last_run))::numeric, 1) as read_age_s,
       round(lagobs.max_lag_s::numeric, 1) as observed_max_lag_s,
       lagobs.n_obs as lag_sample_n,
       -- ★ 三态（W6 第十五轮第 4 条的同形纪律）：f = 可引 / t = 太早不可引 / **NULL = 无从判定（含作用域为空）**
       --   ⇒ 读法：**只有 `too_soon_to_read = f` 才许引 `crash_turn2plus`**；`t` 与 NULL 一律不引，NULL 还要顺带看 ⑭ 的 `scope_empty__if_true_suspect_vars`
       case when agg.runs_in_scope = 0 then null
            when now() - agg.last_run < make_interval(secs => lagobs.max_lag_s) then true
            else false end as too_soon_to_read
from agg, lagobs;

-- ⑮ ★ A17 已裁（架构 v1.7.14 = `44b6783`）：`U-130` 判据② 由"字面式差值"改成**两臂配对的直读式** ⇒ 本段把我这面的尺补成同一形状：
--     **臂 1** =「窗口内 `turn≥2` 且审计行数 **= 0** 的 run 数」期望 0（= ⑭/⑭c 的 `crash_turn2plus`，这里独立再数一遍、含"行数"而不只是"有无行"）
--     **臂 2** =「窗口内 `turn≥2` 且审计行数 **> 1** 的 run 数」期望 0 ⇒ **臂 1 对"多落"是盲的**：W4 的入口复位（`33675b9`）若让第 2 轮把上一轮的行也带下来、或一轮写两行，
--                臂 1 读数仍是 0（看着像通过），只有臂 2 抓得到。架构在 `07` 里点名的就是这一格。
--   🔴 分母（⑭ 注释第 (5) 条）：两臂都按 **run**（`lg.checkpoints` 里带 `tk_` 的组）数，**不是 `terminal`** ⇒ 与他窗按 terminal 的同名数**不可互认、不可相加**；引用请带"分母=run"。
--   🔴 三态（与 ⑭b/⑭c 同形）：**作用域为空 ⇒ 两臂给 NULL 而不是 0**（空作用域下的 0 是最容易读成"验收通过"的形状）⇒ 读前先确认 `runs_in_scope > 0`（⑭c）且 `scope_empty = f`（⑭）。
--   ⚠️ 与 W6 的对表口径：他们那件里同名的 `multi_row_turn2plus_runs` 我这面**没有复算他们的窗**，两数各按各的前缀/窗口 ⇒ 相同只是巧合，不同也不必然是矛盾。
with ck as (
  select thread_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2
), seq as (
  select ck.tk, ck.thread_id, ck.first_seen, split_part(ck.thread_id, ':', 2) as usr,
         row_number() over (partition by ck.thread_id order by ck.first_seen) as turn,
         (select count(*) from app.audit_log a where a.task_id = ck.tk) as n_audit_rows
  from ck
), scoped as (
  select * from seq
  where first_seen between :'win_a'::timestamptz and :'win_b'::timestamptz
    and usr like :'upref'
)
select '⑮ A17 两臂（分母=run）' as k,
       count(*) as runs_in_scope,
       count(*) filter (where turn >= 2) as t2_runs,
       case when count(*) = 0 then null
            else count(*) filter (where turn >= 2 and n_audit_rows = 0) end as arm1_zero_row_runs__want_0,
       case when count(*) = 0 then null
            else count(*) filter (where turn >= 2 and n_audit_rows > 1) end as arm2_multi_row_runs__want_0,
       max(n_audit_rows) filter (where turn >= 2) as max_rows_per_t2_run,
       (count(*) = 0) as scope_empty__if_true_suspect_vars
from scoped;
