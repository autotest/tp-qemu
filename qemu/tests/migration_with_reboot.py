import os
import tempfile

from virttest import utils_misc

# Import helper methods from test "migration"
from qemu.tests import migration


def run(test, params, env):
    """
    KVM migration test:
    1) Get a live VM and clone it.
    2) Verify that the source VM supports migration.  If it does, proceed with
            the test.
    3) Reboot the VM
    4) Send a migration command to the source VM and wait until it's finished.
    5) Kill off the source VM.
    6) Log into the destination VM after the migration is finished.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    migration_exec_cmd_src = params.get("migration_exec_cmd_src")
    migration_exec_cmd_dst = params.get("migration_exec_cmd_dst")
    pre_migrate = migration.get_functions(params.get("pre_migrate"), migration.__dict__)
    post_migrate = migration.get_functions(
        params.get("post_migrate"), migration.__dict__
    )
    if migration_exec_cmd_src and "%s" in migration_exec_cmd_src:
        mig_file = os.path.join(
            tempfile.mkdtemp(prefix="migrate", dir=test.workdir), "migrate_file"
        )
        migration_exec_cmd_src %= mig_file
        migration_exec_cmd_dst %= mig_file

    try:
        # Reboot the VM in the background
        bg = utils_misc.InterruptedThread(
            vm.reboot, kwargs={"session": session, "timeout": login_timeout}
        )
        bg.daemon = True
        bg.start()
        try:
            cnt = 0
            while bg.is_alive():
                for func in pre_migrate:
                    func(vm, params, test)
                if cnt % 2 == 0:
                    dest_host = params.get("mig_dest_node")
                else:
                    dest_host = params.get("vm_node")
                vm.migrate(
                    mig_timeout,
                    mig_protocol,
                    mig_cancel_delay,
                    dest_host=dest_host,
                    env=env,
                    migration_exec_cmd_src=migration_exec_cmd_src,
                    migration_exec_cmd_dst=migration_exec_cmd_dst,
                )
                # run some functions after migrate finish.
                for func in post_migrate:
                    func(vm, params, test)
                cnt += 1
        except Exception:
            # If something bad happened in the main thread, ignore exceptions
            # raised in the background thread
            bg.join(suppress_exception=True)
            raise
        else:
            session = bg.join()
    finally:
        session.close()
