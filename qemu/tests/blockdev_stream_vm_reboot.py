from provider.blockdev_stream_parallel import BlockdevStreamParallelTest


class BlockdevStreamVMRebootTest(BlockdevStreamParallelTest):
    """do block-stream and vm reboot in parallel"""

    def reboot_vm(self):
        reboot_method = self.params.get("reboot_method", "system_reset")
        self.main_vm.reboot(method=reboot_method)

    def do_test(self):
        super(BlockdevStreamVMRebootTest, self).do_test()
        self.clone_vm.destroy()
        self.remove_files_from_system_image()


def run(test, params, env):
    """
    Do block stream during vm reboot

    test steps:
        1. boot VM
        2. create a file on system disk
        3. add a snapshot disk, take snashot for system disk
        4. create another file
        5. do block-stream for system disk and vm reboot in parallel
        6. restart VM with the snapshot disk, check both files and md5sum
        7. remove testing files from system image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamVMRebootTest(test, params, env)
    stream_test.run_test()
