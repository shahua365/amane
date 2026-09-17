# 维护交接

更新时间: 2026-09-17

## 当前版本

- Fork: `shahua365/amane`; 工作分支 `codex/fc2-multisource-scrapers`.
- 通用图片改造代码: `05d27836cbc9938ebd1657d28c4dba47da4270ef`; 后续交接提交只修改文档.
- NAS 已部署 `00527a0ef3510b795d4f8c9bd2cdc5983d0e8ed5`, 版本 v0.14.0; `main` 保持 `5de9f9ae463169942f1ed45314989a2033ee835c`.

## 通用图片回退

- metadata 与 artwork 获取分离; 已返回的 poster / thumb URL 去重保留, 缺图时仅向当前路由和字段黑名单允许的已注册来源补图. 补图阶段不覆盖标题、演员、日期等字段, 不混入来源 raw 标量快照.
- 优先级: 全部可用本地缓存 → 当前已返回候选 (按各自字段优先级) → 尚未查询的合资格 crawler 图片字段 → 用户手工 URL / 本地文件. poster 与 thumb 分别选源; 首个完整解码成功的候选立即缓存, 其余候选保留.
- 远端候选顺序 HEAD / GET; HEAD 405 / 501 可继续 GET. 拒绝 HTML、损坏图片、非法 URL 和超出图片限制的文件, 同次补图不重复请求失败 URL. 按 URL 串行获取并复用成功缓存, 临时文件校验后原子写入 Resource.
- HTTP 403 / Cloudflare challenge 标记 BLOCKED; 同一 WebClient 生命周期内停止受限主机的后续请求, 包括排队和重定向. 不自动解除, 客户端重建后重新判定; 状态不跨进程持久化. 爬虫失败在任务报告显示 BLOCKED, 图片请求状态保留在 HTTP 记录和日志.
- ORGANIZE 先检查全部已缓存候选, 缓存可用时没有远端请求. 缓存丢失且允许复制资源时仍可尝试远端. 强制重新刮削保留可用的本地图片; 既有裁剪 / 超分设置继续生效.
- 手工入口为 `POST /api/metadata/{metadata_id}/artwork-fallback`, 请求指定 `kind=poster|thumb`, 并且仅指定 `url` 或 `path` 一项. 现有候选全部不可用时才使用手工输入; 本地路径受 safe_dirs 约束, 导入后删除原文件不影响缓存. 本轮提供 API 入口, 未新增专用上传界面.

## 验证

- PASS: Ruff lint / format、Pyright、ty; OpenAPI / TS client 已生成, 前端 check 与 production build 通过.
- PARTIAL: 本机全量 Python 2557 passed、42 skipped、4 failed; 四项失败均为既有 Windows 符号链接权限 WinError 1314. 随后补充手工缓存保留和非法 URL 测试, 相关测试组分别 60 passed 与 32 passed. 未删除或放宽原有测试断言.
- PASS: [GitHub CI #4](https://github.com/shahua365/amane/actions/runs/35196230706) 全部通过, 包含 Ubuntu `just ci`、Windows `just ci-windows` 与 Docker build. Ubuntu 2587 passed、18 skipped; Windows 2563 passed、42 skipped.
- PASS: CI Docker 镜像 `amane-ci:05d27836cbc9938ebd1657d28c4dba47da4270ef`, image ID `sha256:f2467527769da3db19db7e8a835dd98cdec9308a45b388b6b6d0d3e23db1fbbd`; NAS 独立构建结果见下文.
- VERIFIED: 合成图片覆盖候选回退、完整解码、缓存写入、缓存优先整理、并发去重、手工文件与 URL、标量不覆盖、字段独立优先级、403 / challenge 停止请求和重定向传播.
- NOT TESTED: 本轮未搜索、查看、访问或新增内容来源, 未针对具体影片编写逻辑. 公网站点可用性和具体影片封面均不属于本轮验收.

## NAS 部署验收

- 镜像 `amane:artwork-00527a0`, ID `sha256:15a0f519233f469937dc857aa0eb3247c03a6e28675cc300add8c0efde5c4241`, revision label 对应部署 SHA; NAS 构建完成后切换生产 `Amane`.
- 禁网、无媒体挂载的数据库副本完成迁移和合成图片缓存验证. 生产 revision 从 `668e214b1a76` 升至 `022f8eb0d22f`; quick_check 为 ok, 外键错误 0; metadata 737、media_files 784、resources 8918、tasks 15644、libraries 2 均保持数量.
- 生产健康接口与 Web 返回 200, 版本 v0.14.0; 容器 healthy、重启计数 0、启动错误计数 0. 配置与 token 字节一致, 媒体挂载、AMANE 环境变量、运行身份及重启策略保持现场状态.
- 两个媒体库 automation 暂停为 NONE, 两个定时任务暂停, 无待执行任务或订阅; 遵守本轮不访问内容来源的范围. 原自动化设置保存在停机备份, 后续恢复须明确授权.

## 运维与历史边界

图片改造未新增迁移, 但 NAS v0.11.0 升至 v0.14.0 包含上游迁移. 项目 `backups/artwork-deploy-20260917` 保存现场容器参数、部署清单和 rollback.py; 数据目录同名备份的 final 子目录保存停机一致性数据库、配置、token 和自动化设置. 均仅保存 NAS 本地. 原镜像保留; 回滚脚本已检查语法但未执行, 将停止新服务、保留失败数据库文件并恢复旧库、旧镜像及原自动化设置. 禁止仅切换旧镜像而继续使用已升级数据库.

此前 FC2 多源工作和 NAS 验收仅代表对应日期的旧代码结果, 见 [来源审计](reports/fc2-audit-20260915.md)、[NAS 验收](reports/fc2-nas-20260916.md) 与 [历史](HISTORY.md). FD2PPV crawler 保留; 本轮没有实现任何验证码、Cloudflare 验证绕过、指纹伪造或 clearance 获取.
