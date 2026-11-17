"""Local operator commands; the control socket is never published on TCP."""
import argparse
import json
import sys

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("health", "status", "inspect", "acknowledge"))
    args = parser.parse_args()
    with httpx.Client(transport=httpx.HTTPTransport(uds="/run/campfinder/inspect.sock"),
                      base_url="http://worker", timeout=15) as client:
        if args.command == "inspect":
            response = client.post("/inspect", json=json.load(sys.stdin))
        elif args.command == "acknowledge":
            response = client.post("/acknowledge")
        else:
            response = client.get("/" + args.command)
        print(json.dumps(response.json(), indent=2))
        return 0 if response.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
