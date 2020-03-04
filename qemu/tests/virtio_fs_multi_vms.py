import logging
import os

from virttest import error_context
from virttest import utils_disk
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test to virtio-fs with the multiple VMs and virtiofs daemons.
    Steps:
        1. Create shared directories on the host.
        2. Run virtiofs daemons on the host.
        3. Boot guests on the host with virtiofs options.
        4. Log into guest then mount the virtiofs targets.
        5. Generate files on the mount points inside guests.
        6. Compare the md5 among guests if multiple virtiofs
           daemons share the source.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    cmd_dd = params.get('cmd_dd')
    cmd_md5 = params.get('cmd_md5')
    io_timeout = params.get_numeric('io_timeout')
    shared_fs_source_dir = params.get('shared_fs_source_dir')

    sessions = []
    vms = env.get_all_vms()
    for vm in vms:
        vm.verify_alive()
        sessions.append(vm.wait_for_login())

    mapping = {}
    for vm, session in zip(params.objects('vms'), sessions):
        vm_params = params.object_params(vm)
        mapping[vm] = {'session': session, 'filesystems': []}
        for fs in vm_params.objects('filesystems'):
            fs_params = vm_params.object_params(fs)
            fs_target = fs_params.get("fs_target")
            fs_dest = fs_params.get("fs_dest")
            guest_data = os.path.join(fs_dest, 'fs_test')
            mapping[vm]['filesystems'].append({'fs_target': fs_target,
                                               'fs_dest': fs_dest,
                                               'guest_data': guest_data})

            error_context.context(
                    "%s: Create a destination directory %s inside guest." %
                    (vm, fs_dest), logging.info)
            utils_misc.make_dirs(fs_dest, session)

            error_context.context(
                    "%s: Mount the virtiofs target %s to %s inside guest." %
                    (vm, fs_target, fs_dest), logging.info)
            utils_disk.mount(fs_target, fs_dest, 'virtiofs', session=session)
            if cmd_dd:
                logging.info("Creating file under %s inside guest." % fs_dest)
                session.cmd(cmd_dd % guest_data, io_timeout)
            if shared_fs_source_dir:
                continue
            error_context.context("%s: Umount the viriofs target %s." %
                                  (vm, fs_target), logging.info)
            utils_disk.umount(fs_target, fs_dest, 'virtiofs', session=session)

    if shared_fs_source_dir:
        error_context.context("Compare the md5 among VMs.", logging.info)
        md5_set = set()
        for vm, info in mapping.items():
            session = info['session']
            for fs in info['filesystems']:
                shared_data = fs['guest_data']
                error_context.context("%s: Get the md5 of %s." %
                                      (vm, shared_data), logging.info)
                val = session.cmd(cmd_md5 % shared_data).strip().split()[0]
                logging.info(val)
                md5_set.add(val)
                error_context.context("%s: Umount the viriofs target %s." %
                                      (vm, fs['fs_target']), logging.info)
                utils_disk.umount(fs['fs_target'], fs['fs_dest'],
                                  'virtiofs', session=session)
        if len(md5_set) != 1:
            test.fail('The md5 values are different among VMs.')
