import re
import os

from virttest import utils_misc
from virttest import env_process

from virttest.utils_version import VersionInterval


def run(test, params, env):
    """
    Acpi hmat test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    qemu_path = utils_misc.get_qemu_binary(params)
    qemu_version = env_process._get_qemu_version(qemu_path)
    version_pattern = r'%s-(\d+\.\d+\.\d+)' % os.path.basename(qemu_path)
    host_qemu = re.findall(version_pattern, qemu_version)[0]
    if host_qemu in VersionInterval('[,5.2.0)'):
        params['numa_hmat_caches_size_hmat_cache1'] = '50K'
        params['numa_hmat_caches_size_hmat_cache2'] = '40K'
        params['numa_hmat_caches_size_hmat_cache3'] = '80K'
        params['numa_hmat_caches_size_hmat_cache4'] = '70K'
        params['numa_hmat_caches_size_hmat_cache5'] = '60K'
    else:
        params['numa_hmat_caches_size_hmat_cache1'] = '40K'
        params['numa_hmat_caches_size_hmat_cache2'] = '50K'
        params['numa_hmat_caches_size_hmat_cache3'] = '60K'
        params['numa_hmat_caches_size_hmat_cache4'] = '70K'
        params['numa_hmat_caches_size_hmat_cache5'] = '80K'

    params['start_vm'] = 'yes'
    vm_name = params['main_vm']
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.wait_for_login()
    # TODO: Check the device inside guest, after get precise checking method
