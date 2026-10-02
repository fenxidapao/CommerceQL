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

-- ⑯ ★ 第二个面 + 判据② 的"读点可行性"（W4 `9319c8d` 第 3 条把它定性成**设计问题**、W6 第十七轮 ⑤ 警告"写面是 thread 级上界、切不出 run 边界" ⇒ 本轮自己量）
--   面 = `lg.checkpoint_writes`（9 列：thread_id / checkpoint_ns / checkpoint_id / task_id(= LangGraph 内部 UUID，**不是我们的 tk_**) / idx / channel / type / blob / task_path）
--   连法 = 写行的 `checkpoint_id` 回到 `lg.checkpoints` 里带 `tk_` 的那一行 ⇒ **run 归属**（这一步是我这面的做法，W6 没这么做，所以两侧不必互认）。
--   现测（全库，零额度）：
-- 🔴 尺修正（2026-10-02，验收窗 QA 第二轮 ③ 提出、我这面独立复算坐实 ⇒ **凡以 `terminal` 写行当"本轮自写终态"的证据，一律排除 `task_path` 含 `__start__` 的行**）：
--   现测全库 `channel='terminal'` = **825 行**，其中 `task_path` 含 `__start__` = **6 行 / 3 个 thread**，且这 6 行**全部落在本轮 P-A′ 新格的三个 thread 上**（`u_r3101`/`e93c97`、`u_r3102`/`e5031c`、`u_r3103`/`42fc87`）。
--   ⇒ 三点后果：① **历轮的 813 不被推翻**（pre-fix 面上根本没有 `__start__` 行；加本轮 6 条真写行后非 `__start__` = **819**），但 **"逐 thread 恒 1 次"作废**（819 行 / 816 thread）；
--       ② 本轮**格2/格3 读数不变**（新格 6 条 run 用两个谓词各测：`t_all = 6`、`t_real = 6` ⇒ 排除后仍 6；`branch:to:audit_supp` 的 `__start__` 行 = **0** ⇒ 路由侧不受影响）；
--       ③ 但**风险是真的**：`__start__` 那行是 W4 修法的**入口复位写行**（`app/graph/state.py` 的 `RUN_SCOPED_STATE_FIELDS` 含 `terminal`、`assert_terminal_is_settable` 要求入口 `terminal is None`），
--           ⇒ 今后任何一条 run 只要走到入口就会留一条 `terminal` 写行；**不加排除 = "本轮自写终态"会被复位行冒充**（下一批跑批就可能真损失）。
--   ⇒ 用法变更（通知 W6/架构）：本件 `⑯`/`⑯b`/`⑰` 三处的 `wrote_terminal` 谓词已改 ⇒ **同源读数须重录 md5**；历史基线引这一列的，一律带"是否排除 `__start__`"。
--   ★ W8 接手订正（2026-10-02，@ `f485ffe`，只读复算）：三处排除式由 `task_path not like '%__start__%'` 改为 **`split_part(task_path, ', ', 2) <> '__start__'`**（与验收窗 T-12 的判据文本同形）。
--       理由 = LIKE 里的 `_` 是**单字符通配**，`'%__start__%'` 实为"任意两字符 + start + 任意两字符"⇒ 形状**过宽**，将来出现名字里含 `start` 的节点会把真终态写一起排掉（= 格3 假红）。
--       两式在 `channel='terminal'` 面上**现测同集合**（2026-10-02 全库：总行 **825**／命中 `__start__` **6**／split_part 命中 **6** ⇒ 等势且 like ⊇ split ⇒ 同集合；`task_path is null` 的 terminal 行 **0** ⇒ 换式不会因 NULL 丢行）。
--       ⇒ 因此这次换式**不改动任何读数**（A/B 对照见 `reports/w8/RELAY.md` §一）。
--     · `channel='terminal'` 在写面 = **813 行**，与 `lg.checkpoint_blobs channel='terminal'`（813）**逐字同数**；
--       但按上面的连法，这 813 行**全部落在 turn1 的 run 上**（turn≥2 = **0**）⇒ 于是有两种解释：① 修复前第 2 轮真的没自己持久化终态（= `U-129` 的机制），
--       ② 写面对终态是 thread 级黏在第一轮（= W6 的警告）。⇒ **判别的读点**：terminal 写会不会落到"零审计行的崩 run"上？现测 **0 次**（504 条 turn1 零行 run 一条都没有）
--       ⇒ 说明该面**能区分 run 的成败**、不是恒黏第一轮 ⇒ 解释 ① 更站得住；**但这是排除法不是全等证明**，P-A 那一格的 turn≥2 若有 terminal 写行 ⇒ ①成立且判据② 拿到落库面读点，若仍为 0 ⇒ ②成立、这一维判不了。**两种结果都有信息量。**
--     · 更有用的读点 = `channel like 'branch:to:%'`（= 逐 run 的**路由/节点集**，共 **8,482 行 / 22 种节点**）⇒ 这就是 W4 候选里的「逐 run `nodes_ran`」，**在落库面上存在**。
--       pre-fix 基线（全库按 run）：turn≥2 ∧ 零审计行 **13 条**里有 **5 条被路由到 `audit_supp`**（= N-08 那条出口，与 ⑬ 的"prev=success 5 条"逐字对上 ✓）；turn≥2 有审计行 48 条里 **0 条**走 `audit_supp`；
--       🔻 **第三十轮就地订正（原句作废、行数未变）**：被路由到 `audit_supp` 的全库真值 = **75 条 run**（turn1 **70** + turn≥2 **5**）；写面 distinct **thread** = 70、写**行数** = 75 ⇒ 我上一轮那句是把 **thread 数当 run 数**、又漏了 turn≥2 那 5 条（W6 `9abbe47` / W4 `fbd8512` / 架构 `3b697de` 三家同时逮到；正解与机制见 **⑰** 注释）。
--   ⇒ 用法：修复后的验收除 ⑮ 两臂之外，另看 `t2_routed_audit_supp` **应 = 0**（pre-fix 基线 5）与 `t2_with_terminal_write`（pre-fix 基线 0 ⇒ 若 >0 则判据② 的落库面读点成立）。
--   🔴 三态与分母同 ⑮：空作用域 ⇒ 派生列给 **NULL**、`scope_empty = t`；所有列分母 = **run**（带 `tk_` 的检查点组），不是 `terminal`。
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2,3
), run_first as (
  select thread_id, tk, min(first_seen) as first_seen from ck group by 1,2
), seq as (
  select rf.thread_id, rf.tk, rf.first_seen, split_part(rf.thread_id, ':', 2) as usr,
         row_number() over (partition by rf.thread_id order by rf.first_seen) as turn,
         (a.task_id is not null) as has_row
  from run_first rf left join app.audit_log a on a.task_id = rf.tk
), scoped as (
  select * from seq
  where first_seen between :'win_a'::timestamptz and :'win_b'::timestamptz
    and usr like :'upref'
), writes as (  -- 逐 run 的写面读数：该 run 自己有没有 terminal 写 / 被路由到哪些出口节点
  select c.tk,
         bool_or(w.channel = 'terminal' and split_part(w.task_path, ', ', 2) <> '__start__') as wrote_terminal,
         bool_or(w.channel = 'branch:to:audit_supp') as routed_audit_supp,
         bool_or(w.channel in ('branch:to:present','branch:to:refuse_out','branch:to:clarify_out','branch:to:error_out')) as routed_terminal_exit,
         count(distinct w.channel) filter (where w.channel like 'branch:to:%') as n_routes
  from ck c join lg.checkpoint_writes w on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id
  group by 1
), joined as (
  select s.tk, s.turn, s.has_row, coalesce(w.wrote_terminal, false) as wrote_terminal,
         coalesce(w.routed_audit_supp, false) as routed_audit_supp,
         coalesce(w.routed_terminal_exit, false) as routed_terminal_exit,
         coalesce(w.n_routes, 0) as n_routes
  from scoped s left join writes w on w.tk = s.tk
), agg as (
  select count(*) as runs_in_scope,
         count(*) filter (where turn >= 2) as t2_runs,
         count(*) filter (where turn >= 2 and wrote_terminal) as t2_with_terminal_write,
         count(*) filter (where turn >= 2 and routed_audit_supp) as t2_routed_audit_supp,
         count(*) filter (where turn >= 2 and routed_terminal_exit) as t2_routed_terminal_exit,
         count(*) filter (where turn >= 2 and not has_row and routed_audit_supp) as crash_t2_routed_audit_supp,
         count(*) filter (where turn >= 2 and n_routes = 0) as t2_runs_no_write_face,
         max(n_routes) as max_routes_per_run
  from joined
)
select '⑯ 写面可行性（分母=run，面=lg.checkpoint_writes）' as k, agg.runs_in_scope, agg.t2_runs,
       case when agg.runs_in_scope = 0 then null else agg.t2_with_terminal_write end as t2_with_terminal_write,
       case when agg.runs_in_scope = 0 then null else agg.t2_routed_audit_supp end as t2_routed_audit_supp,
       case when agg.runs_in_scope = 0 then null else agg.t2_routed_terminal_exit end as t2_routed_terminal_exit,
       case when agg.runs_in_scope = 0 then null else agg.crash_t2_routed_audit_supp end as crash_t2_routed_audit_supp,
       agg.t2_runs_no_write_face, agg.max_routes_per_run,
       (agg.runs_in_scope = 0) as scope_empty__if_true_suspect_vars
from agg;

-- ⑯b 全库侧的两条判别读数（不受窗口限定，用来支撑 ⑯ 注释里那段"两种解释"的现测）
--   (a) terminal 写按 run 归属后落在第几轮 ⇒ 现测应 = 全在 turn1（813 条）、turn≥2 = 0
--   (b) 这些 terminal 写所归属的 run 里，有多少条**零审计行** ⇒ 现测 = 0（⇒ 该面能区分 run 成败，不是恒黏第一轮）
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%'
), runs as (
  select thread_id, tk, min((c2.ts)::timestamptz) as first_seen
  from (select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' tk, checkpoint->>'ts' ts
        from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%') c2
  group by 1,2
), rn as (
  select thread_id, tk, first_seen, row_number() over (partition by thread_id order by first_seen) as turn from runs
), term_runs as (
  select distinct c.tk from lg.checkpoint_writes w join ck c
    on c.checkpoint_id = w.checkpoint_id and c.thread_id = w.thread_id and w.channel = 'terminal'
       and split_part(w.task_path, ', ', 2) <> '__start__'
)
select '⑯b 全库 terminal 写的 run 归属' as k,
       r.turn as turn_of_terminal_write, count(*) as runs,
       count(*) filter (where a.task_id is null) as zero_audit_row_runs
from term_runs t join rn r on r.tk = t.tk left join app.audit_log a on a.task_id = t.tk
group by 1,2 order by 2;

-- ⑰ ★ U-129 验收「三格并报」里我这面负责的 **格2 / 格3**（架构 `3b697de`/`505c243` 已把形状写进 `07 §4.8`；W4 `e8e7a62`/`fbd8512` 建议换形状，我采纳）
--   格1 = ⑮ 两臂（本件里已有，不动）；**格2 = `t2` 里「被路由进 `audit_supp` ∧ 本轮自己没写 terminal」的 run 数 ⇒ 期望 0，pre-fix 基线 5**；
--   格3 = `t2` 里「本轮自己有 terminal 写」的 run 数 ⇒ 期望 ≥1，pre-fix 基线 0，**窗内没有 turn≥2 样本时记 `n/a`、不许记 0**（架构明令，本件用 verdict 列把这条做成语句而不是注释）。
--   ⇒ 为什么格2 比格3 稳（W4 的话，我复算同意）：格2 用**手上已有的 5 条**就能出"修复前后差"，格3 要求窗口里恰好有走到 `complete` 的第 2 轮 ⇒ 取样依赖强。
-- 🔻 本轮同时把我 ⑯ 的两处过窄句钉死（三家逮到）：
--   · 被路由到 `audit_supp` 的全库真值 = **75 条 run**（turn1 **70** + turn≥2 **5**）；写面 distinct thread = **70**、写行数 = **75** ⇒ **"70"是 thread 数、不是 run 数**，"全在 turn1"更是错的。
--     ⚠️ 根因形状 = **同一个名词在两个粒度上是两个数**（与我此前登记的"谓词/分母/面"同族第四种：**粒度**：run vs thread）。⇒ 报数句固定成「数 + 面 + 谓词 + 分母 + **粒度**」。
--   · 路由集**不是**"每行都能连到 run"：现测 `branch:to:%` = **8,482 行**，能连到带 `tk_` 检查点的 = **7,164 行**、连不上 = **1,318 行**（W6 `d2b7920` 报的 1,318 我这面逐字复现 ✓）。
--     🔴 **机制我这面查出来了**（W6 标的是"机制未查"）：**1,318 行里有 1,317 行的 `checkpoint_id` 早于该 thread 第一个带 `tk_` 的检查点** ⇒ 那是**"建线期"的路由行、不属于任何 run**，不是 run 覆盖损失；
--         剩下 **1 行**的 thread **完全没有带 `tk_` 的检查点**（`⑰b` 现测：建线期 1,317 + 无 tk thread 1 = 1,318，两类都**不是 run 覆盖损失**）。
--       ⚠️ 那条未被路由行触到的 run（`tk_435227…`）**不属于**上面这一类：它的 thread 有 11 条写行、其中 1 条路由行落在**建线期**检查点上，而该 run 自己那唯一 1 个带 `tk_` 的检查点**没有任何写行** ⇒ 「run 起过、一次都没被路由」= 09-19 的早期单检查点样本。
--     ⇒ 覆盖面正解：**被路由行触到的 tk run = 1,377 / 1,378**（缺的 1 条 = `tk_435227f534da42478bc6ed3475bcc68b`，`T_A:u_c32:ss_8c3fdb…`，turn1、只有 **1** 个检查点、无审计行、09-19 06:21:07Z）。
--   ★ 顺带给 W4 欠架构的那条「run 边界契约定义」一份**证据**（不是定义，定义归她）：候选 = 「**该 thread 上第一个带 `tk_` 的检查点行 = 本轮开始**」；
--     现测支持它 = 每 thread 恰有一条更早的路由行（1,317/1,318），所以**按"检查点数 = run 数"或"首条写行 = 首条 run"这类写法都会 off-by-one**；⚠️ 边界：我只量了路由行的时间形状，**没有**证明 subgraph/`checkpoint_ns` 维度上无例外（本测里 `checkpoint_id` 在 `checkpoints` 全部存在、0 行悬空）。
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2,3
), run_first as (select thread_id, tk, min(first_seen) as first_seen from ck group by 1,2),
seq as (
  select rf.thread_id, rf.tk, rf.first_seen, split_part(rf.thread_id, ':', 2) as usr,
         row_number() over (partition by rf.thread_id order by rf.first_seen) as turn,
         (a.task_id is not null) as has_row
  from run_first rf left join app.audit_log a on a.task_id = rf.tk
), scoped as (
  select * from seq
  where first_seen between :'win_a'::timestamptz and :'win_b'::timestamptz
    and usr like :'upref'
), w as (
  select c.tk,
         bool_or(w2.channel = 'terminal' and split_part(w2.task_path, ', ', 2) <> '__start__') as wrote_terminal,
         bool_or(w2.channel = 'branch:to:audit_supp') as routed_audit_supp
  from ck c join lg.checkpoint_writes w2 on w2.checkpoint_id = c.checkpoint_id and w2.thread_id = c.thread_id
  group by 1
), j as (
  select s.tk, s.turn, coalesce(w.wrote_terminal,false) as wrote_terminal,
         coalesce(w.routed_audit_supp,false) as routed_audit_supp
  from scoped s left join w on w.tk = s.tk
), agg as (
  select count(*) as runs_in_scope,
         count(*) filter (where turn >= 2) as t2_runs,
         count(*) filter (where turn >= 2 and routed_audit_supp and not wrote_terminal) as ge2_routed_supp_no_terminal_write,
         count(*) filter (where turn >= 2 and routed_audit_supp) as t2_routed_supp,
         count(*) filter (where turn >= 2 and wrote_terminal) as ge3_t2_with_terminal_write
  from j
), shape as (  -- 🔴 T-23（2026-10-02，W8）：⑱ 的**两条形状约定必须在同一语句里被消费** ⇒ "shape_ok = f 时读数作废"不再是散文。
  --   尺与 ⑱ 逐字同源（同表、同谓词、同两个式子）；本 CTE 只出三个数，判定词表在下面两个 verdict 里。
  select (count(*) filter (where position(', ' in task_path) = 0) = 0
          and count(*) filter (where split_part(task_path, ', ', 2) <> '__start__' and task_path ~ '__start__') = 0) as shape_ok,
         count(*) filter (where position(', ' in task_path) = 0) as g1_no_delim,
         count(*) filter (where split_part(task_path, ', ', 2) <> '__start__' and task_path ~ '__start__') as g2_start_outside_seg2
  from lg.checkpoint_writes where channel = 'terminal'
)
-- 🔻 T-22（2026-10-02，W8）：下面这一行是**混合域**作用域（pre-fix 的崩臂与 post-fix 的新格同框）
--   ⇒ 它的 `ge2 = 5` **既不得读成"未达成"也不得读成"回归"**，正解 = 该作用域不含可判样本；分域并报见紧随其后的 **⑰c**。
-- 🔴 T-23：两个 verdict 的第一支 = `not shape.shape_ok ⇒ 不可判`；且 `shape_ok`／`g1`／`g2` 三列**与本行同框输出**
--   ⇒ 读者拿不到守卫位就拿不到判定词（判定与判据输入不可分离，与 `U-129` 行末"第四件前置"同一手法）。
select '⑰ U-129 格2/格3（分母=run，粒度=run）' as k, agg.runs_in_scope, agg.t2_runs,
       case when agg.runs_in_scope = 0 then null else agg.ge2_routed_supp_no_terminal_write end as ge2_routed_supp_no_terminal_write,
       case when agg.runs_in_scope = 0 or agg.t2_runs = 0 then null
            else agg.ge3_t2_with_terminal_write end as ge3_t2_with_terminal_write,
       case when not shape.shape_ok then '不可判__shape_guard_failed（⑱ 两条形状约定有一条变了 ⇒ wrote_terminal 系读数一律作废，含本行与 ⑰c）'
            when agg.runs_in_scope = 0 then 'NULL__scope_empty（无从判定）'
            when agg.t2_runs = 0 then 'n/a__窗内没有 turn>=2 样本（不许记 0）'
            when agg.ge3_t2_with_terminal_write >= 1 then 'ge3 达成（>=1）'
            else 'ge3 = 0 ⇒ 未达成，或"写面黏性"那一支未解' end as ge3_verdict,
       case when not shape.shape_ok then '不可判__shape_guard_failed（同上）'
            when agg.runs_in_scope = 0 then null
            when agg.t2_routed_supp = 0 then 'n/a__格2 空真（窗内 turn>=2 无一条被路由进 audit_supp ⇒ 架构 v1.7.17 的第四件前置 t2_routed_supp > 0 不满足，不许记 0）'
            when agg.ge2_routed_supp_no_terminal_write = 0 then 'ge2 = 0 且 t2_routed_supp = ' || agg.t2_routed_supp || ' ⇒ 非空真达成'
            else 'ge2 = ' || agg.ge2_routed_supp_no_terminal_write || ' ⇒ **本行不作判（混合域）**：作用域含 pre-fix 存量（A 档子窗 4 / 全库 5）⇒ 三态只许读 ⑰c 的分域行，post_fix 那一行才是验收位且须带 t2_routed_supp 的 n' end as ge2_verdict,
       (agg.runs_in_scope = 0) as scope_empty__if_true_suspect_vars,
       case when agg.runs_in_scope = 0 then null else agg.t2_routed_supp end as t2_routed_supp__ge2_第四件前置,
       shape.shape_ok as shape_ok__T23, shape.g1_no_delim as g1_no_delim__want_0, shape.g2_start_outside_seg2 as g2_start_outside_seg2__want_0
from agg, shape;

-- ⑰b 覆盖面与"建线期"行的形状（不受窗口限定，用来支撑 ⑰ 注释里那三句）
with ck_all as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk, (checkpoint->>'ts')::timestamptz as ts
  from lg.checkpoints
), ck_tk as (select * from ck_all where tk like 'tk_%'),
tf as (select thread_id, min(ts) as first_tk from ck_tk group by 1),
rt as (select thread_id, checkpoint_id from lg.checkpoint_writes where channel like 'branch:to:%'),
unm as (
  select r.thread_id, r.checkpoint_id, a.ts
  from rt r left join ck_tk c on c.checkpoint_id = r.checkpoint_id and c.thread_id = r.thread_id
  left join ck_all a on a.checkpoint_id = r.checkpoint_id and a.thread_id = r.thread_id
  where c.checkpoint_id is null
)
select '⑰b 路由行归属形状（全库）' as k,
       (select count(*) from rt) as route_rows,
       (select count(*) from ck_tk) as tk_checkpoint_rows,
       (select count(distinct tk) from ck_tk) as tk_runs,
       (select count(*) from unm) as route_unmatched_rows,
       (select count(distinct thread_id) from unm) as route_unmatched_threads,
       count(*) filter (where u.ts < tf.first_tk) as unmatched_before_first_tk,
       count(*) filter (where u.ts >= tf.first_tk) as unmatched_at_or_after_first_tk,
       count(distinct u.thread_id) filter (where u.ts >= tf.first_tk) as threads_with_late_unmatched
from unm u join tf on tf.thread_id = u.thread_id;

-- ⑰c ★ 格2／格3 **分域并报**（T-22，2026-10-02 W8；粒度 = run，分母 = 全库带 `tk_` 的检查点组，作用域 = 全库）
--   要有这一格的原因：⑰ 那一行是**混合域**，把"修法前存量的 5 条崩臂"和"修法后的新格"算进同一个数 ⇒ 三态无从判。
--   🔴 **分域依据 = 日期代理**（run 首见 ts 与修法落地时刻 `2026-09-30T14:25:35+00`（`33675b9`）比），**不是构建身份**；
--      严格分域依赖闸门输入的 rev 自报（= **T-11②**，本窗仍欠）⇒ 在那之前本格的标签只许写到"日期代理"，不得写成"按被测构建分域"。
--   🔻 **措辞降格（2026-10-02 第 3 轮，采 QA 第 3 轮 ③）**：下面 B 那一栏**不是"第二把独立尺"**——现测 t2 run 只落在
--      09-19(15)／09-28(8)／09-29(38)／10-01(3)，**09-30 与 10-02 各 0 条** ⇒ 边界常量 `09-30 14:25:35Z` 正落在**无样本间隙**里，
--      A 域与 B 域当期**必然同值**（不是"两把尺互相印证"）。⇒ B 的作用改名为**分布可见性**：它给出"哪些天有 t2 但 supp = 0"，
--      这一维 A 尺看不到（真值 09-19 15 条、09-28 8 条、09-29 38 条里 supp 分别 = 0/0/5）。**等 T-11② 的 rev 落地，分域才算独立。**
--   期望读法：**`pre_fix` 那一行的 ge2 是存量不是回归；`post_fix` 那一行的 ge2 = 0 才当验收位，且必须带 `t2_routed_supp` 的 n**（n = 1 ⇒ 单样本，不得升格成"率"）。
--   🔴 T-23：`verdict__T23` 的第一支 = `not shape_ok ⇒ 不可判` ⇒ ⑱ 的守卫位一旦翻，本表**逐行自动降级**，不靠人记得。
with ck as (
  select thread_id, checkpoint_id, checkpoint->'channel_values'->>'task_id' as tk,
         min((checkpoint->>'ts')::timestamptz) as first_seen
  from lg.checkpoints where checkpoint->'channel_values'->>'task_id' like 'tk_%' group by 1,2,3
), run_first as ( select thread_id, tk, min(first_seen) as first_seen from ck group by 1,2 ),
seq as ( select thread_id, tk, first_seen,
                row_number() over (partition by thread_id order by first_seen) as turn
         from run_first ),
wr as ( select c.tk,
               bool_or(w.channel = 'terminal' and split_part(w.task_path, ', ', 2) <> '__start__') as wrote,
               bool_or(w.channel = 'branch:to:audit_supp') as supp
        from ck c join lg.checkpoint_writes w on w.checkpoint_id = c.checkpoint_id and w.thread_id = c.thread_id
        group by 1 ),
j as ( select s.tk, s.turn, s.first_seen, coalesce(w.wrote,false) as wrote, coalesce(w.supp,false) as supp
       from seq s left join wr w on w.tk = s.tk ),
shape as (  -- 尺与 ⑱ 逐字同源；只在最外层消费一次 ⇒ 判定词表只有一份抄本
  select (count(*) filter (where position(', ' in task_path) = 0) = 0
          and count(*) filter (where split_part(task_path, ', ', 2) <> '__start__' and task_path ~ '__start__') = 0) as shape_ok,
         count(*) filter (where position(', ' in task_path) = 0) as g1_no_delim,
         count(*) filter (where split_part(task_path, ', ', 2) <> '__start__' and task_path ~ '__start__') as g2_start_outside_seg2
  from lg.checkpoint_writes where channel = 'terminal'
), rows_ as (
  select 'A 按修法时刻（日期代理，非构建身份）' as domain_ruler,
         case when first_seen < timestamptz '2026-09-30 14:25:35+00' then 'pre_fix' else 'post_fix' end as domain,
         count(*) filter (where turn >= 2) as t2_runs,
         count(*) filter (where turn >= 2 and supp) as t2_routed_supp__n,
         count(*) filter (where turn >= 2 and supp and not wrote) as ge2_routed_supp_no_terminal_write,
         count(*) filter (where turn >= 2 and wrote) as ge3_t2_with_terminal_write
  from j group by 1, 2
  union all
  select 'B 按日（分布可见性，当期与 A 必然同值）', date_trunc('day', first_seen)::date::text,
         count(*) filter (where turn >= 2),
         count(*) filter (where turn >= 2 and supp),
         count(*) filter (where turn >= 2 and supp and not wrote),
         count(*) filter (where turn >= 2 and wrote)
  from j group by 1, 2
)
select '⑰c 分域并报' as k, r.domain_ruler, r.domain, r.t2_runs, r.t2_routed_supp__n,
       r.ge2_routed_supp_no_terminal_write, r.ge3_t2_with_terminal_write,
       s.shape_ok as shape_ok__T23, s.g1_no_delim as g1_no_delim__want_0, s.g2_start_outside_seg2 as g2_start_outside_seg2__want_0,
       case when not s.shape_ok then '不可判__shape_guard_failed（⑱ 两条形状约定有一条变了 ⇒ 本表与 ⑰/⑮/⑯ 的 wrote_terminal 系读数一律作废）'
            when r.t2_routed_supp__n = 0 then 'n/a__该域空真（无被路由进 audit_supp 的 turn>=2 run ⇒ 第四件前置 t2_routed_supp > 0 不满足，不许记 0）'
            when r.ge2_routed_supp_no_terminal_write = 0 then '非空真达成（ge2 = 0 且 n = ' || r.t2_routed_supp__n || ' ⇒ 引这格必须同框带 n）'
            else '未达成（ge2 = ' || r.ge2_routed_supp_no_terminal_write || '，n = ' || r.t2_routed_supp__n || '）' end as verdict__T23
from rows_ r, shape s order by 2, 3;

-- ⑱ ★ 形状守卫（T-21，2026-10-02 W8）：排除式 `split_part(task_path, ', ', 2) <> '__start__'` 的正当性**全靠两条形状约定**，
--   而在本行落地之前**没有任何一件器件守它们** —— 建在这两条之上的谓词共 **8 处**：本件 `:491/:539/:577`、
--   `backend/reports/w4/probe_prod_checkpoint_terminal.sql:157/189/220/253`、`backend/reports/w6/probe_audit_invariant.py:516`
--   🔻 **同轮订正（第 3 轮 22:2x 现读，W8；原文不删）**：上面那句"共 8 处"是**本窗第 2 轮的尺**，此后我自己新加了 3 个消费面
--   （本件 **666**、w4 **348**、w6 **535**）⇒ 现读 = **11 处**（`grep -c` 现算，别抄这行）。行号本身也会随追加漂移。
--   ⇒ 守卫只放这一处（不三处各抄一份，避免第三份真相）；另两处只写指针，见各自件内注记。
--   两条各配一个"若变则怎么坏"的方向（**两个方向都是假绿**，这是本号最怕的形状）：
--     **守卫 1** 不含 `', '` 分隔符的 terminal 行 **必须 = 0** ⇒ 若 > 0：`split_part(…, ', ', 2)` 返回**空串** ⇒ `'' <> '__start__'` **恒真**
--                ⇒ 入口复位写行被算成"本轮自写终态" = 格3 假绿（**静默失效，零报错**）。
--     **守卫 2** 含字面 `__start__` 但**不在第 2 段**的 terminal 行 **必须 = 0** ⇒ 若 > 0：**漏排** ⇒ 同一形状的假绿。
--   ⚠️ 三条写法义务（本窗现测得出，不是推论）：**①** 守卫一律用 `position(', ' in …) = 0` 与**正则** `task_path ~ '__start__'`，
--     **不得用 `like '%__start__%'`**（LIKE 的 `_` 是单字符通配 ⇒ 形状过宽；正则没有这个毛病）；
--     **② 不得拿 `type is not null` 当挡** —— 现测 `__start__` 那 6 行的 `type` 存的是**字符串 `'null'`**（`type = 'null'::text` 命中 **6**、`type is null` 命中 **0**；
--     psql `-t -A` 下真 NULL 显示为空串，所以那一列印出来的 `null` 是值不是空）；
--     **③ 三态联动**：`shape_ok = f` 时，本件 ⑮/⑯/⑯b/⑰/⑰c 的 `wrote_terminal` 系读数**一律不引用**（不是"重新解释"，是作废）。
--     🔻 **同轮升格（第 3 轮，T-23）**：上面 ③ 原本只是散文 ⇒ 现在 **⑰ 与 ⑰c 的 verdict 在第一支就消费 `shape_ok`**（同语句内的 `shape` CTE，尺与本行逐字同源），
--     守卫翻 ⇒ 判定词自动变 `不可判__shape_guard_failed`；反证（注入让 g1 变非 0、看 verdict 真翻）见 `backend/reports/w8/RELAY.md` §三 ＋ 一次性容器 `w8-t23-neg`。
select '⑱ 形状守卫（排除式的正当性前提）' as k,
       count(*) as terminal_rows,
       count(*) filter (where position(', ' in task_path) = 0) as g1_no_delim__want_0,
       count(*) filter (where split_part(task_path, ', ', 2) <> '__start__' and task_path ~ '__start__') as g2_start_outside_seg2__want_0,
       count(*) filter (where split_part(task_path, ', ', 2) = '__start__') as start_rows_excluded,
       count(distinct split_part(task_path, ', ', 2)) as seg2_node_kinds,
       count(*) filter (where split_part(task_path, ', ', 2) = '__start__' and type = 'null'::text) as start_rows_with_literal_null_type,
       (count(*) filter (where position(', ' in task_path) = 0) = 0
        and count(*) filter (where split_part(task_path, ', ', 2) <> '__start__' and task_path ~ '__start__') = 0) as shape_ok
from lg.checkpoint_writes where channel = 'terminal';
