# deploy/demo —— Olist 真实数据的装载与演示资产

> 归属窗口：W1 实施窗（`build_olist_sandbox.py`）｜问题号 `U-143`
> 本目录只放**脚本**，产物一律落 `data/`（gitignore）。

## 1. 已有

### `build_olist_sandbox.py`

从原始 Olist SQLite（只读 ATTACH）生成评测沙箱 `data/olist/olist_sandbox.db`。

⚠️ 用 archive 里的 3.13 venv 跑（`CommerceQL-archive/local/.venv/Scripts/python.exe`）：
自检段会 import `eval/sqlite_exec.py`，它依赖 `app.exec`（pydantic v2）。
Anaconda 的 3.11 + pydantic 1.10 会直接红。仓库根**不放** `.venv`。

```bash
V="E:/01_实训/项目/基于Text2SQL的电商数据分析Agent/CommerceQL-archive/local/.venv/Scripts/python.exe"
"$V" deploy/demo/build_olist_sandbox.py \
  --sqlite ../Text2SQL/real_data/olist/olist.sqlite \
  --out data/olist/olist_sandbox.db
```

产物契约（三条，缺一 `eval/sqlite_exec.py::open_sandbox_connection` 就用不了）：

1. 物理表名**恰好等于**语义包的 `physical_asset`：`v_o_orders` / `v_o_order_items` /
   `v_o_products` / `v_o_payments` / `v_o_reviews`；
2. 每张表带 `tenant_id` 列 —— TEMP VIEW 的过滤条件就是它；
3. 行数 / 体积 / sha256 写进 `eval/olist/sandbox_manifest.json`（经 `eval/olist/build_dataset.py`
   的落盘守卫，所以清单只会出现在 `eval/olist/` 下）。

自检走 `open_sandbox_connection`（不是裸 `sqlite3`）：`T_A` 每表 > 0、`T_B` 每表 = 0。

**当前读数**（2026-10-27，CPython 3.13.14 / sqlite3 3.53.1）：448,152 行 /
92,684,288 bytes / sha256 `17c14cee…`。**同一解释器内**两次构建哈希一致；
**跨解释器会变**（3.13.13 下是 `a67c5f7d…`，字节数相同）—— 判定身份要么钉解释器，
要么以内容为准。

**沙箱里没有的东西**：`geolocation`（1,000,163 行，本薄包不用）、
`order_reviews` 的评论正文两列（自由文本，未做 PII 审阅）、`sellers` 表。

## 2. 尚未创建（W3）

以下文件属于 **W3**，`计划_合并版.md §6.2` 列了名字，但本窗不做：

| 文件 | 用途 |
|---|---|
| `load_olist_to_pg.py` | 原始库 → PG 底表（`app_rw` 写） |
| `materialize_olist.py` | `materialize(with_policy=True)` + 一致性断言 |
| `docker-compose.olist.yml` | 叠加 compose 覆盖 |

⚠️ W3 开工第一件事：`semantic/bundle_olist_2018.yaml` 的 `meta.dialect` 现在是
`sqlite`。进 PG 前必须显式裁定是改 dialect 并递增 `meta.version`（会作废绑在该版本上的
W1/W2 读数），还是分叉第二份包 —— 见 `eval/olist/README.md` §6。

## 3. 文件归属

`deploy/**` 归 W1 实施窗。新增脚本前先确认不覆盖 `deploy/.env`（含密钥，不入库）。
