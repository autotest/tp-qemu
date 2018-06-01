"""
cdrom event check utility functions.

This module is meant to reduce code size by performing extra event check
procedures. Generally, functions here should provide layers of extra event
check for cdrom related operations.
"""
import logging
from six import PY2
from functools import wraps
from virttest import virt_vm, utils_misc


def get_device_tray_status(vm, device_id):
    """
    check whether specified block device tray is open or not.
    Return True, if device is opened, else False.

    : param vm: VM object
    : device_id: block device identifier
    """
    blocks_info = vm.monitor.info('block')

    if device_id not in str(blocks_info):
        raise ValueError('Device id: %s not recognizable by vm' % device_id)

    if isinstance(blocks_info, str):
        open_str = 'tray open'
        close_str = 'tray closed'
        for block in blocks_info.splitlines():
            if device_id in block:
                if open_str in block:
                    return True
                elif close_str in block:
                    return False
    else:
        for block in blocks_info:
            if device_id in str(block) and block.get('tray_open'):
                return block['tray_open']
    return False


def cdrom_event_check(check=True):
    def onDecorator(func):
        @wraps(func)
        def onCall(*args, **kargs):
            code = func.func_code if PY2 else func.__code__
            operation = code.co_name
            assert operation in ['eject_cdrom', 'change_media'], \
                'operation "%s" not supported' % operation

            # get vm object and device identifier from argument list
            vm = args[code.co_varnames.index('self')]
            device_id = kargs.get('device',
                                  args[code.co_varnames.index('device')])

            if check:
                status_before = status_after = get_device_tray_status(vm,
                                                                      device_id)
                for m in vm.qmp_monitors:
                    m.clear_events()

            out = func(*args, **kargs)

            if check:
                for m in vm.qmp_monitors:
                    events = utils_misc.wait_for(m.get_events, timeout=20)
                    if not events:
                        events = []
                    logging.info('Event list:\n%s' % events)
                    count = 0
                    for event in events:
                        if event['event'] == u"DEVICE_TRAY_MOVED":
                            count += 1
                            status_after = bool(event['data']['tray-open'])

                    error_status = {
                        'eject_cdrom': not status_after,
                        'change_media': status_after
                    }
                    if error_status[operation]:
                        raise virt_vm.VMDeviceError(('Device %s tray-open '
                                                     'status: %s after %s')
                                                    % (device_id,
                                                       status_after,
                                                       operation))
                    result = {
                        'eject_cdrom': ((not status_before and count != 1) or
                                        (status_before and count != 0)),
                        'change_media': ((not status_before and count != 2) or
                                         (status_after and count != 1))
                    }
                    if result[operation]:
                        raise virt_vm.VMDeviceError(("%d 'DEVICE_TRAY_MOVED' "
                                                     "received after %s %s") %
                                                    (count,
                                                     operation,
                                                     device_id))
            return out
        return onCall
    return onDecorator
