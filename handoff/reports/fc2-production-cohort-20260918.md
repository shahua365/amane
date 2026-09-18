# FC2 生产 cohort 验证

日期: 2026-09-18

状态: `PARTIAL`; 生产配置恢复与回读为 `BLOCKED`。

## 范围

本轮仅检查既有 15 个生产 SCRAPE cohort 任务及其已有结果，不重新部署、不修改代码、不重新提交任务，也不执行全库 RESCRAPE/ORGANIZE、metadata 创建、媒体移动或删除、Cloudflare/年龄验证绕过、站点认证或限速配置修改。

后续执行环境无法继续连接生产环境，因此文档更新前没有再次确认服务运行状态。

## 任务结果

生产日志确认 15 个任务均已存在并完成，没有重新提交。任务级实例标识、媒体记录标识、具体样本号和逐任务时间不进入公开交接。

## 来源分类

| 来源 | 已确认结果 | 证据边界 |
| --- | --- | --- |
| FC2CMADB | `ok` 10/15; `not_found` 5/15 | 完整 cohort 计数已确认 |
| FD2PPV | `cooldown` 15/15 | cohort 内均命中已有 cooldown，没有据此认定发生新的上游成功请求 |
| FC2DB | `age_verification` 15/15 | cohort 内全部为年龄确认阻塞；未绕过验证 |
| PPVDataBank | 至少 5 个 ok、至少 1 个 not_found | logger 部分记录缺少 site 字段，完整 15 样本计数 `UNVERIFIED` |
| FreeJavBT | 至少 4 个样本为 network timeout | 其余样本分类 `UNVERIFIED` |
| FC2Club | 至少 2 个样本为 network failure | 其余样本分类 `UNVERIFIED` |
| JavBus | cohort 中观察到多条 HTTP 404/not_found | 完整 15 样本计数 `UNVERIFIED` |
| Paipancon | 至少 1 个样本为 not_found | 其余样本分类 `UNVERIFIED` |
| Fourhoi | `UNVERIFIED` | 未取得足够的任务级生产日志证据 |
| HTTP 403 | 本轮窄查询未观察到 `status=403` | 不等同于证明 cohort 没有 Cloudflare challenge |
| Cloudflare challenge | `UNVERIFIED` | 对应生产日志查询未能继续执行 |

## 图片与 ResourceStore 证据

以下验收项没有取得足够的生产证据，继续标记为 `UNVERIFIED`：

- 15 个样本 scrape 前后 poster/thumb/extrafanart 的逐项完整度；
- 各 metadata 字段及 poster/thumb/extrafanart 的最终 provenance；
- 本轮 cohort 对 ResourceStore 的实际新增记录、对应缓存文件路径及文件存在性；
- locator 对应的远端图片是否完成下载、完整解码并写入 ResourceStore。

因此本报告不把图片 locator 存在、crawler `scrape ok` 或 `fields_resolved` 计数视为图片下载成功。

## 生产配置恢复

用户已授权恢复 library 1/2 的 `automation=scrape` 与 schedule 1/2 的 `enabled=true`，并要求修改后重新读取生产配置。执行环境随后无法建立生产执行链路；生产认证读取也被自动安全审查拒绝。由于没有取得修改与后续回读的现场结果，本轮没有把任何生产配置恢复写成成功。

当前状态：library 1/2 自动化与 schedule 1/2 启用状态均为 `BLOCKED / UNVERIFIED`。旧交接中关于暂停或已恢复的历史记录不能替代当前回读。

## 剩余瓶颈

来源失败模式中，FC2DB 的 `age_verification` 为 15/15，FD2PPV 的 `cooldown` 为 15/15；FC2CMADB 已覆盖 10/15，另有 5 个真实 not_found。这些证据说明来源可用性仍存在稳定限制。

实际缺图瓶颈仍不能排序。缺少前后图片完整度、最终 provenance 与 ResourceStore 落盘证据时，无法判断 FC2DB、Fourhoi、Paipancon、actor 或其它来源中哪一项对剩余缺图贡献最大。后续应先恢复只读执行链路并补齐上述证据，再确定下一项实现工作。
