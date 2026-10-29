# LICENSES —— 数据许可证与公开仓库检查

> 查证日期：**2026-10-29（+0800）**
> 本文件只记录**实际查证**结果；未查到的项写 `UNVERIFIED`，不凭记忆填。
> 原始响应：`backend/reports/w4_acceptance/kaggle_olist_metadata.json`（HTTP 200，本窗实跑保存）。

---

## 1. Olist 数据集

| 项 | 查证结果 | 源（元数据字段） |
|---|---|---|
| 数据集 | Brazilian E-Commerce Public Dataset by Olist | `title` |
| Kaggle ref | `olistbr/brazilian-ecommerce` | `ref` |
| 所有者 | Olist | `ownerName` / `ownerNameNullable` |
| 创建者 | Francisco Magioli | `creatorName` / `creatorNameNullable` |
| **许可证** | **CC BY-NC-SA 4.0** | `licenseName` / `licenseNameNullable` |
| 许可证正文 | https://creativecommons.org/licenses/by-nc-sa/4.0/ | 许可证名称对应的 canonical URL |
| 数据页 | https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce | 由 `ref` 拼装 |
| 最后更新（平台） | 2021-10-01T19:08:27.97Z | `lastUpdated` |
| 查证方式 | `GET https://www.kaggle.com/api/v1/datasets/view/olistbr/brazilian-ecommerce` → HTTP 200 | 原始 JSON 已入库证据 |

**署名文本（建议随任何分发/展示携带）**

> Brazilian E-Commerce Public Dataset by Olist — Olist / Francisco Magioli,
> licensed under CC BY-NC-SA 4.0.
> Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
> Changes: subset loaded into a local PostgreSQL demo schema; derived aggregates
> produced for evaluation and demo.

**义务（按 CC BY-NC-SA 4.0）**

- **BY（署名）**：必须署名 Olist / Francisco Magioli、给许可证链接、**标明是否修改**。
- **NC（非商业）**：不得用于商业目的；本项目为求职作品集 / 教学演示，按非商业使用。
- **SA（相同方式共享）**：若分发基于该数据的**改编物**，须以相同许可证分发。
- 不得附加额外法律或技术限制。

> 以上是对许可证名称对应条款的摘要，不替代许可证正文；引用义务时以
> https://creativecommons.org/licenses/by-nc-sa/4.0/ 为准。

---

## 2. 本仓库分发什么 / 不分发什么

- **不分发**原始数据、SQLite 沙箱库、PG 数据卷：
  - 原始数据在仓库外：`Text2SQL/real_data/olist/olist.sqlite`；
  - 沙箱库 `data/olist/olist_sandbox.db` 被 `.gitignore:54`（`*.db`）忽略；
  - 仓库内 `git ls-files` 无任何 `.db`/`.sqlite`/`.sqlite3`。
- **只提交**：loader、schema/迁移、语义包、说明与归属（见 `deploy/demo/README.md`）。
- **派生结果**：仓库内已提交的 `eval/olist/gold60_results.json`、`report.json`、
  `results_v1_r*.json`、`backend/reports/w3_demo/**` 等是**派生聚合结果**；
  其分发/改编义务按 **CC BY-NC-SA 4.0** 说明（署名 + 非商业 + 相同方式共享）。
- **代码许可证**：仓库当前**没有** `LICENSE` 文件；代码许可证由项目所有者决定，
  本窗**不擅自补** MIT / Apache / 其他许可。

---

## 3. 公开仓库前检查（可直接粘贴）

```bash
# 1) 沙箱库被忽略（应输出 .gitignore:54:*.db ...）
git check-ignore -v data/olist/olist_sandbox.db

# 2) 没有任何 db/sqlite 文件入库（应无输出）
git ls-files | grep -Ei '\.(db|sqlite|sqlite3)$'

# 3) 没有 .env / secrets 入库（应无输出）
git ls-files | grep -Ei '(^|/)\.env$|secrets/'

# 4) 工作树凭据字面量扫描
python backend/scripts/scan_secrets.py --working-tree
```

**2026-10-29 本窗实测**

| 检查 | 读数 |
|---|---|
| `git check-ignore -v data/olist/olist_sandbox.db` | `.gitignore:54:*.db	data/olist/olist_sandbox.db`（exit 0） |
| `git ls-files \| grep -Ei '\.(db\|sqlite\|sqlite3)$'` | 空 |
| `git ls-files \| grep -Ei '(^\|/)\.env$\|secrets/'` | 空 |
| `scan_secrets.py --working-tree` | **0 命中**（748 件；`scan_rc=0`） |

> ⚠️ `scan_secrets.py` 是 CI 的**下界**：它只复放本项目自有 3 条规则（DeepSeek key /
> 带密码 DSN / JWT 私钥）并只看工作树当前内容；CI 的 `gitleaks detect` 还含
> 默认规则集与**全部历史**。本脚本绿不代表 CI 绿。

---

## 4. 未决项

- **代码 LICENSE**：`UNVERIFIED`（未声明；由总控拍板）。
- **商用边界**：本项目按非商业使用；若未来商用，需重新评估 **NC** 条款。
- **数据集版本**：本窗未固定 Kaggle 数据集的内容哈希；引用读数时以
  `eval/olist/sandbox_manifest.json`（沙箱行数/体积/sha256）为本地身份。

---

## 5. 引用

- Kaggle 元数据端点：`https://www.kaggle.com/api/v1/datasets/view/olistbr/brazilian-ecommerce`
- 许可证正文：https://creativecommons.org/licenses/by-nc-sa/4.0/
- 本仓库存放的原始响应：`backend/reports/w4_acceptance/kaggle_olist_metadata.json`
