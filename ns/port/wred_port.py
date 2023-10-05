"""
Implements a port with an output buffer, given an output ...


Reference:

Quality of Service Configuration Guide, Cisco IOS XE 17.x

Chapter: Queue Limits and WRED

https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/qos/b-quality-of-service/m_qos-queue_management_and_congestion_avoidance.html

Chapter: Congestion Avoidance Overview

https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/qos/b-quality-of-service/m_qos-conavd-oview-0.html

Chapter: Configuring Weighted Random Early Detection

https://www.cisco.com/c/en/us/td/docs/ios/qos/configuration/guide/12_2sr/qos_12_2sr_book/config_wred.html
"""

from ns.port.red_port import REDPort


class PolicyMap:
    """The policy map define how the classified traffic will be treated.
    In general, there are several policies, which maps to different
    maximum and minimum drop thresholds.

    Parameters
    ----------
    num_priorities: int
        The number of priority classes.
    max_threshold: int
        The maximum threshold for the WRED, and the minimum thresholds are spaced evenly
        between half and the entire maximum threshold. Note that the maximum threshold is
        an integer between [0, 100], which represents the percentage of the queue limit.
    """

    def __init__(
        self,
        num_priorities: int = 8,
        max_threshold: int = 40,
    ):
        self.policies = {}
        self.num_priorities = num_priorities
        self.max_threshold = max_threshold

        self.set_map()

    def add_policy(self, priority_class: int, min_threshold: int, max_threshold: int):
        """Add a new policy to the policy map."""

        assert 0 <= min_threshold <= max_threshold <= 100, "Invalid threshold setting!"

        self.policies[priority_class] = {
            "min_threshold": min_threshold / 100,
            "max_threshold": max_threshold / 100,
        }

    def set_map(self):
        """
        Set the policy map, note that the default minimum thresholds
        are spaced evenly between half and the entire maximum threshold.
        """

        min_threshold = self.max_threshold // 2
        step_size = (self.max_threshold - min_threshold) // self.num_priorities
        for priority_class in range(self.num_priorities):
            self.add_policy(priority_class, min_threshold, self.max_threshold)
            min_threshold += step_size

    def get_policy_map(self):
        """Get the policy map."""

        return self.policies


class WREDPort(REDPort):
    """Models an output port on a switch with a given rate and buffer size (in either bytes
        or packet counts), using Weighted Early Random Detection (WRED) mechanism to drop packets.

    There are two types of values can be used by WRED to calculate the drop probability. First,
    prec_based argument enables IP Precedence value of a packet to calculate the drop probability.
    Second, dscp_based argument category uses the DSCP value of a packet to calculate the drop
    probability. Here we adopt the first one, which means that the flow id will be used to find
    the priority level from the policy map, then retrieve the corresponding drop probability.

    TODO
    Parameters
        ----------
        env: simpy.Environment
            the simulation environment.
        priorities: dict
            a dictionary that contains {flow_id -> priority class}.
        rate: float
            the bit rate of the port.
        num_priorities:
            TODO
        max_threshold: integer
            The maximum (average) queue length threshold, beyond which packets will be
            dropped at the maximum probability. It represents percentage among [0, 100].
        max_probability: float
            The maximum probability (which is equivalent to 1 / mark probability denominator)
            is the fraction of packets dropped when the average queue length is at the
            maximum threshold, which is 'max_threshold'. The rate of packet drop increases
            linearly as the average queue length increases, until the average queue length
            reaches the maximum threshold, 'max_threshold'. All packets will be dropped when
            'qlimit' is exceeded.
        weight_factor: float
            The exponential weight factor 'n' for computing the average queue size.
            average = (old_average * (1-1/2^n)) + (current_queue_size * 1/2^n)
            for byte mode, n is usually set as 9;
            for packet mode, n is usually set as 6.
        element_id: int
            the element id of this port.
        limit_bytes: bool
            if True, the queue length limits will be based on bytes; if False, the queue
            length limits will be based on packets.
        zero_downstream_buffer: bool
            if True, assume that the downstream element does not have any buffers,
            and backpressure is in effect so that all waiting packets queue up in this
            element's buffer.
        debug: bool
            If True, prints more verbose debug information.
    """

    def __init__(
        self,
        env,
        priorities,
        rate: float,
        num_priorities: int,
        max_threshold: int,
        max_probability: float,
        weight_factor: int = 6,
        element_id: int = None,
        qlimit: int = None,
        limit_bytes: bool = False,
        zero_downstream_buffer: bool = False,
        debug: bool = False,
    ):
        super().__init__(
            env,
            rate,
            max_threshold=max_threshold,
            min_threshold=max_threshold // 2,
            max_probability=max_probability,
            weight_factor=weight_factor,
            element_id=element_id,
            qlimit=qlimit,
            limit_bytes=limit_bytes,
            zero_downstream_buffer=zero_downstream_buffer,
            debug=debug,
        )
        self.policies = PolicyMap(num_priorities, max_threshold).get_policy_map()

        if isinstance(priorities, dict):
            self.priorities = priorities
        else:
            raise ValueError("Priorities must be a dictionary.")

        # check the feasibility of the inputed dictionary: priorities.
        all_priorities = set(self.policies.keys())
        for priority in priorities.values():
            if priority not in all_priorities:
                raise ValueError("Error in given priorities!")

    def policy_mapper(self, flow_id):
        """Map the maximum and minimum thresholds for packets."""

        priority_class = self.priorities[flow_id]
        min_threshold = self.policies[priority_class]["min_threshold"]
        max_threshold = self.policies[priority_class]["max_threshold"]
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold

    def put(self, packet):
        """Send a packet to this element."""

        # refresh the max and min threshold based on the flow id.
        self.policy_mapper(packet.flow_id)
        super().put(packet)
