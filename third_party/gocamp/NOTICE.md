# GoCamp Attribution

The discovery, accommodation selection, and dated reservation-link workflow in
`backend/app/goingtocamp.py` and `backend/app/provider_ids.py` is adapted from
[peckjon/gocamp](https://github.com/peckjon/gocamp), reviewed at commit
`21d1000bef6df9f1d53a12881599ad60a87661fd`. The upstream MIT license is included here.

Camp Finder does not install or execute the original console application. The
adapter uses asynchronous HTTP requests, a newer availability-map contract,
provider-qualified identities, full-stay checks, and persisted access stops.
See [the integration guide](../../docs/washington-state-parks.md) for additional
contract references, compatibility limits, and live verification requirements.
