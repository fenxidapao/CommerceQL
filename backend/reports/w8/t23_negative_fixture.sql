-- T-23 反证夹具（一次性容器专用；**绝不得对共享 `ecom` 执行**）
-- 目的：证明 `deploy/loadtest/r23_thread_from_checkpoints.sql` 的 ⑰／⑰c 判定词**真的消费了** ⑱ 的 `shape_ok`，
--       而不是"加了列但没进判定量"（本项目登记过的形状）。
-- 注入内容：一条 `channel='terminal'` 且 `task_path` **不含 `', '`** 的写行 ⇒ 守卫 1（g1）变非 0 ⇒ `shape_ok = f`；
--          同时这一行按排除式会被判成"该 run 自己写了终态"（`split_part('bogus_path_without_delim', ', ', 2)` = 空串 ≠ `__start__`）
--          ⇒ **这正是假绿本身**：未接守卫的旧版会给「非空真达成」，接了守卫的新版必须给「不可判__shape_guard_failed」。
--
-- 复算（零额度、零 LLM、Git Bash）：
--   cd CommerceQL
--   docker run -d --name w8-t23-neg -p 127.0.0.1:55441:5432 -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=ecom_neg pgvector/pgvector:pg16
--   docker exec -i w8-t23-neg psql -U postgres -d ecom_neg -f - < backend/reports/w8/t23_negative_fixture.sql
--   # 从件里**逐字抽**语句（不手抄）：按标记回溯到最近的 `with ` 行、前进到第一个 `;` 行
--   PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "
--   import pathlib
--   def grab(text, marker, out):
--       ls=text.split('\n'); i=next(k for k,l in enumerate(ls) if marker in l)
--       a=i
--       while not ls[a].lstrip().startswith('with '): a-=1
--       b=i
--       while not ls[b].rstrip().endswith(';'): b+=1
--       pathlib.Path(out).write_text('\n'.join(ls[a:b+1]), encoding='utf-8')
--   cur=pathlib.Path('deploy/loadtest/r23_thread_from_checkpoints.sql').read_text(encoding='utf-8')
--   grab(cur, chr(9328)+' U-129', 'E:/tmp_qoder/g17_new.sql'); grab(cur, chr(9328)+'c 分域并报", 'E:/tmp_qoder/g17c_new.sql')
--   "
--   docker exec -i w8-t23-neg psql -U postgres -d ecom_neg -t -A -F '|' -v "win_a=2020-01-01 00:00:00+00" -v "win_b=2120-01-01 00:00:00+00" -v "upref=%" -f - < E:/tmp_qoder/g17_new.sql
--   docker exec -i w8-t23-neg psql -U postgres -d ecom_neg -t -A -F '|' -f - < E:/tmp_qoder/g17c_new.sql
--   # 对照"接线之前"的同一件（同库、同参，只换件版本）：
--   git show 2ae0b43:deploy/loadtest/r23_thread_from_checkpoints.sql > E:/tmp_qoder/r23_pre_T23.sql   # 再对 E:/tmp_qoder/r23_pre_T23.sql 做同样的抽取
--   docker stop w8-t23-neg && docker rm w8-t23-neg        # 删的是**容器**（用完即删）；本夹具件本身入库留证，不删
--
-- 现测结果（2026-10-02 20:1x，容器 `w8-t23-neg`／端口 55441／库 `ecom_neg`，rc 均 0）：
--   ⑰ 旧版（`2ae0b43`）：`ge2 = 0 且 t2_routed_supp = 1 ⇒ 非空真达成`   ← **假绿被复现**
--   ⑰ 新版（本件）    ：`不可判__shape_guard_failed（…wrote_terminal 系读数一律作废，含本行与 ⑰c）`
--   ⑰c 新版          ：四行（A 两域 ＋ B 两天）**全部** 不可判，`shape_ok = f`、`g1 = 1`、`g2 = 0`
--   ⑱ 新版           ：terminal_rows 2／g1 1／g2 0／被排 0／段 2 节点种数 2／`shape_ok = f`

create schema if not exists lg;
create schema if not exists app;
drop table if exists lg.checkpoints;
drop table if exists lg.checkpoint_writes;
drop table if exists app.audit_log;
create table lg.checkpoints(thread_id text, checkpoint_id text, checkpoint jsonb);
create table lg.checkpoint_writes(thread_id text, checkpoint_id text, channel text, task_path text, type text);
create table app.audit_log(task_id text);

-- run1 = 修法前、正常写终态；run2 = 修法后、被路由进 audit_supp，其"终态写"是**没有分隔符的坏形状**
insert into lg.checkpoints values
 ('T_A:u_z01:s1','cp1', jsonb_build_object('ts','2026-09-20T01:00:00+00','channel_values', jsonb_build_object('task_id','tk_run1'))),
 ('T_A:u_z01:s1','cp2', jsonb_build_object('ts','2026-10-01T01:00:00+00','channel_values', jsonb_build_object('task_id','tk_run2')));
insert into lg.checkpoint_writes values
 ('T_A:u_z01:s1','cp1','terminal','~__pregel_pull, refuse_out','null'),
 ('T_A:u_z01:s1','cp2','branch:to:audit_supp','~__pregel_pull, plan','null'),
 ('T_A:u_z01:s1','cp2','terminal','bogus_path_without_delim','null');
insert into app.audit_log values ('tk_run1');

-- 注入自检（这一行必须 = 1；报 0 说明夹具没建起来，而不是"守卫没响"）
select 'fixture_g1_rows__want_1' as k, count(*) as n
from lg.checkpoint_writes where channel = 'terminal' and position(', ' in task_path) = 0;
