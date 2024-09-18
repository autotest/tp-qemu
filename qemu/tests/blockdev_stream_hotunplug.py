import time

from virttest.qemu_monitor import QMPCmdError

from provider import job_utils
from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest


class BlockdevStreamHotunplugTest(BlockdevStreamNowaitTest):
    """
    Block stream with hotunplug test
    """

    def hotunplug_frontend_device(self):
        """
        device_del the frontend device during stream,
        the device CAN be removed without any issue
        """
        self.main_vm.monitor.cmd("device_del", {"id": self.base_tag})

    def wait_till_frontend_device_deleted(self):
        """Wait till devices removed from output of query-block"""

        def _is_device_deleted(device):
            for item in self.main_vm.monitor.query("block"):
                if device in item["qdev"]:
                    return False
            return True

        tmo = self.params.get_numeric("device_del_timeout", 60)
        for i in range(tmo):
            if _is_device_deleted(self.base_tag):
                break
            time.sleep(1)
        else:
            self.test.fail("Failed to hotunplug the frontend device")

    def hotunplug_format_node(self):
        """
        blockdev-del the format nodes during streaming,
        the nodes CANNOT be removed for they are busy
        """
        try:
            self.main_vm.monitor.cmd("blockdev-del", {"node-name": self.params["node"]})
        except QMPCmdError as e:
            if self.params["block_node_busy_error"] not in str(e):
                self.test.fail("Unexpected error: %s" % str(e))
        else:
            self.test.fail("blockdev-del succeeded unexpectedly")

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        job_utils.check_block_jobs_started(
            self.main_vm,
            [self._job],
            self.params.get_numeric("job_started_timeout", 60),
        )
        self.hotunplug_frontend_device()
        self.wait_till_frontend_device_deleted()
        self.hotunplug_format_node()
        job_utils.check_block_jobs_running(
            self.main_vm,
            [self._job],
            self.params.get_numeric("job_running_timeout", 300),
        )
        self.main_vm.monitor.cmd(
            "block-job-set-speed", {"device": self._job, "speed": 0}
        )
        self.wait_stream_job_completed()
        self.check_backing_file()
        self.clone_vm.create()
        self.mount_data_disks()
        self.verify_data_file()


def run(test, params, env):
    """
    Block stream with hotunplug test

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a snapshot image to VM via qmp commands
        5. do live snapshot (base: data, overlay: snapshot)
        6. do block-stream
        7. hotunplug the frontend device with device_del (OK)
        8. hotunplug the format node with blockdev-del (ERROR)
        9. check stream continues and wait stream done
       10. restart VM with the snapshot disk
       11. check the file and its md5

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamHotunplugTest(test, params, env)
    stream_test.run_test()
