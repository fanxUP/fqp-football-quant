"""P105's dedicated CI report must prove that every core module ran."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from scripts.ci.verify_prediction_input_results import main, verify_report

MODULES = (
    "tests.test_storage.test_prediction_input_policy",
    "tests.test_computation.test_prediction_input_updates_postgres",
    "tests.test_computation.test_prediction_input_revisions_postgres",
    "tests.test_computation.test_prediction_input_fence_postgres",
    "tests.test_computation.test_prediction_input_runtime_postgres",
    "tests.test_local.test_native_database_runtime",
)


def report(path: Path):
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root, "testsuite", tests=str(len(MODULES)), errors="0", failures="0", skipped="0"
    )
    for module in MODULES:
        ET.SubElement(suite, "testcase", classname=module, name="test_example")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return root, suite


def save(path, root):
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_complete_report_counts_actual_cases(tmp_path):
    path = tmp_path / "p105.xml"
    root, suite = report(path)
    ET.SubElement(suite, "testcase", classname=MODULES[0], name="test_second[param]")
    suite.set("tests", str(len(MODULES) + 1))
    save(path, root)
    assert verify_report(path) == {
        module: 2 if index == 0 else 1 for index, module in enumerate(MODULES)
    }


@pytest.mark.parametrize("status", ["skipped", "failure", "error"])
def test_nonpassing_case_rejected_even_with_zero_summary(tmp_path, status):
    path = tmp_path / "p105.xml"
    root, suite = report(path)
    ET.SubElement(suite[0], status)
    save(path, root)
    with pytest.raises(ValueError):
        verify_report(path)


@pytest.mark.parametrize("attribute", ["errors", "failures", "skipped"])
def test_nonzero_summary_rejected_even_if_case_missing_status(tmp_path, attribute):
    path = tmp_path / "p105.xml"
    root, suite = report(path)
    suite.set(attribute, "1")
    save(path, root)
    with pytest.raises(ValueError):
        verify_report(path)


@pytest.mark.parametrize("count", ["0", "4", "5", "-1", "bad"])
def test_invalid_or_inconsistent_test_count_rejected(tmp_path, count):
    path = tmp_path / "p105.xml"
    root, suite = report(path)
    suite.set("tests", count)
    save(path, root)
    with pytest.raises(ValueError):
        verify_report(path)


def test_missing_module_rejected_even_with_all_remaining_passed(tmp_path):
    path = tmp_path / "p105.xml"
    root, suite = report(path)
    suite.remove(suite[-1])
    suite.set("tests", str(len(MODULES) - 1))
    save(path, root)
    with pytest.raises(ValueError, match="missing"):
        verify_report(path)


@pytest.mark.parametrize("attribute,value", [("classname", "unrelated"), ("name", "")])
def test_unknown_or_empty_case_identity_rejected(tmp_path, attribute, value):
    path = tmp_path / "p105.xml"
    root, suite = report(path)
    suite[0].set(attribute, value)
    save(path, root)
    with pytest.raises(ValueError):
        verify_report(path)


def test_duplicate_case_rejected(tmp_path):
    path = tmp_path / "p105.xml"
    root, suite = report(path)
    ET.SubElement(suite, "testcase", **suite[0].attrib)
    suite.set("tests", str(len(MODULES) + 1))
    save(path, root)
    with pytest.raises(ValueError, match="duplicate"):
        verify_report(path)


@pytest.mark.parametrize("content", ["", "<testsuites>", "<testsuites/>", "<unrelated/>"])
def test_empty_malformed_or_wrong_shape_report_rejected(tmp_path, content):
    path = tmp_path / "p105.xml"
    path.write_text(content)
    with pytest.raises(ValueError):
        verify_report(path)


def test_missing_report_rejected(tmp_path):
    with pytest.raises(ValueError):
        verify_report(tmp_path / "absent.xml")


def test_cli_exit_and_output(tmp_path, capsys):
    path = tmp_path / "p105.xml"
    report(path)
    assert main([str(path)]) == 0
    assert f"{len(MODULES)} passed" in capsys.readouterr().out
    path.write_text("<testsuites/>")
    assert main([str(path)]) == 1
    assert "P105 CI rejected" in capsys.readouterr().err
