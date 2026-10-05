# astrbot_plugin_github_tool

> AstrBot GitHub 工程协作与自动化运维插件 (v0.3.0)

## 功能概览

- **仓库管理**：新建公开/私有仓库 (`github_create_repo`)
- **文件管理**：单文件创建与更新 (`github_create_or_update_file`)、目录树递归读取 (`github_get_tree`)
- **原子提交 (Git Data API)**：支持多文件事务性批量提交 (`github_push_files`)，避免断网导致的脏提交
- **Actions CI/CD 闭环**：监控工作流状态 (`github_check_actions`)、自动拉取失败 Job 的末尾报错日志 (`github_get_failed_logs`)
- **Release 与制品交付**：一键生成 Release (`github_create_release`)，直传本地插件包等二进制资产 (`github_upload_release_asset`)
- **协作管理**：开 Issue (`github_create_issue`)、提 PR (`github_create_pull_request`)

## 配置说明

在 AstrBot 控制台填写：
- `github_token`：具备 `repo` 与 `workflow` 权限的 Personal Access Token (PAT)
- `api_base`：可选，默认为 `https://api.github.com`
