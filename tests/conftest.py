"""Keep pytest's generated artifacts inside the project's ignored output tree."""

import pytest

from region_comparison.paths import OUTPUT, new_run_id, output_path


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    config.option.basetemp = str(
        output_path(config.option.basetemp)
        if config.option.basetemp
        else OUTPUT / "tmp" / ("pytest-" + new_run_id())
    )
    config.inicfg["cache_dir"] = str(OUTPUT / "cache" / "pytest" / new_run_id())
    if config.option.xmlpath:
        config.option.xmlpath = str(output_path(config.option.xmlpath))
