-- T-23 反证对照件 = r23 的 ⑰ 语句在 **接线之前**（rev 2ae0b43）的逐字抽取件（T-27，2026-10-03）。
--
-- 抽取规则（可复算，不手抄）：取 2ae0b43 的 deploy/loadtest/r23_thread_from_checkpoints.sql，
--   按标记 ⑰ U-129 回溯到最近的『with 』起始行、前进到第一个以分号结尾的行。
--   本件正文（去掉本注释头）的 sha256 = 97335ae24196a0072a05c5a95552696537f999e24752cbe63cce3700d04b2b55
--
-- 为什么把一份旧版本入库、而不在 CI 里 git show：actions/checkout 默认 fetch-depth=1，
--   CI 结构上没有 2ae0b43 这个对象 ⇒ 门禁会在 CI 里恒取不到对照。入库件是主来源；
--   deploy/loadtest/t23_negative_gate.py 在**有历史**的环境里额外做一次 git 校验（无历史记 UNVERIFIED，不红）。
--
-- ⚠️ 绝不得对共享 ecom 执行：本件与夹具同库跑（一次性容器）。它只读数，但它数的是夹具注入的坏形状。
-- 期望（两件事同时成立才算 ⑱ 真的进了判定量）：
--   本件（pre-fix）在注入件上给出**假绿** ge2_verdict = 非空真达成；
--   当前版（post-T-23）在同一份注入件上给出 不可判__shape_guard_failed。

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
)
-- 🔻 T-22（2026-10-02，W8）：下面这一行是**混合域**作用域（pre-fix 的崩臂与 post-fix 的新格同框）
--   ⇒ 它的 `ge2 = 5` **既不得读成"未达成"也不得读成"回归"**，正解 = 该作用域不含可判样本；分域并报见紧随其后的 **⑰c**。
select '⑰ U-129 格2/格3（分母=run，粒度=run）' as k, agg.runs_in_scope, agg.t2_runs,
       case when agg.runs_in_scope = 0 then null else agg.ge2_routed_supp_no_terminal_write end as ge2_routed_supp_no_terminal_write,
       case when agg.runs_in_scope = 0 or agg.t2_runs = 0 then null
            else agg.ge3_t2_with_terminal_write end as ge3_t2_with_terminal_write,
       case when agg.runs_in_scope = 0 then 'NULL__scope_empty（无从判定）'
            when agg.t2_runs = 0 then 'n/a__窗内没有 turn>=2 样本（不许记 0）'
            when agg.ge3_t2_with_terminal_write >= 1 then 'ge3 达成（>=1）'
            else 'ge3 = 0 ⇒ 未达成，或"写面黏性"那一支未解' end as ge3_verdict,
       case when agg.runs_in_scope = 0 then null
            when agg.t2_routed_supp = 0 then 'n/a__格2 空真（窗内 turn>=2 无一条被路由进 audit_supp ⇒ 架构 v1.7.17 的第四件前置 t2_routed_supp > 0 不满足，不许记 0）'
            when agg.ge2_routed_supp_no_terminal_write = 0 then 'ge2 = 0 且 t2_routed_supp = ' || agg.t2_routed_supp || ' ⇒ 非空真达成'
            else 'ge2 = ' || agg.ge2_routed_supp_no_terminal_write || ' ⇒ **本行不作判（混合域）**：作用域含 pre-fix 存量（A 档子窗 4 / 全库 5）⇒ 三态只许读 ⑰c 的分域行，post_fix 那一行才是验收位且须带 t2_routed_supp 的 n' end as ge2_verdict,
       (agg.runs_in_scope = 0) as scope_empty__if_true_suspect_vars,
       case when agg.runs_in_scope = 0 then null else agg.t2_routed_supp end as t2_routed_supp__ge2_第四件前置
from agg;
