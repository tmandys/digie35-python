#!/usr/bin/env python3

import io
import time
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Condition, Thread


"""
FrameBuffer is a synchronized buffer which gets each frame and notifies to all waiting clients.
It implements write() method to be used in image providerpicamera.start_recording()
"""
class FrameBuffer(object):
    def __init__(self):
        self.frame = None
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
                # notify all other threads
                self.condition.notify_all()

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
        if self.path == '/stream':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
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
                            logging.getLogger().debug(f"FPS: %s" % ( frame_count / (time.time() - start_time)))
                            frame_count = 0
                            start_time = time.time()
            except Exception as e:
                print(f'Removed streaming client {self.client_address}, {str(e)}')
        else:
            self.send_response(400)
            # fallback to default handler
            # super().do_GET()

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

