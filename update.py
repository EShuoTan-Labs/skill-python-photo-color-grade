"""从公共代码托管仓库检查更新。

当前支持 GitHub。以后需要支持其他平台时，只需新增 UpdateSource 子类。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path


# ===== 在这里填写固定配置 =====
GITHUB_OWNER = "EShuoTan-Labs"  # 用户名或组织名
GITHUB_REPOSITORY = "skill-python-photo-color-grade"
BRANCH = "main"
RELEASE_ASSET_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPOSITORY}"
    "/releases/latest/download/skill-python-photo-color-grade.zip"
)

# 部署后的项目根目录。更新检查会读取此目录中的 commit 标记文件。
PROJECT_ROOT = Path(__file__).resolve().parent
COMMIT_HASH_FILENAME = ".latest_commit"
COMMIT_RECORD_PATH = PROJECT_ROOT / COMMIT_HASH_FILENAME
TIMEOUT_SECONDS = 30


class UpdateError(RuntimeError):
    """检查更新失败。"""


class RequestError(UpdateError):
    """GitHub 网络请求失败。"""


class UpdateSource(ABC):
    """更新源的统一接口。"""

    @abstractmethod
    def get_latest_commit_hash(self) -> str:
        """返回指定分支最新 commit 的完整哈希值。"""


class GitHubSource(UpdateSource):
    """GitHub 仓库更新源。"""

    def __init__(self, owner: str, repository: str, branch: str) -> None:
        if not owner or not repository or not branch:
            raise ValueError("GitHub 用户名、仓库名和分支名不能为空")

        self.owner = owner
        self.repository = repository.removesuffix(".git")
        self.branch = branch

    def _request(self, url: str) -> urllib.response.addinfourl:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "simple-python-update-checker",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        request = urllib.request.Request(url, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RequestError(f"GitHub 请求失败（HTTP {exc.code}）: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RequestError(f"无法连接 GitHub: {exc.reason}") from exc

    def get_latest_commit_hash(self) -> str:
        # GitHub 的 ref 参数格式为 heads/<分支名>。保留分支名中的斜杠，
        # 以支持 feature/example 这类常见分支名称。
        branch = urllib.parse.quote(self.branch, safe="/")
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repository}"
            f"/git/ref/heads/{branch}"
        )
        with self._request(url) as response:
            result = json.load(response)

        git_object = result.get("object")
        commit_hash = git_object.get("sha") if isinstance(git_object, dict) else None
        if not isinstance(commit_hash, str) or not commit_hash:
            raise UpdateError("GitHub 返回的数据中没有 commit 哈希值")
        return commit_hash


def read_recorded_commit(path: Path) -> str | None:
    """读取当前项目的 commit 哈希。"""
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    except FileNotFoundError:
        return None


def is_update_available(
    source: UpdateSource,
    commit_record_path: Path = COMMIT_RECORD_PATH,
) -> tuple[bool, str]:
    """检查是否需要更新，返回（是否需要更新，远程最新 commit SHA）。"""
    latest_commit = source.get_latest_commit_hash()
    recorded_commit = read_recorded_commit(commit_record_path)
    return recorded_commit != latest_commit, latest_commit


def create_source() -> UpdateSource:
    """根据代码中的固定配置创建更新源。"""
    return GitHubSource(GITHUB_OWNER, GITHUB_REPOSITORY, BRANCH)


def build_deployment_instructions() -> str:
    """生成面向大模型的简洁 skill 更新说明。"""
    return (
        "当前 skill 有更新版本。不影响当前功能，但必须明确向用户请求更新意见。"
        "如果确认更新，请前往以下固定链接下载最新 release 中的 ZIP："
        f"\n{RELEASE_ASSET_URL}"
        "\n下载完成后，请解压该 ZIP，并部署新版文件以替换当前 skill。成功部署后清理旧版的备份以及 ZIP 文件。"
    )


def print_result(
    need_update: bool,
    current_commit: str | None,
    latest_commit: str | None,
    message: str,
) -> None:
    """以固定 JSON 结构输出结果。"""
    result = {
        "NEED_UPDATE": need_update,
        "CURRENT_COMMIT": current_commit,
        "LATEST_COMMIT": latest_commit,
        "MESSAGE": message,
    }
    print(json.dumps(result, ensure_ascii=False))


def main() -> int:
    current_commit: str | None = None
    latest_commit: str | None = None

    try:
        current_commit = read_recorded_commit(COMMIT_RECORD_PATH)
        source = create_source()
        update_available, latest_commit = is_update_available(
            source,
            COMMIT_RECORD_PATH,
        )

        if update_available:
            print_result(
                True,
                current_commit,
                latest_commit,
                build_deployment_instructions(),
            )
        else:
            print_result(
                False,
                current_commit,
                latest_commit,
                "当前 skill 已是最新版本，无需更新。",
            )
    except RequestError as exc:
        print_result(
            False,
            current_commit,
            None,
            f"检查 skill 更新失败：{exc}。请稍后重新运行 update.py。",
        )
        return 1
    except (UpdateError, OSError, ValueError) as exc:
        print_result(
            False,
            current_commit,
            latest_commit,
            f"检查 skill 更新失败：{exc}。请修复错误后重新运行 update.py。",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
