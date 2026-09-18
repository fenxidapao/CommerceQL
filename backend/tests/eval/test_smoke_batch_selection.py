"""W6 冒烟批的**取题规则**（`backend/reports/w6/select_smoke_batch.py`）。

为什么一个"选题脚本"要进 CI：
    报告里的 EX / 拒答率 / 澄清率全部来自这 20 条。若选题规则能随人意换一批题，
    那这些百分比就不是可复算的读数，而是选题偏置的读数（§C.6.1 纪律一）。
    所以这里钉四件事：
      ① 同一份冻结集复跑得到**同一组 id**（确定性）；
      ② execute 的四个结构难度**每层都有题**（否则 G-2 的某格永远是 0/0）；
      ③ refuse / clarify 两类都保底（否则 G-5、G-8 的前半句永远 NOT_AVAILABLE）；
      ④ 已落盘的 `smoke_batch_ids.json` 与**当前规则**重算的结果一致
         （防止"产物里是那 20 条、代码已经改成另外 20 条"这种两份真相）。
"""

from __future__ import annotations

import importlib.util
import json
import os

import pytest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)  # backend/tests/eval -> tests -> backend -> CommerceQL
SCRIPT = os.path.join(REPO_ROOT, "backend", "reports", "w6", "select_smoke_batch.py")
ARTIFACT = os.path.join(REPO_ROOT, "backend", "reports", "w6", "smoke_batch_ids.json")


@pytest.fixture(scope="module")
def sel():
    spec = importlib.util.spec_from_file_location("select_smoke_batch", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def selected_ids(sel, dataset_cases) -> list[str]:
    return [str(c["case_id"]) for c in sel.pick(dataset_cases)]


def test_pick_is_deterministic(sel, dataset_cases):
    assert [str(c["case_id"]) for c in sel.pick(dataset_cases)] == (
        [str(c["case_id"]) for c in sel.pick(dataset_cases)]
    ), "换一次调用就换一批题 ⇒ 报告里的百分比不可复算"


def test_quota_and_no_invented_ids(sel, dataset_cases, selected_ids):
    ids = {str(c["case_id"]) for c in dataset_cases}
    assert set(selected_ids) <= ids, "选出了冻结集里不存在的题号"
    assert len(selected_ids) == sum(sel.QUOTA.values()) == 20
    assert len(set(selected_ids)) == len(selected_ids)


def test_execute_covers_every_struct_stratum(sel, dataset_cases, selected_ids):
    """G-2 判的是 `easy×low` 格 —— 该格没样本时门禁只能 NOT_AVAILABLE，白跑一批真钱。"""
    by_id = {str(c["case_id"]): c for c in dataset_cases}
    picked = [by_id[i] for i in selected_ids]
    struct = {str(c["difficulty_struct"]) for c in picked if c["expected_behavior"] == "execute"}
    all_struct = {str(c["difficulty_struct"]) for c in dataset_cases
                  if c["expected_behavior"] == "execute"}
    assert struct == all_struct == {"easy", "medium", "hard", "extra"}
    behav = {str(c["expected_behavior"]) for c in picked}
    assert behav == {"execute", "refuse", "clarify"}, "缺 refuse ⇒ G-5；缺 clarify ⇒ G-8 前半句"
    easy_low = [c for c in picked
                if c["difficulty_struct"] == "easy" and c["difficulty_semantic"] == "low"]
    assert easy_low, "easy×low 一条都没有 ⇒ G-2 无法判定"


def test_committed_artifact_matches_the_rule(sel, dataset_cases, selected_ids):
    assert os.path.exists(ARTIFACT), "选题产物缺失 ⇒ 报告里的批次构成无从核对"
    with open(ARTIFACT, encoding="utf-8") as fh:
        art = json.load(fh)
    assert art["case_ids"] == selected_ids, (
        "产物里的 20 条与当前规则重算的不一致 ⇒ 报告引用的批次已不可复现"
    )
    assert art["seed"] == sel.SEED and art["n_dataset_cases"] == len(dataset_cases)
