import os
import random
import time

import aexpect
from avocado.utils import crypto, process
from virttest import utils_misc, utils_net


def run(test, params, env):
    """
    Nic teaming test in guest.

    1) Start guest with four nic devices.
    2) Setup Team in guest.
    3) Execute file transfer from host to guest.
    4) Repeatedly set enable/disable interfaces by 'netsh interface set'
    5) Execute file transfer from guest to host.

    :param test: Kvm test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    tmp_dir = params["tmp_dir"]
    filesize = params.get_numeric("filesize")
    dd_cmd = params["dd_cmd"]
    delete_cmd = params["delete_cmd"]
    login_timeout = params.get_numeric("login_timeout", 1200)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session_serial = vm.wait_for_serial_login(timeout=login_timeout)
    nics = params.objects("nics")
    ifnames = ()
    for i in range(len(nics)):
        mac = vm.get_mac_address(i)
        connection_id = utils_net.get_windows_nic_attribute(
            session_serial, "macaddress", mac, "netconnectionid"
        )
        ifnames += (connection_id,)

    # get params of teaming
    setup_cmd = params["setup_cmd"]
    status, output = session_serial.cmd_status_output(setup_cmd % ifnames)
    if status:
        test.fail(
            "Failed to setup team nic from powershell,"
            "status=%s, output=%s" % (status, output)
        )

    # prepare test data
    guest_path = tmp_dir + "src-%s" % utils_misc.generate_random_string(8)
    host_path = os.path.join(
        test.tmpdir, "tmp-%s" % utils_misc.generate_random_string(8)
    )
    test.log.info("Test setup: Creating %dMB file on host", filesize)
    process.run(dd_cmd % host_path, shell=True)

    try:
        netsh_set_cmd = 'netsh interface set interface "%s" %s'
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
                    session_serial.cmd(netsh_set_cmd % (ifname, "disable"))
                    time.sleep(random.randint(1, 30))
                    session_serial.cmd(netsh_set_cmd % (ifname, "enable"))
                    time.sleep(random.randint(1, 30))
        except aexpect.ShellProcessTerminatedError:
            transfer_thread.join(suppress_exception=True)
            raise
        else:
            transfer_thread.join()

        os.remove(host_path)
        test.log.info("Cleaning temp file on host")
        test.log.info("Failover test 2 with file transfer")
        transfer_thread = utils_misc.InterruptedThread(
            vm.copy_files_from, (guest_path, host_path)
        )
        transfer_thread.start()
        try:
            nic_num = len(ifnames)
            index = 0
            while transfer_thread.is_alive():
                index = index % nic_num
                for i in range(nic_num):
                    session_serial.cmd(netsh_set_cmd % (ifnames[i], "enable"))
                    for j in range(nic_num):
                        if i != j:
                            session_serial.cmd(netsh_set_cmd % (ifnames[j], "disable"))
                time.sleep(random.randint(1, 5))
                index += 1
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
        os.remove(host_path)
        session_serial.cmd(
            delete_cmd % guest_path, timeout=login_timeout, ignore_all_errors=True
        )
        session_serial.close()
