#!/usr/bin/python

import os,sys,time,uuid
from stat import *
import subprocess
import time
import zmq
import threading
import pybonjour
import socket
import sdiscover
import netifaces
import uuid

import ConfigParser

def register_callback(sdRef, flags, errorCode, name, regtype, domain):
    if errorCode == pybonjour.kDNSServiceErr_NoError:
        print 'Registered service:'
        print '  name    =', name
        print '  regtype =', regtype
        print '  domain  =', domain

class VideoDevice:
    process = None
    sdref = None
    sd = None
    txtRecord = None
    sdname = ''
    framerate = 30
    resolution = '640x480'
    device = '/dev/video0'
    bufferSize = 2
    port = 0
    dsname = ''
    zmqUri = ''

class VideoServer(threading.Thread):
    
    def __init__(self, uri, inifile, interface="", 
                 ipv4="", svc_uuid=None):
        threading.Thread.__init__(self)
        self.inifile = inifile
        self.interface = interface
        self.ipv4 = ipv4
        self.uri = uri
        self.svc_uuid = svc_uuid

        self.videoDevices = {}
        self.cfg = ConfigParser.ConfigParser()
        self.cfg.read(self.inifile)
        print "video devices:", self.cfg.sections()
        for n in self.cfg.sections():
            videoDevice = VideoDevice()
            
            videoDevice.framerate = self.cfg.getint(n, 'framerate')
            videoDevice.resolution = self.cfg.get(n, 'resolution')
            videoDevice.device = self.cfg.get(n, 'device')
            videoDevice.bufferSize = self.cfg.getint(n, 'bufferSize')
            self.videoDevices[n] = videoDevice
            #print "framerate:", videoDevice.framerate
            #print "resolution:", videoDevice.resolution
            #print "device:", videoDevice.device
            #print "bufferSize:", videoDevice.bufferSize
            
    def startVideo(self, id):
        videoDevice = self.videoDevices[id]
        
        if videoDevice.process != None:
            print ("video device already running")
            return
        
        sock = socket.socket()
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()
        
        videoDevice.port = port
        videoDevice.dsname = self.uri + self.ipv4 + ':' + str(videoDevice.port)
        videoDevice.zmqUri = self.uri + self.interface + ':' + str(videoDevice.port)
        
        os.environ['LD_LIBRARY_PATH'] = os.getcwd()

        command = ['mjpg_streamer -i \"./input_uvc.so -n'
            + ' -f ' + str(videoDevice.framerate) 
            + ' -r ' + videoDevice.resolution 
            + ' -d ' + videoDevice.device 
            + '" -o \"./output_zmqserver.so --address '
            + videoDevice.zmqUri
            + ' --buffer_size ' + str(videoDevice.bufferSize) + '\"']
        print (command)
        videoDevice.process = subprocess.Popen(command, shell=True)
        
        me = uuid.uuid1()
        videoDevice.txtrec = pybonjour.TXTRecord({'dsn' : videoDevice.dsname,
                                           'uuid': self.svc_uuid,
                                           'service' : 'video',
                                           'instance' : str(me) })
        
        try:
            videoDevice.sdname = id + ' on %s' % self.ipv4
            videoDevice.sdref = pybonjour.DNSServiceRegister(regtype = '_machinekit._tcp,_video',
                                                      name = videoDevice.sdname,
                                                      port = videoDevice.port,
                                                      txtRecord = videoDevice.txtrec,
                                                      callBack = register_callback)
            videoDevice.sd = videoDevice.sdref.fileno()
        except:
            print 'cannot register DNS service'
        
    def stopVideo(self, id):
        videoDevice = self.videoDevices[id]
        
        if videoDevice.process == None:
            print ("video device not running")
            return
        
        videoDevice.process.terminate()
        videoDevice.sd.close()
        videoDevice.process = None
        videoDevice.sd = None
        videoDevice.sdref = None
        
    def run(self):
        print "run called"
        poll = zmq.Poller()
        
        try:
            while True:
                s = dict(poll.poll(1000))
                for n in self.videoDevices:
                    videoDevice = self.videoDevices[n]
                    if videoDevice.sd == None:
                        continue
                    if videoDevice.sd in s:
                        pybonjour.DNSServiceProcessResult(videoDevice.sdref)
        except KeyboardInterrupt:
            for n in self.videoDevices:
                videoDevice = self.videoDevices[n]
                if videoDevice.process == None:
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
    trace = False
    uuid = os.getenv("MKUUID")
    if uuid is None:
        print >> sys.stderr, "no MKUUID environemnt variable set"
        print >> sys.stderr, "run export MKUUID=`uuidgen` first"
        sys.exit(1)
        
    prefs = ['wlan','eth','usb']

    iface = choose_ip(prefs)
    if not iface:
       print >> sys.stderr, "failed to determine preferred interface (preference = %s)" % prefs
       sys.exit(1)

    if debug:
        print "announcing videoserver on ",iface

    uri = "tcp://"

    video = VideoServer(uri, "video.ini",
                       svc_uuid=uuid,
                       interface = iface[0],
                       ipv4 = iface[1])
    video.setDaemon(True)
    video.start()
    video.startVideo('Webcam1')

    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()

