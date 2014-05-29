#!/usr/bin/python

import os
import sys
import time
import uuid
from stat import *
import subprocess
import threading
import avahi
import socket
import netifaces
import dbus

import ConfigParser

class ZeroconfService:
    """A simple class to publish a network service with zeroconf using
    avahi.
    """

    def __init__(self, name, port, stype="_http._tcp", subtype=None,
                 domain="", host="", text=""):
        self.name = name
        self.stype = stype
        self.domain = domain
        self.host = host
        self.port = port
        self.text = text
        self.subtype = subtype

    def publish(self):
        bus = dbus.SystemBus()
        server = dbus.Interface(
                         bus.get_object(
                                 avahi.DBUS_NAME,
                                 avahi.DBUS_PATH_SERVER),
                        avahi.DBUS_INTERFACE_SERVER)

        g = dbus.Interface(
                    bus.get_object(avahi.DBUS_NAME,
                                   server.EntryGroupNew()),
                    avahi.DBUS_INTERFACE_ENTRY_GROUP)

        g.AddService(avahi.IF_UNSPEC, avahi.PROTO_UNSPEC, dbus.UInt32(0),
                     self.name, self.stype, self.domain, self.host,
                     dbus.UInt16(self.port), self.text)

        if self.subtype:
            g.AddServiceSubtype(avahi.IF_UNSPEC,
                                avahi.PROTO_UNSPEC,
                                dbus.UInt32(0),
                                self.name, self.stype, self.domain,
                                self.subtype)

        g.Commit()
        self.group = g

    def unpublish(self):
        self.group.Reset()


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

    def __init__(self, uri, inifile, interface="",
                 ipv4="", svc_uuid=None, debug=False):
        threading.Thread.__init__(self)
        self.inifile = inifile
        self.interface = interface
        self.ipv4 = ipv4
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
        videoDevice.dsname = self.uri + self.ipv4 + ':' + str(videoDevice.port)
        videoDevice.zmqUri = self.uri + self.interface + ':' + str(videoDevice.port)

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

        me = uuid.uuid1()
        videoDevice.txtRecord = [str('dsn=' + videoDevice.dsname),
                              str('uuid=' + self.svc_uuid),
                              str('service=' + 'video'),
                              str('instance=' + str(me))]

        if self.debug:
            print (("txtrec:", videoDevice.txtRecord))

        try:
            videoDevice.sdname = id + ' on %s' % self.ipv4
            videoDevice.service = ZeroconfService(videoDevice.sdname, videoDevice.port,
                                           stype='_machinekit._tcp',
                                           subtype="_video._sub._machinekit._tcp",
                                           text=videoDevice.txtRecord)
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
        videoDevice.sd.close()
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
    given an interface preference list, return a tuple (interface, IPv4)
    or None if no match found
    If an interface has several IPv4 addresses, the first one is picked.
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
                # we want the first IPv4 address
                try:
                    ip = ifcfg[netifaces.AF_INET][0]['addr']
                except KeyError:
                    continue
                return (i, ip)
    return None


def main():
    debug = True
    uuid = os.getenv("MKUUID")
    if uuid is None:
        print >> sys.stderr, "no MKUUID environemnt variable set"
        print >> sys.stderr, "run export MKUUID=`uuidgen` first"
        sys.exit(1)

    prefs = ['wlan', 'eth', 'usb']

    iface = choose_ip(prefs)
    if not iface:
        print >> sys.stderr, "failed to determine preferred interface (preference = %s)" % prefs
        sys.exit(1)

    if debug:
        print (("announcing videoserver on ", iface))

    uri = "tcp://"

    video = VideoServer(uri, "video.ini",
                       svc_uuid=uuid,
                       interface=iface[0],
                       ipv4=iface[1],
                       debug=debug)
    video.setDaemon(True)
    video.start()
    video.startVideo('Webcam1')

    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()

