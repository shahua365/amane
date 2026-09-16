# 维护交接

更新时间: 2026-09-16

## 当前版本

- Fork: `shahua365/amane`; 工作分支 `codex/fc2-multisource-scrapers`, 基于 `custom` 的 `14aa4193c620f719c0fc22e33c025506dd8fd9a5`.
- `main` 保持官方 v0.14.0 (`5de9f9ae463169942f1ed45314989a2033ee835c`), 未修改或推送.
- 验证代码提交 `3bbdc5a502063e320437f20ec929e167b4699b9a`; 后续仅追加交接文档. NAS 生产仍为独立 v0.11.0 镜像.

## 功能与验收

- PASS: FC2PPVDB 运行注册删除, FC2CMADB 安全配置迁移与 FD2PPV 源码迁入; 保留年龄验证误判修复.
- PASS: 官方 FC2 查询/Cookie/日期/时长补全; 新增实页结构确认的 JavArchive; FC2 原始标题继续保存在 raw.
- PASS: 同主机共享限速、重试/重定向限速、有界退避、Retry-After、404 负缓存、缓存优先资源获取.
- PASS: Ruff lint/format、Pyright、ty、前端 check 与 production build. 保留既有前端 warning, 未顺带修改无关组件.
- PARTIAL: 本机全量 Python 2535 passed、42 skipped、4 failed; 四项失败均为既有 Windows 符号链接权限 WinError 1314, 没有删除或弱化测试.
- UNVERIFIED: 私有 crawler fixture 无权限; 未覆盖的公网行为不能由 unit tests 推断.
- PASS: 最终代码 [GitHub CI](https://github.com/shahua365/amane/actions/runs/35064932961) 全部成功; Ubuntu、Windows、Docker build 均通过. 边界修复相关本地测试 132 passed.
- VERIFIED: NAS 官方 FC2、JavArchive、FC2CMADB 实际刮削与缓存成功; 三样本首轮及最终镜像单样本复验均正常退出. FD2PPV 为 Cloudflare 403, 停止后续请求.
- PASS: 最终生产 health 为 ok / 0.11.0, config 与 Compose 和备份完全一致, 原镜像继续运行.

## 限制与交接

完整站点/host/速率/认证审计见 [本次报告](reports/fc2-audit-20260915.md), 样本与回滚见 [NAS 验收](reports/fc2-nas-20260916.md).

MissJAV 当前入口无法可靠取得 HTML, Thikana 入口未确认; 7MMTV/AV01 没有低维护证据, 未注册假 crawler. FD2PPV 保留受限状态, 不进行挑战绕过.

NAS 生产数据库 revision 为 `668e214b1a76`, v0.14.0 包含上游后续迁移. 为保留生产库与整理结果, 本轮使用隔离数据目录且不挂载用户媒体验证, 不切换生产数据库. 生产容器 `Amane`、8000 端口、原始挂载和配置保持.

upstream 维护仍采用 main fast-forward 后合并 custom, 不 rebase 已发布分支; 参见 [历史](HISTORY.md).
