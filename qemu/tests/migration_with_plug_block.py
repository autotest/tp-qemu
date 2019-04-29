import logging
import ast

from virttest import error_context
from virttest import utils_disk
from virttest import utils_misc
from virttest import utils_test

from provider.block_devices_plug import BlockDevicesPlug
from provider.storage_benchmark import generate_instance

HOTPLUG, UNPLUG = ('hotplug', 'unplug')


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices with migration.

    Scenario after_hotplug:
        1) Start source guest with virtio-blk-pci(only system disk).
        2) For Windows: check whether viostor.sys verifier enabled in guest.
        3) Hot plug a new virtio-block via qmp.
        4) Start dst guest with “-incoming tcp:0:5888 ” on local host.
        5) Doing live migration to local host.
        6) Run iozone on system/data disk.

    Scenario after_unplug:
        1) Start source guest with virtio-blk-pci (both system disk
           and data disk ).
        2) For Windows: check whether viostor.sys verifier enabled in guest.
        3) Unplug a virtio-block via qmp.
        4) Start dst guest with “-incoming tcp:0:5888 ” on local host.
        5) Set postcopy mode to "on" on source qemu & dst qemu.
        6) Doing live migration to local host.
        7) Change into postcopy mode on source.
        8) Ping-pong for some times.

    Scenario hotplug_unplug_system_reset:
        1) Start source guest system disk.
        2) For Windows: check whether viostor.sys verifier enabled in guest.
        3) Hot plug a new disk via qmp.
        4) Start dst guest with “-incoming tcp:0:5888 ” on local host.
        5) Doing live migration to local host.
        6) Unplug the hot plugged disk via qmp.
        7) Run system_reset.

    Scenario unplug_systrem_reset:
        1) Start source guest with both system disk and data disk.
        2) For Windows: check whether viostor.sys verifier enabled in guest.
        3) Unplug the data disk via qmp.
        4) Start dst guest with “-incoming tcp:0:5888 ” on local host (
           only system disk ).
        5) Doing live migration to local host.
        6) Run system_reset.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def _send_system_reset(vm):
        """ Send system_reset command by qmp. """
        vm.monitor.system_reset()
        if not utils_misc.wait_for(lambda: vm.monitor.get_event('RESET'), 180):
            test.fail('Failed to get the event \"RESET\" after system_reset.')
        return vm.wait_for_login(timeout=360)

    def _ping_pong_migration(times):
        """ Ping-pong migration between src vm and dst vm. """
        for i in range(times):
            logging.info("Iteration %s: Start to ping-pong migrate." % (i + 1))
            vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay,
                       migrate_capabilities=capabilities,
                       mig_inner_funcs=inner_funcs, env=env)
        return vm.wait_for_login(timeout=360)

    def _stress_io_test():
        """ Do io stress testing after hot plug. """
        mount_points = []
        session = vm.wait_for_login(timeout=360)
        iozone = generate_instance(params, vm, 'iozone')
        try:
            if windows:
                session = utils_test.qemu.windrv_check_running_verifier(
                    session, vm, test, params['driver_name'], 300)
                utils_disk.update_windows_disk_attributes(session, plug[0])
                mount_points.append('C')
            else:
                mount_points.append('/home')
            for did in plug:
                mount_points.append(utils_disk.configure_empty_disk(
                    session, did, params['image_size'], os_type)[0])
            for mount_points in mount_points:
                iozone.run(params['iozone_options'].format(mount_points),
                           float(params['iozone_timeout']))
        finally:
            iozone.clean()
            session.close()

    def _set_dst_params(vm):
        """ Set the params of dst vm when hot plug block device in src vm. """
        for name in params['images'].split()[1:]:
            dev_params = ['boot_drive_{0}', 'drive_pci_addr_{0}', 'bus_extra_params_{0}',
                          'drive_scsiid_{0}', 'drive_lun_{0}', 'blk_extra_params_{0}']
            for param in ' '.join(dev_params).format(name).split():
                vm.params[param] = params.get(param) if action == HOTPLUG else None
            vm.params['boot_drive_stg0'] = 'yes' if action == HOTPLUG else 'no'

    os_type = params['os_type']
    windows = os_type == 'windows'
    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    do_stress_io = params.get('do_stress_io', 'no') == 'yes'
    do_system_reset = params.get('do_system_reset', 'no') == 'yes'
    do_ping_pong = params.get('do_ping_pong', 'no') == 'yes'
    inner_funcs = ast.literal_eval(params.get("migrate_inner_funcs", "[]"))
    capabilities = ast.literal_eval(params.get("migrate_capabilities", "{}"))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    plug = BlockDevicesPlug(vm)
    action = HOTPLUG if params.get('hotplug', 'no') == 'yes' else UNPLUG
    _set_dst_params(vm)
    getattr(plug, '%s_devs_serial' % action)()

    vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay,
               migrate_capabilities=capabilities,
               mig_inner_funcs=inner_funcs, env=env)

    if action == HOTPLUG:
        if do_stress_io:
            _stress_io_test()
        if params.get('unplug_after_hotplug', 'no') == 'yes':
            getattr(plug, '%s_devs_serial' % UNPLUG)()
    else:
        if do_ping_pong:
            _ping_pong_migration(int(params['ping_pong_times']))
    if do_system_reset:
        _send_system_reset(vm)
