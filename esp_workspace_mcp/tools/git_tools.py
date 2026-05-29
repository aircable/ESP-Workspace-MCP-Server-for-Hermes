"""Git MCP tools: version control operations via gitpython."""
import os
import logging
from typing import List, Optional

from esp_workspace_mcp.utils.security import safe_resolve, is_path_allowed

logger = logging.getLogger(__name__)

MAX_OUTPUT = 51200  # 50 KB


def _truncate(output: str) -> str:
    if len(output) > MAX_OUTPUT:
        return output[:MAX_OUTPUT] + "\n[OUTPUT TRUNCATED]"
    return output


def _get_repo(directory: str, allowed_roots: List[str]):
    """Get a GitPython Repo object, validating the directory first."""
    try:
        import git as gitmod
    except ImportError:
        raise ImportError("gitpython is not installed: pip install gitpython")

    if not is_path_allowed(directory, allowed_roots):
        raise ValueError(f"Access denied: '{directory}' not within allowed roots")

    resolved = safe_resolve(directory, allowed_roots)

    if not os.path.isdir(resolved):
        raise ValueError(f"Directory does not exist: '{resolved}'")

    try:
        repo = gitmod.Repo(resolved)
    except gitmod.InvalidGitRepositoryError:
        raise ValueError(f"Not a git repository: '{resolved}'")

    return repo, resolved


def git_status(directory: str, allowed_roots: List[str]) -> str:
    """Get the working tree status (modified, untracked, staged files).

    Args:
        directory: Absolute path to the git repository
        allowed_roots: Allowed filesystem roots for sandboxing

    Returns:
        Formatted status string showing branch, changes, and untracked files
    """
    try:
        repo, resolved = _get_repo(directory, allowed_roots)

        lines = [f"Git Status: {resolved}"]
        lines.append("=" * 60)

        # Branch info
        try:
            branch = repo.active_branch.name
            lines.append(f"Branch: {branch}")
        except TypeError:
            # Detached HEAD
            lines.append(f"Branch: DETACHED HEAD ({repo.head.commit.hexsha[:8]})")

        # Remote tracking
        try:
            upstream = repo.active_branch.tracking_branch()
            if upstream:
                lines.append(f"Tracking: {upstream.name}")
                commits_behind = list(repo.iter_commits(f'{upstream.name}..HEAD'))
                commits_ahead = list(repo.iter_commits(f'HEAD..{upstream.name}'))
                if commits_behind:
                    lines.append(f"Commits behind: {len(commits_behind)}")
                if commits_ahead:
                    lines.append(f"Commits ahead: {len(commits_ahead)}")
        except Exception:
            pass

        lines.append("")

        # Staged changes
        staged = repo.index.diff("HEAD")
        if staged:
            lines.append(f"Staged changes ({len(staged)}):")
            for d in staged:
                lines.append(f"  {d.change_type:>12}  {d.b_path}")
            lines.append("")

        # Unstaged (working tree) changes
        unstaged = repo.index.diff(None)
        if unstaged:
            lines.append(f"Unstaged changes ({len(unstaged)}):")
            for d in unstaged:
                lines.append(f"  {d.change_type:>12}  {d.b_path}")
            lines.append("")

        # Untracked files
        untracked = repo.untracked_files
        if untracked:
            lines.append(f"Untracked files ({len(untracked)}):")
            for f in untracked:
                lines.append(f"  {'new file':>12}  {f}")
            lines.append("")

        if not staged and not unstaged and not untracked:
            lines.append("Working tree clean")

        return _truncate("\n".join(lines))

    except ImportError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error getting git status: {e}"


def git_diff(directory: str, allowed_roots: List[str], staged: bool = False,
             file_path: str = "", context_lines: int = 3) -> str:
    """Get the diff of changes in the working tree or staging area.

    Args:
        directory: Absolute path to the git repository
        allowed_roots: Allowed filesystem roots for sandboxing
        staged: If True, show staged changes instead of unstaged
        file_path: Optional file path to limit diff to a single file
        context_lines: Number of context lines around changes

    Returns:
        Unified diff as a string
    """
    try:
        repo, resolved = _get_repo(directory, allowed_roots)

        kwargs = {"unified": context_lines}

        if file_path:
            if not is_path_allowed(file_path, allowed_roots):
                return f"Error: Access denied for file: {file_path}"
            kwargs["file_path"] = safe_resolve(file_path, allowed_roots)

        lines = [f"Git Diff: {resolved}"]
        lines.append(f"Mode: {'staged' if staged else 'unstaged'}")
        lines.append("=" * 60)

        if staged:
            diffs = repo.index.diff("HEAD", **{k: v for k, v in kwargs.items() if k != "file_path"})
        else:
            diffs = repo.index.diff(None, **{k: v for k, v in kwargs.items() if k != "file_path"})

        output_parts = []
        for d in diffs:
            if file_path and d.b_path != file_path:
                continue
            header = f"diff --git a/{d.b_path} b/{d.b_path}"
            output_parts.append(f"{header}\n{d.diff if isinstance(d.diff, str) else d.diff.decode('utf-8', errors='replace')}")

        if output_parts:
            lines.extend(output_parts)
        else:
            lines.append("No changes")

        return _truncate("\n".join(lines))

    except ImportError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error getting git diff: {e}"


def git_commit(directory: str, allowed_roots: List[str], message: str,
               files: Optional[List[str]] = None) -> str:
    """Stage and commit changes.

    Args:
        directory: Absolute path to the git repository
        allowed_roots: Allowed filesystem roots for sandboxing
        message: Commit message
        files: Optional list of specific file paths to stage. If None, stages all changes.

    Returns:
        Commit summary string
    """
    try:
        repo, resolved = _get_repo(directory, allowed_roots)

        if not message or not message.strip():
            return "Error: Commit message cannot be empty"

        # Stage files
        if files:
            resolved_files = []
            for f in files:
                if not is_path_allowed(f, allowed_roots):
                    return f"Error: Access denied for file: {f}"
                resolved_files.append(safe_resolve(f, allowed_roots))
            repo.index.add(resolved_files)
            staged_desc = f"{len(resolved_files)} file(s)"
        else:
            repo.git.add(A=True)
            staged_desc = "all changes"

        # Commit
        commit = repo.index.commit(message)

        lines = [
            f"Commit successful",
            f"  Hash: {commit.hexsha}",
            f"  Short: {commit.hexsha[:8]}",
            f"  Message: {commit.message.strip()}",
            f"  Staged: {staged_desc}",
            f"  Author: {commit.author}",
            f"  Date: {commit.committed_datetime}",
        ]

        return "\n".join(lines)

    except ImportError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error committing: {e}"


def git_branch(directory: str, allowed_roots: List[str],
               create: str = "", delete: str = "",
               rename_from: str = "", rename_to: str = "") -> str:
    """List, create, delete, or rename branches.

    Args:
        directory: Absolute path to the git repository
        allowed_roots: Allowed filesystem roots for sandboxing
        create: Name of a new branch to create
        delete: Name of a branch to delete
        rename_from: Current name of branch to rename
        rename_to: New name for the branch

    Returns:
        Branch listing or operation result
    """
    try:
        repo, resolved = _get_repo(directory, allowed_roots)

        # Rename
        if rename_from and rename_to:
            for b in repo.branches:
                if b.name == rename_from:
                    b.rename(rename_to)
                    return f"Renamed branch '{rename_from}' -> '{rename_to}'"
            return f"Error: Branch '{rename_from}' not found"

        # Delete
        if delete:
            for b in repo.branches:
                if b.name == delete:
                    if b.name == repo.active_branch.name:
                        return f"Error: Cannot delete the currently active branch '{delete}'"
                    repo.git.branch("-D", delete)
                    return f"Deleted branch: {delete}"
            return f"Error: Branch '{delete}' not found"

        # Create
        if create:
            new_branch = repo.create_head(create)
            return f"Created branch: {create} (at {new_branch.commit.hexsha[:8]})"

        # List branches
        lines = [f"Branches: {resolved}", "=" * 60]
        current = repo.active_branch.name

        for b in sorted(repo.branches, key=lambda x: x.name):
            marker = " *" if b.name == current else "  "
            try:
                last_commit = b.commit
                summary = last_commit.summary[:60]
                date = last_commit.committed_datetime.strftime("%Y-%m-%d")
                lines.append(f"{marker} {b.name:<30} {date}  {summary}")
            except Exception:
                lines.append(f"{marker} {b.name}")

        # Remote branches
        try:
            remote_refs = repo.remote().refs
            if remote_refs:
                lines.append("")
                lines.append("Remote branches:")
                for ref in remote_refs:
                    if ref.name != "origin/HEAD":
                        lines.append(f"    {ref.name}")
        except Exception:
            pass

        return _truncate("\n".join(lines))

    except ImportError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error managing branches: {e}"


def git_log(directory: str, allowed_roots: List[str],
            count: int = 20, file_path: str = "",
            author: str = "", since: str = "",
            until: str = "", grep: str = "") -> str:
    """Show commit history with optional filtering.

    Args:
        directory: Absolute path to the git repository
        allowed_roots: Allowed filesystem roots for sandboxing
        count: Maximum number of commits to show
        file_path: Only show commits affecting this file
        author: Filter by author name/email
        since: Only show commits after this date (e.g. "2025-01-01", "1 week ago")
        until: Only show commits before this date
        grep: Filter by commit message pattern

    Returns:
        Formatted commit log
    """
    try:
        repo, resolved = _get_repo(directory, allowed_roots)

        kwargs = {"max_count": min(count, 200)}

        if file_path:
            if not is_path_allowed(file_path, allowed_roots):
                return f"Error: Access denied for file: {file_path}"
            kwargs["paths"] = safe_resolve(file_path, allowed_roots)
        if author:
            kwargs["author"] = author
        if since:
            kwargs["since"] = since
        if until:
            kwargs["until"] = until
        if grep:
            kwargs["grep"] = grep

        commits = list(repo.iter_commits(repo.active_branch.name, **kwargs))

        lines = [f"Git Log: {resolved}"]
        lines.append(f"Showing {len(commits)} commit(s)")
        lines.append("=" * 70)

        for c in commits:
            date = c.committed_datetime.strftime("%Y-%m-%d %H:%M")
            author_name = c.author.name
            summary = c.summary[:80]
            lines.append(f"{c.hexsha[:8]}  {date}  {author_name}")
            lines.append(f"  {summary}")
            lines.append("")

        return _truncate("\n".join(lines))

    except ImportError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error getting git log: {e}"

