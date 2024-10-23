import os
import re
import time

import six
from virttest import qemu_migration, utils_misc

from provider import cpuflags


class Statistic(object):
    """
    Class to display and collect average,
    max and min values of a given data set.
    """

    def __init__(self):
        self._sum = 0
        self._count = 0
        self._max = None
        self._min = None

    def get_average(self):
        if self._count != 0:
            return self._sum / self._count
        else:
            return None

    def get_min(self):
        return self._min

    def get_max(self):
        return self._max

    def record(self, value):
        """
        Record new value to statistic.
        """
        self._count += 1
        self._sum += value
        if not self._max or self._max < value:
            self._max = value
        if not self._min or self._min > value:
            self._min = value


def run(test, params, env):
    """
    KVM migration test:
    1) Get a live VM and clone it.
    2) Verify that the source VM supports migration.  If it does, proceed with
            the test.
    3) Start memory load on vm.
    4) Send a migration command to the source VM and collecting statistic
            of migration speed.
    !) If migration speed is too high migration could be successful and then
            test ends with warning.
    5) Kill off both VMs.
    6) Print statistic of migration.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    mig_timeout = float(params.get("mig_timeout", "10"))
    mig_protocol = params.get("migration_protocol", "tcp")

    install_path = params.get("cpuflags_install_path", "/tmp")

    vm_mem = int(params.get("mem", "512"))

    get_mig_speed = re.compile(r"^transferred ram: (\d+) kbytes$", re.MULTILINE)

    mig_speed = params.get("mig_speed", "1G")
    mig_speed_accuracy = float(params.get("mig_speed_accuracy", "0.2"))
    clonevm = None

    def get_migration_statistic(vm):
        last_transfer_mem = 0
        transfered_mem = 0
        mig_stat = Statistic()
        while vm.monitor.get_migrate_progress() == 0:
            pass
        for _ in range(30):
            o = vm.monitor.info("migrate")
            warning_msg = (
                "Migration already ended. Migration speed is"
                " probably too high and will block vm while"
                " filling its memory."
            )
            fail_msg = (
                "Could not determine the transferred memory from"
                " monitor data: %s" % o
            )
            if isinstance(o, six.string_types):
                if "status: active" not in o:
                    test.error(warning_msg)
                try:
                    transfered_mem = int(get_mig_speed.search(o).groups()[0])
                except (IndexError, ValueError):
                    test.fail(fail_msg)
            else:
                if o.get("status") != "active":
                    test.error(warning_msg)
                try:
                    transfered_mem = o.get("ram").get("transferred") / (1024)
                except (IndexError, ValueError):
                    test.fail(fail_msg)

            real_mig_speed = (transfered_mem - last_transfer_mem) / 1024

            last_transfer_mem = transfered_mem

            test.log.debug("Migration speed: %s MB/s", real_mig_speed)
            mig_stat.record(real_mig_speed)
            time.sleep(1)

        return mig_stat

    try:
        # Reboot the VM in the background
        cpuflags.install_cpuflags_util_on_vm(
            test, vm, install_path, extra_flags="-msse3 -msse2"
        )

        qemu_migration.set_speed(vm, mig_speed)

        cmd = "%s/cpuflags-test --stressmem %d,%d" % (
            os.path.join(install_path, "cpu_flags", "src"),
            vm_mem * 4,
            vm_mem / 2,
        )
        test.log.debug("Sending command: %s", cmd)
        session.sendline(cmd)

        time.sleep(2)

        clonevm = vm.migrate(
            mig_timeout, mig_protocol, not_wait_for_migration=True, env=env
        )

        mig_speed = int(float(utils_misc.normalize_data_size(mig_speed, "M")))

        mig_stat = get_migration_statistic(vm)

        real_speed = mig_stat.get_average()
        ack_speed = mig_speed * mig_speed_accuracy

        test.log.info("Target migration speed: %d MB/s.", mig_speed)
        test.log.info("Average migration speed: %d MB/s", mig_stat.get_average())
        test.log.info("Minimum migration speed: %d MB/s", mig_stat.get_min())
        test.log.info("Maximum migration speed: %d MB/s", mig_stat.get_max())

        test.log.info("Maximum tolerable divergence: %3.1f%%", mig_speed_accuracy * 100)

        if real_speed < mig_speed - ack_speed:
            divergence = (1 - float(real_speed) / float(mig_speed)) * 100
            test.error(
                "Average migration speed (%s MB/s) "
                "is %3.1f%% lower than target (%s MB/s)"
                % (real_speed, divergence, mig_speed)
            )

        if real_speed > mig_speed + ack_speed:
            divergence = (1 - float(mig_speed) / float(real_speed)) * 100
            test.error(
                "Average migration speed (%s MB/s) "
                "is %3.1f%% higher than target (%s MB/s)"
                % (real_speed, divergence, mig_speed)
            )

    finally:
        session.close()
        if clonevm:
            clonevm.destroy(gracefully=False)
        if vm:
            vm.destroy(gracefully=False)
