import socket

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest
from provider.nbd_image_export import QemuNBDExportImage


class BlockdevMirrorRemoteServerDownTest(BlockdevMirrorNowaitTest):
    """
    Suspend/resume remote storage service while doing blockdev-mirror
    """

    def __init__(self, test, params, env):
        localhost = socket.gethostname()
        params["nbd_server_%s" % params["nbd_image_tag"]] = (
            localhost if localhost else "localhost"
        )
        self.nbd_export = QemuNBDExportImage(params, params["local_image_tag"])
        super(BlockdevMirrorRemoteServerDownTest, self).__init__(test, params, env)

    def _create_local_image(self):
        image_params = self.params.object_params(self.params["local_image_tag"])
        local_image = self.source_disk_define_by_params(
            image_params, self.params["local_image_tag"]
        )
        local_image.create(image_params)
        self.trash.append(local_image)

    def prepare_test(self):
        try:
            self._create_local_image()
            self.nbd_export.export_image()
            super(BlockdevMirrorRemoteServerDownTest, self).prepare_test()
        except Exception:
            self.clean_images()
            raise

    def add_target_data_disks(self):
        """Mirror image is an exported nbd image"""

        tag = self._target_images[0]
        devices = self.main_vm.devices.images_define_by_params(
            tag, self.params.object_params(tag), "disk"
        )
        devices.pop()

        for dev in devices:
            ret = self.main_vm.devices.simple_hotplug(dev, self.main_vm.monitor)
            if not ret[1]:
                self.test.fail("Failed to hotplug '%s': %s." % (dev, ret[0]))

    def clean_images(self):
        self.nbd_export.stop_export()
        super(BlockdevMirrorRemoteServerDownTest, self).clean_images()

    def do_test(self):
        self.blockdev_mirror()
        self.check_block_jobs_started(
            self._jobs, self.params.get_numeric("job_started_timeout", 10)
        )
        self.nbd_export.suspend_export()
        try:
            self.check_block_jobs_paused(
                self._jobs, self.params.get_numeric("job_paused_interval", 30)
            )
        finally:
            self.nbd_export.resume_export()
        self.main_vm.monitor.cmd(
            "block-job-set-speed", {"device": self._jobs[0], "speed": 0}
        )
        self.wait_mirror_jobs_completed()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()


def run(test, params, env):
    """
    Suspend/resume remote storage service while doing blockdev-mirror

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. create a local image and export it with qemu-nbd
        5. hotplug the exported image as the mirror target
        6. do blockdev-mirror
        7. suspend qemu-nbd
        8. check mirror job paused
        9. resume qemu-nbd
       10. wait till mirror job done
       11. restart vm with mirror image and check files

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorRemoteServerDownTest(test, params, env)
    mirror_test.run_test()
