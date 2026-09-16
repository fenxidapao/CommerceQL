#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CommerceQL 沙箱数据生成器（确定性）

归属窗口：W1A（data/**）
产出：`ecom_sandbox.db`（SQLite 评测沙箱）

设计约束（三条硬纪律）
----------------------
1. **零新依赖**：只用 Python 标准库（`sqlite3` / `random` / `datetime` / `hashlib`）。
   理由：ADR-20 白名单未含 `faker` / `numpy`，装了就得多走一次 §4.3 流程；
   而本生成器所需的随机能力 `random.Random` 已足够。
2. **可复现**：所有随机来自 `rng("<stream>")`（命名子流）。子流之间**互不干扰** ——
   新增一个子流不会改变既有子流的抽样序列，因此**加字段不会让旧 hash 漂移**。
   种子 = `sha512(f"{seed}:{stream}")` → 与 PYTHONHASHSEED 无关，跨机同结果。
3. **不编数字**：所有规模参数集中在 `PARAMS`，直接对应附录 C §C.12 / §C.12.1，
   并原样写入 MANIFEST 供审计。脚本自己打印实测行数与耗时。

用法
----
    python data/generator/seed_generator.py --out data/ecom_sandbox.db
    python data/generator/seed_generator.py --out X --seed 20260915 --dump-params
    python data/generator/seed_generator.py --out X --orders 5000   # 快速自测

⚠️ 改动任何 PARAMS 值 = 数据物变更 → 必须重算并更新 `eval/MANIFEST_v1.json`，
   且若冻结集已发布，须走升版本号流程（不得静默改集）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta

# ============================================================================
# 生成参数 —— 每一条都能追到附录 C 的出处
# ============================================================================
PARAMS: dict = {
    # ---- 随机种子（唯一入口；改它 = 换一整套数据）----
    "seed": 20260915,

    # ---- 附录 C §C.12 ----
    "date_start": "2024-10-01",          # 时间跨度 24 个月（2024-10 ~ 2026-09）
    "date_end": "2026-09-30",
    "tenants": ["T_A", "T_B", "T_C"],    # 3 个租户
    "shops_per_tenant": {"T_A": 5, "T_B": 4, "T_C": 3},   # 每租户 2–5 家
    "sku_total": 2000,                   # 2,000 SKU
    "category_l1_count": 8,              # 一级类目 8 个
    "channels": ["search", "feed", "live", "direct", "ad"],   # 5 个渠道
    "order_rows_total": 500000,          # 订单总数 50 万行

    # ---- 租户份额（合计 1.0；使 T_C 明显偏小，便于观察"小租户"边界）----
    "tenant_share": {"T_A": 0.40, "T_B": 0.35, "T_C": 0.25},

    # ---- 附录 C §C.12.1 的 14 类"真实脏度" ----
    "promo_windows": {                   # 场景 1：大促尖峰（月-日区间，跨年在年内各自成立）
        "prom_618": ["05-24", "06-20"],          # 含预售期（对齐语义包 time_semantics）
        "prom_double11": ["10-20", "11-11"],
    },
    "promo_day_multiplier": [8.0, 15.0], # 场景 1：大促当日订单量 ×8~15
    "seasonal_amplitude": 0.18,          # 场景 2：月度正弦幅度
    "yearend_uplift": 1.25,              # 场景 2：年末（11/12 月）翘尾
    "sku_powerlaw_alpha": 1.15,          # 场景 3：SKU 销量幂律（越大越集中）
    "refund_rate_range": [0.03, 0.08],   # 场景 4：3–8% 退款
    "partial_refund_share": 0.15,        # 场景 4：部分退款占比小
    "unpaid_rate": 0.15,                 # 场景 5：15% 未支付
    "test_order_rate": 0.003,            # 场景 6：0.3% 测试单
    "empty_interval": {"tenant": "T_C", "year": 2025, "month": 2},   # 场景 7：空区间
    "zero_denominator_sku_count": 40,    # 场景 8：有流量无转化
    "boundary_order_count": 24,          # 场景 9：月首/月末 00:00:00 与 23:59:59
    "outlier_amount": 999999,            # 场景 10：极端大额
    "outlier_count_per_tenant": 5,
    "null_region_rate": 0.02,            # 场景 11：region_code 为空
    "cross_tenant_isomorphic": True,     # 场景 12：三租户同名同构数据（**必须为 True**）
    "missing_category_rate": 0.01,       # 场景 13：少量商品无类目
    "time_inversion_rate": 0.0005,       # 场景 14：pay_time < create_time

    # ---- 流量表（已裁定：稀疏合理分布，不做 2000×730×5 全组合）----
    "traffic_total_rows": 1500000,       # 目标约 150 万行
    "traffic_channels_per_sku_max": 3,   # 单 SKU 单日最多出现在 3 个渠道
}

# 31 个省级行政区（**与语义包 region.value_map 的 31 个省编码一一对应**；
# 不含台港澳 —— 语义包 value_map 未列，故 v_region 也不应有 → selfcheck 断言）
PROVINCES: list[tuple[str, str, str]] = [
    ("110000", "北京市", "华北"), ("120000", "天津市", "华北"), ("130000", "河北省", "华北"),
    ("140000", "山西省", "华北"), ("150000", "内蒙古自治区", "华北"),
    ("210000", "辽宁省", "东北"), ("220000", "吉林省", "东北"), ("230000", "黑龙江省", "东北"),
    ("310000", "上海市", "华东"), ("320000", "江苏省", "华东"), ("330000", "浙江省", "华东"),
    ("340000", "安徽省", "华东"), ("350000", "福建省", "华东"), ("360000", "江西省", "华东"),
    ("370000", "山东省", "华东"),
    ("410000", "河南省", "华中"), ("420000", "湖北省", "华中"), ("430000", "湖南省", "华中"),
    ("440000", "广东省", "华南"), ("450000", "广西壮族自治区", "华南"), ("460000", "海南省", "华南"),
    ("500000", "重庆市", "西南"), ("510000", "四川省", "西南"), ("520000", "贵州省", "西南"),
    ("530000", "云南省", "西南"), ("540000", "西藏自治区", "西南"),
    ("610000", "陕西省", "西北"), ("620000", "甘肃省", "西北"), ("630000", "青海省", "西北"),
    ("640000", "宁夏回族自治区", "西北"), ("650000", "新疆维吾尔自治区", "西北"),
]

# 省会/首府城市（province_code → city_name）。用于 receiver_city 与 shop.city。
PROVINCE_CAPITAL: dict[str, str] = {
    "110000": "北京市", "120000": "天津市", "130000": "石家庄市", "140000": "太原市",
    "150000": "呼和浩特市", "210000": "沈阳市", "220000": "长春市", "230000": "哈尔滨市",
    "310000": "上海市", "320000": "南京市", "330000": "杭州市", "340000": "合肥市",
    "350000": "福州市", "360000": "南昌市", "370000": "济南市", "410000": "郑州市",
    "420000": "武汉市", "430000": "长沙市", "440000": "广州市", "450000": "南宁市",
    "460000": "海口市", "500000": "重庆市", "510000": "成都市", "520000": "贵阳市",
    "530000": "昆明市", "540000": "拉萨市", "610000": "西安市", "620000": "兰州市",
    "630000": "西宁市", "640000": "银川市", "650000": "乌鲁木齐市",
}

CATEGORY_L1: list[str] = [
    "3C数码", "家用电器", "服饰鞋包", "食品生鲜",
    "美妆个护", "家居家装", "母婴玩具", "运动户外",
]


# ============================================================================
# 工具
# ============================================================================
def rng(stream: str, seed: int) -> random.Random:
    """命名子流随机源。跨机、跨 PYTHONHASHSEED 一致。"""
    digest = hashlib.sha512(f"{seed}:{stream}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def allocate(total: int, weights: list[float]) -> list[int]:
    """按权重把 total 拆成整数份（最大余数法，确定性；余数相同时按索引升序）。"""
    s = sum(weights)
    if s <= 0:
        raise ValueError("权重和为 0")
    raw = [total * w / s for w in weights]
    floors = [int(x) for x in raw]
    rem = total - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:rem]:
        floors[i] += 1
    return floors


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def months_between(start: date, end: date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def in_promo(d: date, windows: dict) -> str | None:
    """返回命中的大促 id（prom_618 / prom_double11）或 None。"""
    md = d.strftime("%m-%d")
    for cid, (a, b) in windows.items():
        if a <= md <= b:
            return cid
    return None


def promo_campaign_id(cid: str, year: int) -> str:
    """大促 campaign_id 在**所有租户间同名** —— 这样 dim_date（无 tenant）能对齐，
    也顺带让 V7 变体（漏注入租户谓词）暴露 3 倍行差。"""
    return f"{cid.upper()}_{year}"


def money(x: float) -> float:
    return round(x + 1e-9, 2)


# ============================================================================
# 各表生成
# ============================================================================
def gen_dim_tenant() -> list[tuple]:
    plans = {"T_A": "enterprise", "T_B": "pro", "T_C": "basic"}
    names = {"T_A": "甲租户旗舰集团", "T_B": "乙租户商贸", "T_C": "丙租户小店"}
    return [(t, names[t], plans[t], "2024-01-01 00:00:00") for t in PARAMS["tenants"]]


def gen_region() -> list[tuple]:
    return [(code, pname, region) for code, pname, region in PROVINCES]


def gen_shops() -> tuple[list[tuple], dict[str, list[str]]]:
    """每租户 2–5 家店铺。返回 (rows, tenant→shop_ids)。"""
    r = rng("shop", PARAMS["seed"])
    rows, index = [], {}
    city_pool = list(PROVINCE_CAPITAL.values())
    for ti, t in enumerate(PARAMS["tenants"]):
        n = PARAMS["shops_per_tenant"][t]
        index[t] = []
        for i in range(1, n + 1):
            sid = f"{t}-S{i:02d}"
            # 店铺城市：跨租户给**相近**的城市集合（场景 12 同构），仅顺序不同
            city = city_pool[(i * 3 + ti) % len(city_pool)]
            cat = CATEGORY_L1[(i * 2 + ti) % len(CATEGORY_L1)]
            rows.append((t, sid, f"{t}官方旗舰店{i}号", city, cat, f"2023-{(i % 12) + 1:02d}-15"))
            index[t].append(sid)
    return rows, index


def gen_products(shop_index: dict[str, list[str]]) -> list[tuple]:
    """2000 SKU。场景 12：**三租户共享同一套 sku_id / spu_id / 名称 / 价位** ——
    结构相同、值相近。只有这样才能测出"租户过滤是否生效"。"""
    r = rng("product", PARAMS["seed"])
    n = PARAMS["sku_total"]
    l1n = PARAMS["category_l1_count"]

    # 商品主数据只生成一次，再复制给三个租户（保证同构）
    master = []
    for k in range(n):
        l1 = CATEGORY_L1[k % l1n]
        l2 = f"{l1}-子类{(k // l1n) % 4 + 1}"
        l3 = f"{l2}-细类{(k // (l1n * 4)) % 3 + 1}"
        spu = f"SPU{k // 3 + 1:05d}"
        # 幂律价格：少数高价款
        base = r.choice([19.9, 39.9, 79.0, 129.0, 259.0, 599.0, 1299.0, 2999.0])
        list_price = money(base * r.uniform(0.9, 1.1))
        master.append(dict(
            sku_id=f"SKU{k + 1:05d}", sku_name=f"{l3}-{k + 1:04d}号", spu_id=spu,
            category_l1=l1, category_l2=l2, category_l3=l3,
            list_price=list_price, cost_price=money(list_price * r.uniform(0.45, 0.72)),
            on_sale=0 if r.random() < 0.06 else 1,
            launch_date=(date(2023, 1, 1) + timedelta(days=r.randrange(0, 900))).isoformat(),
        ))

    # 场景 13：类目缺失（**同一批 SKU 在三租户都缺**，保持同构）
    miss = set(r.sample(range(n), max(1, int(n * PARAMS["missing_category_rate"]))))

    rows = []
    for t in PARAMS["tenants"]:
        shops = shop_index[t]
        for k, m in enumerate(master):
            sc = m["cost_price"] if t == "T_A" else money(m["cost_price"] * (1 + 0.02 * PARAMS["tenants"].index(t)))
            rows.append((
                t, m["sku_id"], m["sku_name"], m["spu_id"], shops[k % len(shops)],
                None if k in miss else m["category_l1"],
                None if k in miss else m["category_l2"],
                None if k in miss else m["category_l3"],
                m["list_price"], sc, m["on_sale"], m["launch_date"],
            ))
    return rows


def gen_dim_date(start: date, end: date) -> list[tuple]:
    rows = []
    for d in daterange(start, end):
        cid = in_promo(d, PARAMS["promo_windows"])
        rows.append((
            d.isoformat(), d.year, (d.month - 1) // 3 + 1, d.month, d.isocalendar()[1],
            d.weekday() + 1, 1 if d.weekday() >= 5 else 0,
            promo_campaign_id(cid, d.year) if cid else None,
        ))
    return rows


def gen_campaigns() -> list[tuple]:
    """每租户：范围内的大促 + 每月一条「日常促销」。
    大促 campaign_id **跨租户同名**（见 promo_campaign_id 说明）。"""
    start = date.fromisoformat(PARAMS["date_start"])
    end = date.fromisoformat(PARAMS["date_end"])
    rows = []
    for t in PARAMS["tenants"]:
        for y in sorted({d.year for d in (start, end)} | {y for y in range(start.year, end.year + 1)}):
            for cid, (a, b) in PARAMS["promo_windows"].items():
                s = date.fromisoformat(f"{y}-{a}")
                e = date.fromisoformat(f"{y}-{b}")
                if s < start and e < start:
                    continue
                if s > end:
                    continue
                rows.append((
                    t, promo_campaign_id(cid, y),
                    "618 年中大促" if "618" in cid else "双11 全球狂欢",
                    cid, max(s, start).isoformat(), min(e, end).isoformat(),
                ))
        for (y, m) in months_between(start, end):
            rows.append((
                t, f"NORMAL-{y}-{m:02d}-{t}", f"{y}年{m}月日常促销", "normal_sale",
                f"{y}-{m:02d}-01", (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat(),
            ))
    return rows


def month_weights(months: list[tuple[int, int]]) -> list[float]:
    """场景 2：月度正弦 + 年末翘尾。不含大促（大促进日权重，避免双计）。"""
    w = []
    for i, (y, m) in enumerate(months):
        base = 1.0 + PARAMS["seasonal_amplitude"] * math.sin(2 * math.pi * i / 12)
        if m in (11, 12):
            base *= PARAMS["yearend_uplift"]
        w.append(base)
    return w


def day_weights(days: list[date]) -> list[float]:
    """场景 1（大促尖峰）+ 周末效应。"""
    lo, hi = PARAMS["promo_day_multiplier"]
    w = []
    for d in days:
        x = 1.0
        if in_promo(d, PARAMS["promo_windows"]):
            x *= lo + (hi - lo) * 0.5
        if d.weekday() >= 5:
            x *= 1.15
        w.append(x)
    return w


def gen_orders(shop_index: dict[str, list[str]], product_rows: list[tuple]):
    """生成 v_order_paid 与 v_order_refund。返回 (order_rows, refund_rows, stats)。"""
    lo, hi = PARAMS["refund_rate_range"]
    start = date.fromisoformat(PARAMS["date_start"])
    end = date.fromisoformat(PARAMS["date_end"])
    all_days = list(daterange(start, end))
    months = months_between(start, end)
    mw = month_weights(months)

    # 商品主数据按租户索引（价格/类目/SPU 用）
    prod: dict[tuple[str, str], tuple] = {}
    for row in product_rows:
        prod[(row[0], row[1])] = row

    order_rows: list[tuple] = []
    refund_rows: list[tuple] = []
    stats: dict = {"per_tenant": {}, "promo_rows": 0, "unpaid": 0, "test": 0,
                   "refunded": 0, "partial": 0, "null_region": 0, "inverted": 0,
                   "outlier": 0, "boundary": 0}

    for t in PARAMS["tenants"]:
        total = int(PARAMS["order_rows_total"] * PARAMS["tenant_share"][t])
        per_month = allocate(total, mw)
        shops = shop_index[t]
        # 场景 12：三租户**同一套 SKU 权重**（幂律），保证长尾形状同构
        r_sku = rng(f"sku-pick:{t}", PARAMS["seed"])
        alpha = PARAMS["sku_powerlaw_alpha"]
        sku_ids = [f"SKU{k + 1:05d}" for k in range(PARAMS["sku_total"])]
        weights = [1.0 / ((k + 1) ** alpha) for k in range(PARAMS["sku_total"])]

        r_ord = rng(f"order:{t}", PARAMS["seed"])
        r_rf = rng(f"refund:{t}", PARAMS["seed"])
        r_buyer = rng(f"buyer:{t}", PARAMS["seed"])
        seq = 0
        t_stats = dict(paid=0, unpaid=0, refunded=0, partial=0, promo=0)

        for (mi, (y, m)) in enumerate(months):
            if (t == PARAMS["empty_interval"]["tenant"]
                    and y == PARAMS["empty_interval"]["year"]
                    and m == PARAMS["empty_interval"]["month"]):
                continue                                  # 场景 7：空区间
            mdays = [d for d in all_days if d.year == y and d.month == m]
            per_day = allocate(per_month[mi], day_weights(mdays))
            for di, d in enumerate(mdays):
                for _ in range(per_day[di]):
                    seq += 1
                    sku_id = r_sku.choices(sku_ids, weights=weights, k=1)[0]
                    p = prod[(t, sku_id)]
                    shop_id = shops[r_ord.randrange(len(shops))]
                    qty = 1 if r_ord.random() < 0.78 else r_ord.randint(2, 5)

                    cat1, cat2, cat3 = p[5], p[6], p[7]
                    list_price = p[8]
                    unit = money(max(1.0, list_price * r_ord.uniform(0.72, 1.0)))
                    freight = 0.0 if unit * qty >= 99 else 8.0
                    discount = money(unit * qty * r_ord.uniform(0.0, 0.18))
                    pay_amount = money(unit * qty + freight - discount)

                    # 场景 10：极端大额（单位/聚合正确性）
                    if seq % max(1, total // PARAMS["outlier_count_per_tenant"]) == 0:
                        pay_amount = float(PARAMS["outlier_amount"])
                        stats["outlier"] += 1

                    is_test = 1 if r_ord.random() < PARAMS["test_order_rate"] else 0
                    ctime = datetime(d.year, d.month, d.day,
                                     r_ord.randrange(24), r_ord.randrange(60), r_ord.randrange(60))
                    # 场景 9：边界值 —— 少量订单精确落在月首 00:00:00 / 月末 23:59:59
                    if stats["boundary"] < PARAMS["boundary_order_count"] and seq % 7919 == 0:
                        ctime = (datetime(d.year, d.month, d.day, 0, 0, 0)
                                 if seq % 2 == 0
                                 else datetime(d.year, d.month, d.day, 23, 59, 59))
                        stats["boundary"] += 1

                    paid = r_ord.random() >= PARAMS["unpaid_rate"]
                    if paid:
                        ptime = ctime + timedelta(minutes=r_ord.randint(1, 2880))
                        # 场景 14：时间倒挂（数据质量问题）
                        if r_ord.random() < PARAMS["time_inversion_rate"]:
                            ptime = ctime - timedelta(minutes=r_ord.randint(5, 120))
                            stats["inverted"] += 1
                        # 场景 7 的**配套约束**：不能让支付时间溢出到空区间里。
                        # 实测教训：不夹这一下，上一月最后两天的支付会落进空区间
                        # （T_C 2025-02 实测 145 行）→ V1「空集」变体直接失效。
                        _ei = PARAMS["empty_interval"]
                        if t == _ei["tenant"] and (ptime.year, ptime.month) == (_ei["year"], _ei["month"]):
                            ptime = ctime
                            stats["clamped_into_empty_window"] = stats.get("clamped_into_empty_window", 0) + 1
                        t_stats["paid"] += 1
                    else:
                        ptime = None                      # 未支付 → 无支付时间
                        t_stats["unpaid"] += 1

                    # 场景 11：region_code 为空
                    if r_ord.random() < PARAMS["null_region_rate"]:
                        region_code, rcity = None, None
                        stats["null_region"] += 1
                    else:
                        pc, _, _ = PROVINCES[r_ord.randrange(len(PROVINCES))]
                        region_code, rcity = pc, PROVINCE_CAPITAL[pc]

                    channel = PARAMS["channels"][r_ord.randrange(len(PARAMS["channels"]))]
                    if in_promo(d, PARAMS["promo_windows"]):
                        t_stats["promo"] += 1
                        stats["promo_rows"] += 1

                    # 退款（场景 4）。只有已支付订单才可能退款。
                    rf_status, rtype = "none", None
                    if paid and not is_test:
                        if r_rf.random() < r_rf.uniform(lo, hi):
                            rtype = "partial" if r_rf.random() < PARAMS["partial_refund_share"] else "full"
                            rf_status = "partial" if rtype == "partial" else "refunded"
                            t_stats["partial" if rtype == "partial" else "refunded"] += 1
                            stats["partial" if rtype == "partial" else "refunded"] += 1
                            rtime = ptime + timedelta(days=r_rf.randint(1, 45))
                            ratio = r_rf.uniform(0.30, 0.80) if rtype == "partial" else 1.0
                            refund_rows.append((
                                t, f"RF{seq:08d}", f"{t}-{seq:08d}",
                                money(pay_amount * ratio),
                                rtype, rtime.strftime("%Y-%m-%d %H:%M:%S"),
                                "refunded" if r_rf.random() < 0.75 else "approved",
                            ))
                    if is_test:
                        stats["test"] += 1

                    phone = f"1{r_ord.randrange(3, 10)}{r_ord.randrange(10)}{r_ord.randrange(10)}****{r_ord.randrange(1000, 9999)}"
                    order_rows.append((
                        t, f"{t}-{seq:08d}", f"{t}-P{seq // 2:08d}", shop_id,
                        hashlib.sha256(f"{t}:buyer:{r_buyer.randrange(total // 3 + 1)}".encode()).hexdigest()[:16],
                        sku_id, p[3], cat1, cat2, cat3,
                        pay_amount, money(freight), discount, qty,
                        ptime.strftime("%Y-%m-%d %H:%M:%S") if ptime else None,
                        ctime.strftime("%Y-%m-%d %H:%M:%S"),
                        "paid" if paid else "unpaid", rf_status,
                        region_code, rcity, channel, is_test,
                        phone, f"{rcity or '未知'}示例路{r_ord.randrange(1, 999)}号",
                    ))

        stats["per_tenant"][t] = t_stats
        stats["unpaid"] += t_stats["unpaid"]
        stats["refunded"] += t_stats["refunded"]
        stats["partial"] += t_stats["partial"]

    # 修正：上面 refunded/partial 被累加了两次（t_stats 与 stats），重算一遍保证准确
    stats["refunded"] = sum(v["refunded"] for v in stats["per_tenant"].values())
    stats["partial"] = sum(v["partial"] for v in stats["per_tenant"].values())
    stats["unpaid"] = sum(v["unpaid"] for v in stats["per_tenant"].values())
    stats["paid"] = sum(v["paid"] for v in stats["per_tenant"].values())
    return order_rows, refund_rows, stats


def gen_traffic() -> tuple[list[tuple], dict]:
    """v_traffic_daily —— 稀疏分布（已裁定：不做 2000×730×5 全组合）。

    目标约 150 万行：3 租户 × 730 天 ≈ 2190 个 (租户,日) 单元 × ~685 行/单元。
    稀疏的构造方式 = 每天只有一部分 SKU 有流量、且每个 SKU 当天最多出现在 3 个渠道。
    """
    start = date.fromisoformat(PARAMS["date_start"])
    end = date.fromisoformat(PARAMS["date_end"])
    all_days = list(daterange(start, end))
    dw = day_weights(all_days)
    alpha = PARAMS["sku_powerlaw_alpha"]
    sku_ids = [f"SKU{k + 1:05d}" for k in range(PARAMS["sku_total"])]
    weights = [1.0 / ((k + 1) ** alpha) for k in range(PARAMS["sku_total"])]
    channels = PARAMS["channels"]

    # 场景 8：零分母 —— 指定 SKU 有 UV 但 order_cnt 恒为 0（除零保护用）
    r_zero = rng("zero-denom", PARAMS["seed"])
    zero_skus = set(r_zero.sample(sku_ids, PARAMS["zero_denominator_sku_count"]))

    rows: list[tuple] = []
    stats = {"uv_zero_rows": 0, "zero_denom_rows": 0, "promo_rows": 0, "per_tenant": {}}

    for t in PARAMS["tenants"]:
        t_total = int(PARAMS["traffic_total_rows"] * PARAMS["tenant_share"][t])
        per_day = allocate(t_total, dw)
        r_t = rng(f"traffic:{t}", PARAMS["seed"])
        r_cost = rng(f"adcost:{t}", PARAMS["seed"])
        t_rows = 0

        for di, d in enumerate(all_days):
            target = per_day[di]
            d_iso = d.isoformat()          # 每行一次 isoformat 会造 150 万个临时串，提到日级
            used: set[tuple[str, str]] = set()
            guard = 0
            promo = in_promo(d, PARAMS["promo_windows"]) is not None
            while len(used) < target and guard < target * 6:
                guard += 1
                sku = r_t.choices(sku_ids, weights=weights, k=1)[0]
                n_ch = 1 if r_t.random() < 0.70 else (2 if r_t.random() < 0.83 else 3)
                n_ch = min(n_ch, PARAMS["traffic_channels_per_sku_max"])
                for ch in r_t.sample(channels, n_ch):
                    key = (sku, ch)
                    if key in used:
                        continue
                    used.add(key)

                    # UV：长尾 + 大促放大。极小概率为 0（场景 8 的 V6 变体基础）
                    rank_boost = 1.0 + 6.0 / (1 + int(sku[3:]) / 60)
                    uv = int(max(0, r_t.gauss(12 * rank_boost, 6) * (1.6 if promo else 1.0)))
                    if r_t.random() < 0.01:
                        uv = 0
                        stats["uv_zero_rows"] += 1
                    pv = int(uv * r_t.uniform(1.2, 4.0))
                    cart = int(uv * r_t.uniform(0.05, 0.25))
                    if sku in zero_skus:
                        order_cnt = 0
                        stats["zero_denom_rows"] += 1
                    else:
                        order_cnt = int(uv * r_t.uniform(0.0, 0.09))
                        if uv > 0 and order_cnt == 0:
                            stats["zero_denom_rows"] += 1
                    ad_cost = money(uv * r_cost.uniform(0.30, 2.00)) if ch == "ad" else 0.0
                    if promo:
                        stats["promo_rows"] += 1
                    rows.append((t, d_iso, sku, ch, uv, pv, cart, order_cnt, ad_cost))
                    t_rows += 1
        stats["per_tenant"][t] = t_rows
    return rows, stats


# ============================================================================
# 写库
# ============================================================================
def write_db(out_path: str, payload: dict, vacuum: bool = True) -> None:
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schema.sql")
    schema_sql = open(schema_path, encoding="utf-8").read()

    if os.path.exists(out_path):
        os.remove(out_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    con = sqlite3.connect(out_path)
    cur = con.cursor()
    cur.executescript(schema_sql)

    plan = [
        ("dim_tenant", "INSERT INTO dim_tenant VALUES (?,?,?,?)", payload["dim_tenant"]),
        ("v_region", "INSERT INTO v_region VALUES (?,?,?)", payload["region"]),
        ("v_shop", "INSERT INTO v_shop VALUES (?,?,?,?,?,?)", payload["shops"]),
        ("v_product", "INSERT INTO v_product VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", payload["products"]),
        ("v_campaign", "INSERT INTO v_campaign VALUES (?,?,?,?,?,?)", payload["campaigns"]),
        ("v_dim_date", "INSERT INTO v_dim_date VALUES (?,?,?,?,?,?,?,?)", payload["dim_date"]),
        ("v_order_paid", "INSERT INTO v_order_paid VALUES (" + ",".join("?" * 24) + ")", payload["orders"]),
        ("v_order_refund", "INSERT INTO v_order_refund VALUES (?,?,?,?,?,?,?)", payload["refunds"]),
        ("v_traffic_daily", "INSERT INTO v_traffic_daily VALUES (?,?,?,?,?,?,?,?,?)", payload["traffic"]),
    ]
    for name, sql, rows in plan:
        for i in range(0, len(rows), 50000):
            cur.executemany(sql, rows[i:i + 50000])
        con.commit()

    # 由语义包 value_map 派生的 region_name 已随 v_region 写入；此处只做索引统计
    cur.execute("ANALYZE")
    con.commit()
    if vacuum:
        cur.execute("VACUUM")
        con.commit()

    counts = {}
    for name, _, _ in plan:
        counts[name] = cur.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    con.close()
    payload["_counts"] = counts


# ============================================================================
# CLI
# ============================================================================
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CommerceQL 沙箱数据生成器（确定性）")
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(here, "..", "ecom_sandbox.db")
    ap.add_argument("--out", default=default_out, help="输出 SQLite 路径")
    ap.add_argument("--seed", type=int, default=None, help="覆盖种子（默认取 PARAMS）")
    ap.add_argument("--orders", type=int, default=None, help="覆盖订单总行数（自测用）")
    ap.add_argument("--traffic", type=int, default=None, help="覆盖流量总行数（自测用）")
    ap.add_argument("--dump-params", action="store_true", help="只打印生效参数，不生成")
    ap.add_argument("--no-vacuum", action="store_true", help="跳过 VACUUM（更快，但体积偏大）")
    args = ap.parse_args(argv)

    if args.seed is not None:
        PARAMS["seed"] = args.seed
    if args.orders is not None:
        PARAMS["order_rows_total"] = args.orders
    if args.traffic is not None:
        PARAMS["traffic_total_rows"] = args.traffic

    if args.dump_params:
        print(json.dumps(PARAMS, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    t0 = time.time()
    print(f"[gen] 种子={PARAMS['seed']}  区间={PARAMS['date_start']}~{PARAMS['date_end']}",
          file=sys.stderr)

    step = time.time()
    shop_rows, shop_index = gen_shops()
    print(f"[gen] v_shop            {len(shop_rows):>9,}  {time.time() - step:.1f}s", file=sys.stderr)

    step = time.time()
    product_rows = gen_products(shop_index)
    print(f"[gen] v_product         {len(product_rows):>9,}  {time.time() - step:.1f}s", file=sys.stderr)

    step = time.time()
    order_rows, refund_rows, ostats = gen_orders(shop_index, product_rows)
    print(f"[gen] v_order_paid      {len(order_rows):>9,}  {time.time() - step:.1f}s", file=sys.stderr)
    print(f"[gen] v_order_refund    {len(refund_rows):>9,}", file=sys.stderr)

    step = time.time()
    traffic_rows, tstats = gen_traffic()
    print(f"[gen] v_traffic_daily   {len(traffic_rows):>9,}  {time.time() - step:.1f}s", file=sys.stderr)

    payload = {
        "dim_tenant": gen_dim_tenant(),
        "region": gen_region(),
        "shops": shop_rows,
        "products": product_rows,
        "campaigns": gen_campaigns(),
        "dim_date": gen_dim_date(date.fromisoformat(PARAMS["date_start"]),
                                 date.fromisoformat(PARAMS["date_end"])),
        "orders": order_rows,
        "refunds": refund_rows,
        "traffic": traffic_rows,
    }

    step = time.time()
    write_db(os.path.abspath(args.out), payload, vacuum=not args.no_vacuum)
    print(f"[gen] write_db          {time.time() - step:.1f}s", file=sys.stderr)

    size = os.path.getsize(os.path.abspath(args.out))
    report = {
        "out": os.path.abspath(args.out),
        "bytes": size,
        "mb": round(size / 1024 / 1024, 1),
        "elapsed_s": round(time.time() - t0, 1),
        "params_sha256": hashlib.sha256(
            json.dumps(PARAMS, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16],
        "counts": payload["_counts"],
        "order_stats": ostats,
        "traffic_stats": {k: v for k, v in tstats.items() if k != "per_tenant"},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

