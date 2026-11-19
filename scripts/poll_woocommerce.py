"""Run one bounded polling pass per configured WooCommerce store."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import service
from woocommerce import WooCommerceError, configured_stores, poll_once


def main():
    try:
        stores = configured_stores()
    except WooCommerceError as exc:
        print(exc, file=sys.stderr)
        return 1
    failed = False
    for account, store in stores.items():
        try:
            result = poll_once(service.STATE_PATH, store)
            print(f"{account}: added {result['imported']} order(s)")
        except WooCommerceError as exc:
            print(f"{account}: {exc}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
