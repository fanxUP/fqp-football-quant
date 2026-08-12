from pathlib import Path
from unittest.mock import patch

from scripts.jobs.verify_backup import _test_restore


class _BoundedReadFile:
    def __init__(self, path: Path):
        self._file = path.open("rb")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._file.close()

    def read(self, size: int = -1) -> bytes:
        assert size > 0, "backup verification must never read the entire dump at once"
        return self._file.read(size)


def test_restore_verification_streams_large_plain_sql_dump(tmp_path):
    dump = tmp_path / "backup.sql"
    dump.write_bytes(b"-" * (1024 * 1024 - 8) + b"COPY public.official_matches (id) FROM stdin;\n")

    with patch("builtins.open", return_value=_BoundedReadFile(dump)):
        assert _test_restore(str(dump)) is True


def test_restore_verification_detects_copy_failure_across_chunks(tmp_path):
    dump = tmp_path / "backup.sql"
    dump.write_bytes(
        b"COPY public.official_matches (id) FROM stdin;\n"
        + b"-" * (1024 * 1024 - 5)
        + b"COPY failed: relation error"
    )

    assert _test_restore(str(dump)) is False
