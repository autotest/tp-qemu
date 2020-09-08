from virttest import utils_test

from provider.blockdev_mirror_parallel import BlockdevMirrorParallelTest


class BlockdevMirrorStressTest(BlockdevMirrorParallelTest):
    """Do block-mirror and vm stress test in parallel"""

    def stress_test(self):
        """Run stress testing on vm"""
        self.stress = utils_test.VMStress(self.main_vm, "stress", self.params)
        self.stress.load_stress_tool()

    def check_stress_running(self):
        """stress should be running after block-mirror"""
        if not self.stress.app_running():
            self.test.fail("stress stopped unexpectedly")

    def do_test(self):
        self.blockdev_mirror()
        self.check_stress_running()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()
        self.remove_files_from_system_image()


def run(test, params, env):
    """
    Basic block mirror test with stress -- only system disk

    test steps:
        1. boot VM
        2. create a file on system disk
        3. add a target disk for mirror to VM via qmp commands
        4. do block-mirror for system disk and vm stress test in parallel
        5. check the mirrored disk is attached
        6. check stress is still running
        7. restart VM with the mirrored disk, check the file and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorStressTest(test, params, env)
    mirror_test.run_test()
