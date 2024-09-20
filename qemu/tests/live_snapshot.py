import time

from avocado.utils import process
from virttest import data_dir, error_context, utils_misc, utils_test


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
        error_context.context("Creating live snapshot ...", test.log.info)
        block_info = vm.monitor.info("block")
        if vm.monitor.protocol == "qmp":
            device = block_info[0]["device"]
        else:
            device = "".join(block_info).split(":")[0]
        format = params.get("snapshot_format", "qcow2")
        vm.monitor.live_snapshot(device, snapshot_file, format=format)

        test.log.info("Check snapshot is created ...")
        snapshot_info = str(vm.monitor.info("block"))
        if snapshot_file not in snapshot_info:
            test.log.error(snapshot_info)
            test.fail("Snapshot doesn't exist")

    snapshot_file = "images/%s" % params.get("snapshot_file")
    snapshot_file = utils_misc.get_path(data_dir.get_data_dir(), snapshot_file)
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
            test.log.info("Clean file before creation")
            session.cmd(clean_cmd)  # pylint: disable=E0606

            test.log.info("Creating big file...")
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
            utils_test.run_virt_sub_test, args, {"sub_type": "unattended_install"}
        )
        bg.start()
        if bg.is_alive():
            sleep_time = int(params.get("sleep_time", 60))
            time.sleep(sleep_time)
            create_snapshot(vm)
            try:
                bg.join()
            except Exception:
                raise

    try:
        subcommand = params.get("subcommand")
        eval("%s_test()" % subcommand)
    finally:
        process.system("rm -f %s" % snapshot_file)
