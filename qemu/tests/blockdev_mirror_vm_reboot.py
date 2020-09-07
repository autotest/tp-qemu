from provider.blockdev_mirror_parallel import BlockdevMirrorParallelTest


class BlockdevMirrorVMRebootTest(BlockdevMirrorParallelTest):
    """do block-mirror and vm stop/cont in parallel"""

    def reboot_vm(self):
        """Reboot VM with qmp command"""
        self.main_vm.reboot(method="system_reset")


def run(test, params, env):
    """
    Basic block mirror during vm reboot -- only system disk

    test steps:
        1. boot VM
        2. create a file on system disk
        3. add a target disk for mirror to VM via qmp commands
        4. do block-mirror for system disk and vm reboot in parallel
        5. check the mirrored disk is attached
        6. restart VM with the mirrored disk, check the file and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorVMRebootTest(test, params, env)
    mirror_test.run_test()
