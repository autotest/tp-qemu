from avocado import fail_on
from virttest import qemu_monitor


@fail_on
def job_dismiss(vm, job_id):
    """Dismiss block job in the given VM"""
    job = get_job_by_id(vm, job_id)
    msg = "Job '%s' is '%s', only concluded job can dismiss!" % (
        job_id, job["status"])
    assert job["status"] == "concluded", msg
    func = qemu_monitor.get_monitor_function(vm, "job-dismiss")
    return func(job_id)


def get_job_by_id(vm, job_id):
    """Get block job info by job ID"""
    jobs = query_jobs(vm)
    info = [j for j in jobs if j["id"] == job_id]
    if info:
        return info[0]
    return None


def query_jobs(vm):
    """Get block jobs info list in given VM"""
    func = qemu_monitor.get_monitor_function(vm, "query-jobs")
    return func()


def make_transaction_action(cmd, data):
    """
    Make transaction action dict by arguments
    """
    prefix = "x-"
    if not cmd.startswith(prefix):
        for k in data.keys():
            if data.get(k) is None:
                data.pop(k)
                continue
            if cmd == "block-dirty-bitmap-add" and k == "x-disabled":
                continue
            if k.startswith(prefix):
                data[k.lstrip(prefix)] = data.pop(k)
    return {"type": cmd, "data": data}
