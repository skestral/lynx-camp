# Retired Browser Worker

The optional Washington browser-console prototype was removed after the native
Camping and Roofed connector passed local Docker checks. New installations need
only the regular Camp Finder container. See the [Washington setup guide](washington-state-parks.md).

The prototype never fed the scanner, watches, or notification service. It was a
separate Playwright/Chromium, noVNC, and X11 image, not a dependency of the main
application image. Removing it therefore simplifies the repository without
changing availability monitoring or reducing the size of the main runtime image.

Removed components include `browser_worker/`, `compose.browser.yaml`, the Windows
launcher, the standalone verification script, and the console screenshot. The
ordinary browser-based UI development workflow remains available. Cart Assist
still records manual-checkout tasks; no automated hold service has been removed.

## Existing Installations

Pulling the update does not remove an old container, image, browser profile, or
saved console password. There is no automatic data cleanup.

List possible old workers without printing their environment or credentials:

```bash
docker ps -a --filter label=com.docker.compose.service=browser --format '{{.Names}} {{.Status}}'
```

Check that a listed container is the Camp Finder worker before acting. The
Windows launcher used the name `campfinder-browser-local-browser-1`; a server
installation may have a different name. For that confirmed local container:

```bash
docker inspect campfinder-browser-local-browser-1 --format '{{json .Mounts}}'
docker stop campfinder-browser-local-browser-1
docker rm campfinder-browser-local-browser-1
```

These commands leave its named profile volume intact. Browser profiles may
contain session data; retain or dispose of them separately after reviewing the
mount names. Do not remove Camp Finder's `/data` volume or use a broad Docker
prune to remove the worker. The Windows console credential, when created, remains
at `%LOCALAPPDATA%\CampFinder\browser-worker\console-password.xml`.

## Historical Source

The complete prototype is retained in Git at revision `f1d5654`. To inspect it
without restoring files into the current checkout:

```bash
git archive --format=zip --output=../campfinder-browser-retired.zip f1d5654 -- browser_worker compose.browser.yaml scripts/Start-BrowserWorker.ps1 scripts/check_browser_worker.py docs/browser-worker.md
```

This archive contains source code only, not a browser profile or console secret.
It is historical research, not a supported alternative scanning service.
