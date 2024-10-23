"""Repeatedly blockdev_add/del iothread enabled node"""

import os

from avocado.utils import process
from virttest import data_dir, error_context


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Repeatedly blockdev_add/del iothread enabled node

    1) Run script test on host. The script mainly execute repeatedly
    blockdev_add/del iothread enabled node.

    """
    logger = test.log
    deps_dir = data_dir.get_deps_dir()
    host_file = os.path.join(deps_dir, params["host_script"])
    logger.info("Start script testing %s", host_file)
    process.system_output(host_file, shell=True)
    logger.info("Finished script.")
