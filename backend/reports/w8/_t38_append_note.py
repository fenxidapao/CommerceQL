import json
import pathlib

MARK = "T-38 身份取证"
VOID_ADD = (
    " ｜ T-38 身份取证（作废格＝预热，不进任何分母、不进 P95 样本）："
    "本件 build_identity 为**跑后补打**（attested_at 2026-10-06T04:33:24Z 比 started_at "
    "2026-10-06T04:25:06Z 晚 8m18s），跑前另有**独立一次**取证（04:24:43Z，逐件 SAME 18/18，"
    "归档 backend/reports/w8/evidence/t38/build_identity_pre_run.json）；"
    "全量聚合三面相等 = 158/158 件（换代后的尺），层 3 RUN_SCOPED_STATE_FIELDS present size=47；"
    "被测 = 容器 commerceql-api-1 / 镜像 sha256:ca34ea791a81… / 容器 Created 2026-10-05T15:19:26Z"
    "（本轮**未重建**镜像，当期性只由逐件与全量 md5 自证）。"
)
MAIN_ADD = (
    " ｜ T-38 身份取证（主批）：分母 = admission.admitted = 9（429 拒 20 条按 U-106 排除在 P95 之外）；"
    "报价笔 67be6b0 的 committer date = 2026-10-06T04:24:29Z，**早于**本回执 started_at "
    "2026-10-06T04:25:59Z（差 90 秒，尺见 backend/reports/w8/t38_assembled.json 的 b 格）；"
    "build_identity 为**跑后补打**（04:33:18Z），跑前 04:24:43Z 已独立取过一次，逐件 18/18 SAME ＋ "
    "全量 158 件三面相等 ＋ 层 3 present；镜像未在本轮重建（Created 2026-10-05T15:19:25Z）；"
    "样本 9 < MIN_ADMITTED_FOR_P95 = 20 ⇒ G-6 本批**不可引用**（caveat 原文见 g6_caveat）。"
)

for path, add in (("deploy/loadtest/t38_c3n30_warm.json", VOID_ADD),
                  ("deploy/loadtest/t38_c3n30_main.json", MAIN_ADD)):
    p = pathlib.Path(path)
    d = json.loads(p.read_text(encoding="utf-8"))
    if MARK in d.get("note", ""):
        print(f"跳过（已补过）：{path}")
        continue
    d["note"] = d.get("note", "") + add
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"note 已补：{path}（{len(d['note'])} 字）")
