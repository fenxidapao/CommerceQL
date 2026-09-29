"""离线自证新增的两个探测器（零额度、零服务）：纯函数双向两格。"""

import importlib.util
import sys

spec = importlib.util.spec_from_file_location(
    "probe_mod", "E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL/deploy/loadtest/probe_session_owner_context.py"
)
m = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["probe_mod"] = m
spec.loader.exec_module(m)

# 格 1：第 2 轮复用第 1 轮的 refuse 结论（只有 ack + 终止帧，没有任何 stage 帧；task_id 不同）
turn1 = ('event: ack\ndata: {"task_id":"tk_1","session_id":"s"}\n\n'
         'event: stage\ndata: {"terminal":false,"stage":"intent"}\n\n'
         'event: refuse\ndata: {"terminal":true,"reason":"no_data_asset","message":"没有可用数据资产"}\n\n')
turn2_reuse = ('event: ack\ndata: {"task_id":"tk_2","session_id":"s"}\n\n'
               'event: refuse\ndata: {"terminal":true,"reason":"no_data_asset","message":"没有可用数据资产"}\n\n')

f1, f2 = m._terminal_frame(turn1), m._terminal_frame(turn2_reuse)
same = m._frame_digest(f1) == m._frame_digest(f2)
no_stage = bool(f2) and not m._sse_names(turn2_reuse)["stages_seen"]
print("格1 复用臂: digest 相同 =", same, "| 终止帧但本轮无 stage 帧 =", no_stage)
assert same is True, "复用臂没被判出（digest 应相等）"
assert no_stage is True, "复用臂的'零 stage'没被判出"

# 格 2：正常臂（跑过节点、结论不同）⇒ 两个都必须 False（双向卡，防"恒真探测器"）
turn2_normal = ('event: ack\ndata: {"task_id":"tk_3","session_id":"s"}\n\n'
                'event: stage\ndata: {"terminal":false,"stage":"intent"}\n\n'
                'event: stage\ndata: {"terminal":false,"stage":"plan_ready"}\n\n'
                'event: clarify\ndata: {"terminal":true,"reason":"time_ambiguous","message":"请补充时间范围"}\n\n')
g = m._terminal_frame(turn2_normal)
same_n = m._frame_digest(g) == m._frame_digest(f1)
no_stage_n = bool(g) and not m._sse_names(turn2_normal)["stages_seen"]
print("格2 正常臂: digest 相同 =", same_n, "| 终止帧但本轮无 stage 帧 =", no_stage_n)
assert same_n is False, "正常臂被误判成复用（探测器恒真 = 装饰品）"
assert no_stage_n is False, "正常臂被误判成零 stage"

# 格 3：崩溃臂（error(INTERNAL) + 零 stage）⇒ 零 stage 应为 True、digest 不应等于第 1 轮
turn2_crash = ('event: ack\ndata: {"task_id":"tk_4","session_id":"s"}\n\n'
               'event: error\ndata: {"terminal":true,"code":"INTERNAL","message":"内部错误"}\n\n')
c = m._terminal_frame(turn2_crash)
print("格3 崩溃臂: digest 相同 =", m._frame_digest(c) == m._frame_digest(f1),
      "| 零 stage =", bool(c) and not m._sse_names(turn2_crash)["stages_seen"])
assert m._frame_digest(c) != m._frame_digest(f1)
assert (bool(c) and not m._sse_names(turn2_crash)["stages_seen"]) is True
print("OFFLINE PROBE SELF-TEST OK（3 格双向）")
