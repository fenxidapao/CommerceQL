"""离线自证第 4 步的两个探测器（零额度、零服务、零网络）：四格双向。

⚠️ 为什么格 1 要拆成 1a/1b（W4 `3188a9c` 第 ③ 条的账）：
   上一版格 1 的两帧**都不含** `blocking_issues` ⇒ 它只证明"器件会响"，没证明
   "PLAN 自拒后静默复用"那一格会被响到。1a 就是把那一格摆上桌：第 1 轮带 `blocking_issues`、
   第 2 轮（复用臂）不带 ⇒ **原始帧不等、剥完的指纹相等**。
   ⇒ 断言"原始帧不等"是这条剥键规则的**承重件**：一旦 `blocking_issues` 被移出逐轮键，1a 当场红。
"""

import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location(
    "probe_mod", "E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL/deploy/loadtest/probe_session_owner_context.py"
)
m = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["probe_mod"] = m
spec.loader.exec_module(m)


def _raw(frame: dict | None) -> str:
    return json.dumps(frame or {}, ensure_ascii=False, sort_keys=True)


# ---- 格 1a：PLAN 自拒后的静默复用（`blocking_issues` 只在第 1 轮出现）----
t1_block = ('event: ack\ndata: {"task_id":"tk_1","session_id":"s"}\n\n'
            'event: stage\ndata: {"terminal":false,"stage":"intent"}\n\n'
            'event: refuse\ndata: {"terminal":true,"reason":"plan_blocked",'
            '"message":"缺指标口径","blocking_issues":["找不到 GMV 口径"]}\n\n')
t2_reuse_noblock = ('event: ack\ndata: {"task_id":"tk_2","session_id":"s"}\n\n'
                    'event: refuse\ndata: {"terminal":true,"reason":"plan_blocked","message":"缺指标口径"}\n\n')
a1, a2 = m._terminal_frame(t1_block), m._terminal_frame(t2_reuse_noblock)
print("格1a 原始帧相等 =", _raw(a1) == _raw(a2), "| 剥键后指纹相等 =", m._frame_digest(a1) == m._frame_digest(a2))
assert _raw(a1) != _raw(a2), "格 1a 没造出差异 ⇒ 这条自证不承重（两帧必须本来就长得不一样）"
assert "blocking_issues" in (a1 or {}) and "blocking_issues" not in (a2 or {}), "格 1a 的键不对称写错了"
assert m._frame_digest(a1) == m._frame_digest(a2), "PLAN 自拒复用臂没被判出（该格必须响）"
assert bool(a2) and not m._sse_names(t2_reuse_noblock)["stages_seen"], "格 1a 的零 stage 没被判出"

# ---- 格 1b：对称复用臂（两轮都带同一个 `blocking_issues`）----
t2_reuse_block = ('event: ack\ndata: {"task_id":"tk_3","session_id":"s"}\n\n'
                  'event: refuse\ndata: {"terminal":true,"reason":"plan_blocked","message":"缺指标口径",'
                  '"blocking_issues":["找不到 GMV 口径"]}\n\n')
b2 = m._terminal_frame(t2_reuse_block)
print("格1b 对称复用: 指纹相等 =", m._frame_digest(b2) == m._frame_digest(a1),
      "| 键集合差 =", sorted(set(a1) ^ set(b2)))
assert m._frame_digest(b2) == m._frame_digest(a1)
assert sorted(set(a1) ^ set(b2)) == [], "对称臂不该有键差"

# ---- 格 2：正常臂（跑过节点、结论不同）⇒ 两个都必须 False（双向卡，防"恒真探测器"）----
turn2_normal = ('event: ack\ndata: {"task_id":"tk_4","session_id":"s"}\n\n'
                'event: stage\ndata: {"terminal":false,"stage":"intent"}\n\n'
                'event: stage\ndata: {"terminal":false,"stage":"plan_ready"}\n\n'
                'event: clarify\ndata: {"terminal":true,"reason":"time_ambiguous","message":"请补充时间范围"}\n\n')
g = m._terminal_frame(turn2_normal)
same_n = m._frame_digest(g) == m._frame_digest(a1)
no_stage_n = bool(g) and not m._sse_names(turn2_normal)["stages_seen"]
print("格2 正常臂: digest 相同 =", same_n, "| 终止帧但本轮无 stage 帧 =", no_stage_n)
assert same_n is False, "正常臂被误判成复用（探测器恒真 = 装饰品）"
assert no_stage_n is False, "正常臂被误判成零 stage"

# ---- 格 3：崩溃臂（error(INTERNAL) + 零 stage）⇒ 零 stage True、digest 不等于第 1 轮 ----
turn2_crash = ('event: ack\ndata: {"task_id":"tk_5","session_id":"s"}\n\n'
               'event: error\ndata: {"terminal":true,"code":"INTERNAL","message":"内部错误"}\n\n')
c = m._terminal_frame(turn2_crash)
print("格3 崩溃臂: digest 相同 =", m._frame_digest(c) == m._frame_digest(a1),
      "| 零 stage =", bool(c) and not m._sse_names(turn2_crash)["stages_seen"])
assert m._frame_digest(c) != m._frame_digest(a1)
assert (bool(c) and not m._sse_names(turn2_crash)["stages_seen"]) is True

# ---- 承重件自检：被剥的键必须真的在剥（否则 1a 的"指纹相等"是假的）----
assert "blocking_issues" in m._VOLATILE_FRAME_KEYS, "blocking_issues 已不在逐轮键里 ⇒ W4 那一格会重新漏掉"
print("逐轮键 =", m._VOLATILE_FRAME_KEYS)
print("OFFLINE PROBE SELF-TEST OK（4 格双向 + 剥键承重件）")
