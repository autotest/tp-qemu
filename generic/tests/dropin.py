import os

from avocado.utils import process

from virttest import data_dir


def run(test, params, env):
    """
    Run a dropin test.
    """
    dropin_path = params.get("dropin_path")
    dropin_path = os.path.join(data_dir.get_root_dir(), "dropin",
                               dropin_path)
    try:
        process.system(dropin_path, shell=True)
    except process.CmdError:
        test.fail("Drop in test %s failed" % dropin_path)
