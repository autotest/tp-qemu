import logging
import re
import time

from virttest import error_context
from virttest import utils_test
from virttest import env_process
from virttest import virt_vm
from virttest import utils_disk
from virttest import utils_net
from virttest.utils_windows import virtio_win


@error_context.context_aware
def run(test, params, env):
    """
    Boot guest with different vectors, then do netperf testing.

    1) Boot up VM with vectors.
    2) Enable multi queues in guest.
    3) Check guest pci msi support.
    4) Check the cpu interrupt of virito driver.
    5) Run netperf test in guest.
    6) Repeat step 1 ~ step 5 with different vectors.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def boot_guest_with_vectors(vectors):
        error_context.context("Boot guest with vectors = %s" % vectors,
                              logging.info)
        params["vectors"] = vectors
        params["start_vm"] = "yes"
        try:
            env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        except virt_vm.VMError as err:
            if int(vectors) < 0:
                txt = "Parameter 'vectors' expects uint32_t"
                if re.findall(txt, str(err)):
                    return
        if int(vectors) < 0:
            msg = "Qemu did not raise correct error"
            msg += " when vectors = %s" % vectors
            test.fail(msg)

        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        return vm

    def get_MSI_queue_from_traceview_output(output):
        """
        Extract msi&queues information from traceview log file output

        :param output: the content of traceview processed log infomation
        """

        def _convert_fun(item):
            value_pair = list(reversed(item.split()))
            if not value_pair[1].isdigit():
                value_pair[0] = 'MSIs'
                value_pair[1] = 0
            else:
                value_pair[1] = int(value_pair[1])
            return value_pair

        info_str = "Start checking dump content for msi & queues info"
        error_context.context(info_str, logging.info)
        search_exp = r"\d+ MSIs|\d+ queues"
        lines = output.split('\n')
        for line in lines:
            # special case for vectors = 0
            queue_when_no_msi = re.search(r'No MSIX, using (\d+) queue', line)
            if queue_when_no_msi:
                return (0, int(queue_when_no_msi.group(1)))

            search_res = re.findall(search_exp, line)
            if not search_res:
                continue
            try:
                value_dict = dict(map(_convert_fun, search_res))
                MSIs_number = value_dict["MSIs"]
                queues_number = value_dict["queues"]
                return (MSIs_number, queues_number)
            except Exception:
                pass
        return (None, None)

    def _remove_file(session, file_path):
        """
        Remove a file at file_path

        :param file_path: file path to remove
        :param session: a logined session
        """

        clean_cmd = "del %s" % file_path
        session.cmd_status(clean_cmd)

    def _copy_file(session, src_path, dst_folder):
        """
        Copy a file at src_path to dst_folder.
        If a same name file already exists at dst_folder, it will be replaced.

        :param session: a logined sesison
        :param src_path: file to copy from
        :param dst_folder: folder to copy to

        """

        copy_cmd = "xcopy %s %s /y" % (src_path, dst_folder)
        session.cmd_status(copy_cmd)

    def get_MSIs_and_queues_windows():
        """
        Get msi&queues infomation of currentwindows guest.
        First start a traceview session, then restart the nic interface
        to trigger logging. By analyzing the dumped output, the msi& queue
        info is acquired.

        :return: a tuple of (msis, queues)
        """

        session_serial = vm.wait_for_serial_login(login_timeout)
        # start traceview
        error_context.context("Start trace view with pdb file", logging.info)
        log_path = "c:\\logfile.etl"
        clean_cmd = "del %s" % log_path
        session_serial.cmd(clean_cmd)
        traceview_local_path = "c:\\traceview.exe"
        pdb_local_path = "c:\\netkvm.pdb"
        start_traceview_cmd = "%s -start test_session -pdb %s -level 5 -flag 0x1fff -f %s"
        start_traceview_cmd %= (traceview_local_path, pdb_local_path, log_path)
        session_serial.cmd(start_traceview_cmd)

        # restart nic
        error_context.context("Restart guest nic", logging.info)
        mac = vm.get_mac_address(0)
        connection_id = utils_net.get_windows_nic_attribute(session_serial,
                                                            "macaddress",
                                                            mac,
                                                            "netconnectionid")
        utils_net.restart_windows_guest_network(session_serial, connection_id)

        # stop traceview
        error_context.context("Stop traceview", logging.info)
        stop_traceview_cmd = "%s -stop test_session" % traceview_local_path
        session_serial.cmd(stop_traceview_cmd)

        # checkout traceview output
        error_context.context("Check etl file generated by traceview", logging.info)
        dump_file = "c:\\trace.txt"
        _remove_file(session_serial, dump_file)
        dump_cmd = "%s -process %s -pdb %s -o %s"
        dump_cmd %= (traceview_local_path, log_path, pdb_local_path, dump_file)
        status, output = session_serial.cmd_status_output(dump_cmd)
        if status:
            test.error("Cann't dump log file %s: %s" % (log_path, output))
        time.sleep(100)
        status, output = session_serial.cmd_status_output("taskkill /im traceview.exe && type %s" % dump_file)
        if status:
            test.error("Cann't read dumped file %s: %s" % (dump_file, output))

        return get_MSI_queue_from_traceview_output(output)

    def prepare_traceview_windows(session, timeout):
        """
        First check the driver installation status, then copy traceview.exe
        and corresponding pdb file to drive c: for future use.

        :param session: a session to send command
        :timeout: the command execute timeout
        :return: the session after driver checking.
        """

        # verify driver
        error_context.context("Check if the driver is installed and "
                              "verified", logging.info)
        driver_name = params.get("driver_name", "netkvm")
        session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                test,
                                                                driver_name,
                                                                timeout)

        # copy traceview.exe
        error_context.context("Copy traceview.exe to drive C", logging.info)
        traceview_path_template = params.get("traceview_path_template")
        cd_drive = utils_disk.get_winutils_vol(session)
        traceview_path = traceview_path_template % cd_drive
        _copy_file(session, traceview_path, "c:\\")

        # copy Netkvm.pdb
        error_context.context("Find Netkvm.pdb and copy to drive C", logging.info)
        viowin_ltr = virtio_win.drive_letter_iso(session)
        if not viowin_ltr:
            test.error("Could not find virtio-win drive in guest")
        guest_name = virtio_win.product_dirname_iso(session)
        if not guest_name:
            test.error("Could not get product dirname of the vm")
        guest_arch = virtio_win.arch_dirname_iso(session)
        if not guest_arch:
            test.error("Could not get architecture dirname of the vm")

        pdb_middle_path = "%s\\%s" % (guest_name, guest_arch)
        pdb_find_cmd = 'dir /b /s %s\\%s.pdb | findstr "\\%s\\\\"'
        pdb_find_cmd %= (viowin_ltr, driver_name, pdb_middle_path)
        pdb_path = session.cmd(pdb_find_cmd, timeout=timeout).strip()
        logging.info("Found Netkvm.pdb file at '%s'", pdb_path)
        _copy_file(session, pdb_path, "c:\\")
        return session

    def check_msi_support(session):
        vectors = int(params["vectors"])
        if params["os_type"] == "linux":
            devices = session.cmd_output("lspci | grep Eth").strip()
            error_context.context("Check if vnic inside guest support msi.",
                                  logging.info)
            for device in devices.split("\n"):
                if not device:
                    continue
                d_id = device.split()[0]
                msi_check_cmd = params["msi_check_cmd"] % d_id
                output = session.cmd_output(msi_check_cmd)
                if vectors == 0 and output:
                    test.fail("Guest do not support msi when vectors = 0.")
                if output:
                    if vectors == 1:
                        if "MSI-X: Enable-" in output:
                            logging.info("MSI-X is disabled")
                        else:
                            msg = "Command %s get wrong output." % msi_check_cmd
                            msg += " when vectors = 1"
                            test.fail(msg)
                    else:
                        if "MSI-X: Enable+" in output:
                            logging.info("MSI-X is enabled")
                        else:
                            msg = "Command %s get wrong output." % msi_check_cmd
                            msg += " when vectors = %d" % vectors
                            test.fail(msg)
        else:
            # use traceview
            prepare_traceview_windows(session, 360)
            msis, queues = get_MSIs_and_queues_windows()
            if None in (msis, queues):
                test.fail("Can't get msi status from guest.")
            if vectors == 0 and msis != 0 and queues != 1:
                test.fail("Msis should be 0, queues should be 1  when vectors = 1,"
                          " but guest msis = %s, queues = %s" % (msis, queues))
            elif vectors != msis:
                test.fail("Msis should equal to vectors(%s), but guest is %s" % (vectors, msis))

    def check_interrupt(session, vectors):
        error_context.context("Check the cpu interrupt of virito",
                              logging.info)
        vectors = int(vectors)
        irq_check_cmd = params["irq_check_cmd"]
        output = session.cmd_output(irq_check_cmd).strip()
        if vectors == 0 or vectors == 1:
            if not (re.findall("IO-APIC.*fasteoi|XICS.*Level|XIVE.*Level",
                               output)):
                msg = "Could not find interrupt controller for virito device"
                msg += " when vectors = %d" % vectors
                test.fail(msg)
        elif 2 <= vectors and vectors <= 8:
            if not re.findall("virtio[0-9]-virtqueues", output):
                msg = "Could not find the virtio device for MSI-X interrupt"
                msg += " when vectors = %d " % vectors
                msg += "Command %s got output %s" % (irq_check_cmd, output)
                test.fail(msg)
        elif vectors == 9 or vectors == 10:
            if not (re.findall("virtio[0-9]-input", output) and
                    re.findall("virtio[0-9]-output", output)):
                msg = "Could not find the virtio device for MSI-X interrupt"
                msg += " when vectors = %d " % vectors
                msg += "Command %s got output %s" % (irq_check_cmd, output)
                test.fail(msg)

    vectors_list = params["vectors_list"]
    login_timeout = int(params.get("login_timeout", 360))
    sub_test = params.get("sub_test_name", "netperf_stress")
    for vectors in vectors_list.split():
        vm = boot_guest_with_vectors(vectors)
        if int(vectors) < 0:
            continue
        session = vm.wait_for_login(timeout=login_timeout)
        check_msi_support(session)
        if params["os_type"] == "linux":
            check_interrupt(session, vectors)
        error_context.context("Run netperf test in guest.", logging.info)
        utils_test.run_virt_sub_test(test, params, env, sub_type=sub_test)
