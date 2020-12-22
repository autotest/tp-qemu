import os
import re

from provider.blockdev_base import BlockdevBaseTest


class BlockdevHotplugIOThreadTest(BlockdevBaseTest):
    """Hotplug image when iothread configured"""

    def __init__(self, test, params, env):
        super(BlockdevHotplugIOThreadTest, self).__init__(test, params, env)
        self._backing_tag = params.objects("source_images")[0]

    def _is_qemu_aborted(self):
        log_file = os.path.join(self.test.resultsdir,
                                self.params.get('debug_log_file', 'debug.log'))
        with open(log_file, 'r') as f:
            out = f.read().strip()
            return re.search(self._error_msg, out, re.M) is not None

    def hotplug_image(self):
        disk = self.target_disk_define_by_params(
            self.params, self.params['hotplug_image'])
        self.trash.append(disk)

        try:
            disk.hotplug(self.main_vm)
        except Exception as e:
            self.main_vm.destroy()
            if self._is_qemu_aborted():
                self.test.fail('qemu aborted(core dumped)')
            else:
                raise

    def prepare_test(self):
        self.prepare_main_vm()
        self.disks_info[self._backing_tag] = ["system", "/tmp"]
        self.generate_data_file(self._backing_tag)
        self._error_msg = self.params['error_msg'].format(
            pid=self.main_vm.get_pid())

    def do_test(self):
        self.hotplug_image()


def run(test, params, env):
    """
    Hotplug an image with iothread set

    test steps:
        1. boot VM with iothread set
        2. create a file
        3. Hotplug a 20G image(backing: image1)

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    t = BlockdevHotplugIOThreadTest(test, params, env)
    t.run_test()
