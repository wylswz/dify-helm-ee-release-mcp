# Helm Release MCP Server

MCP (Model Context Protocol) server for automating Dify EE Helm chart releases across GitHub repositories.

## Features

- **Multi-repo management**: Configure and manage multiple repositories from a single server
- **Release branch creation**: Create release branches from any git ref (tag, branch, SHA)
- **Pre-release checks**: Trigger CVE scans, benchmarks, license reviews, and Linear checklists
- **Release workflows**: Publish Helm charts via workflow triggers
- **Tag-based builds**: Trigger builds by creating tags on release branches
- **Per-repo tokens**: Use different GitHub tokens per repository
- **Flexible configuration**: YAML-based repository configuration with environment variable support

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- GitHub Personal Access Token (see below)

### GitHub Token Setup

Create a **Fine-Grained Personal Access Token** at [GitHub Settings > Developer settings > Fine-grained tokens](https://github.com/settings/tokens?type=beta):

| Permission | Access Level | Required For |
|------------|--------------|--------------|
| **Contents** | Read & Write | Clone, commit, push, create branches/tags |
| **Pull requests** | Read & Write | Create and merge PRs |
| **Actions** | Read & Write | Trigger workflows, check run status |
| **Metadata** | Read | Required for API access |

**Repository access**: Select "Only select repositories" and choose the repos you'll manage, or "All repositories" for org-wide access.

### Installation

```bash
# Clone the repository
git clone https://github.com/yourorg/helm-release-mcp.git
cd helm-release-mcp

# Install dependencies
uv sync
```

### Configuration

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set your GitHub token:

   ```
   HELM_MCP_GITHUB_TOKEN=ghp_your_token_here
   ```

3. Configure your repositories in `config/repos.yaml`:

   ```yaml
   repositories:
     - name: dify
       github: langgenius/dify
       type: dify
       description: Dify core services

      - name: dify-helm
        github: langgenius/dify-helm
        type: dify-helm
        description: Dify Helm charts
        settings:
          github_token: ${DIFY_HELM_GITHUB_TOKEN}
          cve_scan_workflow: .github/workflows/cve.yaml
          benchmark_workflow: .github/workflows/benchmark.yaml
          license_review_workflow: .github/workflows/enterprise-license.yaml
          linear_checklist_workflow: .github/workflows/linear-checklist.yaml
          release_workflow: .github/workflows/release.yaml

      - name: dify-enterprise
        github: langgenius/dify-enterprise
        type: dify-enterprise
        description: Dify Enterprise services monorepo
        settings:
          github_token: ${DIFY_ENTERPRISE_GITHUB_TOKEN}

      - name: dify-enterprise-frontend
        github: langgenius/dify-enterprise-frontend
        type: dify-enterprise-frontend
        description: Dify Enterprise frontend
        settings:
          github_token: ${DIFY_ENTERPRISE_FRONTEND_GITHUB_TOKEN}

   ```

   See [docs/configuration.md](docs/configuration.md) for full configuration reference.

### Running the Server

```bash
uv run helm-release-mcp
```

To run over HTTP locally:

```bash
HELM_MCP_TRANSPORT=streamable-http HELM_MCP_HOST=0.0.0.0 HELM_MCP_PORT=8000 uv run helm-release-mcp
```

With authentication enabled:

```bash
HELM_MCP_AUTH_TOKEN=your-secret-token HELM_MCP_TRANSPORT=streamable-http HELM_MCP_HOST=0.0.0.0 HELM_MCP_PORT=8000 uv run helm-release-mcp
```

### HTTP API Endpoints

When running with HTTP transport, the server exposes:

| Endpoint | Auth Required | Description |
|----------|---------------|-------------|
| `POST /mcp` | Yes (if `HELM_MCP_AUTH_TOKEN` set) | MCP protocol endpoint |
| `GET /api/health` | No | Health check endpoint |
| `GET /api/tool-calls` | Yes | List pending tool calls |

Authentication uses Bearer token in the `Authorization` header:

```bash
curl -H "Authorization: Bearer your-secret-token" http://localhost:8000/mcp
```

### MCP Client Configuration

For Claude Desktop, add to your MCP settings:

```json
{
  "mcpServers": {
    "helm-release": {
      "command": "uv",
      "args": ["--directory", "/path/to/helm-release-mcp", "run", "helm-release-mcp"],
      "env": {
        "HELM_MCP_GITHUB_TOKEN": "ghp_xxxx",
        "HELM_MCP_AUTH_TOKEN": "your-long-random-token",
        "DIFY_GITHUB_TOKEN": "ghp_yyyy",
        "DIFY_HELM_GITHUB_TOKEN": "ghp_zzzz",
        "DIFY_ENTERPRISE_GITHUB_TOKEN": "ghp_aaaa",
        "DIFY_ENTERPRISE_FRONTEND_GITHUB_TOKEN": "ghp_bbbb"
      }
    }
  }
}
```

## Available Tools

### Global Tools

#### Discovery Tools

- `list_repos()` - List all managed repositories
- `get_repo_status(repo)` - Get high-level status of a repository
- `get_repo_operations(repo)` - Get available operations for a repository

#### Branch & Commit Tools

- `create_branch(repo, branch, base_ref)` - Create a remote branch from a git ref (tag, branch, or SHA)
- `get_release_branch_info(repo, branch)` - Get branch info with commit details and workflow runs
- `check_commit_in_branch(repo, commit, branch)` - Check if a commit SHA is in a branch

#### PR Tools

- `check_pr(repo, pr_number?, pr_url?)` - Get PR status by number or URL (state, checks, reviews)
- `check_pr_in_branch(repo, branch, pr_number?, pr_url?)` - Check if a PR is in a branch
- `list_open_prs(repo, base?)` - List open pull requests

#### Workflow Tools

- `check_workflow(repo, run_id)` - Check workflow run status
- `wait_for_workflow(repo, run_id, timeout?, poll_interval?)` - Wait for workflow completion
- `list_workflow_runs(repo, workflow_file?, branch?, tag?, status?, limit?)` - List recent workflow runs (requires branch or tag)


### Dify Enterprise Operations

- `dify-enterprise__create_tag(branch, tag)` - Create tag on branch to trigger build/CI

### Dify Enterprise Frontend Operations

- `dify-enterprise-frontend__create_tag(branch, tag)` - Create tag on branch to trigger build/CI

### Dify Helm Operations

- `dify-helm__trigger_cve_scan(branch)` - Trigger container security scan on release branch
- `dify-helm__trigger_benchmark(branch)` - Trigger benchmark test on release branch
- `dify-helm__trigger_license_review(branch)` - Trigger dependency license review on release branch
- `dify-helm__trigger_linear_checklist(branch)` - Trigger Linear release checklist on release branch
- `dify-helm__release(branch)` - Trigger release workflow to publish Helm chart

## Example Workflow

```
# 1. Create release branch from any ref (tag, branch, or SHA)
dify__create_release_branch("0.15.3", "release/ee-1.0.0")

# 2. Run pre-release checks on dify-helm
dify-helm__trigger_cve_scan("release/1.0.0")
dify-helm__trigger_benchmark("release/1.0.0")
dify-helm__trigger_license_review("release/1.0.0")
dify-helm__trigger_linear_checklist("release/1.0.0")

# 3. Release Helm chart
dify-helm__release("release/1.0.0")

# 4. Tag enterprise repos to trigger builds
dify-enterprise__create_tag("release/1.0.0", "v1.0.0")
dify-enterprise-frontend__create_tag("release/1.0.0", "v1.0.0")
```

## Repository Types

### dify

For the Dify core services repository. Supports:
- Creating release branches from any git ref (tag, branch, or SHA)

### dify-helm

For the Dify Helm charts repository. Supports:
- CVE scanning workflow triggers
- Benchmark test workflow triggers
- License review workflow triggers
- Linear checklist workflow triggers
- Release workflow to publish Helm charts

### dify-enterprise

For the Dify Enterprise monorepo. Supports:
- Tag creation on branches to trigger builds

### dify-enterprise-frontend

For the Dify Enterprise Frontend repository. Supports:
- Tag creation on branches to trigger builds

## DockerHub Release

Create a git tag like `v1.2.3` to trigger the DockerHub publish workflow. Configure these repository secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

Images will publish to `DOCKERHUB_USERNAME/helm-release-mcp` with tags `vX.Y.Z` and `latest`.

## Development

```bash
# Install dev dependencies
uv sync

# Run linting
make lint

# Run type checking
uv run mypy src/

# Run tests
uv run pytest
```

## License

MIT
