#!/usr/bin/python

import os
import sys
import time
from stat import *
import subprocess
import threading
import socket
import netifaces

import ConfigParser
from machinekit import service


class VideoDevice:
    process = None
    service = None
    txtRecord = None
    sdname = ''
    framerate = 30
    resolution = '640x480'
    quality = 80
    device = '/dev/video0'
    bufferSize = 2
    port = 0
    dsname = ''
    zmqUri = ''


class VideoServer(threading.Thread):

    def __init__(self, uri, inifile, ip="", svc_uuid=None, debug=False):
        threading.Thread.__init__(self)
        self.inifile = inifile
        self.interface = interface
        self.ip = ip
        self.uri = uri
        self.svc_uuid = svc_uuid
        self.debug = debug

        self.videoDevices = {}
        self.cfg = ConfigParser.ConfigParser()
        self.cfg.read(self.inifile)
        if self.debug:
            print (("video devices:", self.cfg.sections()))
        for n in self.cfg.sections():
            videoDevice = VideoDevice()

            videoDevice.framerate = self.cfg.getint(n, 'framerate')
            videoDevice.resolution = self.cfg.get(n, 'resolution')
            videoDevice.quality = self.cfg.get(n, 'quality')
            videoDevice.device = self.cfg.get(n, 'device')
            videoDevice.bufferSize = self.cfg.getint(n, 'bufferSize')
            self.videoDevices[n] = videoDevice
            if self.debug:
                print (("framerate:", videoDevice.framerate))
                print (("resolution:", videoDevice.resolution))
                print (("quality:", videoDevice.quality))
                print (("device:", videoDevice.device))
                print (("bufferSize:", videoDevice.bufferSize))

    def startVideo(self, id):
        videoDevice = self.videoDevices[id]

        if videoDevice.process is not None:
            print ("video device already running")
            return

        sock = socket.socket()
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()

        videoDevice.port = port
        videoDevice.dsname = self.uri + self.ip + ':' + str(videoDevice.port)
        videoDevice.zmqUri = self.uri + self.ip + ':' + str(videoDevice.port)

        if self.debug:
            print ((
                "dsname = ", videoDevice.dsname,
                "port =", videoDevice.port))

        libpath = '/usr/local/lib/'
        os.environ['LD_LIBRARY_PATH'] = libpath

        command = ['mjpg_streamer -i \"' + libpath + 'input_uvc.so -n'
            + ' -f ' + str(videoDevice.framerate)
            + ' -r ' + videoDevice.resolution
            + ' -q ' + videoDevice.quality
            + ' -d ' + videoDevice.device
            + '" -o \"' + libpath + 'output_zmqserver.so --address '
            + videoDevice.zmqUri
            + ' --buffer_size ' + str(videoDevice.bufferSize) + '\"']

        if self.debug:
            print (("command:", command))

        videoDevice.process = subprocess.Popen(command, shell=True)

        try:
            videoDevice.service = service.Service(type='video',
                                  svcUuid=svc_uuid,
                                  dsn=videoDevice.dsname,
                                  port=videoDevice.port,
                                  ip=self.ip,
                                  debug=self.debug)
            videoDevice.service.publish()
        except Exception as e:
            print (('cannot register DNS service', e))

    def stopVideo(self, id):
        videoDevice = self.videoDevices[id]

        if videoDevice.process is None:
            print ("video device not running")
            return

        videDevice.service.unpublish()
        videoDevice.process.terminate()
        videoDevice.process = None
        videoDevice.service = None

    def run(self):
        if self.debug:
            print ("run called")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            for n in self.videoDevices:
                videoDevice = self.videoDevices[n]
                if videoDevice.process is None:
                    continue
                stopVideo(n)


def choose_ip(pref):
    '''
    given an interface preference list, return a tuple (interface, ip)
    or None if no match found
    If an interface has several ip addresses, the first one is picked.
    pref is a list of interface names or prefixes:

    pref = ['eth0','usb3']
    or
    pref = ['wlan','eth', 'usb']
    '''

    # retrieve list of network interfaces
    interfaces = netifaces.interfaces()

    # find a match in preference oder
    for p in pref:
        for i in interfaces:
            if i.startswith(p):
                ifcfg = netifaces.ifaddresses(i)
                # we want the first ip address
                try:
                    ip = ifcfg[netifaces.AF_INET][0]['addr']
                except KeyError:
                    continue
                return (i, ip)
    return None


def main():
    debug = True

    mkini = os.getenv("MACHINEKIT_INI")
    if mkini is None:
        sys.stderr.write("no MACHINEKIT_INI environemnt variable set")
        sys.exit(1)

    mki = ConfigParser.ConfigParser()
    mki.read(mkini)
    mkUuid = mki.get("MACHINEKIT", "MKUUID")
    remote = mki.getint("MACHINEKIT", "REMOTE")
    prefs = mki.get("MACHINEKIT", "INTERFACES").split()

    if remote == 0:
        print("Remote communication is deactivated, mkwrapper will use the loopback interfaces")
        print(("set REMOTE in " + mkini + " to 1 to enable remote communication"))
        iface = ['lo', '127.0.0.1']
    else:
        iface = choose_ip(prefs)
        if not iface:
            sys.stderr.write("failed to determine preferred interface (preference = %s)" % prefs)
            sys.exit(1)

    if debug:
        print (("announcing videoserver on ", iface))

    uri = "tcp://"

    video = VideoServer(uri, "video.ini",
                       svc_uuid=mkUuid,
                       ip=iface[1],
                       debug=debug)
    video.setDaemon(True)
    video.start()
    video.startVideo('Webcam1')

    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()

