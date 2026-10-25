from ocgm.tray import ICONS, severity_for


def test_severity_uses_configured_thresholds() -> None:
    thresholds = (60, 80, 95)
    assert severity_for(10, thresholds) == "ok"
    assert severity_for(65, thresholds) == "warn"
    assert severity_for(85, thresholds) == "danger"


def test_severity_defaults_with_one_threshold() -> None:
    assert severity_for(65, (70,)) == "ok"
    assert severity_for(75, (70,)) == "danger"
    assert severity_for(99, (70,)) == "danger"


def test_icon_names_are_symbolic_variants() -> None:
    assert ICONS["ok"].endswith("-symbolic") or ICONS["ok"] == "emblem-ok-symbolic"
