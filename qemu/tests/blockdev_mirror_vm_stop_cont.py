import random
import time

from provider.blockdev_mirror_parallel import BlockdevMirrorParallelTest


class BlockdevMirrorVMStopContTest(BlockdevMirrorParallelTest):
    """do block-mirror and vm stop/cont in parallel"""

    def stop_cont_vm(self):
        """Stop VM for a while, then resume it"""
        self.main_vm.pause()
        t = int(random.choice(self.params.objects("vm_stop_time_list")))
        time.sleep(t)
        self.main_vm.resume()


def run(test, params, env):
    """
    Basic block mirror during vm stop_cont -- only system disk

    test steps:
        1. boot VM
        2. create a file on system disk
        3. add a target disk for mirror to VM via qmp commands
        4. do block-mirror for system disk and vm stop/continue in parallel
        5. check the mirrored disk is attached
        6. restart VM with the mirrored disk, check the file and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorVMStopContTest(test, params, env)
    mirror_test.run_test()
