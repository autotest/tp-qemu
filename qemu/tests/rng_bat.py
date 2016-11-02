import re
import logging
import aexpect

from virttest import utils_misc
from virttest import error_context
from virttest import utils_test
from avocado.core import exceptions
from avocado.utils import process


@error_context.context_aware
def run(test, params, env):
    """
    Qemu virtio-rng device test:
    1) boot guest with virtio-rng device
    3) check host random device opened by qemu (optional)
    4) enable driver verifier in guest
    5) check device using right driver in guest.
    6) read random data from guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def is_dev_used_by_qemu(dev_file, vm_pid):
        """
        Check host random device opened by qemu.

        :param dev_file: host random device name.
        :param vm_pid: qemu process ID.
        :return: Match objects or None.
        """
        lsof_cmd = "lsof %s" % dev_file
        output = process.system_output(lsof_cmd, ignore_status=True)
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

    def check_driver_status(session, check_cmd, driver_id):
        """
        :param session: VM session
        :param check_cmd: cmd to check driver status
        :param driver_id: driver id
        """
        check_cmd = check_cmd.replace("DRIVER_ID", driver_id)
        status, output = session.cmd_status_output(check_cmd)
        print output
        if "disabled" in output:
            raise exceptions.TestFail("Driver is disable")

    def get_driver_id(session, cmd, pattern):
        """
        :param session: VM session
        :param cmd: cmd to get driver id
        :param pattern: driver id pattern
        """
        output = session.cmd_output(cmd)
        driver_id = re.findall(pattern, output)
        if not driver_id:
            raise exceptions.TestFail("Didn't find driver info from guest %s"
                                      % output)
        driver_id = driver_id[0]
        driver_id = '^&'.join(driver_id.split('&'))
        return driver_id

    rng_data_rex = params.get("rng_data_rex", r".*")
    dev_file = params.get("filename_passthrough")
    timeout = float(params.get("login_timeout", 360))
    rng_dll_register_cmd = params.get("rng_dll_register_cmd")
    read_rng_timeout = float(params.get("read_rng_timeout", "360"))
    cmd_timeout = float(params.get("session_cmd_timeout", "360"))
    driver_name = params["driver_name"]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm_pid = vm.get_pid()

    if dev_file:
        error_context.context("Check '%s' used by qemu" % dev_file,
                              logging.info)
        if not is_dev_used_by_qemu(dev_file, vm_pid):
            msg = "Qemu (pid=%d) not using host passthrough " % vm_pid
            msg += "device '%s'" % dev_file
            raise exceptions.TestFail(msg)

    if params["os_type"] == "windows":
        utils_test.qemu.setup_win_driver_verifier(driver_name,
                                                  vm, timeout)
        error_context.context("Check driver status", logging.info)
        session = vm.wait_for_login(timeout=timeout)
        driver_id_cmd = set_winutils_letter(params.get("driver_id_cmd"),
                                            session, params)
        driver_id = get_driver_id(session, driver_id_cmd,
                                  params["driver_id_pattern"])
        if params.get("driver_check_cmd"):
            driver_check_cmd = set_winutils_letter(
                params.get("driver_check_cmd"), session, params)
            check_driver_status(session, driver_check_cmd, driver_id)
    else:
        error_context.context("verify virtio-rng device driver", logging.info)
        session = vm.wait_for_login(timeout=timeout)
        verify_cmd = params["driver_verifier_cmd"]
        try:
            output = session.cmd_output_safe(verify_cmd, timeout=cmd_timeout)
        except aexpect.ShellTimeoutError:
            err = "%s timeout, pls check if it's a product bug" % verify_cmd
            raise exceptions.TestFail(err)

        if not re.search(r"%s" % driver_name, output, re.M):
            msg = "Verify device driver failed, "
            msg += "guest report driver is %s, " % output
            msg += "expect is '%s'" % driver_name
            raise exceptions.TestFail(msg)

    error_context.context("Read virtio-rng device to get random number",
                          logging.info)
    read_rng_cmd = set_winutils_letter(params.get("read_rng_cmd"),
                                       session, params)
    if rng_dll_register_cmd:
        logging.info("register 'viorngum.dll' into system")
        session.cmd(rng_dll_register_cmd, timeout=120)

    output = session.cmd_output(read_rng_cmd, timeout=read_rng_timeout)
    if len(re.findall(rng_data_rex, output, re.M)) < 2:
        raise exceptions.TestFail("Unable to read random numbers from"
                                  "guest: %s" % output)
    session.close()
