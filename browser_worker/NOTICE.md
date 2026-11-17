# Third-party Runtime Files

`seccomp_profile.json` is adapted from Microsoft's Playwright
repository at tag `v1.65.1`:
https://github.com/microsoft/playwright/blob/v1.65.1/utils/docker/seccomp_profile.json

Playwright is Copyright Microsoft Corporation and licensed under Apache 2.0.
The upstream license is included as `LICENSE.playwright`. The Python package and
Docker image use version 1.65.2, the corresponding Python patch release.

The only local change allows the `chroot` syscall even with all container
capabilities dropped. Chromium uses it inside its own user namespace to complete
sandbox setup. The kernel still checks capabilities; the container user does not
receive `SYS_CHROOT` or `SYS_ADMIN` in the outer namespace.

The profile retains the upstream deny-by-default syscall policy while allowing the
user-namespace calls required by Chromium's sandbox. Do not replace it with an
unconfined profile or add `--no-sandbox` to make a failing host work.
