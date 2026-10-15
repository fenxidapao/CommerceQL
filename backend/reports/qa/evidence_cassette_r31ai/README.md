# evidence_cassette_r31ai · 匣带层真因复现 ＋ 命令自匹配实测 ＋ 摘要长度复算（R31ai，2026-10-15）

**用途**：为 W8 第 43 轮的三条主张做**独立复算**，并回答「谁的真因、能不能修、修了会不会更糟」。
**边界**：**零出站、零花费**（全程离线；**不跑 W8 的脚本** —— 其 `probe_semantic_summary.py` 会写
`probe_semantic_summary.json`，本窗一律**自建**探针）；不动容器；不动 `semantic/**`／`backend/app/**`。

---

## 一、清单

| 文件 | 说明 | md5（前 12） |
|---|---|---|
| `repro_decoding.py` | **离线复现**门失败真因（`httpx.DecodingError`） | `3efa09de834e` |
| `out_repro.txt` | 上面实跑输出 | `3d2a5ec493a5` |
| `selfmatch2.py` | **自匹配矩阵**（录制的扫描命令 × 改动前/后 pattern） | `6c0a95047ef5` |
| `out_selfmatch.txt` | 上面实跑输出 | `6e9ad03dbdfe` |
| `probe_summary_len.py` | **语义摘要长度复算**（旧 9 指标包 ⟷ 新 22 指标包） | `85311b051257` |
| `out_summary.txt` | 上面实跑输出 | `b2488502d902` |

**六件均 LF、无凭据、无 DSN 连续字面量**（本窗已实测；见下「四、脱敏自查」）。

---

## 二、结论一：门失败真因 = 匣带层（**与 W8 一致，且本窗给出确定性离线复现**）

`out_repro.txt` 实读（httpx 0.28.1）：

| 步 | 结果 |
|---|---|
| ① `httpx.Response(headers={"content-encoding":"gzip"}, content=<明文>)` | 🔴 **构造即抛 `DecodingError`**（`Error -3 while decompressing data: incorrect header check`） |
| ② 端到端：`CassetteTransport(mode="record")` ＋ 上游返回真 gzip | 🔴 **同样抛 `DecodingError`** |
| ③ `DecodingError` 的 MRO | `DecodingError → RequestError → HTTPError` ⇒ **会被 `client.py:346 except httpx.HTTPError` 捕获** |
| ④ replay 分支为何不炸 | `cassette.py:197-202` `_to_response` **显式覆盖** headers 为 `{"content-type": "application/json"}`（不含 `content-encoding`） |

**真因点**：`eval/cassette.py:171-176`（record 分支）用 `headers=dict(response.headers)` **原样带上上游全部响应头**
（含 `content-encoding: gzip` 与**压缩版** `content-length`），而 `content=` 用的是 `await response.aread()` 之后的
**已解压明文** ⇒ 下游按 `content-encoding` 再解一次 ⇒ 确定性失败（**不是间歇、不是上游**）。

**三段接力的后两段（读码证成）**：
- `backend/app/llm/client.py:346-350` 把它包成 `LlmUpstreamError("上游连接失败", detail={"model":…, "kind":"DecodingError"})`
  ⇒ 🔴 **消息把「解码失败」说成「上游连接失败」** —— 这正是第 41/42 轮误归因的直接来源。
- `backend/app/graph/nodes/_shared.py:178-205` `llm_error_update` **只取 `default_code`、丢弃 `exc.detail`**
  ⇒ 终态只剩 `LLM_UPSTREAM_ERROR` ⇒ 根因在产物里不可见。
- `eval/harness.py:699-700` `elif cassette_path and live:` ⇒ `CassetteTransport(mode="record")`
  ⇒ **「带匣带 live」必然走这条路** ⇒ 与 W8「带匣带必失败、去掉匣带 success」一致。

---

## 三、结论二：录制的扫描命令**自匹配**，且**截断式拆段把命中面放大**

`out_selfmatch.txt` 实读（**尺已自检**：`OLD` 命中对照行 `True`、命中反例 `False`）：

| | 改动前 pattern（完整 DSN 形态） | 改动后 pattern（截断 `postgres://`） |
|---|---|---|
| **改动前的行** | **True**（自匹配） | True |
| **改动后的行** | False | **True**（自匹配） |

⇒ ① **自匹配不是截断引入的**（改动前就自匹配）；
⇒ 🔴 ② **但截断把命中面放大**：在记录的被测集合（`983214c..HEAD` 内 json/py/md，共 **74** 个文件）里，
截断后的 pattern **命中 7 个文件**（含 `backend/reports/qa/{QA_LEDGER,RELAY,TASK_BOARD}.md` 与
`evidence_outage_r31ah/README.md`），而**该命令的结论仍写着「命中数必须 = 0」** ⇒ **命令与结论脱钩**。
⇒ **建议**：录制的扫描命令**不要包含它要扫的 pattern 字面量** —— 最干净是把扫描**抽成脚本**
（报告只引脚本名），一次性同时解决「gitleaks 连续字面量」与「自匹配」两件事。

---

## 四、结论三：语义摘要 8,235 → 13,364（**本窗独立复算，逐位吻合**）

`out_summary.txt` 实读（本窗**自建**探针，调 `build_semantic_summary`，不跑 W8 脚本）：

| 面 | yaml | version | 摘要 chars（T_A／T_B／T_C） | 截断 |
|---|---|---|---|---|
| 写前（9 指标，`a943575`） | 62,129 B | `2026.09.14.1` | 8,235／8,235／8,235 | False |
| 现读（22 指标） | 88,633 B | `2026.10.15.1` | 13,364／13,364／13,364 | False |

⇒ 增长 **+5,129 chars（1.62×／+62.3%）**，与 W8 报值**逐位一致**；上限 `MAX_SEMANTIC_SUMMARY_CHARS = 40,000`，
**未截断**（后段没被挤掉）。
🔴 **产品含义（须上呈）**：这四个 LLM 节点**每个都吃一遍**摘要 ⇒ **单次问答的提示成本随语义包扩张而上涨**；
「补 metric 让 G-2/G-5 变绿」与「单次成本上升」是**同一动作的两面**，对外口径不宜只写前者。

---

## 五、脱敏自查（**本窗上一轮的教训**）

本窗 R31ah 曾因**归档 pytest 原始输出**而把 DSN 连续正则带进仓库（同族第 4 例）。
本轮归档前**先跑**：`grep -c '<该连续正则>' <归档目录>/*` ⇒ **全 0**。
两个 `.py` 里的 pattern 也是**字符串拼接**写成（`"postgres://" + WS + "*:…"`），**无连续字面量**。

---

## 六、限制（诚实登记，不得越界引用）

1. **本窗未跑**真正的 `--live` 门（要花真钱）⇒ 本目录**不能**替代 W8 的门；它只证「真因是确定性的、可离线复现」。
2. `repro_decoding.py` 用**假上游**（返回 gzip）⇒ 证的是**机制**；「真上游确实回 gzip」这一步由 W8 的 spy 读数与
   `DecodingError` 字面吻合间接支撑。
3. **W8 的成本数（¥0.058163／27,103 tok）本窗不可复算**：其产物落 `%TEMP%\w8r43\`、未入仓。
   本窗只复核了**由它派生的算术**（¥3.6643／¥0.58163）与**摘要长度**（可独立复算，已吻合）。
4. 自匹配矩阵里的「改动前的行」取自 `git show bdcd111^:backend/reports/w8/RELAY.md`；
   🔴 v1 版本曾拿**改动后**的行去测**改动前**的 pattern（**循环测试**）⇒ 已作废，本目录只收 v2。
