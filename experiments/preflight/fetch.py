"""Fetch the official archive and copy only zh-CN and license members."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

URL = "https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.1.tar.gz"
SHA256 = "4cba5faa11c71437928e17cb1b9b3d8b8e727e7ea363a3a9a8045e19c0491577"


def fetch(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "source.tar.gz"
    if not archive.exists():
        temporary = output / "source.tar.gz.part"
        subprocess.run(["curl", "--fail", "--location", "--max-time", "180", "--silent", "--show-error", "--output", str(temporary), URL], check=True)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
            raise ValueError("SOURCE_HASH_MISMATCH")
        temporary.rename(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("SOURCE_HASH_MISMATCH")
    allowed = {"1.1/data/zh-CN.jsonl": "zh-CN.jsonl", "1.1/LICENSE": "LICENSE", "1.1/NOTICE.md": "NOTICE.md"}
    with tarfile.open(archive) as tar:
        for name, destination in allowed.items():
            member = tar.getmember(name)
            if not member.isfile() or member.size > 20 * 1024 * 1024:
                raise ValueError("INVALID_ARCHIVE_MEMBER")
            payload = tar.extractfile(member).read()
            target = output / destination
            if target.exists() and target.read_bytes() != payload:
                raise ValueError("EXISTING_SOURCE_CHANGED")
            target.write_bytes(payload)
    return {"source_url": URL, "archive_sha256": SHA256, "data_sha256": hashlib.sha256((output / "zh-CN.jsonl").read_bytes()).hexdigest(), "license_sha256": hashlib.sha256((output / "LICENSE").read_bytes()).hexdigest(), "notice_sha256": hashlib.sha256((output / "NOTICE.md").read_bytes()).hexdigest(), "license": "CC-BY-4.0", "source_release": "MASSIVE-1.1", "locale": "zh-CN"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(fetch(args.output), ensure_ascii=False, indent=2))
