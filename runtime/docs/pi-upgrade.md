# Pi Upgrade Procedure

Pi is a complete vendored source tree. Upgrades are explicit product changes from a verified official
source archive, not Git submodule updates or automatic dependency refreshes.

1. Read the target Pi changelogs and `pi/AGENTS.md`.
2. Download the latest official `pi-X.Y.Z-source.tar.gz` release asset and verify its published SHA-256.
3. Replace `pi/` with the archive contents without copying nested Git metadata.
4. Update `pi-source.lock.json` with release, commit, archive, file-count, and manifest evidence.
5. Install Pi dependencies with lifecycle scripts disabled and run its required checks.
6. Build Pi, then run `npm run verify:pi-source` and root checks.
7. Revalidate the narrow imports used by `packages/agent-runtime`; do not replace them with external
   SDK packages to hide a source incompatibility.
8. Run faux Runtime tests, Docker policy tests, Web E2E, Windows packaging, and the native release
   matrix.
9. Record changed Pi behavior and the new release evidence in SpecKit before deployment.

Direct Pi-source patches are never permitted. If an official stable release does not provide a
required capability, implement it in WorkDude Runtime or adapters outside `pi/`, or pause the Pi
upgrade until an official stable release contains the capability. The only authorized `pi/` change
is the atomic whole-directory replacement described above.
