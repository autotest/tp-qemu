import re
import time

from virttest import env_process, error_context, qemu_qtree, utils_misc, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Qemu multiqueue test for virtio-scsi controller:

    1) Boot up a guest with virtio-scsi device which support multi-queue and
       the vcpu and images number of guest should match the multi-queue number.
    2) Pin the vcpus to the host cpus.
    3) Check the multi queue option from monitor.
    4) Check device init status in guest
    5) Pin the interrupts to the vcpus.
    6) Load I/O in all targets.
    7) Check the interrupt queues in guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_mapping_interrupts2vcpus(irqs, pattern):
        """Get the mapping of between virtio interrupts and vcpus."""
        regex = r"(\d+):(\s+(\d+\s+){%d})\s+.+\s%s\s" % (
            len(re.findall(r"\s+CPU\d+", irqs, re.M)),
            pattern,
        )
        return {f[0]: {"count": f[1].split()} for f in re.findall(regex, irqs, re.M)}

    def create_data_images():
        """Create date image objects."""
        for extra_image in range(images_num):
            image_tag = "stg%s" % extra_image
            params["images"] += " %s" % image_tag
            params["image_name_%s" % image_tag] = "images/%s" % image_tag
            params["image_size_%s" % image_tag] = extra_image_size
            params["force_create_image_%s" % image_tag] = "yes"
            image_params = params.object_params(image_tag)
            env_process.preprocess_image(test, image_params, image_tag)

    def check_irqbalance_status():
        """Check the status of irqbalance service."""
        error_context.context("Check irqbalance service status.", test.log.info)
        return re.findall("Active: active", session.cmd_output(status_cmd))

    def start_irqbalance_service():
        """Start the irqbalance service."""
        error_context.context("Start the irqbalance service.", test.log.info)
        session.cmd("systemctl start irqbalance")
        output = utils_misc.strip_console_codes(session.cmd_output(status_cmd))
        if not re.findall("Active: active", output):
            test.cancel("Can not start irqbalance inside guest.Skip this test.")

    def pin_vcpus2host_cpus():
        """Pint the vcpus to the host cpus."""
        error_context.context("Pin vcpus to host cpus.", test.log.info)
        host_numa_nodes = utils_misc.NumaInfo()
        vcpu_num = 0
        for numa_node_id in host_numa_nodes.nodes:
            numa_node = host_numa_nodes.nodes[numa_node_id]
            for _ in range(len(numa_node.cpus)):
                if vcpu_num >= len(vm.vcpu_threads):
                    break
                vcpu_tid = vm.vcpu_threads[vcpu_num]
                test.log.debug(
                    "pin vcpu thread(%s) to cpu(%s)",
                    vcpu_tid,
                    numa_node.pin_cpu(vcpu_tid),
                )
                vcpu_num += 1

    def verify_num_queues():
        """Verify the number of queues."""
        error_context.context("Verify num_queues from monitor.", test.log.info)
        qtree = qemu_qtree.QtreeContainer()
        try:
            qtree.parse_info_qtree(vm.monitor.info("qtree"))
        except AttributeError:
            test.cancel("Monitor deson't supoort qtree skip this test")
        error_msg = "Number of queues mismatch: expect %s report from monitor: %s(%s)"
        scsi_bus_addr = ""
        qtree_num_queues_full = ""
        qtree_num_queues = ""
        for node in qtree.get_nodes():
            type = node.qtree["type"]
            if isinstance(node, qemu_qtree.QtreeDev) and (type == "virtio-scsi-device"):
                qtree_num_queues_full = node.qtree["num_queues"]
                qtree_num_queues = re.search("[0-9]+", qtree_num_queues_full).group()
            elif (isinstance(node, qemu_qtree.QtreeDev)) and (
                type == "virtio-scsi-pci"
            ):
                scsi_bus_addr = node.qtree["addr"]

        if qtree_num_queues != num_queues:
            error_msg = error_msg % (
                num_queues,
                qtree_num_queues,
                qtree_num_queues_full,
            )
            test.fail(error_msg)
        if not scsi_bus_addr:
            test.error("Didn't find addr from qtree. Please check the log.")

    def check_interrupts():
        """Check the interrupt queues in guest."""
        error_context.context("Check the interrupt queues in guest.", test.log.info)
        return session.cmd_output(irq_check_cmd)

    def check_interrupts2vcpus(irq_map):
        """Check the status of interrupters to vcpus."""
        error_context.context(
            "Check the status of interrupters to vcpus.", test.log.info
        )
        cpu_selects = {}
        cpu_select = 1
        for _ in range(int(num_queues)):
            val = ",".join(
                [
                    _[::-1]
                    for _ in re.findall(r"\w{8}|\w+", format(cpu_select, "x")[::-1])
                ][::-1]
            )
            cpu_selects[val] = format(cpu_select, "b").count("0")
            cpu_select = cpu_select << 1
        irqs_id_reset = []
        for irq_id in irq_map.keys():
            cmd = "cat /proc/irq/%s/smp_affinity" % irq_id
            cpu_selected = re.sub(
                r"(^[0+,?0+]+)|(,)", "", session.cmd_output(cmd)
            ).strip()
            if cpu_selected not in cpu_selects:
                irqs_id_reset.append(irq_id)
            else:
                cpu_irq_map[irq_id] = cpu_selects[cpu_selected]
                del cpu_selects[cpu_selected]
        return irqs_id_reset, cpu_selects

    def pin_interrupts2vcpus(irqs_id_reset, cpu_selects):
        """Pint the interrupts to vcpus."""
        bind_cpu_cmd = []
        for irq_id, cpu_select in zip(irqs_id_reset, cpu_selects):
            bind_cpu_cmd.append(
                "echo %s > /proc/irq/%s/smp_affinity" % (cpu_select, irq_id)
            )
            cpu_irq_map[irq_id] = cpu_selects[cpu_select]
        if bind_cpu_cmd:
            error_context.context("Pin interrupters to vcpus", test.log.info)
            session.cmd(" && ".join(bind_cpu_cmd))
        return cpu_irq_map

    def _get_data_disks(session):
        """Get the data disks."""
        output = session.cmd_output(params.get("get_dev_cmd", "ls /dev/[svh]d*"))
        system_dev = re.search(r"/dev/([svh]d\w+)(?=\d+)", output, re.M).group(1)
        return (dev for dev in output.split() if system_dev not in dev)

    def check_io_status(timeout):
        """Check the status of I/O."""
        chk_session = vm.wait_for_login(timeout=360)
        while int(chk_session.cmd_output("pgrep -lx dd | wc -l", timeout)):
            time.sleep(5)
        chk_session.close()

    def load_io_data_disks():
        """Load I/O on data disks."""
        error_context.context("Load I/O in all targets", test.log.info)
        dd_session = vm.wait_for_login(timeout=360)
        dd_timeout = int(re.findall(r"\d+", extra_image_size)[0])
        cmd = "dd of=%s if=/dev/urandom bs=1M count=%s oflag=direct &"
        cmds = [cmd % (dev, dd_timeout) for dev in _get_data_disks(dd_session)]
        if len(cmds) != images_num:
            test.error(
                "Disks are not all show up in system, only %s disks." % len(cmds)
            )

        # As Bug 1177332 exists, mq is not supported completely.
        # So don't considering performance currently, dd_timeout is longer.
        dd_session.cmd(" ".join(cmds), dd_timeout * images_num * 2)
        check_io_status(dd_timeout)
        dd_session.close()

    def compare_interrupts(prev_irqs, cur_irqs):
        """Compare the interrupts between after and before IO."""
        cpu_not_used = []
        diff_interrupts = {}
        for irq in prev_irqs.keys():
            cpu = int(cpu_irq_map[irq])
            diff_val = int(cur_irqs[irq]["count"][cpu]) - int(
                prev_irqs[irq]["count"][cpu]
            )
            if diff_val == 0:
                cpu_not_used.append("CPU%s" % cpu)
            else:
                diff_interrupts[cpu] = diff_val
        test.log.debug("The changed number of interrupts:")
        for k, v in sorted(diff_interrupts.items()):
            test.log.debug("  CPU%s: %d", k, v)
        if cpu_not_used:
            cpus = " ".join(cpu_not_used)
            error_msg = (
                "%s are not used during test. "
                "Please check debug log for more information."
            )
            test.fail(error_msg % cpus)

    def wmi_facility_test(session):
        driver_name = params["driver_name"]
        wmi_check_cmd = params["wmi_check_cmd"]
        pattern = params["pattern"]
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name, timeout
        )
        wmi_check_cmd = utils_misc.set_winutils_letter(session, wmi_check_cmd)
        error_context.context("Run wmi check in guest.", test.log.info)
        output = session.cmd_output(wmi_check_cmd)
        queue_num = re.findall(pattern, output, re.M)
        try:
            if not queue_num or queue_num[0] != num_queues:
                test.fail(
                    "The queue_num from guest is not match with expected.\n"
                    "queue_num from guest is %s, expected is %s"
                    % (queue_num, num_queues)
                )
        finally:
            session.close()

    cpu_irq_map = {}
    timeout = float(params.get("login_timeout", 240))
    num_queues = params["vcpu_maxcpus"]
    params["smp"] = num_queues
    params["num_queues"] = num_queues
    images_num = int(num_queues)
    extra_image_size = params.get("image_size_extra_images", "512M")
    system_image = params.get("images")
    system_image_drive_format = params.get("system_image_drive_format", "virtio")
    params["drive_format_%s" % system_image] = system_image_drive_format
    irq_check_cmd = params.get("irq_check_cmd", "cat /proc/interrupts")
    irq_name = params.get("irq_regex")
    status_cmd = "systemctl status irqbalance"

    error_context.context(
        "Boot up guest with block devcie with num_queues"
        " is %s and smp is %s" % (num_queues, params["smp"]),
        test.log.info,
    )
    for vm in env.get_all_vms():
        if vm.is_alive():
            vm.destroy()
    create_data_images()
    params["start_vm"] = "yes"
    vm = env.get_vm(params["main_vm"])
    env_process.preprocess_vm(test, params, env, vm.name)
    session = vm.wait_for_login(timeout=timeout)
    if params["os_type"] == "windows":
        wmi_facility_test(session)
        return
    if not check_irqbalance_status():
        start_irqbalance_service()
    pin_vcpus2host_cpus()
    verify_num_queues()
    prev_irqs = check_interrupts()
    prev_mapping = get_mapping_interrupts2vcpus(prev_irqs, irq_name)
    pin_interrupts2vcpus(*check_interrupts2vcpus(prev_mapping))
    load_io_data_disks()
    cur_irqs = check_interrupts()
    cur_mapping = get_mapping_interrupts2vcpus(cur_irqs, irq_name)
    compare_interrupts(prev_mapping, cur_mapping)
