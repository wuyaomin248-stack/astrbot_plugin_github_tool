import aiohttp
import asyncio
import base64
import json
import os
import mimetypes
from typing import Optional

from astrbot.api import logger
from astrbot.api.star import Context, Star, register
from astrbot.api.event import AstrMessageEvent
import astrbot.api.event.filter as flt

DEFAULT_GITHUB_API = "https://api.github.com"
DEFAULT_UPLOADS_API = "https://uploads.github.com"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=45)


@register(
    "astrbot_plugin_github_tool",
    "日海 & 橙子汐",
    "提供 GitHub API 常用调用能力，支持创建仓库、原子多文件提交、工作流监控、日志获取、Release 发布与 Issue/PR 管理",
    "0.3.0",
)
class GitHubToolPlugin(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)
        self.config = config or {}

    def _get_api_base(self) -> str:
        base = (self.config.get("api_base") or "").strip()
        return base.rstrip("/") if base else DEFAULT_GITHUB_API

    def _get_token(self) -> str:
        token = (self.config.get("github_token") or "").strip()
        return token

    def _get_headers(self, accept: str = "application/vnd.github+json") -> dict:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AstrBot-GitHubTool",
        }
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _check_token(self) -> Optional[str]:
        if not self._get_token():
            return "错误：未在插件配置中填写 github_token，请在 AstrBot 控制台填入 GitHub Personal Access Token。"
        return None

    # ==================== 仓库与基础文件管理 ====================

    @flt.llm_tool(name="github_create_repo")
    async def create_repo(
        self,
        event: AstrMessageEvent,
        repo_name: str,
        description: str = "",
        private: bool = False,
    ):
        """在 GitHub 上创建一个新仓库。

        Args:
            repo_name(string): 仓库名称
            description(string): 仓库描述
            private(boolean): 是否为私有仓库，默认为 False
        """
        err = self._check_token()
        if err:
            return err

        url = f"{self._get_api_base()}/user/repos"
        payload = {
            "name": repo_name,
            "description": description,
            "private": private,
            "auto_init": True,
        }

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.post(
                    url, headers=self._get_headers(), json=payload
                ) as resp:
                    data = await resp.json()
                    if resp.status in [200, 201]:
                        return f"成功创建仓库：{data.get('html_url')}"
                    else:
                        return f"创建仓库失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
        except Exception as e:
            return f"请求失败: {str(e)}"

    @flt.llm_tool(name="github_create_or_update_file")
    async def create_or_update_file(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        path: str,
        content: str,
        commit_message: str,
        branch: str = "",
    ):
        """向 GitHub 仓库创建或更新单个文件。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            path(string): 文件路径
            content(string): 文件的完整文本内容
            commit_message(string): 提交信息
            branch(string): 目标分支名，留空则默认为默认分支
        """
        err = self._check_token()
        if err:
            return err

        url = f"{self._get_api_base()}/repos/{owner}/{repo}/contents/{path}"
        headers = self._get_headers()

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                sha = None
                params = {}
                if branch:
                    params["ref"] = branch
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        sha = data.get("sha")

                payload = {
                    "message": commit_message,
                    "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
                }
                if branch:
                    payload["branch"] = branch
                if sha:
                    payload["sha"] = sha

                async with session.put(url, headers=headers, json=payload) as resp:
                    data = await resp.json()
                    if resp.status in [200, 201]:
                        commit_url = data.get("commit", {}).get("html_url", "")
                        return f"文件推送成功：{path} (Commit: {commit_url})"
                    else:
                        return f"推送文件失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
        except Exception as e:
            return f"请求失败: {str(e)}"

    @flt.llm_tool(name="github_get_tree")
    async def get_tree(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        branch: str = "main",
        recursive: bool = True,
    ):
        """获取 GitHub 仓库的文件树结构。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            branch(string): 分支名或 commit sha，默认为 main
            recursive(boolean): 是否递归获取全量文件树，默认为 True
        """
        err = self._check_token()
        if err:
            return err

        url = f"{self._get_api_base()}/repos/{owner}/{repo}/git/trees/{branch}"
        params = {"recursive": "1"} if recursive else {}
        headers = self._get_headers()

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        tree = data.get("tree", [])
                        file_list = [f"{item['type']}: {item['path']}" for item in tree]
                        count = len(file_list)
                        truncated = file_list[:80]
                        result_text = f"仓库 {owner}/{repo} ({branch}) 共计 {count} 个对象：\n" + "\n".join(truncated)
                        if count > 80:
                            result_text += f"\n... 其余 {count - 80} 个对象已截断"
                        return result_text
                    else:
                        return f"获取文件树失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
        except Exception as e:
            return f"请求失败: {str(e)}"

    # ==================== Phase 1: Git Data API 原子多文件提交 ====================

    @flt.llm_tool(name="github_push_files")
    async def push_files(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        branch: str,
        commit_message: str,
        files_json: str,
    ):
        """向 GitHub 仓库原子化批量提交多个文件（Git Data API 事务提交）。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            branch(string): 目标分支名，例如 main
            commit_message(string): 提交日志说明
            files_json(string): 包含文件路径和内容的 JSON 格式字符串，例如 {"path/file.py": "content"}
        """
        err = self._check_token()
        if err:
            return err

        try:
            files_map = json.loads(files_json)
            if not isinstance(files_map, dict) or not files_map:
                return "错误：files_json 必须是非空的 JSON 对象字典，形如 {\"path/file.py\": \"content\"}。"
        except Exception as e:
            return f"错误：files_json 解析失败，不是有效的 JSON 字符串: {str(e)}"

        headers = self._get_headers()
        base_url = f"{self._get_api_base()}/repos/{owner}/{repo}"

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                ref_url = f"{base_url}/git/ref/heads/{branch}"
                async with session.get(ref_url, headers=headers) as resp:
                    if resp.status != 200:
                        data = await resp.json()
                        return f"获取分支 {branch} HEAD 引用失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
                    ref_data = await resp.json()
                    latest_commit_sha = ref_data.get("object", {}).get("sha")

                if not latest_commit_sha:
                    return f"错误：未能在分支 {branch} 上找到 HEAD commit SHA。"

                commit_url = f"{base_url}/git/commits/{latest_commit_sha}"
                async with session.get(commit_url, headers=headers) as resp:
                    if resp.status != 200:
                        data = await resp.json()
                        return f"获取 commit 基础信息失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
                    commit_data = await resp.json()
                    base_tree_sha = commit_data.get("tree", {}).get("sha")

                if not base_tree_sha:
                    return "错误：未能获取基础 tree SHA。"

                tree_items = []
                for file_path, file_content in files_map.items():
                    blob_url = f"{base_url}/git/blobs"
                    if isinstance(file_content, bytes):
                        b64_str = base64.b64encode(file_content).decode("utf-8")
                        blob_payload = {"content": b64_str, "encoding": "base64"}
                    else:
                        blob_payload = {"content": str(file_content), "encoding": "utf-8"}

                    async with session.post(blob_url, headers=headers, json=blob_payload) as resp:
                        if resp.status != 201:
                            data = await resp.json()
                            return f"创建文件 Blob 失败 [{file_path}] (HTTP {resp.status})：{data.get('message', '未知错误')}"
                        blob_data = await resp.json()
                        blob_sha = blob_data.get("sha")

                    tree_items.append({
                        "path": file_path.lstrip("/"),
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_sha,
                    })

                tree_url = f"{base_url}/git/trees"
                tree_payload = {
                    "base_tree": base_tree_sha,
                    "tree": tree_items,
                }
                async with session.post(tree_url, headers=headers, json=tree_payload) as resp:
                    if resp.status != 201:
                        data = await resp.json()
                        return f"创建 Git Tree 失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
                    new_tree_data = await resp.json()
                    new_tree_sha = new_tree_data.get("sha")

                new_commit_url = f"{base_url}/git/commits"
                commit_payload = {
                    "message": commit_message,
                    "tree": new_tree_sha,
                    "parents": [latest_commit_sha],
                }
                async with session.post(new_commit_url, headers=headers, json=commit_payload) as resp:
                    if resp.status != 201:
                        data = await resp.json()
                        return f"创建 Git Commit 失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
                    new_commit_data = await resp.json()
                    new_commit_sha = new_commit_data.get("sha")

                update_ref_url = f"{base_url}/git/refs/heads/{branch}"
                patch_payload = {
                    "sha": new_commit_sha,
                    "force": False,
                }
                async with session.patch(update_ref_url, headers=headers, json=patch_payload) as resp:
                    if resp.status != 200:
                        data = await resp.json()
                        return f"更新分支引用失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"

                file_names = list(files_map.keys())
                files_summary = ", ".join(file_names[:5]) + (f" 等共 {len(file_names)} 个文件" if len(file_names) > 5 else "")
                return f"✅ 原子多文件提交成功！\n分支: {branch}\nCommit SHA: {new_commit_sha[:8]}\n提交信息: {commit_message}\n变更文件: {files_summary}\n提交链接: https://github.com/{owner}/{repo}/commit/{new_commit_sha}"

        except Exception as e:
            return f"原子提交过程异常: {str(e)}"

    # ==================== Phase 2: GitHub Actions CI/CD 状态与日志 ====================

    @flt.llm_tool(name="github_check_actions")
    async def check_actions(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        branch: str = "",
        limit: int = 5,
    ):
        """查看 GitHub 仓库最近的 Actions CI/CD 流水线运行状态。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            branch(string): 分支过滤，留空则查看所有分支
            limit(number): 返回的最大运行数量，默认为 5
        """
        err = self._check_token()
        if err:
            return err

        url = f"{self._get_api_base()}/repos/{owner}/{repo}/actions/runs"
        params = {"per_page": str(min(max(limit, 1), 20))}
        if branch:
            params["branch"] = branch

        headers = self._get_headers()

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        data = await resp.json()
                        return f"获取 Actions 运行记录失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
                    data = await resp.json()
                    runs = data.get("workflow_runs", [])
                    if not runs:
                        return f"仓库 {owner}/{repo} {'在分支 ' + branch if branch else ''} 没有找到任何 Actions 运行记录。"

                    results = [f"=== 仓库 {owner}/{repo} Actions 运行列表 (共 {len(runs)} 条) ==="]
                    for r in runs:
                        run_id = r.get("id")
                        name = r.get("name")
                        status = r.get("status")
                        conclusion = r.get("conclusion") or "running"
                        head_branch = r.get("head_branch", "")
                        head_commit = (r.get("head_commit") or {}).get("message", "").split("\n")[0]
                        html_url = r.get("html_url", "")
                        created_at = r.get("created_at", "")

                        icon = "🟢" if conclusion == "success" else ("🔴" if conclusion == "failure" else "🟡")
                        results.append(
                            f"{icon} Run ID: {run_id} | 名称: {name}\n"
                            f"   状态: {status} ({conclusion}) | 分支: {head_branch}\n"
                            f"   Commit: {head_commit[:40]}\n"
                            f"   时间: {created_at}\n"
                            f"   详情: {html_url}"
                        )

                    return "\n\n".join(results)
        except Exception as e:
            return f"查询 Actions 失败: {str(e)}"

    @flt.llm_tool(name="github_get_failed_logs")
    async def get_failed_logs(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        run_id: int,
        tail_lines: int = 80,
    ):
        """获取 GitHub Actions 失败运行的 Job 错误日志。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            run_id(number): Actions Workflow Run 的数字 ID
            tail_lines(number): 截取的日志末尾行数，默认为 80 行
        """
        err = self._check_token()
        if err:
            return err

        headers = self._get_headers()
        base_url = f"{self._get_api_base()}/repos/{owner}/{repo}"

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                jobs_url = f"{base_url}/actions/runs/{run_id}/jobs"
                async with session.get(jobs_url, headers=headers) as resp:
                    if resp.status != 200:
                        data = await resp.json()
                        return f"查询 Run Jobs 失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
                    jobs_data = await resp.json()
                    jobs = jobs_data.get("jobs", [])

                if not jobs:
                    return f"Run #{run_id} 未找到任何关联 Job。"

                failed_job = next((j for j in jobs if j.get("conclusion") == "failure"), None)
                target_job = failed_job or jobs[-1]
                job_id = target_job.get("id")
                job_name = target_job.get("name")
                job_conclusion = target_job.get("conclusion") or target_job.get("status")

                step_failures = []
                for s in target_job.get("steps", []):
                    if s.get("conclusion") == "failure":
                        step_failures.append(f"❌ 步骤 [{s.get('name')}] 失败 (序号 #{s.get('number')})")

                logs_url = f"{base_url}/actions/jobs/{job_id}/logs"
                log_content = ""
                async with session.get(logs_url, headers=headers, allow_redirects=True) as log_resp:
                    if log_resp.status == 200:
                        raw_text = await log_resp.text(errors="replace")
                        lines = raw_text.splitlines()
                        cut_lines = lines[-tail_lines:] if len(lines) > tail_lines else lines
                        log_content = "\n".join(cut_lines)
                    else:
                        log_content = f"（未能拉取到原始日志流，HTTP {log_resp.status}）"

                steps_summary = "\n".join(step_failures) if step_failures else "无具体失败步骤标记"
                return (
                    f"=== Actions 运行日志 (Run ID: {run_id}, Job: {job_name} #{job_id}) ===\n"
                    f"结论: {job_conclusion}\n"
                    f"失败步骤:\n{steps_summary}\n\n"
                    f"--- 日志尾部截取 ({min(tail_lines, 80)} 行) ---\n"
                    f"{log_content}"
                )

        except Exception as e:
            return f"获取失败日志异常: {str(e)}"

    # ==================== Phase 3: GitHub Release 发布与制品交付 ====================

    @flt.llm_tool(name="github_create_release")
    async def create_release(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        tag_name: str,
        name: str = "",
        body: str = "",
        target_commitish: str = "main",
        draft: bool = False,
        prerelease: bool = False,
    ):
        """在 GitHub 仓库发布一个新的 Release。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            tag_name(string): Tag 标签名称，例如 v1.0.0
            name(string): Release 发版标题，留空则默认与 tag_name 一致
            body(string): Release 版本说明/更新日志
            target_commitish(string): 目标分支或 Commit SHA，默认为 main
            draft(boolean): 是否为草稿，默认为 False
            prerelease(boolean): 是否为预发布版本，默认为 False
        """
        err = self._check_token()
        if err:
            return err

        url = f"{self._get_api_base()}/repos/{owner}/{repo}/releases"
        headers = self._get_headers()
        payload = {
            "tag_name": tag_name,
            "target_commitish": target_commitish or "main",
            "name": name or tag_name,
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
        }

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    data = await resp.json()
                    if resp.status in [200, 201]:
                        rel_id = data.get("id")
                        html_url = data.get("html_url")
                        return f"🎉 成功创建 Release {tag_name} (ID: {rel_id})：\n{html_url}"
                    else:
                        return f"创建 Release 失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
        except Exception as e:
            return f"创建 Release 异常: {str(e)}"

    @flt.llm_tool(name="github_upload_release_asset")
    async def upload_release_asset(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        release_id: int,
        file_path: str,
        name: str = "",
    ):
        """上传本地制品文件至指定的 GitHub Release。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            release_id(number): Release 的数字 ID
            file_path(string): 服务器本地待上传的文件绝对或相对路径
            name(string): 目标文件名，留空则默认取本地文件名
        """
        err = self._check_token()
        if err:
            return err

        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            return f"错误：本地文件不存在或不是有效文件: {file_path}"

        filename = name or os.path.basename(file_path)
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = "application/octet-stream"

        upload_base = DEFAULT_UPLOADS_API if self._get_api_base() == DEFAULT_GITHUB_API else self._get_api_base()
        upload_url = f"{upload_base}/repos/{owner}/{repo}/releases/{release_id}/assets?name={filename}"

        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AstrBot-GitHubTool",
            "Content-Type": content_type,
        }

        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                async with session.post(upload_url, headers=headers, data=file_bytes) as resp:
                    data = await resp.json()
                    if resp.status in [200, 201]:
                        download_url = data.get("browser_download_url", "")
                        size = data.get("size", len(file_bytes))
                        return f"✅ 制品上传成功！\n文件: {filename} ({size} 字节)\n下载地址: {download_url}"
                    else:
                        return f"上传制品失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
        except Exception as e:
            return f"上传制品异常: {str(e)}"

    # ==================== Issue 与 PR 管理 ====================

    @flt.llm_tool(name="github_create_issue")
    async def create_issue(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
    ):
        """在 GitHub 仓库中创建一个新的 Issue。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            title(string): Issue 标题
            body(string): Issue 内容描述
        """
        err = self._check_token()
        if err:
            return err

        url = f"{self._get_api_base()}/repos/{owner}/{repo}/issues"
        headers = self._get_headers()
        payload = {"title": title, "body": body}

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    data = await resp.json()
                    if resp.status == 201:
                        return f"成功创建 Issue #{data.get('number')}：{data.get('html_url')}"
                    else:
                        return f"创建 Issue 失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
        except Exception as e:
            return f"创建 Issue 异常: {str(e)}"

    @flt.llm_tool(name="github_create_pull_request")
    async def create_pull_request(
        self,
        event: AstrMessageEvent,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str = "main",
        body: str = "",
    ):
        """在 GitHub 仓库中创建一个新的 Pull Request。

        Args:
            owner(string): 仓库所有者用户名或组织名
            repo(string): 仓库名
            title(string): PR 标题
            head(string): 包含修改的来源分支（例如 feature-branch）
            base(string): 合入的目标分支（默认为 main）
            body(string): PR 内容说明
        """
        err = self._check_token()
        if err:
            return err

        url = f"{self._get_api_base()}/repos/{owner}/{repo}/pulls"
        headers = self._get_headers()
        payload = {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
        }

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    data = await resp.json()
                    if resp.status == 201:
                        return f"成功创建 Pull Request #{data.get('number')}：{data.get('html_url')}"
                    else:
                        return f"创建 Pull Request 失败 (HTTP {resp.status})：{data.get('message', '未知错误')}"
        except Exception as e:
            return f"创建 PR 异常: {str(e)}"
