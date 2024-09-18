"""
cdrom event check utility functions.

This module is meant to reduce code size by performing extra event check
procedures. Generally, functions here should provide layers of extra event
check for cdrom related operations.
"""

import logging

from avocado import fail_on
from virttest import utils_misc
from virttest.qemu_capabilities import Flags

LOG_JOB = logging.getLogger("avocado.test")


class CDRomError(Exception):
    pass


class CDRomStatusError(CDRomError):
    def __init__(self, device, operation, status):
        self.device = device
        self.operation = operation
        self.status = status

    def __str__(self):
        return "Device %s tray-open status: %s after %s" % (
            self.device,
            self.status,
            self.operation,
        )


class CDRomEventCountError(CDRomError):
    def __init__(self, device, operation, event, count):
        self.device = device
        self.operation = operation
        self.event = event
        self.count = count

    def __str__(self):
        return "%d '%s' received after %s %s" % (
            self.count,
            self.event,
            self.operation,
            self.device,
        )


def is_device_tray_opened(vm, device_id):
    """
    check whether specified block device tray is open or not.
    Return True, if device is opened, else False.

    : param vm: VM object
    : device_id: block device identifier
    """
    blocks_info = vm.monitor.info("block")

    if vm.check_capability(Flags.BLOCKDEV):
        device_id = vm.devices.get_qdev_by_drive(device_id)

    if isinstance(blocks_info, str):
        open_str = "tray open"
        close_str = "tray closed"
        for block in blocks_info.splitlines():
            if device_id in block:
                if open_str in block:
                    return True
                elif close_str in block:
                    return False
    else:
        for block in blocks_info:
            if device_id in str(block) and block.get("tray_open"):
                return block["tray_open"]
    return False


class QMPEventCheck(object):
    """
    base context manager class.
    """

    def __init__(self, *args, **kargs):
        super(QMPEventCheck, self).__init__(*args, **kargs)

    def __enter__(self):
        """
        setup of event check.
        """
        raise NotImplementedError

    def __exit__(self, *exc_info):
        """
        actual event check goes here, after the execution of event-triggering
        function.
        """
        if exc_info[0]:
            return
        self._event_check()

    def _event_check(self):
        raise NotImplementedError


class QMPEventCheckCD(QMPEventCheck):
    """
    context manager class to handle checking of event "DEVICE_TRAY_MOVED"
    """

    event_to_check = "DEVICE_TRAY_MOVED"

    def __init__(self, vm, device_id, operation):
        self.vm = vm
        self.device_id = device_id
        self.operation = operation

    def __enter__(self):
        """
        initialize status of tray and clear events of qmp_monitors.
        """
        status = is_device_tray_opened(self.vm, self.device_id)
        self.status_before = status
        self.status_after = status

        for m in self.vm.qmp_monitors:
            m.clear_event(self.event_to_check)

    def is_status_after_incorrect(self):
        raise NotImplementedError

    def is_events_count_incorrect(self):
        raise NotImplementedError

    @fail_on(CDRomError)
    def _event_check(self):
        """
        check triggered 'DEIVCE_TRAY_MOVED' events

        # 1. eject_cdrom will always open the tray and the event
        # count is 0 if opened before, 1 if closed before.
        # 2. change_media will always close the tray and the event
        # count is 2 if closed before, 1 if opened before.
        """
        if not len(self.vm.qmp_monitors):
            LOG_JOB.warning(
                "unable to check %s due to no qmp_monitor available",
                self.event_to_check,
            )
            return

        m = self.vm.qmp_monitors[0]
        events = utils_misc.wait_for(m.get_events, timeout=20)
        if not events:
            events = []
        LOG_JOB.info("Event list:\n%s", events)
        self.count = 0
        for event in events:
            if event["event"] == "DEVICE_TRAY_MOVED":
                self.count += 1
                self.status_after = bool(event["data"]["tray-open"])

        if self.is_status_after_incorrect():
            raise CDRomStatusError(self.device_id, self.status_after, self.operation)

        if self.is_events_count_incorrect():
            raise CDRomEventCountError(
                self.device_id, self.operation, self.event_to_check, self.count
            )


class QMPEventCheckCDEject(QMPEventCheckCD):
    """
    class to check for eject_cdrom
    """

    def __init__(self, vm, device_id):
        super(QMPEventCheckCDEject, self).__init__(vm, device_id, "eject_cdrom")

    def is_status_after_incorrect(self):
        return not self.status_after

    def is_events_count_incorrect(self):
        return (not self.status_before and self.count != 1) or (
            self.status_before and self.count != 0
        )


class QMPEventCheckCDChange(QMPEventCheckCD):
    """
    class to check for change_media
    """

    def __init__(self, vm, device_id):
        super(QMPEventCheckCDChange, self).__init__(vm, device_id, "change_media")

    def is_status_after_incorrect(self):
        return self.status_after

    def is_events_count_incorrect(self):
        return (not self.status_before and self.count != 2) or (
            self.status_before and self.count != 1
        )
