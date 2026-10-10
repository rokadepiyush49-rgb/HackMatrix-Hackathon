"""Object storage for evidence packs.

Evidence must be immutable once issued, so production writes go to S3 with Object Lock in
COMPLIANCE mode: until the retention date passes nobody — not an admin, not the root account —
can overwrite or delete the object. The hash manifest in Postgres then lets anyone prove a pack
is the one that was issued. Local development uses a directory with the same interface.

Keys look like ``PACK-20260921221500/pack.pdf``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"key escapes the storage root: {key}")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage:
    def __init__(self, bucket: str, prefix: str, kms_key_id: str, retention_days: int, lock_mode: str,
                 region: str) -> None:
        import boto3  # imported lazily: local development never needs AWS libraries

        self.client = boto3.client("s3", region_name=region)
        self.bucket, self.prefix = bucket, prefix
        self.kms_key_id, self.retention_days, self.lock_mode = kms_key_id, retention_days, lock_mode

    def put(self, key: str, data: bytes, content_type: str) -> None:
        extra: dict = {"ServerSideEncryption": "aws:kms"}
        if self.kms_key_id:
            extra["SSEKMSKeyId"] = self.kms_key_id
        if self.retention_days > 0:
            extra["ObjectLockMode"] = self.lock_mode
            extra["ObjectLockRetainUntilDate"] = datetime.now(UTC) + timedelta(days=self.retention_days)
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data, ContentType=content_type,
                               ChecksumAlgorithm="SHA256", **extra)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self.prefix + key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        if not s.s3_bucket:
            raise RuntimeError("SUTRA_STORAGE_BACKEND=s3 needs SUTRA_S3_BUCKET")
        return S3Storage(s.s3_bucket, s.s3_prefix, s.s3_kms_key_id, s.evidence_retention_days,
                         s.evidence_lock_mode, s.aws_region)
    return LocalStorage(s.storage_path)
