# deploy/w2b_materialize —— 四个脚本的**收件副本**（不是新真相）

来源：W2B 工作区根目录 `_w2b_u112_{materialize,probe,control,verify_read}.py`（09-21 14:4x 逐字节复制，未改动一个字符）。
原因：那四个文件在**仓库之外**（`git status` 报 `outside repository`）⇒ 与 U-112 落地前的五文件同款孤本风险，而 W7 复现判据④ 依赖 materialize + verify_read。
归属：**作者仍是 W2B**。W7 只做两件事——存档、以及在自己目录里给判据④ 留一条可跑路径。**权威版本以 W2B 的仓库内提交为准**；两边不一致时以 W2B 为准并请通知 W7 重取。
用法：`cd 仓库根 && .venv/Scripts/python.exe deploy/w2b_materialize/_w2b_u112_materialize.py`（前置：pg healthy、Ollama 可达、bge-m3 在册）。

⚠️ 与 `tests/integration/test_semantic_materialization.py` 的冲突（W2B 实证）：那个夹具会把 `app.embed_doc` 的 embedding/tsv 清回 NULL **且测试全绿** ⇒ 物化之后不要跑 `tests/integration`，且每次预检前先复核 `(197,197,197)`。
