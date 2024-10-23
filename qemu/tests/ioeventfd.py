"""
ioeventfd.py include following case:
    1. Test ioeventfd under stress.
    2. Check the ioeventfd property.
"""

import re

from avocado.utils import process
from virttest import env_process, error_context, qemu_qtree, utils_test

from provider.storage_benchmark import generate_instance
from qemu.tests.virtio_serial_file_transfer import transfer_data


@error_context.context_aware
def run(test, params, env):
    """
    Test the related functions of ioeventfd.
    Step:
        Scenario 1:
            1.1 Start guest with ioeventfd=off.
                For windows: Check whether vioscsi.sys verifier enabled in
                the guest.
            1.2 I/O test in the guest.
                For linux: do dd testing.
                For windows: do fio testing.
            1.3 Reboot the guest.
            1.4 Run iozone in the guest.
            1.5 Power off the guest.
            1.6 Repeat the step 1.1-1.5 with ioeventfd=on.
        Scenario 2:
            2.1 Boot guest with ioeventfd=off.
            2.2 Execute info qtree in QMP monitor, info qtree should show the
                ioeventfd = false.
            2.3 Check the ioeventfd=off via /proc/$PID/fd/.
            2.4 Boot guest with ioeventfd=on.
            2.5 Execute info qtree in QMP monitor, info qtree should show the
                ioeventfd = true.
            2.6 Check the ioeventfd=on via /proc/$PID/fd/.
            2.7 Compare the output of 'ls -l /proc/$PID/fd/', the fds with
                "off" should be less than the one with "on".
        Scenario 3:
            3.1 Boot guest with ioeventfd=off and port attched to virtio_serial_pci.
            3.2 Execute info qtree in QMP monitor, info qtree should show the
                ioeventfd = false.
            3.3 Check the ioeventfd=off via /proc/$PID/fd/.
            3.4 Transfer data via the virtserialport.
            3.5 Boot guest with ioeventfd=on attched to one virtio_serial_pci.
            3.6 Execute info qtree in QMP monitor, info qtree should show the
                ioeventfd = true.
            3.7 Check the ioeventfd=on via /proc/$PID/fd/.
            3.8 Compare the output of 'ls -l /proc/$PID/fd/', the fds with
                "off" should be less than the one with "on".
            3.9 Transfer data via the virtserialport.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _set_ioeventfd_options():
        """
        Set the ioeventfd options.

        :return: device id with parameter ioeventfd
        """
        dev_type = params.get("dev_type")
        if dev_type == "virtio_serial":
            params["virtio_serial_extra_params_vs1"] = ioeventfd
            dev_id = params.get("dev_id", "virtio_serial_pci0")
        elif params["drive_format"] == "virtio":
            params["blk_extra_params_image1"] = ioeventfd
            dev_id = "image1"
        elif params["drive_format"] == "scsi-hd":
            params["bus_extra_params_image1"] = ioeventfd
            dev_id = params.get("dev_id", "virtio_scsi_pci0")
        else:
            raise ValueError(f"unexpected dev_type: {dev_type}")
        return dev_id

    def _dd_test(session):
        """Execute dd testing inside guest."""
        test.log.info("Doing dd testing inside guest.")
        test.log.debug(session.cmd(params["dd_cmd"], float(params["stress_timeout"])))

    def _fio_test(session):
        """Execute fio testing inside guest."""
        test.log.info("Doing fio testing inside guest.")
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, params["driver_name"]
        )
        fio = generate_instance(params, vm, "fio")
        try:
            fio.run(params["fio_options"], float(params["stress_timeout"]))
        finally:
            fio.clean()

    def _io_stress_test():
        """Execute io stress testing inside guest."""
        {"windows": _fio_test, "linux": _dd_test}[os_type](session)

    def _iozone_test(session):
        """Execute iozone testing inside guest."""
        test.log.info("Doing iozone inside guest.")
        if os_type == "windows":
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, params["driver_name"]
            )
        iozone = generate_instance(params, vm, "iozone")
        try:
            iozone.run(params["iozone_options"], float(params["iozone_timeout"]))
        finally:
            iozone.clean()
            return session

    def _check_property(vm, ioeventfd_opt):
        """
        Check the value of ioeventfd by sending "info qtree" in QMP.
        """
        ioevent_qtree_val = "true" if "on" in ioeventfd_opt else "false"
        test.log.info("Execute info qtree in QMP monitor.")
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(vm.monitor.info("qtree"))
        for node in qtree.get_nodes():
            if isinstance(node, qemu_qtree.QtreeDev) and (
                node.qtree.get("id", None) == dev_id
            ):
                if node.qtree.get("ioeventfd", None) is None:
                    test.fail("The qtree device %s has no property ioeventfd." % dev_id)
                elif node.qtree["ioeventfd"] == ioevent_qtree_val:
                    test.log.info(
                        'The "%s" matches with qtree device "%s"(%s).',
                        ioeventfd_opt,
                        dev_id,
                        ioevent_qtree_val,
                    )
                    break
                else:
                    test.fail(
                        'The "%s" mismatches with qtree device "%s"(%s).'
                        % (ioeventfd_opt, dev_id, ioevent_qtree_val)
                    )
        else:
            test.error('No such "%s" qtree device.' % dev_id)

    def _get_ioeventfds(ioeventfd_opt):
        """
        Get the number of ioeventfds inside host.
        """
        test.log.info('Check the "%s" via /proc/$PID/fd/.', ioeventfd)
        dst_log = "off" if "off" in ioeventfd_opt else "on"
        cmd = "ls -l /proc/$(pgrep qemu-kvm)/fd > /tmp/{0}; cat /tmp/{0}".format(
            dst_log
        )
        test.log.debug("Running '%s'", cmd)
        s, o = process.getstatusoutput(cmd)
        test.log.debug(o)
        if s:
            test.error("Failed to get the number of event fd.\n%s" % o)

    def _compare_ioeventfds():
        """
        Compare fd number of ioeventfd=on between ioeventfd=off
        """
        error_context.context(
            "Compare the output of 'ls -l /proc/$PID/fd/'.", test.log.info
        )
        cmd = "grep -c eventfd /tmp/off /tmp/on;rm -rf /tmp/off /tmp/on"
        test.log.debug("Running '%s'", cmd)
        s, o = process.getstatusoutput(cmd)
        test.log.debug(o)
        if s:
            test.error("Failed to compare the outputs.\n%s" % s)
        nums = re.findall(r"\w+:(\d+)", o, re.M)
        if int(nums[0]) > int(nums[1]):
            test.fail(
                'The number of event fds with "off" '
                'should be less than the one with "on".'
            )
        test.log.info(
            'The number of event fds with "off" ' 'is less than the one with "on".'
        )

    params["start_vm"] = "yes"
    os_type = params["os_type"]
    timeout = float(params.get("login_timeout", 240))
    ioeventfds = (params["orig_ioeventfd"], params["new_ioeventfd"])
    for ioeventfd in ioeventfds:
        dev_id = _set_ioeventfd_options()
        # Disable iothread when ioeventfd=off
        if ioeventfd == "ioeventfd=off" and params.get("iothread_scheme"):
            error_context.context(
                "Disable iothread under %s" % ioeventfd, test.log.info
            )
            clone_params = params.copy()
            clone_params["iothread_scheme"] = None
            clone_params["image_iothread"] = None
            clone_params["iothreads"] = ""
        else:
            clone_params = params

        error_context.context('Boot a guest with "%s".' % ioeventfd, test.log.info)
        env_process.preprocess_vm(test, clone_params, env, params["main_vm"])
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        if params.get("io_stress", "no") == "yes":
            _io_stress_test()
        else:
            _check_property(vm, ioeventfd)
            _get_ioeventfds(ioeventfd)
        if params.get("reboot", "no") == "yes":
            error_context.context("Reboot the guest.", test.log.info)
            session = _iozone_test(vm.reboot(session, timeout=timeout))
        if params.get("data_transfer", "no") == "yes":
            if os_type == "windows":
                session = utils_test.qemu.windrv_check_running_verifier(
                    session, vm, test, params["driver_name"]
                )
            transfer_data(params, vm)
        session.close()
        vm.destroy(gracefully=True)
    if params.get("compare_fd", "no") == "yes":
        _compare_ioeventfds()
