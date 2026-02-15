"""Interpret the response to a query for this experiment's specific instance ID."""


def instance_gone(reservations):
    # EC2 can stop returning a terminated instance after its retention window.
    states = [i["State"]["Name"] for r in reservations for i in r["Instances"]]
    return not states or all(state == "terminated" for state in states)
