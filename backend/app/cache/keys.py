"""缓存键唯一构造入口 —— 单一真相文件 #3 / 3（07 §11.2）。

归属窗口：W0（docs/08 §4.1）。

**铁律**（07 §11.2 的 7 条硬规则 + §11.5 的 4 条红线，全部落在这里）：
1. **任何键必须含 `tenant_id`** —— 违反 = 跨租户泄露（N-10 / R-5，致命）；
2. **任何与语义相关的键必须含 `bundle_version`** —— 违反 = 语义包更新后返回旧口径结果，
   **静默错误、不报错**（比崩溃更难排查）；
3. **禁止裸字符串拼键** —— 全项目只能调用本模块的函数；
4. 键中**不得出现明文 `user_id`** —— 统一 `user_scope_hash(user_id)`；
5. 键长 ≤ 200 字符，超长说明把内容塞进键了（应改为哈希）；
6. 自由文本一律 `sha256` 摘要，不直接使用；
7. `tenant_id` **必须来自服务端可信上下文**，绝不接受客户端传入。

**本模块不读配置、不连 Redis** —— 它是纯函数库。TTL 只提供默认值，调用方可注入覆盖。

--------------------------------------------------------------------------------
**回填请求 U-14 的裁定结果（07 v0.6，已落笔）—— 本文件据此修正过一轮**

我（W0）曾提"§11.1 里 `emb:` / `evt:` 两个键不含租户，与硬规则 1 冲突"。
架构窗口**没有简单加租户**，而是把根因挖到了两处更深的地方，**三条结论全部改变了本文件**：

| 键 | 我的原始请求 | 裁定 | 依据 |
|---|---|---|---|
| `sem:fs`（few-shot 索引） | **我漏了它** | ✅ **必须加 `{tenant}`** | §11.2 规则 9：few-shot 的内容来源含 `gold_query`，而 Gold Query 由**用户反馈**产生（FR-11.1/11.2）= **租户数据**。我原按"语义包是公共的"推理 —— **推理错了**：包是公共的，**资产不是** |
| `emb:`（向量缓存） | 请求加租户 | ❌ **不加**，恢复无租户 | §11.2 规则 8：豁免的唯一形态 = "**纯派生自公共语义包**"（全部输入可追溯到已发布语义包、且不含任何租户级内容），且**必须被显式列出** —— 当前唯一豁免键就是它 |
| `evt:`（事件缓冲） | 请求加租户 | ❌ **不加** | 规则 1 收紧后，判据是"**键的内容 / 命中与否是否可能反映租户数据**"。`task_id` 是服务端生成的随机 ID，键本身与命中状态都不含租户信息 → 规则 1 本就**不要求**它带租户（这不是"豁免"，是不适用） |

**⚠️ 但 `evt:` 留了一个我不该擅自消化的口子**：规则 8 断言"当前唯一豁免键 = `emb:`"，
而 §11.1 表里 `evt:` 同样没有租户 —— 二者若按"有没有租户"字面对比，会让人误以为
`evt:` 是**第二个豁免**（那就要走规则 8 的三条门槛）。实际它是"规则 1 不适用"。
→ 已在交付中登记 **U-21**，请求在 §11.1 表里给 `evt:` 加一句"规则 1 不适用"的脚注，
把这个歧义从"靠推理"变成"表里写明"。**在裁定前本文件按 §11.1 的键格式实现**（不带租户）。

**根因（值得留档）**：`sem:fs` 的漏判说明 —— **"内容来自公共语义包"不等于"内容里没有租户数据"**。
语义包承载的是**定义**（公共），few-shot 承载的是**样例**（可能来自租户反馈）。
本文件的 `TENANTLESS_BUILDERS` 就是为这类错误准备的：**任何新增的无租户键都必须在此登记并写出理由**。
--------------------------------------------------------------------------------
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = [
    "ALL_BUILDERS",
    "DEFAULT_TTL_S",
    "KEY_MAX_LEN",
    "TENANTLESS_BUILDERS",
    "active_version",
    "clarify_context",
    "embedding",
    "event_buffer",
    "idempotency",
    "jittered_ttl",
    "rate_limit",
    "rate_limit_tenant",
    "result_set",
    "semantic_few_shot",
    "semantic_retrieval",
    "session_lock",
    "session_plan",
    "sha256_text",
    "user_scope_hash",
]

#: 键长上限（§11.2 硬规则 5）。
KEY_MAX_LEN: Final[int] = 200


# ============================================================================
# 基础摘要工具（§11.2 硬规则 4 / 6）
# ============================================================================

def sha256_text(text: str) -> str:
    """自由文本 → 定长摘要。**自由文本绝不原文进键**（§11.2 硬规则 6）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def user_scope_hash(user_id: str) -> str:
    """`user_id` → 16 位摘要，用于限流桶与会话锁（§9.2 / §9.3）。

    ⚠️ 明文 `user_id` **不得**出现在键里：Redis 的 `KEYS` 输出与监控面板会把它暴露出去
    （§11.2 硬规则 4，PII 泄露面）。
    """
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def _build(*parts: object) -> str:
    """统一装配 + 强制自检。**唯一的字符串拼接点**。

    自检项刻意做成"构造函数级别的断言"而不是评审 Checklist：
    遗漏租户/版本这类错误**不会报错**，只会静默返回错数据，靠人看是看不出来的。
    """
    segments = [str(p) for p in parts]
    if any(not seg for seg in segments):
        raise ValueError(f"缓存键片段不得为空：{segments}")
    key = ":".join(segments)
    if len(key) > KEY_MAX_LEN:
        raise ValueError(
            f"缓存键超长（{len(key)} > {KEY_MAX_LEN}）：{key[:64]}… "
            f"—— 超长说明把内容直接塞进了键，应改为 sha256 摘要（§11.2 硬规则 5）"
        )
    return key


# ============================================================================
# 版本指针（07 §6.2 —— 单键指针，一次 SET 完成原子切换）
# ============================================================================

def active_version() -> str:
    """语义包活动版本指针键。

    ⚠️ **本键是唯一不带租户的键，且是有意的**：它是**全局**版本指针，
    所有含 `bundle_version` 的键靠它"自然失效"，而不是遍历删缓存。
    这正是把竞态窗口从"秒级遍历"压缩为"一次 SET 的原子性"的原因（§6.2）。
    """
    return _build("semantic", "active_version")


# ============================================================================
# 语义相关键（**必须含 bundle_version** —— §11.2 硬规则 2）
# ============================================================================

def semantic_retrieval(tenant_id: str, bundle_version: str, question: str) -> str:
    """语义检索候选缓存。TTL 1h。格式：`sem:retr:{tenant}:{bundle}:{sha256(q)}`。"""
    return _build("sem", "retr", tenant_id, bundle_version, sha256_text(question))


def semantic_few_shot(tenant_id: str, bundle_version: str, domain: str) -> str:
    """few-shot 索引。TTL = 版本期。格式：`sem:fs:{tenant}:{bundle}:{domain}`。

    ⚠️ **必须有租户维度**（07 v0.6 §11.2 规则 9，**推翻了我最初的实现**）：
    few-shot 的内容来源包含 `gold_query`，而 Gold Query 由**用户反馈修正**产生
    （FR-11.1/11.2）→ **是租户数据**。缺租户 = 租户 A 的 bad case 修正被租户 B 召回。

    ⚠️ 即使某一刻库内内容**全部**来自全局认证库（§11.7 的 `tenant_id IS NULL` 层），
    键仍必须含租户 —— 因为**"命中与否"本身就反映了"该租户有没有私有 Gold Query"**，
    属于规则 8 说的那种侧信道。
    """
    return _build("sem", "fs", tenant_id, bundle_version, domain)


# ============================================================================
# 向量缓存（**全项目唯一被显式豁免租户的缓存键** —— §11.2 规则 8）
# ============================================================================

def embedding(model: str, dim: int, text: str) -> str:
    """embedding 向量缓存。TTL 30d。格式：`emb:{model}:{dim}:{sha256(text)}`（**无租户**）。

    ⚠️ **不要"顺手"给它加租户** —— 它是 §11.2 规则 8 里**唯一**被显式列出的豁免键，
    满足豁免的三个条件：① 输入（`model`/`dim`/`text`）全部可追溯到**已发布语义包**，
    对所有租户字节相同；② 不含任何租户级内容；③ 在 §11.1 表中被显式列出。
    加租户会让"同一段公共定义的向量"被重复计算 N 次（N = 租户数），是纯损失。

    `model` / `dim` 进键 → 换模型/换维度时**缓存自然失效**，无需手工清理（§11.3）。
    """
    return _build("emb", model, dim, sha256_text(text))


# ============================================================================
# 会话相关键
# ============================================================================

def session_plan(tenant_id: str, session_id: str) -> str:
    """会话计划摘要（N-17：只存计划摘要与 bundle 版本，**不存历史 SQL 与历史结果**）。"""
    return _build("sess", "plan", tenant_id, session_id)


def clarify_context(tenant_id: str, clarify_id: str) -> str:
    """澄清上下文。TTL **5min**（对齐附录 A §A.13 的 `CLARIFY_EXPIRED` 410）。"""
    return _build("clarify", tenant_id, clarify_id)


def idempotency(tenant_id: str, idempotency_key: str) -> str:
    """幂等键（附录 A §A.12 / 07 §9.4）。TTL 24h。"""
    return _build("idem", tenant_id, idempotency_key)


def event_buffer(task_id: str) -> str:
    """流重放事件缓冲（Redis List）。TTL 1h。格式：`evt:{task_id}`（**无租户**）。

    ⚠️ **这里的"无租户"是规则 1 不适用，不是豁免**（见文件头 U-21）：
    判据是"键的内容 / 命中与否是否反映租户数据"，而 `task_id` 是服务端生成的随机 ID ——
    键的内容不含租户信息，命中与否只反映"该任务的事件缓冲是否存在"。
    重放端点的**授权**由 `GET /query/{task_id}` 的所有权校验负责（附录 A §A.2），
    **不能**指望键来兜底。

    ⚠️ 与之对照：**结果集键 `result:{tenant}:{task_id}` 必须带租户** ——
    它的值是真结果行（含业务明细），与这里只放 SSE 帧的事件缓冲不是一类东西。
    """
    return _build("evt", task_id)


def result_set(tenant_id: str, task_id: str) -> str:
    """结果集（异步/重放）。TTL 1h。

    ⚠️ 这是**唯一**允许存放结果行的缓存位置（不进检查点，07 §5.2.1 体积规则）。
    ⚠️ 写入前结果必须**已脱敏**（N-05）。
    """
    return _build("result", tenant_id, task_id)


# ============================================================================
# 限流与会话锁（07 §9.2 / §9.3）
# ============================================================================

def rate_limit(bucket: str, tenant_id: str, user_id: str) -> str:
    """限流计数键（**用户维度**）。格式：`rl:{bucket}:{tenant}:{sha256(user_id)[:16]}`（§9.2 明文给定）。

    ⚠️ **必须含租户**（§9.2 末行明确写了这一条）。
    ⚠️ 这是"租户内按用户分桶"的键 —— **租户合计维度**请用 `rate_limit_tenant`，
    两者绝不可混用（见该函数的防撞说明）。
    """
    return _build("rl", bucket, tenant_id, user_scope_hash(user_id))


def rate_limit_tenant(bucket: str, tenant_id: str) -> str:
    """限流计数键（**租户合计维度**）。格式：`rl:t:{bucket}:{tenant}`（U-38，2026-09-16 补齐）。

    背景（U-38）：07 §9.2 给四个桶各有一条**租户级**窗口（query 100/min、
    read 1200/min、write 300/min），此前因本模块缺这个构造函数而**无人执行**
    （`app/api/ratelimit.py` 的 `UNENFORCED_DIMENSIONS` 显式登记了这一削弱）。

    ⚠️ **与前缀 `rl:t:` 的双重防撞设计**：
    用户键是 `rl:{bucket}:{tenant}:{user}`（4 段，第 1 段 `rl`），
    租户键是 `rl:t:{bucket}:{tenant}`（4 段，第 2 段字面量 `t`）。
    两键**在任何参数取值下都不可能相等** —— 这不是风格偏好，是正确性前提：
    `ratelimit.py` 的滑窗脚本对 KEYS[1] / KEYS[2] 分别判定，若两个维度共用一个 ZSET，
    用户配额会被当成租户配额 → "限流忽然变得极严"且**无任何报错**。
    （该文件在 `_window_keys` 里为此设了显式 `raise`，本函数是它的解。）

    ⚠️ `tenant_id` 明文进键与本文件其余键一致（硬规则 4 只约束 `user_id` ——
    PII 面是"自然人身份"，租户是组织标识，且监控面板需要按租户读数）。
    """
    return _build("rl", "t", bucket, tenant_id)


def session_lock(tenant_id: str, user_id: str, session_id: str) -> str:
    """会话串行锁键。格式：`lock:session:{tenant}:{sha256(user_id)[:16]}:{session_id}`。

    ⚠️ 锁的 value 必须是 `task_id`：续租与释放都要校验持有者，
    否则会出现"A 超时释放、B 已持有 → 释放了别人的锁"（§9.3）。
    """
    return _build("lock", "session", tenant_id, user_scope_hash(user_id), session_id)


# ============================================================================
# TTL 与防雪崩
# ============================================================================

#: 默认 TTL（秒）。调用方可注入覆盖，**本模块不读配置**。
#: 注：`semantic_few_shot` 的 TTL 是"版本期"，由版本指针失效驱动，不走 TTL。
DEFAULT_TTL_S: Final[Mapping[str, int]] = MappingProxyType(
    {
        "semantic_retrieval": 3600,
        "embedding": 30 * 86400,
        "session_plan": 86400,          # 会话期（SESSION_TTL_SECONDS）
        "clarify_context": 300,         # 5min，对齐 A.13
        "idempotency": 86400,           # 24h
        "event_buffer": 3600,
        "result_set": 3600,
        # 限流计数的 TTL = **窗口长度**，不是"缓存时长"：§A.0.6 的四个桶都是「N 次/分钟」，
        # 故窗口 = 60s。写死在这里只是缺省值 —— 限流器按桶配置覆盖（§9.2）。
        "rate_limit": 60,
        "rate_limit_tenant": 60,
        "session_lock": 60,             # 执行中每 20s 续租（§9.3）
    }
)


def jittered_ttl(ttl_s: int, *, rand: float | None = None) -> int:
    """TTL 抖动 ±10%（§11.4 防雪崩）。

    ⚠️ **不得**对会话锁、幂等键之外的关键键省略抖动 —— 大量键同时过期会导致同一瞬间回源。
    `rand` 参数只为让测试可复现（传 `0.0` / `1.0` 取边界）。
    """
    if ttl_s <= 0:
        raise ValueError(f"TTL 必须为正数：{ttl_s}")
    r = random.random() if rand is None else rand
    if not 0.0 <= r <= 1.0:
        raise ValueError(f"rand 必须落在 [0,1]：{r}")
    return max(1, int(ttl_s * (0.9 + r * 0.2)))


# ---------------------------------------------------------------------------
# 无租户键的**唯一登记处**（07 §11.2 规则 1 / 8）。
#
# 这里的每个名字都必须能回答同一个问题："**为什么它不含租户不会泄露**？"
# 新增无租户键 = 往这个集合里加名字 —— 而那会在契约测试里**红**，
# 逼作者写下一句理由。机制与 U-19 的 `test_tau_gate_is_prod_only_by_design` 同构：
# **绕过它需要显式改一个带决策编号的测试，而不是"顺手少传一个参数"。**
#
# 三种"无租户"，性质不同，**不要混为一谈**：
#   1. semantic:active_version —— 全局单值指针，对全部租户字节相同（**不是缓存条目**）
#   2. emb:...                —— 唯一被**显式列出**的豁免键（§11.2 规则 8 三条条件全满足）
#   3. evt:...                —— 规则 1 **不适用**（键内容与命中与否都不反映租户数据）
#                               ⚠️ 第 3 类的表述待 §11.1 补脚注（U-21）
# ---------------------------------------------------------------------------
TENANTLESS_BUILDERS: Final[frozenset[str]] = frozenset(
    {
        "active_version",   # 全局指针（非缓存条目）
        "embedding",        # §11.2 规则 8 的唯一显式豁免
        "event_buffer",     # 规则 1 不适用（task_id 为服务端随机 ID）
    }
)

#: 全部键构造函数名（供契约测试做"无租户键必须已登记"的全集比对）。
ALL_BUILDERS: Final[frozenset[str]] = frozenset(
    {
        "active_version",
        "clarify_context",
        "embedding",
        "event_buffer",
        "idempotency",
        "rate_limit",
        "rate_limit_tenant",
        "result_set",
        "semantic_few_shot",
        "semantic_retrieval",
        "session_lock",
        "session_plan",
    }
)

# ---------------------------------------------------------------------------
# 本模块**故意不提供**的键（红线，07 §11.5）—— 不是遗漏：
#   1. 无"查询结果缓存"键（P0 关闭，ADR-12：成本不构成约束，而键设计错 = 事故）；
#   2. 无"负缓存（空结果）"键 —— 最危险的一条：空结果可能是 RLS 行级过滤造成的，
#      缓存它会让另一个角色/租户命中"无数据"的确定结论 = **跨租户存在性泄露**；
#   3. 无任何含明文 PII 的键。
# 若某窗口"顺手"在本模块外拼了上述键 → 按 08 §6.3 视为契约冲突，须回本文件登记。
# ---------------------------------------------------------------------------
