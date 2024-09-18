import logging

from virttest import error_context

from provider.blockdev_snapshot_base import BlockDevSnapshotTest

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevSnapshotStopContTest(BlockDevSnapshotTest):
    @error_context.context_aware
    def create_snapshot(self):
        error_context.context(
            "do snaoshot during running guest stop_cont", LOG_JOB.info
        )
        self.main_vm.pause()
        super(BlockdevSnapshotStopContTest, self).create_snapshot()
        self.main_vm.resume()


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with system disk
    2) create target disk with qmp command
    3) load stress in guest
    4) do snapshot to target disk
    5) shutdown VM
    6) boot VM with target disk
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    base_image = params.get("images", "image1").split()[0]
    params.setdefault("image_name_%s" % base_image, params["image_name"])
    params.setdefault("image_format_%s" % base_image, params["image_format"])
    snapshot_stop_cont = BlockdevSnapshotStopContTest(test, params, env)
    snapshot_stop_cont.run_test()
