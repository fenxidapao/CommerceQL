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

-- ⚠️ EXPLAIN 不打印计数 ⇒ 只有 ① 的话，"三件套"里可比的那个数是缺的。
-- 这里沿用 ① 的并行设置直接打印数值，好与 ③ 的串行计数在**同一快照**里相减。
\echo '=== ①b 同一快照内的并行**数值**计数（与 ③ 串行计数直接可比） ==='
select '并行(v_order_paid)' as probe, count(*) from app.v_order_paid;

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

-- ----------------------------------------------------------------------------
-- ④ 生产注入形态：**显式设值**之后，worker 到底读不读得到
--    这一格回答的是"生产里 GUC 由 `app/exec` 注入，会不会也少算"。
--    ⚠️ 必须放在最后：它会改会话态，先跑会污染 ③ 的"串行 = 真值"对照。
--    与生产一致的三点：`is_local = true`（事务级，§16.3 复用连接后会被 reset 掉）、
--    值是**真实店铺列表**（不是 `''` 也不是哨兵 `'*'`）、以 `app_rw` 身份读视图。
-- ----------------------------------------------------------------------------
\echo '=== ④ 生产形态（显式 set_config LOCAL）：每进程取值 + 并行计数是否等于 ③ 串行真值 ==='
reset role;                                        -- 取列表要属主视角（RLS 下 app_rw 此刻看得见 0 行）
select string_agg(distinct shop_id, ',') as t_a_shops
  from app.order_paid where tenant_id = 'T_A';
\gset
set role app_rw;
select set_config('app.shop_ids', :'t_a_shops', true);

select case when t.tenant_id is not null
            then coalesce(current_setting('app.shop_ids', true), '<NULL-in-this-process>')
            else '<unreachable>'
       end as value_seen_by_the_scanning_process,
       count(*) as rows_carrying_it
  from app.traffic_daily t group by 1 order by 1;

set max_parallel_workers_per_gather to 2;
explain (analyze, verbose, costs off, timing off, buffers off)
  select count(*) from app.v_order_paid;
select '并行(v_order_paid, 显式设值)' as probe, count(*) from app.v_order_paid;

commit;

-- ----------------------------------------------------------------------------
-- ⑤ **对称**清除态（= W6 第三条读数："同一把连接 commit 后再复用"）
--    生产的注入是**一条语句里三个 `set_config(..., true)`**（`app/repo/dsn.py:141-145`
--    + `app/exec/executor.py:284-290`），所以 commit 之后三个键**一起**回到占位符 `''`
--    （`RESET` 是这条路径的等价 stand-in，理由见本文件头部注释）。
--    这一栏要回答：对称清除会不会也少算？（预测 **不会** —— `tenant_id=''` 连 Index Cond 都过不去，
--    worker 压根没有行可丢 ⇒ 干净 0 行。少算需要的是**非对称**态：租户有值、shop_ids 是占位符。）
-- ----------------------------------------------------------------------------
\echo '=== ⑤ 对称清除（两个身份 GUC 同为占位符）：并行计数是否 = 0（干净）而非随机 ==='
reset app.tenant_id;
reset app.shop_ids;
select 'leader 侧两键' as probe,
       coalesce(current_setting('app.tenant_id', true), '<NULL>') || ' / '
         || coalesce(current_setting('app.shop_ids', true), '<NULL>') as v;
set max_parallel_workers_per_gather to 2;
explain (analyze, verbose, costs off, timing off, buffers off)
  select count(*) from app.v_order_paid;
select '并行(对称清除后)' as probe, count(*) from app.v_order_paid;

-- ----------------------------------------------------------------------------
-- 判读（把结果对着这两条读，别只贴数）
--   · 若 ② 只出现一个值组且值是 `''`      ⇒ **worker 看得见值** ⇒ 本窗口的
--     "占位符不传给 worker"这条解释**作废**，得另找机制（这正是 W6 报的形状，需被确认）。
--   · 若 ② 出现 `<NULL-in-this-process>` ⇒ worker 取到 NULL，机制成立；
--     再对 ②b 的 `Worker 0/1: actual rows=0` 与 ① 的 `Worker 0: actual rows=0` 互相印证。
--   · ⓪ 的 `Workers Launched = 0` ⇒ **整轮作废**（没并行可谈），把 traffic 表加大或提高
--     `min_parallel_*` 之前先别下任何结论。
--   · **关闭判据（架构 v1.5 要的"同源三件套"里可比的那个数）**：①b 与 ③ 在同一快照内相减。
--     不等 ⇒ 少算成立，且 ② 的 `<NULL-in-this-process>` 那一格给出机制。
--     相等 ⇒ **不得判"没问题"** —— 掉几行取决于哪几个进程抢到哪些块，是随机的；
--     本文件跑一次只算一个样本，要多跑几轮再看。
--   · ④（生产形态）三条**同时**成立才算"显式设值安全"：
--     取值分布只有**一个**值组、其值 = 注入的店铺列表；`并行(显式设值)` = ③ 串行 200,000；
--     且 ④ 的 EXPLAIN 里 `Workers Launched ≥ 1`（少了这条，相等只是没并行，废话）。
--     ⇒ 成立则 R-17 的影响面精确等于"会话从未设过该键 / 被清成 `''` 占位符"这一族，
--       **不包含**正常请求路径（`app/exec` 每事务注入）。
-- ============================================================================
