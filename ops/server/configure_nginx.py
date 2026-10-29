"""Install FQP's shared static rules without replacing an existing Nginx site."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "nginx"
TOKENS = re.compile(r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\#[^\n]*|[{};]|[^\s{};\#]+""")


class NginxRecoveryError(RuntimeError):
    """The release must stop instead of restarting against unverified config."""


def server_directives(text: str) -> list[tuple[list[str], int, int]]:
    """Read direct server statements with offsets and their owning server block."""
    stack: list[tuple[str, int]] = []
    directive: list[str] = []
    statements = []
    for token in TOKENS.finditer(text):
        value = token.group()
        if value.startswith("#"):
            continue
        if value == "{":
            stack.append((directive[0] if directive else "", token.start()))
            directive = []
        elif value == "}":
            if stack:
                stack.pop()
            directive = []
        elif value == ";":
            if stack and stack[-1][0] == "server":
                statements.append((directive, token.end(), stack[-1][1]))
            directive = []
        else:
            directive.append(value)
    return statements


def plan_config(nginx_root: Path) -> dict[Path, bytes]:
    root = nginx_root.resolve(strict=True)
    sites: dict[Path, tuple[str, int, int]] = {}
    candidates = [*(root / "sites-enabled").glob("*"), *(root / "conf.d").glob("*.conf")]
    for candidate in candidates:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError(f"Enabled Nginx configuration is outside {root}: {candidate}")
        if not resolved.is_file():
            continue
        text = resolved.read_text(encoding="utf-8")
        for directive, offset, owner in server_directives(text):
            if (
                len(directive) == 2
                and directive[0] == "root"
                and directive[1].strip("\"'").rstrip("/") == "/var/www/fqp"
            ):
                if resolved in sites and sites[resolved][1] != offset:
                    raise ValueError(
                        "Expected exactly one FQP server root, found multiple in one file"
                    )
                sites[resolved] = (text, offset, owner)
    if len(sites) != 1:
        raise ValueError(
            f"Expected exactly one enabled FQP site with server root /var/www/fqp, found {len(sites)}"
        )

    site, (text, offset, owner) = next(iter(sites.items()))
    snippet = root / "snippets/fqp-static.conf"
    include = f'include "{snippet}";'
    installed = [
        directive
        for directive, _, statement_owner in server_directives(text)
        if statement_owner == owner
        and len(directive) == 2
        and directive[0] == "include"
        and directive[1].strip("\"'") == str(snippet)
    ]
    if len(installed) > 1:
        raise ValueError("Multiple active FQP static includes in the same server")
    if not installed:
        text = text[:offset] + f"\n    {include}\n" + text[offset:]
    expected = {
        root / "conf.d/00-fqp-performance.conf": (SOURCE / "http.conf").read_bytes(),
        snippet: (SOURCE / "static.conf").read_bytes(),
        site: text.encode("utf-8"),
    }
    for path in expected:
        current = root
        for part in path.relative_to(root).parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"Managed Nginx path is a symlink: {current}")
        if path.exists() and not path.is_file():
            raise ValueError(f"Managed Nginx path is not a regular file: {path}")
    return expected


def write_config(path: Path, content: bytes, metadata: os.stat_result | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".fqp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode) if metadata else 0o644)
            if metadata and os.geteuid() == 0:
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def check_nginx() -> None:
    subprocess.run(["nginx", "-t"], check=True)


def reload_nginx() -> None:
    subprocess.run(["systemctl", "reload", "nginx"], check=True)


def configure(
    nginx_root: Path,
    *,
    apply: bool = False,
    check: Callable[[], None] = check_nginx,
    reload: Callable[[], None] = reload_nginx,
) -> list[Path]:
    expected = plan_config(nginx_root)
    changed = [p for p, content in expected.items() if not p.exists() or p.read_bytes() != content]
    if not apply or not changed:
        return changed
    check()
    original = {p: (p.read_bytes(), p.stat()) if p.exists() else (None, None) for p in changed}
    reload_attempted = False
    try:
        for path in changed:
            write_config(path, expected[path], original[path][1])
        check()
        reload_attempted = True
        reload()
    except BaseException:
        try:
            for path, (content, metadata) in reversed(original.items()):
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    write_config(path, content, metadata)
            check()
            if reload_attempted:
                reload()
        except BaseException as recovery_error:
            raise NginxRecoveryError(
                "ROLLBACK_REQUIRED: Nginx configuration recovery failed"
            ) from recovery_error
        raise
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Read-only preview (default)")
    mode.add_argument("--apply", action="store_true", help="Install, validate and reload")
    args = parser.parse_args()
    try:
        changed = configure(Path("/etc/nginx"), apply=args.apply)
    except NginxRecoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(f"Nginx {'configured' if args.apply else 'plan'}: {len(changed)} file(s)")
    for path in changed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
