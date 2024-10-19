import random

from virttest import utils_numeric

from provider.blockdev_mirror_wait import BlockdevMirrorWaitTest


class BlockdevMirrorSimpleTest(BlockdevMirrorWaitTest):
    """
    Block mirror simple test:
      granularity, buf-size
    """

    def __init__(self, test, params, env):
        self._set_granularity(params)
        self._set_bufsize(params)
        self._set_auto_finalize(params)
        self._set_auto_dismiss(params)
        super(BlockdevMirrorSimpleTest, self).__init__(test, params, env)

    def _set_auto_finalize(self, params):
        auto_finalize = params.get("auto_finalize")
        if auto_finalize:
            params["auto-finalize"] = auto_finalize

    def _set_auto_dismiss(self, params):
        auto_dismiss = params.get("auto_dismiss")
        if auto_dismiss:
            params["auto-dismiss"] = auto_dismiss

    def _set_granularity(self, params):
        granularities = params.objects("granularity_list")
        granularity = (
            random.choice(granularities) if granularities else params.get("granularity")
        )

        if granularity:
            params["granularity"] = int(
                utils_numeric.normalize_data_size(granularity, "B")
            )

    def _set_bufsize(self, params):
        factors = params.objects("buf_size_factor_list")
        if factors:
            params["buf-size"] = int(random.choice(factors)) * params["granularity"]


def run(test, params, env):
    """
     Block mirror granularity test

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a target disk for mirror to VM via qmp commands
        5. do block-mirror with some options:
           granularity/buf-size
        6. check the mirror disk is attached
        7. restart VM with the mirror disk
        8. check the file and its md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorSimpleTest(test, params, env)
    mirror_test.run_test()
