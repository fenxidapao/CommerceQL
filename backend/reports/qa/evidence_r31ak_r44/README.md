# R31ak W8 第 44 轮 replay 反证

- 归档时刻：2026-10-16 11:02:05 +0800
- 命令：`.venv/Scripts/python.exe eval/runner.py --cases E-VER-01,E-VER-02,E-VER-03,E-VER-04,E-VER-05 --mode replay --cassette eval/cassettes/w8_r44_a3.jsonl --out <temp> --yes --provenance "QA R31ak 独立 replay 复算（零出站）"`
- 结果：`complete 4 / refuse 1`、`tokens=124011`、`n_equivalent=3`、`cost_cny_total=0.107013`。
- 对照：W8 录制的非峰时成本为 `0.053505`；差异 `2.0000x`，来自 replay 当前峰时重新计价。
- 本目录只读引用；未改 W8 产物。
