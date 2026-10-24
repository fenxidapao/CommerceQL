# data —— 合成数据生成器（沙箱库不入库）

> 这里**没有** `ecom_sandbox.db`。仓库只带生成器；`.gitignore` 刻意排除产物（`data/*.db`、`*.db-*`），
> 因为沙箱库约 **440MB**，且必须能从种子确定性重建。

## 1. 目录

| 文件 | 作用 |
|---|---|
| `generator/seed_generator.py` | 主生成器：造 `ecom_sandbox.db`（订单/商品/流量，3 租户） |
| `generator/layering.py` | 分层视图（已支付订单视图等，供评测取数） |
| `generator/selfcheck.py` | 生成后自检（行数/分布/口径断言） |
| `schema.sql` | 沙箱库的 DDL 参考 —— ⚠️ **不是生产 DDL 真相**，生产迁移在 `backend/app/repo/migrations/` |

## 2. 跑 eval / 复算之前必须先做这一步

```bash
python data/generator/seed_generator.py --out data/ecom_sandbox.db
# 快速自测（小规模）：
python data/generator/seed_generator.py --out /tmp/t.db --orders 5000
# 只看生效参数，不生成：
python data/generator/seed_generator.py --dump-params
```

否则 `eval/runner.py` 会因为找不到沙箱库直接失败 —— **不是代码坏了**。

## 3. 三条硬纪律（写在生成器 docstring 里，改之前先读）

1. **零新依赖**：只用标准库（`sqlite3` / `random` / `datetime` / `hashlib`），不引入 `faker`/`numpy`。
2. **可复现**：所有随机来自命名子流 `rng("<stream>")`，种子 = `sha512(f"{seed}:{stream}")`；新增子流不改变既有序列 ⇒ 加字段不会让旧 hash 漂移。
3. **不编数字**：规模参数集中在 `PARAMS`，与 `docs/04 附录 C §C.12` 对应并写入 `eval/MANIFEST_v1.json` 供审计。

⚠️ 改 `PARAMS` 任何值 = **数据物变更** ⇒ 必须重算并更新 `eval/MANIFEST_v1.json`；冻结集已发布时还须走升版本流程（不得静默改集）。
