import os
import uuid

from avocado.utils import path
from virttest import cpu, data_dir, env_process, error_context, libvirt_xml, virsh


def extend_flags_patterns(flags_dict):
    """
    Return all possible patterns for given flags
    :param flags_dict: The original dict of flags
    """
    tmp_dict = {}
    replace_char = [("_", ""), ("_", "-"), ("-", "_"), ("-", "")]
    for flag in flags_dict.keys():
        tmp_list = []
        tmp_list.extend(set(map(lambda x: flag.replace(*x), replace_char)))
        for tmp in tmp_list:
            tmp_dict[tmp] = flags_dict[flag]
    return tmp_dict


def get_cpu_info_from_dumpxml(name):
    """
    Get cpu info from virsh dumpxml
    :param name: Domain name
    :return: Cpu info dict in dumpxml
    """
    cpu_xml = libvirt_xml.VMXML.new_from_dumpxml(name).cpu
    feature_list = cpu_xml.get_feature_list()
    cpu_model = cpu_xml.model
    cpu_features = {}
    for i in range(0, len(feature_list)):
        feature_name = cpu_xml.get_feature(i).get("name")
        feature_policy = cpu_xml.get_feature(i).get("policy")
        if feature_policy == "require":
            feature_policy = "on"
        elif feature_policy == "disable":
            feature_policy = "off"
        cpu_features[feature_name] = feature_policy
    cpu_info = {}
    cpu_info["model"] = cpu_model
    cpu_info["features"] = cpu_features
    return cpu_info


def compare_cpu_info(test, params):
    """
    Compare flags between qemu cli and libvirt dumpxml with 'host-model'
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :return: True or False
    """
    vm_arch = params["vm_arch_name"]
    machine = params["machine_type"]
    name = uuid.uuid4().hex
    try:
        path.find_command("virsh")
    except path.CmdNotFoundError:
        test.cancel("Virsh executable not set or found on path")

    xml = """
            <domain type='kvm'>
                <name>%s</name>
                <memory>1</memory>
                <os>
                    <type arch='%s' machine='%s'>hvm</type>
                </os>
                <cpu mode='host-model'/>
            </domain>
          """ % (name, vm_arch, machine)
    xml_file = os.path.join(data_dir.get_tmp_dir(), "temp_xml_for_cpu")
    with open(xml_file, "w") as f:
        f.write(xml)
    try:
        test.log.info("Get cpu model and features from virsh")
        virsh.define(xml_file)
        virsh.start(name)
    except Exception as err:
        test.cancel(err)
    else:
        global qemu_cpu_info, libvirt_cpu_info, qemu_proc_cpu_flags
        qemu_cpu_info = cpu.get_cpu_info_from_virsh_qemu_cli(name)
        libvirt_cpu_info = get_cpu_info_from_dumpxml(name)

        cpu_model_qemu = qemu_cpu_info["model"]
        cpu_model_libvirt = libvirt_cpu_info["model"]
        qemu_proc_cpu_flags = qemu_cpu_info["flags"]
        if cpu_model_qemu != cpu_model_libvirt:
            test.log.error(
                "mismatch cpu model bwteen qemu %s and libvirt %s",
                cpu_model_qemu,
                cpu_model_libvirt,
            )
            return False
        params["cpu_model"] = cpu_model_qemu
        qemu_cpu_flags = cpu.parse_qemu_cpu_flags(qemu_cpu_info["flags"])
        libvirt_cpu_flags = libvirt_cpu_info["features"]
        qemu_cpu_flags = extend_flags_patterns(qemu_cpu_flags)
        exclude_map = eval(params.get("exclude_map", "{}"))
        check_exclude = False
        exclude_map_flags = []
        if cpu_model_qemu in exclude_map.keys():
            exclude_map_flags = exclude_map[cpu_model_qemu]
            check_exclude = True
        miss_flags = []
        mismatch_flags = []
        result_bool = True
        for flag in libvirt_cpu_flags.keys():
            if flag not in qemu_cpu_flags.keys():
                if libvirt_cpu_flags[flag] == "on":
                    miss_flags.append(flag)
            elif libvirt_cpu_flags[flag] != qemu_cpu_flags[flag]:
                mismatch_flags.append(flag)
        if miss_flags:
            test.log.error("\nmiss flags %s from qemu cli\n", miss_flags)
            if not check_exclude:
                result_bool = False
            else:
                for miss_flag in miss_flags:
                    if miss_flag not in exclude_map_flags:
                        result_bool = False
                        break
        if mismatch_flags:
            test.log.error(
                "\nmismatch flags %s between libvirt and qemu\n", mismatch_flags
            )
            if not check_exclude:
                result_bool = False
            else:
                for mismatch_flag in miss_flags:
                    if mismatch_flag not in exclude_map_flags:
                        result_bool = False
                        break
        return result_bool
    finally:
        if virsh.is_alive(name):
            virsh.destroy(name, ignore_status=True)
        virsh.undefine(name, ignore_status=True)


@error_context.context_aware
def run(test, params, env):
    """
    Test cpu models with full flags that libvirt generates
    1) start a default configuration xml by virsh
    2) get the cpu elements from libvirt xml by 'virsh dumpxml $domain'
    3) parse the cpu_flags and store into libvirt_cpu_flags
    4) get the cpu flags from qemu process and stroe to qemu_cpu_flags
    5) Compare the cpu flags, model of xml and qemu process, should be same
    6) Boot guest with combined flags, model, guest works well without crash

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    if not compare_cpu_info(test, params):
        test.log.error("\ncpu libvirt flags are %s\n", (str(libvirt_cpu_info)))
        test.log.error("\ncpu qemu cli flags are %s\n", (str(qemu_cpu_info)))
        test.fail("CPU info is different between dumpxml and qemu cli")

    cpu_flags = params.get("cpu_model_flags")
    params["cpu_model_flags"] = cpu.recombine_qemu_cpu_flags(
        qemu_proc_cpu_flags, cpu_flags
    )
    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    error_context.context("Try to log into guest", test.log.info)
    vm.wait_for_login()

    vm.verify_kernel_crash()
