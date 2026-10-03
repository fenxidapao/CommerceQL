"""A5：compose 的**声明面**必须只把宿主端口绑到回环，且宿主端口不重号。

为什么这张单值得一条契约测试（不是"顺手加个 lint"）
--------------------------------------------------------------------------
2026-10-01 的现测：`deploy/docker-compose.yml` 全文没有 `host_ip` ⇒ 6379／5432／6432／8000
绑在 `0.0.0.0`，而 U-134 裁的是"**不轮换**属主口令 + 显式豁免登记"。豁免登记的**前提**就是
"这组本机引导凭据只有本机能拨到" —— 端口对外开，前提就塌了，那一支裁定随之不成立
（QA O-11 当年点出的正是这个耦合）。

所以这里守的是两条，缺一条都会静默回退：
1. **每个**发布端口的宿主侧地址是回环（`127.0.0.1`；`::1` 不算，本项目没有 IPv6 需求）；
2. **宿主端口不重号** —— 这条是本轮自己踩出来的：改 A5 时把 `web` 的那行误写成
   `127.0.0.1:8000:8000`，与 `api` 撞号，同时把容器侧 80 换成没人监听的 8000。
   `docker compose config` 不报错、yaml 也解析得过 ⇒ 只有把"重号"变成断言才拦得住。

⚠️ 本测试量的是**声明面**。运行面（`docker ps` 的 PORTS 列）要等一次 recreate 才跟着变，
   所以"本测试绿"不等于"当前运行的栈只绑回环"—— 报数时必须点名是哪一面（同 U-134 的口径）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

_COMPOSE = Path(__file__).resolve().parents[3] / "deploy" / "docker-compose.yml"
_LOOPBACK = frozenset({"127.0.0.1", "localhost"})


def _published(raw: object) -> tuple[str, str, str]:
    """归一出一条发布记录 → (宿主地址, 宿主端口, 容器端口)，长短两种语法都吃。"""
    if isinstance(raw, dict):  # 长语法：{mode, host_ip, published, target}
        host_ip = str(raw.get("host_ip", ""))
        published = str(raw.get("published", ""))
        target = str(raw.get("target", ""))
        return host_ip, published.split("/")[0], target.split("/")[0]
    text = str(raw)
    proto = ""
    if "/" in text:
        text, proto = text.rsplit("/", 1)
        proto = "/" + proto
    parts = text.split(":")
    if len(parts) == 3:  # "127.0.0.1:8000:8000"
        return parts[0], parts[1], parts[2] + proto
    if len(parts) == 2:  # "8000:8000" —— **没有**宿主地址段 ⇒ 落到 0.0.0.0
        return "", parts[0], parts[1] + proto
    return "", parts[0], parts[0] + proto  # "8000"


def test_every_published_port_is_loopback_bound() -> None:
    assert _COMPOSE.exists(), "deploy/docker-compose.yml 不存在 —— 本测试验的是空气"
    doc = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    offenders: list[str] = []
    seen: dict[str, str] = {}
    for name, svc in (doc.get("services") or {}).items():
        for entry in svc.get("ports") or []:
            host_ip, published, _target = _published(entry)
            if host_ip not in _LOOPBACK:
                offenders.append(f"{name}: {entry!r} → 宿主地址 {host_ip!r}（空 = 0.0.0.0）")
            owner = seen.get(published)
            if owner is not None:
                offenders.append(f"{name}: 宿主端口 {published} 与 {owner} 重号")
            seen.setdefault(published, name)
    assert not offenders, (
        "compose 声明面存在对外发布或宿主端口重号 —— U-134「不轮换 + 显式豁免登记」的前提是"
        "「只有本机能拨到」，端口开到 0.0.0.0 会让该前提塌：\n  " + "\n  ".join(offenders)
    )


def test_loopback_guard_bites_on_the_unconverged_shape() -> None:
    """正对照：尺子必须咬得住"没收窄"的写法（`5432:5432` 与缺 host_ip 的长语法）。

    ⚠️ 这里一律用**裸串**而不是带引号的串 —— YAML 里 `"5432:5432"` 的引号是语法不是内容，
    把引号一起写进本断言会得到 `('\"127.0.0.1', '80', '80\"')` 这种形状，
    于是"归一函数"看起来错了、其实错的是尺子的输入（实测红过一次）。
    """
    for bad in ("5432:5432", "6379:6379", {"published": "8000", "target": "8000"}):
        assert _published(bad)[0] not in _LOOPBACK, f"归一函数把没收窄的形态读成了回环：{bad!r}"
    assert _published("127.0.0.1:80:80") == ("127.0.0.1", "80", "80")
    assert _published({"host_ip": "127.0.0.1", "published": "9090", "target": "9090"})[:2] == (
        "127.0.0.1",
        "9090",
    )
