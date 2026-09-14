# 重要维护记录

## 2026-09-14 — 建立个人 Fork 维护基础

- 创建 `shahua365/amane` Fork, 配置 `origin` 与官方 `upstream`
- 保持 `main` 与 `upstream/main` 一致, 从该提交建立长期维护分支 `custom`
- 补充个人维护规则和交接结构, 将 `custom` 纳入官方 CI
- 增加不推送镜像的 Docker build CI; 自动 upstream 同步 PR 因维护复杂度暂不实现
- 本地 lint、format、typecheck、OpenAPI/client 漂移检查及前端构建通过; Python 测试仅因 Windows 符号链接权限出现 4 项环境失败
- 未修改业务功能、生产配置或 NAS
