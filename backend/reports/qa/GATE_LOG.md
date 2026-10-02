# 验收窗口（QA）· GATE_LOG（每轮门禁复跑，同一轮内同 HEAD 才可两两比较）

> 规矩：`rc` 一律**不接管道**取真值（`> file 2>&1` 后读 `$?`）；`exit 0` 不等于跑完；目录级计数**必须带 HEAD**。

## 第一轮（HEAD `fd5f5f2` ｜ 2026-10-01 21:45–22:05 +0800 ｜ 本机无 U-132 阻塞、无 shim 前提）

| 门禁 | 命令形状（工作目录与解释器） | 真 rc | 读数 | 备注 |
|---|---|---|---|---|
| 全树 pytest | `cd backend` ＋ `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest -q -rfEs --continue-on-collection-errors` | **1** | **2,284 passed / 6 skipped / 10 errors / 89.97 s** | 10 errors = **7 条收集期**（缺 `COMMERCEQL_TEST_RW_DSN` 与 `_SUPER_DSN`，`U-114` 防线① 按设计 fail、明令禁止 skip）＋ **3 条 setup**（`test_retrieval_fts_pg.py` 夹具 `InsufficientPrivilege`，见 RELAY F-3） |
| 取值集自检 | `cd backend` ＋ 同解释器 `-m app.core.enums` | **0** | **rc=0**，33 项基数；`ast_rule` 20、`error_code` 28、`outcome` 5、`latency_key` 8、`degraded_reason` 8 | CI 步骤 `ci.yml:130–132`；与 W7 那句「self-check 10/10」**不是同一把尺**（本尺 = 单项命令 rc ＋ 基数项条数 33） |
| ruff（backend 整目录） | `cd backend` ＋ `../.venv/Scripts/python.exe -m ruff check --config pyproject.toml .` | **0** | **0 条**（All checks passed） | 尺 = `cd backend` 那把（与 CI `working-directory` 同形，`ci.yml:319–321`） |
| ruff（`deploy/loadtest` 整目录） | `cd backend` ＋ `… -m ruff check --config pyproject.toml ../deploy/loadtest` | **1** | **18 条**（11 可自动修） | 与 W7 `47bfdd2` 记录的「18 条真 rc=1」**同形同数** ⇒ 属 pre-existing，非本轮新增 |
| mypy | `cd backend` ＋ `… -m mypy app` | **0** | **Success: no issues found in 147 source files** | CI 步骤 `ci.yml:323–325` |
| import-linter | `cd backend` ＋ `../.venv/Scripts/lint-imports.exe` | **0** | **Contracts: 4 kept, 0 broken**（Analyzed 192 files / 1,069 dependencies） | 必须用 exe；`python -m importlinter.cli` 会**假绿**（`U-41`）；在仓库根跑会打印 `Could not read any configuration.` ＋ rc=1 |
| 远端一致性 | `git ls-remote origin main` 对 `git rev-parse HEAD` | **0** | **同点** `fd5f5f2` | 判"推上去没有"只认 `ls-remote` |
| 花钱口径 | `docker exec -i commerceql-pg-1 psql -U postgres -d ecom -t -A -F 竖线符 -c "select count(… ), round(sum(cost_cny),6), max(created_at) from app.cost_ledger;"` | **0** | **1,601 行 / ¥2.635700 / max 2026-10-01 12:56:32Z** | 与 W7 上一轮逐字相同 ⇒ 20:56 后零新增；本窗零花费 |

### 复算命令原文（可直接粘贴；日志产物本机路径 `E:/tmp_qoder/qa_r1/`，`.log`/scratch 不入库）

```bash
cd CommerceQL/backend
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m pytest -q -rfEs --continue-on-collection-errors > ../E_tmp/pytest_full.txt 2>&1; echo PYTEST_RC=$?
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m ruff check --config pyproject.toml . ; echo RUFF_RC=$?
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m ruff check --config pyproject.toml ../deploy/loadtest ; echo RUFF_LT_RC=$?
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m mypy app ; echo MYPY_RC=$?
PYTHONUTF8=1 ../.venv/Scripts/lint-imports.exe ; echo LINT_RC=$?
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 ../.venv/Scripts/python.exe -m app.core.enums ; echo ENUMS_RC=$?
```

> ⚠️ 上面第一行的 `E_tmp/` 是占位写法：本窗实际把日志写到真实盘路径 `E:/tmp_qoder/qa_r1/`（Git Bash 的 `/tmp` 不是 Windows Python 的 `/tmp`）。

---

# 第二轮（HEAD `d440ed6` ｜ 2026-10-02 16:56 +0800 ｜ 本机 `platform.machine()` 未复测 ⇒ 计时前提只对本轮内命令成立）

| 门禁 | 命令形状 | 真 rc | 读数 | 与第一轮对比（同尺） |
|---|---|---|---|---|
| 全树 pytest | 同第一轮第一行（`cd backend` ＋ `--continue-on-collection-errors`，日志落 `E:/tmp_qoder/qa_r2/`） | **1** | **2,312 passed / 0 skipped / 8 errors / 101.14 s** | passed ＋28、skipped −6、errors −2 ⇒ 与 W2B（@ `3f1c951` 给 2,289/0/8）与 W6（@ `8ffb53e` 给 2,312/0/8）**同形**；我的红法拆分独立复现 = **收集期 8、夹具期 0**（8 条 error 行全部无 `::`） |
| error 相位尺 | 对同一份日志按 `ERROR` 行的测试 id 是否含 `::` 分类计数 | 0 | **7 个模块 ＋ `test_retrieval_fts_pg.py` 1 个 = 8**，全部收集期 | 第一轮为「收集期 7 ＋ 夹具期 3」⇒ 夹具期归零 = T-02 生效的直接证据 |
| skip 归属尺 | `grep -c` 行首 `SKIPPED` | 0 | **0 条**（第一轮 6 条，全在 `test_retrieval_fts_pg.py`） | 🔻 但 `:107-108` 的权限型 skip 分支仍在 ⇒ 「skip 家族被消灭」**不成立**，只是本轮走 import 期 fail 路径（O-6） |
| 报告排版守卫 | 对 `reports/qa/**` 逐表数竖线 ＋ 找表内空行（跳过围栏块） | 0 | 第一轮五件：**0 问题、全 LF**；本轮追加后复扫见 RELAY §二.4 | 表格单元含竖线 = GFM 劈列，本窗规矩：命令里的竖线一律写成文字 |
| DSN 卫生门禁 | `cd backend` ＋ `… -m pytest -q tests/unit/test_migration_dsn_hygiene.py` | **0** | **8 passed / 6.08 s**（第一轮新件入库前实测） | 本轮追加文本含"口令等值 = True"这类**派生布尔**、未写任何 scheme／用户／口令／主机连续形态 ⇒ 复扫通过 |
| 远端一致性 | `git ls-remote origin main` 对 `git rev-parse HEAD` | 0 | 同点 `d440ed6`；`git log --grep docs(qa)` = **仅 1 笔**（`8375391`）⇒ **无重复提交**（本轮新坑：git 写操作可能被 sandbox→escalation 重跑两遍，判成立只认 `git log`／`show`／`ls-remote`，不认 stdout） | W1B 现测并上交，本窗复核自身成立 |
| 花钱口径 | 同第一轮 | 0 | **1,601 行 / ¥2.635700 / max 2026-10-01 12:56:32Z** ⇒ **与第一轮逐字同 ⇒ 10-02 全项目零新增花费** | 分档实测（供切几何，不当乘数）：非峰 1,183 调用 / ¥1.045121 ⇒ **¥0.000883 每次**；峰时 418 调用 / ¥1.590579 ⇒ **¥0.003805 每次**；两数相加 = 总量 ⇒ 反推自洽 |
| 向量完整性 | `select count(*), count(embedding is not null) from app.embed_doc` | 0 | **197 / 197** | U-114 相关跑批未损向量（独立于 W0 的旁证再量） |

---

# 第 7 轮追加（2026-10-02 · @ `8ca95cb`）

## 一、本轮门禁读数（同轮内同 HEAD 才可两两比较）

| 门禁 | 命令形状（含工作目录与解释器） | 真 `rc`（不接管道） | 读数 | HEAD | 备注 |
|---|---|---|---|---|---|
| 跨租户 RLS 行为断言 | `cd backend/` ＋ 三条 `COMMERCEQL_TEST_*_DSN` 指向 **55433 一次性库 `ecom_qa`** ＋ `../.venv/Scripts/python.exe -m pytest tests/integration/test_rls_tenant_isolation.py -q -rfEs` | **0** | **5 passed in 2.50s**（`-rfEs` 无 skip／xfail 行） | `8ca95cb` | 2.5s 反直觉 ⇒ 用**制品**自证：`alembic heads=0005 (head)`、`relrowsecurity` 表 **6**、`pg_policies` **6** |
| 同件的**反向对照** | 同上 ＋ `PYTHONPATH=E:/tmp_qoder/qa_r3/neg -p negctrl`（out-of-tree 插件注入 `coalesce(current_setting('app.shop_ids', true),'')=''`） | **1** | **1 failed ／ 4 passed** —— 红的恰是 `test_shop_ids_unset_vs_explicit_empty_is_distinguishable` | `8ca95cb` | 还原后重跑 = **5 passed ／ rc=0** ⇒ 该断言**非恒绿** |
| 我自己的独立尺 | `E:/tmp_qoder/qa_r3_own_ruler.py`（`.venv/Scripts/python.exe`，cwd=仓库根） | **0** | 未设身份 0 ／ `shop_ids` 未设 0 ／ `''` 2 ／ `'S1'` 1 ／ `'S1,S2'` 2 ／ 他租户 `''` 1；残留 0 | `8ca95cb` | 不经他们夹具；种 3 行走 SUPER、清理带 `tenant_id = ANY(...)` 谓词 |
| DoD④ 门的形状覆盖面 | `cd backend/` ＋ `../.venv/Scripts/python.exe` 载入 `tests.unit.test_migration_dsn_hygiene._dsn_rule` ＋ 合成串矩阵（用户/口令各 1–8 长度） | **0** | `postgresql+psycopg://` 需用户≥3 且口令≥3；**纯 `postgresql://` 全 0 命中** | `8ca95cb` | 全仓粗尺差量：**61 ／ 门中 24 ／ 失明 37 ／ 失明且未放行 35**；只报路径·行号·布尔 |
| 共享 `ecom` 未被写入 | `docker exec -i commerceql-pg-1 psql -U postgres -d ecom -t -A -c "select count(*) from app.embed_doc"` | **0** | **197**（本轮跑前／跑后同数） | `8ca95cb` | U-114 残余面：本窗零新增 |

## 二、⚠️ 本轮盘面出现**他窗未提交的在途改动**（影响"按 HEAD 复算"的可引用性）

| 盘面 | 读数 | 我的处置 |
|---|---|---|
| ` M deploy/loadtest/r23_thread_from_checkpoints.sql`（`git diff --stat` = ＋10／－2） | 该件上一个提交是 W7 的 `0a236ec` ⇒ **W7 正在改它**（大概率就是 T-09 的 `__start__` 谓词） | **不碰、不提交、不催**；但登记：我下轮引"格2／格3 锚点"时必须**现读工作副本**而不是引 `0a236ec` 的行号，否则会拿到已被他窗改动的锚点 |
| `?? backend/reports/w6/_full_pytest_0929.rev`、`?? eval/results_replay_probe.json` | W6 的两件产物**未入库** | ⇒  reinforcing 我第二轮的**当期性缺口**：闸门输入产物若不入库，`gate_provenance` 就永远补不上 `self_reported_rev`。列进批次 3（架构 O 件）而不单开单 |
| `?? backend/生成：2026-09-16` | **0 字节**空文件，文件名带全角冒号 | 不是本窗产物 ⇒ **不动**；上呈总控确认归属（多半是某次重定向手滑） |

## 三、本窗自曝（本轮两条）

1. **机制归因错**：上轮我说 DoD④ 门"匹配不到 `user:pass@host` 形状"，真机制是**只认 `+psycopg` 前缀**。根因 = 我拿 2 字符合成串去测，没把"串太短"和"形状不吃"分离。⇒ 固化成规矩：**测任何形状尺的覆盖面，先量它的最小命中长度（用户／口令／主机各扫一遍长度），再做形状差量。**
2. **直觉拦住了假绿，但没有拦停我**：`5 passed in 2.50s` 对一个内含 `alembic upgrade head` 的模块级夹具**太快**。我第一反应是怀疑假绿，去查制品才确认是真的（0005＋6＋6）。⇒ 固化成规矩：**夹具里带子进程的件，"用时短"必须用制品自证，不能靠跑通本身。**

## 第 7 轮补：运行面直读（体制变更期取证）

| 探针 | 命令形状 | 真 `rc` | 读数 | HEAD | 备注 |
|---|---|---|---|---|---|
| 运行容器路由面 | `docker exec commerceql-api-1 sh -c "python -c <urllib 自探 127.0.0.1:8000>"`（**进程内**，绕开宿主端口） | **0** | `/api/v1/healthz` **200**（637 B）；`/api/v1/health`／`/api/v1/metrics`／`/metrics`／`/docs`／`/openapi.json` **404** | `304d37a` | 代码路径 = **`/srv/app/`**；`/docs`＋`/openapi.json` 404 是**本轮新量到**的，此前未登记 |
| dev 占位凭据面 | `git grep -lE "app_(rw\|ro)_pwd" HEAD \| wc -l` | **0** | **21** 个跟踪文件（旧快照 = 9，已过期） | `304d37a` | ⚠️ 该数**随交付涨** ⇒ 一律现读，不写死 |
