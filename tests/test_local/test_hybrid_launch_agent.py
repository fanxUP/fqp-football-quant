import plistlib

from scripts.local.hybrid_launch_agent import (
    LAUNCHD_PATH,
    build_launch_agent_plist,
    write_launch_agent_plist,
)


def test_hybrid_launch_agent_keeps_one_complete_runtime_alive(tmp_path):
    project_root = tmp_path / "fqp"
    target = tmp_path / "LaunchAgents" / "com.fqp.hybrid.plist"

    plist = build_launch_agent_plist(project_root)
    write_launch_agent_plist(target, project_root)

    assert plist["Label"] == "com.fqp.hybrid"
    assert plist["ProgramArguments"] == [
        "/bin/bash",
        str(project_root / "ops/local/run_hybrid_dev.sh"),
    ]
    assert "WorkingDirectory" not in plist
    assert plist["EnvironmentVariables"]["PATH"] == LAUNCHD_PATH
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    assert plist["ThrottleInterval"] >= 30
    with target.open("rb") as source:
        assert plistlib.load(source) == plist
