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
from threading import Thread, Event, Timer, Lock
from datetime import timedelta, datetime
from timeit import default_timer
import logging
import time
import re

## @package digie35core
# Core library for Digie35

## Periodic task triggered in specific timeout
class Job(Thread):
    def __init__(self, interval, execute, *args, **kwargs):
        Thread.__init__(self)
        self.daemon = False
        self.stopped = Event()
        self.interval = interval
        self.execute = execute
        self.args = args
        self.kwargs = kwargs

    def stop(self):
        self.stopped.set()
        self.join()


    def run(self):
        # logging.getLogger().debug("job interval: %s s, %s Hz" %(self.interval, 1/self.interval.total_seconds() if self.interval.total_seconds() > 0 else 0))
        while not self.stopped.wait(timeout=self.interval.total_seconds()):
            new_interval = self.execute(*self.args, **self.kwargs)
            if new_interval != None and new_interval != self.interval:
                self.interval = new_interval
                # logging.getLogger().debug("job new interval: %s s, %s Hz" %(self.interval, 1/self.interval.total_seconds() if self.interval.total_seconds() > 0 else 0))



## General error
class DigitizerError(Exception):
    pass

class Mainboard:
    def __init__(self):
        self._xboard = None

    def __del__(self):
        pass

    def assign_extension_board(self, xboard):
        self._xboard = xboard

    def set_gpio_function(self, num, func):
        pass

    def set_gpio_as_input(self, num, pull_up_down):
        pass

    def set_gpio_as_output(self, num, init_hi):
        pass

    def set_gpio_event_handler(self, num, edge, name = None, handler = None):
        pass

    def set_gpio(self, num, val):
        pass

    def get_gpio(self, num):
        return 0

    def set_pwm(self, channel, duty_cycle, freq=None):
        pass

    def set_input_device(self, id_name):
        pass

    def get_input_device_state(self, id_name, num):
        pass

    def set_input_device_handler(self, id_name, num, edge, name = None, handler = None):
        pass

    def debug(self, name, **kwargs):
        pass

## Abstract class for extension board connected on CPU mainboard
class ExtensionBoard:

    VERSION = "0.2"
    AOT_NAME = "AOT"

    def __init__(self, mainboard, callback):
        # logging.getLogger().debug("ExtensionBoard.__init__(%s)" % (mainboard))
        self._mainboard = mainboard
        self._mainboard.assign_extension_board(self)
        self._is_xio = False
        self._initialized = False
        self._timers = {}
        self._xio_input_mask = 0
        self._xio_negative_mask = 0
        self._xio_state = 0
        self._gpio_input_mask = 0
        self._gpio_negative_mask = 0
        self._gpio_state = 0
        self._pwm_state = {}
        self._notify_callback = callback
        self._adapters = {}
        self._callback_per_gpio = {}
        self._save_backlight_intensity = {}
        self._current_backlight_color = None
        self._merge_io_configuration()
        self._initialize_io_map(False)
        self._pending_notification = Event()

        self.check_connected_adapter()
        self.reset()
        self._initialized = True

    def __del__(self):
        pass

    def get_adapter(self, name = AOT_NAME):
        if name in list(self._adapters):
            return self._adapters[name]
        else:
            return None

    def check_connected_adapter(self):
        adapter_class = self._get_connected_adapter_class_impl()
        logging.getLogger().debug("Adapters: %s" % (adapter_class))
        flag = False
        for adapter_type in list(self._adapters):
            if not adapter_type in list(adapter_class) or adapter_class[adapter_type] != self.get_adapter(adapter_type).__class__:
                logging.getLogger().debug("Destroing adapter: %s" % (self.get_adapter(adapter_type).__class__))
                self._finalize_io_map(adapter_type)
                del self._adapters[adapter_type]
                self._merge_io_configuration()
                flag = True
        for adapter_type in list(adapter_class):
            if not adapter_type in list(self._adapters):
                logging.getLogger().debug("Creating adapter: %s" % (adapter_class[adapter_type]))
                self._adapters[adapter_type] = adapter_class[adapter_type](self)
                self._merge_io_configuration()
                self._initialize_io_map(adapter_type)
                self.get_adapter(adapter_type)._initialize_io_map()
                flag = True

        if not flag:
            logging.getLogger().debug("Adapter confirmed: %d" % len(self._adapters))

    def _get_connected_adapter_class_impl(self):
        return {}

    def _pulse_off_handler(self, *args, **kwargs):
        name = kwargs["name"]
        self.set_io_state(name, 1)
        self._add_and_start_timer(name, Timer(kwargs["on_secs"], self._pulse_on_handler, kwargs={"name": name}))

    def _pulse_on_handler(self, *args, **kwargs):
        name = kwargs["name"]
        self.set_io_state(name, 0)
        self._finalize_timer(name)

    def _add_and_start_timer(self, name, timer):
        self._cancel_timer(name)
        self._timers[name] = timer
        self._timers[name].start()

    def _finalize_timer(self, name):
        if self._timers.__contains__(name):
            del self._timers[name]

    def _cancel_timer(self, name):
        if self._timers.__contains__(name):
            self._timers[name].cancel()
            self._timers[name].join()
            self._finalize_timer(name)

    def _merge_io_configuration(self):
        io_map = self._get_io_configuration()
        unknown = []
        merged_adapter_io_map = {}
        for adapter_type in list(self._adapters):
            adapter_io_map = self.get_adapter(adapter_type)._get_io_configuration()

            unknown = []
            for name in list(adapter_io_map):
                if not name in list(io_map):
                    unknown.append(name)
                    continue
                # adapter alias is in collision with a xboard io name
                if "name" in list(adapter_io_map[name]) and adapter_io_map[name]["name"] != name and adapter_io_map[name]["name"] in list(io_map):
                    unknown.append(name)
                    continue
                merged_adapter_io_map[name] = adapter_io_map[name] | {"_scope": adapter_type}
        # logging.getLogger().debug("merged_adapter_io_map: %s" % (merged_adapter_io_map))

        if unknown != []:
            raise DigitizerError("Unknown/wrong io map options: %s" % (unknown))

        self._io_map = {}
        # filter active io and merge adapter ones
        for name in list(io_map):
            item = {"unused": False} | io_map[name]
            if name in list(merged_adapter_io_map):
                item["_adapter_scope"] = merged_adapter_io_map[name]["_scope"]
                del merged_adapter_io_map[name]["_scope"]
            else:
                item["_adapter_scope"] = False

            if item["_adapter_scope"]:
                item = item | {"unused": False} | merged_adapter_io_map[name]
                if "name" in list(item):
                    name = item["name"]   # rename io to adapter name
                    del item["name"]
            if item["unused"]:
                continue
            del item["unused"]
            self._io_map[name] = item
        logging.getLogger().debug("using io_map: %s" % (self._io_map))

    def _initialize_io_map(self, adapter_scope = False):

        is_xio = False
        xio_init = 0
        xio_output_mask = 0
        for name in list(self._io_map):
            item = self._io_map[name]
            if item["_adapter_scope"] != adapter_scope:
                continue

            negative = ("negative" in item) and item["negative"]
            if item["type"] == "xio":
                is_xio = True
                if item["dir"] == "i":
                    self._xio_input_mask |= 1 << item["num"]
                else:
                    self._xio_input_mask &= ~ (1 << item["num"])
                    xio_output_mask |= 1 << item["num"]
                    if "init" in item and item["init"]:
                        xio_init |= 1 << item["num"]
                if negative:
                    self._xio_negative_mask |= 1 << item["num"]
                else:
                    self._xio_negative_mask &= ~ (1 << item["num"])
            elif item["type"] == "gpio":
                self._mainboard.set_gpio_function(item["num"], item["type"])
                if negative:
                    self._gpio_negative_mask |= 1 << item["num"]
                else:
                    self._gpio_negative_mask &= ~ (1 << item["num"])
                if item["dir"] == "i":
                    pud = None
                    if "pud" in item:
                        if item["pud"] == "up":
                            pud = True
                        elif item["pud"] == "down":
                            pud = False
                    self._gpio_input_mask |= 1 << item["num"]
                    self._mainboard.set_gpio_as_input(item["num"], pud)
                    self._get_gpio(item["num"])
                    if "trigger" in item:
                        logging.getLogger().debug("GPIO event callback: %s(%s)" % (item["num"], item["trigger"]))
                        if "handler" in item:
                            self._mainboard.set_gpio_event_handler(item["num"], item["trigger"], name, item["handler"])
                        else:
                            self._mainboard.set_gpio_event_handler(item["num"], item["trigger"], name)
                else:
                    self._gpio_input_mask &= ~ (1 << item["num"])
                    val = "init" in item and item["init"]
                    self._mainboard.set_gpio_as_output(item["num"], val ^ negative)
                    self._set_gpio(item["num"], val)
            elif item["type"] == "pwm":
                self._mainboard.set_gpio_function(item["gpio"], item["type"])
                self._mainboard.set_pwm(item["num"], 0)
                self._pwm_state[name] = 0
            elif item["type"] == "i2c":
                self._mainboard.set_gpio_function(item["gpio"], item["type"])
            elif item["type"] == "input_device":
                self._mainboard.set_input_device(item["id_name"])
                if "trigger" in item:
                    if "handler" in item:
                        self._mainboard.set_input_device_handler(item["id_name"], item["num"], item["trigger"], name, item["handler"])
                    else:
                        self._mainboard.set_input_device_handler(item["id_name"], item["num"], item["trigger"], name)

        if is_xio:
            self._is_xio = True
            val = self._get_xio()
            if xio_output_mask != 0:
                self._set_xio((val & ~xio_output_mask) | xio_init)

    def _finalize_io_map(self, adapter_scope = False):
        for name in list(self._io_map):
            item = self._io_map[name]
            if item["_adapter_scope"] != adapter_scope:
                continue
            if item["type"] == "pwm":
                self._mainboard.set_pwm(item["num"], 0)
                self._pwm_state[name] = 0
            elif item["type"] == "gpio":
                if item["dir"] == "i":
                    if "trigger" in item:
                        if "handler" in item:
                            self._mainboard.set_gpio_event_handler(item["num"], "none", name, item["handler"])
                        else:
                            self._mainboard.set_gpio_event_handler(item["num"], "none", name)
            elif item["type"] == "input_device":
                if "trigger" in item:
                    if "handler" in item:
                        self._mainboard.set_input_device_handler(item["id_name"], item["num"], "none", name, item["handler"])
                    else:
                        self._mainboard.set_input_device_handler(item["id_name"], item["num"], "none", name)



    def _set_backlight_impl(self, color, intensity):
        pass

    def _set_xio(self, val):
        return

    def _get_xio(self, force = False):
        return 0

    def _set_gpio(self, num, val):
        val = int(val != 0)
        if self._gpio_negative_mask & (1<<num):
            val ^= 1
        self._mainboard.set_gpio(num, val)
        if (((self._gpio_state >> num) & 1) != val):
            self._gpio_state ^= 1<<num

    def _get_gpio(self, num):
        if (self._gpio_input_mask & (1<<num)):
            result = self._mainboard.get_gpio(num)
        else:
            result = (self._gpio_state >> num) & 1
        if self._gpio_negative_mask & (1<<num):
            result ^= 1
        return result

    def on_gpio_change(self, source):
        """
            Sensor state has changed
        """
        logging.getLogger().debug("%s: on_gpio_change(%s)" % (__name__, source))
        if not self._initialized:
            return
        for adapter_type in list(self._adapters):
            self.get_adapter(adapter_type).on_gpio_change(source)
        self._call_notify_callback(source)

    def _do_pending_notification(self, source, postpone_interval):
        self._pending_notification.wait(timeout=postpone_interval)
        # logging.getLogger().debug("Pending notification: %s" % (source))
        self._notify_callback({"source": source} | self.get_state())

    def _call_notify_callback(self, source, new_thread = False, postpone_interval = 0):
        if not self._initialized:
            return
        if self._notify_callback != None:
            # avoid notification flooding (e.g. backlight slidebar) so postpone callback call on demand
            if hasattr(self, "_notify_thread") and self._notify_thread.is_alive():
                # logging.getLogger().debug("Check pending: %s vs. %s" % (source, self._pending_source))
                if source != self._pending_source:
                    # call pending event immediately
                    self._pending_notification.set()
                    self._notify_thread.join()
                else:
                    return
            if new_thread:
                self._pending_source = source
                self._pending_notification.clear()
                # logging.getLogger().debug("Set pending notification: %s, %s" % (source, postpone_interval))
                self._notify_thread = Thread(target=self._do_pending_notification, kwargs={"source": source, "postpone_interval": postpone_interval})
                self._notify_thread.name = "notify"
                self._notify_thread.start()
            else:
                # logging.getLogger().debug("Normal notification: %s" % (source))
                self._notify_callback({"source": source} | self.get_state())

    # public stuff
    def get_id(self):
        """
            Get class identification
        """
        return f"%s:%s" % (type(self).__name__, self.VERSION)

    def get_capabilities(self):
        result = {
            # enumerate all supported capabilities
            "motorized": False,
            # "motorized": isinstance(self.get_adapter(), StepperMotorAdapter),
            "flattening": False,
            "camera_remote_control": True,  # RC via jack

            "white_backlight": False,
            "ir_backlight": False,
            "rgb_backlight": False,
            "rgbaw_backlight": False,
            "backlight_control": False,
            #"camera_remote_control": False,
            "jack_detection": False,

            "preview_backlight": False,
            "preview_backlight_control": False,
            "film_sensor": False,

            "aot_detection": False,
        }
        # logging.getLogger().debug("CORE::get_capabilities: %s" % self._adapters)
        for adapter_type in list(self._adapters):
            # logging.getLogger().debug("CORE::get_capabilities: %s" % adapter_type)
            result |= self.get_adapter(adapter_type).get_capabilities()
        return result

    def get_capability(self, cap):
        caps = self.get_capabilities()
        return caps.get(cap, False)

    def check_capability(self, cap):
        if not self.get_capability(cap):
            raise DigitizerError("Capability %s not supported" % cap)

    def reset(self):
        """
            Reset board, switch off output signals and motor
        """
        for name in list(self._io_map):
            if not self._io_map[name]["_adapter_scope"]:
                if not self._io_map[name]["type"] in ("xio", "i2c"):
                    if "init" in self._io_map[name]:
                        init = self._io_map[name]["init"]
                    else:
                        init = 0
                    self.set_io_state(name, init)
        for adapter_type in list(self._adapters):
            self.get_adapter(adapter_type).reset()
        self._set_xio(0)
        for key in list(self._timers):
            self._cancel_timer(key)
        self._get_xio(True)

    def get_state(self, force=False):
        """
            Get adapter and i/o state
        """
        self._get_xio(force)
        result = {
            "io": self.get_io_states(),
            "backlight": {
                "color": self._current_backlight_color if self._current_backlight_color != None else "",
            },
        }
        if result["backlight"]["color"] != "":
            result["backlight"]["intensity"] = self._save_backlight_intensity[self._current_backlight_color]

        for adapter_type in list(self._adapters):
            result |= self.get_adapter(adapter_type).get_state()
        return result

    def get_io_states(self, names = None):
        """
            Get all io states
        """
        if names is None:
            names = []
            for key in list(self._io_map):
                names.append(key)
        result = {}
        for name in names:
            if (name in list(self._io_map)) and (not "hidden" in list(self._io_map[name]) or not self._io_map[name]["hidden"]):
                state = self.get_io_state(name)
                if state != None:
                    result[name] = state
        return result

    def get_io_state(self, name):
        """
            Get particular io state
        """
        type = self._io_map[name]["type"]
        if type == "xio":
            xio_state = self._get_xio()
            if "num" in list(self._io_map[name]):
                return xio_state & (1 << self._io_map[name]["num"]) != 0
        elif type == "gpio":
            if "num" in list(self._io_map[name]):
                return self._get_gpio(self._io_map[name]["num"])
        elif type == "pwm":
            return self._pwm_state[name]
        elif type == "input_device":
            return self._mainboard.get_input_device_state(self._io_map[name]["id_name"], self._io_map[name]["num"])
        return None

    def set_io_states(self, vals):
        """
            Set more io states
        """
        xio_state = self._get_xio()
        for name in list(vals):
            if not name in list(self._io_map):
                continue
            if self._io_map[name]["type"] == "xio":
                num = self._io_map[name]["num"]
                if (vals[name] != 0):
                    xio_state = xio_state | (1<<num)
                else:
                    xio_state = xio_state & ~(1<<num)
            else:
                self.set_io_state(name, vals[name])
        if xio_state != self._get_xio():
            self._set_xio(xio_state)

    def set_io_state(self, name, val):
        type = self._io_map[name]["type"]
        if type == "xio":
            val = int(val != 0)
            num = self._io_map[name]["num"]
            xio_state = self._get_xio()
            if (((xio_state >> num) & 1) != val):
                xio_state = xio_state ^ (1 << num)
                self._set_xio(xio_state)
        elif type == "gpio":
            self._set_gpio(self._io_map[name]["num"], val)
        elif type == "pwm":
            max_pwm = 255
            if val > max_pwm:
                val = max_pwm
            if "min_duty_cycle" in self._io_map[name]:
                min_dc = self._io_map[name]["min_duty_cycle"]
                val2 = (max_pwm - min_dc) / max_pwm * val + min_dc
            else:
                val2 = val
            if "max_duty_cycle" in self._io_map[name]:
                max_dc = self._io_map[name]["max_duty_cycle"]
                val2 = val2 * max_dc / max_pwm
            else:
                val2 = val
            freq = None
            if "freq" in self._io_map[name]:
                freq = self._io_map[name]["freq"]
            self._mainboard.set_pwm(self._io_map[name]["num"], val2, freq)
            self._pwm_state[name] = val

    def pulse_output(self, name, off_secs, on_secs):
        """
            Make async pulse off->on->off
        """
        self._cancel_timer(name)
        if off_secs > 0:
            self.set_io_state(name, 0)
            self._add_and_start_timer(name, Timer(off_secs, self._pulse_off_handler, kwargs={"name":name, "on_secs":on_secs}))
        else:
            self.set_io_state(name, 1)
            self._add_and_start_timer(name, Timer(on_secs, self._pulse_on_handler, kwargs={"name":name}))

    def set_backlight(self, color = None, intensity = None):
        if color != None and intensity == -1:
            if color in self._save_backlight_intensity:
                intensity = self._save_backlight_intensity[color]
            else:
                intensity = 50
        self._set_backlight_impl(color, intensity)
        change_flag = self._current_backlight_color != color
        self._current_backlight_color = color
        if color != None:
            change_flag |= not color in self._save_backlight_intensity or self._save_backlight_intensity[color] != intensity
            self._save_backlight_intensity[color] = intensity
        if change_flag:
            self._call_notify_callback("backlight", True, 0.2)

    def get_current_backlight_color(self):
        return self._current_backlight_color

    def get_current_backlight_color_and_intensity(self):
        color = self._current_backlight_color
        if color != None:
            return (color, self._save_backlight_intensity[color])
        else:
            return (None, None)

    def _get_io_configuration(self):
        return {
            "in_out_1": {
                "dir": "o",
                "type": "gpio",
                "num": 0,
                "hidden": True,
                "unused": True,
            },
            "in_out_2": {
                "dir": "o",
                "type": "gpio",
                "num": 1,
                "hidden": True,
                "unused": True,
            },
            "in_out_3": {
                "dir": "o",
                "type": "gpio",
                "num": 2,
                "hidden": True,
                "unused": True,
            },
            "in_out_4": {
                "dir": "o",
                "type": "gpio",
                "num": 3,
                "hidden": True,
                "unused": True,
            },
            "sensor_f": {
                "dir": "i",
                "type": "xio",
                "num": 0,
                "unused": True,
            },
            "sensor_r": {
                "dir": "i",
                "type": "xio",
                "num": 1,
                "unused": True,
            },
            "sensor_m": {
                "dir": "i",
                "type": "xio",
                "num": 2,
                "unused": True,
            },
            "detect_aot": {
                "dir": "i",
                "type": "xio",
                "num": 3,
                "unused": True,
            },
        }

## Abstract class for extension board with used I2C
class ExtensionBoardWithI2C(ExtensionBoard):

    def __init__(self, mainboard, callback):
        # logging.getLogger().debug("ExtensionBoardWithI2C.__init__(%s)" % (mainboard))
        self._i2c = self._get_i2c_configuration()
        super().__init__(mainboard, callback)

    def _get_i2c_configuration(self):
        return {}

    def _get_io_configuration(self):

        result = super()._get_io_configuration()
        result |= {
            "i2c_scl": {
                "type": "i2c",
                "gpio": 3,
            },
            "i2c_sda": {
                "type": "i2c",
                "gpio": 2,
            },
        }
        return result


    def _set_xio(self, val):
        if not self._is_xio:
            return super()._set_xio(val)
        val ^= self._xio_negative_mask
        self._mainboard.debug("set_xio_input", i2c_addr = self._i2c["addr"]["xio"], value = val, input_mask = self._xio_input_mask)
        val |= self._xio_input_mask # input pins are always pulled up
        self._mainboard.i2c_write_read(self._i2c["addr"]["xio"], [val], 0)
        self._xio_state = (self._xio_state & self._xio_input_mask) | (val & ~self._xio_input_mask)

    def _get_xio(self, force = False):
        if not self._is_xio:
            return super()._get_xio(force)
        if force:
            val = self._mainboard.i2c_write_read(self._i2c["addr"]["xio"], None, 1)[0]
            val ^= self._xio_negative_mask
            self._xio_state = val  # read input status of outputs or force output values ???
        return self._xio_state

class BoardMemory:
    def __init__(self):
        pass

    def _read_impl(self, addr, count):
        pass

    def _write_impl(self, addr, data):
        pass

    def read_number(self, addr, count, signed = False):
        data = self.read_array(addr, count)
        res = 0
        for i in range(0, count):
            res += data[i] << (i * 8)
        if not signed and res == (1 << 8*count) - 1:
            # uninitialized value
            return None
        if signed and (res & (1<<(8*count-1)) != 0):
            mask = 0
            for i in range(0, count):
                mask = mask << 8 | 0xFF
            res = ~res + mask
        return res

    def write_number(self, addr, val, count):
        if val == None:
            val = 0
        data = []
        for i in range(0, count):
            data.append(val & 0xFF)
            val >>= 8
        self.write_array(addr, data)

    def read_array(self, addr, count):
        return self._read_impl(addr, count)

    def write_array(self, addr, data):
        self._write_impl(addr, data)

    def read_string(self, addr, max_len):
        ret = ""
        data = self.read_array(addr, max_len)
        if data[0] == 0xFF:
            # uninitialized value
            return None
        i = 0
        while i < len(data):
            if data[i] == 0:
                break
            ret += chr(data[i])
            i += 1
        return ret

    def write_string(self, addr, str, max_len):
        if str == None:
            str = ""
        data = []
        i = 0
        while i < len(str) and i < max_len:
            data.append(ord(str[i]))
            i += 1
        while i < max_len:
            data.append(0)
            i += 1
        self.write_array(addr, data)

class SerialEeprom(BoardMemory):
    def __init__(self, mainboard, i2c_addr, page_size):
        super().__init__()   # Atmel has 8 byte page size
        self._mainboard = mainboard
        self._i2c_addr = i2c_addr
        self._page_size = page_size

    def _read_impl(self, addr, count):
        return self._mainboard.i2c_write_read(self._i2c_addr, [addr], count)

    def _write_impl(self, addr, data):
        count = len(data)
        i = 0
        while count > 0:
            page_end = (addr & ~(self._page_size - 1)) + self._page_size
            if page_end - addr >= count:
                l = count
            else:
                l = page_end - addr
            # print("DEBUG: write addr: %s, page: %s, l: %s, i: %s, data: %s" % (addr, page_end, l, i, data[i:i+l]))
            self._mainboard.i2c_write_read(self._i2c_addr, [addr] + data[i:i+l], 0)
            addr += l
            i += l
            count -= l
            time.sleep(0.01)   # 5ms EEPROM write delay (otherwise check ACK)


class Adapter:
    ID = "_abstract_"
    def __init__(self, xboard):
        self._xboard = xboard
        self._props = {}

    def __del__(self):
        pass

    def get_state(self):
        return {}

    def reset(self):
        for name in list(self._xboard._io_map):
            io = self._xboard._io_map[name]
            if io["_adapter_scope"] == self.ID:
                if io["type"] != "xio":
                    if "init" in io:
                        init = io["init"]
                    else:
                        init = 0
                    self._xboard.set_io_state(name, init)

    def _initialize_io_map(self):
        pass

    def _get_io_configuration(self):
        return {}

    def get_capabilities(self):
        # logging.getLogger().debug("%s::get_capabilities" % self.__class__.__name__)
        return {}

    # support custom properties
    def set_property(self, name, value):
        self._props[name] = value

    def get_property(self, name, default = None):
        return self._props.get(name, default)

    def on_gpio_change(self, source):
        pass

## Abstract motorized adapter for stepper motors
class StepperMotorAdapter(Adapter):
    _PERFORATION_HOLE_DISTANCE = 4.75 # mm
    _PERFORATION_HOLE_WIDTH = 1.98 # mm
    _FRAME_WIDTH = 36.5 # mm
    _MAX_GEAR = 4
    _MIN_SENSOR_WIDTH = 6   # ignore short random peaks when detecting perforation

    def __init__(self, xboard, **kwargs):
        super().__init__(xboard)
        self._motor_current_dir = 0
        self._motor_current_action = None
        self._motor_position = 0   # soft backlash compensated position
        self._raw_motor_position = 0   # just calculated motor steps
        self._film_position = 0  # calculated position in mm using sensors and motor steps
        self._backlash = {
            "compensation": -1,
            "position": 0,
        }
        self._sensor_distance = {
            "front": 0,
            "rear": 0,
        }
        self._motor_lock = Lock()
        self._last_forward = None,   # last direction when motor moved, i.e. ignores stop state
        self._frame_counters = {}
        self._film_sensing = {
            "state": {
                "shot_ready": False,
                "light_ready": False,
                "insert_ready": False,
                "controlled": False,
            },
            "pos": {
            },
        }
        self._save_backlight_color = None
        self._counters = {
            "front": "sensor_f",
            "rear": "sensor_r",
            "window": "sensor_m",
        }
        for key in list(self._counters):
            self._film_sensing["state"][key] = False
            self._film_sensing["pos"][key] = None

            self._frame_counters[key] = {
                "counter": 0,
                "motor_position": 0,
                "positions": {},
                "pending": {},
            }
        self.set_propery("MAX_MOTOR_RUN", 180.0)  # to avoid overheating

    def __del__(self):
        super().__del__()
        self.set_motor(0)

    def _initialize_io_map(self):
        super()._initialize_io_map()
        # fixup when xboard._io_map has been initialized
        input_names = []
        for key in list(self._counters):
            input_names.append(self._counters[key])
        inputs = self._xboard.get_io_states(input_names)
        for key in list(self._counters):
            self._frame_counters[key]["state"] = inputs[self._counters[key]]

    def _do_step_impl(self):
        pass

    def _do_on_start(self, direction):
        pass

    def _do_on_stop(self, next_direction):
        pass

    def get_steps_per_mm(self):
        pass

    ## get required stepping freq, acceleration
    def _get_stepper_params(self, speed):
        return (self._SPEED_TO_FREQ[abs(speed)-1], )

    def get_state(self, force=False):
        counters = {"motor": self._motor_position, }
        for key in list(self._frame_counters):
            counters[key] = self._frame_counters[key]["counter"]
        result = {
            "movement": self._motor_current_dir,   # atomic ?
            "frame_ready": self._film_sensing["state"]["shot_ready"],
            "film_detected": self._film_sensing["state"]["front"] or self._film_sensing["state"]["rear"],
            "film_position": round(self._film_position, 3),
            "insert_ready":  self._film_sensing["state"]["insert_ready"],
            #"counters": counters,
        }
        if (self._motor_current_action != None):
            result["action"] = self._motor_current_action["cmd"]
        return super().get_state() | result

    def on_gpio_change(self, source):
        """
            Sensor state has changed
        """
        # logging.getLogger().debug("%s" % __name__)
        super().on_gpio_change(source)
        self._xboard._get_xio(True)
        input_names = []
        for key in list(self._counters):
            input_names.append(self._counters[key])
        inputs = self._xboard.get_io_states(input_names)
        # TODO: atomic ??
        motor_dir = max(-1, min(1, self._motor_current_dir))
        motor_pos = self._motor_position

        logging.getLogger().debug("gpio_inchange: %s", inputs)

        for key in list(self._frame_counters):
            if self._frame_counters[key]["state"] != inputs[self._counters[key]]:
                # manual film movement are not considered as direction is unknown
                self._frame_counters[key]["counter"] += motor_dir
                self._frame_counters[key]["motor_position"] = motor_pos
                self._frame_counters[key]["state"] = inputs[self._counters[key]]

        self._adjust_film_detected()

    def get_capabilities(self):
        result = {
            "motorized": True,
            "film_sensor": True,
        }
        return result

    def reset(self):
        super().reset()
        self.set_motor(0)

    def set_motor(self, direction, action = None):
        """
            Control transport speed and direction
        """
        self._motor_lock.acquire()
        try:
            direction = min(self._MAX_GEAR, max(-self._MAX_GEAR, direction))
            if action == None:
                action = {"cmd": "MOVE"}

            logging.getLogger().debug("motor: dir: %s, action: %s", direction, action)
            if direction != self._motor_current_dir or self._motor_current_action == None or self._motor_current_action["cmd"] != action["cmd"]:
                if hasattr(self, "_motor_job"):
                    logging.getLogger().debug("_motor_job: %s", self._motor_job)
                    self._motor_job.stop()
                    self._do_on_stop(direction)
                    del self._motor_job
                self._motor_current_action = action
                self._motor_current_dir = direction
                self._xboard._call_notify_callback("motor", True, 0)
                if direction != 0:
                    params = self._get_stepper_params(direction)
                    logging.getLogger().debug("Stepper params: %s", params)
                    freq = params[0]
                    self._start_timestamp = default_timer()
                    self._start_ramping_time = self._start_timestamp
                    self._start_freq = 0
                    self._ramping_time = (freq / params[1]) if params[1] > 0 else 0
                    interval = timedelta(seconds=0)  # first step immediately regardless speed/acceleration
                    if hasattr(self, "_motor_handler_storage"):
                        del self._motor_handler_storage
                    frame_counters = {}
                    for key in list(self._frame_counters):
                        frame_counters[key] = self._frame_counters[key]["counter"]   # copy value as it passed by reference
                    self._motor_job = Job(interval=interval, execute=self._motor_handler, start_position={"motor": self._motor_position, "film": self._film_position, }, start_frame_counters=frame_counters, action=action, req_freq=freq)
                    self._do_on_start(direction)
                    self._motor_job.start()
        finally:
            self._motor_lock.release()

    def _adjust_motor_position(self, forward):
        if forward:
            step_dir = 1
        else:
            step_dir = -1
        self._raw_motor_position += step_dir

        if self._film_sensing["state"]["controlled"]:
            if self._last_forward != forward:
                # initialize counter to measure position in mm
                cnt = {"motor": None, "film": None, }
                for key in list(self._frame_counters):
                    self._frame_counters[key]["positions"] = {
                        "pending": None,
                        "state": self._frame_counters[key]["state"],
                        "level": [cnt.copy(), cnt.copy()],
                    }
                self._last_forward = forward
        else:
            self._last_forward = None
        # NOTE: we cannot calculate automatically backlash by sensors as they have hysteresis and position of edge
        # is related to perforation relatively, no idea when signal change is triggered. Sensor can be safely used
        # to movement test but only in one direction. Forward ans reverse direction are totaly unrelated for our reason.

        if self._backlash["compensation"] > 0:
            # when direction has been change the there is grey space where output is steady even motor is moving
            # logging.getLogger().debug("Backlash compensation: %s, %s" % (self._backlash["compensation"], self._backlash["position"]))
            if self._backlash["position"] > self._backlash["compensation"]:
                self._backlash["position"] = self._backlash["compensation"]
            if forward and self._backlash["position"] < self._backlash["compensation"]:
                self._backlash["position"] += 1
                return
            elif not forward and self._backlash["position"] > 0:
                self._backlash["position"] -= 1
                return

        self._motor_position += step_dir

        film_nom = 0
        film_denom = 0
        if self._film_sensing["state"]["controlled"]:
            for key in list(self._frame_counters):
                st = self._frame_counters[key]["state"]
                if self._frame_counters[key]["positions"]["state"] != st:
                    if self._frame_counters[key]["positions"]["pending"] != None:
                        cnt = abs(self._frame_counters[key]["positions"]["pending"] - self._motor_position)
                        if cnt >= self._MIN_SENSOR_WIDTH:  # avoid some unstable peaks
                            # now we have the confirmed edge and we can calculate distance since last edge of the same sense
                            film = self._frame_counters[key]["positions"]["level"][st]["film"]
                            if film != None:
                                film += step_dir * self._PERFORATION_HOLE_DISTANCE
                            else:
                                film = self._film_position

                            self._frame_counters[key]["positions"]["level"][st]["motor"] = self._motor_position
                            self._frame_counters[key]["positions"]["level"][st]["film"] = film
                            self._frame_counters[key]["positions"]["state"] = st
                            self._frame_counters[key]["positions"]["pending"] = None
                    else:
                        self._frame_counters[key]["positions"]["pending"] = self._motor_position
                else:
                    self._frame_counters[key]["positions"]["pending"] = None

                # calculate average of sensor related positions
                for st in range(0, 2):
                    film = self._frame_counters[key]["positions"]["level"][st]["film"]
                    if film != None:
                        film_nom += film + (self._motor_position - self._frame_counters[key]["positions"]["level"][st]["motor"]) / self.get_steps_per_mm()
                        film_denom += 1

        if film_denom == 0:
            self._film_position += step_dir / self.get_steps_per_mm()
        else:
            self._film_position = film_nom / film_denom

    def _motor_handler(self, *args, **kwargs):
        # logging.getLogger().debug("motor_handler: args: %s, kwargs: %s", args, kwargs)
        self._do_step_impl()
        self._adjust_film_detected()
        action = kwargs["action"]
        if action != None:
            stop = False
            if action["cmd"] == "LEAD_IN":
                if self._motor_current_action["phase"] == 0:
                    if self._film_sensing["state"]["controlled"]:  # just passed over middle sensor
                        self._motor_current_action["phase"] = 1
                        self._motor_current_action["position"] = self._motor_position

                        logging.getLogger().debug("LEAD_IN film detected: %d", self._motor_position)
                    else:
                        lead_in_steps = self._sensor_distance["front"] * self.get_steps_per_mm()
                        if self._motor_position - kwargs["start_position"]["motor"] > lead_in_steps:
                            logging.getLogger().debug("LEAD_IN stopped: %d-%d > %d", self._motor_position, kwargs["start_position"]["motor"], lead_in_steps)
                            stop = True
                else:
                    window_width = self._FRAME_WIDTH * self.get_steps_per_mm() / 2
                    if self._motor_position - self._motor_current_action["position"] > window_width:
                        logging.getLogger().debug("LEAD_IN stopped2: %d-%d > %d", self._motor_position, self._motor_current_action["position"], window_width)
                        stop = True
            elif action["cmd"] == "EJECT":
                if self._motor_current_action["phase"] == 0:
                    # when film is not detected allow some time to detect or stop
                    if abs(self._motor_position - kwargs["start_position"]["motor"]) > self._PERFORATION_HOLE_DISTANCE * self.get_steps_per_mm():
                        self._motor_current_action["phase"] = 1
                elif not self._film_sensing["state"]["front"] and not self._film_sensing["state"]["rear"]:
                    stop = True
            elif action["cmd"] == "MOVE_BY":
                if abs(self._film_position - kwargs["start_position"]["film"]) >= action["mm"]:
                    logging.getLogger().debug("MOVE_BY stopped:abs(%d-%d) >= %d", self._film_position, kwargs["start_position"]["film"], action["mm"])
                    stop = True
                #if abs(self._motor_position - kwargs["start_position"]["motor"]) >= action["step_count"]:
                #    logging.getLogger().debug("MOVE_BY emergency stopped:abs(%d-%d) >= %d", self._motor_position, kwargs["start_position"]["motor"], action["step_count"])
                #    stop = True
            if not stop:
                interval = default_timer() - self._start_timestamp
                if interval > self.get_property("MAX_MOTOR_RUN"):
                    stop = True
                    logging.getLogger().debug("Motor autostopped (%s)", interval)
            if stop:
                self._motor_job.stopped.set()
                self._do_on_stop(0)
                self._motor_current_dir = 0
                self._motor_current_action = None
                self._xboard._call_notify_callback("motor")
            else:
                return self._get_next_interval(kwargs["req_freq"])

    ## Consider acceleration to adjust speed smoothly, i.e. ramping
    def _get_next_interval(self, req_freq):
        delta = default_timer() - self._start_ramping_time
        if delta >= self._ramping_time:
            freq = req_freq
        else:
            freq = max((req_freq - self._start_freq) * delta / self._ramping_time, 10)  # avoid long intervals when interpolation starts

        # logging.getLogger().debug("Adjust interval: freq: %s, req_freq: %s, start_freq: %s, deltat: %s, ramping time: %s" % (freq, req_freq, self._start_freq, delta, self._ramping_time))
        interval = timedelta(seconds=1/freq)
        return interval


    def _adjust_film_detected(self):
        # TODO: protect by lock ?
        # film is detected when reaches window sensor and undetected when leaves front/rear sensor control

        s1 = "%s" % (self._film_sensing, )
        try:
            steps_per_hole_limit = self._PERFORATION_HOLE_DISTANCE * self.get_steps_per_mm()
            for key in list(self._counters):
                if not self._film_sensing["state"][key] and not self._frame_counters[key]["state"]:
                    continue
                state = steps_per_hole_limit > abs(self._motor_position - self._frame_counters[key]["motor_position"])
                if self._film_sensing["state"][key] != state:
                    self._film_sensing["pos"][key] = self._frame_counters[key]["motor_position"]
                    self._film_sensing["state"][key] = state

            if not self._film_sensing["state"]["controlled"] and self._film_sensing["state"]["window"] and (self._film_sensing["state"]["rear"] or self._film_sensing["state"]["front"]):
                self._film_sensing["state"]["controlled"] = True
            if not self._film_sensing["state"]["light_ready"] and self._film_sensing["state"]["controlled"] and self._film_sensing["state"]["window"]:
                self._film_sensing["state"]["light_ready"] = True
                if self._save_backlight_color != None:
                    self._xboard.set_backlight(self._save_backlight_color, -1)
            if self._film_sensing["state"]["controlled"] and \
                ((not self._film_sensing["state"]["rear"] and not self._film_sensing["state"]["front"]) or \
                (self._film_sensing["state"]["rear"] and self._film_sensing["state"]["front"] and not self._film_sensing["state"]["window"])):  # pushed next film, i.e. 2 strips in adapter
                self._film_sensing["state"]["controlled"] = False
                for key in list(self._counters):
                    self._film_sensing["pos"][key] = None
            if self._film_sensing["state"]["light_ready"] and not self._film_sensing["state"]["window"]:
                self._film_sensing["state"]["light_ready"] = False
                self._save_backlight_color = self._xboard.get_current_backlight_color()
                self._xboard.set_backlight()
            # film is ready when whole film frame is raedy to shot, window sensor is mandatory but not sufficient
            if not self._film_sensing["state"]["shot_ready"] and self._film_sensing["state"]["controlled"] and self._film_sensing["state"]["window"]:
                self._film_sensing["state"]["shot_ready"] = \
                    self._film_sensing["state"]["window"] and \
                    (self._film_sensing["state"]["rear"] and self._film_sensing["state"]["front"]) or \
                    (self._film_sensing["state"]["front"] and self._film_sensing["pos"]["window"] != None and (self._motor_position > self._film_sensing["pos"]["window"] + self._FRAME_WIDTH/2 * self.get_steps_per_mm())) or \
                    (self._film_sensing["state"]["rear"] and self._film_sensing["pos"]["window"] != None and (self._motor_position < self._film_sensing["pos"]["window"] - self._FRAME_WIDTH/2 * self.get_steps_per_mm()))
            if self._film_sensing["state"]["shot_ready"]:
                if not self._film_sensing["state"]["window"] or not self._film_sensing["state"]["controlled"]:
                    self._film_sensing["state"]["shot_ready"] = False
                elif self._sensor_distance["front"] > 0 and not self._film_sensing["state"]["front"] and self._film_sensing["pos"]["front"] != None and \
                    (self._motor_position > self._film_sensing["pos"]["front"] + (self._sensor_distance["front"]) * self.get_steps_per_mm()):
                    self._film_sensing["state"]["shot_ready"] = False
                elif self._sensor_distance["rear"] > 0 and not self._film_sensing["state"]["rear"] and self._film_sensing["pos"]["rear"] != None and \
                    (self._motor_position < self._film_sensing["pos"]["rear"] - (self._sensor_distance["rear"]) * self.get_steps_per_mm()):
                    self._film_sensing["state"]["shot_ready"] = False
            if not self._film_sensing["state"]["insert_ready"]:
                self._film_sensing["state"]["insert_ready"] = (not self._film_sensing["state"]["front"] or self._film_sensing["pos"]["front"] == self._frame_counters["front"]["motor_position"]) and not self._film_sensing["state"]["window"]
            else:
                self._film_sensing["state"]["insert_ready"] = (not self._film_sensing["state"]["front"] or self._motor_current_dir <= 0) and not self._film_sensing["state"]["window"]
            # for testing
            # self._film_sensing["state"]["light_ready"] = self._film_sensing["state"]["shot_ready"]
            s2 = "%s" % (self._film_sensing, )
            if s1 != s2:
                logging.getLogger().info("Film sensing: %s -> %s" %(s1, s2))
        except Exception as ex:
            logging.getLogger().info("Film sensing: %s, motor pos: %s, sensor distance: %s, frame_counters: %s" %(self._film_sensing, self._motor_position, self._sensor_distance, self._frame_counters))
            raise ex

    def _check_adapter_ready(self):
        """
            Check if adapter is ready
        """
        return True

    def eject(self, forward):
        """
            Eject film in forward or backward direction. It runs transport till sensors providing perforation output.
        """
        self._check_adapter_ready()
        self.set_motor((int(forward)*2-1) * 999, {"cmd": "EJECT", "phase": 0, })

    def move_by(self, mm, speed):
        """
            Move film by particular number of mm
        """
        self._check_adapter_ready()
        if mm > 0:
            dir = 1
        elif mm < 0:
            dir = -1
        else:
            dir = 0
        # TODO: stepcount is obsolete
        self.set_motor(dir*abs(speed), {"cmd": "MOVE_BY", "mm": abs(mm), "step_count": abs(mm)*self.get_steps_per_mm()})

    def lead_in(self):
        """
            Run transport to get film till front detected by sensors
        """
        self._check_adapter_ready()
        if not self._film_sensing["state"]["insert_ready"]:
            raise DigitizerError("Adapter is not in insert ready state")
        self._film_position = 0
        self.set_motor(999, {"cmd": "LEAD_IN", "phase": 0, })

    def flatten_plane(self, enable):
        """
            Enable/disable mechanized flattening press
        """
        pass