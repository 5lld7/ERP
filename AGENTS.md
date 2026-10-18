# ERP collaboration and publishing

The user wants completed ERP changes made in Codex to reach GitHub and then
deploy through Vercel's Git integration. Follow this workflow for future ERP
implementation requests unless the user explicitly asks for review only,
uncommitted changes, a different branch, or no publication.

- Use the existing checkout. Preserve the user's files, commits and local data.
- Implement the requested change and run relevant checks before publishing.
  Application changes normally require the existing unittest suite; UI changes
  should also use the browser smoke test when its dependencies are available.
  Documentation-only edits do not need a repeat of the application test suite.
- After a completed, validated implementation, create a descriptive commit and
  push it to `origin/main` without requesting a second routine confirmation.
  Check the actual remote state first. Never force-push, discard unrelated
  changes, or overwrite another contributor's work to publish.
- If the remote has advanced, fetch and integrate compatible changes safely.
  Keep the user's work intact and report any conflict that cannot be resolved
  without a substantive user decision.
- Keep `.local`, `.venv`, `.vercel`, real `.env` files, databases, employee
  attachments and authentication tokens out of Git. Commit only the intended
  source, configuration, documentation and tests.
- GitHub CI runs on pushes and pull requests. Vercel must be connected once to
  `5lld7/ERP`, with `main` as its production branch, in the user's own account.
  That external integration, the Turso database and Vercel environment variables
  are prerequisites; a Git push does not create or authenticate them.
- Report the Git push result separately from the deployment result. Claim a
  live deployment only after checking a real Vercel deployment or application
  response. If access is blocked, report that limitation and the exact action
  needed rather than guessing a deployment URL.
- This workflow runs while handling the user's requests. Do not install a
  filesystem watcher that publishes every save or claim to monitor files
  continuously between tasks.

See `docs/VERCEL.md` for the one-time hosting setup and environment variables.
