# eval —— 评测执行器与当前证据索引（2026-10-24 整理后）

> 判据措辞的权威在 `docs/07 §17.3`；官方门禁快照在 `backend/reports/w6/eval_metrics.json`
>（`88f3500`／PASS 1/8）；当期复算在 `results_w80_gate_recompute.json`（**不是**官方快照）。两数必须同框。

## 1. 仓库内保留什么

| 内容 | 说明 |
|---|---|
| `*.py`（46 个） | 执行器：`runner.py`、`reporter.py`、`gates.py`、`harness.py`、`redteam_eval.py`、`cassette.py`、`pg_guard.py`，以及各轮一次性诊断脚本 |
| `dataset_v1_frozen.json` | 冻结评测集（166 题）；**不可改** |
| `gold_query_seed_v1.json` | 金标查询种子；**不可改** |
| `red_team_cases_v1.json` | 红队用例集；**不可改** |
| `MANIFEST_v1.json` | 数据集清单与哈希 |
| `cassettes/` | **只留 2 个**：`w6_batch.jsonl`（14M，ACCEPTANCE 引用）、`w8_r44_a3.jsonl`（453K，文档引用） |
| `results_*.json` | **只留当期 15 个**：`results_w77_*`、`results_w78_*`、`results_w79_*`、`results_w80_*` |
| `results_w80_offline_pytest.junit.xml` | 当期离线测试面 |

## 2. 当期权威产物（引用只认这一组）

- `results_w80_final_audit.json` —— 八格逐格 verdict / evidence path / git_rev / dirty / fresh / 复算命令 / “什么会改变判定”；
- `results_w80_gate_recompute.json` —— 当期复算 **6 PASS／0 PARTIAL／2 UNVERIFIED／0 FAIL**（rev `26421ae`）；
- `results_w80_redteam.json`、`results_w80_redteam_tail.json` —— 红队与尾巴归类；
- `results_w80_offline_pytest.junit.xml` —— 离线测试面；
- `results_w79_blockers.json` —— G-6／G-8 阻塞输入；
- `results_w78_integration.json` —— 集成层证据；
- `results_w77_g8_answer_gap.json` —— G-8 补答缺口。

## 3. 历史产物在哪

旧轮次的 `results_r*`、`results_w7*`、`results_v1*`、`results_v2*`、`results_replay*` 等，以及其余 138 个 cassette（另 1 个 manifest），已移到：

```
..\CommerceQL-archive\evidence\results\
..\CommerceQL-archive\evidence\cassettes\
```

需要复算某一旧轮次时，先恢复（`-WhatIf` 预览）：

```powershell
powershell -ExecutionPolicy Bypass -File ..\CommerceQL-archive\restore-evidence.ps1 -What cassettes -WhatIf
powershell -ExecutionPolicy Bypass -File ..\CommerceQL-archive\restore-evidence.ps1 -What results -WhatIf
```

历史引用按原路径保留；找不到时去 archive 对应目录。

## 4. 复算与回放

```bash
# 参数以各自的 --help 为权威；不要抄死命令
.venv/Scripts/python.exe eval/runner.py --help
.venv/Scripts/python.exe eval/reporter.py --help
.venv/Scripts/python.exe eval/w80_gate_recompute.py --help
```

- **回放（cassette）零 LLM、零出站**：当前只带 2 个匣带；旧批回放先从 archive 恢复。
- **live 跑批会花钱**：没有预算批准不要跑 live；G-6 的压测另有 ¥40+ 预算与容量前提（见 `backend/reports/w8/DELIVERY.md` 终版节的阻塞表）。
- **G-1 的输入是未跟踪 `.log`**（`backend/reports/**/_*.log`，被 `.gitignore` 忽略）：异地 clone 只带入库件时，G-1 会读作 `NOT_AVAILABLE`，不能宣称“拷仓库就能重跑 G-1”。

## 5. 纪律

- 冻结集、金标、红队用例、门禁阈值与判据措辞**不因调试或整理而改动**；要改先走 `docs/07 §4.8` 取号与裁定。
- 产物是证据，不手改；需要修正读数时新生成一件并在 `backend/reports/w8/RELAY.md` 记录命令、rev、时刻。
- 不在本目录写任何真实密钥或明文 DSN。
