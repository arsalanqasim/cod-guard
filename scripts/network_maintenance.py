"""Private host tool for a network steward; no phone appears in CLI arguments."""

import argparse
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import reputation_network
import service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--remove-subject", metavar="CASE_REFERENCE")
    action.add_argument("--purge-expired", action="store_true")
    args = parser.parse_args()
    try:
        if args.purge_expired:
            removed = reputation_network.purge_expired(service.STATE_PATH)
            print(f"Purged {removed} expired consents and their linked contributions.")
        else:
            if not sys.stdin.isatty():
                parser.exit(2, "Use a private interactive terminal for subject removal.\n")
            phone = getpass("Verified buyer mobile number (hidden): ")
            removed = reputation_network.suppress_subject(service.STATE_PATH, phone, args.remove_subject)
            print(f"Network-wide suppression recorded. Removed {removed} consent records.")
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
