import os
import time

import aexpect
from avocado.utils import process
from virttest import data_dir, env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    virtio-trace support testing:
    1) Make FIFO per CPU in a host.
    2) reboot guest with virtio-serial device, control path and data path per CPU.
    3) Download trace agent and compile it.
    4) Enable ftrace in the guest.
    5) Run trace agent in the guest.
    6) Open FIFO in a host.
    7) Start to read trace data by ordering from a host
    8) Stop to read trace data by ordering from a host
    9) repeat 7) and 8) with different CPU

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_procs():
        procs = []
        for x in range(0, int(nums_cpu)):
            pipefile = "/tmp/virtio-trace/trace-path-cpu{}.out".format(x)
            proc = aexpect.run_bg("cat %s" % pipefile)
            procs.append(proc)
        return procs

    try:
        nums_cpu = int(params.get("smp", 1))
        serials = params.get("serials", "")
        v_path = "/tmp/virtio-trace/"
        if not os.path.isdir(v_path):
            process.run("mkdir {}".format(v_path))
        for t in ["in", "out"]:
            process.run("mkfifo {}agent-ctl-path.{}".format(v_path, t))
            for x in range(int(nums_cpu)):
                process.run("mkfifo {}trace-path-cpu{}.{}".format(v_path, x, t))

        enable_cmd = "echo 1 > /tmp/virtio-trace/agent-ctl-path.in"
        disable_cmd = "echo 0 > /tmp/virtio-trace/agent-ctl-path.in"
        for x in range(int(nums_cpu)):
            serials += " vs{} ".format(x)
            params["serial_type_vs{}".format(x)] = "virtserialport"
            params["chardev_backend_vs{}".format(x)] = "pipe"
            params["serial_name_vs{}".format(x)] = "trace-path-cpu{}".format(x)
            params["chardev_path_vs{}".format(x)] = "{}trace-path-cpu{}".format(
                v_path, x
            )
        params["serials"] = serials
        params["start_vm"] = "yes"
        env_process.preprocess(test, params, env)
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login()
        status, output = session.cmd_status_output(
            "echo 1 > /sys/kernel/debug/tracing/events/sched/enable"
        )
        if status != 0:
            test.error("Enable ftrace in the guest failed as %s" % output)

        # run trace agnet in vm
        vm.copy_files_to(data_dir.get_deps_dir("virtio-trace"), "/home/")
        session.cmd("cd /home/virtio-trace/ && make")
        session.cmd("sudo /home/virtio-trace/trace-agent &")

        # Host injects read start order to the guest via virtio-serial
        process.run(enable_cmd, shell=True)
        procs = get_procs()
        time.sleep(10)

        # Host injects read stop order to the guest via virtio-serial
        process.run(disable_cmd, shell=True)
        time.sleep(10)
        for index, proc in enumerate(procs):
            if not proc.get_output():
                test.fail(
                    "cpu %s do not have output while it is enabled in host" % index
                )
            proc.close()

        procs = get_procs()
        time.sleep(10)
        for index, proc in enumerate(procs):
            if proc.get_output():
                test.fail("cpu %s still have output after disabled in host" % index)
            proc.close()
    finally:
        process.run("rm -rf {}".format(v_path))
