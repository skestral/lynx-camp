# Camply

Camp Finder's Washington connector uses Camply's GoingToCamp request-header
pattern (Chrome User-Agent generation and Accept-Language) and the `rootMapId`,
JSON filter, and exact-stay workflow described in PR #398. It retains Camp
Finder's asynchronous HTTP client, pacing, diagnostics, cancellation, and
notification pipeline. The full Camply package is not a runtime dependency.

Reference: https://github.com/juftin/camply/pull/398

Reviewed commit: `09b69e4ed502cae2f259bee54e33f36cc7c07bbd`.

Camply is Copyright (c) 2021 Justin Flannery, licensed under the MIT License
included alongside this notice. Local adaptations add Roofed category searches,
complete map traversal, response validation, and persistent access stops. The
retired site-details endpoint is not used and placeholder capacities are not
treated as real accommodation data.
