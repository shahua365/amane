# 重要维护记录

## 2026-09-14 — 建立个人 Fork 维护基础

- 创建 `shahua365/amane` Fork, 配置 `origin` 与官方 `upstream`
- 保持 `main` 与 `upstream/main` 一致, 从该提交建立长期维护分支 `custom`
- 补充个人维护规则和交接结构, 将 `custom` 纳入官方 CI
- 增加不推送镜像的 Docker build CI; 自动 upstream 同步 PR 因维护复杂度暂不实现
- 本地 lint、format、typecheck、OpenAPI/client 漂移检查及前端构建通过; Python 测试仅因 Windows 符号链接权限出现 4 项环境失败
- 验证基线 `a2ca0dbd2c4043eb23a4a2f6d913b524022f10a8` 的 GitHub Actions CI #1 全部通过, 包含 Ubuntu、Windows 与 Docker build
- 未修改业务功能、生产配置或 NAS

## 2026-09-16 — FC2 多源增强

- 沿用指定会话的 FC2CMADB/FD2PPV 实现和年龄验证修复, 适配当前 v0.14.0 架构.
- 复用官方 FC2, 增加有实际 HTML 依据的 JavArchive; 强化限速、查询规范化、补空和图片缓存复用.
- 受限或未确认站点保留真实验证边界; 完整审计见 [报告](reports/fc2-audit-20260915.md).
- 本机全量测试保留四项 Windows 符号链接环境失败; 最终代码 3bbdc5a 的 GitHub Ubuntu / Windows / Docker CI 全通过.
- NAS 首轮三样本与最终镜像单样本成功入隔离库、缓存图片; FD2PPV 403 后停止. 生产 v0.11.0、配置、Compose 未改; 备份和回滚见验收报告.

## 2026-09-17 — 通用 artwork 回退与缓存

- 代码 `05d27836cbc9938ebd1657d28c4dba47da4270ef` 将补图与 metadata 标量聚合分离, 复用当前注册来源, 不新增内容站点或影片专用逻辑.
- 图片完整解码后原子缓存, organize 优先本地; 增加手工 URL / safe_dirs 内图片文件的最终回退 API.
- 403 / Cloudflare 在当前 HTTP 客户端生命周期内标记 BLOCKED 并停止请求; 无验证绕过.
- 验证仅使用合成图片和离线响应, 本轮未访问内容来源或部署 NAS; 测试和 Docker CI 结果见 [当前交接](LATEST.md).

## 2026-09-17 — NAS 生产升级

- 用户授权部署 `00527a0`; NAS 构建 `amane:artwork-00527a0` 并将生产升级至 v0.14.0. 先完成在线备份、禁网副本迁移与合成图片缓存验证, 再停机备份和切换.
- 数据库完整性、外键和主要表计数通过; Web / health 200, 容器 healthy, 无重启或启动错误. 保留实际挂载、运行身份、环境和重启策略.
- 自动刮削及定时任务暂停以保持本轮无内容来源访问; 原设置及回滚材料仅保存 NAS. 详细验证与恢复边界见 [当前交接](LATEST.md).
