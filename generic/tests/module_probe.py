import logging
from virttest import base_installer

# Make it work under both autotest-framework and avocado-framework
try:
    from avocado.utils import linux_modules
except ImportError:
    from autotest.client import base_utils as linux_modules

try:
    from avocado.core import exceptions
except ImportError:
    from autotest.client.shared import error as exceptions


def run(test, params, env):
    """
    load/unload kernel modules several times.

    This tests the kernel pre-installed kernel modules
    """
    #Destory all vms for unload/load module kvm_intel/kvm_amd
    for vm in env.get_all_vms():
        if vm:
            vm.destroy()
            env.unregister_vm(vm.name)
    installer_object = base_installer.NoopInstaller('noop',
                                                    'module_probe',
                                                    test, params)
    logging.debug('installer object: %r', installer_object)
    submodules = []
    modules_str = " "
    for module in installer_object.module_list:
        if " %s " % module in modules_str:
            continue
        tmp_list = [module]
        if linux_modules.module_is_loaded(module):
            tmp_list += linux_modules.get_submodules(module)
        modules_str += "%s " % " ".join(tmp_list)
        if len(tmp_list) > 1:
            for _ in submodules:
                if _[0] in tmp_list:
                    submodules.remove(_)
                    break
        submodules.append(tmp_list)

    installer_object.module_list = []
    for submodule_list in submodules:
        installer_object.module_list += submodule_list

    load_count = int(params.get("load_count", 100))
    try:
        for _ in range(load_count):
            try:
                installer_object.load_modules()
            except base_installer.NoModuleError, e:
                logging.error(e)
                break
            except Exception, e:
                raise exceptions.TestFail("Failed to load modules [%r]: %s" %
                                          (installer_object.module_list, e))
            try:
                installer_object.unload_modules()
            except RuntimeError, e:
                logging.warn("Warning: %s" % e)
    finally:
        try:
            installer_object.load_modules()
        except base_installer.NoModuleError:
            pass
