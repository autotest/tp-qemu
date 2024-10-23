"""
virtio_mem useful functions.

This module is meant to reduce code size on virtio_mem cases avoiding
repeat functions implementation.
"""

import re

from avocado.utils.wait import wait_for
from virttest import error_context
from virttest.utils_misc import normalize_data_size


def get_node_plugged_size(node, vm, test):
    """
    get numa node plugged size from HMP info command
    :param node: numa node number
    :param vm: vm object
    :param test: qemu test object
    """
    output = vm.monitor.info("numa").splitlines()
    for numa_info in output:
        if "node " + str(node) + " plugged: " in numa_info:
            node_plugged = (
                numa_info.split("node " + str(node) + " plugged: ").pop().split(" ")[0]
            )
            if node_plugged is None:
                test.fail("Error, unexpected numa node plugged info at node %d" % node)
            error_context.context(
                "node %d plugged: %s" % (node, node_plugged), test.log.debug
            )
    return int(node_plugged)


def get_node_size(node, vm, test):
    """
    get numa node size from HMP info command
    :param node: numa node number
    :param vm: vm object
    :param test: qemu test object
    """
    output = vm.monitor.info("numa").splitlines()
    for numa_info in output:
        if "node " + str(node) + " size: " in numa_info:
            node_size = (
                numa_info.split("node " + str(node) + " size: ").pop().split(" ")[0]
            )
            if node_size is None:
                test.fail("Error, unexpected numa node size info at node %d" % node)
            error_context.context(
                "node %d size: %s" % (node, node_size), test.log.debug
            )
    return int(node_size)


def check_numa_plugged_mem(node_id, requested_size, threshold, vm, test):
    """
    Compares numa node plugged memory with memory requested size from virtio_mem device
    allowing a little difference defined by mem_limit
    :param node_id: id of the node to be checked
    :param requested_size: requested-size configuration parameter
    :param threshold: memory threshold
    :param vm: vm object
    :param test: qemu test object
    """
    node_plugged_memory = get_node_plugged_size(node_id, vm, test)
    node_size = get_node_size(node_id, vm, test)
    mem_limit = (node_size - node_plugged_memory) * threshold
    requested_size = int(float(normalize_data_size(requested_size, "M")))
    error_context.context(
        "requested_size: %d, node_plugged_memory: %d"
        % (requested_size, node_plugged_memory),
        test.log.debug,
    )
    if node_plugged_memory != requested_size and float(node_plugged_memory) > mem_limit:
        test.fail(
            "Error, requested-size: %d does not match with plugged memory: %d."
            % (requested_size, node_plugged_memory)
        )


def check_memory_devices(device_id, cfg_req_size_param, threshold, vm, test):
    """
    Compares virtio_mem device memory size with the memory requested size
    allowing a little difference defined by mem_limit
    :param device_id: id of the device to be checked
    :param cfg_req_size_param: requested-size configuration parameter
    :param threshold: memory threshold
    :param vm: vm object
    :param test: qemu test object
    """
    output = vm.monitor.info("memory-devices")
    for dev_info in output:
        data = dev_info.get("data")
        id = data.get("id")
        if device_id == id:
            size = int(data.get("size"))
            node = int(data.get("node"))
            requested_size = int(data.get("requested-size"))
            error_context.context(
                "node: %d, id: %s, size: %d and requested-size: %d"
                % (node, id, size, requested_size),
                test.log.debug,
            )
            node_size = float(get_node_size(node, vm, test))
            normalized_size = float(normalize_data_size(str(size), "M"))
            mem_limit = (node_size - normalized_size) * threshold
            if size != requested_size and normalized_size > mem_limit:
                test.fail(
                    "Error, size: %d and requested-size: %d are not equals."
                    % (size, requested_size)
                )
            if cfg_req_size_param != "0":
                req_size_param = int(
                    float(normalize_data_size(cfg_req_size_param, "B"))
                )
            else:
                req_size_param = int(cfg_req_size_param)
            error_context.context("req_size_param: %d" % req_size_param, test.log.debug)
            if requested_size != req_size_param:
                test.fail(
                    "Error, requested-size: %d is not the specified in the cfg: %d."
                    % (requested_size, req_size_param)
                )


def count_memslots(vm, mem_object_id):
    """
    Returns the number of memslots assigned to the current virtio-mem device
    :param vm: the VM object
    :param mem_object_id: the ID of the memory object device
    """
    output = vm.monitor.info("mtree")
    return len(set(re.findall(r"(memslot.+%s)" % mem_object_id, output, re.MULTILINE)))


def validate_memslots(expected_memslots, test, vm, mem_object_id, timeout=10):
    """
    Validates the total number of memslots is the expected one
    :param expected_memslots: the expected number of memslots
    :param test: QEMU test object
    :param vm: the VM object
    :param mem_object_id: the ID of the memory object device
    """
    if not wait_for(
        lambda: count_memslots(vm, mem_object_id) == expected_memslots, timeout
    ):
        test.fail("The number of memslots is not %d" % expected_memslots)
