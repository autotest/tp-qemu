import time

from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorHotunplugTest(BlockdevMirrorNowaitTest):
    """
    Block mirror with hotunplug test
    """

    def hotunplug_frontend_devices(self):
        """
        device_del the frontend devices during mirroring,
        the devices CAN be removed without any issue
        """

        def _device_del(device):
            self.main_vm.monitor.cmd("device_del", {"id": device})

        list(map(_device_del, self._source_images))

    def wait_till_frontend_devices_deleted(self):
        """Wait till devices removed from output of query-block"""

        def _is_device_deleted(device):
            for item in self.main_vm.monitor.query("block"):
                """
                'qdev' item can be absent from block info
                while the device hotunplug is in progress.
                To handle this issue, the value of 'qdev' is set to device
                when 'qdev' is absent.
                """
                if device in item.get("qdev", device):
                    return False
            return True

        def _wait_till_device_deleted(device):
            tmo = self.params.get_numeric("device_del_timeout", 60)
            for i in range(tmo):
                if _is_device_deleted(device):
                    break
                time.sleep(1)
            else:
                self.test.fail("Failed to hotunplug the frontend device")

        list(map(_wait_till_device_deleted, self._source_images))

    def hotunplug_format_nodes(self):
        """
        blockdev-del the format nodes during mirroring,
        the nodes CANNOT be removed for they are busy
        """

        def _blockdev_del(node):
            try:
                self.main_vm.monitor.cmd("blockdev-del", {"node-name": node})
            except QMPCmdError as e:
                err = self.params["block_node_busy_error"] % node
                if err not in str(e):
                    self.test.fail("Unexpected error: %s" % str(e))
            else:
                self.test.fail("blockdev-del succeeded unexpectedly")

        list(map(_blockdev_del, self._source_nodes))

    def do_test(self):
        self.blockdev_mirror()
        self.check_block_jobs_started(self._jobs)
        self.hotunplug_frontend_devices()
        self.wait_till_frontend_devices_deleted()
        self.hotunplug_format_nodes()
        self.check_block_jobs_running(self._jobs)
        self.wait_mirror_jobs_completed()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()


def run(test, params, env):
    """
    Block mirror with hotunplug test

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a target disk for mirror to VM via qmp commands
        5. do block-mirror with sync mode full
        6. hotunplug the frontend device with device_del (OK)
        7. hotunplug the format node with blockdev-del (ERROR)
        8. check mirror continues and wait mirror done
        9. restart VM with the mirror disk
       10. check the file and its md5

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorHotunplugTest(test, params, env)
    mirror_test.run_test()
