# Publishing

Publishing is handled through GitHub Actions and npm Trusted Publishing so
GitHub and npm releases stay in sync without a long-lived npm token.

Configure the `codex-thread-tools` package on npm with this trusted publisher:

| Field | Value |
| --- | --- |
| Publisher | GitHub Actions |
| Organization/user | `zenzig` |
| Repository | `codex-thread-tools` |
| Workflow filename | `publish-npm.yml` |

Then publish a GitHub release whose tag matches the package version, for example
`v1.0.0`. The `Publish npm package` workflow will:

- verify `VERSION` and `package.json` match
- verify the GitHub release tag matches the package version
- run `python3 -m pytest`
- check that the npm version has not already been published
- update npm to the latest CLI
- run `npm pack --dry-run`
- publish to npm with Trusted Publishing and provenance

The workflow can also be run manually from the GitHub Actions tab. Ordinary
pushes to `main` do not publish npm.

## Release Checklist

1. Update `VERSION`, `package.json`, README badge/current version, and
   `CHANGELOG.md`.
2. Run `python3 -m pytest`.
3. Run `npm pack --dry-run --json`.
4. Commit and push `main`.
5. Create a normal GitHub release, not a prerelease, with a `vX.Y.Z` tag.
6. Confirm npm reports the new version under the `latest` dist-tag.
