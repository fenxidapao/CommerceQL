-- 用 cost_ledger 给每个 user 的 run 排"第几轮"（审计面 0 行的那 4 条也能定轮 ⇒ 与审计面互补）
with runs as (
  select task_id, user_id, min(created_at) as t0
  from app.cost_ledger
  where user_id like 'u_f%' and user_id <> 'u_f00'
  group by 1, 2
), ranked as (
  select task_id, user_id, t0,
         row_number() over (partition by user_id order by t0) as turn
  from runs
)
select r.turn,
       count(*) as runs,
       count(*) filter (where a.task_id is null) as no_audit_row,
       count(*) filter (where a.outcome = 'failed' and not (a.latency_ms ? 'gen_sql')) as shallow_failed,
       count(*) filter (where a.outcome = 'failed' and (a.latency_ms ? 'gen_sql')) as deep_failed,
       count(*) filter (where a.outcome = 'success') as ok,
       count(*) filter (where a.outcome = 'refuse') as refuse,
       count(*) filter (where a.outcome = 'clarify') as clarify
from ranked r
left join app.audit_log a using (task_id)
group by 1
order by 1;

-- 四条"0 审计行"的 run 各在第几轮（崩溃臂）
with runs as (
  select task_id, user_id, min(created_at) as t0
  from app.cost_ledger
  where user_id like 'u_f%'
  group by 1, 2
), ranked as (
  select task_id, user_id, t0,
         row_number() over (partition by user_id order by t0) as turn
  from runs
)
select r.task_id, r.user_id, r.turn, r.t0
from ranked r
where r.task_id in ('tk_6a1a6c029be7427cb41c7dac2ce736e1',
                    'tk_a1e54c1d5d8c49bb8cd7117703020f45',
                    'tk_9f575a098ecf4ac6be50649f20a18b23',
                    'tk_398fa097c589466ba6b61c35a2b633cb')
order by r.turn;
