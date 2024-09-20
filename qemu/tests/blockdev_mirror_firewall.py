import socket

from avocado.utils import process

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest
from provider.nbd_image_export import QemuNBDExportImage


class BlockdevMirrorFirewallTest(BlockdevMirrorNowaitTest):
    """
    Block mirror with firewall test
    """

    def __init__(self, test, params, env):
        localhost = socket.gethostname()
        params["nbd_server_%s" % params["nbd_image_tag"]] = (
            localhost if localhost else "localhost"
        )
        self._offset = None
        self._net_down = False

        super(BlockdevMirrorFirewallTest, self).__init__(test, params, env)

    def _create_local_image(self):
        image_params = self.params.object_params(self.params["local_image_tag"])
        local_image = self.source_disk_define_by_params(
            image_params, self.params["local_image_tag"]
        )
        local_image.create(image_params)
        self.trash.append(local_image)

    def _export_local_image_with_nbd(self):
        self._nbd_export = QemuNBDExportImage(
            self.params, self.params["local_image_tag"]
        )
        self._nbd_export.export_image()

    def prepare_test(self):
        try:
            self._create_local_image()
            self._export_local_image_with_nbd()
            super(BlockdevMirrorFirewallTest, self).prepare_test()
        except Exception:
            self.clean_images()
            raise

    def add_target_data_disks(self):
        tag = self._target_images[0]
        devices = self.main_vm.devices.images_define_by_params(
            tag, self.params.object_params(tag), "disk"
        )
        devices.pop()  # ignore the front end device

        for dev in devices:
            ret = self.main_vm.devices.simple_hotplug(dev, self.main_vm.monitor)
            if not ret[1]:
                self.test.fail("Failed to hotplug '%s': %s." % (dev, ret[0]))

    def _run_iptables(self, cmd):
        cmd = cmd.format(s=self.params["nbd_server_%s" % self.params["nbd_image_tag"]])
        result = process.run(cmd, ignore_status=True, shell=True)
        if result.exit_status != 0:
            self.test.error("command error: %s" % result.stderr.decode())

    def break_net_with_iptables(self):
        self._run_iptables(self.params["net_break_cmd"])
        self._net_down = True

    def resume_net_with_iptables(self):
        self._run_iptables(self.params["net_resume_cmd"])
        self._net_down = False

    def clean_images(self):
        # recover nbd image access
        if self._net_down:
            self.resume_net_with_iptables()

        # stop nbd image export
        self._nbd_export.stop_export()

        super(BlockdevMirrorFirewallTest, self).clean_images()

    def do_test(self):
        self.blockdev_mirror()
        self.check_block_jobs_started(
            self._jobs, self.params.get_numeric("mirror_started_timeout", 10)
        )
        self.break_net_with_iptables()
        self.check_block_jobs_paused(
            self._jobs, self.params.get_numeric("mirror_paused_interval", 50)
        )
        self.resume_net_with_iptables()
        self.check_block_jobs_running(
            self._jobs, self.params.get_numeric("mirror_resmued_timeout", 200)
        )
        self.wait_mirror_jobs_completed()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()


def run(test, params, env):
    """
    Block mirror with firewall test

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. create a 2G local fs image, exported with qemu-nbd
        5. add the nbd image for mirror to VM via qmp commands
        6. do blockdev-mirror
        7. insert a rule with iptables to drop all packets from
           the port to which the nbd image was bound
        8. check mirror paused (offset should not change)
        9. remove the rule with iptables
       10. check mirror job resumed (offset should increase)
       11. wait till mirror job done
       12. check the mirror disk is attached
       13. restart VM with the mirror disk
       14. check the file and its md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorFirewallTest(test, params, env)
    mirror_test.run_test()
