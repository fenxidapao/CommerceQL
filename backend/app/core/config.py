"""配置 —— pydantic-settings，**启动即校验（fail fast）**。

归属窗口：W0（docs/08 §4.1）。依据：07 §18.4 + 07 附-6 + 附录 D §D.4.1。

设计原则（三条，都是踩过的坑）：
1. **宁可起不来，也不要带错配置跑起来**（N-15）。错配置不会报错，只会让某个能力静默失效
   —— 例如 `ACTIVE` 语义包路径写错、embedding 维度与向量列不一致，排查成本远高于启动失败。
2. **密钥只来自环境变量**，绝不硬编码、绝不进仓库（PRD §11.5 有真实事故）。
   `SecretStr` 保证它连日志/`repr` 都不会漏。
3. **校验分两级**：
   - **纯配置级**（本文件，import 后即可校验，CI 可跑）：类型、范围、互斥、组合约束；
   - **需真实依赖级**（必须连库才能判定，见 `STARTUP_ASSERTIONS_DELEGATED_TO_W1B`）：
     归 W1B 的 lifespan 实现 —— 阶段 0 **不伪造**这部分实现。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["STARTUP_ASSERTIONS_DELEGATED_TO_W1B", "AppEnv", "Settings", "get_settings"]


class AppEnv(StrEnum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class Settings(BaseSettings):
    """全量实现级配置项。

    字段分组与 `.env.example`（`deploy/.env.example`）**一一对应**：
    新增配置项必须同步 07 附-6 与 `.env.example`，否则新机器部署会缺项。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # ⚠️ `extra="forbid"` 的**真实边界**（阶段 0 实测，勿高估它）：
        #    它拦得住"显式传错的初始化参数"（`Settings(DATABSE_URL=...)`），
        #    但**拦不住"拼错的环境变量名"** —— pydantic-settings 对未知环境变量是
        #    **静默忽略**的。即 `DATABSE_URL=x` 放进环境里不会报错，只会让
        #    `DATABASE_URL` 悄悄用默认值（而默认值通常是"最不安全但能跑"的那一档）。
        #    → 真正的防线是 `deploy/.env.example` ↔ 本类字段的**双向同步断言**，
        #      见 `tests/contract/test_config_failfast.py` §6
        #      （`test_env_example_covers_every_setting` / `test_env_example_has_no_stale_keys`）。
        #      两条断言合起来保证"键名只有一个出处、新机器部署不缺项"，
        #      这比 extra 能提供的保护更贴近实际故障模式。
        extra="forbid",
    )

    # ---------------- 应用 ----------------
    APP_ENV: AppEnv = AppEnv.DEV
    LOG_LEVEL: str = "INFO"
    API_PORT: int = Field(default=8000, ge=1, le=65535)
    TIMEZONE: str = "Asia/Shanghai"
    CORS_ALLOWED_ORIGINS: str = ""  # 逗号分隔；prod 必须为空（同源反代，07 §8.6.5 常见误配）

    # ---------------- LLM（DeepSeek） ----------------
    DEEPSEEK_API_KEY: SecretStr = Field(..., description="必填。只在此处填，严禁硬编码")
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL_FAST: str = "deepseek-flash"
    LLM_MODEL_STRONG: str = "deepseek-v4-pro"
    LLM_TIMEOUT_SECONDS: int = Field(default=60, gt=0)
    LLM_MAX_CONCURRENCY: int = Field(default=50, gt=0)  # 上游限的是并发连接数，不是 QPS
    LLM_MAX_RETRIES: int = Field(default=3, ge=0)
    LLM_SEMAPHORE_FLASH: int = Field(default=8, gt=0)  # 07 附-6
    LLM_SEMAPHORE_PRO: int = Field(default=2, gt=0)
    LLM_CIRCUIT_FAILS: int = Field(default=5, gt=0)
    LLM_CIRCUIT_OPEN_S: int = Field(default=30, gt=0)

    # ---------------- 数据库（⚠️ 双 DSN，两套角色，代码不得混用） ----------------
    DATABASE_URL: str = Field(..., description="元数据 R/W，角色 app_rw，对 audit_log 仅 INSERT")
    ANALYTICS_DB_URL: str = Field(..., description="业务只读，角色 app_ro")
    SQLITE_SANDBOX_PATH: str = "/data/sandbox/ecom_sandbox.db"

    # ---------------- Embedding（Ollama，运行在宿主） ----------------
    EMBEDDING_BASE_URL: str = "http://127.0.0.1:11434"
    EMBEDDING_MODEL: str = "bge-m3"
    EMBEDDING_DIM: int = Field(default=1024, gt=0)  # 参与向量索引 DDL
    EMBEDDING_TIMEOUT_SECONDS: int = Field(default=30, gt=0)  # 需覆盖"未预热"的模型加载
    EMBEDDING_REQUIRED: bool = False  # false = 不可用走降级，且必须在 meta 里标注

    # ---------------- Redis ----------------
    REDIS_URL: str = "redis://redis:6379/0"
    CACHE_TTL_SECONDS: int = Field(default=3600, gt=0)
    SESSION_TTL_SECONDS: int = Field(default=86400, gt=0)

    # ---------------- 认证 ----------------
    JWT_PUBLIC_KEY_PATH: str = "/run/secrets/jwt_public.pem"
    JWT_ISSUER: str = "workbuddy-demo"
    JWT_AUDIENCE: str = "text2sql-agent"

    # ---------------- 语义层 ----------------
    SEMANTIC_BUNDLE_PATH: str = "/semantic/bundle_2026.09.14.1.yaml"
    SEMANTIC_REQUIRE_CERTIFIED: bool = True

    # ---------------- 执行与安全 ----------------
    EXEC_STATEMENT_TIMEOUT_MS: int = Field(default=30000, gt=0)
    EXEC_MAX_ROWS: int = Field(default=10000, gt=0)
    EXEC_MAX_MEMORY_MB: int = Field(default=512, gt=0)  # 超限 → EXEC_RESOURCE_EXCEEDED
    EXEC_COST_ROW_THRESHOLD: int = Field(default=1_000_000, gt=0)
    GATE_REJECT_SELECT_STAR: bool = True
    GATE_MAX_REPAIR_ROUNDS: int = Field(default=2, ge=0, le=2)

    # ---------------- 闸门三阈值（07 §7.5） ----------------
    GATE3_COST_WARN: float = Field(default=5e4, gt=0)
    GATE3_COST_REJECT: float = Field(default=5e5, gt=0)
    GATE3_ROWS_WARN: int = Field(default=500_000, gt=0)
    GATE3_ROWS_REJECT: int = Field(default=5_000_000, gt=0)

    # ---------------- 检索与融合（07 附-6） ----------------
    HNSW_M: int = Field(default=16, gt=0)
    HNSW_EF_CONSTRUCTION: int = Field(default=64, gt=0)
    HNSW_EF_SEARCH: int = Field(default=40, gt=0)
    FTS_RANK_NORMALIZATION: int = Field(default=32, ge=0, le=32)
    FTS_SCORE_MIN: float = Field(default=0.05, ge=0.0, le=1.0)
    RRF_K: int = Field(default=60, gt=0)
    DENSE_WEIGHT: float = Field(default=0.40, ge=0.0, le=1.0)
    SPARSE_WEIGHT: float = Field(default=0.35, ge=0.0, le=1.0)
    VALUE_WEIGHT: float = Field(default=0.15, ge=0.0, le=1.0)
    GRAPH_WEIGHT: float = Field(default=0.10, ge=0.0, le=1.0)

    # ---------------- 绑定 L4 打分器（N-27：τ 必须绑定版本 + 校准时间） ----------------
    BINDING_TAU: float = Field(default=0.20, ge=0.0, le=1.0)
    BINDING_TAU_EPSILON: float = Field(default=0.05, ge=0.0, le=1.0)
    BINDING_TAU_MODEL_ID: str = ""
    BINDING_TAU_PROMPT_VERSION: str = ""
    BINDING_TAU_CALIBRATED_AT: str = ""  # ISO8601；空 = 未校准
    BINDING_TAU_REPORT_REF: str = ""

    # ---------------- 并发、幂等与预算 ----------------
    SESSION_LOCK_TTL_S: int = Field(default=60, gt=0)
    SESSION_LOCK_WAIT_MS: int = Field(default=3000, ge=0)  # 超时 → 409 SESSION_CONFLICT
    REPLAY_EVENT_LIMIT: int = Field(default=200, gt=0)  # 防异常循环打满 Redis
    CHECKPOINT_TTL_DAYS: int = Field(default=7, gt=0)
    DAILY_BUDGET_CNY: float = Field(default=100.0, gt=0)
    BUDGET_ALERT_RATIO: float = Field(default=0.8, gt=0.0, le=1.0)

    # ---------------- 开关（默认关闭的必须显式确认） ----------------
    ENABLE_RESULT_CACHE: bool = False
    ENABLE_RESULT_CACHE_CONFIRMED: bool = False  # ADR-12 防误开

    # ========================================================================
    # 校验
    # ========================================================================

    @field_validator("TIMEZONE")
    @classmethod
    def _tz_must_exist(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TIMEZONE 不是合法 IANA 时区：{v!r}") from exc
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def _log_level_known(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL 必须是 {sorted(allowed)} 之一，收到 {v!r}")
        return upper

    @field_validator("DATABASE_URL", "ANALYTICS_DB_URL")
    @classmethod
    def _must_be_psycopg3(cls, v: str) -> str:
        if not v.startswith("postgresql+psycopg://"):
            raise ValueError(
                f"DSN 必须是 postgresql+psycopg://（psycopg **3**，不是 psycopg2）：{v!r}"
            )
        return v

    @model_validator(mode="after")
    def _cross_checks(self) -> Settings:
        # (1) 两套 DSN 不得相同 —— 相同即意味着"只读角色"实际是 app_rw，
        #     N-02（业务查询必须走只读连接）整套保证当场失效。
        if self.DATABASE_URL == self.ANALYTICS_DB_URL:
            raise ValueError(
                "DATABASE_URL 与 ANALYTICS_DB_URL 不得相同：前者是元数据 R/W(app_rw)，"
                "后者必须指向只读角色(app_ro)。相同 = 只读保证失效（N-02 / 07 §3.3）"
            )

        # (2) prod 下 CORS 必须为空（同源反代；07 §18.4 列为常见误配）
        if self.APP_ENV is AppEnv.PROD and self.CORS_ALLOWED_ORIGINS.strip():
            raise ValueError("APP_ENV=prod 时 CORS_ALLOWED_ORIGINS 必须为空（同源反代）")

        # (3) ADR-12 防误开：结果缓存若为 on，必须有显式确认标志
        if self.ENABLE_RESULT_CACHE and not self.ENABLE_RESULT_CACHE_CONFIRMED:
            raise ValueError(
                "启用结果缓存必须同时设置 ENABLE_RESULT_CACHE_CONFIRMED=true —— "
                "ADR-12/P0 判定其'键设计错 = 事故，收益小风险大'（PRD §12.4），故设二次确认"
            )

        # (4) 闸门三阈值必须 warn < reject（否则 warn 永不触发，等于没有预警档）
        if not self.GATE3_COST_WARN < self.GATE3_COST_REJECT:
            raise ValueError("GATE3_COST_WARN 必须小于 GATE3_COST_REJECT")
        if not self.GATE3_ROWS_WARN < self.GATE3_ROWS_REJECT:
            raise ValueError("GATE3_ROWS_WARN 必须小于 GATE3_ROWS_REJECT")

        # (5) 融合权重大致归一（允许 ±1% 浮点误差；不等 1 会让分数跨查询不可比）
        total_weight = (
            self.DENSE_WEIGHT + self.SPARSE_WEIGHT + self.VALUE_WEIGHT + self.GRAPH_WEIGHT
        )
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(
                f"DENSE/SPARSE/VALUE/GRAPH_WEIGHT 之和必须为 1.0（±0.01），当前 = {total_weight}"
            )

        # (6) N-27：τ 必须绑定 (model_id, prompt_version) 且带校准时间
        #
        # ⚠️ 为什么这条**只在 prod 强制**（阶段 0 的取舍，已登记为 U-19）：
        #   N-27 的目的是「不得把未经校准的 τ 上线」，不是「不得在本地把服务跑起来」。
        #   而 τ 的校准是 **W2B 的产出**，阶段 0 根本不存在 —— 若此处无条件 fail-fast，
        #   api 容器会在 `docker compose up` 时直接崩溃重启，三个探针全部不可访问，
        #   **阶段 0 DoD① 变成不可验证**（DoD① 明确要求 /live=200、/ready=503，
        #   即"服务起来了、但硬依赖未接"这个状态必须可达）。
        #   → 因此：prod 下 fail-closed（N-27 的强制力一点不减）；
        #            非 prod 下放行，但**不隐瞒** —— `binding_tau_is_calibrated`
        #            属性如实返回 False，供启动日志（WARN）与指标 gauge 上报。
        #   ⚠️ **不得**把它塞进 `/healthz` 的 `checks{}` —— 该 payload 是附录 A §A.8.4 的
        #      契约，私增字段违反"唯一规范源"（07 §18.4.1 硬要求 3）。架构窗口已把该诉求
        #      登记为补充契约 **C-13**（`config_warnings[]`，待回填附录 A）；
        #      在回填前承载方式 = **启动日志 + 指标**。
        #   后续窗口若要收紧（例如禁止 APP_ENV≠prod 的实例连生产库），
        #   应在此处加"非 prod + 生产 DSN → 拒绝启动"，而不是把 τ 检查改回无条件。
        if self.APP_ENV is AppEnv.PROD:
            if not (self.BINDING_TAU_MODEL_ID and self.BINDING_TAU_PROMPT_VERSION):
                raise ValueError(
                    "BINDING_TAU 必须同时声明 BINDING_TAU_MODEL_ID 与 BINDING_TAU_PROMPT_VERSION "
                    "—— τ 是待校准参数，脱离版本即无意义（N-27 约束②）"
                )
            if not self.BINDING_TAU_CALIBRATED_AT:
                raise ValueError(
                    "BINDING_TAU_CALIBRATED_AT 为空 = τ 未经冻结集校准 —— 不得上线（N-25/N-27："
                    "τ 的每次变更都必须附校准报告）"
                )

        # (7) 会话锁等待必须有上限（无上限 = 无限排队 = 延迟不可预期，07 §9.5）
        if self.SESSION_LOCK_WAIT_MS > 10_000:
            raise ValueError("SESSION_LOCK_WAIT_MS 不得 > 10s（07 §9.5：禁止无限排队）")

        # (8) ★ 行尾注释泄漏兜底 —— 本会话实测发现的真实陷阱
        #
        # python-dotenv 只在**值非空**时剥离 ` # 注释`：
        #     A=                → ''            ✅
        #     B=value  # cmt    → 'value'       ✅
        #     C=  # only cmt    → '# only cmt'  ❌ **注释变成了值**
        # `deploy/.env.example` 里曾因此有 5 个键静默拿到注释文本，
        # 其中 4 个是 τ 校准三元组 + 报告引用 → `binding_tau_is_calibrated` 恒为 True：
        #   · N-27 的 prod 门禁**形同虚设**（三个"必填"字段都被注释填满了）；
        #   · U-19 硬要求① 的启动 WARN **永远不会打**（因为它以为 τ 已校准）。
        # 这是"配置型假绿灯"：没有任何报错，配置看起来齐全，保护全部失效。
        #
        # 判据取"值以 `#` 开头"：正常配置值不会以 `#` 开头（DSN/模型名/路径/密钥都不会），
        # 而注释泄漏**必然**是 `#` 开头。宁可误伤（让作者改一行）也不放过。
        leaked = sorted(
            name
            for name in type(self).model_fields
            if isinstance(getattr(self, name), str)
            and getattr(self, name).lstrip().startswith("#")
        )
        if leaked:
            raise ValueError(
                f"以下配置项的值以 `#` 开头 —— 疑似把**行尾注释**读成了值：{leaked}。\n"
                f"  根因：python-dotenv 只在值非空时剥离 ` # 注释`；"
                f"`KEY=  # 说明` 会把 `# 说明` 当成值（`.env.example` 顶部有完整说明）。\n"
                f"  修法：把注释移到**上一行**，让该行只留 `KEY=`。"
            )

        return self

    # ------------------------------------------------------------------
    # 派生视图（供启动日志 / 健康检查 / 后续窗口读取）
    # ------------------------------------------------------------------

    @property
    def binding_tau_is_calibrated(self) -> bool:
        """τ 是否已绑定模型+提示词版本**且**附有校准时间（N-27 的完整条件）。

        ⚠️ 存在的理由（对应上面校验 (6) 的 env-gate）：
        prod 下未校准会直接拒绝启动，因此这里恒为 True；
        非 prod 下服务会起来，但**必须有人能看见 τ 未校准这个事实** ——
        否则 U-19 的"放行"就变成了"隐瞒"。启动日志（WARN）与指标 gauge
        `binding_tau_calibrated` 都应读取本属性。
        ⚠️ **不是** `/healthz` —— 那个 payload 是附录 A §A.8.4 的契约，
        私增字段违反"唯一规范源"（07 §18.4.1 硬要求 3、补充契约 C-13）。
        """
        return bool(
            self.BINDING_TAU_MODEL_ID
            and self.BINDING_TAU_PROMPT_VERSION
            and self.BINDING_TAU_CALIBRATED_AT
        )

#: **阶段 0 故意不实现**的启动断言（需要真实依赖，属 W1B 的 lifespan）。
#: 列在这里是为了让"还差哪三条"是明确的，而不是靠人记：
#:   - 07 §18.4 第 2 条：`ANALYTICS_DB_URL` 的角色具备 `default_transaction_read_only` → 否则拒绝启动（N-02）
#:   - 07 §18.4 第 3 条：`EMBEDDING_DIM` 与向量列维度一致 → 否则拒绝启动
#:   - 07 §18.4 第 5 条：`audit_log` 存在且 `app_rw` **无** UPDATE/DELETE 权限 → 否则拒绝启动
#:                       （这是 N-09 append-only 的**前提**；前置条件不成立时 fail-closed 无从谈起）
#:   - 07 §18.4 第 4 条：语义包通过 §6.1 五步校验（W2A 提供校验器）
STARTUP_ASSERTIONS_DELEGATED_TO_W1B: Final[tuple[str, ...]] = (
    "analytics_dsn_is_read_only",
    "embedding_dim_matches_vector_column",
    "audit_log_append_only_enforced",
    "semantic_bundle_passed_five_step_validation",
)


_settings: Settings | None = None


def get_settings() -> Settings:
    """进程内单例。

    ⚠️ 刻意**不做模块级实例化**（`settings = Settings()`）：
    那样任何一次 `import app.core.config` 都会要求环境变量齐全，
    连"只想跑一个离线单测"都得先配好生产密钥 —— 这会把 N-01（确定性模块离线可测）毁掉。
    """
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]  # 值来自环境变量
    return _settings
