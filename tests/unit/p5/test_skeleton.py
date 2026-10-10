import importlib

import pytest

PACKAGES = [
    "greenhome", "greenhome.core", "greenhome.ml", "greenhome.llm", "greenhome.memory",
    "api", "api.routes", "data_pipeline", "data_pipeline.download", "training", "evaluation",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    importlib.import_module(name)
