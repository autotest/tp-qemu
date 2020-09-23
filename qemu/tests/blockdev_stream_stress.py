from virttest import utils_test

from provider.blockdev_stream_base import BlockDevStreamTest


class BlockdevStreamStressTest(BlockDevStreamTest):
    """Do block-stream with vm stress test"""

    def _run_stress_test(self):
        """Run stress test before block-stream"""
        self.stress = utils_test.VMStress(self.main_vm, "stress", self.params)
        self.stress.load_stress_tool()

    def check_stress_running(self):
        """stress should be running after block-stream"""
        if not self.stress.app_running():
            self.test.fail("stress stopped unexpectedly")

    def pre_test(self):
        super(BlockdevStreamStressTest, self).pre_test()
        self._run_stress_test()

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        self.check_stress_running()
        self.check_backing_file()
        self.clone_vm.create()
        self.verify_data_file()
        self.clone_vm.destroy()
        self.remove_files_from_system_image()


def run(test, params, env):
    """
    Basic block stream test with stress

    test steps:
        1. boot VM
        2. add a snapshot image for system image
        3. run stress test on VM
        4. create a file on system image
        5. take snapshot for system image
        6. create another file on system image(the active snapshot image)
        7. do block-stream for system image and wait job done
        8. check stress is still running
        9. restart VM with the snapshot image, check both files and md5sum
       10. remove testing files from system image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamStressTest(test, params, env)
    stream_test.run_test()
