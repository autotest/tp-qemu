import re
import time

from virttest import error_context, utils_misc, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Runs CPU hotplug test:

    0) sync host clock via ntp server
    1) Boot the vm with -smp X,maxcpus=Y
    2) After logged into the vm, check CPUs number
    3) Stop the guest if config 'stop_before_hotplug'
    4) sync guest clock via ntp server if config ntp_sync_cmd
    5) Do cpu hotplug
    6) Resume the guest if config 'stop_before_hotplug'
    7) Recheck guest get hot-pluged CPUs
    8) Do cpu online/offline in guest and check clock
       offset via ntp server if config online/offline_cpus
    9) Run sub test after CPU Hotplug if run_sub_test is 'yes'
    10) Recheck guest cpus after sub test if vcpu_num_rechek is 'yes'

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def get_clock_offset(session, ntp_query_cmd):
        """
        Get guest clock offset between ntp service;
        """
        output = session.cmd_output(ntp_query_cmd)
        try:
            offset = float(re.findall(r"[+-](\d+\.\d+)", output)[-1])
        except IndexError:
            offset = 0.0
        return offset

    def qemu_guest_cpu_match(vm, vcpu_been_pluged=0, wait_time=300):
        """
        Check Whether the vcpus are matche
        """
        total_cpus_expected = int(vm.cpuinfo.smp) + int(vcpu_been_pluged)
        if utils_misc.wait_for(
            lambda: (
                (total_cpus_expected == vm.get_cpu_count())
                and (vm.get_cpu_count() == len(vm.vcpu_threads))
            ),
            wait_time,
            first=10,
            step=5.0,
        ):
            test.log.info("Cpu number in cmd_line, qemu and guest are match")
            return True
        err_msg = "Cpu mismatch! "
        err_msg += "after hotplug %s vcpus, " % vcpu_been_pluged
        err_msg += "there shoule be %s vcpus exist, " % total_cpus_expected
        err_msg += "in qemu %s vcpus threads works, " % len(vm.vcpu_threads)
        err_msg += "in guest %s cpus works." % vm.get_cpu_count()
        test.fail(err_msg)

    def cpu_online_offline(session, cpu_id, online=""):
        """
        Do cpu online/offline in guest
        """
        if online == "online":
            online = 1
        else:
            online = 0
        online_file = "/sys/devices/system/cpu/cpu%s/online" % cpu_id
        if session.cmd_status("test -f %s" % online_file):
            test.log.info(
                "online file %s not exist, just pass the cpu%s", online_file, cpu_id
            )
            return
        session.cmd("echo %s > %s " % (online, online_file))

    def onoff_para_opt(onoff_params):
        """
        Online offline params anaylize
        Return a cpu list need do online offline
        """
        onoff_list = []
        offline = onoff_params.split(",")
        for item in offline:
            if "-" in item:
                onoff_list += range(int(item.split("-")[0]), int(item.split("-")[1]))
            else:
                onoff_list.append(item)
        return [str(i) for i in onoff_list]

    timeout = int(params.get("login_timeout", 360))
    onoff_iterations = int(params.get("onoff_iterations", 2))
    vcpu_need_hotplug = int(params.get("vcpu_need_hotplug", 1))
    acceptable_offset = float(params.get("acceptable_offset", 5))
    ntp_query_cmd = params.get("ntp_query_cmd", "")
    ntp_sync_cmd = params.get("ntp_sync_cmd", "")

    error_context.context("Boot the vm, with '-smp X,maxcpus=Y' option", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    maxcpus = vm.cpuinfo.maxcpus
    if params.get("max_cpus_need_hotplug", "no") == "yes":
        vcpu_need_hotplug = vcpu_need_hotplug - vm.cpuinfo.smp

    if ntp_sync_cmd:
        error_context.context("sync guest time via ntp server", test.log.info)
        session.cmd(ntp_sync_cmd)

    error_context.context(
        "Check if cpus in guest match qemu " "cmd before hotplug", test.log.info
    )
    qemu_guest_cpu_match(vm)

    # do pre_operation like stop, before vcpu Hotplug
    stop_before_hotplug = params.get("stop_before_hotplug", "no")
    if stop_before_hotplug == "yes":
        error_context.context("Stop the guest before hotplug vcpu", test.log.info)
        vm.pause()

    error_context.context("Do cpu hotplug", test.log.info)
    if vm.monitor.protocol == "human":
        human_check_info = params.get("human_error_recheck", None)
        qmp_check_info = None
        hotplug_add_cmd = ""
    elif vm.monitor.protocol == "qmp":
        qmp_check_info = params.get("qmp_error_recheck", None)
        hotplug_add_cmd = params.get("vcpu_add_cmd", "")
        if hotplug_add_cmd:
            human_check_info = params.get("human_error_recheck", None)
        else:
            human_check_info = None
    else:
        raise ValueError(f"unexpected monitor protocol type {vm.monitor.protocol}")

    vcpu_been_pluged = 0
    for i in range(vcpu_need_hotplug):
        hotplug_vcpu_params = params.object_params("hotplug_vcpu%s" % i)
        plug_cpu_id = len(vm.vcpu_threads)
        plug_cpu_id = hotplug_vcpu_params.get("cpuid", plug_cpu_id)

        (status, output) = vm.hotplug_vcpu(plug_cpu_id, hotplug_add_cmd)

        if status:
            if not qmp_check_info and not human_check_info:
                vcpu_been_pluged += 1
                test.log.info("Cpu%s hotplug successfully", plug_cpu_id)
                test.log.info("Now '%s' cpus have been hotpluged", vcpu_been_pluged)
                continue
            else:
                err_msg = "Qemu should report error, but hotplug successfully"
                test.fail(err_msg)
        else:
            if not output:
                warn_msg = "Qemu should report some warning information"
                test.error(warn_msg)
            if qmp_check_info and re.findall(qmp_check_info, output, re.I):
                msg = "Hotplug vcpu(id:'%s') error, qemu report the error."
                test.log.info(msg, plug_cpu_id)
                test.log.debug("QMP error info: '%s'", output)
                continue
            elif human_check_info and re.findall(human_check_info, output, re.I):
                msg = "Hotplug vcpu(id:'%s') error, qemu report the error"
                test.log.info(msg, plug_cpu_id)
                test.log.debug("Error info: '%s'", output)
                continue
            else:
                err_msg = "Hotplug error! "
                err_msg += "the hotplug cpu_id is: '%s', " % plug_cpu_id
                err_msg += "the maxcpus allowed is: '%s', " % maxcpus
                err_msg += "qemu cpu list is:'%s'" % vm.monitor.info("cpus")
                test.log.debug("The error info is:\n '%s'", output)
                test.fail(err_msg)

    if stop_before_hotplug == "yes":
        error_context.context("Resume the guest after cpu hotplug", test.log.info)
        vm.resume()

    if params.get("reboot_after_hotplug", False):
        error_context.context("Reboot guest after hotplug vcpu", test.log.info)
        vm.reboot()

    if vcpu_been_pluged != 0:
        error_context.context(
            "Check whether cpus are match after hotplug", test.log.info
        )
        qemu_guest_cpu_match(vm, vcpu_been_pluged)

    error_context.context("Do cpu online/offline in guest", test.log.info)
    # Window guest doesn't support online/offline test
    if params["os_type"] == "windows":
        test.log.info("For windows guest not do online/offline test")
        return

    online_list = []
    offline_list = []
    offline = params.get("offline", "")
    online = params.get("online", "")
    repeat_time = int(params.get("repeat_time", 0))

    if offline:
        offline_list = onoff_para_opt(offline)
        test.log.debug("Cpu offline list is %s ", offline_list)
    if online:
        online_list = onoff_para_opt(online)
        test.log.debug("Cpu online list is %s ", offline_list)

    for i in range(repeat_time):
        for offline_cpu in offline_list:
            cpu_online_offline(session, offline_cpu)
            test.log.info("sleep %s seconds", onoff_iterations)
            time.sleep(onoff_iterations)
            if ntp_query_cmd:
                error_context.context(
                    "Check guest clock after online cpu", test.log.info
                )
                current_offset = get_clock_offset(session, ntp_query_cmd)
                if current_offset > acceptable_offset:
                    test.fail(
                        "time drift(%ss)" % current_offset
                        + "after online cpu(%s)" % offline_cpu
                    )
        for online_cpu in online_list:
            cpu_online_offline(session, online_cpu, "online")
            test.log.info("sleep %s seconds", onoff_iterations)
            time.sleep(onoff_iterations)
            if ntp_query_cmd:
                error_context.context(
                    "Check guest clock after offline cpu", test.log.info
                )
                current_offset = get_clock_offset(session, ntp_query_cmd)
                if current_offset > acceptable_offset:
                    test.fail(
                        "time drift(%s)" % current_offset
                        + "after offline cpu(%s)" % online_cpu
                    )

    # do sub test after cpu hotplug
    if params.get("run_sub_test", "no") == "yes" and "sub_test_name" in params:
        sub_test = params["sub_test_name"]
        error_context.context(
            "Run subtest %s after cpu hotplug" % sub_test, test.log.info
        )
        if sub_test == "guest_suspend" and params["guest_suspend_type"] == "disk":
            vm.params["smp"] = int(vm.cpuinfo.smp) + vcpu_been_pluged
            vcpu_been_pluged = 0
        utils_test.run_virt_sub_test(test, params, env, sub_type=sub_test)
        if sub_test == "shutdown":
            test.log.info("Guest shutdown normally after cpu hotplug")
            return
        if params.get("session_need_update", "no") == "yes":
            session = vm.wait_for_login(timeout=timeout)

    if params.get("vcpu_num_rechek", "yes") == "yes":
        error_context.context("Recheck cpu numbers after operation", test.log.info)
        qemu_guest_cpu_match(vm, vcpu_been_pluged)

    if session:
        session.close()
