from virttest import data_dir, storage

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest
from provider.job_utils import get_event_by_condition


class BlockdevMirrorCancelReadyIOError(BlockdevMirrorNowaitTest):
    """
    Cancel a ready job when target image is in error
    """

    def __init__(self, test, params, env):
        params["filter-node-name"] = params["filter_node_name"]
        super(BlockdevMirrorCancelReadyIOError, self).__init__(test, params, env)

    def _blockdev_add_image(self, tag):
        params = self.params.object_params(tag)
        devices = self.main_vm.devices.images_define_by_params(tag, params, "disk")
        devices.pop()
        for dev in devices:
            if self.main_vm.devices.get_by_qid(dev.get_qid()):
                continue
            ret = self.main_vm.devices.simple_hotplug(dev, self.main_vm.monitor)
            if not ret[1]:
                self.test.fail("Failed to hotplug '%s': %s." % (dev, ret[0]))

    def _create_image(self, tag):
        disk = self.disk_define_by_params(self.params, tag)
        disk.create(self.params)
        self.trash.append(disk)

    def create_source_image(self):
        """create source image of data image"""
        self._create_image(self.params["source_images"])

    def create_target_image(self):
        """create target image of mirror image"""
        self._create_image(self.params["target_images"])

    def add_source_image(self):
        """blockdev-add source image: protocol and format nodes only"""
        self.create_source_image()
        self._blockdev_add_image(self.params["source_images"])

    def add_target_image(self):
        """blockdev-add target image: protocol and format nodes only"""
        self.create_target_image()
        # Fixme if blkdebug driver is supported completely in avocado-vt
        target = self.params["target_images"]
        target_params = self.params.object_params(target)
        target_filename = storage.get_image_filename(
            target_params, data_dir.get_data_dir()
        )
        args = {
            "node-name": "drive_target",
            "driver": "qcow2",
            "file": {
                "driver": "blkdebug",
                "image": {"driver": "file", "filename": target_filename},
                "set-state": [{"event": "flush_to_disk", "state": 1, "new_state": 2}],
                "inject-error": [
                    {
                        "event": "flush_to_disk",
                        "once": True,
                        "immediately": True,
                        "state": 2,
                    }
                ],
            },
        }
        self.main_vm.monitor.cmd("blockdev-add", args)

    def qemu_io_source(self):
        qmp_cmd = "human-monitor-command"
        filter_node = self.params["filter_node_name"]
        qemu_io_cmd = 'qemu-io %s "write 0 64k"' % filter_node
        args = {"command-line": qemu_io_cmd}
        self.main_vm.monitor.cmd(qmp_cmd, args)

    def cancel_job(self):
        self.main_vm.monitor.cmd("block-job-cancel", {"device": self._jobs[0]})
        event = get_event_by_condition(
            self.main_vm,
            "BLOCK_JOB_ERROR",
            self.params.get_numeric("job_cancelled_timeout", 60),
            device=self._jobs[0],
            action="stop",
        )
        if event is None:
            self.test.fail("Job failed to cancel")

    def wait_till_job_ready(self):
        event = get_event_by_condition(
            self.main_vm,
            "BLOCK_JOB_READY",
            self.params.get_numeric("job_ready_timeout", 120),
            device=self._jobs[0],
        )
        if event is None:
            self.test.fail("Job failed to reach ready state")

    def prepare_test(self):
        self.prepare_main_vm()

    def do_test(self):
        self.add_source_image()
        self.add_target_image()
        self.blockdev_mirror()
        self.wait_till_job_ready()
        self.qemu_io_source()
        self.cancel_job()


def run(test, params, env):
    """
    Cancel a ready job with target in error

    test steps:
        1. boot VM.
        2. hotplug 128M source node
        3. hotplug target node with eject error event set
        4. mirror from source to target
        5. when mirror reach ready status, wirte data to source
        node with qemu-io
        6. cancel mirror job
        7. check mirror job stopped with Block_job_error

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorCancelReadyIOError(test, params, env)
    mirror_test.run_test()
