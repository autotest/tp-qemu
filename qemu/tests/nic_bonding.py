import os
import random
import time

import aexpect
from avocado.utils import crypto, process
from virttest import utils_misc, utils_net


def run(test, params, env):
    """
    Nic bonding test in guest.

    1) Start guest with four nic devices.
    2) Setup bond0 in guest.
    3) Execute file transfer test between guest and host.
    4) Repeatedly put down/up interfaces by 'ip link'
    5) Execute file transfer test between guest and host.
    6) Check md5 value after transfered.

    :param test: Kvm test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    tmp_dir = params["tmp_dir"]
    filesize = params.get_numeric("filesize")
    dd_cmd = params["dd_cmd"]
    login_timeout = params.get_numeric("login_timeout", 1200)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    mac = vm.get_mac_address(0)
    session_serial = vm.wait_for_serial_login(timeout=login_timeout)
    ifnames = utils_net.get_linux_ifname(session_serial)

    ssh_login_cmd = (
        "echo LoginGraceTime 5m  >> /etc/ssh/sshd_config &&"
        " systemctl restart sshd.service || service sshd restart"
    )
    session_serial.cmd_output_safe(ssh_login_cmd)

    # get params of bonding
    nm_stop_cmd = "service NetworkManager stop; true"
    session_serial.cmd_output_safe(nm_stop_cmd)
    modprobe_cmd = "modprobe -r bonding; modprobe bonding"
    bonding_params = params.get("bonding_params")
    if bonding_params:
        modprobe_cmd += " %s" % bonding_params
    session_serial.cmd_output_safe(modprobe_cmd)
    session_serial.cmd_output_safe("ip link set dev bond0 addr %s up" % mac)
    setup_cmd = "ifenslave bond0 " + " ".join(ifnames)
    session_serial.cmd_output_safe(setup_cmd)
    dhcp_cmd = params.get("dhcp_cmd")
    session_serial.cmd_output_safe(dhcp_cmd, timeout=240)
    # prepare test data
    guest_path = os.path.join(tmp_dir + "dst-%s" % utils_misc.generate_random_string(8))
    host_path = os.path.join(
        test.tmpdir, "tmp-%s" % utils_misc.generate_random_string(8)
    )
    test.log.info("Test setup: Creating %dMB file on host", filesize)
    process.run(dd_cmd % host_path, shell=True)

    # get_bonding_nic_mac and ip
    try:
        link_set_cmd = "ip link set dev %s %s"
        # transfer data
        original_md5 = crypto.hash_file(host_path, algorithm="md5")
        test.log.info("md5 value of data original: %s", original_md5)
        test.log.info("Failover test with file transfer")
        transfer_thread = utils_misc.InterruptedThread(
            vm.copy_files_to, (host_path, guest_path)
        )
        transfer_thread.start()
        try:
            while transfer_thread.is_alive():
                for ifname in ifnames:
                    session_serial.cmd_output_safe(link_set_cmd % (ifname, "down"))
                    time.sleep(random.randint(1, 30))
                    session_serial.cmd_output_safe(link_set_cmd % (ifname, "up"))
                    time.sleep(random.randint(1, 30))
        except aexpect.ShellProcessTerminatedError:
            transfer_thread.join(suppress_exception=True)
            raise
        else:
            transfer_thread.join()

        test.log.info("Cleaning temp file on host")
        os.remove(host_path)
        test.log.info("Failover test 2 with file transfer")
        transfer_thread = utils_misc.InterruptedThread(
            vm.copy_files_from, (guest_path, host_path)
        )
        transfer_thread.start()
        try:
            nic_num = len(ifnames)
            up_index = 0
            while transfer_thread.is_alive():
                nic_indexes = list(range(nic_num))
                up_index = up_index % nic_num
                session_serial.cmd_output_safe(link_set_cmd % (ifnames[up_index], "up"))
                nic_indexes.remove(up_index)
                for num in nic_indexes:
                    session_serial.cmd_output_safe(
                        link_set_cmd % (ifnames[num], "down")
                    )
                time.sleep(random.randint(3, 5))
                up_index += 1
        except aexpect.ShellProcessTerminatedError:
            transfer_thread.join(suppress_exception=True)
            raise
        else:
            transfer_thread.join()
        current_md5 = crypto.hash_file(host_path, algorithm="md5")
        test.log.info("md5 value of data current: %s", current_md5)
        if original_md5 != current_md5:
            test.fail("File changed after transfer host -> guest " "and guest -> host")

    finally:
        session_serial.sendline("ifenslave -d bond0 " + " ".join(ifnames))
        session_serial.sendline("kill -9 `pgrep dhclient`")
        session_serial.sendline("sed -i '$ d' /etc/ssh/sshd_config")
