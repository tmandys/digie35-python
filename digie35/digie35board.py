# vim: set expandtab:
# -*- coding: utf-8 -*-
#
# Copyright (c) 2023 MandySoft
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

__author__ = "Tomas Mandys"
__copyright__ = "Copyright (C) 2023 MandySoft"
__licence__ = "MIT"
__version__ = "0.3"

from digie35.digie35core import *
import logging
import time
import time
import datetime

## @package digie35board
# Board and adapter Support


## Adapter for Nikon SA-21 with unipolar 5V stepper motor
class NikonStepperMotorAdapter(StepperMotorAdapter):

    _STEPPER_MOTOR_PHASES = (0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001)
    _SPEED_TO_FREQ = (13, 33, 130, 333)  # 1000 when extra 18V power for adapter
    _ACCELERATION = 0
    #_STEPS_PER_HOLE = 1100/10  # measured
    #_STEPS_PER_MM = _STEPS_PER_HOLE/StepperMotorAdapter._PERFORATION_HOLE_DISTANCE
    # 3stage gear box with plactic wheels between stepper and axis
    _STEPS_PER_REVOLUTION = 40
    _GEAR_1_1 = 18
    _GEAR_1_2 = 76
    _GEAR_2_1 = 18
    _GEAR_2_2 = 44
    _GEAR_3_1 = 17
    _GEAR_3_2 = 44
    _WHEEL_DIAMETER_IN_MM = 15
    _BACKLASH_COMPENSATION = 15   # TODO: somehow configure, this is harcoded value for testing
    _FRONT_SENSOR_DISTANCE = 43.75 # mm  FRONT-MIDDLE
    _REAR_SENSOR_DISTANCE = 45.60 # mm  MIDDLE-REAR    FRONT-REAR 89.2mm
    # calculated value is 22.67
    _STEPS_PER_MM = 1 / (_WHEEL_DIAMETER_IN_MM * 3.14159 * _GEAR_1_1 * _GEAR_2_1 * _GEAR_3_1 / _GEAR_1_2 / _GEAR_2_2 / _GEAR_3_2 / _STEPS_PER_REVOLUTION)


    def __init__(self, xboard):
        super().__init__(xboard)
        self._backlash["compensation"] = self._BACKLASH_COMPENSATION
        self._sensor_distance = {
            "front": self._FRONT_SENSOR_DISTANCE,
            "rear": self._REAR_SENSOR_DISTANCE,
        }
        self._motor_phase = 0

    def _initialize_io_map(self):
        super()._initialize_io_map()
        self._motor_gpio = (self._xboard._io_map["in_out_3"]["num"], self._xboard._io_map["in_out_2"]["num"], self._xboard._io_map["in_out_4"]["num"], self._xboard._io_map["in_out_1"]["num"])
        logging.getLogger().debug(f"Motor gpios: %s", self._motor_gpio)

    def get_steps_per_mm(self):
        return self._STEPS_PER_MM

    def _get_stepper_params(self, speed):
        return (self._SPEED_TO_FREQ[abs(speed)-1], self._ACCELERATION)

    def _do_set_motor_gpio(self, outputs):
        for i in range(0, 4):
            self._xboard._set_gpio(self._motor_gpio[i], ((1<<i) & outputs) != 0)
        # logging.getLogger().debug(f"Motor phase: {outputs:b}")

    def _do_step_impl(self):
        if self._motor_current_dir > 0:
            self._motor_phase = (self._motor_phase + 1) % len(self._STEPPER_MOTOR_PHASES)
        else:
            self._motor_phase = (self._motor_phase - 1) % len(self._STEPPER_MOTOR_PHASES)
        self._adjust_motor_position(self._motor_current_dir > 0)
        self._do_set_motor_gpio(self._STEPPER_MOTOR_PHASES[self._motor_phase])

    def _do_on_start(self, direction):
        # TODO: set PWM
        logging.getLogger().debug("STEPPER: do_on_start(%s)", direction)
        self._do_set_motor_gpio(self._STEPPER_MOTOR_PHASES[self._motor_phase])

    def _do_on_stop(self, next_direction):
        logging.getLogger().debug("STEPPER: do_on_stop(%s)", next_direction)
        if next_direction == 0:
            # switch on motor windings current to avoid overheating. TODO: PWM
            self._do_set_motor_gpio(0)

    def _check_adapter_ready(self):
        """
            Check if adapter is ready and closed
        """
        # testing via detect_aot is unreliaoble on pre 1.03 boards
        pass

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        # propagate io used by adapter, we can leave default configuration
        for i in range(1, 5):
            result["in_out_"+str(i)] = {}
        result["sensor_r"] = {}
        result["sensor_f"] = {}
        result["sensor_m"] = {}
        return result

## Development board for Nikon SA-21 adapter with I2C i/o non integrated to any hw box. 10-pin extension connector
class AlphaExtensionBoard(ExtensionBoardWithI2C):

    def _get_connected_adapter_class_impl(self):
        return {
            super().AOT_NAME: NikonStepperMotorAdapter,
        }

    def _get_i2c_configuration(self):
        return super()._get_i2c_configuration() | {
            #"bus_id": 1,
            "addr": {
                "xio": 0b0100011, # PCF8574
            },
        }

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["in_out_1"]["num"] = 21
        result["in_out_2"]["num"] = 20
        result["in_out_3"]["num"] = 26
        result["in_out_4"]["num"] = 19
        result |= {
            "xio_int": {
                "dir": "i",
                "type": "gpio",
                "num": 16,
                "hidden": True,
                "pud": "up",
                "trigger": "falling",
            },
            "jack": {
                "dir": "i",
                "type": "xio",
                "num": 4,
                "negative": True,
            },
            "focus": {
                "dir": "o",
                "type": "xio",
                "num": 5,
            },
            "shutter": {
                "dir": "o",
                "type": "xio",
                "num": 6,
            },
            "reserve": {
                "dir": "o",
                "type": "xio",
                "num": 7,
            },
            # we can leave sensor_x default (at xio)
        }
        return result

## Nikon only board for 60mm rig, i.e. metal u-shape box. 10-pin extension connector and powered by 5V
class NikiExtensionBoard(ExtensionBoard):

    def _set_backlight_impl(self, color, intensity):
        if color == None:
            self.set_io_states({"led_white": 0, "led_ir": 0, "psu_led": 0, })
        elif color == "white":
            self.set_io_states({"led_ir": 0, "led_white": intensity, "psu_led": intensity > 0, })
        elif color == "ir":
            self.set_io_states({"led_white": 0, "led_ir": intensity, "psu_led": intensity > 0, })
        else:
            raise DigitizerError("Color '%s' is not supported" % color)

    def get_capabilities(self):
        result = super().get_capabilities()
        result |= {
            "backlight_control": True,
            "white_backlight": True,
            "sleep": True,
        }
        return result

    def _get_connected_adapter_class_impl(self):
        return {
            super().AOT_NAME: NikonStepperMotorAdapter,
        }

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["in_out_1"]["num"] = 21
        result["in_out_2"]["num"] = 20
        result["in_out_3"]["num"] = 26
        result["in_out_4"]["num"] = 19
        result |= {
            "focus": {
                "dir": "o",
                "type": "gpio",
                "num": 25,
            },
            "shutter": {
                "dir": "o",
                "type": "gpio",
                "num": 24,
            },
            "psu_led": {
                "dir": "o",
                "type": "gpio",
                "num": 16,
            },
            "led_white": {
                "dir": "o",
                "type": "pwm",
                "num": 1,
                "gpio": 13,
            },
            "led_ir": {
                "dir": "o",
                "type": "pwm",
                "num": 0,
                "gpio": 12,
                #"min_duty_cycle": 0,
            },
            "sleep_button": {
                "dir": "i",
                "type": "gpio",
                "num": 3,
                "pud": "up",
                "trigger": "both",
                "negative": True,
                "hidden": False,
            },
        }
        sensor_gpios = {
            "sensor_r": 6,
            "sensor_f": 5,
            "sensor_m": 7,
            "detect_aot": 8,
        }
        for name in list(sensor_gpios):
            result[name] |= {
                "type": "gpio",
                "negative": True,
                "num": sensor_gpios[name],
                "trigger": "both",
            }

        return result

class GulpBoardMemory(SerialEeprom):
    # EEPROM 256 bytes
    HEADER_ADDR = 0
    HEADER_SIZE = 128
    CUSTOM_ADDR = HEADER_SIZE
    CUSTOM_SIZE = 128

    # (name, type: [string, STRING, datetime, int...signed, number], size, descr, [default value, [options]] )
    HEADER_MAP = [
        (None, "number", 2, "Magic"),
        (None, None, 6, "Reserved"),
        ("system_id", "STRING", 8, "System id", "DIGIE35"),
        ("adapter_id", "STRING", 8, "Adapter id used to identify plugged-in adapter", None, lambda: [cls.ID for cls in registered_boards]),
        ("board_id", "STRING", 8, "Board id", "GULP"),
        ("version", "number", 2, "Board version in decimal form 'xxyy' corresponding to xx.yy"), # no default value not to overwrite easily value
        ("serial_number", "number", 8, "Unique serial number"), # dtto
        ("human_name", "string", 16, "Human readable board name, e.g. Digie35", "Digie35"),
        ("manufacturer", "string", 8, "Manufacturer name", "2P"),
        ("pcb_by", "string", 3, "PCB manufacturer nick"),
        ("pcb_stamp", "number", 2, "PCB stamp ('YY9WW' or 'YYDDD')"),
        ("pcba_smd_by", "string", 3, "PCBA SMD by nick"),
        ("pcba_smd_stamp", "number", 2, "PCBA SMD stamp ('YY9WW' or 'YYDDD')"),
        ("pcba_tht_by", "string", 3, "PCBA SMD by nick"),
        ("pcba_tht_stamp", "number", 2, "PCBA SMD stamp ('YY9WW' or 'YYDDD')"),
        ("tested1_by", "string", 3, "Tested phase 1 by nick"),
        ("tested1_stamp", "number", 2, "Tested phase 1 stamp ('YY9WW' or 'YYDDD')"),
        ("tested2_by", "string", 3, "Tested phase 2 by nick"),
        ("tested2_stamp", "number", 2, "Tested phase 2 stamp ('YY9WW' or 'YYDDD')"),
        #("dt_param", "datetime", 8, "Datetime example"),
    ]

    CUSTOM_MAP  = []
    MAGIC = 0xAA55

    def get_version(self):
        return self.read_number(32, 2)

    def get_id_version(self):
        w = self.read_number(0, 2)
        if w == self.MAGIC:
            adapter_id = self.read_string(16, 8)
            version = self.get_version()
            #logging.getLogger().debug("adapter_id: %s, ver: %s", (adapter_id, version))
            if adapter_id == None or version == None:
                return None
            return (adapter_id, version)
        else:
            return None

    def _read_datetime(self, addr):
        arr = self.read_array(addr, 6)
        if arr[0] < 30 and arr[1] >= 1 and arr[1] <= 12 and arr[2] >= 1 and arr[2] <= 31 and arr[3] < 24 and arr[4] < 60 and arr[5] < 60:
            return datetime.datetime(2000+arr[0], arr[1], arr[2], arr[3], arr[4], arr[5])
        else:
            return None

    def _write_datetime(self, addr, dt):
        if dt != None:
            arr = [
                dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second
            ]
            if arr[0] < 2000:
                arr[0] = 0
            else:
                arr[0] = arr[0] - 2000
        else:
            arr = [0, 0, 0, 0, 0, 0]
        self.write_array(addr, arr)

    def reset(self, addr, len):
        arr = []
        for i in range(0, len):
            arr.append(0xFF)
        self.write_array(addr, arr)

    def erase(self):
        self.reset(self.HEADER_ADDR, self.HEADER_SIZE)
        self.reset(self.CUSTOM_ADDR, self.CUSTOM_SIZE)

    def read_data(self, addr, map):
        res  = {}
        for item in map:
            if item[0] != None:
                if item[1].upper() == "STRING":
                    res[item[0]] = self.read_string(addr, item[2])
                elif item[1] == "int":
                    res[item[0]] = self.read_number(addr, item[2], True)
                elif item[1] == "number":
                    res[item[0]] = self.read_number(addr, item[2])
                elif item[1] == "datetime":
                    res[item[0]] = self._read_datetime(addr)
            addr += item[2]
        return res

    def write_data(self, addr, map, data):
        for item in map:
            if item[0] != None and item[0] in data:
                if item[1] == "STRING":
                    self.write_string(addr, data[item[0]].upper(), item[2])
                elif item[1] == "string":
                    self.write_string(addr, data[item[0]], item[2])
                elif item[1] in ["int", "number"]:
                    self.write_number(addr, data[item[0]], item[2])
                elif item[1] == "datetime":
                    self._write_datetime(addr, data[item[0]])
            addr += item[2]

    def read_header(self):
        return self.read_data(self.HEADER_ADDR, self.HEADER_MAP)

    def write_header(self, hdr):
        self.write_number(0, self.MAGIC, self.HEADER_MAP[0][2])
        self.write_data(self.HEADER_ADDR, self.HEADER_MAP, hdr)

    def read_custom(self):
        return self.read_data(self.CUSTOM_ADDR, self.CUSTOM_MAP)

    def write_custom(self, data):
        return self.write_data(self.CUSTOM_ADDR, self.CUSTOM_MAP, data)

class GulpAdapterMemory(GulpBoardMemory):

    def create_adapter_memory(self, adapter_class):
        res = adapter_class.BOARD_MEMORY_CLASS(self._mainboard, self._i2c_addr, self._page_size)
        return res

    def get_adapter_custom(self, adapter):
        adapter_memory = self.create_adapter_memory(type(adapter))
        res = adapter_memory.read_custom()
        logging.getLogger().debug("%s custom data: %s", type(adapter).__name__, res)
        return res

## Adapter for Nikon SA-21 with unipolar 5V stepper motor
class GulpNikonStepperMotorAdapterMemory(GulpAdapterMemory):

    # TODO: speed is higher for v102, board_tool does not work with version so all options are here
    CUSTOM_MAP = [
        ("backlash_compensation", "int", 2, "Backlash compensation", NikonStepperMotorAdapter._BACKLASH_COMPENSATION),
        ("speed1", "number", 2, "Speed1 in mm/100/sec", int(100*NikonStepperMotorAdapter._SPEED_TO_FREQ[0]/NikonStepperMotorAdapter._STEPS_PER_MM)),
        ("speed2", "number", 2, "Speed2 in mm/100/sec", int(100*NikonStepperMotorAdapter._SPEED_TO_FREQ[1]/NikonStepperMotorAdapter._STEPS_PER_MM)),
        ("speed3", "number", 2, "Speed3 in mm/100/sec", int(100*NikonStepperMotorAdapter._SPEED_TO_FREQ[2]/NikonStepperMotorAdapter._STEPS_PER_MM)),
        ("speed4", "number", 2, "Speed4 in mm/100/sec", int(100*NikonStepperMotorAdapter._SPEED_TO_FREQ[3]/NikonStepperMotorAdapter._STEPS_PER_MM)),
        ("acceleration", "int", 2, "Max.acceleration mm/100/sec^2", 5000),
    ]

class GulpNikonStepperMotorAdapter(NikonStepperMotorAdapter):
    ID = "NIKON"
    BOARD_MEMORY_CLASS = GulpNikonStepperMotorAdapterMemory

    def __init__(self, xboard):
        super().__init__(xboard)
        custom = xboard._aot_memory.get_adapter_custom(self)
        self._backlash["compensation"] = custom["backlash_compensation"]
        arr = []
        for i in range(1, 5):
            speed = custom["speed"+str(i)]
            if speed != None:
                arr.append(speed/100*NikonStepperMotorAdapter._STEPS_PER_MM)
            else:
                arr.append(None)
        self._SPEED_TO_FREQ = (arr[0], arr[1], arr[2], arr[3])
        if custom["acceleration"] > 0:
            self._ACCELERATION = custom["acceleration"]/100*NikonStepperMotorAdapter._STEPS_PER_MM

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["psu_sensor"] = {}
        return result

class GulpNikonStepperMotorAdapter_0103(GulpNikonStepperMotorAdapter):

    def __init__(self, xboard):
        super().__init__(xboard)
        caps = self._xboard.get_capabilities()
        self._aot_detection = caps["aot_detection"]

    def _do_on_start(self, direction):
        super()._do_on_start(direction)
        self._xboard.set_io_state("nikon_psu", 1)

    def _do_on_stop(self, next_direction):
        super()._do_on_stop(next_direction)
        if next_direction == 0:
            self._xboard.set_io_state("nikon_psu", 0)

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["in_out_5"] = {
            "name": "nikon_psu",
        }
        return result

    def _check_adapter_ready(self):
        """
            Check if adapter is ready
        """
        if not self._is_drive_plugged():
            raise DigitizerError("Adapter is not detected")

    def get_capabilities(self):
        result = super().get_capabilities()
        result["motorized"] = self._is_drive_plugged()
        return result

    def _is_drive_plugged(self):
        return not self._aot_detection or self._xboard.get_io_state("detect_aot")


## Motorized adapter with 24V bipolar stepper motor controlled by STEP/DIR interface
class GulpStepperMotorAdapterMemory(GulpAdapterMemory):
    DRIVER_A4988 = 0
    DRIVER_DRV8825 = 1
    DRIVER_TMC2208_COMP = 2
    DRIVER_TMC2208_UART = 3

    CUSTOM_MAP = [
        ("driver", "number", 1, "Driver", DRIVER_TMC2208_COMP, {DRIVER_A4988: "A4988", DRIVER_DRV8825: "DRV8825", DRIVER_TMC2208_COMP: "TMC2208 (compatible)", DRIVER_TMC2208_UART: "TMC2208 (UART mode TBD)",}),
        ("gear1", "number", 1, "Wheel 1 teeth numberx", 12, [12, 16, 20]),
        ("gear2", "number", 1, "Wheel 2 teeth number", 20, [12, 16, 20]),
        ("steps_per_revolution", "number", 2, "Steeper number of steps per revolution", 200),
        ("microstepping", "number", 1, "Microstepping", 2, {0: "full", 1: "half", 2: "/4", 3: "/8", 4: "/16"}),  # for hight speed frequency is to high so think about reasonable MS
        ("wheel_diameter", "number", 2, "Wheel diameter in mm/100", 1280),
        ("speed1", "number", 2, "Speed1 in mm/100/sec", 100),
        ("speed2", "number", 2, "Speed2 in mm/100/sec", 600),
        ("speed3", "number", 2, "Speed3 in mm/100/sec", 1500),
        ("speed4", "number", 2, "Speed4 in mm/100/sec", 3000),
        ("acceleration", "int", 2, "Max.acceleration mm/100/sec^2", 5000),
        ("front_sensor_distance", "int", 2, "Front sensor distance", 4500),
        ("rear_sensor_distance", "int", 2, "Rear sensor distance", 4900),
        ("backlash_compensation", "int", 2, "Backlash compensation", -1),
    ]

class GulpStepperMotorAdapter(StepperMotorAdapter):
    ID = "STEPPER"
    BOARD_MEMORY_CLASS = GulpStepperMotorAdapterMemory

    #_GEAR1 = 16
    #_GEAR2 = 20
    #_WHEEL_DIAMETER_IN_MM = 12
    #_STEPS_PER_REVOLUTION = 200
    #_SPEED_IN_MM_PER_SECS = (5, 30, 40, 70)
    #_MICROSTEPPING = 3
    #_STEPS_PER_MM = 1 / (_WHEEL_DIAMETER_IN_MM * 3.14159 * _GEAR1 / _GEAR2 / _STEPS_PER_REVOLUTION) * (1 << _MICROSTEPPING)
    #_BACKLASH_COMPENSATION = -1

    def __init__(self, xboard):
        super().__init__(xboard)
        custom = self._xboard._aot_memory.get_adapter_custom(self)
        self._DRIVER = custom["driver"]
        self._MICROSTEPPING = custom["microstepping"]
        if self._DRIVER == GulpStepperMotorAdapterMemory.DRIVER_TMC2208_COMP:
            # TMC driver in legacy mode has range 1/2 - 1/16
            if self._MICROSTEPPING == 0:
                self._MICROSTEPPING = 1
        else:
            # range 1/1 - 1/8
            if self._MICROSTEPPING > 3:
                self._MICROSTEPPING = 3
        try:
            self._STEPS_PER_MM = 1/ (custom["wheel_diameter"]/100 * 3.14159 * custom["gear1"] / custom["gear2"] / custom["steps_per_revolution"]) * (1<<self._MICROSTEPPING)
            logging.getLogger().debug("wheel diameter: %s, circ: %s, dist per motor rev: %s, dist per step: %s, dist per mstep: %s, " %
                                  (custom["wheel_diameter"]/100, custom["wheel_diameter"]/100*3.14159,
                                   custom["wheel_diameter"]/100 * 3.14159 * custom["gear1"] / custom["gear2"],
                                   custom["wheel_diameter"]/100 * 3.14159 * custom["gear1"] / custom["gear2"] / custom["steps_per_revolution"],
                                   custom["wheel_diameter"]/100 * 3.14159 * custom["gear1"] / custom["gear2"] / custom["steps_per_revolution"] / (1<<self._MICROSTEPPING),
                                  ))
        except:
            # when wrong value in EEPROM
            self._STEPS_PER_MM = 1
            pass
        self._backlash["compensation"] = custom["backlash_compensation"]
        self._sensor_distance = {
            "front": custom["front_sensor_distance"]/100,
            "rear": custom["rear_sensor_distance"]/100,
        }
        self._SPEED_IN_MM_PER_SECS = (custom["speed1"]/100, custom["speed2"]/100, custom["speed3"]/100, custom["speed4"]/100)
        self._ACCELERATION_IN_MM_PER_SECS2 = custom["acceleration"]/100

        logging.getLogger().debug("driver: %s, ms: %s, steps_per_mm: %s, speed: %s, interval#0: %s" % (self._DRIVER, self._MICROSTEPPING, self.get_steps_per_mm(), self._SPEED_IN_MM_PER_SECS, self._get_stepper_params(1)))

    def _initialize_io_map(self):
        super()._initialize_io_map()
        self._step_output_num = self._xboard._io_map["stepper_step"]["num"]
        self._xboard.set_io_state("stepper_sleep", True)

    def reset(self):
        super().reset()
        self._xboard.set_io_state("stepper_sleep", True)

    def get_steps_per_mm(self):
        return self._STEPS_PER_MM

    def _get_stepper_params(self, speed):
        freq = self._SPEED_IN_MM_PER_SECS[abs(speed)-1] * self.get_steps_per_mm() * 2 # step signal has has half freq
        return (freq, self._ACCELERATION_IN_MM_PER_SECS2 * self.get_steps_per_mm() * 2)

    def _do_on_start(self, direction):
        #logging.getLogger().debug("STEPPER: do_on_start: %s", dir)
        if self._DRIVER == GulpStepperMotorAdapterMemory.DRIVER_TMC2208_COMP:
            # MS1 MS0 ... 00=1/8, 01=1/2, 10=1/4, 11=1/16
            self._xboard.set_io_state("stepper_ms0", self._MICROSTEPPING in (1, 4))
            self._xboard.set_io_state("stepper_ms1", self._MICROSTEPPING in (2, 4))
        else:
            self._xboard.set_io_state("stepper_ms0", (self._MICROSTEPPING & 0x1) != 0)
            self._xboard.set_io_state("stepper_ms1", (self._MICROSTEPPING & 0x2) != 0)
        self._xboard.set_io_state("stepper_dir", direction <= 0)
        # self._xboard._set_io_state("stepper_step", False)
        self._xboard.set_io_state("stepper_sleep", False)
        self._motor_home_pos = 0  # motor should be in home position

    def _do_on_stop(self, next_direction):
        if self._DRIVER == GulpStepperMotorAdapterMemory.DRIVER_TMC2208_COMP:
            # driver has standstill power reduction so we can leave it powered when film is detected
            if self._film_sensing["state"]["controlled"]:
                return

        #logging.getLogger().debug("STEPPER: do_on_stop(%s)", next_direction)
        if next_direction == 0:
            # driver goes to sleep and stops feeding windings so axis turns likely to nearest full step
            # or turns when wake up. So we need round motor position to home position
            # A4988 and DRV8825 have home when both winding has 70% current, angle 45°
            # TMCxxxx driver has standstill power down so we do not care about position
            if self._MICROSTEPPING != 0 and self._DRIVER != GulpStepperMotorAdapterMemory.DRIVER_TMC2208_COMP:
                home_pos = 1 << (self._MICROSTEPPING - 1)   # Allegro has home index it half and seems it is the most stable index for our reasons
                logging.getLogger().debug("Homing: %s" % (self._motor_home_pos))
                while self._motor_home_pos != home_pos:
                    self._do_step_impl()
                    time.sleep(self._motor_job.interval.total_seconds())
            # now we can smoothly switch of current
            self._xboard.set_io_state("stepper_sleep", True)

    def _do_step_impl(self):
        #logging.getLogger().debug("do step")
        state = self._xboard._get_gpio(self._step_output_num)
        if not state:  # step proceed on 0->1 edge
            self._adjust_motor_position(self._motor_current_dir > 0)
            if self._MICROSTEPPING > 0:
                steps_per_full = 1 << self._MICROSTEPPING
                if self._motor_current_dir > 0:
                    if self._motor_home_pos < steps_per_full - 1:
                        self._motor_home_pos += 1
                    else:
                        self._motor_home_pos = 0
                else:
                    if self._motor_home_pos > 0:
                        self._motor_home_pos -= 1
                    else:
                        self._motor_home_pos = steps_per_full - 1

        self._xboard._set_gpio(self._step_output_num, not state)

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result |= {
            "in_out_3": {
                "name": "stepper_ms0",
            },
            "in_out_4": {
                "name": "stepper_ms1",
            },
            "in_out_6": {
                "name": "stepper_step",
            },
            "in_out_2": {
                "name": "stepper_dir",
            },
            "in_out_1": {
                "name": "stepper_sleep",
                "negative": True,
            },
            "in_out_5": {
                "name": "stepper_vref",
                "unused": True,
            },
        }
        result["psu_sensor"] = {}
        result["sensor_r"] = {}
        result["sensor_f"] = {}
        result["sensor_m"] = {}
        return result


class GulpStepperMotorAdapter_0101(GulpStepperMotorAdapter):

    def reset(self):
        super().reset()
        self._xboard.set_io_state("stepper_enable", False)

    def _do_on_start(self, direction):
        super()._do_on_start(direction)
        self._xboard.set_io_state("stepper_enable", True)

    def _do_on_stop(self, next_direction):
        super()._do_on_stop(next_direction)
        if next_direction == 0:
            self._xboard.set_io_state("stepper_enable", False)

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["in_out_4"] = {
            "name": "stepper_ms0",
        }
        result["in_out_5"] = {
            "name": "stepper_ms1",
        }
        result["in_out_1"] = {
            "name": "stepper_enable",
            "negative": True,
        }
        result["in_out_3"] = {
            "name": "stepper_sleep",
            "negative": True,
        }
        return result

class GulpStepperMotorAdapter_0103(GulpStepperMotorAdapter_0101):
    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["in_out_1"]["negative"] = False  # there is transistor which negates
        return result

## Manual sledge adapter with own light box

class GulpManualAdapterMemory(GulpAdapterMemory):

    CUSTOM_MAP = [
        ("max_backlight", "number", 1, "Max.backlight pwm, (0..100)", 20),
    ]

class GulpManualAdapter(Adapter):
    ID = "MANUAL"
    BOARD_MEMORY_CLASS = GulpManualAdapterMemory

    def __init__(self, xboard):
        super().__init__(xboard)
        custom = self._xboard._aot_memory.get_adapter_custom(self)
        self._max_backlight = custom["max_backlight"]
        self._save_backlight_color = self._xboard.get_current_backlight_color()
        if self._save_backlight_color == None or self._save_backlight_color == "external":
            self._save_backlight_color = "white"
        self._xlight = self._save_backlight_color == "external"
        self._last_sensor_states = None
        self._shot_ready = False

    def get_state(self, force=False):
        result = {
            "frame_ready": self._shot_ready,
        }
        return result

    def on_gpio_change(self, source):
        """
            Sensor state has changed
        """
        logging.getLogger().debug("%s" % __name__)
        super().on_gpio_change(source)
        self._xboard._get_xio(True)
        input_names = ["sensor_f", "sensor_r", "sensor_m"]
        inputs = self._xboard.get_io_states(input_names)
        logging.getLogger().debug("sensor states: %s" % inputs)
        if inputs == self._last_sensor_states:
            return
        self._last_sensor_states = inputs
        # TODO: adjust backlight

        color = self._xboard.get_current_backlight_color()
        is_backlight = color != None and color != "external"
        is_preview = color == "external"
        if is_backlight and not inputs["sensor_f"]:
            # backlight till front sensor
            self._save_backlight_color = color
            self._xboard.set_backlight(None)
        elif is_preview and inputs["sensor_f"] and not inputs["sensor_r"]:
            # moving back interrupts front sensor first but it may be interrupted by film strip so wait for rear sensor is off
            self._xboard.set_backlight(None)
        elif not is_preview and not is_backlight and not inputs["sensor_f"] and inputs["sensor_r"] and not inputs["sensor_m"]:
            # also sensor_m because finger over ra sensor can unintetionally switch on preview during movement
            self._xboard.set_backlight("external", -1)
        elif not is_preview and not is_backlight and inputs["sensor_f"] and not inputs["sensor_m"]: # and not inputs["sensor_r"]:
            self._xboard.set_backlight(self._save_backlight_color, -1)
        if not self._shot_ready and inputs["sensor_f"] and not inputs["sensor_m"] and not inputs["sensor_r"]:
            self._shot_ready = True
        elif self._shot_ready and not (inputs["sensor_f"] and not inputs["sensor_m"]):
            self._shot_ready = False

    def get_capabilities(self):
        result = {
            "preview_backlight": True,
            "preview_backlight_control": True,
        }
        return result

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["led_external"] = {}
        result["psu_sensor"] = {}
        result["sensor_r"] = {}
        result["sensor_f"] = {}
        result["sensor_m"] = {}
        result["led_external"]["max_duty_cycle"] = self._max_backlight
        return result

## Light control board
class GulpLightAdapterMemory(GulpAdapterMemory):
    LED_WHITE = 1
    LED_IR = 2
    LED_RGB = 3
    LED_RGBAW = 4

    CUSTOM_MAP = [
        ("led1", "number", 1, "LED connected to slot 1", LED_WHITE, {0: "None", 1: "White"}),
        ("led2", "number", 1, "LED connected to slot 2", 0, {0: "None", 2: "IR"}),
        ("led3", "number", 1, "LED connected to slot 3", 0, {0: "None", 3: "RGB", 4: "RGBAW"}),
    ]

class GulpLightAdapter(Adapter):
    # ID = "LIGHT"
    BOARD_MEMORY_CLASS = GulpLightAdapterMemory

    def set_backlight(self, color, intensity=None):
        pass

class GulpLight8xPWMAdapter(GulpLightAdapter):
    ID = "LGHT8PWM"

    def __init__(self, xboard):
        super().__init__(xboard)
        custom = self._xboard._light_memory.get_adapter_custom(self)
        self._led = (
            custom["led1"],
            custom["led2"],
            custom["led3"]
        )

        self._i2c_addr = 0x6C
        data = [
            0, # MODE1
            0b00010101, # MODE2 Mode register 2    (totem, /oe..hi-Z)
            0, 0, 0, 0, 0, 0, 0, 0, # PWM brightness 0-7
            0xFF, # GRPPWM group duty cycle control
            0xFF, # GRPFREQ group frequency (not used)
            0x0, # LEDOUT0 LED output state 0
            0x0, # LEDOUT1 LED output state 1
        ]
        self._write_to_driver(0, data)

    def _write_to_driver(self, addr, data):
        buf = [0x80 | addr] + data
        logging.getLogger().debug("PCA9634 write: %s" % buf)
        self._xboard._mainboard.i2c_write_read(self._i2c_addr, buf, 0)

    def get_capabilities(self):
        result = super().get_capabilities()
        result |= {
            "white_backlight": self._led[0] == GulpLightAdapterMemory.LED_WHITE,
            "ir_backlight": self._led[1] == GulpLightAdapterMemory.LED_IR,
            "rgb_backlight": self._led[2] in [GulpLightAdapterMemory.LED_RGB, GulpLightAdapterMemory.LED_RGBAW, ],
            "rgbaw_backlight": self._led[2] == GulpLightAdapterMemory.LED_RGBAW,
            "backlight_control": True,
        }
        return result

    def set_backlight(self, color, intensity=None):
        if intensity != None:
            logging.getLogger().debug("set_backlight(%s, 0x%x)" % (color, intensity))
        # PCA9634 I2C=0x6C
        # 0 .. res / general on/off in v0103
        # 1 .. white (standalone)
        # 2 .. ir
        # 3 .. white
        # 4 .. red
        # 5 .. green
        # 6 .. blue
        # 7 .. amber
        pwm = [0, 0, 0, 0, 0, 0, 0, 0]
        if color == None:
            pass
        if color == "white":
            pwm[1] = intensity
        elif color == "ir":
            pwm[2] = intensity
        elif color in ["red+green+blue", "white+red+green+blue", "amber+white+red+green+blue"]:
            pwm[4] = (intensity >> 16) & 0xFF
            pwm[5] = (intensity >> 8) & 0xFF
            pwm[6] = (intensity >> 0) & 0xFF
            white = (intensity >> 24) & 0xFF
            pwm[7] = (intensity >> 32) & 0xFF
            if self._led[2] == GulpLightAdapterMemory.LED_RGBAW:
                pwm[3] = white
            elif self._led[0] == GulpLightAdapterMemory.LED_WHITE:
                pwm[1] = white
        else:
            DigitizerError("Unknown color: %s" % (color))

        self._write_to_driver(0x02, pwm)  # PWM addr
        # enable/disable drivers
        out = 0
        for i in (range(0, len(pwm))):
            out = out << 2
            if pwm[len(pwm)-i-1] > 0:
                out |= 0b10
        self._write_to_driver(0x0C, [out & 0xFF, out >> 8])  # LED driver output state registers

class GulpLight8xPWMAdapter_0103(GulpLight8xPWMAdapter):
    # channel #0 is used for general on/off because default output level is 5V after power cycle.
    # Class code will switch off which is what we need.
    pass

## First board with 20-pin header, powered by 24V. Hotplug AOT (adapter-on-top) adapters
class GulpExtensionBoardMemory(GulpBoardMemory):
    LED_WHITE = 1
    LED_IR = 2
    LED_RGB = 3

    CUSTOM_MAP = [
        ("led1", "number", 1, "LED connected to slot 1", LED_WHITE, {0: "none", LED_WHITE: "white", LED_IR: "IR"}),
        ("led2", "number", 1, "LED connected to slot 2", 0, {0: "none", LED_IR: "IR", LED_RGB: "RGB"}),
        ("pwr_button", "number", 1, "Power button on RPI 5 board driven by Sleep button", 0),
    ]

class GulpExtensionBoard(ExtensionBoardWithI2C):
    XBOARD_MEMORY_ADDR = 0b1010100 # 24LCxx EEPROM on main board
    LIGHT_NAME = "light"
    BOARD_MEMORY_CLASS = GulpExtensionBoardMemory
    ID = "MAIN"

    def __init__(self, mainboard, callback):
        # we need memory instance early during initialization
        i2c = self._get_i2c_configuration()
        self._xboard_memory = self.BOARD_MEMORY_CLASS(mainboard, i2c["addr"]["main_eeprom"], i2c["eeprom_page_size"])
        self._aot_memory = GulpAdapterMemory(mainboard, i2c["addr"]["aot_eeprom"], i2c["eeprom_page_size"])
        self._light_memory = GulpAdapterMemory(mainboard, i2c["addr"]["light_eeprom"], i2c["eeprom_page_size"])
        self._custom_data = self._xboard_memory.read_custom()
        super().__init__(mainboard, callback)
        self._light_adapter = self.get_adapter(self.LIGHT_NAME)

    def get_xboard_class_by_version(version):
        if version == None:
            raise DigitizerError("X-board version is not defined")
        if version >= 103:
            res = GulpExtensionBoard_0103
        elif version >= 102:
            res = GulpExtensionBoard_0102
        elif version >= 101:
            res = GulpExtensionBoard_0101
        else:
            res = GulpExtensionBoard
        logging.getLogger().debug("Version %s resolved as %s" % (version, res))
        return res

    def get_xboard_class(mainboard):
        eeprom = GulpExtensionBoardMemory(mainboard, GulpExtensionBoard.XBOARD_MEMORY_ADDR, 1)
        # TODO: test board_id == GULP ??
        ver = eeprom.get_version()
        return GulpExtensionBoard.get_xboard_class_by_version(ver)

    def _set_backlight_impl(self, color, intensity):

        led_off = {"led_white": 0, "led_ir": 0, "led_external": 0, "led_pwm": 0, }
        if color == None:
            self.set_io_states(led_off)
        elif color == "white":
            self.set_io_states(led_off | {"led_white": intensity > 0, "led_pwm": intensity, })
        elif color == "ir":
            self.set_io_states(led_off | {"led_ir": intensity > 0, "led_pwm": intensity, })
        elif color == "external":
            self.set_io_states(led_off | {"led_external": intensity > 0, "led_pwm": intensity, })
        else:
            raise DigitizerError("Color '%s' is not supported" % color)

    def get_capabilities(self):
        result = super().get_capabilities()
        result |= {
            "sleep": True,
            "hot_plug": True,
        }
        if not result["backlight_control"]:
            # do board light only when not managed by light adapter
            result |= {
                "backlight_control": True,
                "white_backlight": GulpExtensionBoardMemory.LED_WHITE in [self._custom_data["led1"], self._custom_data["led2"]],
                "ir_backlight": GulpExtensionBoardMemory.LED_IR in [self._custom_data["led1"], self._custom_data["led2"]],
            }
        return result

    def get_adapter_class_by_name(id_ver):
        id = id_ver[0]
        ver = id_ver[1]
        if id == "NIKON":
            if ver >= 103:
                res = GulpNikonStepperMotorAdapter_0103
            else:
                res = GulpNikonStepperMotorAdapter
        elif id == "STEPPER":
            if ver >= 103:
                res = GulpStepperMotorAdapter_0103
            elif ver >= 101:
                res = GulpStepperMotorAdapter_0101
            else:
                res = GulpStepperMotorAdapter
        elif id == "MANUAL":
            res = GulpManualAdapter
        elif id == "LGHT8PWM":
            if ver >= 103:
                res = GulpLight8xPWMAdapter_0103
            else:
                res = GulpLight8xPWMAdapter
        else:
            res = None
        logging.getLogger().debug("Id: %s resolved as %s" % (id_ver, res))
        return res

    def _get_connected_adapter_class_impl(self):
        adapters = {}
        try:
            logging.getLogger().debug("%s checking hotplug adapter" % (__name__))
            id_ver = self._aot_memory.get_id_version()
            logging.getLogger().debug("got: id_ver:%s" % (id_ver, ))
            if id_ver != None:
                adapters[super().AOT_NAME] = GulpExtensionBoard.get_adapter_class_by_name(id_ver)
        except OSError:
            pass
        try:
            logging.getLogger().debug("%s checking light adapter" % (__name__))
            id_ver = self._light_memory.get_id_version()
            logging.getLogger().debug("got: id_ver: %s" % (id_ver, ))
            if id_ver != None:
                adapters[self.LIGHT_NAME] = GulpExtensionBoard.get_adapter_class_by_name(id_ver)
        except OSError:
            pass
        return adapters

    def _get_i2c_configuration(self):
        return super()._get_i2c_configuration() | {
            "bus_id": 1,
            "addr": {
                "rtc": 0b1101111, # MCP79400
                "rtc_eeprom": 0b1010111, # MCP79400 EEPROM
                "main_eeprom": self.XBOARD_MEMORY_ADDR,
                "aot_eeprom": 0b1010101, # 24LCxx EEPROM on adapter board
                "light_eeprom": 0b1010110, # 24LCxx EEPROM on light adapter board
            },
            "eeprom_page_size": 8,
        }

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["in_out_1"]["num"] = 21
        result["in_out_2"]["num"] = 20
        result["in_out_3"]["num"] = 26
        result["in_out_4"]["num"] = 19
        result |= {
            "focus": {
                "dir": "o",
                "type": "gpio",
                "num": 25,
            },
            "shutter": {
                "dir": "o",
                "type": "gpio",
                "num": 24,
            },
            "led_white": {
                "dir": "o",
                "type": "gpio",
                "num": 17,
                "init": 0,
            },
            "led_ir": {
                "dir": "o",
                "type": "gpio",
                "num": 27,
                "init": 0,
            },
            "led_external": {
                "dir": "o",
                "type": "gpio",
                "num": 22,
                "init": 0,
                "unused": True,
            },
            "led_pwm": {
                "dir": "o",
                "type": "pwm",
                "init": 0,
                "num": 1,
                "gpio": 13,
            },
            "psu_sensor": {
                "dir": "o",
                "type": "gpio",
                "num": 18,
                "init": 1,
                "unused": True,
            },
            "xio_int": {
                "dir": "i",
                "type": "gpio",
                "num": 16,
                "hidden": True,
                "pud": "up",
                "trigger": "falling",
                "unused": True,
            },
            "sleep_button": {
                "dir": "i",
                "type": "gpio",
                "num": 4,
                "pud": "up",
                "trigger": "both",
                "negative": True,
                "hidden": False,
            },
            "in_out_5": {
                "dir": "o",
                "type": "gpio",
                "num": 23,
                "hidden": True,
                "unused": True,
            },
            "in_out_6": {    # x_pwm
                "dir": "o",
                "type": "gpio",
                "num": 12,
                "hidden": True,
                "unused": True,
            },
        }
        sensor_gpios = {
            "sensor_r": 6,
            "sensor_f": 5,
            "sensor_m": 7,
            "detect_aot": 8,
        }
        for name in list(sensor_gpios):
            result[name] |= {
                "type": "gpio",
                "negative": True,
                "num": sensor_gpios[name],
                "trigger": "both",
                "unused": True,
            }
        return result

# Board with RGB support
class GulpExtensionBoard_0101(GulpExtensionBoard):

    def _set_backlight_impl(self, color, intensity):
        led_off = {"led_white": 0, "led_ir": 0, "led_external": 0, "led_pwm": 0, "led_red": 0, "led_green": 0, "led_blue": 0, }
        if color == None:
            self.set_io_states(led_off)
        elif color == "white":
            if self._white_as_rgb:
                self.set_io_states(led_off | {"led_red": intensity > 0, "led_green": intensity > 0, "led_blue": intensity > 0, "led_pwm": intensity, })
            else:
                self.set_io_states(led_off | {"led_white": intensity > 0, "led_pwm": intensity, })
        elif color == "ir":
            self.set_io_states(led_off | {"led_ir": intensity > 0, "led_pwm": intensity, })
        elif color == "external":
            self.set_io_states(led_off | {"led_external": intensity, })
        elif color == "red":
            self.set_io_states(led_off | {"led_red": intensity > 0, "led_pwm": intensity, })
        elif color == "green":
            self.set_io_states(led_off | {"led_green": intensity > 0, "led_pwm": intensity, })
        elif color == "blue":
            self.set_io_states(led_off | {"led_blue": intensity > 0, "led_pwm": intensity, })
        elif color == "red+green":
            self.set_io_states(led_off | {"led_red": intensity > 0, "led_green": intensity > 0, "led_pwm": intensity, })
        elif color == "red+blue":
            self.set_io_states(led_off | {"led_red": intensity > 0, "led_blue": intensity > 0, "led_pwm": intensity, })
        elif color == "green+blue":
            self.set_io_states(led_off | {"led_green": intensity > 0, "led_blue": intensity > 0, "led_pwm": intensity, })
        elif color == "red+green+blue":
            self.set_io_states(led_off | {"led_red": intensity > 0, "led_green": intensity > 0, "led_blue": intensity > 0, "led_pwm": intensity, })
        else:
            raise DigitizerError("Color '%s' is not supported" % color)
        logging.getLogger().debug(f"LED: %s, wrgb: %s", self.get_io_states(list(led_off)), self._white_as_rgb)

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["in_out_3"]["num"] = 14
        result |= {
            "led_red": {
                "dir": "o",
                "type": "gpio",
                "num": 27,
                "init": 0,
            },
            "led_green": {
                "dir": "o",
                "type": "gpio",
                "num": 22,
                "init": 0,
            },
            "led_blue": {
                "dir": "o",
                "type": "gpio",
                "num": 10,
                "init": 0,
            },
            "led_external": {
                "dir": "o",
                "type": "pwm",
                "num": 0,
                "init": 0,
                "gpio": 12,
                "freq": 5000,
            },
            "in_out_5": {
                "dir": "o",
                "type": "gpio",
                "num": 15,
                "hidden": True,
                "unused": True,
            },
        }
        if GulpExtensionBoardMemory.LED_IR == self._custom_data["led2"]:
            result["led_ir"]["num"] = result["led_red"]["num"]
            result["led_red"]["unused"] = True
        elif GulpExtensionBoardMemory.LED_IR == self._custom_data["led1"]:
            result["led_ir"]["num"] = result["led_white"]["num"]
            result["led_white"]["unused"] = True
        else:
            result["led_ir"]["unused"] = True
        self._white_as_rgb = GulpExtensionBoardMemory.LED_WHITE != self._custom_data["led1"] and GulpExtensionBoardMemory.LED_RGB == self._custom_data["led2"]

        return result

    def get_capabilities(self):
        result = super().get_capabilities()
        result |= {
            "rgb_backlight": self._custom_data["led2"] == GulpExtensionBoardMemory.LED_RGB,
        }
        return result

# Board with extranal light control board and adapter detection signal
class GulpExtensionBoard_0102(GulpExtensionBoard):
    def __init__(self, mainboard, callback):
        super().__init__(mainboard, callback)
        self._light_adapter = self.get_adapter(self.LIGHT_NAME)
        if self._light_adapter != None:
            self._light_adapter_capabilities = self._light_adapter.get_capabilities()

    def _set_backlight_impl(self, color, intensity):
        led_off = {"led_white": 0, "led_external": 0, }
        if self._light_adapter != None:
            if color == "external":
                self._light_adapter.set_backlight(None)
                self.set_io_states(led_off | {"led_external": intensity, })
            else:
                self._light_adapter.set_backlight(color, intensity)
                self.set_io_states(led_off)
        else:
            if color == None:
                self.set_io_states(led_off)
            elif color == "white":
                self.set_io_states(led_off | {"led_white": intensity, })
            elif color == "external":
                self.set_io_states(led_off | {"led_external": intensity, })
            else:
                raise DigitizerError("Color '%s' is not supported" % color)

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result["in_out_3"]["num"] = 14
        result["led_ir"]["unused"] = True
        result |= {
            "led_white": {
                "dir": "o",
                "type": "pwm",
                "init": 0,
                "num": 1,
                "gpio": 13,
                "freq": 100000,
            },
            "led_indicator": {
                "dir": "o",
                "type": "gpio",
                "num": 17,
                "init": 0,
            },
            "led_external": {
                "dir": "o",
                "type": "pwm",
                "num": 0,
                "init": 0,
                "gpio": 12,
                "freq": 30000,
            },
            "in_out_5": {
                "dir": "o",
                "type": "gpio",
                "num": 15,
                "hidden": True,
                "unused": True,
            },
        }
        return result

class GulpExtensionBoard_0103(GulpExtensionBoard_0102):
    PLUG_DELAY = 0.7

    def __init__(self, mainboard, callback):
        super().__init__(mainboard, callback)
        self.set_io_state("xpwr", 1)
        self._last_detect_aot = self.get_io_state("detect_aot")

    def _get_io_configuration(self):
        result = super()._get_io_configuration()
        result |= {
            "xpwr": {
                "dir": "o",
                "type": "gpio",
                "init": 0,
                "num": 27,
                "hidden": True,
            },
        }
        result["detect_aot"]["negative"] = False
        result["detect_aot"]["unused"] = False
        if self._custom_data["pwr_button"]:
            result |= {
                "sleep_button": {
                    "dir": "i",
                    "type": "input_device",
                    "id_name": "pwr_button",  # input device id in OS, see /proc/bus/input/devices
                    "num": "KEY_POWER",   # 116
                    "trigger": "both",
                    "hidden": False,
                },
            }
        return result

    def on_gpio_change(self, source):
        """
            detect adapter change
        """
        super().on_gpio_change(source)
        if not self._initialized:
            return
        if self._last_detect_aot != self.get_io_state("detect_aot"):
            self._last_detect_aot = self.get_io_state("detect_aot")
            if self._last_detect_aot:
                # take some time to get power and also partial connector plug is an issue
                time.sleep(self.PLUG_DELAY)
            self.check_connected_adapter()
            self._call_notify_callback("hotplug")


    def get_capabilities(self):
        result = super().get_capabilities()
        result["aot_detection"] = True
        return result


global registered_boards
registered_boards = [
    GulpExtensionBoard,
    GulpNikonStepperMotorAdapter,
    GulpStepperMotorAdapter,
    GulpManualAdapter,
    GulpLight8xPWMAdapter,
]


