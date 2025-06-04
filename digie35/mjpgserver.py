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

    def write(self, buf):
        if buf.nbytes > 2 and buf[0:2] == b'\xff\xd8':
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
                self.latest_timestamp = datetime.datetime.utcnow()
                # notify all other threads
                self.condition.notify_all()

    def get_latest_frame(self):
        with self.condition:
            return self.latest_frame

    def stop(self):
        self.stop_flag = True
        with self.condition:
            self.condition.notify_all()

"""
StreamingHandler extent http.server.SimpleHTTPRequestHandler class to handle mjpg file for live stream
"""
class StreamingHandler(SimpleHTTPRequestHandler):
    def __init__(self, frames_buffer, *args):
        self.frames_buffer = frames_buffer
        logging.getLogger().debug("new StreamingHandler")
        super().__init__(*args)

    def __del__(self):
        logging.getLogger().debug(f"Remove StreamingHandler")

    def do_GET(self):
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        path = unquote(parsed.path[1:])
        logging.getLogger().log(logging.DEBUG, f"path: %s, query: %s" % (path, query_params))
        if path == 'stream':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, no-store, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
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
        elif path == 'latest.jpg':
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
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode("utf-8"))

        elif path.startswith("preview/") and base_directory != None:
            parts = unquote(path).split("/")
            if len(parts) < 3:
                self.send_error(404, "File not found 1")
            else:
                info = query_params.get("info", 0)
                abs_path = Path(os.path.join(base_directory, parts[1], parts[2], "previews", parts[3] + ".preview." + ("json" if info else "jpg") )).resolve()
                logging.getLogger().log(logging.DEBUG, f"abs_path: %s, parts: %s" % (abs_path, parts))
                if str(abs_path).startswith(str(base_directory)) and os.path.isfile(abs_path):
                    if info:
                        response = None
                        with open(abs_path, "r", encoding="utf-8") as f:
                            try:
                                data = json.load(f)
                                response = json.dumps(data).encode("utf-8")
                            except:
                                self.send_error(500, "Parsing error")
                        if response != None:
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.send_header('Content-Length', str(len(response)))
                            self.end_headers()
                            self.wfile.write(response)
                    else:
                        with open(abs_path, "rb") as f:
                            data = f.read()
                            self.send_response(200)
                            self.send_header('Content-Type', 'image/jpeg')
                            self.send_header('Content-Length', str(len(data)))
                            self.end_headers()
                            self.wfile.write(data)
                else:
                    self.send_error(404, "File not found 2")
        else:
            self.send_error(404, "Not found")
            # fallback to default handler
            # super().do_GET()

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
    address = (addr, port)
    logging.getLogger().debug(f"HTTP server listening on %s:%s" % address)
    httpd = ThreadingHTTPServer(address, lambda *args: StreamingHandler(frame_buffer, *args))
    httpd_thread = Thread(target=run_httpd, kwargs={
        "httpd": httpd,
        })
    httpd_thread.start()
    return (httpd_thread, frame_buffer, httpd)

def stop_http_server():
    global stop_flag
    stop_flag = True

