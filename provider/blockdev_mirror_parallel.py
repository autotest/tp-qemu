"""
Module specified for parallel test cases, i.e.
running block-mirror and some other tests in paralell, and wait
till all mirror jobs done.
Please refer to blockdev_mirror_base for detailed test strategy.
"""

from functools import partial

from avocado.utils import memory
from virttest import utils_misc

from provider import backup_utils, blockdev_mirror_base


class BlockdevMirrorParallelTest(blockdev_mirror_base.BlockdevMirrorBaseTest):
    """
    block-mirror parallel test module
    """

    def blockdev_mirror(self):
        """Run block-mirror and other operations in parallel"""
        # parallel_tests includes function names separated by space
        # e.g. parallel_tests = 'stress_test', we should define stress_test
        # function with no argument
        parallel_tests = self.params.objects("parallel_tests")
        targets = list([getattr(self, t) for t in parallel_tests if hasattr(self, t)])

        # block-mirror on all source nodes is in parallel too
        for idx, source_node in enumerate(self._source_nodes):
            targets.append(
                partial(
                    backup_utils.blockdev_mirror,
                    vm=self.main_vm,
                    source=source_node,
                    target=self._target_nodes[idx],
                    **self._backup_options[idx],
                )
            )

        try:
            utils_misc.parallel(targets)
        finally:
            memory.drop_caches()
