import plistlib

from scripts.local.scheduler_launch_agent import build_launch_agent_plist, write_launch_agent_plist


def test_launch_agent_keeps_the_local_scheduler_alive(tmp_path):
    project_root = tmp_path / "fqp"
    target = tmp_path / "LaunchAgents" / "com.fqp.scheduler.plist"

    plist = build_launch_agent_plist(project_root)
    write_launch_agent_plist(target, project_root)

    assert plist["Label"] == "com.fqp.scheduler"
    assert plist["ProgramArguments"] == [str(project_root / "ops/local/run_local_scheduler.sh")]
    assert plist["WorkingDirectory"] == str(project_root)
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    with target.open("rb") as source:
        assert plistlib.load(source) == plist
