"""
Module for IO throttling relevant interfaces.
"""
import logging

from virttest.qemu_monitor import QMPCmdError

from virttest.qemu_devices.qdevices import QThrottleGroup


class ThrottleError(Exception):
    """ General Throttle error"""
    pass


class ThrottleGroupManager(object):
    """
    General operations for Throttle group.
    """

    def __init__(self, vm):
        """
        :param vm:VM object.
        """
        self._vm = vm
        self._monitor = vm.monitor

    def set_monitor(self, monitor):
        """
        Set the default monitor.

        :param monitor: QMPMonitor monitor.
        """
        self._monitor = monitor

    # object-add
    def add_throttle_group(self, group_id, props):
        """
        hot-plug throttle group object.

        :param group_id: Throttle group id.
        :param props: Dict of throttle group properties.
        :return: QThrottleGroup object.
        """

        dev = QThrottleGroup(group_id, props)
        try:
            self._vm.devices.simple_hotplug(dev, self._monitor)
            return dev
        except QMPCmdError:
            self._vm.devices.remove(dev)

    # object-del
    def delete_throttle_group(self, group_id):
        """
        hot-unplug throttle group object.

        :param group_id: Throttle group id.
        :return: True for succeed.
        """

        dev = self.get_throttle_group(group_id)
        if dev:
            self._vm.devices.simple_unplug(dev, self._monitor)
            return True
        else:
            logging.error("Can not find throttle group")
            return False

    def get_throttle_group(self, group_id):
        """
        Search throttle group in vm devices.

        :param group_id: Throttle group id.
        :return: QThrottleGroup object. None for not found or something wrong.
        """

        devs = self._vm.devices.get_by_qid(group_id)
        if len(devs) != 1:
            logging.error("There are %d devices %s" % (len(devs), group_id))
            return None
        return devs[0]

    def get_throttle_group_props(self, group_id):
        """
        Get the attributes of throttle group object via qmp command.

        :param group_id: Throttle group id.
        :return: Dictionary of throttle group properties.
        """

        try:
            return self._monitor.qom_get(group_id, "limits")
        except QMPCmdError as e:
            logging.error("qom_get %s %s " % (group_id, str(e)))

    # qom-set
    def update_throttle_group(self, group_id, props):
        """
        Update throttle group properties.

        :param group_id: Throttle group id.
        :param props: New throttle group properties.
        """

        dev = self.get_throttle_group(group_id)
        if dev:
            tmp_dev = QThrottleGroup(group_id, props)
            self._monitor.qom_set(group_id, "limits", tmp_dev.raw_limits)
            dev.raw_limits = tmp_dev.raw_limits
        else:
            raise ThrottleError("Can not find throttle group")

    # x-blockdev-reopen
    def change_throttle_group(self, image, group_id):
        """
        Change image to other throttle group.

        :param image: Image name of disk.
        :param group_id: New throttle group id.
        """

        node_name = "drive_" + image

        throttle_blockdev = self._vm.devices.get_by_qid(node_name)[0]

        old_throttle_group = self._vm.devices.get_by_qid(
            throttle_blockdev.get_param("throttle-group"))[0]
        new_throttle_group = self._vm.devices.get_by_qid(group_id)[0]
        file = throttle_blockdev.get_param("file")
        args = {"driver": "throttle", "node-name": node_name, "file": file,
                "throttle-group": group_id}
        self._monitor.x_blockdev_reopen(args)

        for bus in old_throttle_group.child_bus:
            bus.remove(throttle_blockdev)

        throttle_blockdev.parent_bus = (
            {"busid": group_id}, {"type": "ThrottleGroup"})
        throttle_blockdev.set_param("throttle-group", group_id)

        for bus in new_throttle_group.child_bus:
            bus.insert(throttle_blockdev)
