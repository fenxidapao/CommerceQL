# backend/reports —— 当前证据索引（2026-10-24 整理后）

> 本目录只保留**当前真相链**需要的证据。旧窗口报告已移到仓库外 `../../CommerceQL-archive/reports/`；
> 当前进展与门禁仍以 `OVERVIEW.md §6/§7` 为准。

## 1. 当前真相的读取顺序

1. **`qa/TASK_BOARD.md` 末节** —— 最新一轮验收结论（本件只追加，当期永远在最后一节）；
2. **`w8/DELIVERY.md` 终版节** —— 对外最终口径（6 PASS＋2 UNVERIFIED 的逐格说明）；
3. **`w8/OFFICIAL_SNAPSHOT_DECISION.md`** —— 官方快照 `88f3500` 为何不刷新、何时才允许刷新；
4. **`w6/eval_metrics.json`** —— 官方门禁快照（自报 `88f3500`／PASS 1/8，**非当期读数**）；
5. **`../OVERVIEW.md §6/§7`** —— 入口摘要（两套读数同框）。

## 2. 目录

| 目录 | 定位 | 读什么 |
|---|---|---|
| `w8/` | 当期（集成收尾窗） | `DELIVERY.md` 终版节、`OFFICIAL_SNAPSHOT_DECISION.md`、`RELAY.md`、当期证据 |
| `qa/` | 当期（验收窗） | `TASK_BOARD.md` 末节、`QA_LEDGER.md` 最新条目、`RELAY.md` |
| `w6/` | 当期（官方快照） | `eval_metrics.json`、`评测报告与门禁判定.md`、G-1 日志与探针 |

## 3. 历史窗口报告在哪

`w0`、`w1a`、`w1b`、`w2a`–`w2d`、`w2-int`、`w3a`–`w3c`、`w3-int`、`w4`、`w5`、`w7`、`arch`、`t-a1` 已整体移到：

```
CommerceQL-archive\reports\      （与本仓库同级，不在仓库内）
```

它们是**史料**，只读、不得引作当期依据。需要查阅或被旧文档引用时，在**仓库根**执行恢复：

```powershell
powershell -ExecutionPolicy Bypass -File ..\CommerceQL-archive\restore-evidence.ps1 -What reports -WhatIf
powershell -ExecutionPolicy Bypass -File ..\CommerceQL-archive\restore-evidence.ps1 -What reports
```

## 4. 怎么读追加型文件

`TASK_BOARD.md`、`RELAY.md` 只追加、不插入正文，**当期永远在最后一节**；不要整读：

```bash
F=backend/reports/qa/TASK_BOARD.md; N=$(grep -n '^## ' "$F" | tail -1 | cut -d: -f1); sed -n "${N},\$p" "$F"
F=backend/reports/qa/RELAY.md;      N=$(grep -n '^## ' "$F" | tail -1 | cut -d: -f1); sed -n "${N},\$p" "$F"
```

两条已踩过的坑：

- **导航头会滞后**：文件顶部的“现读末节 / 行数”是上一次手工更新的快照，可能落后于末节实际位置；以 `grep '^## '` 现读为准。
- **行号会漂移**：插入新节会让后面所有行号下移；引用只用“行首串 + 现读行号”两格，禁止只写行号。

## 5. 根目录的两类遗留件

- `.w8r59-git-scan.json`、`.w8r59-worktree-scan.json`：W59 的 gitleaks 原始扫描件（命中值已 `REDACTED`）。聚合读数见 `eval/results_r59_secret_scan_final.json`（该文件已随旧结果移至 archive）；原始件被 `w8/RELAY.md` 引用，保留不删。
- `../W1A_HANDOVER.md`：2026-09-16 的 W1A 交接，历史件；被 `docs/07` 引用，保留不删。

## 6. 维护约定

- 新轮次只**追加末节**并更新文件顶部导航头；不改历史正文、不改 `qa/QA_LEDGER.md` 的既有判据行。
- 跨窗引用先写“哪一件、哪一节、哪一行首串”，再写现读行号；不把某一轮的数字写成“当前”。
- 本目录不写真实密钥；扫描件中的命中值必须保持脱敏。
