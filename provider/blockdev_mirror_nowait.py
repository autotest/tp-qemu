"""
Module specified for test cases that don't need to wait job done,
please refer to blockdev_mirror_base for detailed test strategy.
"""

from functools import partial

from avocado.utils import memory
from virttest import utils_misc

from provider import backup_utils, blockdev_mirror_base, job_utils


class BlockdevMirrorNowaitTest(blockdev_mirror_base.BlockdevMirrorBaseTest):
    """
    block-mirror test module without waiting mirror job done
    """

    def __init__(self, test, params, env):
        super(BlockdevMirrorNowaitTest, self).__init__(test, params, env)
        self._jobs = []

    def blockdev_mirror(self):
        """Run block-mirror without waiting job completed"""
        for idx, source_node in enumerate(self._source_nodes):
            self._jobs.append(
                backup_utils.blockdev_mirror_nowait(
                    self.main_vm,
                    source_node,
                    self._target_nodes[idx],
                    **self._backup_options[idx],
                )
            )

    def wait_mirror_jobs_completed(self):
        """Wait till all mirror jobs completed in parallel"""
        targets = [
            partial(job_utils.wait_until_block_job_completed, vm=self.main_vm, job_id=j)
            for j in self._jobs
        ]
        try:
            utils_misc.parallel(targets)
        finally:
            memory.drop_caches()
