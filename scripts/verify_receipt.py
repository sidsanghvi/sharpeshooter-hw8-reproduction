#!/usr/bin/env python3
"""Verify one stored receipt without opening SQLite for writes."""
import argparse
import json
from pathlib import Path
import sqlite3

from sharpeshooter.receipts import verify_receipt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--receipt-id", required=True)
    args = parser.parse_args(argv)
    try:
        uri = "file:" + str(Path(args.db).resolve()) + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        row = connection.execute("SELECT payload_json,integrity_hash FROM receipts WHERE receipt_id=?", (args.receipt_id,)).fetchone()
        connection.close()
        if row is None:
            raise ValueError
        result = verify_receipt(json.loads(row[0]), row[1])
    except (sqlite3.Error, OSError, ValueError, TypeError, json.JSONDecodeError):
        print("HASH_MISMATCH")
        return 1
    print("VERIFIED" if result.valid else "HASH_MISMATCH")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
