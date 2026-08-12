# Releases and build identity

`VERSION` is the product release source of truth. It is manual SemVer; package
manager versions are metadata and do not drive the UI.

- **Major** — a deliberate compatibility or product milestone, including 1.0.
- **Minor** — a coherent user-facing feature release.
- **Patch** — fixes and small refinements.

Do not bump for every commit or infer a minor bump from every PR. Each concrete
deployment is already identified by its Git SHA.

## Cut a release

1. Run the **Product release** workflow manually and choose `major`, `minor`, or
   `patch`.
2. The workflow calculates the next version with `scripts/bump_version.py`,
   moves the current Phase 3 changelog section under that version, and opens a
   `release/vX.Y.Z` PR changing only `VERSION` and `CHANGELOG.md`. GitHub
   suppresses recursive workflow events from its own token, so the release
   workflow explicitly dispatches the repository's ordinary `ci.yml` against
   the release branch.
3. Review the changelog, let ordinary CI pass, and merge the PR.
4. The closed-PR half of the workflow verifies the branch, SemVer, and changed
   files, then creates the matching `vX.Y.Z` tag and GitHub Release at the merge
   commit. Ordinary CI and ordinary PRs never publish.

Build identity is automatic: API and frontend prefer `RENDER_GIT_COMMIT`, fall
back to `GITHUB_SHA` in CI, and use `dev` locally. Their independently deployed
SHAs may temporarily differ; the navbar and Admin → System show both.
