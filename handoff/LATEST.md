# 维护交接

更新时间: 2026-09-14

## 当前版本

- upstream: `sqzw-x/amane` `v0.14.0`, `upstream/main` 为 `5de9f9ae463169942f1ed45314989a2033ee835c`
- main: `5de9f9ae463169942f1ed45314989a2033ee835c`, 与 `upstream/main` 及 `origin/main` 一致
- custom: 本文件所在提交; 精确值使用 `git rev-parse custom` 获取; CI 验证基线为 `a2ca0dbd2c4043eb23a4a2f6d913b524022f10a8`

## 已验证功能

- PASS: `origin` 指向 `https://github.com/shahua365/amane.git`
- PASS: `upstream` 指向 `https://github.com/sqzw-x/amane.git`
- PASS: `main` 与当前 `upstream/main` 完全一致
- PASS: `custom` 从当前 `main` 建立, 个人维护规则和交接文件只进入 `custom`
- PASS: CI 继续使用官方 `just ci`、`just ci-windows`, 并覆盖 `custom`
- PASS: CI 增加仅构建、不登录、不推送的 Docker 验证
- PASS: Ruff lint/format、Pyright、ty、OpenAPI/client 漂移检查、前端 check 与前端 production build
- PARTIAL: Python 测试为 2495 passed、42 skipped、4 failed; 失败均为 Windows `WinError 1314` 符号链接权限不足, 未进入被测业务逻辑
- PASS: GitHub Actions CI #1 在验证基线提交通过: Ubuntu `just ci`、Windows `just ci-windows`、Docker build

## 未验证功能

- UNVERIFIED: 私有 `amane-testdata` 无访问权限, crawler fixture 测试按官方机制跳过
- UNVERIFIED: NAS 生产部署; 本次任务未连接或修改 NAS

## 当前阻塞项

- 无仓库基础维护阻塞项. 本机 Windows 符号链接权限与私有 fixture 仅限制本地覆盖范围, 对应标准 CI 与 Docker build 已通过

## 与 upstream 的差异

- 仅包含个人 Fork 维护规则、`custom` 分支 CI 覆盖、Docker build CI 验证和 `handoff/` 交接记录
- 未增加 FC2、Cookie、Rate Limit 或其他业务功能

## upstream 更新流程

1. `git fetch upstream --prune --tags`
2. 检查 `main..upstream/main` 的提交、依赖、迁移、配置、API 与构建变化
3. `git switch main`, 确认工作区干净后执行 `git merge --ff-only upstream/main`, 再推送 `origin/main`
4. `git switch custom`, 执行 `git merge main`; 解决冲突时保留已确认的个人增强
5. 执行 `just ci` 和 `docker build -t amane-custom:verify .`
6. 更新本文件及 `handoff/HISTORY.md`, 独立提交并推送 `origin/custom`

采用 merge 而非定期 rebase: `custom` 是长期发布分支, merge 保留 upstream 集成点且不要求强制推送. 尚未实现自动同步 PR; 该流程需要写权限、去重和冲突处理, 当前收益不足以抵消维护成本.

## 下一步

检查首次 `custom` 推送触发的 GitHub Actions, 以 CI 结果补齐本机无法完成的完整门禁与 Docker 构建证据.
