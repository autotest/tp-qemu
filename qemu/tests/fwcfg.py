from avocado.utils import process
from virttest import env_process, error_context, utils_disk, utils_test

from provider import win_driver_utils, win_dump_utils


@error_context.context_aware
def run(test, params, env):
    """
    Fwcfg64 basic function test:

    1) Boot guest with -device vmcoreinfo.
    2) Check the fwcfgg64 driver has been installed.
    3) Run "dump-guest-memory -w memory.dmp" in qemu monitor.
    4) Check the memory.dmp can be saved and the size is larger then 0Kb.
    5) Check the dump file can be open with windb tools.
    """
    win_dump_utils.set_vm_for_dump(test, params)
    vm_name = params["main_vm"]
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)

    session = vm.wait_for_login()
    driver = params["driver_name"]
    wdbg_timeout = params.get("wdbg_timeout", 600)
    error_context.context("Check fwcfg driver is running", test.log.info)
    utils_test.qemu.windrv_verify_running(session, test, driver)
    if params.get("setup_verifier", "yes") == "yes":
        error_context.context("Enable fwcfg driver verified", test.log.info)
        session = utils_test.qemu.setup_win_driver_verifier(session, driver, vm)

    error_context.context("Disable security alert", test.log.info)
    win_dump_utils.disable_security_alert(params, session)
    disk = sorted(session.cmd("wmic diskdrive get index").split()[1:])[-1]
    utils_disk.update_windows_disk_attributes(session, disk)
    disk_letter = utils_disk.configure_empty_disk(
        session, disk, params["image_size_stg"], params["os_type"]
    )[0]

    error_context.context("Generate the Memory.dmp file", test.log.info)
    dump_file, dump_zip_file = win_dump_utils.generate_mem_dump(test, params, vm)

    try:
        error_context.context(
            "Copy the Memory.dmp.zip file " "from host to guest", test.log.info
        )
        vm.copy_files_to(dump_zip_file, "%s:\\Memory.dmp.zip" % disk_letter)
        unzip_cmd = params["unzip_cmd"] % (disk_letter, disk_letter)
        unzip_timeout = int(params.get("unzip_timeout", 1800))
        status, output = session.cmd_status_output(unzip_cmd, timeout=unzip_timeout)
        if status:
            test.error("unzip dump file failed as:\n%s" % output)
        session.cmd(params["move_cmd"].format(disk_letter))
        session.cmd(params["save_path_cmd"].format(disk_letter))
        windbg_installed = False
        status, _ = session.cmd_status_output(params["chk_sdk_ins"])
        if not status:
            windbg_installed = True
        if not windbg_installed:
            win_dump_utils.install_windbg(test, params, session, timeout=wdbg_timeout)
        # TODO: A temporary workaround to clear up unexpected pop-up in guest
        if params.get("need_reboot", "no") == "yes":
            session = vm.reboot()
        win_dump_utils.dump_windbg_check(test, params, session)
    finally:
        process.system("rm %s %s" % (dump_file, dump_zip_file), shell=True)
        session.cmd("del %s" % params["dump_analyze_file"])
        session.cmd(params["del_path_file"])
        session.close()
    win_driver_utils.memory_leak_check(vm, test, params)
