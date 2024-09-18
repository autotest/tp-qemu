import logging
import socket
import time

from avocado.utils import process
from virttest import error_context

from provider.blockdev_base import BlockdevBaseTest
from provider.nbd_image_export import QemuNBDExportImage

LOG_JOB = logging.getLogger("avocado.test")


class BlockReconnectTest(BlockdevBaseTest):
    """
    Block kill and reconnect test
    """

    def __init__(self, test, params, env):
        self.net_down = False
        self.disk_op_cmd = params["disk_op_cmd"]
        self.disk_op_timeout = int(params.get("disk_op_timeout", 360))
        localhost = socket.gethostname()
        params["nbd_server_%s" % params["nbd_image_tag"]] = (
            localhost if localhost else "localhost"
        )
        self.timeout = int(params.get("login_timeout", 360))
        self.repeat_times = int(params["repeat_times"])
        self.reconnect_time_wait = int(params["reconnect_time_wait"])
        self.vm = env.get_vm(params["main_vm"])
        super(BlockReconnectTest, self).__init__(test, params, env)

    def prepare_test(self):
        try:
            self.create_local_image()
            self.export_local_image_with_nbd()
            super(BlockReconnectTest, self).prepare_test()
        except Exception:
            self.clean_images()
            raise

    def create_local_image(self):
        image_params = self.params.object_params(self.params["local_image_tag"])
        local_image = self.source_disk_define_by_params(
            image_params, self.params["local_image_tag"]
        )
        local_image.create(image_params)
        self.trash.append(local_image)

    def export_local_image_with_nbd(self):
        self.nbd_export = QemuNBDExportImage(
            self.params, self.params["local_image_tag"]
        )
        self.nbd_export.export_image()

    def get_disk_storage_name(self, system_disk_cmd, data_disk_cmd):
        """
        get data disk name
        return: data disk name e.g. /dev/sdb
        """
        error_context.context("Identify data disk.", LOG_JOB.info)
        LOG_JOB.info("Identify data disk")
        session = self.vm.wait_for_login(timeout=self.timeout)
        system_disk_name = session.cmd(
            system_disk_cmd, timeout=self.disk_op_timeout
        ).strip()
        find_disk_cmd = data_disk_cmd % system_disk_name
        data_disk_name = session.cmd(
            find_disk_cmd, timeout=self.disk_op_timeout
        ).strip()
        LOG_JOB.info("The data disk is %s", data_disk_name)
        session.close()
        return system_disk_name, data_disk_name

    def run_io_test(self, test_disk):
        """Run io test on given disks."""
        error_context.context("Run io test on %s." % test_disk, LOG_JOB.info)
        session = self.vm.wait_for_login(timeout=self.timeout)
        test_cmd = self.disk_op_cmd % (test_disk, test_disk)
        session.cmd(test_cmd, timeout=self.disk_op_timeout)
        session.close()

    def run_iptables(self, cmd):
        result = process.run(cmd, ignore_status=True, shell=True)
        if result.exit_status != 0:
            LOG_JOB.error("command error: %s", result.stderr.decode())

    def break_net_with_iptables(self):
        self.run_iptables(self.params["net_break_cmd"])
        self.net_down = True

    def resume_net_with_iptables(self):
        self.run_iptables(self.params["net_resume_cmd"])
        self.net_down = False

    def reconnect_loop_io(self):
        error_context.context("Run IO test when in reconnecting loop", LOG_JOB.info)
        for iteration in range(self.repeat_times):
            error_context.context(
                "Wait %s seconds" % self.reconnect_time_wait, LOG_JOB.info
            )
            time.sleep(self.reconnect_time_wait)
            self.run_io_test("test_file")

    def check_data_disk_resume(self, test_disk):
        error_context.context("check data disk resumed", LOG_JOB.info)
        for iteration in range(self.repeat_times):
            LOG_JOB.info("Wait %s seconds", self.reconnect_time_wait)
            time.sleep(self.reconnect_time_wait)
            self.run_io_test(test_disk)

    def clean_images(self):
        """
        recover nbd image access
        """
        if self.net_down:
            self.resume_net_with_iptables()

        self.stop_export_local_image_with_nbd()

        super(BlockReconnectTest, self).clean_images()

    def stop_export_local_image_with_nbd(self):
        LOG_JOB.info("Stop export nbd data disk image.")
        self.nbd_export.stop_export()

    def do_test(self):
        disk_storage_name = self.get_disk_storage_name(
            self.params["find_system_disk_cmd"], self.params["find_data_disk_cmd"]
        )
        data_disk = disk_storage_name[1]
        self.run_io_test(data_disk)
        self.stop_export_local_image_with_nbd()
        self.break_net_with_iptables()
        self.reconnect_loop_io()
        self.nbd_export.export_image()
        self.resume_net_with_iptables()
        self.check_data_disk_resume(data_disk)


@error_context.context_aware
def run(test, params, env):
    """
    Test kill/reconnect of block devices.

        1) Boot up guest with a data disk.
        2) Do I/O on data disk
        3) Kill nbd export image process.
        4) Apply a firewall on nbd data disk's port
        5) Check guest system disk function
        6) Drop the firewall
        7) Export the nbd data disk image
        8) Do I/O on data disk

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    kill_reconnect_test = BlockReconnectTest(test, params, env)
    kill_reconnect_test.run_test()
