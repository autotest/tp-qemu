import logging
import time

import aexpect
from virttest import error_context, utils_misc, utils_test

LOG_JOB = logging.getLogger("avocado.test")


class MigrationAfterVmPaused(object):
    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env
        self.login_timeout = int(self.params.get("login_timeout", 360))
        self.mig_timeout = float(self.params.get("mig_timeout", "3600"))
        self.mig_protocol = self.params.get("migration_protocol", "tcp")
        self.mig_cancel_delay = int(self.params.get("mig_cancel") == "yes") * 2
        self.mig_exec_cmd_src = self.params.get("migration_exec_cmd_src")
        self.mig_exec_cmd_dst = self.params.get("migration_exec_cmd_dst")
        if self.mig_exec_cmd_src and "gzip" in self.mig_exec_cmd_src:
            self.mig_exec_file = self.params.get("migration_exec_file", "/var/tmp/exec")
            self.mig_exec_file += "-%s" % utils_misc.generate_random_string(8)
            self.mig_exec_cmd_src = self.mig_exec_cmd_src % self.mig_exec_file
            self.mig_exec_cmd_dst = self.mig_exec_cmd_dst % self.mig_exec_file
        self.offline = self.params.get("offline", "no") == "yes"
        self.check = self.params.get("vmstate_check", "no") == "yes"
        self.living_guest_os = self.params.get("migration_living_guest", "yes") == "yes"
        self.vm = self.env.get_vm(self.params["main_vm"])
        self.test_command = self.params.get("migration_test_command")
        self.background_command = self.params.get("migration_bg_command")
        self.bg_check_command = self.params.get("migration_bg_check_command")
        self.guest_stress_test = self.params.get("guest_stress_test")
        self.ping_pong = self.params.get("ping_pong", 1)
        self.stress_stop_cmd = self.params.get("stress_stop_cmd")

    def stress_test_in_guest(self, timeout=60):
        self.bg = utils_misc.InterruptedThread(
            utils_test.run_virt_sub_test,
            args=(
                self.test,
                self.params,
                self.env,
            ),
            kwargs={"sub_type": self.guest_stress_test},
        )
        self.bg.start()
        LOG_JOB.info("sleep %ds waiting guest stress test start.", timeout)
        time.sleep(timeout)
        if not self.bg.is_alive():
            self.test.fail("Failed to start guest stress test!")

    def stop_stress_test_in_guest(self):
        if self.bg and self.bg.is_alive():
            try:
                self.vm.verify_alive()
                session = self.vm.wait_for_login()
                if self.stress_stop_cmd:
                    LOG_JOB.warning(
                        "Killing background stress process "
                        "with cmd '%s', you would see some "
                        "error message in client test result,"
                        "it's harmless.",
                        self.stress_stop_cmd,
                    )
                    session.cmd(self.stress_stop_cmd)
                    self.bg.join(10)
            except Exception:
                pass

    @error_context.context_aware
    def before_migration(self):
        self.vm.verify_alive()
        if self.living_guest_os:
            session = self.vm.wait_for_login(timeout=self.login_timeout)
            # Get the output of migration_test_command
            self.reference_output = session.cmd_output(self.test_command)
            # Start some process in the background (and leave the session open)
            session.sendline(self.background_command)
            time.sleep(5)
            # Start another session with the guest and make sure the background
            # process is running
            session2 = self.vm.wait_for_login(timeout=self.login_timeout)
            error_context.context(
                "Checking the background command in " "the guest pre migration",
                LOG_JOB.info,
            )
            session2.cmd(self.bg_check_command, timeout=30)
            session2.close()
        else:
            # Just migrate on a living guest OS
            self.test.fail(
                "The guest is not alive," " this test must on a living guest OS."
            )

    @error_context.context_aware
    def after_migration(self):
        LOG_JOB.info("Logging into guest after migration...")
        session2 = self.vm.wait_for_login(timeout=self.login_timeout)
        LOG_JOB.info("Logged in after migration")
        error_context.context(
            "Checking the background command in the guest " "post migration",
            LOG_JOB.info,
        )
        session2.cmd(self.bg_check_command, timeout=30)
        output = session2.cmd_output(self.test_command)
        # Compare output to reference output
        if output != self.reference_output:
            LOG_JOB.info(
                "Command output before migration differs from "
                "command output after migration"
            )
            LOG_JOB.info("Command: %s", self.test_command)
            LOG_JOB.info(
                "Output before: %s",
                utils_misc.format_str_for_message(self.reference_output),
            )
            LOG_JOB.info("Output after: %s", utils_misc.format_str_for_message(output))
            self.test.fail(
                "Command '%s' produced different output "
                "before and after migration" % self.test_command
            )
        # Kill the background process
        if session2 and session2.is_alive():
            bg_kill_cmd = self.params.get("migration_bg_kill_command", None)
            ignore_status = self.params.get("migration_bg_kill_ignore_status", 1)
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
                    LOG_JOB.debug("Remote session not responsive.")

    def ping_pong_migration(self):
        for i in range(int(self.ping_pong)):
            if i % 2 == 0:
                LOG_JOB.info("Round %s ping...", (i / 2))
            else:
                LOG_JOB.info("Round %s pong...", (i / 2))
            self.vm.migrate(
                self.mig_timeout,
                self.mig_protocol,
                self.mig_cancel_delay,
                self.offline,
                self.check,
                migration_exec_cmd_src=self.mig_exec_cmd_src,
                migration_exec_cmd_dst=self.mig_exec_cmd_dst,
                env=self.env,
            )

    def start_test(self):
        self.before_migration()
        if self.guest_stress_test:
            self.stress_test_in_guest()
        self.vm.pause()
        self.ping_pong_migration()
        if self.vm.is_paused():
            self.vm.resume()
        self.after_migration()
        if self.guest_stress_test:
            self.stop_stress_test_in_guest()
        self.vm.reboot()
        self.vm.graceful_shutdown(timeout=60)


def run(test, params, env):
    """
    KVM migration test:
    1) Get a live VM and clone it.
    2) Verify that the source VM supports migration.  If it does, proceed with
       the test.
    3) Do I/O operations load(iozone) in the guest
    4) Stop guest
    5) Send a migration command to the source VM and wait until it's finished.
    6) Kill off the source VM.
    7) Log into the destination VM after the migration is finished.
    8) Compare the output of a reference command executed on the source with
       the output of the same command on the destination machine.
    9) reboot, then shutdown the guest

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    mig_after_vm_paused = MigrationAfterVmPaused(test, params, env)
    mig_after_vm_paused.start_test()
