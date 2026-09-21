-- ============================================================================
-- `U-110` 关闭证据（并入 `U-109`）：同一 run、同一快照里凑齐架构要的"三件套"
--   ① RLS qual 落在哪个执行节点          ② 每个进程实际读到的 app.shop_ids 值
--   ③ leader 侧计数（串行 = 真值对照）
--
-- 归属：W7（`deploy/**`）。**只读**：不写任何业务表、不改策略文本、不改 PG 配置。
--
-- 为什么要有这个文件（而不是在聊天里报三个数）：
--   本窗口在这个问题上已经交过两次不成立的证据 ——
--   第一次用 `RESET` 在同一条连接里"清场"，而 PG 对**从未设过**的自定义 GUC 做 RESET 会留下
--   值为 `''` 的占位符（不是 NULL）⇒ 我量的那一格被自己的准备动作改掉了；
--   第二次用"投影 + group by"读 worker 取值，而 `pg_backend_pid()` / `current_setting()` 这类
--   **不含列引用**的表达式可以被规划器放到 Gather **之上**求值 ⇒ 看到的永远是 leader 的值。
--   ⇒ ② 这一栏被刻意做成**不能提升**的形状（见下面的注释），并要求先证明 `Workers Launched ≥ 1`。
--
-- 用法（两种角色路径都该跑一遍；W6 已实测两条等价）：
--   docker exec -i commerceql-pg-1 psql -U postgres -d ecom -f - < deploy/loadtest/rls_parallel_evidence.sql
--   # 直接以 app_ro 登录时，把下面的 `set role app_rw;` 改成 `-- (app_ro 直接登录：跳过 set role)`
-- ⚠️ 必须在**没有其它并发写**的窗口跑（③ 的属主真值与 ① 的计数要在同一快照里可比）。
-- ============================================================================

\set ON_ERROR_STOP on
\pset footer off

set role app_rw;                                   -- 视图属主、FORCE ROW LEVEL SECURITY 对它生效、非超级用户
select set_config('app.tenant_id', 'T_A', false);
reset app.shop_ids;                                -- ★ 进入"占位符"那一格（不是显式设值）

select 'state' as section,
       coalesce(current_setting('app.shop_ids', true), '<NULL>') as shop_ids_seen_in_leader,
       current_setting('app.shop_ids', true) is null as is_null_in_leader;

-- 全部取证在同一个 REPEATABLE READ 快照内完成 ⇒ 三件套之间不存在 cross-run 差
begin isolation level repeatable read;

-- ----------------------------------------------------------------------------
-- ⓪ 先证明"并行真的发生了"，否则后面所有"没差异"都是废话
-- ----------------------------------------------------------------------------
\echo '=== ⓪ 计划里必须真有 Gather 且 Workers Launched >= 1（否则 ② 无意义） ==='
explain (analyze, verbose, costs off, timing off, buffers off)
  select count(*) from app.traffic_daily;

-- ----------------------------------------------------------------------------
-- ① RLS qual 落在哪一层 + 每个进程留了几行
--    期望（本窗口先前独立测到、W6 也复现到的形状）：
--      `Filter: (current_setting('app.shop_ids') = '' OR shop_id = ANY(...))` 挂在
--      **Parallel Index Only Scan** 上（不是 One-Time Filter，因为它含逐行比较），
--      且 `Worker 0: actual rows=0`。
-- ----------------------------------------------------------------------------
\echo '=== ① 失败查询的 RLS qual 落层 + 每进程留行（并行开） ==='
set max_parallel_workers_per_gather to 2;
explain (analyze, verbose, costs off, timing off, buffers off)
  select count(*) from app.v_order_paid;

-- ----------------------------------------------------------------------------
-- ② 每个进程实际读到的值 —— **不能提升**的形状
--    为什么写成 `group by 1` 且表达式里带列引用（`t.tenant_id is not null`）：
--    表达式若不含列引用，规划器可以把它放在 Gather 之上、由 leader 一次算完
--    （本窗口就是这样被骗过一次的：`Output:` 里 `(pg_backend_pid() = 0), current_setting(...)`
--    出现在 GroupAggregate 上，而 Parallel Scan 的 Output 只有索引两列）。
--    带上列引用 ⇒ 只能在扫到那一行时就地求值 ⇒ 谁扫的行就带谁进程里的值。
--    选 `traffic_daily` 是刻意的：它的策略**只有租户条件** ⇒ worker 不会掉行 ⇒
--    这一栏与 ① 不构成循环论证（在 v_order_paid 上测必然只看到 leader 的值）。
-- ----------------------------------------------------------------------------
\echo '=== ② worker 侧实际取值（含列引用 ⇒ 不可提升；表：只有租户条件的 traffic_daily） ==='
select case when t.tenant_id is not null
            then coalesce(current_setting('app.shop_ids', true), '<NULL-in-this-process>')
            else '<unreachable>'
       end as value_seen_by_the_scanning_process,
       count(*) as rows_carrying_it
  from app.traffic_daily t
 group by 1
 order by 1;

-- 同一状态、同一键，做成**能提升**的形状 —— 两条放一起才叫"证据"而不是"猜测"
\echo '=== ②b 同一状态同一个键，纯 GUC 谓词（会被提升成 One-Time Filter）的留行情况 ==='
explain (analyze, verbose, costs off, timing off, buffers off)
  select count(*) from app.traffic_daily t
   where current_setting('app.shop_ids', true) = '';

-- ----------------------------------------------------------------------------
-- ③ leader 侧真值对照：同一快照内的串行计数 + 绕开 RLS 的属主计数
-- ----------------------------------------------------------------------------
\echo '=== ③ 同一快照内：串行 count / 属主绕 RLS count / 并行 count 三者对照 ==='
set max_parallel_workers_per_gather to 0;
select '串行(v_order_paid, app_rw 视角)' as probe, count(*) from app.v_order_paid;
reset role;
select '属主真值(绕 RLS, T_A)' as probe, count(*) from app.order_paid where tenant_id = 'T_A';
set role app_rw;
select 'n_live_tup(并发写没写动的旁证)' as probe,
       (select n_live_tup from pg_stat_user_tables where schemaname = 'app' and relname = 'order_paid');

commit;

-- ----------------------------------------------------------------------------
-- 判读（把结果对着这两条读，别只贴数）
--   · 若 ② 只出现一个值组且值是 `''`      ⇒ **worker 看得见值** ⇒ 本窗口的
--     "占位符不传给 worker"这条解释**作废**，得另找机制（这正是 W6 报的形状，需被确认）。
--   · 若 ② 出现 `<NULL-in-this-process>` ⇒ worker 取到 NULL，机制成立；
--     再对 ②b 的 `Worker 0/1: actual rows=0` 与 ① 的 `Worker 0: actual rows=0` 互相印证。
--   · ⓪ 的 `Workers Launched = 0` ⇒ **整轮作废**（没并行可谈），把 traffic 表加大或提高
--     `min_parallel_*` 之前先别下任何结论。
-- ============================================================================
