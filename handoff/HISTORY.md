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
- 本机全量测试仅保留四项 Windows 符号链接环境失败; CI 和 NAS 隔离测试结果待后续验证记录.
