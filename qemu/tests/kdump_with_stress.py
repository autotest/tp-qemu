from virttest import data_dir, error_context, utils_misc, utils_test

from generic.tests import kdump


@error_context.context_aware
def run(test, params, env):
    """
    KVM kdump test with stress:
    1) Log into a guest
    2) Check, configure and enable the kdump
    3) Load stress with netperf/stress tool in guest
    4) Trigger a crash by 'sysrq-trigger' and check the vmcore for each vcpu,
       or only trigger one crash with nmi interrupt and check vmcore.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def install_stress_app(session):
        """
        Install stress app in guest.
        """
        stress_path = data_dir.get_deps_dir("stress")
        stress_guest_path = params["tmp_dir"]
        test.log.info("Copy stress package to guest.")
        session.cmd_status_output("mkdir -p %s" % stress_guest_path)
        vm.copy_files_to(stress_path, stress_guest_path)
        session.cmd(params["install_cmd"])

        test.log.info("Install app successed")

    def start_stress(session):
        """
        Load stress in guest.
        """
        error_context.context("Load stress in guest", test.log.info)
        stress_type = params.get("stress_type", "none")

        if stress_type == "none":
            return

        if stress_type == "netperf":
            bg = ""
            bg_stress_test = params.get("run_bgstress")

            bg = utils_misc.InterruptedThread(
                utils_test.run_virt_sub_test,
                (test, params, env),
                {"sub_type": bg_stress_test},
            )
            bg.start()

        if stress_type == "io":
            install_stress_app(session)

            cmd = params.get("start_cmd")
            test.log.info("Launch stress app in guest with command: '%s'", cmd)
            session.sendline(cmd)

        running = utils_misc.wait_for(
            lambda: stress_running(session), timeout=150, step=5
        )
        if not running:
            test.error("Stress isn't running")

        test.log.info("Stress running now")

    def stress_running(session):
        """
        Check stress app really run in background.
        """
        cmd = params.get("kdump_check_cmd")
        status = session.cmd_status(cmd, timeout=120)
        return status == 0

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = float(params.get("login_timeout", 240))
    crash_timeout = float(params.get("crash_timeout", 360))
    kernel_param_cmd = params.get("kernel_param_cmd")
    def_kdump_enable_cmd = "chkconfig kdump on && service kdump restart"
    kdump_enable_cmd = params.get("kdump_enable_cmd", def_kdump_enable_cmd)
    def_crash_kernel_prob_cmd = "grep -q 1 /sys/kernel/kexec_crash_loaded"
    crash_kernel_prob_cmd = params.get(
        "crash_kernel_prob_cmd", def_crash_kernel_prob_cmd
    )

    session = kdump.kdump_enable(
        vm, vm.name, crash_kernel_prob_cmd, kernel_param_cmd, kdump_enable_cmd, timeout
    )

    try:
        start_stress(session)

        error_context.context(
            "Kdump Testing, force the Linux kernel to crash", test.log.info
        )
        crash_cmd = params.get("crash_cmd", "echo c > /proc/sysrq-trigger")
        if crash_cmd == "nmi":
            kdump.crash_test(test, vm, None, crash_cmd, timeout)
        else:
            # trigger crash for each vcpu
            nvcpu = int(params.get("smp", 1))
            for i in range(nvcpu):
                kdump.crash_test(test, vm, i, crash_cmd, timeout)

        kdump.check_vmcore(test, vm, session, crash_timeout)
    finally:
        session.close()
        vm.destroy()
