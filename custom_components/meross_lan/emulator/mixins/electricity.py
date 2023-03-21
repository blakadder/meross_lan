""""""
from __future__ import annotations

from datetime import datetime, timezone
from random import randint
from time import gmtime
import typing

from .. import MerossEmulator, MerossEmulatorDescriptor
from ...merossclient import const as mc


class ElectricityMixin(MerossEmulator if typing.TYPE_CHECKING else object):
    def __init__(self, descriptor: MerossEmulatorDescriptor, key):
        super().__init__(descriptor, key)
        self.payload_electricity = descriptor.namespaces[
            mc.NS_APPLIANCE_CONTROL_ELECTRICITY
        ]
        self.electricity = self.payload_electricity[mc.KEY_ELECTRICITY]
        self.voltage_average: int = self.electricity[mc.KEY_VOLTAGE] or 2280
        self.power = self.electricity[mc.KEY_POWER]

    def _GET_Appliance_Control_Electricity(self, header, payload):
        """
        {
            "electricity": {
                "channel":0,
                "current":34,
                "voltage":2274,
                "power":1015,
                "config":{"voltageRatio":188,"electricityRatio":100}
            }
        }
        """
        p_electricity = self.electricity
        power: int = p_electricity[mc.KEY_POWER]  # power in mW
        if randint(0, 5) == 0:
            # make a big power step
            power += randint(-1000000, 1000000)
        else:
            # make some noise
            power += randint(-1000, 1000)

        if power > 3600000:
            p_electricity[mc.KEY_POWER] = self.power = 3600000
        elif power < 0:
            p_electricity[mc.KEY_POWER] = self.power = 0
        else:
            p_electricity[mc.KEY_POWER] = self.power = int(power)

        p_electricity[mc.KEY_VOLTAGE] = self.voltage_average + randint(-20, 20)
        p_electricity[mc.KEY_CURRENT] = int(
            10 * self.power / p_electricity[mc.KEY_VOLTAGE]
        )
        return mc.METHOD_GETACK, self.payload_electricity


class ConsumptionMixin(MerossEmulator if typing.TYPE_CHECKING else object):

    # this is a static default but we're likely using
    # the current 'power' state managed by the ElectricityMixin
    power = 0.0  # in mW
    energy = 0.0  # in Wh
    epoch_prev: int
    power_prev = 0.0

    BUG_RESET = True

    def __init__(self, descriptor: MerossEmulatorDescriptor, key):
        super().__init__(descriptor, key)
        self.payload_consumptionx = descriptor.namespaces[
            mc.NS_APPLIANCE_CONTROL_CONSUMPTIONX
        ]
        p_consumptionx: list = self.payload_consumptionx[mc.KEY_CONSUMPTIONX]
        if (len(p_consumptionx)) == 0:
            p_consumptionx.append(
                {
                    mc.KEY_DATE: "1970-01-01",
                    mc.KEY_TIME: 0,
                    mc.KEY_VALUE: 1,
                }
            )
        else:

            def _get_timestamp(consumptionx_item):
                return consumptionx_item[mc.KEY_TIME]

            p_consumptionx = sorted(p_consumptionx, key=_get_timestamp)
            self.payload_consumptionx[mc.KEY_CONSUMPTIONX] = p_consumptionx

        self.consumptionx = p_consumptionx
        self.epoch_prev = self.epoch
        # REMOVE
        # "Asia/Bangkok" GMT + 7
        # "Asia/Baku" GMT + 4
        descriptor.timezone = descriptor.time[mc.KEY_TIMEZONE] = "Asia/Baku"

    def _GET_Appliance_Control_ConsumptionX(self, header, payload):
        """
        {
            "consumptionx": [
                {"date":"2023-03-01","time":1677711486,"value":52},
                {"date":"2023-03-02","time":1677797884,"value":53},
                {"date":"2023-03-03","time":1677884282,"value":51},
                ...
            ]
        }
        """
        # energy will be reset every time we update our consumptionx array
        self.energy += (
            (self.power + self.power_prev) * (self.epoch - self.epoch_prev) / 7200000
        )
        self.epoch_prev = self.epoch
        self.power_prev = self.power

        if self.energy < 1.0:
            return mc.METHOD_GETACK, self.payload_consumptionx

        energy = int(self.energy)
        self.energy -= energy

        y, m, d, hh, mm, ss, weekday, jday, dst = gmtime(self.epoch)
        ss = min(ss, 59)  # clamp out leap seconds if the platform has them
        devtime = datetime(y, m, d, hh, mm, ss, 0, timezone.utc)
        if (tzinfo := self.tzinfo) is not None:  # REMOVE
            devtime = devtime.astimezone(tzinfo)

        date_value = "{:04d}-{:02d}-{:02d}".format(
            devtime.year, devtime.month, devtime.day
        )

        p_consumptionx = self.consumptionx
        consumptionx_last = p_consumptionx[-1]
        if consumptionx_last[mc.KEY_DATE] != date_value:
            if len(p_consumptionx) >= 30:
                p_consumptionx.pop(0)
            p_consumptionx.append(
                {
                    mc.KEY_DATE: date_value,
                    mc.KEY_TIME: self.epoch,
                    mc.KEY_VALUE: energy + consumptionx_last[mc.KEY_VALUE]
                    if self.BUG_RESET
                    else 0,
                }
            )

        else:
            consumptionx_last[mc.KEY_TIME] = self.epoch
            consumptionx_last[mc.KEY_VALUE] += energy

        return mc.METHOD_GETACK, self.payload_consumptionx
