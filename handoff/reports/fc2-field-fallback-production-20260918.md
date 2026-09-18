# FC2 字段级多源回退生产灰度验收

验收日期: 2026-09-18

## 验收结论

总体状态: `PARTIAL`

本次生产灰度未标记为 `PRODUCTION VERIFIED`。生产实例稳定运行，两个历史 FC2 缺图样本完成按 ID 重新刮削，PPVDataBank 成功补充字段并写入 extrafanart 缓存；用户指定的三个番号不在当前生产数据库中，无法在不创建新 metadata 的前提下验收。Fourhoi、Paipancon 以及 FC2CMADB 完整字段时的低优先级跳过行为未在本次生产样本中触发。

`FC2DB` 年龄确认、`Fourhoi` 403、演员缺失属于独立后续事项，不作为本次功能成功依据。

## 代码与工作区基线

- 本地分支为 `codex/source-session-resilience`，验收基线 commit 为 `7ddfc8a53840f4e39d5c1029a4b39638a6b14e09`。
- 验收开始前已通过远端分支页面确认该分支指向上述 SHA；`main` 未修改。
- `tests/net/test_resilient_requests.py` 的工作区差异仅为行尾假修改。恢复后文件 hash 为 `a0f357eab47822b99caa4166576f9ffc48ef8306`，与基线版本一致，工作区无未提交修改。
- 生产验收后定向测试结果为 `VERIFIED`: 179 passed，39 warnings。warning 为 Windows `curl_cffi` 事件循环提示，未修改业务代码。

## 部署基线与回滚点

部署前 Amane 使用镜像 `amane:source-session-resilience-6b8a217`，镜像 ID 为 `sha256:ff139df0da8a33f077070c483387adfc9d35400fcee9fe02dc114f8bcee01620`，OCI revision 为 `6b8a21717741135de28f15f1053ae2c146dd8fa2`。

生产备份目录为 `/volume3/docker/amane/backups/fc2-field-fallback-deploy-20260918T202500+0800`，包含部署前 compose、配置、数据库、部署清单和 SHA256 清单；数据库备份 hash 为 `c51bef495f1a604ca2256dae12be69971c310db129324a139c5f6fcdabb2b578`。数据库源文件与备份均通过完整性检查。

部署前数据库计数为 metadata 737、media_files 784、resources 9049、tasks 16539；媒体挂载 `/volume2/video/学习资料` 为 22626 个文件、4431569621460 字节。

回滚点由以下两部分组成:

- 恢复 `compose.yaml.before` 和 `config.toml.before`，使用部署前镜像重新创建 `Amane`；本次没有数据库 schema 迁移。
- 如出现数据库一致性或资源写入异常，保留当前日志后再使用备份目录中的 `amane.db` 恢复数据库。默认不恢复数据库，以保留本次已完成任务的审计记录。

## 生产部署

基于目标 commit 在 NAS 构建并部署镜像 `amane:fc2-field-fallback-7ddfc8a`，镜像 ID 为 `sha256:f4f98a0ea3c1a979cec77e2d330e85f6c35e7d8ecf6c3f72d5c1cdce8bcd47ef`，OCI revision 与目标 commit 一致。

生产 compose 只修改了 Amane 的 image 字段。配置只将 FC2 content route 扩展为已在该 commit 中实现的四个来源及现有来源；配置前后除该 route 外完全一致，未修改 Cookie、rate_limit 或其他运行参数。部署期间仅重建 Amane，未修改、删除或移动媒体文件，未执行 organize。

部署后结果为 `VERIFIED`:

- 容器 `running`、`healthy`、重启次数 0；`/api/health` 返回 HTTP 200，版本 `0.14.0`。
- worker `paused=false`；数据库 `integrity_check=ok`，metadata 737、media_files 784、resources 9053、tasks 16541。
- `/api/libraries` 返回 2 个 library；`/api/media?limit=1` 返回 HTTP 200、总数 784。
- 媒体挂载仍为 22626 个文件、4431569621460 字节，与部署前一致。
- 验收期间暂停的两个 schedule 已恢复为部署前的启用状态；验收结束时无 QUEUED/RUNNING 任务。

启动日志存在既有的 inotify watch limit warning。媒体库 API 加载正常，但 watcher 的长期行为未在本次验收中验证，标记为 `UNVERIFIED`。

## 生产样本

用户指定的 `3193265`、`4974556`、`4601311` 在当前生产 metadata 中不存在。为避免创建 metadata、导入媒体或触碰全库，未使用隔离环境结果替代生产结果；指定样本覆盖状态为 `BLOCKED`。

实际执行两个现有历史缺图 metadata 的按 ID 重新刮削任务。API 任务类型为定向 `SCRAPE`，语义为只重新刮削既有 metadata；未执行全库 `RESCRAPE`，未创建媒体文件，未执行 organize。严格按 `TaskType.RESCRAPE` 的指定番号验收未实现，标记为 `PARTIAL`，原因是现有 RESCRAPE handler 仅按更新时间选取批次，不能安全指定这两个番号。

| metadata | 任务 | 结果 | 最终字段来源 | 图片结果 |
| --- | ---: | --- | --- | --- |
| 647 / FC2-3193266 | 16540 | `VERIFIED`，DONE | title、release、runtime、studio、publisher: `ppvdatabank`；tags、directors、series、plot: `javarchive` | poster/thumb locator 保留多来源；2 条 `ppvdatabank` extrafanart 写入 ResourceStore |
| 648 / FC2-3192152 | 16541 | `VERIFIED`，DONE | title、release、runtime、studio、publisher: `ppvdatabank`；tags、directors、series、plot: `javarchive` | poster/thumb locator 保留多来源；2 条 `ppvdatabank` extrafanart 写入 ResourceStore |

两条样本的最终 poster/thumb locator 均包含 `fc2cmadb.com`、`img.javstore.net`、`ppvdatabank.com` 来源；647 的 extrafanart provenance 包含 `javarchive` 与 `ppvdatabank`，648 的 extrafanart provenance 包含 `ppvdatabank`。actors 为空，不纳入本次字段回退结论。

验收前资源总数为 9049，验收后为 9053。新增的 4 条 `ppvdatabank` extrafanart ResourceStore 记录均有 content hash，容器内实际文件存在，数据库记录大小与文件大小一致，图片写入状态为 `VERIFIED`。未将仅有 locator 的候选计为下载成功。

## 逐站点结果

两条任务的 `eligible_sites` 均包含 `fc2cmadb`、`fd2ppv`、`ppvdatabank`、`fc2db`、`fourhoi`、`paipancon` 及现有 FC2 来源；实际 `sites_queried` 均为:

`fc2cmadb`、`fd2ppv`、`ppvdatabank`、`fc2db`、`fc2`、`javarchive`、`javdb`、`freejavbt`、`javbus`、`fc2club`。

| 来源 | 16540 | 16541 | 生产判定 |
| --- | --- | --- | --- |
| FC2CMADB | HTTP 404，`not_found` | HTTP 404，`not_found` | 单源失败未阻断 metadata，`VERIFIED` |
| FD2PPV | HTTP 403，`cloudflare_challenge` | `cooldown`，未产生新的上游请求 | 未绕过、未高频重试，`VERIFIED` |
| PPVDataBank | `ok`，补充标量与图片字段 | `ok`，补充标量与图片字段 | 历史缺图样本补充成功，`VERIFIED` |
| FC2DB | `network` | `age_verification` | 失败被隔离，未写入错误详情；年龄确认详情成功仍为后续事项 |
| Fourhoi | 未调用 | 未调用 | 前序 artwork 候选已满足，403 候选 miss 未在生产样本触发，`UNVERIFIED` |
| Paipancon | 未调用 | 未调用 | 前序 artwork 候选已满足，生产 404/miss 未触发，`UNVERIFIED` |
| FC2 / JavDB / FreeJavBT / JavBus / FC2Club | 各有 `no_usable_metadata`、`network` 或 `cooldown` | 各有 `no_usable_metadata` 或 `cooldown` | 均未阻断主 metadata scrape，`VERIFIED` |

生产日志中观察到 HTTP 403 与 404；本次样本没有 429 或 503。FC2DB 年龄确认记录只有 `age_verification` 分类，没有把确认页写成 metadata；该来源详情页的可用性不作成功结论。

## 验收项状态

- `VERIFIED`: 健康、worker、数据库完整性、library/media API、部署隔离、媒体文件不变、按字段记录 provenance、PPVDataBank 补充历史缺图样本、ResourceStore 实际写入、FC2CMADB/FD2PPV/FC2DB 单源失败不阻断主任务、FD2PPV Cloudflare/cooldown 不绕过。
- `PARTIAL`: 生产仅覆盖两个替代样本；本次按 ID 使用定向 SCRAPE 代替全库 RESCRAPE；低优先级来源跳过行为仅由未调用记录间接显示。
- `UNVERIFIED`: FC2CMADB 已提供完整字段时不调用全部低优先级来源；Fourhoi 403 只造成 artwork candidate miss；Paipancon 生产 miss；watcher 长期稳定性；演员字段命中。
- `BLOCKED`: 用户指定的 3193265、4974556、4601311 不存在于当前生产数据库，无法执行真实生产样本验收。

## 后续独立事项

1. 取得指定三个现有生产 metadata 或由维护者明确允许导入后，再执行同范围的生产灰度；不得使用隔离数据库结果替代。
2. 单独安排 Fourhoi 403 artwork candidate miss 与 Paipancon miss 的生产样本，继续禁止 Cloudflare 绕过、Cookie 新增和 rate_limit 调整。
3. 单独安排 FC2DB 年龄确认页详情可用性验证；年龄确认页必须继续分类为失败。
4. 单独处理 actor 0/3（或本次两个样本 actor 为空）问题，不与 field fallback 验收合并。
