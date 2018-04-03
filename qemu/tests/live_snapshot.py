import time
import logging

from virttest import error_context
from virttest import utils_misc
from virttest import utils_test


def run(test, params, env):
    """
    live_snapshot test:
    1). Create live snapshot during big file creating
    2). Create live snapshot when guest reboot
    3). Check if live snapshot is created
    4). Shutdown guest

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    @error_context.context_aware
    def create_snapshot(vm):
        """
        Create live snapshot:
        1). Check which monitor is used
        2). Get device info
        3). Create snapshot
        """
        error_context.context("Creating live snapshot ...", logging.info)
        block_info = vm.monitor.info("block")
        if vm.monitor.protocol == 'qmp':
            device = block_info[0]["device"]
        else:
            device = "".join(block_info).split(":")[0]
        snapshot_name = params.get("snapshot_file")
        format = params.get("snapshot_format", "qcow2")
        vm.monitor.live_snapshot(device, snapshot_name, format=format)

        logging.info("Check snapshot is created ...")
        snapshot_info = str(vm.monitor.info("block"))
        if snapshot_name not in snapshot_info:
            logging.error(snapshot_info)
            test.fail("Snapshot doesn't exist")

    timeout = int(params.get("login_timeout", 360))
    dd_timeout = int(params.get("dd_timeout", 900))
    vm = env.get_vm(params["main_vm"])
    if params.get("need_install", "no") == "no":
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)

    def runtime_test():
        try:
            clean_cmd = params.get("clean_cmd")
            file_create = params.get("file_create")
            clean_cmd += " %s" % file_create
            logging.info("Clean file before creation")
            session.cmd(clean_cmd)

            logging.info("Creating big file...")
            create_cmd = params.get("create_cmd") % file_create

            args = (create_cmd, dd_timeout)
            bg = utils_test.BackgroundTest(session.cmd_output, args)
            bg.start()
            time.sleep(5)
            create_snapshot(vm)
            if bg.is_alive():
                try:
                    bg.join()
                except Exception:
                    raise
        finally:
            session.close()

    def file_transfer_test():
        try:
            bg_cmd = utils_test.run_file_transfer
            args = (test, params, env)
            bg = utils_test.BackgroundTest(bg_cmd, args)
            bg.start()
            sleep_time = int(params.get("sleep_time"))
            time.sleep(sleep_time)
            create_snapshot(vm)
            if bg.is_alive():
                try:
                    bg.join()
                except Exception:
                    raise
        finally:
            session.close()

    def installation_test():
        args = (test, params, env)
        bg = utils_misc.InterruptedThread(
            utils_test.run_virt_sub_test, args,
            {"sub_type": "unattended_install"})
        bg.start()
        if bg.is_alive():
            sleep_time = int(params.get("sleep_time", 60))
            time.sleep(sleep_time)
            create_snapshot(vm)
            try:
                bg.join()
            except Exception:
                raise

    subcommand = params.get("subcommand")
    eval("%s_test()" % subcommand)
