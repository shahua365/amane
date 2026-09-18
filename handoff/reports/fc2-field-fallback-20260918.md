# FC2 字段级多源回退验收

验收日期: 2026-09-18

## 实现边界

- 保留 FC2CMADB、FD2PPV、来源 cookie、host 级限流与共享 WebClient；新增 PPVDataBank、FC2DB、Fourhoi、Paipancon 独立 crawler，并通过 Aggregator 按字段补空。
- 标量、poster / thumb 与 extrafanart 分别按配置优先级选择；低优先级结果不覆盖已有非空字段。每轮根据尚未满足的字段重新选择来源，高优先级来源失败后可以继续访问先前被跳过的候选。
- 图片解析、探测、下载与缓存继续使用 ResourceStore 和 WebClient。URL 稳定去重；来源 Referer、限流、失败分类、冷却和 HTTP 记录保持统一。不新增 HTTP client，不自动处理 Cloudflare 或年龄确认页。
- Fourhoi 仅产生 cover 与 trailer 候选，不抓取 HTML；trailer 只保留 URL。404 是正常 miss，403 / 429 / 503 保留为可观察失败，图片源失败不改变已成功的 metadata 结果。

## 测试

- 新来源测试覆盖三种番号形式、完整与缺图页面、FC2DB selector fallback、相对 URL、重复图片、广告过滤、trailer 候选、404 / 403 / 429 / 503、字段补空、高优先级保护和图片源失败隔离。
- FC2 聚合与图片相关定向测试: 148 passed。
- Ruff lint / format、ty、Pyright、前端 check 与 production build 通过；NAS 候选 Docker build 通过。
- 本机全量测试: 2593 passed、42 skipped、5 failed。4 项为 Windows 符号链接权限 `WinError 1314`；1 项日志捕获测试在全量运行中得到空日志，随后单独重跑 1 passed。失败均不在本轮 FC2 路径，未删除、跳过或放宽测试。

## 公网来源观测

| 来源 | 样本 | 本轮观测 | HTTP / 限制 |
| --- | --- | --- | --- |
| PPVDataBank | 4974556、3193265、4601311 | 实际取得 title、release、runtime、studio、publisher、poster / thumb 与 extrafanart；图片 HEAD / GET 后写入隔离缓存 | detail 与本轮使用的图片请求为 200 |
| FC2DB | 4974556、3193265、4601311 | 未取得可用字段；fixture 已验证 title、actors、poster 与 official link selector | GET 200，但内容为年龄确认页，分类为 `age_verification` |
| Fourhoi | 4601311 | 实际 cover 探测失败；仅验证候选 URL 生成和 same-origin Referer，trailer 未下载、未验证可用 | cover 为 403；快速降级，无绕过 |
| Paipancon | 4974556、4601311 | 4974556 的详情解析得到 poster、相关 extrafanart 与 trailer 候选；4601311 为 miss。未把候选存在写成图片下载成功 | 4974556 detail 为 200；4601311 detail 为 404 |

本轮新增四源未观察到 429、503 或 Cloudflare challenge。既有 FD2PPV 对 4974556 返回 403，分类为 `cloudflare_challenge`，随后同一 WebClient 生命周期内进入 host 冷却，不再重复访问。

## NAS 隔离验收

候选镜像 `amane:fc2-field-fallback-candidate-20260918` 在无生产数据与媒体挂载的临时数据库中运行。生产 `Amane` 未替换、未重启，未删除或移动影片；验收后健康接口仍返回 200。

| 指标 | 现网镜像基线 | 候选镜像 |
| --- | ---: | ---: |
| title | 3 / 3 | 3 / 3 |
| actor | 0 / 3 | 0 / 3 |
| poster | 3 / 3 | 3 / 3 |
| extrafanart | 1 / 3 | 3 / 3 |

- 4974556: 候选保持 FC2CMADB 标量与 poster，PPVDataBank 提供 extrafanart；21 张实际图片通过探测并写入隔离缓存。
- 3193265: FC2CMADB 404 后继续访问 PPVDataBank，title、poster、thumb 与 1 张 extrafanart 成功；JavArchive raw 结果同时保留。
- 4601311: 候选保持 FC2CMADB 标量与 poster，PPVDataBank 提供 2 张 extrafanart。
- 三个样本 actor 均为空，不能把本轮实现描述为 actor 命中率提升。

首次候选验证暴露静态 wave 会永久跳过同 wave fallback 的问题，已改为按未满足字段动态重算来源并新增回归测试；上述结果来自修复后的第二版候选镜像。

## 未验证边界

- FC2DB 本轮公网只能到达年龄确认页，因此其真实详情 selector 可用性仅有 fixture 证据。
- Fourhoi trailer 没有下载或播放验证；cover 在观测样本返回 403。
- Paipancon 只验证详情解析与候选收集，没有把图片候选下载成功作为验收结论。
- 本轮没有部署生产镜像；公网状态和站点 HTML 可能继续变化。
