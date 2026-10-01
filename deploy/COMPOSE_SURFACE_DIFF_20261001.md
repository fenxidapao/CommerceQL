# 部署面盘点 · compose 展开 vs `docs/05 §D.5` vs 盘上运行态（2026-10-01，W7）

> 触发：验收窗口（QA）第一轮 ②③ 两条请办。零花费、零 LLM 调用、**没动共享栈**（未 `up`/未 `down`/未改 compose）。
> 口径：每条读数都标「命令 + 时刻」；**声明面**（compose 渲染）与**运行面**（`docker` / 宿主监听 / 经局域网 IP 可达性）分开写，两者不可互认。
> 时刻：**首测** 2026-10-01 13:2x–13:4xZ；**落笔前重测** 15:5x–16:00Z（北京 10-02 00:00）——两秒都实测过，结论未变（4 个 running 容器、四个端口 `0.0.0.0` 监听、经 LAN IP 的 `api` = `200`、`80/3000/9090` 拒连、`nginx`/`grafana` 镜像 MISSING）。`HEAD` 起点 = `fd5f5f2`。

## 一、全 profile 展开（声明面，`docker compose ... config`）

| 展开方式 | 服务 | 卷 |
|---|---|---|
| 默认（不给 `--profile`） | **5**：`pg` `redis` `api` `pgbouncer` **`web`** | `pg_data` `prom_data` `grafana_data`（3，`config --volumes`） |
| `--profile async --profile observability` | **8**：以上 + `worker`(async) + `prometheus`(observability) + `grafana`(observability) | 同上 3 |
| profile 归属 | `worker: ["async"]`、`prometheus`/`grafana`: `["observability"]`；**`web` 没有 profile**（默认就该起） | — |
| 宿主端口（`config` 渲染） | `api` **published 8000**、`web` 80、`pg` 5432、`pgbouncer` 6432、`redis` 6379、`prometheus` 9090、`grafana` 3000 | `prometheus`/`grafana` 带 `host_ip: 127.0.0.1`；**`api`/`pg`/`redis`/`pgbouncer` 未见 `host_ip`** |
| 镜像 | `api` 与 `worker` = `build:`；`pg`=`pgvector/pgvector:pg16`、`redis`=`redis:7-alpine`、`pgbouncer`=`edoburu/pgbouncer:latest`、`web`=`nginx:1.27-alpine`、`prometheus`=`prom/prometheus:v2.54.1`、`grafana`=`grafana/grafana:11.2.0` | — |

## 二、🔴 与 `docs/05 §D.5` 的差异表（文档契约 vs 盘上声明）

| # | `docs/05 §D.5`（341–421 行）要求 | 盘上 `deploy/docker-compose.yml` | 性质 |
|---|---|---|---|
| 1 | 服务只有 **`web`/`api`/`worker`/`pg`/`redis`（5 个）** | **8 个**（多 `pgbouncer`、`prometheus`、`grafana`） | 🔴 **文档面缺 3 个服务**：`docs/05` 全文 `grafana` = **0 命中**、`prometheus` = **0**、`observability` = **0**、`pgbouncer` = **0 命中**（我用 `re.findall` 复核，不是转述） |
| 2 | **关键点 2：`api` 用 `expose` 不用 `ports`**，理由"后端不经 Nginx 直连会绕过限流与安全响应头" | `api` 有 `ports: "8000:8000"`（`sed -n '128,145p'` 内**无** `expose`/`ports` 关键字命中 ⇒ 端口声明在别段，`config` 渲染出 `published: "8000"`） | 🔴 **直接违背契约第 2 条**，且见 §三 的运行面后果（LAN 可达 200） |
| 3 | 卷 = `pgdata` / `redisdata` / `sandbox` | 卷 = `pg_data` / `prom_data` / `grafana_data` | 🔴 名称与集合都不同：**盘上没有 `redisdata`、没有 `sandbox` 命名卷**；`redis` 段只有 `command: … --appendonly no`（⇒ Redis 不持久化）；`api` 的 sandbox 走 `w7load_sandbox`/别的挂载 ⇒ 需 W0/架构确认"沙箱卷消失"是否刻意 |
| 4 | **关键点 4：`./init` → `docker-entrypoint-initdb.d`**（RLS 策略 + `app_rw`/`app_ro` 两角色 + 列级 GRANT 必须初始化时建立） | **`deploy/init/` 目录不存在**、compose 里无该挂载 | ⚠️ **不是"库没做"**（现网库里确有 FORCE RLS 策略，见 `deploy/loadtest/README.md` 的 RLS 面取证）——是**建立路径从 init 脚本改成了迁移/手工**，而 `docs/05` 没跟。⇒ **新环境按 D.5 复现将缺安全边界初始化**，属交付面缺口（归 W1B/架构确认） |
| 5 | `worker` 无 profile | `worker: profiles ["async"]` | 🟠 差异（可接受，但"异步长查询"默认不起 ⇒ 部署清单该写怎么起） |
| 6 | `pg`/`redis` 未声明宿主端口 | 5432 / 6379 都 published（**无 `host_ip`**） | 🔴 攻击面扩张，见 §三 |
| 7 | `healthcheck` 用 `/healthz/ready` + `start_period: 60s` | ✅ 一致（compose 内 urlopen `healthz/ready`、`start_period: 60s`） | 🟢 相符（7 个关键点里第 5、6 两条也对得上：`:ro` 挂载、`extra_hosts`） |

## 三、运行面（盘上真实状态；与上表不可互认）

| 项 | 现测 | 判读 |
|---|---|---|
| `commerceql` 项目容器 | **4 个 running**：`pg` `redis` `api` `pgbouncer`（`Config.Labels` 逐一体：project=`commerceql`、config_files=`…/deploy/docker-compose.yml`） | 默认集 5 个里 **`web` 没有容器** |
| `web` 起不来的**候选**成因 | `nginx:1.27-alpine` 本地 **MISSING**（`docker images --format` 精确比对）；`grafana/grafana:11.2.0` 也 **MISSING**；`prom/prometheus:v2.54.1` present 但无容器 | ⚠️ **未证**：镜像缺失与"从未 `up` 过这两个服务"同形，我没跑 `pull`/`create` 去分辨（那会动共享项目）⇒ 只登记候选，不写成结论 |
| 宿主监听（`netstat -ano`） | `0.0.0.0:8000` `0.0.0.0:5432` `0.0.0.0:6379` `0.0.0.0:6432` LISTENING；**80 / 3000 / 9090 无监听** | 与 §二-2/6 一致：四个端口绑在全接口 |
| 🔴 **经局域网 IP 可达性实测** | `curl http://10.89.175.120:8000/api/v1/healthz/live` ⇒ **`http_code=200`**；`socket.connect` 到同 IP：**6379 / 5432 / 6432 可达**；80 / 3000 / 9090 `ConnectionRefused`（服务未起） | ⇒ **绕过 nginx 的 api 直连成立（契约第 2 条被破坏且外网面可达）**；**Redis 6379 无 `requirepass` 且 LAN 可建连**；pg/pgbouncer 同样暴露。⚠️ 本机是开发机、IP 是 WLAN 段 ⇒ 风险级别请总控/W0 裁 |
| 观测栈（**W7 本窗地盘**） | 配置齐全（`deploy/observability/` 有 `prometheus.yml`、`alert.rules.yml(+test)`、`grafana/datasource`、`provider.dashboards.yml`、`dashboards/commerceql.json`、`README.md` 385 行）；**容器 0、镜像缺 grafana** | 🔴 **本窗自曝**：`deploy/observability/README.md:11` 自己就写着「**仍未在真实运行时验证过：本窗口没起观测栈、没做过一次抓取、没在 Grafana 里渲染过面板**」⇒ 该声明从 09-18 至今**没有闭合记录**。落地定义第 4 条不成立，一半就在这里 |

## 四、与 QA 第一轮 ①④ 两条的对表（我复算 vs 它的读数）

| QA 的断言 | 我这面独立复算 | 结论 |
|---|---|---|
| ① compose = 8 服务 + 3 卷 | ✅ 逐字同（`config --services` 全 profile = 8；`--volumes` = 3） | 一致 |
| ① 实际容器只有 4 个 | ✅ running 4（`pg`/`redis`/`api`/`pgbouncer`）；⚠️ 若把 `docker ps -a` 全列出来还有 **1 个我留的退出的 `w7load-api_pre0930r11_bak`** ⇒ 报数要带"含不含退出容器" | 一致 + 粒度补一条 |
| ① `web` 无 profile 却无容器 | ✅ 同测 | 一致 |
| ④ `0930r11 = imgID 8c1eb47fb118`（基准 `9998de1`） | ✅ 同值；且我把它 tag 成 `w7load-api:latest` 后 `compose up` 过一轮（第三十一轮，件 `0a236ec`） | 一致 |
| ④ `0928r10 = 4806c5687c4e`、容器 created `2026-09-28T13:39:34Z` | ✅ 逐字同（`docker inspect` 直读） | 一致 |
| ④ `commerceql-api` 镜像 built 2026-09-18 ⇒ 不是被测构建 | ✅ `imgID=7098716adf2e`、容器 `created=2026-09-18T07:44:47Z`、`StartedAt=2026-10-01T04:49:47Z` | 一致 |

## 五、我建议但不擅自做的（都要总控批，因为会动共享栈/别人的契约）

1. 🔴 **最小安全收敛（建议优先）**：给 `api`/`pg`/`redis`/`pgbouncer` 的 published 端口加 `host_ip: 127.0.0.1`，或按 `docs/05 §D.5` 关键点 2 把 `api` 改回 `expose`（前端只走 `web`）。⇒ 代价 = **`docker compose up` 会重建这四个容器**（共享栈重启 = 集体决定，且本窗规矩是"单窗不重启共享栈"）。⇒ 谁可能受影响：一切用 `127.0.0.1:8000/5432/6379` 的本机工具不受影响；**只有**从别的机器经 LAN 连的用法会断（我这面没证据表明存在，未查）。
2. `deploy/init/` 的复位（或把 `docs/05 §D.5` 关键点 4 改成"由迁移建立"）⇒ **文档面归 W0/架构**，我不动 `docs/`。
3. 观测栈运行面闭合 = **我的地盘、我可以做**：`docker compose --profile observability up -d prometheus grafana`（需拉 grafana 镜像 ⇒ **联网 + 起两个新容器**；3000/9090 已绑回环 ⇒ 不触发"暴露 3000 要先设 Grafana 口令"那条纪律）。⇒ **等总控一句"起"**：我可以顺带补 `README.md:11` 那句自曝的闭合证据（一次抓取 + 一次面板渲染 + `/metrics` 抓取目标全 up）。
4. ⚠️ 命名反着长那件（QA ③）：`w7load-api_pre0930r11_bak` 的镜像确实是 **`0928r10`（pre-fix）**。名字含义 = "**0930r11 之前那批**的备份容器"，不是我起的规范名。⇒ 我这面处置 = 已在 `deploy/loadtest/README.md §三.0.1ac` **逐对象标面**（名字不作为身份判据，判据 = `Config.Image` + imgID + 两层身份证据）。

## 六、复算命令（全部零花费、只读）

```bash
cd CommerceQL/deploy
# 1) 声明面：全 profile 展开
docker compose -f docker-compose.yml config --services
docker compose -f docker-compose.yml --profile async --profile observability config --services
docker compose -f docker-compose.yml --profile async --profile observability config --volumes
docker compose -f docker-compose.yml --profile observability config | grep -E "host_ip|published:"
# 2) 运行面：逐容器镜像标面（名字不可信，认 Config.Image）
docker ps -a --format '{{.Names}}' | while read n; do docker inspect --format "{{.Name}} | {{.Config.Image}} | imgID={{.Image}} | created={{.Created}} | state={{.State.Status}} | started={{.State.StartedAt}}" "${n#/}"; done
docker images --format "{{.Repository}}:{{.Tag}}" | grep -cE "nginx:1.27-alpine|grafana/grafana:11.2.0|prom/prometheus:v2.54.1"
# 3) 宿主监听 + LAN 可达性（这两条决定 §三 的安全结论）
netstat -ano | grep LISTENING | grep -E ":(80|3000|5432|6379|6432|8000|9090) "
curl -s -o /dev/null -w "%{http_code}\n" http://<本机 WLAN IP>:8000/api/v1/healthz/live
# 4) 文档面命中数（别抄我的，自己跑）
python -c "import re,pathlib;t=pathlib.Path('../docs/05_附录D_环境依赖与部署清单.md').read_text(encoding='utf-8');print({k:len(re.findall(k,t,re.I)) for k in ['grafana','prometheus','observability','pgbouncer','worker','web']})"
```
