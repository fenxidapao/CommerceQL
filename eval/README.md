# eval —— 评测执行器与证据索引

> 本目录是评测与门禁的**执行器 + 产物**。判据措辞的权威在 `docs/07 §17.3`；
> 官方门禁快照在 `backend/reports/w6/eval_metrics.json`（`88f3500`／PASS 1/8）；
> 当期复算在 `results_w80_gate_recompute.json`（**不是**官方快照）。两数必须同框。

## 1. 目录里有什么

| 内容 | 说明 |
|---|---|
| `*.py`（现读 46 个） | 执行器：`runner.py`（跑批）、`reporter.py`（装配门禁报告）、`gates.py`（判定实现）、`harness.py`、`redteam_eval.py`、`cassette.py`、`pg_guard.py`，以及各轮一次性诊断脚本（`w67_*`…`w80_*`） |
| `dataset_v1_frozen.json` | 冻结评测集（166 题）；**不可改** |
| `gold_query_seed_v1.json` | 金标查询种子；**不可改** |
| `red_team_cases_v1.json` | 红队用例集；**不可改** |
| `MANIFEST_v1.json` | 数据集清单与哈希 |
| `cassettes/` | 回放匣带：141 个文件（140 个 `.jsonl` + 1 个 manifest），约 144MB；已入库 |
| `results_*.json` / `*.xml` | 各轮产物（现读 263 个 `.json`）；含当期审计链与历史轮次 |

## 2. 当期权威产物（引用只认这一组）

- `results_w80_final_audit.json` —— 八格逐格 verdict / evidence path / git_rev / dirty / fresh / 复算命令 / “什么会改变判定”；`all_checks_pass=true`；
- `results_w80_gate_recompute.json` —— 当期复算 **6 PASS／0 PARTIAL／2 UNVERIFIED／0 FAIL**（rev `26421ae`）；
- `results_w80_redteam.json`、`results_w80_redteam_tail.json` —— 红队与尾巴归类；
- `results_w80_offline_pytest.junit.xml` —— 离线测试面；
- `results_w79_blockers.json` —— G-6／G-8 阻塞输入；
- `results_w78_integration.json` —— 集成层证据；
- `results_w77_g8_answer_gap.json` —— G-8 补答缺口。

`results_r*`（现读最早 `results_r49_clean_r1.json`、最晚 `results_r75_window_delta.json`）是**历史轮次**读数，只作过程证据；引用时带“哪一轮、哪一件”，不要写成当前。
`*.checkpoint.jsonl`、`*.bak-*`、`eval/runs/`、`eval/reports/local/` 是断点/备份/本地产物，已被 `.gitignore` 忽略、可再生成。

## 3. 复算与回放

```bash
# 参数以各自的 --help 为权威；不要抄死命令
.venv/Scripts/python.exe eval/runner.py --help
.venv/Scripts/python.exe eval/reporter.py --help
.venv/Scripts/python.exe eval/w80_gate_recompute.py --help
```

- **回放（cassette）零 LLM、零出站**：同一批题可用匣带复算，适合核对逻辑与判据。
- **live 跑批会花钱**：没有预算批准不要跑 live；G-6 的压测另有 ¥40+ 预算与容量前提（见 `backend/reports/w8/DELIVERY.md` 终版节的阻塞表）。
- **G-1 的输入是未跟踪 `.log`**（`backend/reports/**/_*.log`，被 `.gitignore` 忽略）：异地 clone 只带入库件时，G-1 会读作 `NOT_AVAILABLE`，不能宣称“拷仓库就能重跑 G-1”。

## 4. 纪律

- 冻结集、金标、红队用例、门禁阈值与判据措辞**不因调试或整理而改动**；要改先走 `docs/07 §4.8` 取号与裁定。
- 产物是证据，不手改；需要修正读数时新生成一件并在 `backend/reports/w8/RELAY.md` 记录命令、rev、时刻。
- 不在本目录写任何真实密钥或明文 DSN。
