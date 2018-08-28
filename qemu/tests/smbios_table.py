import logging

from avocado.utils import process

from virttest import error_context
from virttest import env_process
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Check smbios table :
    1) Get the smbios table from config file,if there is no config option in
       config file, the script will generate the config parameters automately.
    2) Boot a guest with smbios options and/or -M option
    3) Verify if bios options have been emulated correctly.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    smbios_type = params.get("smbios_type")
    notset_output = params.get("notset_output")
    dmidecode_exp = params.get("dmidecode_exp")
    login_timeout = float(params.get("login_timeout", 360))

    smbios = ""
    if params.get("smbios_type_disable", "no") == "no":
        # Set the smbios parameter, if you have set it in the config file,
        # it'll be honored, else, one will be generated.
        for sm_type in smbios_type.split():
            if sm_type == "Bios":
                smbios_type_number = 0
            elif sm_type == "System":
                smbios_type_number = 1
            smbios += " -smbios type=%s" % smbios_type_number
            dmidecode_key = params.object_params(sm_type).get("dmikeyword")
            dmidecode_key = dmidecode_key.split()
            for key in dmidecode_key:
                cmd = (dmidecode_exp % (smbios_type_number, key))
                default_key_para = process.system_output(
                    cmd, shell=True).strip()
                smbios_key_para_set = params.object_params(sm_type).get(key,
                                                                        default_key_para)
                smbios += ",%s='%s'" % (key.lower(), smbios_key_para_set)

        if params.get("extra_params"):
            params["extra_params"] += smbios
        else:
            params["extra_params"] = smbios

    support_machine_types = []
    if params.get("traversal_machine_emulated", "no") == "no":
        support_machine_types.append(params.get("machine_type"))
    else:
        qemu_binary = utils_misc.get_qemu_binary(params)
        tmp = utils_misc.get_support_machine_type(qemu_binary, remove_alias=True)[:2]
        (support_machine_types, expect_system_versions) = tmp
        machine_type = params.get("machine_type", "")
        if ':' in machine_type:
            prefix = machine_type.split(':', 1)[0]
            support_machine_types = ["%s:%s" % (prefix, m_type)
                                     for m_type in support_machine_types]

    failures = []
    for m_type in support_machine_types:
        params["machine_type"] = m_type
        params["start_vm"] = "yes"

        error_context.context("Boot the vm using -M option:'-M %s', smbios "
                              "para: '%s'" % (m_type, smbios), logging.info)
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        vm1 = env.get_vm(params["main_vm"])
        session = vm1.wait_for_login(timeout=login_timeout)

        error_context.context("Check smbios info on guest "
                              "is setted as expected")

        for sm_type in smbios_type.split():
            if sm_type == "Bios":
                smbios_type_number = 0
            elif sm_type == "System":
                smbios_type_number = 1
            dmidecode_key = params.object_params(sm_type).get("dmikeyword")
            dmidecode_key = dmidecode_key.split()
            for key in dmidecode_key:
                cmd = (dmidecode_exp % (smbios_type_number, key))
                smbios_get_para = session.cmd(cmd).strip()
                default_key_para = process.system_output(
                    cmd, shell=True).strip()
                if params.get("smbios_type_disable", "no") == "no":
                    smbios_set_para = params.object_params(sm_type).get(key,
                                                                        default_key_para)
                else:
                    key_index = support_machine_types.index(m_type)
                    smbios_set_para = expect_system_versions[key_index]

                if smbios_get_para == notset_output:
                    smbios_get_para = default_key_para

                # make UUID check case insensitive
                if key == "UUID":
                    smbios_set_para = smbios_set_para.lower()
                    smbios_get_para = smbios_get_para.lower()

                if (smbios_set_para not in smbios_get_para):
                    e_msg = ("%s.%s mismatch, Set '%s' but guest is : '%s'"
                             % (sm_type, key, smbios_set_para,
                                smbios_get_para))
                    failures.append(e_msg)

        session.close()
        if params.get("traversal_machine_emulated", "no") == "yes":
            vm1.destroy(gracefully=False)

    error_context.context("")
    if failures:
        test.fail("smbios table test reported %s failures:\n%s" %
                  (len(failures), "\n".join(failures)))
