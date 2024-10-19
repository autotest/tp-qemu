import logging

from autotest.client.shared import error
from virttest import remote, virt_vm
from virttest.utils_test.qemu import migration


@error.context_aware
def run(test, params, env):
    """
    KVM multi-host migration with cancel test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.
    steps:
        1) boot vm and login, then load stress in guest
        2) do migration and wait 10 seconds cancel it
        3) reboot vm
        4) do migration again without cancel

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    preprocess_env = params.get("preprocess_env", "yes") == "yes"
    mig_protocol = params.get("mig_protocol", "tcp")
    base_class = migration.MultihostMigration
    if mig_protocol == "fd":
        base_class = migration.MultihostMigrationFd
    if mig_protocol == "exec":
        base_class = migration.MultihostMigrationExec
    if "rdma" in mig_protocol:
        base_class = migration.MultihostMigrationRdma

    class TestMultihostMigrationCancel(base_class):
        def __init__(self, test, params, env):
            super(TestMultihostMigrationCancel, self).__init__(
                test, params, env, preprocess_env
            )
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.vms = params["vms"].split()
            self.vm = params["vms"].split()[0]
            self.id = {
                "src": self.srchost,
                "dst": self.dsthost,
                "type": "cancel_migration",
            }

        def check_guest(self):
            broken_vms = []
            for vm in self.vms:
                try:
                    vm = env.get_vm(vm)
                    stress_kill_cmd = params.get("stress_kill_cmd", "killall -9 stress")
                    error.context("Kill load and reboot vm.", logging.info)
                    session = vm.wait_for_login(timeout=self.login_timeout)
                    session.sendline(stress_kill_cmd)
                    vm.reboot()
                except (remote.LoginError, virt_vm.VMError):
                    broken_vms.append(vm)
            if broken_vms:
                raise error.TestError(
                    "VMs %s should work on src"
                    " host after canceling of"
                    " migration." % (broken_vms)
                )

        def migration_scenario(self):
            @error.context_aware
            def worker(mig_data):
                vm = mig_data.vms[0]
                stress_cmd = params.get("stress_cmd")

                session = vm.wait_for_login(timeout=self.login_timeout)

                error.context("Load stress in guest before migration.", logging.info)
                logging.debug("Sending command: %s", stress_cmd)
                session.sendline(stress_cmd)

            self.migrate_wait([self.vm], self.srchost, self.dsthost, worker)

            if params.get("hostid") == self.master_id():
                self.check_guest()

            self._hosts_barrier(
                self.hosts, self.id, "wait_for_cancel", self.login_timeout
            )

            params["cancel_delay"] = None
            error.context("Do migration again", logging.info)
            self.migrate_wait([self.vm], self.srchost, self.dsthost)

    mig = TestMultihostMigrationCancel(test, params, env)
    mig.run()
