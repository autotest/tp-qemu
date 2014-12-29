import re
import logging
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    Qemu virtio-rng device test:
    1) boot guest with virtio-rng device
    3) check host random device opened by qemu (optional)
    4) enable driver verifier in guest
    5) reboot guest (optional)
    6) check device using right driver in guest.
    7) read random data from guest.
    8) stop vm
    9) check vm relased host random device (optional)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def is_dev_used_by_qemu(dev_file, vm_pid):
        """
        Check host random device opened by qemu.

        :param dev_file: host random device name.
        :param vm_pid: qemu process ID.
        :return: False or True.
        """
        lsof_cmd = "lsof %s" % dev_file
        output = utils.system_output(lsof_cmd, ignore_status=True)
        return re.search(r"\s+%s\s+" % vm_pid, output, re.M)

    def set_winutils_letter(cmd, session, params):
        """
        Replace 'X:' in command to real cdrom drive letter.
        """
        vol = "X:"
        if params["os_type"] != "linux":
            vol = utils_misc.get_winutils_vol(session)
            vol = "%s:" % vol
        return cmd.replace("X:", vol)

    driver_name = params.get("driver_name")
    rng_data_rex = params.get("rng_data_rex", r".*")
    dev_file = params.get("filename_passthrough")
    timeout = float(params.get("login_timeout", 360))
    rng_dll_register_cmd = params.get("rng_dll_register_cmd")
    read_rng_timeout = float(params.get("read_rng_timeout", "360"))
    cmd_timeout = float(params.get("session_cmd_timeout", "360"))

    error.context("Boot guest with virtio-rng device", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm_pid = vm.get_pid()
    session = vm.wait_for_login(timeout=timeout)
    session_cmds = []
    session_cmds_key = ["read_rng_cmd",
                        "enable_verifier_cmd",
                        "driver_verifier_cmd"]
    for key in session_cmds_key:
        cmd = set_winutils_letter(params.get(key), session, params)
        session_cmds.append(cmd)
    read_rng_cmd, enable_verifier_cmd, driver_verifier_cmd = session_cmds

    if dev_file:
        error.context("Check '%s' used by qemu" % dev_file, logging.info)
        if not is_dev_used_by_qemu(dev_file, vm_pid):
            msg = "Qemu not using host passthrough "
            msg += "device '%s'" % dev_file
            raise error.TestFail(msg)

    error.context("enable driver verifier in guest", logging.info)
    session.cmd(enable_verifier_cmd,
                timeout=cmd_timeout, ignore_all_errors=True)
    if params.get("need_reboot", "") == "yes":
        vm.reboot()
        session = vm.wait_for_login(timeout=timeout)

    error.context("verify virtio-rng device driver", logging.info)
    output = session.cmd_output(driver_verifier_cmd, timeout=cmd_timeout)
    if not re.search(r"%s" % driver_name, output, re.M):
        msg = "Verify device driver failed, "
        msg += "guest report driver is %s, " % output
        msg += "expect is '%s'" % driver_name
        raise error.TestFail(msg)

    error.context("Read virtio-rng device to get random number", logging.info)
    if rng_dll_register_cmd:
        logging.info("register 'viorngum.dll' into system")
        session.cmd(rng_dll_register_cmd, timeout=120)
    output = session.cmd_output(read_rng_cmd, timeout=read_rng_timeout)
    if len(re.findall(rng_data_rex, output, re.M)) < 2:
        logging.debug("rng output: %s" % output)
        raise error.TestFail("Unable to read random numbers from guest.")

    error.context("Stop guest", logging.info)
    vm.destroy(gracefully=True)
    if dev_file:
        error.context("Check '%s' released by qemu" % dev_file, logging.info)
        if is_dev_used_by_qemu(dev_file, vm_pid):
            msg = "Qemu not release host device '%s' after it quit" % dev_file
            raise error.TestFail(msg)
