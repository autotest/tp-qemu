import time

from avocado.utils import process


def run(test, params, env):
    """
    Check unhalt vcpu of guest.
    1) Use qemu-img create any image which can not boot.
    2) Start vm with the image created by step 1
    3) Use ps get qemu-kvm process %cpu, if greater than 90%, report fial.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    pid = vm.get_pid()
    if not pid:
        test.error("Could not get QEMU's PID")

    sleep_time = params.get("sleep_time", 60)
    time.sleep(sleep_time)

    cpu_get_usage_cmd = params["cpu_get_usage_cmd"]
    cpu_get_usage_cmd = cpu_get_usage_cmd % pid
    cpu_usage = process.system_output(cpu_get_usage_cmd, shell=True)

    try:
        cpu_usage = float(cpu_usage)
    except ValueError as detail:
        test.error(
            "Could not get correct cpu usage value with cmd"
            " '%s', detail: '%s'" % (cpu_get_usage_cmd, detail)
        )

    test.log.info("Guest's reported CPU usage: %s", cpu_usage)
    if cpu_usage >= 90:
        test.fail("Guest have unhalt vcpu.")

    test.log.info("Guest vcpu work normally")
