import random
import time

from provider.blockdev_stream_parallel import BlockdevStreamParallelTest


class BlockdevStreamVMStopContTest(BlockdevStreamParallelTest):
    """do block-stream and vm stop/cont in parallel"""

    def stop_cont_vm(self):
        """Stop VM for a while, then resume it"""
        self.main_vm.pause()
        t = int(random.choice(self.params.objects("vm_stop_time_list")))
        time.sleep(t)
        self.main_vm.resume()

    def do_test(self):
        super(BlockdevStreamVMStopContTest, self).do_test()
        self.clone_vm.destroy()
        self.remove_files_from_system_image()


def run(test, params, env):
    """
    Basic block stream test during vm stop and cont

    test steps:
        1. boot VM
        2. add a snapshot image for the system disk
        3. create a file on system disk
        4. take snapshot for system disk
        5. create another file
        6. do block-stream(system->snapshot) and vm stop/continue in parallel
        7. restart VM with the snapshot disk, check both files and md5sum
        8. remove testing files from system image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamVMStopContTest(test, params, env)
    stream_test.run_test()
