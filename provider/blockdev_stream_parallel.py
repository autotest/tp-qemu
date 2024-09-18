"""
Module specified for block stream parallel test cases, i.e.
running block-stream and some other tests in paralell, and wait
till all block jobs done.
"""

from functools import partial

from avocado.utils import memory
from virttest import utils_misc

from provider import backup_utils, blockdev_stream_base


class BlockdevStreamParallelTest(blockdev_stream_base.BlockDevStreamTest):
    """
    block-stream parallel test module
    """

    def blockdev_stream(self):
        """
        Run block-stream and other operations in parallel

        parallel_tests includes function names separated by space
        e.g. parallel_tests = 'stress_test', we should define stress_test
        function with no argument
        """
        parallel_tests = self.params.objects("parallel_tests")
        targets = list([getattr(self, t) for t in parallel_tests if hasattr(self, t)])
        targets.append(
            partial(
                backup_utils.blockdev_stream,
                vm=self.main_vm,
                device=self._top_device,
                **self._stream_options,
            )
        )

        try:
            utils_misc.parallel(targets)
        finally:
            memory.drop_caches()
