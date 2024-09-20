import os
import re
from shutil import copyfile

from avocado.utils import process
from virttest import arch, env_process, utils_misc
from virttest.staging import utils_memory
from virttest.utils_test import BackgroundTest, VMStress


def run(test, params, env):
    """
    Check KSM can be started automaticly when ksmtuned threshold is reached

    1. Get the memory of your host and the KSM_THRES_COEF
    2. Boot a guest with memory less than KSM_THRES_COEF threshold
    3. Get the memory used in host of process qemu-kvm
    4. Get the free memory in host
    5. If both the free memory size is not smaller than the threshold and guest
        used memory + threshold is not bigger than total memory in host. Check
        the ksm status in host. Ksm should not start in the host
    6. Repeat step 2~5 under it broke the rule in step 5

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def check_ksm(mem, threshold_reached=False):
        """
        :param mem: Boot guest with given memory, in KB
        :ksmtuned_enabled: ksmtuned threshold is reached or not
        """

        def heavyload_install():
            if session.cmd_status(test_install_cmd) != 0:  # pylint: disable=E0606
                test.log.warning(
                    "Could not find installed heavyload in guest, "
                    "will install it via winutils.iso "
                )
                winutil_drive = utils_misc.get_winutils_vol(session)
                if not winutil_drive:
                    test.cancel("WIN_UTILS CDROM not found.")
                install_cmd = params["install_cmd"] % winutil_drive
                session.cmd(install_cmd)

        def check_qemu_used_mem(qemu_pid, mem):
            qemu_used_page = process.getoutput(get_qemu_used_mem % qemu_pid, shell=True)
            qemu_used_mem = float(qemu_used_page) * pagesize
            if qemu_used_mem < mem * mem_thres:
                return False
            return True

        params["mem"] = mem // 1024
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        session = vm.wait_for_login()
        qemu_pid = vm.get_pid()
        if params["os_type"] == "linux":
            params["stress_args"] = "--cpu 4 --io 4 --vm 2 --vm-bytes %sM" % (
                int(params["mem"]) // 2
            )
            stress_test = VMStress(vm, "stress", params)
            stress_test.load_stress_tool()
        else:
            install_path = params["install_path"]
            test_install_cmd = 'dir "%s" | findstr /I heavyload' % install_path
            heavyload_install()
            heavyload_bin = r'"%s\heavyload.exe" ' % install_path
            heavyload_options = ["/MEMORY 100", "/START"]
            start_cmd = heavyload_bin + " ".join(heavyload_options)
            stress_tool = BackgroundTest(
                session.cmd, (start_cmd, stress_timeout, stress_timeout)
            )
            stress_tool.start()
            if not utils_misc.wait_for(stress_tool.is_alive, stress_timeout):
                test.error("Failed to start heavyload process")
        if not utils_misc.wait_for(
            lambda: check_qemu_used_mem(qemu_pid, mem), stress_timeout, 10, 10
        ):
            test.error(
                "QEMU used memory doesn't reach %s of guest mem %sM in "
                "%ss" % (mem_thres, mem // 1024, stress_timeout)
            )
        cmd = params["cmd_check_ksm_status"]
        free_mem_host = utils_memory.freememtotal()
        ksm_status = utils_misc.wait_for(
            lambda: "1" == process.getoutput(cmd), 40, first=20.0
        )
        vm.destroy()
        test.log.info(
            "The ksm threshold is %sM, QEMU used memory is %sM, "
            "and the total free memory on host is %sM",
            ksm_thres // 1024,
            mem // 1024,
            free_mem_host // 1024,
        )
        if threshold_reached:
            if free_mem_host > ksm_thres:
                test.error("Host memory is not consumed as much as expected")
            if not ksm_status:
                test.fail("KSM should be running")
        else:
            if free_mem_host < ksm_thres:
                test.error("Host memory is consumed too much more than " "expected")
            if ksm_status:
                test.fail("KSM should not be running")

    total_mem_host = utils_memory.memtotal()
    utils_memory.drop_caches()
    free_mem_host = utils_memory.freememtotal()
    ksm_thres = process.getoutput(params["cmd_get_thres"], shell=True)
    ksm_thres = int(total_mem_host * (int(re.findall("\\d+", ksm_thres)[0]) / 100))
    guest_mem = (free_mem_host - ksm_thres) // 2
    if arch.ARCH in ("ppc64", "ppc64le"):
        guest_mem = guest_mem - guest_mem % (256 * 1024)
    status_ksm_service = process.system(
        params["cmd_status_ksmtuned"], ignore_status=True
    )
    if status_ksm_service != 0:
        process.run(params["cmd_start_ksmtuned"])
    stress_timeout = params.get("stress_timeout", 1800)
    mem_thres = float(params.get("mem_thres", 0.95))
    get_qemu_used_mem = params["cmd_get_qemu_used_mem"]
    pagesize = utils_memory.getpagesize()
    check_ksm(guest_mem)

    ksm_config_file = params["ksm_config_file"]
    backup_file = ksm_config_file + ".backup"
    copyfile(ksm_config_file, backup_file)
    threshold = params.get_numeric("ksm_threshold")
    with open(ksm_config_file, "a+") as f:
        f.write("%s=%s" % (params["ksm_thres_conf"], threshold))
    process.run(params["cmd_restart_ksmtuned"])
    ksm_thres = total_mem_host * (threshold / 100)
    guest_mem = total_mem_host - ksm_thres // 2
    if arch.ARCH in ("ppc64", "ppc64le"):
        guest_mem = guest_mem - guest_mem % (256 * 1024)
    try:
        check_ksm(guest_mem, threshold_reached=True)
    finally:
        copyfile(backup_file, ksm_config_file)
        os.remove(backup_file)
        if status_ksm_service != 0:
            process.run(params["cmd_stop_ksmtuned"])
        else:
            process.run(params["cmd_restart_ksmtuned"])
