# B5 反查扫描产物 · 归档件（R31t）

> 归档现读：**2026-10-14 10:23 ＋0800** ｜ 起点 HEAD **`485cce3`／524 笔** ｜ 🔴 归档动作零出站
> 上游：`../evidence_a_table_r31e/`（机械尺）／下游：判定件 `../A_TABLE_VERDICT.md §九`（B5）＋ `§十`（**A 表 pass 收口**）

## 1. 本目录文件

| 文件 | 说明 |
|---|---|
| `grade_b5.py` | B5 分档扫描器：33 条 × **机制符号词** → 去重到测试文件级 |
| `b5_grade.json` | 逐条 `n_s2`／`n_test_files`／`grade`／逐词命中数 |

## 2. 🔴 两条已登记的产物瑕疵（复算前必读）

1. **脚本 `ITEMS` 含 34 条，多跑 `FR-11.4`**（它属 B3 批次，已于 R31r 判 B 档）⇒ 末行 `分档统计` 是 **34 条**的统计，**B5 正文按 33 条重述**。`FR-11.4` 判定**以 B3 为准**。
2. **`S3-弱` 的唯一条目（`FR-10.3`）是蹭词**：命中的 `test_auth_chain.py:652 test_step7_create_task_inherits_context` 讲的是 **JWT 上下文继承**，与「条件继承」语义无关 ⇒ 正文把它**降判为 C 档（弱）**。

## 3. B5 特点（写给复算者）

本批主体是 **NFR**（性能/可用性/持久化/合规）。这类需求的载体**不在单一功能点**，而在：
- **分阶段埋点键**（如 `LatencyKey.GEN_SQL`，`core/enums.py:813`）
- **降级机制**（如 `TEMPLATE_ONLY`／`LLM_UNAVAILABLE`）
- **守卫常量与契约测试**
⇒ 反查词必须取**机制符号**，取 NFR 名（"可用性""延迟"）会**全零**（本窗首轮即踩）。

## 4. 复算

```
CommerceQL/.venv/Scripts/python.exe backend/reports/qa/evidence_a_table_r31t/grade_b5.py
# 期望末行：分档统计 = {'S3-实质': 30, 'S3-无': 3, 'S3-弱': 1}   ← 34 条口径，见 §2-1
```
