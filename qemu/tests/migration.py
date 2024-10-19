import ast
import re
import time
import types

import aexpect
from virttest import (
    error_context,
    qemu_migration,
    qemu_monitor,  # For MonitorNotSupportedMigCapError
    utils_misc,
    utils_package,
    utils_test,
)


# Define get_function-functions as global to allow importing from other tests
def get_functions(func_names, locals_dict):
    """
    Find sub function(s) in this function with the given name(s).
    """
    if not func_names:
        return []
    funcs = []
    for f in func_names.split():
        f = locals_dict.get(f)
        if isinstance(f, types.FunctionType):
            funcs.append(f)
    return funcs


def mig_set_speed(vm, params, test):
    mig_speed = params.get("mig_speed", "1G")
    return qemu_migration.set_speed(vm, mig_speed)


def check_dma(vm, params, test):
    dmesg_pattern = params.get("dmesg_pattern", "ata.*?configured for PIO")
    dma_pattern = params.get("dma_pattern", r"DMA.*?\(\?\)$")
    pio_pattern = params.get("pio_pattern", r"PIO.*?pio\d+\s+$")
    hdparm_cmd = params.get("hdparm_cmd", "i=`ls /dev/[shv]da` ; hdparm -I $i")
    session_dma = vm.wait_for_login()
    hdparm_output = session_dma.cmd_output(hdparm_cmd)
    failed_msg = ""
    if not re.search(dma_pattern, hdparm_output, re.M):
        failed_msg += "Failed in DMA check from hdparm output.\n"
    if not re.search(pio_pattern, hdparm_output, re.M):
        failed_msg += "Failed in PIO check from hdparm output.\n"

    if failed_msg:
        failed_msg += "hdparm output is: %s\n" % hdparm_output

    dmesg = session_dma.cmd_output("dmesg")
    if not re.search(dmesg_pattern, dmesg):
        failed_msg += "Failed in dmesg check.\n"
        failed_msg += " dmesg from guest is: %s\n" % dmesg

    if failed_msg:
        test.fail(failed_msg)


@error_context.context_aware
def run(test, params, env):
    """
    KVM migration test:
    1) Get a live VM and clone it.
    2) Verify that the source VM supports migration.  If it does, proceed with
            the test.
    3) Send a migration command to the source VM and wait until it's finished.
    4) Kill off the source VM.
    3) Log into the destination VM after the migration is finished.
    4) Compare the output of a reference command executed on the source with
            the output of the same command on the destination machine.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def guest_stress_start(guest_stress_test):
        """
        Start a stress test in guest, Could be 'iozone', 'dd', 'stress'

        :param type: type of stress test.
        """
        from generic.tests import autotest_control

        timeout = 0

        if guest_stress_test == "autotest":
            test_type = params.get("test_type")
            func = autotest_control.run
            new_params = params.copy()
            new_params["test_control_file"] = "%s.control" % test_type

            args = (test, new_params, env)
            timeout = 60
        elif guest_stress_test == "dd":
            vm = env.get_vm(env, params.get("main_vm"))
            vm.verify_alive()
            session = vm.wait_for_login(timeout=login_timeout)
            func = session.cmd_output
            args = (
                "for((;;)) do dd if=/dev/zero of=/tmp/test bs=5M "
                "count=100; rm -f /tmp/test; done",
                login_timeout,
                test.log.info,
            )

        test.log.info("Start %s test in guest", guest_stress_test)
        bg = utils_test.BackgroundTest(func, args)  # pylint: disable=E0606
        params["guest_stress_test_pid"] = bg
        bg.start()
        if timeout:
            test.log.info("sleep %ds waiting guest test start.", timeout)
            time.sleep(timeout)
        if not bg.is_alive():
            test.fail("Failed to start guest test!")

    def guest_stress_deamon():
        """
        This deamon will keep watch the status of stress in guest. If the stress
        program is finished before migration this will restart it.
        """
        while True:
            bg = params.get("guest_stress_test_pid")
            action = params.get("action")
            if action == "run":
                test.log.debug("Check if guest stress is still running")
                guest_stress_test = params.get("guest_stress_test")
                if bg and not bg.is_alive():
                    test.log.debug("Stress process finished, restart it")
                    guest_stress_start(guest_stress_test)
                    time.sleep(30)
                else:
                    test.log.debug("Stress still on")
            else:
                if bg and bg.is_alive():
                    try:
                        stress_stop_cmd = params.get("stress_stop_cmd")
                        vm = env.get_vm(env, params.get("main_vm"))
                        vm.verify_alive()
                        session = vm.wait_for_login()
                        if stress_stop_cmd:
                            test.log.warning(
                                "Killing background stress process "
                                "with cmd '%s', you would see some "
                                "error message in client test result,"
                                "it's harmless.",
                                stress_stop_cmd,
                            )
                            session.cmd(stress_stop_cmd)
                        bg.join(10)
                    except Exception:
                        pass
                break
            time.sleep(10)

    login_timeout = int(params.get("login_timeout", 360))
    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    mig_exec_cmd_src = params.get("migration_exec_cmd_src")
    mig_exec_cmd_dst = params.get("migration_exec_cmd_dst")
    if mig_exec_cmd_src and "gzip" in mig_exec_cmd_src:
        mig_exec_file = params.get("migration_exec_file", "/var/tmp/exec")
        mig_exec_file += "-%s" % utils_misc.generate_random_string(8)
        mig_exec_cmd_src = mig_exec_cmd_src % mig_exec_file
        mig_exec_cmd_dst = mig_exec_cmd_dst % mig_exec_file
    offline = params.get("offline", "no") == "yes"
    check = params.get("vmstate_check", "no") == "yes"
    living_guest_os = params.get("migration_living_guest", "yes") == "yes"
    deamon_thread = None

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    if living_guest_os:
        session = vm.wait_for_login(timeout=login_timeout)

        # Get the output of migration_test_command
        test_command = params.get("migration_test_command")
        reference_output = session.cmd_output(test_command)

        # Start some process in the background (and leave the session open)
        background_command = params.get("migration_bg_command", "")

        # check whether tcpdump is installed
        if "tcpdump" in background_command:
            if not utils_package.package_install("tcpdump", session):
                test.cancel("Please install tcpdump to proceed")
        session.sendline(background_command)
        time.sleep(5)

        # Start another session with the guest and make sure the background
        # process is running
        session2 = vm.wait_for_login(timeout=login_timeout)

        try:
            check_command = params.get("migration_bg_check_command", "")
            error_context.context(
                "Checking the background command in the " "guest pre migration",
                test.log.info,
            )
            if session2.cmd_status(check_command, timeout=30) != 0:
                test.error("migration bg check command failed")
            session2.close()

            # Start stress test in guest.
            guest_stress_test = params.get("guest_stress_test")
            if guest_stress_test:
                guest_stress_start(guest_stress_test)
                params["action"] = "run"
                deamon_thread = utils_test.BackgroundTest(guest_stress_deamon, ())
                deamon_thread.start()

            capabilities = ast.literal_eval(params.get("migrate_capabilities", "{}"))
            inner_funcs = ast.literal_eval(params.get("migrate_inner_funcs", "[]"))
            mig_parameters = ast.literal_eval(params.get("migrate_parameters", "None"))
            target_mig_parameters = params.get("target_migrate_parameters", "None")
            target_mig_parameters = ast.literal_eval(target_mig_parameters)
            migrate_parameters = (mig_parameters, target_mig_parameters)
            pre_migrate = get_functions(params.get("pre_migrate"), globals())

            # Migrate the VM
            ping_pong = params.get("ping_pong", 1)
            for i in range(int(ping_pong)):
                # run some functions before migrate start
                for func in pre_migrate:
                    func(vm, params, test)
                if i % 2 == 0:
                    test.log.info("Round %s ping...", str(i / 2))
                else:
                    test.log.info("Round %s pong...", str(i / 2))
                try:
                    vm.migrate(
                        mig_timeout,
                        mig_protocol,
                        mig_cancel_delay,
                        offline,
                        check,
                        migration_exec_cmd_src=mig_exec_cmd_src,
                        migration_exec_cmd_dst=mig_exec_cmd_dst,
                        migrate_capabilities=capabilities,
                        mig_inner_funcs=inner_funcs,
                        env=env,
                        migrate_parameters=migrate_parameters,
                    )
                except qemu_monitor.MonitorNotSupportedMigCapError as e:
                    test.cancel("Unable to access capability: %s" % e)
                except:
                    raise

            # Set deamon thread action to stop after migrate
            params["action"] = "stop"

            # run some functions after migrate finish.
            post_migrate = get_functions(params.get("post_migrate"), globals())
            for func in post_migrate:
                func(vm, params, test)

            # Log into the guest again
            test.log.info("Logging into guest after migration...")
            session2 = vm.wait_for_login(timeout=30)
            test.log.info("Logged in after migration")

            # Make sure the background process is still running
            error_context.context(
                "Checking the background command in the " "guest post migration",
                test.log.info,
            )
            session2.cmd(check_command, timeout=30)

            # Get the output of migration_test_command
            output = session2.cmd_output(test_command)

            # Compare output to reference output
            if output != reference_output:
                test.log.info(
                    "Command output before migration differs from "
                    "command output after migration"
                )
                test.log.info("Command: %s", test_command)
                test.log.info(
                    "Output before: %s",
                    utils_misc.format_str_for_message(reference_output),
                )
                test.log.info(
                    "Output after: %s", utils_misc.format_str_for_message(output)
                )
                test.fail(
                    "Command '%s' produced different output "
                    "before and after migration" % test_command
                )

        finally:
            # Kill the background process
            if session2 and session2.is_alive():
                bg_kill_cmd = params.get("migration_bg_kill_command", None)
                ignore_status = params.get("migration_bg_kill_ignore_status", 1)
                if bg_kill_cmd is not None:
                    try:
                        session2.cmd(bg_kill_cmd)
                    except aexpect.ShellCmdError as details:
                        # If the migration_bg_kill_command rc differs from
                        # ignore_status, it means the migration_bg_command is
                        # no longer alive. Let's ignore the failure here if
                        # that is the case.
                        if not int(details.status) == int(ignore_status):
                            raise
                    except aexpect.ShellTimeoutError:
                        test.log.debug(
                            "Remote session not responsive, " "shutting down VM %s",
                            vm.name,
                        )
                        vm.destroy(gracefully=True)
            if deamon_thread is not None:
                # Set deamon thread action to stop after migrate
                params["action"] = "stop"
                deamon_thread.join()
    else:
        # Just migrate without depending on a living guest OS
        vm.migrate(
            mig_timeout,
            mig_protocol,
            mig_cancel_delay,
            offline,
            check,
            migration_exec_cmd_src=mig_exec_cmd_src,
            migration_exec_cmd_dst=mig_exec_cmd_dst,
            migrate_parameters=migrate_parameters,
        )
