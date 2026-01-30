"""GitHub API service using PyGithub."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from github import Auth, Github, GithubException
from github.PullRequest import PullRequest as GHPullRequest
from github.Repository import Repository as GHRepo
from github.WorkflowRun import WorkflowRun as GHWorkflowRun

logger = logging.getLogger(__name__)


class GitHubError(Exception):
    """Exception raised for GitHub API failures."""

    pass


@dataclass
class PullRequestInfo:
    """Information about a pull request."""

    number: int
    title: str
    state: str
    url: str
    html_url: str
    head_sha: str
    head_ref: str
    base_ref: str
    mergeable: bool | None
    merged: bool
    draft: bool
    created_at: datetime
    updated_at: datetime
    merge_commit_sha: str | None = None
    checks_passed: bool | None = None
    review_state: str | None = None


@dataclass
class WorkflowRunInfo:
    """Information about a workflow run."""

    id: int
    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None  # success, failure, cancelled, etc.
    url: str
    html_url: str
    head_sha: str
    head_branch: str
    event: str
    created_at: datetime
    updated_at: datetime
    run_started_at: datetime | None = None


@dataclass
class ReleaseInfo:
    """Information about a GitHub release."""

    id: int
    tag_name: str
    name: str
    body: str
    draft: bool
    prerelease: bool
    html_url: str
    created_at: datetime
    published_at: datetime | None


@dataclass
class BranchInfo:
    """Information about a branch and its latest commit."""

    name: str
    sha: str
    html_url: str
    protected: bool
    commit_message: str
    commit_author: str
    commit_committer: str
    commit_date: datetime
    commit_url: str


@dataclass
class CommitComparison:
    """Comparison result between two commits."""

    status: str  # identical, ahead, behind, diverged
    ahead_by: int
    behind_by: int
    merge_base_sha: str
    html_url: str


class GitHubService:
    """Service for GitHub API operations.

    Provides methods for working with pull requests, workflows, and releases.
    """

    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        """Initialize the GitHub service.

        Args:
            token: GitHub personal access token.
            base_url: GitHub API base URL (for GitHub Enterprise).
        """
        auth = Auth.Token(token)
        if base_url == "https://api.github.com":
            self._client = Github(auth=auth)
        else:
            self._client = Github(auth=auth, base_url=base_url)

    def get_repo(self, repo_path: str) -> GHRepo:
        """Get a repository object.

        Args:
            repo_path: Repository path in "owner/repo" format.

        Returns:
            GitHub repository object.

        Raises:
            GitHubError: If repository not found.
        """
        try:
            return self._client.get_repo(repo_path)
        except GithubException as e:
            raise GitHubError(f"Repository not found: {repo_path}: {e}") from e

    # =========================================================================
    # Pull Request Operations
    # =========================================================================

    def create_pr(
        self,
        repo_path: str,
        *,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        draft: bool = False,
    ) -> PullRequestInfo:
        """Create a pull request.

        Args:
            repo_path: Repository path in "owner/repo" format.
            title: PR title.
            body: PR description.
            head: Head branch name.
            base: Base branch name.
            draft: Create as draft PR.

        Returns:
            Pull request information.

        Raises:
            GitHubError: If PR creation fails.
        """
        try:
            repo = self.get_repo(repo_path)
            pr = repo.create_pull(
                title=title,
                body=body,
                head=head,
                base=base,
                draft=draft,
            )
            logger.info(f"Created PR #{pr.number}: {title}")
            return self._pr_to_info(pr)
        except GithubException as e:
            raise GitHubError(f"Failed to create PR: {e}") from e

    def get_pr(self, repo_path: str, pr_number: int) -> PullRequestInfo:
        """Get pull request information.

        Args:
            repo_path: Repository path in "owner/repo" format.
            pr_number: Pull request number.

        Returns:
            Pull request information.
        """
        try:
            repo = self.get_repo(repo_path)
            pr = repo.get_pull(pr_number)
            return self._pr_to_info(pr)
        except GithubException as e:
            raise GitHubError(f"Failed to get PR #{pr_number}: {e}") from e

    def merge_pr(
        self,
        repo_path: str,
        pr_number: int,
        *,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> bool:
        """Merge a pull request.

        Args:
            repo_path: Repository path.
            pr_number: Pull request number.
            merge_method: Merge method (merge, squash, rebase).
            commit_title: Optional commit title.
            commit_message: Optional commit message.

        Returns:
            True if merged successfully.

        Raises:
            GitHubError: If merge fails.
        """
        try:
            repo = self.get_repo(repo_path)
            pr = repo.get_pull(pr_number)

            kwargs: dict[str, Any] = {"merge_method": merge_method}
            if commit_title:
                kwargs["commit_title"] = commit_title
            if commit_message:
                kwargs["commit_message"] = commit_message

            result = pr.merge(**kwargs)
            if result.merged:
                logger.info(f"Merged PR #{pr_number}")
                return True
            return False
        except GithubException as e:
            raise GitHubError(f"Failed to merge PR #{pr_number}: {e}") from e

    def get_pr_checks_status(self, repo_path: str, pr_number: int) -> dict[str, Any]:
        """Get the status of checks on a pull request.

        Args:
            repo_path: Repository path.
            pr_number: Pull request number.

        Returns:
            Dictionary with check information.
        """
        try:
            repo = self.get_repo(repo_path)
            pr = repo.get_pull(pr_number)

            # Get combined status
            commit = repo.get_commit(pr.head.sha)
            combined_status = commit.get_combined_status()

            # Get check runs
            check_runs = list(commit.get_check_runs())

            return {
                "state": combined_status.state,
                "total_count": combined_status.total_count,
                "statuses": [
                    {"context": s.context, "state": s.state, "description": s.description}
                    for s in combined_status.statuses
                ],
                "check_runs": [
                    {
                        "name": cr.name,
                        "status": cr.status,
                        "conclusion": cr.conclusion,
                    }
                    for cr in check_runs
                ],
            }
        except GithubException as e:
            raise GitHubError(f"Failed to get PR checks: {e}") from e

    def get_pr_reviews(self, repo_path: str, pr_number: int) -> list[dict[str, Any]]:
        """Get reviews on a pull request.

        Args:
            repo_path: Repository path.
            pr_number: Pull request number.

        Returns:
            List of review information.
        """
        try:
            repo = self.get_repo(repo_path)
            pr = repo.get_pull(pr_number)
            reviews = list(pr.get_reviews())

            return [
                {
                    "user": r.user.login if r.user else None,
                    "state": r.state,
                    "submitted_at": r.submitted_at,
                }
                for r in reviews
            ]
        except GithubException as e:
            raise GitHubError(f"Failed to get PR reviews: {e}") from e

    def list_open_prs(self, repo_path: str, *, base: str | None = None) -> list[PullRequestInfo]:
        """List open pull requests.

        Args:
            repo_path: Repository path.
            base: Filter by base branch.

        Returns:
            List of open pull requests.
        """
        try:
            repo = self.get_repo(repo_path)
            prs = repo.get_pulls(state="open", base=base) if base else repo.get_pulls(state="open")
            return [self._pr_to_info(pr) for pr in prs]
        except GithubException as e:
            raise GitHubError(f"Failed to list PRs: {e}") from e

    def _pr_to_info(self, pr: GHPullRequest) -> PullRequestInfo:
        """Convert GitHub PR object to PullRequestInfo."""
        return PullRequestInfo(
            number=pr.number,
            title=pr.title,
            state=pr.state,
            url=pr.url,
            html_url=pr.html_url,
            head_sha=pr.head.sha,
            head_ref=pr.head.ref,
            base_ref=pr.base.ref,
            mergeable=pr.mergeable,
            merged=pr.merged,
            draft=pr.draft,
            created_at=pr.created_at or datetime.now(UTC),
            updated_at=pr.updated_at or pr.created_at or datetime.now(UTC),
            merge_commit_sha=pr.merge_commit_sha if pr.merged else None,
        )

    # =========================================================================
    # Workflow Operations
    # =========================================================================

    def trigger_workflow(
        self,
        repo_path: str,
        workflow_file: str,
        *,
        ref: str = "main",
        inputs: dict[str, str] | None = None,
        wait_for_run_seconds: int = 60,
    ) -> int:
        """Trigger a workflow dispatch event.

        Args:
            repo_path: Repository path.
            workflow_file: Workflow filename (e.g., "release.yaml").
            ref: Git ref to run workflow on.
            inputs: Workflow inputs.
            wait_for_run_seconds: Seconds to wait for the run to appear (default: 30).

        Returns:
            Workflow run ID if available, None otherwise.

        Raises:
            GitHubError: If trigger fails.
        """
        try:
            repo = self.get_repo(repo_path)
            workflow = repo.get_workflow(workflow_file)

            success = workflow.create_dispatch(ref=ref, inputs=inputs or {})
            if not success:
                raise GitHubError(f"Failed to trigger workflow: {workflow_file}")

            logger.info(f"Triggered workflow: {workflow_file} on {ref}")

            # Try to get the run ID (may take a moment to appear)
            import time

            deadline = time.monotonic() + wait_for_run_seconds
            while time.monotonic() < deadline:
                runs = list(workflow.get_runs(branch=ref, event="workflow_dispatch"))
                if runs:
                    return runs[0].id
                time.sleep(2)

            raise GitHubError(f"Workflow run ID not available yet for {workflow_file} on {ref}")

        except GithubException as e:
            raise GitHubError(f"Failed to trigger workflow {workflow_file}: {e}") from e

    def get_workflow_run(self, repo_path: str, run_id: int) -> WorkflowRunInfo:
        """Get workflow run information.

        Args:
            repo_path: Repository path.
            run_id: Workflow run ID.

        Returns:
            Workflow run information.
        """
        try:
            repo = self.get_repo(repo_path)
            run = repo.get_workflow_run(run_id)
            return self._run_to_info(run)
        except GithubException as e:
            raise GitHubError(f"Failed to get workflow run {run_id}: {e}") from e

    def list_workflow_runs(
        self,
        repo_path: str,
        *,
        workflow_file: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        head_sha: str | None = None,
        limit: int = 10,
    ) -> list[WorkflowRunInfo]:
        """List workflow runs.

        Args:
            repo_path: Repository path.
            workflow_file: Filter by workflow file.
            branch: Filter by branch.
            status: Filter by status.
            head_sha: Filter by head commit SHA.
            limit: Maximum number of runs to return.

        Returns:
            List of workflow runs.
        """
        try:
            repo = self.get_repo(repo_path)

            kwargs: dict[str, Any] = {}
            if branch:
                kwargs["branch"] = branch
            if status:
                kwargs["status"] = status
            if head_sha:
                kwargs["head_sha"] = head_sha

            if workflow_file:
                workflow = repo.get_workflow(workflow_file)
                runs = workflow.get_runs(**kwargs)
            else:
                runs = repo.get_workflow_runs(**kwargs)

            return [self._run_to_info(run) for run in list(runs)[:limit]]
        except GithubException as e:
            raise GitHubError(f"Failed to list workflow runs: {e}") from e

    def _run_to_info(self, run: GHWorkflowRun) -> WorkflowRunInfo:
        """Convert GitHub workflow run to WorkflowRunInfo."""
        return WorkflowRunInfo(
            id=run.id,
            name=run.name or "",
            status=run.status,
            conclusion=run.conclusion,
            url=run.url,
            html_url=run.html_url,
            head_sha=run.head_sha,
            head_branch=run.head_branch or "",
            event=run.event,
            created_at=run.created_at,
            updated_at=run.updated_at or run.created_at or datetime.now(UTC),
            run_started_at=run.run_started_at,
        )

    # =========================================================================
    # Release Operations
    # =========================================================================

    def create_release(
        self,
        repo_path: str,
        *,
        tag_name: str,
        name: str | None = None,
        body: str = "",
        draft: bool = False,
        prerelease: bool = False,
        target_commitish: str | None = None,
    ) -> ReleaseInfo:
        """Create a GitHub release.

        Args:
            repo_path: Repository path.
            tag_name: Tag name for the release.
            name: Release name (defaults to tag_name).
            body: Release notes.
            draft: Create as draft.
            prerelease: Mark as prerelease.
            target_commitish: Commit/branch for the tag.

        Returns:
            Release information.
        """
        try:
            repo = self.get_repo(repo_path)

            kwargs: dict[str, Any] = {
                "tag": tag_name,
                "name": name or tag_name,
                "message": body,
                "draft": draft,
                "prerelease": prerelease,
            }
            if target_commitish:
                kwargs["target_commitish"] = target_commitish

            release = repo.create_git_release(**kwargs)
            logger.info(f"Created release: {tag_name}")
            return self._release_to_info(release)
        except GithubException as e:
            raise GitHubError(f"Failed to create release {tag_name}: {e}") from e

    def get_latest_release(self, repo_path: str) -> ReleaseInfo | None:
        """Get the latest release.

        Args:
            repo_path: Repository path.

        Returns:
            Latest release info, or None if no releases.
        """
        try:
            repo = self.get_repo(repo_path)
            release = repo.get_latest_release()
            return self._release_to_info(release)
        except GithubException as e:
            if e.status == 404:
                return None
            raise GitHubError(f"Failed to get latest release: {e}") from e

    def list_releases(self, repo_path: str, *, limit: int = 10) -> list[ReleaseInfo]:
        """List releases.

        Args:
            repo_path: Repository path.
            limit: Maximum number of releases.

        Returns:
            List of releases.
        """
        try:
            repo = self.get_repo(repo_path)
            releases = list(repo.get_releases())[:limit]
            return [self._release_to_info(r) for r in releases]
        except GithubException as e:
            raise GitHubError(f"Failed to list releases: {e}") from e

    def _release_to_info(self, release: Any) -> ReleaseInfo:
        """Convert GitHub release to ReleaseInfo."""
        return ReleaseInfo(
            id=release.id,
            tag_name=release.tag_name,
            name=release.title or release.tag_name,
            body=release.body or "",
            draft=release.draft,
            prerelease=release.prerelease,
            html_url=release.html_url,
            created_at=release.created_at,
            published_at=release.published_at,
        )

    # =========================================================================
    # Tag Operations
    # =========================================================================

    def create_tag(
        self,
        repo_path: str,
        *,
        tag_name: str,
        message: str,
        sha: str,
    ) -> str:
        """Create a git tag.

        Args:
            repo_path: Repository path.
            tag_name: Tag name.
            message: Tag message.
            sha: Commit SHA to tag.

        Returns:
            Tag SHA.
        """
        try:
            repo = self.get_repo(repo_path)
            tag = repo.create_git_tag(
                tag=tag_name,
                message=message,
                object=sha,
                type="commit",
            )
            # Create the reference
            repo.create_git_ref(ref=f"refs/tags/{tag_name}", sha=tag.sha)
            logger.info(f"Created tag: {tag_name}")
            return tag.sha
        except GithubException as e:
            raise GitHubError(f"Failed to create tag {tag_name}: {e}") from e

    def get_default_branch(self, repo_path: str) -> str:
        """Get the default branch name.

        Args:
            repo_path: Repository path.

        Returns:
            Default branch name.
        """
        repo = self.get_repo(repo_path)
        return repo.default_branch

    def get_branch(self, repo_path: str, branch_name: str) -> BranchInfo | None:
        """Get branch information including latest commit details."""
        try:
            repo = self.get_repo(repo_path)
            branch = repo.get_branch(branch_name)
            commit = branch.commit

            return BranchInfo(
                name=branch.name,
                sha=commit.sha,
                html_url=f"https://github.com/{repo_path}/tree/{branch_name}",
                protected=branch.protected,
                commit_message=commit.commit.message,
                commit_author=commit.commit.author.name if commit.commit.author else "",
                commit_committer=commit.commit.committer.name if commit.commit.committer else "",
                commit_date=commit.commit.author.date
                if commit.commit.author
                else commit.commit.committer.date,
                commit_url=commit.html_url,
            )
        except GithubException as e:
            if e.status == 404:
                return None
            raise GitHubError(f"Failed to get branch {branch_name}: {e}") from e

    # =========================================================================
    # Commit Comparison Operations
    # =========================================================================

    def compare_commits(
        self,
        repo_path: str,
        base: str,
        head: str,
    ) -> CommitComparison:
        """Compare two commits or branches.

        Args:
            repo_path: Repository path.
            base: Base commit SHA, branch, or tag.
            head: Head commit SHA, branch, or tag.

        Returns:
            Comparison result with status and commit counts.

        Raises:
            GitHubError: If comparison fails.
        """
        try:
            repo = self.get_repo(repo_path)
            comparison = repo.compare(base, head)

            return CommitComparison(
                status=comparison.status,
                ahead_by=comparison.ahead_by,
                behind_by=comparison.behind_by,
                merge_base_sha=comparison.merge_base_commit.sha,
                html_url=comparison.html_url,
            )
        except GithubException as e:
            raise GitHubError(f"Failed to compare {base}...{head}: {e}") from e

    def close(self) -> None:
        """Close the GitHub client."""
        self._client.close()
