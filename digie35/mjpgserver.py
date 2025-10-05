#!/usr/bin/env python3

import os
import io
import time
import datetime
import logging
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Condition, Thread
from urllib.parse import unquote, urlparse, parse_qs
from pathlib import Path


"""
FrameBuffer is a synchronized buffer which gets each frame and notifies to all waiting clients.
It implements write() method to be used in preview
"""
class FrameBuffer(object):
    def __init__(self):
        self.frame = None
        self.latest_frame = None
        self.latest_timestamp = None
        self.buffer = io.BytesIO()
        self.condition = Condition()
        self.stop_flag = False

    ## buff is momoryview object
    def write(self, buf):
        # logging.getLogger().debug("FrameBuffer.write(%s, %s ..)" % (buf.nbytes, buf[0:2].hex()))
        if buf.nbytes > 2 and buf[0:2] == b'\xff\xd8':   # JPG header
            # New frame
            with self.condition:
                # write to buffer
                self.buffer.seek(0)
                self.buffer.write(buf)
                # crop buffer to exact size
                self.buffer.truncate()
                # save the frame
                self.frame = self.buffer.getvalue()
                self.latest_frame = self.frame
                self.latest_timestamp = datetime.datetime.now(datetime.timezone.utc)
                # notify all other threads
                self.condition.notify_all()

    def get_latest_frame(self, not_older = None):
        with self.condition:
            if self.latest_timestamp is None or (not not_older is None and self.latest_timestamp < not_older):
                return None
            else:
                return self.latest_frame

    def stop(self):
        self.stop_flag = True
        with self.condition:
            self.condition.notify_all()

class RingBuffer(object):

    def __init__(self, size = 10):
        self._data = [None] * size
        self._full = False
        self._index = 0
        self.condition = Condition()

    def get_count(self):
        with self.condition:
            return len(self._data) if self._full else self._index

    def add(self, id, val):
        # logging.getLogger().debug("RingBuffer.add(%s)" % (id))
        with self.condition:
            self._data[self._index] = (id, val)
            self._index = (self._index + 1) % len(self._data)
            self._full = self._full or self._index == 0

    def get(self, id):
        # logging.getLogger().debug("RingBuffer.get(%s)" % (id))
        with self.condition:
            if isinstance(id, int):
                idx = id
                if idx >= 0 and idx < len(self._data):
                    item = self._data[(self._index - idx - 1) % len(self._data)]
                    if item:
                        return item[1]
            else:
                cnt = len(self._data) if self._full else self._index
                idx = 0
                while idx < cnt:
                    item = self._data[(self._index - idx - 1) % len(self._data)]
                    #logging.getLogger().debug("RingBuffer.get(%s), %s, %s" % (id, idx, item[0]))
                    if item[0] == id:
                        #logging.getLogger().debug("RingBuffer.get(%s) found" % id)
                        return item[1]
                    idx += 1
            return None

    def update(self, id, val):
        # logging.getLogger().debug("RingBuffer.update(%s, %s)" % (id, val))
        with self.condition:
            if isinstance(id, int):
                idx = id
                if idx >= 0 and idx < len(self._data):
                    item = self._data[(self._index - idx - 1) % len(self._data)]
                    if item:
                        self._data[(self._index - idx - 1) % len(self._data)] = (item[0], val)
            else:
                cnt = len(self._data) if self._full else self._index
                idx = 0
                while idx < cnt:
                    item = self._data[(self._index - idx - 1) % len(self._data)]
                    if item[0] == id:
                        self._data[(self._index - idx - 1) % len(self._data)] = (id, val)
                        break
                    idx += 1

    def foreach(self, callback):
        with self.condition:
            cnt = len(self._data) if self._full else self._index
            idx = 0
            result = []
            while idx < cnt:
                item = self._data[(self._index - idx - 1) % len(self._data)]
                result.append(callback(item[0], item[1]))
                idx += 1
            return result

"""
StreamingHandler extent http.server.SimpleHTTPRequestHandler class to handle mjpg file for live stream
"""
class StreamingHandler(SimpleHTTPRequestHandler):
    def __init__(self, frames_buffer, snapshot_list, *args):
        self.frames_buffer = frames_buffer
        self.snapshot_list = snapshot_list
        logging.getLogger().log(logging.DEBUG-1, "new StreamingHandler")
        super().__init__(*args)

    def __del__(self):
        logging.getLogger().log(logging.DEBUG-1, f"Remove StreamingHandler")

    def log_message(self, format, *args):
        if logging.getLogger().getEffectiveLevel() <= logging.DEBUG-1:
            super().log_message(format, *args)

    def do_GET(self):
        # TODO: CORS headers also to send_error()
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        path = unquote(parsed.path[1:])
        logging.getLogger().log(logging.DEBUG-1, f"path: %s, query: %s" % (path, query_params))
        if path == 'stream':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, no-store, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self._send_cors_headers()
            self.end_headers()
            try:
                # tracking serving time
                start_time = time.time()
                frame_count = 0
                # endless stream
                while not self.frames_buffer.stop_flag:
                    with self.frames_buffer.condition:
                        # wait for a new frame
                        self.frames_buffer.condition.wait()
                        if self.frames_buffer.stop_flag:
                            break
                        # it's available, pick it up
                        frame = self.frames_buffer.frame
                        # send it
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', len(frame))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                        # count frames
                        frame_count += 1
                        # calculate FPS every 5s
                        if (time.time() - start_time) > 5:
                            fps = frame_count / (time.time() - start_time)
                            logging.getLogger().log(logging.DEBUG-1, f"FPS: %s" % (fps))
                            frame_count = 0
                            start_time = time.time()
            except Exception as e:
                print(f'Removed streaming client {self.client_address}, {str(e)}')
        elif path == 'snapshot':
            frame = self.frames_buffer.get_latest_frame()
            if frame != None:
                self.send_response(200)
                self.send_header('Age', 0)
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(frame)))
                self.send_header('X-Timestamp', self.frames_buffer.latest_timestamp.isoformat() + "Z")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(frame)

            else:
                self.send_error(404, "No image available")
        elif path == 'stats':
            stats = {
                # TODO: some metrics
            }
            self.send_response(200)
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.send_header('Content-Type', 'application/json')
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode("utf-8"))

        elif path.startswith("preview/"):
            parts = unquote(path).split("/")
            parts.pop(0)
            src = parts.pop(0) if parts else None
            # logging.getLogger().debug("src: %s, parts: %s" % (src, parts))
            info = query_params.get("info", 0)
            if src == "archive" and base_directory != None:
                if len(parts) < 3:
                    self.send_error(404, "File not found 1")
                else:
                    id = os.path.join(parts[0], parts[1], parts[2])
                    abs_path = Path(os.path.join(base_directory, ".previews", id + ".preview." + ("json" if info else "jpg") )).resolve()
                    cached = self.snapshot_list.get(id)
                    # logging.getLogger().debug("id: %s, abs_path: %s, parts: %s, incache: %s" % (id, abs_path, parts, cached != None))
                    payload = None
                    if cached != None:
                        if info:
                            payload = cached["json"]
                        else:
                            payload = cached["frame"]
                    elif str(abs_path).startswith(str(base_directory)) and os.path.isfile(abs_path):
                        if info:
                            with open(abs_path, "r", encoding="utf-8") as f:
                                try:
                                    payload = json.load(f)
                                except:
                                    self.send_error(500, "Parsing error")
                        else:
                            with open(abs_path, "rb") as f:
                                payload = f.read()

                    if payload:
                        if info:
                            payload["from_cache"] = cached != None

                        self._send_response_200(info, payload)
                    else:
                        self.send_error(404, "File not found 2")
            elif src == "latest":
                if not parts or parts[0] == "":
                    def get_json(id, item):
                        return item["json"]

                    self._send_response_200(True, self.snapshot_list.foreach(get_json))
                    return

                elif parts[0].isdigit():
                    item = self.snapshot_list.get(int(parts[0]))
                    if item != None:
                        if info:
                            payload = item["json"] | {"from_cache": True}
                        else:
                            payload = item["frame"] if item["frame"] != None else ""
                        self._send_response_200(info, payload)
                        return
                self.send_error(404, "Preview not found")

        else:
            self.send_error(404, "Not found")
            # fallback to default handler
            # super().do_GET()

    def _send_response_200(self, json_type, payload):
        if json_type:
            payload = json.dumps(payload).encode("utf-8")

        self.send_response(200)
        self.send_header('Content-Type', 'application/json' if json_type else 'image/jpeg')
        self.send_header('Content-Length', str(len(payload)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Method', 'GET, OPTIONS')

def set_base_dir(dir):
    global base_directory
    if dir != None:
        base_directory = Path(dir).resolve()
    else:
        base_directory = None
    logging.getLogger().log(logging.DEBUG, f"set_base_dir(%s): %s" % (dir, base_directory))


global base_directory
base_directory = None

def run_httpd(httpd):
    httpd.serve_forever()

def start_http_server(addr, port):
    frame_buffer = FrameBuffer()
    snapshot_list = RingBuffer()
    address = (addr, port)
    logging.getLogger().debug(f"HTTP server listening on %s:%s" % address)
    httpd = ThreadingHTTPServer(address, lambda *args: StreamingHandler(frame_buffer, snapshot_list, *args))
    httpd_thread = Thread(target=run_httpd, kwargs={
        "httpd": httpd,
        })
    httpd_thread.start()
    return (httpd_thread, frame_buffer, snapshot_list, httpd)

def stop_http_server():
    global stop_flag
    stop_flag = True

