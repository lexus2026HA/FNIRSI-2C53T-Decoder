import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SAMPLES = ROOT / "samples"

# Ground truth read by eye from the scope's own screenshots (samples/*.bmp):
# timebase s/div, CH1 V/div, CH2 V/div, enabled channels, measured channel,
# on-screen Freq and Vp-p of that channel.
TRUTH = {
    "1": dict(tb=2e-3, v1=20.0, v2=0.1, on=("CH1",), ch="CH1", freq=59.0, vpp=72.67),
    "2": dict(tb=20e-3, v1=20.0, v2=0.1, on=("CH1",), ch="CH1", freq=59.0, vpp=69.60),
    "3": dict(tb=200e-6, v1=0.5, v2=0.1, on=("CH1",), ch="CH1", freq=998.0, vpp=3.04),
    "4": dict(tb=200e-6, v1=1.0, v2=0.1, on=("CH1",), ch="CH1", freq=1000.0, vpp=3.10),
    "5": dict(tb=200e-6, v1=0.2, v2=0.5, on=("CH1", "CH2"), ch="CH2", freq=1000.0, vpp=3.00),
    "6": dict(tb=200e-6, v1=0.2, v2=0.5, on=("CH1", "CH2"), ch="CH2", freq=1000.0, vpp=2.99),
    "8": dict(tb=200e-6, v1=0.2, v2=0.5, on=("CH2",), ch="CH2", freq=1000.0, vpp=2.98),
    "9": dict(tb=200e-6, v1=0.2, v2=0.1, on=("CH2",), ch="CH2", freq=998.0, vpp=0.800),
    "10": dict(tb=1e-3, v1=0.2, v2=0.5, on=("CH2",), ch="CH2", freq=1000.0, vpp=2.99),
}


@pytest.fixture(params=sorted(TRUTH, key=int))
def sample(request):
    return request.param, SAMPLES / f"{request.param}.bin", TRUTH[request.param]


# The 2C53T sample captures come from RafaelDiasCampos/FNIRSI-2C53T-Decoder and are not
# redistributed here (no license).  Without them the tests that need them are skipped.
HAVE_2C53T = all((SAMPLES / f"{n}.bin").exists() and (SAMPLES / f"{n}.bmp").exists() for n in TRUTH)
NEEDS_2C53T_MODULES = {"test_decoder", "test_bmp", "test_measurements", "test_export"}
NEEDS_2C53T_TESTS = {"test_model_selection", "test_profile_mismatch_rejected"}


def pytest_collection_modifyitems(config, items):
    if HAVE_2C53T:
        return
    skip = pytest.mark.skip(reason="нет образцов 2C53T в samples/ (см. README, раздел «Тесты»)")
    for item in items:
        if item.module.__name__ in NEEDS_2C53T_MODULES or item.originalname in NEEDS_2C53T_TESTS:
            item.add_marker(skip)
