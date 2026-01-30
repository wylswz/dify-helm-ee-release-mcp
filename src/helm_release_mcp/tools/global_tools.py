"""Global MCP tools for discovery and status queries."""

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from fastmcp import FastMCP

from helm_release_mcp.repos.registry import RepoRegistry
from helm_release_mcp.tools.pr_commit_handler import PrCommitHandler
from helm_release_mcp.core.tool_calls import aapprove_required

logger = logging.getLogger(__name__)


def register_global_tools(mcp: FastMCP, registry: RepoRegistry) -> None:
    """Register global discovery and status tools.

    Args:
        mcp: FastMCP server instance.
        registry: Repository registry.
    """

    # =========================================================================
    # Discovery Tools
    # =========================================================================

    @mcp.tool()
    async def list_repos() -> dict[str, Any]:
        """List all managed repositories with their types and available operations.

        Returns information about each configured repository including
        its name, type, description, and available operations.
        """
        repos_info = []

        for name in registry.list_repos():
            repo = registry.get_repo(name)
            if repo:
                operations = repo.get_operations()
                repos_info.append(
                    {
                        "name": repo.name,
                        "github": repo.github_path,
                        "type": repo.repo_type,
                        "description": repo.config.description,
                        "operations": list(operations.keys()),
                    }
                )

        return {
            "repos": repos_info,
            "count": len(repos_info),
        }

    @mcp.tool()
    async def get_repo_status(repo: str) -> dict[str, Any]:
        """Get high-level status of a specific repository.

        Args:
            repo: Repository name.

        Returns status including latest release, open PRs, running workflows.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        try:
            status = await repo_obj.get_status()
            return {
                "success": True,
                **asdict(status),
            }
        except Exception as e:
            logger.exception(f"Error getting status for {repo}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def get_repo_operations(repo: str) -> dict[str, Any]:
        """Get available operations for a repository.

        Args:
            repo: Repository name.

        Returns list of operations with their parameters and descriptions.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        operations = repo_obj.get_operations()

        return {
            "success": True,
            "repo": repo,
            "type": repo_obj.repo_type,
            "operations": {name: asdict(info) for name, info in operations.items()},
        }

    # =========================================================================
    # Status Query Tools
    # =========================================================================

    @mcp.tool()
    async def check_workflow(repo: str, run_id: int) -> dict[str, Any]:
        """Check the status of a GitHub Actions workflow run.

        Args:
            repo: Repository name.
            run_id: Workflow run ID.

        Returns workflow status including conclusion if completed.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        try:
            run_info = registry.services.github.get_workflow_run(repo_obj.github_path, run_id)
            return {
                "success": True,
                "id": run_info.id,
                "name": run_info.name,
                "status": run_info.status,
                "conclusion": run_info.conclusion,
                "html_url": run_info.html_url,
                "head_branch": run_info.head_branch,
                "event": run_info.event,
                "created_at": run_info.created_at.isoformat(),
                "updated_at": run_info.updated_at.isoformat(),
            }
        except Exception as e:
            logger.exception(f"Error checking workflow {run_id}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def check_pr(
        repo: str,
        pr_number: int | None = None,
        pr_url: str | None = None,
    ) -> dict[str, Any]:
        """Check the status of a pull request.

        Args:
            repo: Repository name.
            pr_number: Pull request number.
            pr_url: Pull request URL (alternative to pr_number).

        Returns PR status including state, checks, and review status.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        handler = PrCommitHandler()
        resolution = handler.resolve_pr_identifier(
            repo_obj.github_path,
            pr_number=pr_number,
            pr_url=pr_url,
        )

        if not resolution["success"]:
            return resolution

        resolved_pr_number = resolution["pr_number"]

        try:
            github_path = repo_obj.github_path
            github = registry.services.github

            pr_info = github.get_pr(github_path, resolved_pr_number)

            checks = github.get_pr_checks_status(github_path, resolved_pr_number)

            reviews = github.get_pr_reviews(github_path, resolved_pr_number)

            review_state = "pending"
            for review in reversed(reviews):
                if review["state"] in ("APPROVED", "CHANGES_REQUESTED"):
                    review_state = review["state"].lower()
                    break

            return {
                "success": True,
                "number": pr_info.number,
                "title": pr_info.title,
                "state": pr_info.state,
                "draft": pr_info.draft,
                "mergeable": pr_info.mergeable,
                "merged": pr_info.merged,
                "merge_commit_sha": pr_info.merge_commit_sha,
                "html_url": pr_info.html_url,
                "head_ref": pr_info.head_ref,
                "head_sha": pr_info.head_sha,
                "base_ref": pr_info.base_ref,
                "checks_state": checks["state"],
                "checks_passed": checks["state"] == "success",
                "review_state": review_state,
                "reviews_count": len(reviews),
                "created_at": pr_info.created_at.isoformat(),
                "updated_at": pr_info.updated_at.isoformat(),
            }
        except Exception as e:
            logger.exception(f"Error checking PR #{resolved_pr_number}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def check_commit_in_branch(
        repo: str,
        commit: str,
        branch: str,
    ) -> dict[str, Any]:
        """Check if a commit is in a branch.

        Args:
            repo: Repository name.
            commit: Commit SHA to check.
            branch: Branch name to check against.

        Returns whether the commit is in the branch with comparison details.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        try:
            github = registry.services.github
            github_path = repo_obj.github_path

            comparison = github.compare_commits(github_path, commit, branch)

            handler = PrCommitHandler()
            contains = handler.check_commit_in_branch(
                {
                    "status": comparison.status,
                    "ahead_by": comparison.ahead_by,
                    "behind_by": comparison.behind_by,
                    "merge_base_sha": comparison.merge_base_sha,
                },
                commit,
            )

            return {
                "success": True,
                "contains": contains,
                "commit": commit,
                "branch": branch,
                "comparison_status": comparison.status,
                "ahead_by": comparison.ahead_by,
                "behind_by": comparison.behind_by,
                "merge_base_sha": comparison.merge_base_sha,
                "comparison_url": comparison.html_url,
            }
        except Exception as e:
            logger.exception(f"Error checking commit {commit} in branch {branch}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def check_pr_in_branch(
        repo: str,
        branch: str,
        pr_number: int | None = None,
        pr_url: str | None = None,
    ) -> dict[str, Any]:
        """Check if a pull request is in a branch.

        Args:
            repo: Repository name.
            branch: Branch name to check against.
            pr_number: Pull request number.
            pr_url: Pull request URL (alternative to pr_number).

        Returns whether the PR is in the branch with PR and comparison details.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        handler = PrCommitHandler()
        resolution = handler.resolve_pr_identifier(
            repo_obj.github_path,
            pr_number=pr_number,
            pr_url=pr_url,
        )

        if not resolution["success"]:
            return resolution

        resolved_pr_number = resolution["pr_number"]

        try:
            github = registry.services.github
            github_path = repo_obj.github_path

            pr_info = github.get_pr(github_path, resolved_pr_number)

            if pr_info.merged and pr_info.base_ref == branch:
                return {
                    "success": True,
                    "contains": True,
                    "reason": "PR merged into target branch",
                    "pr_number": pr_info.number,
                    "pr_title": pr_info.title,
                    "pr_state": pr_info.state,
                    "pr_merged": pr_info.merged,
                    "pr_base_ref": pr_info.base_ref,
                    "pr_head_ref": pr_info.head_ref,
                    "pr_merge_commit_sha": pr_info.merge_commit_sha,
                    "branch": branch,
                }

            commit_to_check = (
                pr_info.merge_commit_sha if pr_info.merge_commit_sha else pr_info.head_sha
            )

            comparison = github.compare_commits(github_path, commit_to_check, branch)

            contains = handler.check_commit_in_branch(
                {
                    "status": comparison.status,
                    "ahead_by": comparison.ahead_by,
                    "behind_by": comparison.behind_by,
                    "merge_base_sha": comparison.merge_base_sha,
                },
                commit_to_check,
            )

            return {
                "success": True,
                "contains": contains,
                "pr_number": pr_info.number,
                "pr_title": pr_info.title,
                "pr_state": pr_info.state,
                "pr_merged": pr_info.merged,
                "pr_base_ref": pr_info.base_ref,
                "pr_head_ref": pr_info.head_ref,
                "pr_head_sha": pr_info.head_sha,
                "pr_merge_commit_sha": pr_info.merge_commit_sha,
                "branch": branch,
                "checked_commit": commit_to_check,
                "comparison_status": comparison.status,
                "ahead_by": comparison.ahead_by,
                "behind_by": comparison.behind_by,
                "merge_base_sha": comparison.merge_base_sha,
                "comparison_url": comparison.html_url,
            }
        except Exception as e:
            logger.exception(f"Error checking PR #{resolved_pr_number} in branch {branch}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def wait_for_workflow(
        repo: str,
        run_id: int,
        timeout: int = 3600,
        poll_interval: int = 10,
    ) -> dict[str, Any]:
        """Wait for a workflow run to complete.

        Args:
            repo: Repository name.
            run_id: Workflow run ID.
            timeout: Maximum seconds to wait (default: 3600).
            poll_interval: Seconds between status checks (default: 10).

        Returns final workflow status when completed or timeout.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        github = registry.services.github
        github_path = repo_obj.github_path

        elapsed = 0
        last_status = None

        while elapsed < timeout:
            try:
                run_info = github.get_workflow_run(github_path, run_id)
                last_status = run_info.status

                if run_info.status == "completed":
                    return {
                        "success": True,
                        "completed": True,
                        "id": run_info.id,
                        "name": run_info.name,
                        "status": run_info.status,
                        "conclusion": run_info.conclusion,
                        "html_url": run_info.html_url,
                        "elapsed_seconds": elapsed,
                    }

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            except Exception as e:
                logger.warning(f"Error polling workflow {run_id}: {e}")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

        return {
            "success": False,
            "completed": False,
            "error": "Timeout waiting for workflow completion",
            "timeout": timeout,
            "last_status": last_status,
        }

    @mcp.tool()
    async def list_workflow_runs(
        repo: str,
        workflow_file: str | None = None,
        branch: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """List recent workflow runs for a repository.

        Args:
            repo: Repository name.
            workflow_file: Filter by workflow file (e.g., "ci.yaml").
            branch: Filter by branch (mutually exclusive with tag).
            tag: Filter by tag (mutually exclusive with branch).
            status: Filter by status. Available values: queued, in_progress, completed,
                    action_required, cancelled, failure, neutral, skipped, stale, success,
                    timed_out, waiting, pending, requested.
            limit: Maximum runs to return (default: 10).

        Note:
            Either 'branch' or 'tag' must be provided. If both are provided, 'tag' takes priority.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        if not branch and not tag:
            return {
                "success": False,
                "error": "Either 'branch' or 'tag' must be provided",
            }

        head_sha = None
        if tag:
            try:
                github_repo = repo_obj.github.get_repo(repo_obj.github_path)
                normalized_tag = tag.replace("refs/tags/", "")
                tag_ref = github_repo.get_git_ref(f"tags/{normalized_tag}")

                # Annotated tags require dereferencing to reach the commit object
                if tag_ref.object.type == "tag":
                    git_tag = github_repo.get_git_tag(tag_ref.object.sha)
                    head_sha = git_tag.object.sha
                else:
                    head_sha = tag_ref.object.sha

                branch = None
            except Exception as e:
                logger.exception(f"Error resolving tag: {tag}")
                return {
                    "success": False,
                    "error": f"Tag not found or invalid: {tag}. Error: {str(e)}",
                }

        try:
            runs = registry.services.github.list_workflow_runs(
                repo_obj.github_path,
                workflow_file=workflow_file,
                branch=branch,
                status=status,
                head_sha=head_sha,
                limit=limit,
            )

            return {
                "success": True,
                "runs": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "status": r.status,
                        "conclusion": r.conclusion,
                        "html_url": r.html_url,
                        "head_branch": r.head_branch,
                        "event": r.event,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in runs
                ],
                "count": len(runs),
            }
        except Exception as e:
            logger.exception("Error listing workflow runs")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def list_open_prs(repo: str, base: str | None = None) -> dict[str, Any]:
        """List open pull requests for a repository.

        Args:
            repo: Repository name.
            base: Filter by base branch.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        try:
            prs = registry.services.github.list_open_prs(repo_obj.github_path, base=base)

            return {
                "success": True,
                "prs": [
                    {
                        "number": pr.number,
                        "title": pr.title,
                        "state": pr.state,
                        "draft": pr.draft,
                        "html_url": pr.html_url,
                        "head_ref": pr.head_ref,
                        "base_ref": pr.base_ref,
                        "created_at": pr.created_at.isoformat(),
                    }
                    for pr in prs
                ],
                "count": len(prs),
            }
        except Exception as e:
            logger.exception("Error listing open PRs")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    @aapprove_required()
    async def create_branch(repo: str, branch: str, base_ref: str | None = None) -> dict[str, Any]:
        """Create a new branch in a repository (remote GitHub ref).

        Args:
            repo: Repository name.
            branch: Branch name to create.
            base_ref: Optional Git ref to base the branch on (tag, branch, or SHA).
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        try:
            github_repo = repo_obj.github.get_repo(repo_obj.github_path)

            if base_ref is None:
                base_ref = repo_obj.github.get_default_branch(repo_obj.github_path)

            base_sha = None

            try:
                ref = github_repo.get_git_ref(f"tags/{base_ref}")
                base_sha = ref.object.sha
            except Exception:
                pass

            if not base_sha:
                try:
                    branch_ref = github_repo.get_branch(base_ref)
                    base_sha = branch_ref.commit.sha
                except Exception:
                    pass

            if not base_sha:
                try:
                    commit = github_repo.get_commit(base_ref)
                    base_sha = commit.sha
                except Exception:
                    pass

            if not base_sha:
                return {
                    "success": False,
                    "error": f"Could not resolve ref: {base_ref}",
                }

            try:
                github_repo.get_branch(branch)
                return {
                    "success": False,
                    "error": f"Branch already exists: {branch}",
                }
            except Exception:
                pass

            github_repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base_sha)

            return {
                "success": True,
                "repo": repo,
                "branch": branch,
                "base_ref": base_ref,
                "sha": base_sha,
                "url": f"https://github.com/{repo_obj.github_path}/tree/{branch}",
            }
        except Exception as e:
            logger.exception("Error creating branch")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def get_release_branch_info(repo: str, branch: str) -> dict[str, Any]:
        """Get release branch info including latest commit and workflow runs.

        Args:
            repo: Repository name.
            branch: Branch name to check.
        """
        repo_obj = registry.get_repo(repo)
        if not repo_obj:
            return {
                "success": False,
                "error": f"Repository not found: {repo}",
            }

        try:
            github = repo_obj.github
            branch_info = github.get_branch(repo_obj.github_path, branch)

            if branch_info is None:
                return {
                    "success": False,
                    "exists": False,
                    "error": f"Branch not found: {branch}",
                }

            workflow_runs = github.list_workflow_runs(
                repo_obj.github_path,
                branch=branch,
                limit=5,
            )

            return {
                "success": True,
                "exists": True,
                "branch_name": branch_info.name,
                "branch_url": branch_info.html_url,
                "branch_sha": branch_info.sha,
                "branch_protected": branch_info.protected,
                "commit_message": branch_info.commit_message,
                "commit_author": branch_info.commit_author,
                "commit_committer": branch_info.commit_committer,
                "commit_date": branch_info.commit_date.isoformat(),
                "commit_url": branch_info.commit_url,
                "workflow_runs": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "status": r.status,
                        "conclusion": r.conclusion,
                        "html_url": r.html_url,
                        "event": r.event,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in workflow_runs
                ],
            }
        except Exception as e:
            logger.exception("Error getting branch info")
            return {
                "success": False,
                "error": str(e),
            }
