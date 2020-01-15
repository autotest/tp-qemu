from virttest import error_context

from provider.blockdev_snapshot_base import BlockDevSnapshotTest


@error_context.context_aware
def run(test, params, env):
    """
    Block device snapshot test
    1) Start VM with a data disk
    2) Create snapshot for the data disk
    3) Save a temp file and record md5sum
    4) Rebase snapshot file if VM start with blockdev mode
    5) Boot VM with Snapshot image as data disk
    6) Check temp file md5sum

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.

    """
    snapshot_test = BlockDevSnapshotTest(test, params, env)
    snapshot_test.run_test()
