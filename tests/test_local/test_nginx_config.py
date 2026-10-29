from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import Mock

import pytest

from ops.server import configure_nginx
from ops.server.configure_nginx import NginxRecoveryError, configure


@pytest.fixture
def nginx_root(tmp_path: Path) -> Path:
    root = tmp_path / "nginx"
    for directory in ("conf.d", "sites-available", "sites-enabled", "snippets"):
        (root / directory).mkdir(parents=True)
    site = root / "sites-available/fqp"
    site.write_text(
        "server {\n"
        "    listen 443 ssl;\n"
        "    root /var/www/fqp; # keep this comment\n"
        "    add_header X-Frame-Options SAMEORIGIN always;\n"
        "    location /api/ { proxy_pass http://127.0.0.1:8080; }\n"
        "    location / { try_files $uri $uri/ /index.html; }\n"
        "}\n"
    )
    (root / "sites-enabled/fqp").symlink_to(site)
    return root


def files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_plan_is_read_only_and_does_not_invoke_nginx(nginx_root: Path):
    before = files(nginx_root)
    check, reload = Mock(), Mock()
    changed = configure(nginx_root, check=check, reload=reload)
    assert len(changed) == 3
    assert files(nginx_root) == before
    check.assert_not_called()
    reload.assert_not_called()


def test_apply_preserves_site_and_follows_enabled_symlink(nginx_root: Path):
    site = nginx_root / "sites-available/fqp"
    original = site.read_text()
    site.chmod(0o640)
    check, reload = Mock(), Mock()
    configure(nginx_root, apply=True, check=check, reload=reload)
    updated = site.read_text()
    include = f'\n    include "{nginx_root}/snippets/fqp-static.conf";\n'
    assert updated.replace(include, "") == original
    assert (nginx_root / "sites-enabled/fqp").is_symlink()
    assert stat.S_IMODE(site.stat().st_mode) == 0o640
    assert check.call_count == 2
    reload.assert_called_once_with()
    assert "log_format fqp_timing" in (nginx_root / "conf.d/00-fqp-performance.conf").read_text()
    assert "location ^~ /assets/" in (nginx_root / "snippets/fqp-static.conf").read_text()


def test_repeated_apply_is_idempotent_and_does_not_reload(nginx_root: Path):
    configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    before = files(nginx_root)
    check, reload = Mock(), Mock()
    assert configure(nginx_root, apply=True, check=check, reload=reload) == []
    assert files(nginx_root) == before
    check.assert_not_called()
    reload.assert_not_called()


def test_two_enabled_names_for_same_site_are_not_ambiguous(nginx_root: Path):
    (nginx_root / "sites-enabled/alias").symlink_to(nginx_root / "sites-available/fqp")
    assert len(configure(nginx_root)) == 3


def test_commented_include_is_not_mistaken_for_an_installed_include(nginx_root: Path):
    site = nginx_root / "sites-available/fqp"
    site.write_text(site.read_text() + f'\n# include "{nginx_root}/snippets/fqp-static.conf";\n')
    configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    assert f'\n    include "{nginx_root}/snippets/fqp-static.conf";\n' in site.read_text()


def test_existing_unquoted_include_is_not_added_a_second_time(nginx_root: Path):
    site = nginx_root / "sites-available/fqp"
    include = f"include {nginx_root}/snippets/fqp-static.conf;"
    site.write_text(site.read_text().replace("root /var/www/fqp;", "root /var/www/fqp; " + include))
    configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    assert site.read_text().count("fqp-static.conf") == 1


def test_include_in_another_server_does_not_skip_selected_server(nginx_root: Path):
    site = nginx_root / "sites-available/fqp"
    site.write_text(
        site.read_text()
        + f'\nserver {{ root /srv/other; include "{nginx_root}/snippets/fqp-static.conf"; }}\n'
    )
    configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    assert site.read_text().count("fqp-static.conf") == 2


def test_duplicate_active_includes_are_rejected_without_mutation(nginx_root: Path):
    site = nginx_root / "sites-available/fqp"
    include = f'include "{nginx_root}/snippets/fqp-static.conf";'
    site.write_text(
        site.read_text().replace("root /var/www/fqp;", "root /var/www/fqp;" + include * 2)
    )
    before = files(nginx_root)
    with pytest.raises(ValueError, match="Multiple active"):
        configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    assert files(nginx_root) == before


def test_ambiguous_sites_are_rejected_without_mutation(nginx_root: Path):
    (nginx_root / "conf.d/other.conf").write_text("server { root /var/www/fqp; }")
    before = files(nginx_root)
    with pytest.raises(ValueError, match="exactly one"):
        configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    assert files(nginx_root) == before


@pytest.mark.parametrize(
    "site_text",
    [
        "server { root /var/www/another-app; }",
        "server { location / { root /var/www/fqp; } }",
        "# server { root /var/www/fqp; }\nserver { root /srv/other; }",
        "server { root /var/www/fqp; } server { root /var/www/fqp; }",
    ],
)
def test_missing_or_nested_or_duplicate_server_root_is_rejected(nginx_root: Path, site_text: str):
    (nginx_root / "sites-available/fqp").write_text(site_text)
    before = files(nginx_root)
    with pytest.raises(ValueError, match="exactly one"):
        configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    assert files(nginx_root) == before


def test_enabled_file_outside_nginx_tree_is_rejected(nginx_root: Path, tmp_path: Path):
    outside = tmp_path / "outside.conf"
    outside.write_text("server { root /var/www/fqp; }")
    (nginx_root / "sites-enabled/unsafe").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    assert outside.read_text() == "server { root /var/www/fqp; }"


def test_managed_snippet_symlink_is_rejected(nginx_root: Path, tmp_path: Path):
    outside = tmp_path / "outside.conf"
    outside.write_text("keep")
    (nginx_root / "snippets/fqp-static.conf").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        configure(nginx_root, apply=True, check=Mock(), reload=Mock())
    assert outside.read_text() == "keep"


def test_invalid_original_configuration_does_not_write(nginx_root: Path):
    before = files(nginx_root)
    with pytest.raises(RuntimeError, match="original invalid"):
        configure(
            nginx_root,
            apply=True,
            check=Mock(side_effect=RuntimeError("original invalid")),
            reload=Mock(),
        )
    assert files(nginx_root) == before


@pytest.mark.parametrize("existing_snippets", [False, True])
def test_configuration_validation_failure_restores_exact_old_files(
    nginx_root: Path, existing_snippets: bool
):
    if existing_snippets:
        (nginx_root / "conf.d/00-fqp-performance.conf").write_text("# previous http rules\n")
        (nginx_root / "snippets/fqp-static.conf").write_text("# previous static rules\n")
    before = files(nginx_root)
    check = Mock(side_effect=[None, RuntimeError("new invalid"), None])
    reload = Mock()
    with pytest.raises(RuntimeError, match="new invalid"):
        configure(nginx_root, apply=True, check=check, reload=reload)
    assert files(nginx_root) == before
    assert check.call_count == 3
    reload.assert_not_called()


def test_failed_reload_restores_files_and_reloads_old_configuration(nginx_root: Path):
    before = files(nginx_root)
    reload = Mock(side_effect=[RuntimeError("reload failed"), None])
    check = Mock()
    with pytest.raises(RuntimeError, match="reload failed"):
        configure(nginx_root, apply=True, check=check, reload=reload)
    assert files(nginx_root) == before
    assert check.call_count == 3
    assert reload.call_count == 2


def test_failed_recovery_is_distinguished_from_a_restored_config(nginx_root: Path):
    check = Mock(side_effect=[None, RuntimeError("new invalid"), RuntimeError("restore invalid")])
    with pytest.raises(NginxRecoveryError, match="ROLLBACK_REQUIRED"):
        configure(nginx_root, apply=True, check=check, reload=Mock())


def test_cli_returns_distinct_exit_code_for_failed_recovery(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["configure_nginx.py", "--apply"])
    monkeypatch.setattr(
        configure_nginx,
        "configure",
        Mock(side_effect=NginxRecoveryError("ROLLBACK_REQUIRED: fixture")),
    )
    assert configure_nginx.main() == 3
    assert "ROLLBACK_REQUIRED" in capsys.readouterr().err


def test_deployment_checks_nginx_before_stop_and_installs_after_publish():
    deploy = Path("ops/server/deploy.sh").read_text()
    stop = deploy.index('sudo -n systemctl stop "${SERVICES[@]}"\ngit')
    preflight = deploy.index('"$SCRIPT_DIR/configure_nginx.py" --plan')
    publish = deploy.rindex("FRONTEND_PUBLISH_ATTEMPTED=true")
    install = deploy.index('"$SCRIPT_DIR/configure_nginx.py" --apply')
    assert preflight < stop < publish < install < deploy.rindex("trap - ERR")
    assert "NGINX_CONFIG_STATUS == 3" in deploy
    assert "rollback_required 'Nginx configuration recovery failed;" in deploy
