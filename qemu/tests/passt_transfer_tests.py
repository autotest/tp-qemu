import os
import re
import time

from avocado.utils import crypto, process
from virttest import error_context, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Test Step
        1. boot up two virtual machine with passt device
        2. For linux guest,Transfer data via tcp&udp:
        host-->guest1 & host-->guest2 & guest<-->guest2
        3. after data transfer, check data have no change
    Params:
        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """

    def get_file_md5sum(file_name, session, timeout):
        """
        Get file md5sum from guest.
        """
        test.log.info("Get md5sum of the file:'%s'", file_name)
        s, o = session.cmd_status_output("md5sum %s" % file_name, timeout=timeout)
        if s != 0:
            test.error("Get file md5sum failed as %s" % o)
        return re.findall(r"\w{32}", o)[0]

    def transfer_data(src, dst):
        error_context.context(
            "Transferring data from %s to %s" % (src.name, dst.name), test.log.info
        )
        nic = dst.virtnet[0]
        transfer_port = int(re.search(r"\d+", nic.net_port_forwards).group())
        sessions[dst].sendline(receive_cmd % (transfer_port, dest_path))
        time.sleep(5)
        sessions[src].sendline(sent_cmd % (guest_path, gateway, transfer_port))
        dst_md5 = get_file_md5sum(
            dest_path, sessions[dst], timeout=file_md5_check_timeout
        )
        error_context.context(
            "md5 value of data in %s: %s" % (dst.name, dst_md5), test.log.info
        )
        if dst_md5 != src_md5:
            test.fail("File changed transfer %s -> %s" % (src.name, dst.name))

    timeout = params.get_numeric("login_timeout", 360)
    receive_cmd = params.get("receive_cmd")
    sent_cmd = params.get("sent_cmd")
    tmp_dir = params["tmp_dir"]
    filesize = params.get_numeric("filesize")
    dd_cmd = params["dd_cmd"]
    file_md5_check_timeout = params.get_numeric("file_md5_check_timeout", 120)
    fw_stop_cmd = params["fw_stop_cmd"]

    sessions = {}
    ifname = {}

    error_context.context("Boot vms for test", test.log.info)
    vms = env.get_all_vms()
    for vm in vms:
        vm.verify_alive()
        sessions[vm] = vm.wait_for_serial_login(timeout=timeout)

    if params.get_boolean("ipv6"):
        gateway_address = utils_net.get_default_gateway(ip_ver="ipv6")
        local_address = "[::1]"
        ifname[vm] = utils_net.get_linux_ifname(sessions[vm], vm.get_mac_address())
        gateway = [f"{gateway_address}%{ifname[vm]}"]
    else:
        gateway = utils_net.get_default_gateway(ip_ver="ipv4")
        local_address = "localhost"
    # prepare test data
    guest_path = tmp_dir + "src-%s" % utils_misc.generate_random_string(8)
    dest_path = tmp_dir + "dst-%s" % utils_misc.generate_random_string(8)
    host_path = os.path.join(
        test.tmpdir, "tmp-%s" % utils_misc.generate_random_string(8)
    )
    test.log.info("Test setup: Creating %dbytes file on host", filesize)
    process.run(dd_cmd % (host_path, filesize), shell=True)

    try:
        src_md5 = crypto.hash_file(host_path, algorithm="md5")
        error_context.context("md5 value of data from src: %s" % src_md5, test.log.info)
        # transfer data from host to guest
        for vm in vms:
            error_context.context(
                "Transfer data from host to %s" % vm.name, test.log.info
            )
            sessions[vm].cmd_output_safe(fw_stop_cmd)
            nic = vm.virtnet[0]
            transfer_port = int(re.search(r"\d+", nic.net_port_forwards).group())
            sessions[vm].sendline(receive_cmd % (transfer_port, guest_path))
            time.sleep(5)
            process.run(
                sent_cmd % (host_path, local_address, transfer_port), shell=True
            )
            dst_md5 = get_file_md5sum(
                guest_path, sessions[vm], timeout=file_md5_check_timeout
            )
            error_context.context(
                "md5 value of data in %s: %s" % (vm.name, dst_md5), test.log.info
            )
            if dst_md5 != src_md5:
                test.fail("File changed after transfer host -> %s" % vm.name)

        transfer_data(*vms)
        transfer_data(*reversed(vms))

    finally:
        process.system("rm -rf %s" % host_path, timeout=timeout, ignore_status=True)
