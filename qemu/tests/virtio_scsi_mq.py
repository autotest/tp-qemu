import logging
import re
import time

from autotest.client.shared import error
from autotest.client import local_host

from virttest import utils_misc
from virttest import env_process
from virttest import qemu_qtree


@error.context_aware
def run(test, params, env):
    """
    Qemu multiqueue test for virtio-scsi controller:

    1) Boot up a guest with virtio-scsi device which support multi-queue and
       the vcpu and images number of guest should match the multi-queue number
    2) Check the multi queue option from monitor
    3) Check device init status in guest
    4) Load I/O in all targets
    5) Check the interrupt queues in guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def proc_interrupts_results(results, irqs_pattern):
        results_dict = {}
        cpu_count = 0
        cpu_list = []
        for line in results.splitlines():
            line = line.strip()
            if re.match("CPU0", line):
                cpu_list = re.findall("CPU\d+", line)
                cpu_count = len(cpu_list)
                continue
            if cpu_count > 0:
                irq_key = re.split(":", line)[0]
                if re.findall(irqs_pattern, re.split(":", line)[-1]):
                    results_dict[irq_key] = {}
                    content = line[len(irq_key) + 1:].strip()
                    if len(re.split("\s+", content)) < cpu_count:
                        continue
                    count = 0
                    irq_des = ""
                    for irq_item in re.split("\s+", content):
                        if count < cpu_count:
                            if count == 0:
                                results_dict[irq_key]["count"] = []
                            results_dict[irq_key]["count"].append(irq_item)
                        else:
                            irq_des += " %s" % irq_item
                        count += 1
                    results_dict[irq_key]["irq_des"] = irq_des.strip()
        if not irq_key:
            test.error("Can't find virtio request interrupts from procfs")
        return results_dict, cpu_list

    timeout = float(params.get("login_timeout", 240))
    host_cpu_num = local_host.LocalHost().get_num_cpu()
    while host_cpu_num:
        num_queues = str(host_cpu_num)
        host_cpu_num &= host_cpu_num - 1
    params['smp'] = num_queues
    params['num_queues'] = num_queues
    images_num = int(num_queues)
    extra_image_size = params.get("image_size_extra_images", "512M")
    system_image = params.get("images")
    system_image_drive_format = params.get("system_image_drive_format", "ide")
    params["drive_format_%s" % system_image] = system_image_drive_format

    error.context("Boot up guest with block devcie with num_queues"
                  " is %s and smp is %s" % (num_queues, params['smp']),
                  logging.info)
    for vm in env.get_all_vms():
        if vm.is_alive():
            vm.destroy()
    for extra_image in range(images_num):
        image_tag = "stg%s" % extra_image
        params["images"] += " %s" % image_tag
        params["image_name_%s" % image_tag] = "images/%s" % image_tag
        params["image_size_%s" % image_tag] = extra_image_size
        params["force_create_image_%s" % image_tag] = "yes"
        image_params = params.object_params(image_tag)
        env_process.preprocess_image(test, image_params, image_tag)

    params["start_vm"] = "yes"
    vm = env.get_vm(params["main_vm"])
    env_process.preprocess_vm(test, params, env, vm.name)
    session = vm.wait_for_login(timeout=timeout)

    error.context("Check irqbalance service status", logging.info)
    output = session.cmd_output("systemctl status irqbalance")
    if not re.findall("Active: active", output):
        session.cmd("systemctl start irqbalance")
        output = session.cmd_output("systemctl status irqbalance")
        output = utils_misc.strip_console_codes(output)
        if not re.findall("Active: active", output):
            raise error.TestNAError("Can not start irqbalance inside guest. "
                                    "Skip this test.")

    error.context("Pin vcpus to host cpus", logging.info)
    host_numa_nodes = utils_misc.NumaInfo()
    vcpu_num = 0
    for numa_node_id in host_numa_nodes.nodes:
        numa_node = host_numa_nodes.nodes[numa_node_id]
        for _ in range(len(numa_node.cpus)):
            if vcpu_num >= len(vm.vcpu_threads):
                break
            vcpu_tid = vm.vcpu_threads[vcpu_num]
            logging.debug("pin vcpu thread(%s) to cpu"
                          "(%s)" % (vcpu_tid,
                                    numa_node.pin_cpu(vcpu_tid)))
            vcpu_num += 1

    error.context("Verify num_queues from monitor", logging.info)
    qtree = qemu_qtree.QtreeContainer()
    try:
        qtree.parse_info_qtree(vm.monitor.info('qtree'))
    except AttributeError:
        raise error.TestNAError("Monitor deson't supoort qtree "
                                "skip this test")
    error_msg = "Number of queues mismatch: expect %s"
    error_msg += " report from monitor: %s(%s)"
    scsi_bus_addr = ""
    qtree_num_queues_full = ""
    qtree_num_queues = ""
    for node in qtree.get_nodes():
        if isinstance(node, qemu_qtree.QtreeDev) and (
                node.qtree['type'] == "virtio-scsi-device"):
            qtree_num_queues_full = node.qtree["num_queues"]
            qtree_num_queues = re.search(
                "[0-9]+",
                qtree_num_queues_full).group()
        elif isinstance(node, qemu_qtree.QtreeDev) and node.qtree['type'] == "virtio-scsi-pci":
            scsi_bus_addr = node.qtree['addr']

    if qtree_num_queues != num_queues:
        error_msg = error_msg % (num_queues,
                                 qtree_num_queues,
                                 qtree_num_queues_full)
        raise error.TestFail(error_msg)
    if not scsi_bus_addr:
        raise error.TestError("Didn't find addr from qtree. Please check "
                              "the log.")
    error.context("Check device init status in guest", logging.info)
    irq_check_cmd = params.get("irq_check_cmd", "cat /proc/interrupts")
    output = session.cmd_output(irq_check_cmd)
    irq_name = params.get("irq_regex")
    prev_irq_results, _ = proc_interrupts_results(output, irq_name)
    logging.debug('The info of interrupters before testing:')
    for irq_watch in prev_irq_results.keys():
        logging.debug('%s : %s %s' % (irq_watch, prev_irq_results[irq_watch]['count'], prev_irq_results[irq_watch]['irq_des']))

    error.context("Pin the interrupters to vcpus", logging.info)
    cpu_select = 1
    for irq_id in prev_irq_results.keys():
        bind_cpu_cmd = "echo %s > /proc/irq/%s/smp_affinity" % (hex(cpu_select).replace('0x', ''), irq_id)
        cpu_select = cpu_select << 1
        session.cmd(bind_cpu_cmd)

    error.context("Load I/O in all targets", logging.info)
    get_dev_cmd = params.get("get_dev_cmd", "ls /dev/[svh]d*")
    output = session.cmd_output(get_dev_cmd)
    system_dev = re.findall("[svh]d(\w+)\d+", output)[0]
    dd_timeout = int(re.findall("\d+", extra_image_size)[0])
    fill_cmd = ""
    count = 0
    for dev in re.split("\s+", output):
        if not dev:
            continue
        if not re.findall("[svh]d%s" % system_dev, dev):
            fill_cmd += " dd of=%s if=/dev/urandom bs=1M " % dev
            fill_cmd += "count=%s oflag=direct &" % dd_timeout
            count += 1
    if count != images_num:
        raise error.TestError("Disks are not all show up in system. Output "
                              "from the check command: %s" % output)
    # As Bug 1177332 exists, mq is not supported completely.
    # So don't considering performance currently, dd_timeout is longer.
    dd_timeout = dd_timeout * images_num * 2
    session.cmd(fill_cmd, timeout=dd_timeout)

    dd_thread_num = count
    while dd_thread_num:
        time.sleep(5)
        dd_thread_num = session.cmd_output("pgrep -x dd", timeout=dd_timeout)

    error.context("Check the interrupt queues in guest", logging.info)
    output = session.cmd_output(irq_check_cmd)
    next_irq_results, cpu_list = proc_interrupts_results(output, irq_name)
    logging.debug('The info of interrupters after testing :')
    for irq_watch in next_irq_results.keys():
        logging.debug('%s : %s %s' % (irq_watch, next_irq_results[irq_watch]['count'], next_irq_results[irq_watch]['irq_des']))
    irq_bit_map = 0
    for irq_watch in next_irq_results.keys():
        for index, count in enumerate(next_irq_results[irq_watch]["count"]):
            if (int(count) - int(prev_irq_results[irq_watch]["count"][index])) > 0:
                irq_bit_map |= 2 ** index

    error_msg = ""
    cpu_not_used = []
    for index, cpu in enumerate(cpu_list):
        if 2 ** index & irq_bit_map != 2 ** index:
            cpu_not_used.append(cpu)

    if cpu_not_used:
        logging.debug("Interrupt info from procfs:\n%s" % output)
        error_msg = " ".join(cpu_not_used)
        if len(cpu_not_used) > 1:
            error_msg += " are"
        else:
            error_msg += " is"
        error_msg += " not used during test. Please check debug log for"
        error_msg += " more information."
        raise error.TestFail(error_msg)
