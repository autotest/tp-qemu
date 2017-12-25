import time
import random

from virttest import utils_test
from virttest import utils_misc

from qemu.tests import blk_commit


def run(test, params, env):
    """
    drive_mirror_stress test:
    1). guest installation
    2). start snapshot and commit during guest installation
    3). after installation finished, reboot guest verfiy guest reboot correctly.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    args = (test, params, env)
    bg = utils_misc.InterruptedThread(utils_test.run_virt_sub_test, args,
                                      {"sub_type": "unattended_install"})
    bg.start()
    utils_misc.wait_for(bg.is_alive, timeout=10)
    time.sleep(random.uniform(60, 200))
    tag = params["source_image"]
    commit_test = blk_commit.BlockCommit(test, params, env, tag)
    commit_test.trash_files.append(commit_test.image_file)
    try:
        commit_test.create_snapshots(create_file=False)
        commit_test.start()
        commit_test.wait_for_finished()
        bg.join()
    finally:
        commit_test.clean()
