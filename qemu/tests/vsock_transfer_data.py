import logging
import threading
import time

from avocado.utils import process
from virttest import error_context

from provider.win_driver_utils import get_driver_inf_path

LOG_JOB = logging.getLogger("avocado.test")


class VSockTransfer:
    """
    VSOCK data transfer handler for host-guest communication
    """

    def __init__(self):
        """
        Initialize the VSockTransfer instance
        """
        self.server_ready = threading.Event()
        self.results = {}

    def server_thread(self, session, cmd):
        """
        Execute server command in guest VM

        :param session: VM session object
        :param cmd: Server command to execute
        """
        self.server_ready.set()
        result = session.cmd_output(cmd)
        self.results["server"] = ("success", result)

    def client_thread(self, cmd):
        """
        Execute client command on host

        :param cmd: Client command to execute
        """
        self.server_ready.wait()
        time.sleep(1)
        result = process.system_output(cmd)
        self.results["client"] = ("success", result)

    def run(self, session, server_cmd, client_cmd):
        """
        Execute VSOCK data transfer between host and guest

        :param session: VM session object
        :param server_cmd: Command to run in guest VM
        :param client_cmd: Command to run on host
        :returns: Transfer results dictionary
        """
        threads = [
            threading.Thread(target=self.server_thread, args=(session, server_cmd)),
            threading.Thread(target=self.client_thread, args=(client_cmd,)),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        return self.results


@error_context.context_aware
def run(test, params, env):
    """
    Vsock transfer data test

    1. Boot guest with vhost-vsock-pci device
    2. Start viosocklib-test.exe in guest
    3. Transfer data from host to VM
    4. Check src and dst file's md5sum

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    LOG_JOB.info("Boot guest with vhost-vsock-pci device")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    test_tool = params["test_tool"]
    virtio_win_media_type = params["virtio_win_media_type"]
    driver_name = params["driver_name"]
    vsock_dev = params["vsocks"].split()[0]
    guest_cid = vm.devices.get(vsock_dev).get_param("guest-cid")

    LOG_JOB.info("Start viosocklib-test.exe in guest")
    path = get_driver_inf_path(session, test, virtio_win_media_type, driver_name)
    test_tool_src_path = path[: path.rfind("\\")] + "\\" + test_tool
    session.cmd_output("xcopy %s C:\\ /y" % test_tool_src_path)
    process.system_output(params["generate_file_cmd"])
    server_cmd = params["receive_data_cmd"]
    client_cmd = params["send_data_cmd"] % guest_cid

    LOG_JOB.info("Transfer data from host to VM")
    transfer = VSockTransfer()
    transfer.run(session, server_cmd, client_cmd)

    LOG_JOB.info("Check src and dst file's md5sum")
    src_output = process.system_output("md5sum %s" % params["src_file_path"]).decode()
    src_md5_sum = src_output.split()[0]
    dst_output = session.cmd_output(params["md5sum_check_cmd"])
    dst_md5_sum = dst_output.splitlines()[1]
    if src_md5_sum != dst_md5_sum:
        test.fail("File md5sum is not the same after transfer from host to guest")
    else:
        LOG_JOB.info("MD5 verification passed")

    session.close()
