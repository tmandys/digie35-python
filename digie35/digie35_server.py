#!/usr/bin/env python3
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

import argparse
#import yaml
import logging
import asyncio
import websockets
import json
import time
import gphoto2 as gp
import locale
import os
import datetime
import re
import digie35.digie35core as digie35core
import importlib
import subprocess
import stat
import errno
import digie35.mjpgserver as mjpgserver
import netifaces
from threading import Lock, Thread, get_native_id


RPI_FLAG = True
try:
    import digie35.digie35rpi
except ImportError:
    RPI_FLAG = False
    print("RPi stuff not found. RPi support disabled")

ws_lock = Lock()

class CameraControlError(Exception):
    pass

class CameraWrapper:
    _DESCRIPTION_FILENAME = ".description.txt"
    _INTERTHREAD_CAPTURE_TIMEOUT = 0.050  # probably not needed, issou with Sony USB preview does not solve
    _MIN_PICTURE_FILE_SIZE = 100000

    def __init__(self, frame_buffer, **kwargs):
        #logging.getLogger().debug("CameraWrapper(%s)" % (kwargs))
        self._capture_lock = Lock()
        self._capture_lock_release_clock = 0
        self._capture_lock_thread_id = 0
        self._camera_lock = Lock()
        self._camera_counter = 0
        self._camera_preview = False
        self._camera_id = None
        self._capture_in_progress = False
        if kwargs["fifopath"] != None:
            self._fifopath = os.path.abspath(os.path.expandvars(kwargs["fifopath"]))
        else:
            self._fifopath = None
        self._preview_delay = float(kwargs["preview_delay"])/1000
        self._frame_buffer = frame_buffer

        proj_dir = os.path.abspath(os.path.expandvars(kwargs["proj_dir"]))
        l = proj_dir.split("*")
        if len(l) > 2:
            raise CameraControlError("Wrong path, too many asterisks")
        if len(l) == 1:
            self._media_dir = None
            if not os.path.isdir(proj_dir):
                raise CameraControlError(f"Wrong directory path '%s'" % proj_dir)
            self._cur_proj_dir = proj_dir
            logging.getLogger().debug("Projdir: %s" % self._cur_proj_dir)
        else:
            self._media_dir = l[0]
            self._volume_dir = l[1].strip("/")
            self._cur_volume = None
            self._cur_proj_dir = None
            logging.getLogger().debug("Mediadir: %s, volumedir: %s" % (self._media_dir, self._volume_dir))

    def _dump(self, obj, indent = 2, recursion=0):
        logging.getLogger().debug("obj: %s" % (type(obj)))

        if isinstance(obj, object):
            result = {}

            for attr in dir(obj):
                if hasattr(obj, attr):
                    if attr[:2] == "__" or attr == "this":
                        continue
                    val = getattr(obj, attr)
                    if hasattr(val, "__dict__"):
                        if recursion > 3:
                            continue
                        result[attr] = self._dump(val, indent+2, recursion+1)
                    else:
                        result[attr] = getattr(obj, attr)
            return json.dumps(result, indent=4, sort_keys=True, default=str)
        elif isinstance(obj, list):
            result = []
            for i in obj:
                result.append(self.dump, obj, indent, recursion)
            return result
        else:
            return obj

    def _acquire_capture_lock(self, info = ""):
        self._capture_lock.acquire()
        logging.getLogger().debug("capture_lock.acquire(%s) %s" % (info, get_native_id()))
        if self._capture_lock_thread_id != get_native_id():
            while time.perf_counter() - self._capture_lock_release_clock < self._INTERTHREAD_CAPTURE_TIMEOUT:
                #logging.getLogger().debug("interthread delay: %s-%s<%s" % (time.perf_counter(), self._capture_lock_release_clock, self._INTERTHREAD_CAPTURE_TIMEOUT))
                pass
        self._capture_lock_thread_id = get_native_id()

    def _release_capture_lock(self, info = ""):
        self._capture_lock_release_clock = time.perf_counter()
        self._capture_lock.release()
        logging.getLogger().debug("capture_lock.release(%s) %s" % (info, get_native_id()))
        
    def _usb_connect(self):
        # proceed Sony camera connection
        camera = gp.Camera()
        try:
            camera.init()
        except:
            pass
        else:
            camera.exit()

    def _create_camera(self, camera_id):
        logging.getLogger().debug("gp.PortInfoList()")
        port_info_list = gp.PortInfoList()
        port_info_list.load()
        #logging.getLogger().debug("port_info_list: %s" % self._dump(port_info_list))
        for idx in range(port_info_list.count()):
            obj = port_info_list.get_info(idx)
            logging.getLogger().debug("port_info_list[%s]: %s/%s/%s" % (idx, obj.get_name(), obj.get_path(), obj.get_type()))
        logging.getLogger().debug("gp.CameraAbilitiesList()")
        abilities_list = gp.CameraAbilitiesList()
        abilities_list.load()
        #logging.getLogger().debug("abilities_list: %s" % self._dump(abilities_list))
        #for idx in range(abilities_list.count()):
        #    obj = abilities_list.get_abilities(idx)
        #    logging.getLogger().debug("abilities_list[%s]: %s" % (idx, self._dump(obj)))

        camera_list = abilities_list.detect(port_info_list)
        #logging.getLogger().debug("camera_list: %s" % self._dump(camera_list))
        for idx in range(camera_list.count()):
            obj = camera_list[idx]
            #logging.getLogger().debug("camera_list[%s]: %s" % (idx, self._dump(obj)))
            logging.getLogger().debug("camera_list[%s]: %s/%s" % (idx, camera_list.get_name(idx), camera_list.get_value(idx)))
        if len(camera_list) < 1:
            raise CameraControlError('No camera detected')
        camera = gp.Camera()
        logging.getLogger().debug(f"choose camera: %s" % camera_id)        
        idx = port_info_list.lookup_path(camera_id.split("|")[0])
        logging.getLogger().debug("camera.set_port_info([%s])" % idx)
        camera.set_port_info(port_info_list[idx])
        idx = abilities_list.lookup_model(camera_list[0][0])
        logging.getLogger().debug("camera.set_abilities([%s])" % idx)
        logging.getLogger().debug("camera.set_abilities(): %s" % self._dump(abilities_list[idx]))
        camera.set_abilities(abilities_list[idx])
        self._camera = camera
        self._camera_abilities = abilities_list[idx]

    def _reinit_camera(self):
        logging.getLogger().debug("Reinitializing: %s" % (self._camera_id))
        count = 0
        model = self._camera_id.split("|")[1]
        while True:
            logging.getLogger().debug("gp.Camera.autodetect()")
            cameras = gp.Camera.autodetect()
            logging.getLogger().debug("Reinit #%d" % (count))
            for n, (name, value) in enumerate(cameras):
                logging.getLogger().debug("Checking %s:%s" % (name, value))
                if name == model:
                    logging.getLogger().debug("Found current camera %s as %s" % (name, value))
                    self._usb_connect()
                    save_camera = self._camera
                    try:
                        self._camera = None
                        self._create_camera(value)
                        logging.getLogger().debug("camera.init()")
                        self._camera.init()
                        if self._camera_counter > 0:
                            logging.getLogger().debug("camera.exit()")
                            gp.gp_camera_exit(save_camera)
                        del save_camera
                    except:
                        if self._camera != None:
                            del self._camera
                        self._camera = save_camera
                        # it is too early to broken camera appear on USB bus with new name
                        break
                    self._camera_id = "|".join([value, name])
                    return
            count += 1
            if count > 10:
                raise CameraControlError(f"Cannot reinit camera: %s" % model)
            time.sleep(0.2*count)


    def _open_camera(self, camera_id):
        #logging.getLogger().debug("open_camera:camera.acquire")
        self._camera_lock.acquire()
        try:
            if self._camera_counter == 0:
                self._create_camera(camera_id)
                self._camera_id = camera_id
                logging.getLogger().debug("camera.init()")
                try:
                    self._camera.init()
                except Exception as e:
                    # usbid might differ because of reinint (client knows original id)
                    logging.getLogger().error(e, exc_info=True)
                    self._reinit_camera()
                try:
                    self._camera_config_list = {}
                    # get list of supported config items
                    config_list = gp.check_result(gp.gp_camera_list_config(self._camera))
                    for i in range(len(config_list)):
                        self._camera_config_list[config_list.get_name(i)] = config_list.get_value(i)

                    camera_config = self._camera.get_config()
                    # get the camera model (or from abilities.model)
                    logging.getLogger().debug("gp.gp_widget_get_child_by_name(camera_config, 'cameramodel')")
                    OK, camera_model = gp.gp_widget_get_child_by_name(camera_config, 'cameramodel')
                    if OK < gp.GP_OK:
                        logging.getLogger().debug("camera_config.get_child_by_name('model')")
                        OK, camera_model = camera_config.get_child_by_name('model')
                    if OK >= gp.GP_OK:
                        logging.getLogger().debug("camera_model.get_value()")
                        self._camera_model = camera_model.get_value()
                    else:
                        self._camera_model = ""
                    logging.getLogger().debug("Camera: %s" % (self._camera_model))
                    self._get_battery(camera_config)
                except Exception as e:
                    self._camera.exit()
                    del self._camera
                    raise e
            else:
                if camera_id != self._camera_id:
                    CameraControlError("Camera is used. Cannot change camera")
                # camera_config = self._camera.get_config()
            # self._get_battery(camera_config)

            self._camera_counter += 1
        finally:
            #logging.getLogger().debug("open_camera:camera.release")
            self._camera_lock.release()

    def _close_camera(self):
        #logging.getLogger().debug("close_camera:camera.acquire")
        self._camera_lock.acquire()
        try:
            if self._camera_counter == 0:
                return
            self._camera_counter -= 1
            if self._camera_counter == 0:
                logging.getLogger().debug("camera exit")
                gp.check_result(gp.gp_camera_exit(self._camera))
                del self._camera
        finally:
            #logging.getLogger().debug("close_camera:camera.release")
            self._camera_lock.release()

    def list_volumes(self):
        if self._media_dir == None:
            return {
                "volume": self.get_volume_info(),
            }
        else:
            names = os.listdir(self._media_dir)
            names.sort()
            volumes = []
            for name in names:
                dn = os.path.join(self._media_dir, name)
                if os.path.isdir(dn):
                    item = self.get_volume_info(dn)
                    item["name"] = name
                    if name == self._cur_volume:
                        item["active"] = True
                    volumes.append(item)

            return {"volume_list": volumes}

    def set_volume(self, volume):
        if self._media_dir == None:
            raise CameraControlError("Volume set is not enabled")

        if volume != None:
            path = os.path.join(self._media_dir, volume, self._volume_dir)
            if not os.path.isdir(path):
                raise CameraControlError("Directory does not exists '%s'" % path)
            self._cur_volume = volume
            self._cur_proj_dir = path
        else:
            self._cur_volume = None
            self._cur_proj_dir = None
        return self.list_volumes()

    def _get_battery(self, camera_config):
        logging.getLogger().debug("camera_config.get_child_by_name('batterylevel')")
        OK, batterylevel_cfg = gp.gp_widget_get_child_by_name(camera_config, 'batterylevel')
        #OK, batterylevel_cfg = camera_config.get_child_by_name("batterylevel")
        if OK >= gp.GP_OK:
            self._camera_battery = batterylevel_cfg.get_value()
        else:
            self._camera_battery = None

    def list_cameras(self):
        logging.getLogger().debug("gp.Camera.autodetect()")
        #callback_obj = gp.check_result(gp.use_python_logging())
        cameras = gp.Camera.autodetect()
        result = []
        for n, (name, value) in enumerate(cameras):
            item = {"name": name, "id": "|".join([value, name])}
            if value == self._camera_id:
                item["current"] = True
                item["battery"]= self._camera_battery
            result.append(item)

        # proceed Sony camera connection
        if self._camera_counter == 0:
            self._camera_lock.acquire()
            try:
                if self._camera_counter == 0:
                    self._usb_connect()
            finally:
                self._camera_lock.release()

        return {"camera_list": result}

    def set_camera(self, camera_id):
        # TODO: unselect/stop preview, ...
        if camera_id == "":
            return
        self._open_camera(camera_id)
        try:
            result = {"model": self._camera_model, "id": self._camera_id, "battery": self._camera_battery}
            result["device_type"] = self._camera_abilities.device_type
            result["device_status"] = self._camera_abilities.status
            result["library"] = self._camera_abilities.library

            result["capture_preview"] = (self._camera_abilities.operations & gp.GP_OPERATION_CAPTURE_PREVIEW) != 0
            result["capture_image"] = (self._camera_abilities.operations & gp.GP_OPERATION_CAPTURE_IMAGE) != 0
            result["capture_video"] = (self._camera_abilities.operations & gp.GP_OPERATION_CAPTURE_VIDEO) != 0
            result["capture_audio"] = (self._camera_abilities.operations & gp.GP_OPERATION_CAPTURE_AUDIO) != 0
            result["config_support"] = (self._camera_abilities.operations & gp.GP_OPERATION_CONFIG) != 0
            result["trigger_capture"] = (self._camera_abilities.operations & gp.GP_OPERATION_TRIGGER_CAPTURE) != 0

            result["file_delete"] = (self._camera_abilities.file_operations & gp.GP_FILE_OPERATION_DELETE) != 0
            result["file_preview"] = (self._camera_abilities.file_operations & gp.GP_FILE_OPERATION_PREVIEW) != 0
            result["file_raw"] = (self._camera_abilities.file_operations & gp.GP_FILE_OPERATION_RAW) != 0
            result["file_audio"] = (self._camera_abilities.file_operations & gp.GP_FILE_OPERATION_AUDIO) != 0
            result["file_exif"] = (self._camera_abilities.file_operations & gp.GP_FILE_OPERATION_EXIF) != 0

            result["folder_delete_all"] = (self._camera_abilities.folder_operations & gp.GP_FOLDER_OPERATION_DELETE_ALL) != 0
            result["folder_put_file"] = (self._camera_abilities.folder_operations & gp.GP_FOLDER_OPERATION_PUT_FILE) != 0
            result["folder_make_dir"] = (self._camera_abilities.folder_operations & gp.GP_FOLDER_OPERATION_MAKE_DIR) != 0
            result["folder_remove_dir"] = (self._camera_abilities.folder_operations & gp.GP_FOLDER_OPERATION_REMOVE_DIR) != 0
        finally:
            self._close_camera()
        return result

    def _do_download(self, project_id, film_id, file_path, websocket, client_data):
        try:
            error = None
            try:
                try:
                    logging.getLogger().debug(f"Download thread started: %s" % (file_path))
                    fname, fext = os.path.splitext(file_path.name)
                    now = datetime.datetime.now()
                    fname += now.strftime("_%Y%m%d%H%M%S") + fext
                    target = os.path.join(self._get_path(project_id, film_id), fname)
                    logging.getLogger().info(f"Copying image to '%s'", target)
                    logging.getLogger().debug("gp_camera_file_get(%s, %s, %s)" % (file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL))
                    camera_file = gp.check_result(gp.gp_camera_file_get(self._camera, file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL))
                    gp.check_result(gp.gp_file_save(camera_file, target))
                    logging.getLogger().debug(f"Delete image '%s'", file_path.name)
                    gp.check_result(gp.gp_camera_file_delete(self._camera, file_path.folder, file_path.name))
                        
                finally:
                    self._close_camera()
            except Exception as e:
                logging.getLogger().error(e, exc_info=True)
                error = repr(e)

            msg = {
                "cmd": "DOWNLOAD",
                "payload": {
                    "name": file_path.name,
                    "file_path": target,
                    "volume": self.get_volume_info(),
                }}
            if client_data != None:
                msg["payload"]["client_data"] = client_data
            if error != None:
                msg["payload"]["error"] = error
            send_thread = Thread(target=run_send, kwargs={
                "websocket": websocket,
                "message": msg
                })   # to avoid running event loop error, async/await pain
            send_thread.name = "download_notify"
            send_thread.start()
            send_thread.join()
        finally:
            self._capture_in_progress = False
            self._broadcast_capture_status_from_event()
            self._release_capture_lock()

    def capture(self, websocket, camera_id, project_id, film_id, client_data = None):
        if self._capture_in_progress:  # but not preview capture
            raise CameraControlError("Capture in progress")
        color = digitizer.get_current_backlight_color()
        if color == None or color == "external":
            raise CameraControlError("Backlight is switched off")
        self._acquire_capture_lock()
        self._capture_in_progress = True
        self._broadcast_capture_status_from_event()
        try:
            logging.getLogger().debug("CameraId: %s" % camera_id)
            self._open_camera(camera_id)
            try:
                if self._camera_preview:
                    # self._switch_to_capture_mode()  # XXX
                    # time.sleep(3.0)
                    pass
                try:
                    count = 0
                    while True:
                        if False:  # XXX
                            camera_config = self._camera.get_config()
                            if 'capturetarget' in self._camera_config_list:
                                logging.getLogger().debug("gp_widget_get_child_by_name('capturetarget')")
                                capturetarget_cfg = gp.check_result(gp.gp_widget_get_child_by_name(camera_config, 'capturetarget'))
                                #OK, capturetarget_cfg = camera_config.get_child_by_name("capturetarget")
                                #logging.getLogger().debug("target: %s/%s" % (OK, self._dump(capturetarget_cfg)))
                                capturetarget = gp.check_result(gp.gp_widget_get_value(capturetarget_cfg))
                                #capturetarget = capturetarget_cfg.get_value()
                                logging.getLogger().debug("savetarget: %s" % capturetarget)
                                logging.getLogger().debug("setvalue: %s" % "Internal RAM")
                                capturetarget_cfg.set_value("Internal RAM")
                                self._camera.set_config(camera_config)
                        else:
                            capturetarget = None
                        # self._get_battery(camera_config)

                        logging.getLogger().debug("camera.capture()")
                        try:
                            file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE)
                            break
                        except Exception as e:
                            count += 1
                            if count > 1:
                                raise e
                            logging.getLogger().error(e, exc_info=True)
                            # self._reinit_camera()

                    logging.getLogger().debug('Camera file path: {0}/{1}'.format(file_path.folder, file_path.name))

                    if capturetarget != None:
                        logging.getLogger().debug("setvalue: %s" % capturetarget)
                        capturetarget_cfg.set_value(capturetarget)
                        self._camera.set_config(camera_config)
                finally:
                    if self._camera_preview and False: # XXX
                        self._switch_to_preview_mode()
                # leave asap to allow move commands
                download_thread = Thread(target=self._do_download, kwargs={"project_id": project_id, "film_id": film_id, "file_path": file_path, "websocket": websocket, "client_data": client_data})
                download_thread.name = "download"
                download_thread.start()
            except Exception as e:
                logging.getLogger().error(e, exc_info=True)
                self._close_camera()
                raise e
        except Exception as e:
            self._capture_in_progress = False
            self._broadcast_capture_status_from_event()
            self._release_capture_lock("error")
            raise e
        return {
            "camera": self._camera_model,
            "name": file_path.name,
            "folder": file_path.folder,
            "battery": self._camera_battery,
        }

    def _broadcast_capture_status_from_event(self):
        send_thread = Thread(target=self._broadcast_camera_status, kwargs={
            })   # to avoid running event loop error, async/await pain
        send_thread.name = "capture_notify"
        send_thread.start()
        send_thread.join()

    def _broadcast_camera_status(self):
        global ws_clients
        message = {"cmd": "CAMERA", "payload": {"usbpreview": self._camera_preview, "capturing": self._capture_in_progress, }}
        logging.getLogger().debug("broadcast: %s", message)
        for websocket in ws_clients.copy():
            asyncio.run(send(websocket, message))

    def _switch_to_preview_mode(self):
        if self._camera_model == 'unknown':
            # find the capture size class config item
            # need to set this on my Canon 350d to get preview to work at all
            camera_config = self._camera.get_config()
            OK, capture_size_class = gp.gp_widget_get_child_by_name(camera_config, 'capturesizeclass')
            if OK >= gp.GP_OK:
                # set value
                value = capture_size_class.get_choice(2)
                capture_size_class.set_value(value)
                # set config
                self._camera.set_config(camera_config)
        else:
            # put camera into preview mode to raise mirror
            gp.gp_camera_capture_preview(self._camera) # OK, camera_file

        logging.getLogger().debug(f"Started capture view (extended lens/raised mirror) on camera '%s'" % (self._camera_model))

    def _switch_to_capture_mode(self):
        camera_config = self._camera.get_config()
        # https://github.com/gphoto/gphoto2/issues/195
        logging.getLogger().debug("gp.gp_widget_get_child_by_name(camera_config, 'capture')")
        OK, capture = gp.gp_widget_get_child_by_name(camera_config, 'capture')
        if OK >= gp.GP_OK:
            capture.set_value(0)
            self._camera.set_config(camera_config)
        logging.getLogger().debug(f"Stopped capture view (retracted lens/released mirror) on camera (%s)" % (OK))

    def _do_preview(self, fifo):
        self._camera_preview = True
        try:
            self._broadcast_camera_status()
            try:
                while not self._stop_preview_flag:
                    # capture preview image
                    self._acquire_capture_lock()
                    try:
                        logging.getLogger().debug("gp.gp_camera_capture_preview()")
                        OK, camera_file = gp.gp_camera_capture_preview(self._camera)  # in JPG
                        if OK < gp.GP_OK:
                            logging.getLogger().error(f"Failed to capture preview: %s: %s" % (OK, gp.gp_result_as_string(OK)))
                            # Sony fails to preview without a obvious reason and USB reinit is required
                            self._reinit_camera()
                            continue;
                        logging.getLogger().debug("camera_file.get_data_and_size()")
                        file_data = camera_file.get_data_and_size()
                        #logging.getLogger().debug(f"%s" % file_data)
                    finally:
                        self._release_capture_lock()


                    data = memoryview(file_data)
                    #logging.getLogger().debug(f"write fifo: %d" % data.nbytes)
                    if fifo != None:
                        try:
                            os.write(fifo, data)
                        except OSError as e:
                            if e.errno == errno.EPIPE:
                                break
                            elif e.errno == errno.EWOULDBLOCK:
                                pass
                            else:
                                logging.getLogger().debug(f"Errno: %d" % e.errno)
                                raise
                    if self._frame_buffer != None:
                        # logging.getLogger().debug(f"Write frame buffer: %s" % len(data))
                        self._frame_buffer.write(data)

                    time.sleep(self._preview_delay)

            finally:
                if fifo != None:
                    logging.getLogger().debug(f"close FIFO")
                    os.close(fifo)

            self._acquire_capture_lock("2")
            try:
                self._switch_to_capture_mode()
            finally:
                self._release_capture_lock("2")

        finally:
            self._close_camera()
            self._camera_preview = False
            self._broadcast_camera_status()
            logging.getLogger().debug(f"Preview thread terminated")

    def start_preview(self, camera_id):
        if not self._camera_preview:
            if self._frame_buffer == None and self._fifopath == None:
                raise CameraControlError(f"Neither FIFO not HTTP server are activated")

            if self._fifopath != None:
                logging.getLogger().debug(f"Check FIFO: %s" % self._fifopath)
                if not os.path.exists(self._fifopath) or not stat.S_ISFIFO(os.stat(self._fifopath).st_mode):
                    raise CameraControlError(f"FIFO '%s' does not exists" % self._fifopath)
                try:
                    logging.getLogger().debug(f"open FIFO: %s" % self._fifopath)
                    fifo = os.open(self._fifopath, os.O_NONBLOCK | os.O_WRONLY)  # os.O_BINARY
                except OSError as e:
                    if e.errno == errno.ENXIO:
                        raise CameraControlError("FIFO server is not running")
                    else:
                        raise
            else:
                fifo = None
            try:
                self._acquire_capture_lock()
                try:
                    self._open_camera(camera_id)
                    try:
                        self._switch_to_preview_mode()
                        self._stop_preview_flag = False
                        self._preview_thread = Thread(target=self._do_preview, kwargs={"fifo": fifo})
                        self._preview_thread.name = "preview"
                        self._preview_thread.start()

                    except Exception as e:
                        self._close_camera()
                        raise e
                finally:
                   self._release_capture_lock()
            except:
                if fifo != None:
                    os.close(fifo)
                raise
        return {
            "camera_id": camera_id,
            "usbpreview": True,
        }

    def stop_preview(self, camera_id):
        if self._camera_preview:
            self._stop_preview_flag = True
            self._preview_thread.join()
        return {
            "camera_id": camera_id,
            "usbpreview": False,
        }

    def _check_id(self, id, fld):
        if (id == ""):
            raise CameraControlError(f"Empty %s value" % fld)
        reg = re.compile("^[a-zA-Z0-9_\-]+$")
        if not reg.match(id):
            raise CameraControlError(f"Wrong %s value" % fld)

    def create_project(self, project_id, project_descr):
        self._check_project_exists(project_id, True)
        path = self._get_path(project_id)
        os.mkdir(path)
        return self.update_project(project_id, project_descr)

    def get_project(self, project_id):
        self._check_project_exists(project_id)
        with open(self._get_descr(project_id), "r") as f:
            result = {
                "id": project_id,
                "descr": f.read()
            }
        filenames = os.listdir(self._get_path(project_id))
        filenames.sort()
        films = []
        for filename in filenames:
            if filename[0] == ".":
                continue
            path = self._get_path(project_id, filename)
            if os.path.isdir(path):
                if os.path.isfile(os.path.join(path, self._DESCRIPTION_FILENAME)):
                    films.append(self.get_film(project_id, filename))
        result["film_list"] = films
        return result

    def update_project(self, project_id, project_descr):
        self._check_project_exists(project_id)
        with open(self._get_descr(project_id), "w") as f:
            f.write(project_descr)
        return self.get_project(project_id)

    def delete_project(self, project_id):
        project = self.get_project(project_id)
        if not hasattr(project, "film_list"):
            path = self._get_path(project_id)
            os.remove(self._get_descr(project_id))
            os.rmdir(path)
            return "OK"
        else:
            raise CameraControlError(f"Project '%s' is not empty" % project_id)

    def list_projects(self):
        filenames = os.listdir(self._get_path(""))
        logging.getLogger().debug(f"LIST PROJ: %s", filenames)
        filenames.sort()
        projects = []
        for filename in filenames:
            if filename[0] == ".":
                continue
            path = self._get_path(filename)
            if os.path.isdir(path):
                if os.path.isfile(os.path.join(path, self._DESCRIPTION_FILENAME)):
                    projects.append(self.get_project(filename))
        return {"project_list": projects}

    def create_film(self, project_id, film_id, film_descr):
        self._check_film_exists(project_id, film_id, True)
        path = self._get_path(project_id, film_id)
        os.mkdir(path)
        return self.update_film(project_id, film_id, film_descr)

    def update_film(self, project_id, film_id, film_descr):
        self._check_film_exists(project_id, film_id)
        with open(self._get_descr(project_id, film_id), "w") as f:
            f.write(film_descr)
        return self.get_film(project_id, film_id)

    def delete_film(self, project_id, film_id):
        self._check_film_exists(project_id, film_id)
        path = self._get_path(project_id, film_id)
        os.remove(self._get_descr(project_id, film_id))
        os.rmdir(path)
        return "OK"

    def get_film(self, project_id, film_id):
        self._check_film_exists(project_id, film_id)
        with open(self._get_descr(project_id, film_id), "r") as f:
            result = {
                "id": film_id,
                "descr": f.read()
            }
        path = self._get_path(project_id, film_id)
        filenames = os.listdir(path)
        pictures = []
        for filename in filenames:
            if filename[0] == ".":
                continue
            filepath = os.path.join(path, filename);
            if os.path.isfile(filepath):
                if len(filename) > 4 and filename[len(filename)-4] == "." and os.path.getsize(filepath) > self._MIN_PICTURE_FILE_SIZE:   # expected 3 char extension and minimal size to filter out potential metadata or so
                    pictures.append({"name": filename, "size": os.path.getsize(filepath)})
        pictures.sort(key=lambda x: x.get("name"))
        result["captured"] = pictures
        return result

    def _get_path(self, project_id, film_id = ""):
        if self._cur_proj_dir == None:
            raise CameraControlError("Target directory is not specified")
        path = self._cur_proj_dir
        if project_id != "":
            path = os.path.join(path, project_id)
            if film_id:
                path = os.path.join(path, film_id)
        return path

    def _get_descr(self, project_id, film_id = ""):
        path = self._get_path(project_id, film_id)
        return os.path.join(path, self._DESCRIPTION_FILENAME)

    def _check_project_exists(self, project_id, neg = False):
        self._check_id(project_id, "project_id")
        if os.path.isdir(self._get_path(project_id)):
            if neg:
                raise CameraControlError(f"Project '%s' already exists" % project_id)
        else:
            if not neg:
                raise CameraControlError(f"Project '%s' does not exists" % project_id)

    def _check_film_exists(self, project_id, film_id, neg = False):
        self._check_project_exists(project_id)
        self._check_id(film_id, "film_id")
        if os.path.isdir(self._get_path(project_id, film_id)):
            if neg:
                raise CameraControlError(f"Film '%s/%s' already exists" % (project_id, film_id))
        else:
            if not neg:
                raise CameraControlError(f"Film '%s/%s' does not exists" % (project_id, film_id))

    def get_volume_info(self, dir=None):
        if dir == None:
            dir = self._cur_proj_dir
        process = subprocess.Popen(["findmnt", "-J", "-o", "TARGET,SOURCE,PARTLABEL,SIZE,AVAIL,USE%", "--target", dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True)
        stdout, stderr = process.communicate()

        logging.getLogger().debug(f"targetinfo: %s" % stdout)
        if stderr != "":
            raise CameraControlError(f"findmnt error: %s" % stderr)
        if stdout == "":
            raise CameraControlError(f"Cannot get info about: %s" % dir)
        info = json.loads(stdout)
        logging.getLogger().debug(f"targetinfo: %s" % info)
        return info["filesystems"][0]


WS_PROTOCOL_VERSION = "0.2"

VERSION_INFO = {
    "program": "camera_control",
    "version": __version__,
    "ws_protocol": WS_PROTOCOL_VERSION,
    "libphoto2": gp.gp_library_version(gp.GP_VERSION_SHORT),
    "libphoto2_port": gp.gp_port_library_version(gp.GP_VERSION_SHORT),
    "python-libphoto2": gp.__version__,
}

ws_clients = set()

async def ws_handler(websocket, path):
    global ws_clients
    global VERSION_INFO
    global camera
    ws_clients.add(websocket)
    try:
        PARAM_DELIMITER = ":"
        log = logging.getLogger()
        log.debug("path: %s", path)
        while True:
            try:
                data = await websocket.recv()
                log.debug("ws: %s", data)

                l = data.split(PARAM_DELIMITER, 1)
                cmd = l[0]
                if (len(l) > 1):
                    params = json.loads(l[1])
                else:
                    params = {}
                cmd = cmd.upper()
                if "client_data" in params:
                    client_data = params["client_data"]
                    if cmd != "CAPTURE":
                        del params["client_data"]
                else:
                    client_data = None
                reply = ""
                reply_status = False
                try:
                    if "":
                        pass
                    elif cmd == "LIST_VOLUMES":
                        reply = camera.list_volumes()
                    elif cmd == "SET_VOLUME":
                        reply = camera.set_volume(**params)
                    elif cmd == "LIST_PROJECTS":
                        reply = camera.list_projects()
                    elif cmd == "CREATE_PROJECT":
                        reply = camera.create_project(**params)
                    elif cmd == "UPDATE_PROJECT":
                        reply = camera.update_project(**params)
                    elif cmd == "DELETE_PROJECT":
                        reply = camera.delete_project(**params)
                    elif cmd == "GET_PROJECT":
                        reply = camera.get_project(**params)

                    elif cmd == "CREATE_FILM":
                        reply = camera.create_film(**params)
                    elif cmd == "UPDATE_FILM":
                        reply = camera.update_film(**params)
                    elif cmd == "DELETE_FILM":
                        reply = camera.delete_film(**params)
                    elif cmd == "GET_FILM":
                        reply = camera.get_film(**params)

                    elif cmd == "CAPTURE":
                        reply = camera.capture(websocket, **params)
                        status = digitizer.get_state()
                        if "film_position" in list(status):
                            reply["film_position"] = round(status["film_position"], 3)
                    elif cmd == "LIST_CAMERAS":
                        reply = camera.list_cameras()
                    elif cmd == "SET_CAMERA":
                        reply = camera.set_camera(**params)

                    elif cmd == "START_PREVIEW":
                        reply = camera.start_preview(**params)
                    elif cmd == "STOP_PREVIEW":
                        reply = camera.stop_preview(**params)

                    elif cmd == "SET_BACKLIGHT":
                        digitizer.set_backlight(**params)
                        status = digitizer.get_state();
                    elif cmd == "LEVEL":
                        digitizer.set_io_state(**params)
                        reply_status = True
                    elif cmd == "WAIT":
                        time.sleep(float(params.sed))
                        reply_status = True
                    elif cmd == "PULSE":
                        digitizer.pulse_output(**params)
                        reply_status = True
                    elif cmd == "SENSOR":
                        digitizer.set_io_state(**params)
                        reply_status = True
                    elif cmd == "MOVE":
                        digitizer.check_capability("motorized")
                        digitizer.get_adapter().set_motor(**params)
                        reply_status = True
                    elif cmd == "STOP":
                        digitizer.check_capability("motorized")
                        digitizer.get_adapter().set_motor(0)
                        reply_status = True
                    elif cmd == "EJECT":
                        digitizer.check_capability("motorized")
                        digitizer.get_adapter().eject(**params)
                        reply_status = True
                    elif cmd == "INSERT":
                        digitizer.check_capability("motorized")
                        digitizer.get_adapter().lead_in()
                        reply_status = True
                    elif cmd == "MOVE_BY":
                        digitizer.check_capability("motorized")
                        digitizer.get_adapter().move_by(**params)
                        reply_status = True
                    elif cmd == "GET":
                        reply_status = True

                    elif cmd in ["HELLO", "HOTPLUG"]:
                        digitizer.check_connected_adapter()
                        reply = VERSION_INFO.copy()
                        reply["mainboard_class"] = digitizer._mainboard.__class__.__name__
                        reply["xboard_class"] = digitizer.__class__.__name__
                        reply["adapter_class"] = {}
                        for name in list(digitizer._adapters):
                            reply["adapter_class"][name] = digitizer.get_adapter(name).__class__.__name__
                        reply["capabilities"] = digitizer.get_capabilities()
                        if reply["capabilities"]["motorized"]:
                            reply["steps_per_mm"] = digitizer.get_adapter().get_steps_per_mm()
                        reply |= camera.list_volumes()
                        ifaces = netifaces.interfaces()

                        for iface in ["eth0", "wlan0", ]:
                            if iface in ifaces:
                                ifc = netifaces.ifaddresses(iface)
                                if netifaces.AF_INET in ifc:
                                    reply["lan_ip"] = ifc[netifaces.AF_INET][0]["addr"]
                                    break
                    elif cmd == "BYE":
                        reply = ""
                        break
                    else:
                        reply = f"Unknown command: {cmd}"

                except Exception as e:
                    logging.getLogger().error(e, exc_info=True)
                    reply = repr(e)

                if reply_status and reply == "":
                    reply = digitizer.get_state(True)

                if isinstance(reply, (dict, list, set)):
                    if client_data != None:
                        # pass back a "cookie"
                        reply["client_data"] = client_data
                    reply = json.dumps({"cmd": cmd, "payload": reply})

                log.debug("ws.send: %s" % reply)
                global ws_lock
                ws_lock.acquire()
                try:
                    await websocket.send(reply)
                finally:
                    ws_lock.release()

            except websockets.exceptions.ConnectionClosedError:
                log.error("Connection closed");
                break;
            except websockets.exceptions.ConnectionClosedOK:
                break;
    finally:
        ws_clients.remove(websocket)
        if len(ws_clients) == 0:
            digitizer.set_backlight()  # switch off backlight


def run_send(websocket, message):
    asyncio.run(send(websocket, message))

async def send(websocket, message):
    try:
        global ws_lock;
        ws_lock.acquire()
        try:
            await websocket.send(json.dumps(message))
        finally:
            ws_lock.release()
    except websockets.ConnectionClosed:
        pass


def broadcast(message):
    global last_adapter   # should be per ws_client but it is corner case
    global ws_clients
    logging.getLogger().debug("broadcast: %s", message)
    try:
        last_adapter   # initialization pain
        last_adapter = message | last_adapter  # add missing fields
    except NameError:
        last_adapter = message
    send_flag = not ("last_adapter" in globals())
    if message["source"] == "sleep_button":
        if (on_sleep_button()):
            send_flag = True
            message["backlight"]["color"] = digitizer.get_current_backlight_color() if digitizer.get_current_backlight_color() != None else ""  # on_sleep switched off backlight
            if (message["backlight"]["color"] == "" and "intensity" in message["backlight"]):
                del message["backlight"]["intensity"]
    if message["source"] == "backlight":
        send_flag |= True
    if not "action" in message:
        message["action"] = ""
    if not "movement" in message:
        message["movement"] = 0

    message2 = {
        "movement": message["movement"],
        "action": message["action"],
        "backlight": message["backlight"],
    }
    if "frame_ready" in message:
        send_flag |= last_adapter["frame_ready"] != message["frame_ready"]
        message2["frame_ready"] = message["frame_ready"]

    caps = digitizer.get_capabilities()
    if message["source"] == "hotplug":
        send_flag |= True
        message2["adapter_class"] = digitizer.get_adapter().__class__.__name__
        message2["capabilities"] = caps
        if caps["motorized"]:
            message2["steps_per_mm"] = digitizer.get_adapter().get_steps_per_mm()

    elif caps["motorized"]:

        insert_detected = False
        if not send_flag:
            send_flag = last_adapter["movement"] != message["movement"] or \
                last_adapter["action"] != message["action"]
        if not send_flag and "frame_ready" in last_adapter:  # when changing adapters
            send_flag = last_adapter["frame_ready"] != message["frame_ready"] or \
                last_adapter["film_detected"] != message["film_detected"]
        if "last_adapter" in globals():
            # TODO: it may generate oscillating level, the signal should be stable for some time
            insert_detected = (message["movement"] == 0 and \
                # not message["film_detected"] and \
                not last_adapter["io"]["sensor_f"] and message["io"]["sensor_f"] and \
                not last_adapter["io"]["sensor_r"] and not message["io"]["sensor_r"] and \
                not last_adapter["io"]["sensor_m"] and not message["io"]["sensor_m"])
            send_flag |= insert_detected

        message2 |= {
            "film_position": message["film_position"],
            "film_inserted": insert_detected,
            #"motor_position": message["counters"]["motor"],  # for debugging
        }
    last_adapter = message
    if not send_flag:
        return
    logging.getLogger().debug("broadcast: %s", message2)

    # eg. set_backlight triggers broadcast when is in running loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 'RuntimeError: There is no current event loop...'
        loop = None
    for websocket in ws_clients.copy():
        if loop and loop.is_running():
                logging.getLogger().debug("starting broadcast thread for: %s", message2)
                send_thread = Thread(target=run_send, kwargs={
                    "websocket": websocket,
                    "message": message2,
                    })   # to avoid running event loop error, async/await pain
                send_thread.name = "broadcast_notify"
                send_thread.start()
                send_thread.join()
        else:
            # asyncio.run(send(websocket, {"cmd": "ADAPTER", "payload": message2}))
            run_send(websocket, {"cmd": "ADAPTER", "payload": message2})

SLEEP_INTERVAL = [0.2, 1.0, 3.0]
last_button_state = None

def on_sleep_button():
    global digitizer
    global camera
    global last_button_state
    result = False
    state = digitizer.get_io_state("sleep_button")
    logging.getLogger().debug("Sleep button: %d", state)
    ts = time.monotonic()
    if state:
        # button is pressed, wait to release
        pass
    else:
        if last_button_state != None:
            if last_button_state["state"]:
                interval = ts - last_button_state["time"]
                if not camera._capture_in_progress and interval >= SLEEP_INTERVAL[0] and interval < SLEEP_INTERVAL[2]:   # button pressed 1-3secs
                    logging.getLogger().debug("Switch off adapter")
                    if issubclass(type(digitizer.get_adapter()), digie35core.StepperMotorAdapter):
                        digitizer.get_adapter().set_motor(0)
                    digitizer.set_backlight()
                    if interval >= SLEEP_INTERVAL[1]:
                        logging.getLogger().debug("Going to shutdown")
                        subprocess.call(['shutdown', '-h', 'now'], shell=False)
                    result = True
    last_button_state = {
        "time": ts,
        "state": state,
    }
    return result

def main():
    locale.setlocale(locale.LC_ALL, 'C')
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Camera Control via gphoto2, v%s" % __version__,
        epilog="",
    )
    #argParser.add_argument("-c", "--config", dest="configFile", metavar="FILEPATH", type=argparse.FileType('r'), help="RPi+HAT configuration file in YAML")
    argParser.add_argument("-d", "--directory", dest="proj_dir", metavar="PATH", default="/media/pi/*", help=f"Project directory, via asterisk are supported dynamically mounted disks, env variables are supported, e.g.$HOME/.digie35/projects , default: %(default)s")
    argParser.add_argument("-w", "--addr", dest="wsAddr", metavar="ADDR", default="0.0.0.0", help=f"Websocket listener bind address ('0.0.0.0' = all addresses), default: %(default)s")
    argParser.add_argument("-p", "--port", dest="wsPort", metavar="PORT", type=int, default=8400, help=f"Websocket listener port, default: %(default)s")
    argParser.add_argument("-u", "--preview-port", dest="previewPort", metavar="PORT", type=int, default=8408, help=f"HTTP server port for preview stream, default: %(default)s")
    argParser.add_argument("-f", "--pipe", dest="fifopath", metavar="FIFOPATH", default=None, help="FIFO where preview pictures are written, FIFO must exist (mkfifo FIFOPATH) and reader must be running")
    argParser.add_argument("-e", "--preview-delay", dest="preview_delay", metavar="msec", type=int, default=100, help=f"Delay in ms when capturing preview from camera, default: %(default)s")
    argParser.add_argument("-l", "--logfile", dest="logFile", metavar="FILEPATH", help="Logging file, default: stderr")
    argParser.add_argument("-b", "--board", choices=["HEAD", "GULP", "NIKI", "ALPHA"], type=str.upper, default="HEAD", help=f"Board name, default: %(default)s")
    argParser.add_argument("-s", "--shutdown", action="store_true", help="Shutdown when side button is pressed between %s-%s secs" % (SLEEP_INTERVAL[1], SLEEP_INTERVAL[2]))
    argParser.add_argument("-m", "--mainboard", choices=["GPIOZERO", "RPIGPIO", "SIMULATOR",], type=str.upper, default="GPIOZERO", help=f"Mainboard library name, default: %(default)s")
    argParser.add_argument("-v", "--verbose", action="count", default=0, help="verbose output")
    argParser.add_argument("-g", "--gphoto2-logging", dest="gp_log", action="store_true", help="gphoto2 library logging")
    argParser.add_argument("--version", action="version", version=f"%s" % VERSION_INFO)

    args = argParser.parse_args()
    LOGGING_FORMAT = "%(asctime)s: %(name)s: %(threadName)s: %(levelname)s: %(message)s"
    if args.logFile:
        logging.basicConfig(filename=args.logFile, format=LOGGING_FORMAT)
    else:
        logging.basicConfig(format=LOGGING_FORMAT)
    log = logging.getLogger()

    # logging.NOTSET logs everything
    verbose2level = (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)
    args.verbose = min(max(args.verbose, 0), len(verbose2level) - 1)
    log.setLevel(verbose2level[args.verbose])

    if args.gp_log:
        log_callback_obj = gp.check_result(gp.use_python_logging())

    log.debug("Parsed args: %s", args)

    if args.previewPort != 0:
        http_thread, frame_buffer, httpd = mjpgserver.start_http_server(args.wsAddr, args.previewPort)
    else:
        frame_buffer = None

    global camera
    camera = CameraWrapper(frame_buffer, **args.__dict__)

    board = args.board.upper()
    extra_io_map = {}

    if args.mainboard == "SIMULATOR":
        module2 = importlib.import_module("digie35.digie35simulator")
        mainboard = module2.SimulatorMainboard()
    elif args.mainboard == "GPIOZERO":
        module2 = importlib.import_module("digie35.digie35gpiozero")
        mainboard = module2.GpioZeroMainboard(board != "NIKI")
    else:
        module2 = importlib.import_module("digie35.digie35rpigpio")
        mainboard = module2.RpiGpioMainboard(board != "NIKI")

    module = importlib.import_module("digie35.digie35board")
    if board == "ALPHA":
        film_xboard_class = module.AlphalExtensionBoard
    elif board == "NIKI":
        film_xboard_class = module.NikiExtensionBoard
    else:   # GULP
        film_xboard_class = module.GulpExtensionBoard.get_xboard_class(mainboard)

    if not args.shutdown:
        SLEEP_INTERVAL[1] = SLEEP_INTERVAL[2] + 1  # condition which will never meet to shutdown

    #if args.configFile:
    #    log.debug("Loading config file: %s", args.configFile)
    #    cfg = yaml.load(args.configFile, Loader=yaml.CLoader)
    #log.debug("Configuration: %s", cfg)

    global digitizer
    log.debug("film_xboard_class: %s", film_xboard_class.__name__)
    digitizer = film_xboard_class(mainboard, broadcast)

    async def ws_run():
        async with websockets.serve(ws_handler, args.wsAddr, args.wsPort):
            await asyncio.Future()  # run forever

    try:
        asyncio.run(ws_run())
    except KeyboardInterrupt:
        log.debug("Keyboard interrupt, shutdown")
        digitizer.reset()
        camera.stop_preview("dummy")
        if frame_buffer != None:
            frame_buffer.stop()
            httpd.shutdown()


if __name__ == "__main__":
   main()
