import os
import re
import time
import random
import logging

from virttest import utils_test
from virttest import utils_misc
from virttest import error_context
from avocado.core import exceptions
from aexpect import ShellCmdError
from virttest.utils_test.qemu import MemoryBaseTest
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Balloon service test for windows guest.
    1) boot a windows guest with balloon device.
    2) enable and check driver verifier in guest.
    3) install balloon service in guest.
    4) enable polling in qmp.
    5) evict and enlarge balloon.
    6) get polling value in qmp.
    7) uninstall balloon service and clear driver verifier.
    """

    def get_disk_vol(session):
        """
        Get virtio-win disk volume letter.

        :param session: VM session.
        """
        key = "VolumeName like 'virtio-win%'"
        try:
            return utils_misc.get_win_disk_vol(session,
                                               condition=key)
        except Exception:
            raise exceptions.TestFail("Could not get virtio-win disk vol!")

    def config_balloon_service(session, drive_letter):
        """
        Check / Install balloon service.

        :param session: VM session.
        :param drive_letter: virtio-win disk volume letter.
        """
        status_cmd = params["status_balloon_service"] % drive_letter
        logging.debug("Check balloon service status.")
        output = session.cmd_output(status_cmd)
        if re.search(r"running", output.lower(), re.M):
            logging.debug("Balloon service is already running !")
        elif re.search(r"stop", output.lower(), re.M):
            logging.debug("Run Balloon Service in guest.")
            try:
                start_cmd = params["run_balloon_service"] % drive_letter
                session.cmd(start_cmd)
            except ShellCmdError:
                raise exceptions.TestError("Start balloon service failed!")
        else:
            logging.debug("Install Balloon Service in guest.")
            try:
                install_cmd = params["install_balloon_service"] % drive_letter
                session.cmd(install_cmd)
            except ShellCmdError:
                raise exceptions.TestError("Install balloon service failed !")

    def memory_check(vm, get_polling_output, keyname):
        """
        Check memory status.

        :param vm: VM object.
        :param get_polling_output: output of get polling in qmp.
        :param keyname: key name of the output of the 'qom-get' property.
        """
        check_mem_ratio = float(params.get("check_mem_ratio", 0.1))

        error_context.context("Get memory from guest", logging.info)
        mem_base = MemoryBaseTest(test, params, env)
        if keyname == "stat-free-memory":
            guest_mem = mem_base.get_guest_free_mem(vm)
        elif keyname == "stat-total-memory":
            guest_mem = mem_base.get_vm_mem(vm)

        error_context.context("Get memory from qmp", logging.info)
        stat_memory_qmp = get_polling_output['stats'][keyname]
        stat_memory_qmp = "%sB" % stat_memory_qmp
        stat_memory_qmp = int(float(utils_misc.normalize_data_size(
                                   (stat_memory_qmp), order_magnitude="M")))

        error_context.context("Compare memory from guest with qmp",
                              logging.info)
        if abs(float(guest_mem - stat_memory_qmp)) / guest_mem > check_mem_ratio:
            raise exceptions.TestFail("%s of guest %s is not equal to %s in"
                                      " qmp, the acceptable ratio is %s" %
                                      (keyname, guest_mem, stat_memory_qmp,
                                       check_mem_ratio))

    def balloon_memory(session, device_path):
        """
        Doing memory balloon in a loop and check memory status during balloon.

        :param session: VM session.
        :param device_path: balloon polling path.
        """
        repeat_times = int(params.get("repeat_times", 5))
        logging.info("repeat times: %d" % repeat_times)
        balloon_test = BallooningTestWin(test, params, env)

        while repeat_times:
            for tag in params.objects('test_tags'):
                error_context.context("Running %s test" % tag, logging.info)
                params_tag = params.object_params(tag)
                balloon_type = params_tag['balloon_type']
                min_sz, max_sz = balloon_test.get_memory_boundary(balloon_type)
                expect_mem = int(random.uniform(min_sz, max_sz))

                quit_after_test = balloon_test.run_ballooning_test(expect_mem,
                                                                   tag)
                time.sleep(20)
                get_polling_output = vm.monitor.qom_get(device_path,
                                                        get_balloon_property)
                time.sleep(20)
                memory_check(vm, get_polling_output, 'stat-free-memory')
                if quit_after_test:
                    return

            balloon_test.reset_memory()
            repeat_times -= 1

    timeout = int(params.get("login_timeout", 360))
    driver_name = params.get("driver_name", "balloon")

    error_context.context("Boot guest with balloon device", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    sleep_time = int(params.get("polling_sleep_time", 20))
    base_path = params.get("base_path", "/machine/peripheral/")
    device = params.get("balloon", "balloon0")
    device_path = os.path.join(base_path, device)
    set_balloon_property = params.get("set_balloon_property",
                                      "guest-stats-polling-interval")
    get_balloon_property = params.get("get_balloon_property", "guest-stats")
    polling_interval = int(params.get("polling_interval", 2))

    try:
        utils_test.qemu.setup_win_driver_verifier(driver_name, vm, timeout)

        error_context.context("Config balloon service in guest", logging.info)
        session = vm.wait_for_login(timeout=timeout)
        drive_letter = get_disk_vol(session)
        config_balloon_service(session, drive_letter)

        error_context.context("Enable polling in qemu", logging.info)
        vm.monitor.qom_set(device_path, set_balloon_property, polling_interval)
        time.sleep(sleep_time)
        get_polling_output = vm.monitor.qom_get(device_path,
                                                get_balloon_property)
        memory_check(vm, get_polling_output, 'stat-total-memory')

        error_context.context("Balloon vm memory in loop", logging.info)
        balloon_memory(session, device_path)

    finally:
        error_context.context("Clear balloon service in guest", logging.info)
        uninstall_cmd = params["uninstall_balloon_service"] % drive_letter
        session.cmd(uninstall_cmd, ignore_all_errors=True)
        session.close()
