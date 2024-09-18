import os
import random
import time

from avocado.utils import crypto, process
from virttest import data_dir, error_context, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Test nic driver load/unload.

    1) Boot a VM.
    2) Get the NIC driver name.
    3) Multi-session TCP transfer on test interface.
    4) Repeatedly unload/load NIC driver during file transfer.
    5) Check whether the test interface should still work.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def reset_guest_udevrules(session, rules_file, rules_content):
        """
        Write guest udev rules, then reboot the guest and
        return the new session
        """
        set_cmd = "echo '%s' > %s" % (rules_content, rules_file)
        session.cmd_output_safe(set_cmd)
        return vm.reboot()

    def all_threads_done(threads):
        """
        Check whether all threads have finished
        """
        for thread in threads:
            if thread.is_alive():
                return False
            else:
                continue
        return True

    def all_threads_alive(threads):
        """
        Check whether all threads is alive
        """
        for thread in threads:
            if not thread.is_alive():
                return False
            else:
                continue
        return True

    timeout = int(params.get("login_timeout", 360))
    transfer_timeout = int(params.get("transfer_timeout", 1000))
    filesize = int(params.get("filesize", 512))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    vm_mac_address = vm.get_mac_address()
    udev_rules_file = "/etc/udev/rules.d/70-persistent-net.rules"
    rules = params.get("rules")
    if not session.cmd_status("[ -e %s ]" % udev_rules_file):
        if not rules:
            test.cancel("You must set udev rules before test")
        rules = rules % vm_mac_address
        session = reset_guest_udevrules(session, udev_rules_file, rules)

    error_context.base_context("Test env prepare")
    error_context.context("Get NIC interface name in guest.", test.log.info)
    ethname = utils_net.get_linux_ifname(session, vm.get_mac_address(0))
    # get ethernet driver from '/sys' directory.
    # ethtool can do the same thing and doesn't care about os type.
    # if we make sure all guests have ethtool, we can make a change here.
    sys_path = params.get("sys_path") % (ethname)
    # readlink in RHEL4.8 doesn't have '-e' param, should use '-f' in RHEL4.8.
    readlink_cmd = params.get("readlink_command", "readlink -e")
    driver = os.path.basename(session.cmd("%s %s" % (readlink_cmd, sys_path)).strip())
    test.log.info("The guest interface %s using driver %s", ethname, driver)

    error_context.context(
        "Host test file prepare, create %dMB file on host" % filesize, test.log.info
    )
    tmp_dir = data_dir.get_tmp_dir()
    host_path = os.path.join(
        tmp_dir, "host_file_%s" % utils_misc.generate_random_string(8)
    )
    guest_path = os.path.join(
        "/home", "guest_file_%s" % utils_misc.generate_random_string(8)
    )
    cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (host_path, filesize)
    process.run(cmd)
    file_checksum = crypto.hash_file(host_path, algorithm="md5")

    error_context.context(
        "Guest test file prepare, Copy file %s from host to " "guest" % host_path,
        test.log.info,
    )
    vm.copy_files_to(host_path, guest_path, timeout=transfer_timeout)
    if session.cmd_status("md5sum %s | grep %s" % (guest_path, file_checksum)):
        test.cancel("File MD5SUMs changed after copy to guest")
    test.log.info("Test env prepare successfully")

    error_context.base_context("Nic driver load/unload testing", test.log.info)
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    try:
        error_context.context("Transfer file between host and guest", test.log.info)
        threads = []
        file_paths = []
        host_file_paths = []
        for sess_index in range(int(params.get("sessions_num", "10"))):
            sess_path = os.path.join("/home", "dst-%s" % sess_index)
            host_sess_path = os.path.join(tmp_dir, "dst-%s" % sess_index)

            thread1 = utils_misc.InterruptedThread(
                vm.copy_files_to, (host_path, sess_path), {"timeout": transfer_timeout}
            )

            thread2 = utils_misc.InterruptedThread(
                vm.copy_files_from,
                (guest_path, host_sess_path),
                {"timeout": transfer_timeout},
            )
            thread1.start()
            threads.append(thread1)
            thread2.start()
            threads.append(thread2)
            file_paths.append(sess_path)
            host_file_paths.append(host_sess_path)

        utils_misc.wait_for(lambda: all_threads_alive(threads), 60, 10, 1)

        time.sleep(5)
        error_context.context(
            "Repeatedly unload/load NIC driver during file " "transfer", test.log.info
        )
        while not all_threads_done(threads):
            error_context.context(
                "Shutdown the driver for NIC interface.", test.log.info
            )
            sleep_time = random.randint(1, 5)
            error_context.context("Unload  NIC driver.", test.log.info)
            session_serial.cmd_output_safe("modprobe -r %s" % driver)
            time.sleep(sleep_time)
            error_context.context("Load NIC driver.", test.log.info)
            session_serial.cmd_output_safe("modprobe %s" % driver)
            time.sleep(sleep_time)

        # files md5sums check
        error_context.context(
            "File transfer finished, checking files md5sums", test.log.info
        )
        err_info = []
        for copied_file in file_paths:
            if session_serial.cmd_status(
                "md5sum %s | grep %s" % (copied_file, file_checksum)
            ):
                err_msg = "Guest file %s md5sum changed"
                err_info.append(err_msg % copied_file)
        for copied_file in host_file_paths:
            if process.system(
                "md5sum %s | grep %s" % (copied_file, file_checksum), shell=True
            ):
                err_msg = "Host file %s md5sum changed"
                err_info.append(err_msg % copied_file)
        if err_info:
            test.error("files MD5SUMs changed after copying %s" % err_info)
    except Exception:
        for thread in threads:
            thread.join(suppress_exception=True)
            raise
    else:
        for thread in threads:
            thread.join()
        for copied_file in file_paths:
            session_serial.cmd("rm -rf %s" % copied_file)
        for copied_file in host_file_paths:
            process.system("rm -rf %s" % copied_file)
        session_serial.cmd("%s %s" % ("rm -rf", guest_path))
        os.remove(host_path)
        session.close()
        session_serial.close()
