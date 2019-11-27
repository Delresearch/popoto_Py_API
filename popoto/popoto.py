#!/usr/bin/python
from __future__ import print_function
from socket import socket, AF_INET, SOCK_STREAM, IPPROTO_TCP, TCP_NODELAY,   SHUT_RDWR
from socket import error as socket_error
import sys
import time
import threading
import cmd
import json
import Queue
import struct

import logging
import os
import os.path
import functools

PCMLOG_OFFSET=2

class popoto:
    '''  
    An API for the Popoto Modem product

    This class can run on the local Popoto Modem,  or can be run
    remotely on a PC.

    All commands are sent via function calls, and all JSON encoded responses and status
    from the modem are enqueued as Python objects in the reply queue.

    In order to do this, the class launches a processing thread that looks for replies 
    decodes the JSON and adds the resulting python object into the reply queue. 

    The Popoto class requires an IP address and port number to communicate with the Popoto Modem.
    This Port number corresponds to the base port of the modem application.


    '''
    def __init__(self, ip='localhost', basePort=17000): 
        logging.info("Popoto Init Called")        
        self.pcmioport  = basePort+3
        self.pcmlogport = basePort+2
        self.dataport   = basePort+1
        self.cmdport    = basePort
        self.quiet = 0
        logging.info("Opening Command Socket")
        self.cmdsocket=socket(AF_INET, SOCK_STREAM)
        self.cmdsocket.connect((ip, basePort))
        self.cmdsocket.settimeout(20)

        self.SampFreq = 102400        
        self.pcmlogsocket = 0
        self.recByteCount = 0
        self.ip = ip
        self.is_running = True
        self.fp = None;
        self.fileLock = threading.Lock()
        logging.info("Starting Command Thread")
        self.rxThread = threading.Thread(target=self.RxCmdLoop, name="CmdRxLoop")
        self.rxThread.start();
        self.replyQ = Queue.Queue()
        self.datasocket = None
        logging.info("Starting pcmThread")
        self.intParams = {}
        self.floatParams = {}
	self.verbose = 2    
        self.getAllParameters()
    
    def RxCmdLoop(self):
        errorcount = 0
        rxString = ''
        self.cmdsocket.settimeout(1)
        while(self.is_running ==True):
            try:
                data = self.cmdsocket.recv(1)
                if(len(data) >= 1):

                    if ord(data)  != 13:
                        rxString = rxString+str(data);
                     
                    else:
                        
                        idx = rxString.find("{")
                        msgType = rxString[0:idx]
                        msgType = msgType.strip();

                        jsonData = rxString[idx:len(rxString)]
                        try:
                            reply = json.loads(jsonData)
                            self.replyQ.put(reply)
                        except:
                            print("Unparseable JSON message " + jsonData)
                        if(self.verbose > 1):
				print("\033[1m"+str(jsonData)+"\033[0m")
                        logging.info(str(jsonData))
                        rxString = ''
            
            except socket_error  as s_err:
                errorcount = errorcount +1 
        print("exiting RxCmd")
    def exit(self):
        print ("Stub for exit routine")
    def send(self, message):
        args =message.split(' ',1)

        if len(args) > 1:
            command = args[0]
            arguments = args[1]
        else:
            command = message
            arguments = "Unused Arguments"

        message = "{ \"Command\": \"" + command + "\", \"Arguments\": \""+arguments + "\"}"

        self.cmdsocket.sendall(message + '\n')
      
    def receive(self):
        data = self.cmdsocket.recv(256)

    def close(self):
        self.cmdsocket.close() 

    def settimeout(self, timeout):
        self.cmdsocket.settimeout(timeout)

    def getParametersList(self):
        return self.paramsList

    def drainReplyQ(self):
        while self.replyQ.empty() == False:
            print(self.replyQ.get())
    
    def waitForReply(self, Timeout):
        reply = self.replyQ.get(True, Timeout)
        return reply

    def sendPing(self, power=.1):
        self.setValueF('TxPowerWatts', power)
        self.setValueI('CarrierTxMode', 0)
        self.send('Event_sendTestPacket')
    def getCycleCount(self):
        while self.replyQ.empty() == False:
            self.replyQ.get()

        self.getValueI('APP_CycleCount')
        reply = self.replyQ.get(True, 3)    
        if reply:    
            if "Application.0" in reply:
                self.dispmips(reply)

        else:
            print("Get CycleCount Timeout")


    def dispmips(self, mips):
        v = {};
        print('Name                            |       min  |        max |     total  |      count |    average |  peak mips | avg mips')
        for module in mips:
            v = mips[module]
            name = module 
            print('{:<32}|{:12}|{:12}|{:12.1e}|{:12}|{:12.1f}|{:12.1f}|{:12.1f}'.format(name,v['min'],v['max'],v['total'], v['count'], v['total']/v['count'], v['max']*160/1e6, (160/1e6)*v['total']/v['count'] ))



    def startRx(self):
        self.send('Event_StartRx')

    def calibrate(self):
        self.setValueF('TxPowerWatts', 1)
 
        self.send('Event_startTxCal')

    def transmitJSON(self, JSmessage):
     
        message = "{ \"Command\": \"TransmitJSON\", \"Arguments\": " +JSmessage+" }"
        try:
            testJson = json.loads(message)
            print("Sending " + message)
            self.cmdsocket.sendall(message + '\n')
        except:
            print("Invalid JSON message: ", JSmessage)


       



    def version(self):
        self.send('GetVersion')

    def sendRange(self, power=.1):
        self.setValueF('TxPowerWatts', power)
        self.setValueI('CarrierTxMode', 0)
        self.send('Event_sendRanging')
    
    def recordStartTarget(self,filename, duration):
        self.send('StartRecording {} {}'.format(filename, duration))
    def recordStopTarget(self):
        self.send('StopRecording')          

    def playStartTarget(self,filename, scale):
	print ("Playing {} at Scale {}".format(filename, scale))    
	self.send('StartPlaying {} {}'.format(filename, scale))
    def playStopTarget(self):
        self.send('StopPlaying')



    def recordStart(self, filename):
        with self.fileLock:
            self.fp = open(filename, 'w')
            self.recByteCount = 0;
        
        if(self.fp is not None):
            print('Record Started for Filename {}'.format(filename))

    def recordStop(self):
        #self.send('StopRecording')
        with self.fileLock:
            self.fp.close()
            self.fp = None
            print('Record Stopped {} bytes Recorded'.format( self.recByteCount) )
       
    
    def getInbandEnergy(self):
        self.getValueF('GetInbandEnergy')



    def setGainMode(self, value=2):
        self.setValueI('GainAdjustMode', value)

    def setValueI(self, Element, value):
        self.send('SetValue {} int {} 0'.format(Element, value))        

    def setValueF(self, Element, value):
        self.send('SetValue {} float {} 0'.format(Element, value))        

    def getValueI(self, Element):
        self.send('GetValue {} int  0'.format(Element))        

    def getValueF(self, Element):
        self.send('GetValue {} float  0'.format(Element))        

    def getParameter(self, idx):
        self.send('GetParameters {}'.format(idx))        
    

    def getAllParameters(self):
        idx = 0;
        try:
            while idx >= 0:
                self.getParameter(idx)
                reply = self.replyQ.get(True, 3)    
                if reply:    
                    if "Element" in reply:
                        El = reply['Element']
                        if 'nextidx' in El:
                            idx = int(El['nextidx'])
                        if  int(El['nextidx'])  > 0:
                            if (El['Format'] == 'int'):
                                self.intParams[El['Name']] = El
                            else:
                                self.floatParams[El['Name']] = El
                    if El['Channel'] == 0:
                        print('{}:{}:{}'.format(El['Name'], El['Format'], El['description']))
                    #print(reply)
                else:
                    print("GetParameter Timeout")

                    idx = -1
        except Exception, a:
            print(a)
            return
    def teardownpopoto(self):
        done=0
        self.is_running =0
        time.sleep(1)


    def setRtc(self, clockstr):
        self.send('SetRTC {}'.format(clockstr))

    def getRtc(self):
        self.send('GetRTC')


    def __del__(self):
        done = 0;

        # Read all data out of socket
        self.is_running =0


    def PlayPcmLoop(self, inFile, bb):
        # Record passband pcm for duration seconds.  This function also
        # returns a vector of timestamps in pcmCount and a vector of
        # HiGain_LowGain flags 0=lo,1=hi which indicate which A/D
        # channel was selected on a frame basis
        self.pcmlogsocket=socket(AF_INET, SOCK_STREAM)
        self.pcmlogsocket.connect((self.ip, self.pcmlogport))
        self.pcmlogsocket.settimeout(1)
        if(self.pcmlogsocket == None):
            print("Unable to open PCM Log Socket")
            return

        self.setValueI('PlayMode', bb)
        
        self.send('StartNetPlay 0 0')
       
        fpin  = open(inFile, 'r')
        if(fpin == None):
            print("Unable to Open {} for Reading")
            return
        s_time = time.time()
        sampleCounter = 0 
        if(bb):
            SampPerSec = 10240 *2
        else:
            SampPerSec = 102400

        Done = 0
        while Done == 0:
            # Read socket
            fdata = fpin.read(642*4)

            if(len(fdata) < 642*4):
                print('Done Reading File')
                Done = 1
           
            StartSample = sampleCounter
            while(sampleCounter == StartSample):
                try:
                    self.pcmlogsocket.send(fdata)
                    sampleCounter += (len(fdata)-8)
                except:
                    print('Waiting For Network')
        

        duration = sampleCounter / (4*SampPerSec);  #  Bytes to Floats->seconds
        print('Duration {}'.format(duration))

        while(time.time() < s_time+duration):
            time.sleep(1)            
        
        self.send('Event_playPcmQueueEmpty')
    
        print("Exiting PCM Loop")
        self.pcmlogsocket.close()
        fpin.close()


    def RecPcmLoop(self, outFile, duration, bb):
        # Record passband pcm for duration seconds.  This function also
        # returns a vector of timestamps in pcmCount and a vector of
        # HiGain_LowGain flags 0=lo,1=hi which indicate which A/D
        # channel was selected on a frame basis
        # Code sets baseband mode as selected on input, but changes back to pass
        # band mode on exit.  Base band recording and normal modem function are
        # mutually exclusive, as they share the Modem's Digital up converter. 
        self.pcmlogsocket=socket(AF_INET, SOCK_STREAM)
        self.pcmlogsocket.connect((self.ip, self.pcmlogport))
        self.pcmlogsocket.settimeout(1)

        self.setValueI('RecordMode', bb)
        if(bb == 1):
            duration = duration * 10240 *2   # Baseband rate 10240 Cplx samples /sec
        else:
            duration = duration *102400


       
        if(self.pcmlogsocket == None):
            print("Unable to open PCM Log Socket")
            self.setValueI('RecordMode', 0)
            return

        fpout = open(outFile,'w')
        if(fpout == None):
            print("Unable to Open {} for Writing")
            self.setValueI('RecordMode', 0)
            return      
              
        self.recByteCount = 0
        Done = 0
        while Done == 0:
            # Read socket
            try:
                fromRx=self.pcmlogsocket.recv(642*4);
                if fpout != None:
                    fpout.write(fromRx)
                self.recByteCount = self.recByteCount + len(fromRx)-2;
                if (self.recByteCount >= duration*4):
                    Done=1
                FrameCounter = FrameCounter +1
                if FrameCounter > 80:
                    print('.')
                    FrameCounter = 0
            except:
                continue



        print("Exiting PCM Loop")
        self.pcmlogsocket.close()
        fpout.close()
        self.setValueI('RecordMode', 0)
      
    def StreamUpload(self, filename, power):
        # Stream a file
             # Set the file size


        if(self.datasocket == None):            
            self.datasocket=socket(AF_INET, SOCK_STREAM)

            self.datasocket.connect((self.ip, self.dataport))
            self.datasocket.settimeout(10)
            self.datasocket.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)

            if(self.datasocket == None):
                print("Unable to open data Socket")
                return
           
        if os.path.isfile(filename) and os.access(filename, os.R_OK):
            print("File exists and is readable")
            nbytes = os.path.getsize(filename)
            print("File is %d bytes" % nbytes )  
        else:
            print ("Either the file is missing or not readable")
            return

        # All good with the file lets upload
        done = 0
        while(done == 0):
            try:
                self.replyQ.get(False)
            except:
                done =1
   
        self.setValueI('TCPecho',0)
        self.setValueI('ConsolePacketBytes', 256)
        self.setValueI('ConsoleTimeoutMS', 500)
        self.setValueI('StreamingTxLen', nbytes)
        self.setValueI('PayloadMode', 1)
     	self.setValueF('TxPowerWatts', power)
   
        done = 0
        while(done == 0):
            time.sleep(.1)
            resp = self.replyQ.get()
            print("Got a response")
            print(resp)
            if('PayloadMode' in resp['Info']):
                done = 1
   

# Read each character and send it to the socket
        sent=0
        with open(filename) as f:
            '''
            f_read_ch = functools.partial(f.read, 6657)
            for ch in iter(f_read_ch, ''):
                #print('Read a character:', repr(ch))
                # Escape the telnet 255 chars  ToDo:

                try:
                    count=self.datasocket.send(ch);
                    #count = 0
                    #while (count < 1): 
                    #    count = self.datasocket.send(ch)
                    #    sent=sent+1
                except:
                    print("ERROR SENDING ON  DATA SOCKET")
                    continue
            '''
            fileChars = f.read(nbytes)
            
            try:
                count=self.datasocket.send(fileChars);
               
            except:
                print("ERROR SENDING ON  DATA SOCKET")
            
        print("Upload Complete")
        print("Sent out %d",count)
        f.close();



if __name__ == '__main__':
    mt = popoto()
    mt.sendRange()

   
