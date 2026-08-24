"""从公共代码托管仓库检查并下载更新。

当前支持 GitHub。以后需要支持其他平台时，只需新增 UpdateSource 子类。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath


# ===== 在这里填写固定配置 =====
GITHUB_OWNER = "EShuoTan-Labs"  # 用户名或组织名
GITHUB_REPOSITORY = "skill-python-photo-color-grade"
BRANCH = "main"

# 部署后的项目根目录。更新检查会读取此目录中的 commit 标记文件。
PROJECT_ROOT = Path(__file__).resolve().parent
COMMIT_HASH_FILENAME = ".latest_commit"
COMMIT_RECORD_PATH = PROJECT_ROOT / COMMIT_HASH_FILENAME
TIMEOUT_SECONDS = 30


class UpdateError(RuntimeError):
    """检查或下载更新失败。"""


class RequestError(UpdateError):
    """GitHub 网络请求失败。"""


class UpdateSource(ABC):
    """更新源的统一接口。"""

    @abstractmethod
    def get_latest_commit_hash(self) -> str:
        """返回指定分支最新 commit 的完整哈希值。"""

    @abstractmethod
    def download_commit_zip(self, commit_hash: str, destination: Path) -> None:
        """下载指定 commit 的 zip 到 destination。"""


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

    def download_commit_zip(self, commit_hash: str, destination: Path) -> None:
        commit = urllib.parse.quote(commit_hash, safe="")
        url = (
            f"https://api.github.com/repos/{self.owner}/{self.repository}"
            f"/zipball/{commit}"
        )
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination.with_suffix(destination.suffix + ".part")

        try:
            with self._request(url) as response, temporary_path.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary_path.replace(destination)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise


def read_recorded_commit(path: Path) -> str | None:
    """读取当前项目的 commit 哈希。"""
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    except FileNotFoundError:
        return None


def embed_commit_hash_in_zip(
    archive_path: Path,
    commit_hash: str,
    filename: str = COMMIT_HASH_FILENAME,
) -> None:
    """在 ZIP 的项目根目录中写入 commit 哈希文件。"""
    rewritten_path = archive_path.with_name(archive_path.name + ".rewrite")

    try:
        with zipfile.ZipFile(archive_path, "r") as source_archive:
            entries = source_archive.infolist()
            roots = {
                PurePosixPath(entry.filename).parts[0]
                for entry in entries
                if PurePosixPath(entry.filename).parts
            }
            if len(roots) != 1:
                raise UpdateError("下载的 ZIP 不包含唯一的项目根目录")

            root_directory = roots.pop()
            marker_path = f"{root_directory}/{filename}"

            with zipfile.ZipFile(rewritten_path, "w") as target_archive:
                for entry in entries:
                    if entry.filename == marker_path:
                        continue

                    if entry.is_dir():
                        target_archive.writestr(entry, b"")
                    else:
                        with source_archive.open(entry, "r") as source_file:
                            with target_archive.open(entry, "w") as target_file:
                                shutil.copyfileobj(source_file, target_file)

                target_archive.writestr(
                    marker_path,
                    commit_hash + "\n",
                    compress_type=zipfile.ZIP_DEFLATED,
                )

        rewritten_path.replace(archive_path)
    except zipfile.BadZipFile as exc:
        raise UpdateError("下载的文件不是有效的 ZIP 压缩包") from exc
    finally:
        rewritten_path.unlink(missing_ok=True)


def is_update_available(
    source: UpdateSource,
    commit_record_path: Path = COMMIT_RECORD_PATH,
) -> tuple[bool, str]:
    """检查是否需要更新，返回（是否需要更新，远程最新 commit SHA）。"""
    latest_commit = source.get_latest_commit_hash()
    recorded_commit = read_recorded_commit(commit_record_path)
    return recorded_commit != latest_commit, latest_commit


def download_latest_commit_zip(
    source: UpdateSource,
    download_path: Path,
    latest_commit: str | None = None,
) -> str:
    """无条件下载最新 commit ZIP、注入 SHA 文件，并返回最新 SHA。"""
    if latest_commit is None:
        latest_commit = source.get_latest_commit_hash()

    # 先在旁路临时文件中完成下载和 ZIP 修改，全部成功后再替换目标文件。
    prepared_path = download_path.with_name(download_path.name + ".prepare")
    try:
        source.download_commit_zip(latest_commit, prepared_path)
        embed_commit_hash_in_zip(prepared_path, latest_commit)
        prepared_path.replace(download_path)
    finally:
        prepared_path.unlink(missing_ok=True)
    return latest_commit


def create_source() -> UpdateSource:
    """根据代码中的固定配置创建更新源。"""
    return GitHubSource(GITHUB_OWNER, GITHUB_REPOSITORY, BRANCH)


def get_default_download_path(latest_commit: str) -> Path:
    """返回供自动化工具使用的、位于项目目录之外的 ZIP 路径。"""
    short_commit = latest_commit[:12]
    return PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}-update-{short_commit}.zip"


def build_deployment_instructions(
    archive_path: Path,
    *,
    include_download_step: bool,
) -> str:
    """生成面向大模型的简洁 skill 更新说明。"""
    archive_path = archive_path.resolve()
    if include_download_step:
        command = (
            f'"{sys.executable}" "{Path(__file__).resolve()}" '
            f'--download "{archive_path}"'
        )
        return (
            "当前 skill 需要更新。请执行以下命令下载新版 skill ZIP："
            f"\n{command}"
            f'\n下载得到的 ZIP（"{archive_path}"）就是新版 skill；'
            "下载成功后，请自行决定如何解压、部署并替换当前 skill。"
        )
    return (
        f'新版 skill ZIP 已下载到："{archive_path}"。'
        "这个 ZIP 就是新版 skill，请自行决定如何解压、部署并替换当前 skill。"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查并下载 GitHub 仓库的最新代码")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--check",
        action="store_true",
        help="输出当前版本、远程最新版本和下一步操作建议",
    )
    actions.add_argument(
        "--download",
        type=Path,
        metavar="ZIP_PATH",
        help="检测并自动下载最新版到指定 ZIP 文件路径",
    )
    return parser.parse_args(argv)


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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    current_commit: str | None = None
    latest_commit: str | None = None

    try:
        current_commit = read_recorded_commit(COMMIT_RECORD_PATH)
        source = create_source()
        update_available, latest_commit = is_update_available(
            source,
            COMMIT_RECORD_PATH,
        )

        if args.check:
            if update_available:
                download_path = get_default_download_path(latest_commit)
                print_result(
                    True,
                    current_commit,
                    latest_commit,
                    build_deployment_instructions(
                        download_path,
                        include_download_step=True,
                    ),
                )
            else:
                print_result(
                    False,
                    current_commit,
                    latest_commit,
                    "当前 skill 已是最新版本，无需更新。",
                )
        else:
            destination = args.download.resolve()
            download_latest_commit_zip(
                source,
                destination,
                latest_commit,
            )
            message = build_deployment_instructions(
                destination,
                include_download_step=False,
            )
            print_result(update_available, current_commit, latest_commit, message)
    except RequestError as exc:
        print_result(
            False,
            current_commit,
            None,
            f"检查 skill 更新失败：{exc}。请稍后重新执行 --check。",
        )
        return 1
    except (UpdateError, OSError, ValueError) as exc:
        print_result(
            False,
            current_commit,
            latest_commit,
            f"skill 更新操作失败：{exc}。请修复错误后重新执行 --check。",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
