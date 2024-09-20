import re
import time

from avocado.utils import process
from virttest import error_context, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Enable MULTI_QUEUE feature in guest

    1) Boot up VM(s)
    2) Login guests one by one
    3) Enable MQ for all virtio nics by ethtool -L
    4) Run netperf on guest
    5) check vhost threads on host, if vhost is enable
    6) check cpu affinity if smp == queues

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_virtio_queues_irq(session):
        """
        Return multi queues input irq list
        """
        guest_irq_info = session.cmd_output("cat /proc/interrupts")
        virtio_queues_irq = re.findall(r"(\d+):.*virtio\d+-input.\d", guest_irq_info)
        if not virtio_queues_irq:
            test.error('Could not find any "virtio-input" interrupts')
        return virtio_queues_irq

    def get_cpu_affinity_hint(session, irq_number):
        """
        Return the cpu affinity_hint of irq_number
        """
        cmd_get_cpu_affinity = r"cat /proc/irq/%s/affinity_hint" % irq_number
        return session.cmd_output(cmd_get_cpu_affinity).strip()

    def get_cpu_index(cpu_id):
        """
        Transfer cpu_id to cpu index
        """
        cpu_used_index = []
        for cpu_index in range(int(vm.cpuinfo.smp)):
            if int(cpu_id) & (1 << cpu_index) != 0:
                cpu_used_index.append(cpu_index)
        return cpu_used_index

    def set_cpu_affinity(session):
        """
        Set cpu affinity
        """
        cmd_set_cpu_affinity = r"echo $(cat /proc/irq/%s/affinity_hint)"
        cmd_set_cpu_affinity += " > /proc/irq/%s/smp_affinity"
        irq_list = get_virtio_queues_irq(session)
        for irq in irq_list:
            session.cmd(cmd_set_cpu_affinity % (irq, irq))

    def get_cpu_irq_statistics(session, irq_number, cpu_id=None):
        """
        Get guest interrupts statistics
        """
        online_cpu_number_cmd = r"cat /proc/interrupts | head -n 1 | wc -w"
        cmd = r"cat /proc/interrupts | sed -n '/^\s*%s:/p'" % irq_number
        online_cpu_number = int(session.cmd_output_safe(online_cpu_number_cmd))
        irq_statics = session.cmd_output(cmd)
        irq_statics_list = list(map(int, irq_statics.split()[1:online_cpu_number]))
        if irq_statics_list:
            if cpu_id and cpu_id < len(irq_statics_list):
                return irq_statics_list[cpu_id]
            if not cpu_id:
                return irq_statics_list
        return []

    login_timeout = int(params.get("login_timeout", 360))
    bg_stress_run_flag = params.get("bg_stress_run_flag")
    stress_thread = None
    queues = int(params.get("queues", 1))
    vms = params.get("vms").split()
    if queues == 1:
        test.log.info("No need to enable MQ feature for single queue")
        return
    for vm in vms:
        vm = env.get_vm(vm)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=login_timeout)
        for i, nic in enumerate(vm.virtnet):
            if "virtio" in nic["nic_model"]:
                ifname = utils_net.get_linux_ifname(session, vm.get_mac_address(i))
                session.cmd_output("ethtool -L %s combined %d" % (ifname, queues))
                o = session.cmd_output("ethtool -l %s" % ifname)
                if len(re.findall(r"Combined:\s+%d\s" % queues, o)) != 2:
                    test.error("Fail to enable MQ feature of (%s)" % nic.nic_name)
                test.log.info("MQ feature of (%s) is enabled", nic.nic_name)

        taskset_cpu = params.get("netperf_taskset_cpu")
        if taskset_cpu:
            taskset_cmd = "taskset -c %s " % " ".join(taskset_cpu)
            params["netperf_cmd_prefix"] = taskset_cmd

        check_cpu_affinity = params.get("check_cpu_affinity", "no")
        check_vhost = params.get("check_vhost_threads", "yes")
        if check_cpu_affinity == "yes" and (vm.cpuinfo.smp == queues):
            process.system("systemctl stop irqbalance.service")
            session.cmd("systemctl stop irqbalance.service")
            set_cpu_affinity(session)

        bg_sub_test = params.get("bg_sub_test")
        n_instance = int(params.get("netperf_para_sessions", queues))
        try:
            if bg_sub_test:
                error_context.context(
                    "Run test %s background" % bg_sub_test, test.log.info
                )

                # Set flag, when the sub test really running, will change this
                # flag to True
                stress_thread = utils_misc.InterruptedThread(
                    utils_test.run_virt_sub_test,
                    (test, params, env),
                    {"sub_type": bg_sub_test},
                )
                stress_thread.start()

            if params.get("vhost") == "vhost=on" and check_vhost == "yes":
                vhost_thread_pattern = params.get(
                    "vhost_thread_pattern", r"\w+\s+(\d+)\s.*\[vhost-%s\]"
                )
                vhost_threads = vm.get_vhost_threads(vhost_thread_pattern)
                time.sleep(120)
                error_context.context("Check vhost threads on host", test.log.info)
                top_cmd = (
                    r'top -n 1 -bis | tail -n +7 | grep -E "^ *%s "'
                    % " |^ *".join(map(str, vhost_threads))
                )
                top_info = None
                while session.cmd_status("ps -C netperf") == 0:
                    top_info = process.system_output(
                        top_cmd, ignore_status=True, shell=True
                    ).decode()
                    if top_info:
                        break
                test.log.info(top_info)
                vhost_re = re.compile(r"(0:00.\d{2}).*vhost-\d+[\d|+]")
                invalid_vhost_thread = len(vhost_re.findall(top_info, re.I))
                running_threads = len(top_info.splitlines()) - int(invalid_vhost_thread)

                n_instance = min(n_instance, int(queues), int(vm.cpuinfo.smp))
                if running_threads != n_instance:
                    err_msg = "Run %s netperf session, but %s queues works"
                    test.fail(err_msg % (n_instance, running_threads))

            # check cpu affinity
            if check_cpu_affinity == "yes" and (vm.cpuinfo.smp == queues):
                error_context.context("Check cpu affinity", test.log.info)
                vectors = params.get("vectors", None)
                enable_msix_vectors = params.get("enable_msix_vectors")
                expect_vectors = 2 * int(queues) + 2
                if (not vectors) and (enable_msix_vectors == "yes"):
                    vectors = expect_vectors
                if vectors and (vectors >= expect_vectors) and taskset_cpu:
                    cpu_irq_affinity = {}
                    for irq in get_virtio_queues_irq(session):
                        cpu_id = get_cpu_affinity_hint(session, irq)
                        cpu_index = get_cpu_index(cpu_id)
                        if cpu_index:
                            for cpu in cpu_index:
                                cpu_irq_affinity["%s" % cpu] = irq
                        else:
                            test.error("Can not get the cpu")

                    irq_number = cpu_irq_affinity[taskset_cpu]
                    irq_ori = get_cpu_irq_statistics(session, irq_number)
                    test.log.info("Cpu irq info: %s", irq_ori)
                    time.sleep(10)
                    irq_cur = get_cpu_irq_statistics(session, irq_number)
                    test.log.info("After 10s, cpu irq info: %s", irq_cur)

                    irq_change_list = [x[0] - x[1] for x in zip(irq_cur, irq_ori)]
                    cpu_affinity = irq_change_list.index(max(irq_change_list))
                    if cpu_affinity != int(taskset_cpu):
                        err_msg = "Error, taskset on cpu %s, "
                        err_msg += "but queues use cpu %s"
                        test.fail(err_msg % (taskset_cpu, cpu_affinity))
            if bg_sub_test and stress_thread:
                env[bg_stress_run_flag] = False
                try:
                    stress_thread.join()
                except Exception as e:
                    err_msg = "Run %s test background error!\n "
                    err_msg += "Error Info: '%s'"
                    test.error(err_msg % (bg_sub_test, e))
        finally:
            if session:
                session.close()
            if check_cpu_affinity == "yes" and (vm.cpuinfo.smp == queues):
                process.system("systemctl start irqbalance.service")
