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
    
    def send(self, message):
        """
        The send function is used to send a command  with optional arguments to Popoto as
        a JSON string

        :param      message:  The message contains a Popoto command with optional arguments
        :type       message:  string
        """
        args =message.split(' ',1)

        # Break up the command and optional arguements around the space
        if len(args) > 1:
            command = args[0]
            arguments = args[1]
        else:
            command = message
            arguments = "Unused Arguments"

        # Build the JSON message
        message = "{ \"Command\": \"" + command + "\", \"Arguments\": \""+arguments + "\"}"

        # Send the message to the command socket
        self.cmdsocket.sendall(message + '\n')
   
    def drainReplyQ(self):
        """
        This function reads and dumps any data that currently resides in the
        Popoto reply queue.  This function is useful for putting the replyQ in a known
        empty state.
        """
        while self.replyQ.empty() == False:
            print(self.replyQ.get())
    
    def waitForReply(self, Timeout):
        """
        waitForReply is a method that blocks on the replyQ until either a reply has been
        received or a timeout (in seconds) occurs.
        
        :param      Timeout:  The timeout 
        :type       Timeout:  { type_description }
        """
        reply = self.replyQ.get(True, Timeout)
        return reply

    def startRx(self):
        """
        startRx places Popoto modem in receive mode.
        """
        self.send('Event_StartRx')

    def calibrateTransmit(self):
        """
        calibrateTransmit send performs a calibration cycle on a new transducer
        to allow transmit power to be specified in watts.  It does this by sending
        a known amplitude to the transducer while measuring voltage and current across 
        the transducer.  The resulting measured power is used to adjust scaling parameters
        in Popoto such that future pings can be specified in watts.
        """
        self.setValueF('TxPowerWatts', 1)
        self.send('Event_startTxCal')

    def transmitJSON(self, JSmessage):
        """
        The transmitJSON method sends an arbitrary user JSON message for transmission out the 
        acoustic modem. 
        
        :param      JSmessage:  The Users JSON message
        :type       JSmessage:  string
        """
        
        # Format the user JSON message into a TransmitJSON message for Popoto   
        message = "{ \"Command\": \"TransmitJSON\", \"Arguments\": " +JSmessage+" }"
        
        # Verify the JSON message integrity and send along to Popoto
        try:
            testJson = json.loads(message)
            print("Sending " + message)
            self.cmdsocket.sendall(message + '\n')
        except:
            print("Invalid JSON message: ", JSmessage)

    def getVersion(self):
        """
        Retrieve the software version of Popoto
        """
        self.send('GetVersion')

    def sendRange(self, power=.1):
        """
        Send a command to Popoto to initiate a ranging cycle to another modem
        
        :param      power:  The power in watts
        :type       power:  number
        """
        self.setValueF('TxPowerWatts', power)
        self.setValueI('CarrierTxMode', 0)
        self.send('Event_sendRanging')
    
    def recordStartTarget(self,filename, duration):
        """
        Initiate recording acoustic signal data to the local SD card.
        Recording is passband if  Popoto 'RecordMode' is 0
        Recording is baseband if  Popoto 'RecordMode' is 1
        
        :param      filename:  The filename on the local filesystem with path
        :type       filename:  string
        :param      duration:  The duration in seconds for continuous record to split-up
                                files with autonaming.  Typical value is 60 for 1 minute files.
        :type       duration:  number
        """
        self.send('StartRecording {} {}'.format(filename, duration))

    def recordStopTarget(self):
        """
        Turn off recording to local SD card
        """
        self.send('StopRecording')          

    def playStartTarget(self,filename, scale):
        """
        Play a PCM file of 32bit IEEE float values out the transmitter
        Playback is passband if  Popoto 'PlayMode' is 0
        Playback is baseband if  Popoto 'PlayMode' is 1
        
        :param      filename:  The filename of the pcm file on the SD card
        :type       filename:  string
        :param      scale:     The transmitter scale value 0-10; higher numbers result in
                                higher transmit power.
        :type       scale:     number
        """
	   print ("Playing {} at Scale {}".format(filename, scale))    
	   self.send('StartPlaying {} {}'.format(filename, scale))
    
    def playStopTarget(self):
        """
        End playout of stored PCM file through Popoto transmitter 
        """
        self.send('StopPlaying')
     
    def setValueI(self, Element, value):
        """
        Sets an integer value of a Popoto integer variable
        
        :param      Element:  The name of the variable to be set
        :type       Element:  string
        :param      value:    The value
        :type       value:    integer
        """
        self.send('SetValue {} int {} 0'.format(Element, value))        

    def setValueF(self, Element, value):
        """
        Sets a 32bit float value of a Popoto float variable
        
        :param      Element:  The name of the variable to be set
        :type       Element:  string
        :param      value:    The value
        :type       value:    float
        """
        self.send('SetValue {} float {} 0'.format(Element, value))        

    def getValueI(self, Element):
        """
        Gets an integer value of a Popoto integer variable
        
        :param      Element:  The name of the variable to be retreived
        :type       Element:  string
        :returns    value:    The value
        :type       value:    integer
        """
        self.send('GetValue {} int  0'.format(Element))        

    def getValueF(self, Element):
        """
        Gets the 32bit floating value of a Popoto float variable
        
        :param      Element:  The name of the variable to be retreived
        :type       Element:  string
        :returns    value:    The value
        :type       value:    float
        """
        self.send('GetValue {} float  0'.format(Element))        

    
    def tearDownPopoto(self):
        """
        The tearDownPopoto method provides a graceful exit from any python Popoto script

        """
        done=0
        self.is_running =0
        time.sleep(1)

    def setRtc(self, clockstr):
        """
        Sets the real time clock.
        
        :param      clockstr:  The clockstr contains the value of the date in string
                                format YYYY.MM.DD-HH:MM;SS
                                Note: there is no error checking on the string so make it right
        :type       clockstr:  string
        """
        self.send('SetRTC {}'.format(clockstr))

    def getRtc(self):
        """
        Gets the real time clock date and time.
        
        :returns     clockstr:  The clockstr contains the value of the date in string
                                format YYYY.MM.DD-HH:MM;SS
        :type       clockstr:   string
        """
        self.send('GetRTC')

    def __del__(self):
        # Destructor
        done = 0;

        # Read all data out of socket
        self.is_running =0


    def playPcmLoop(self, inFile, bb):
        """
        playPcmLoop 
        Play passband/baseband PCM for duration seconds.  
        :param      inFile:  In file
        :type       inFile:  string
        :param      bb:      selects passband or baseband data
        :type       bb:      number 0/1 for pass/base
        """
        self.pcmlogsocket=socket(AF_INET, SOCK_STREAM)
        self.pcmlogsocket.connect((self.ip, self.pcmlogport))
        self.pcmlogsocket.settimeout(1)
        if(self.pcmlogsocket == None):
            print("Unable to open PCM Log Socket")
            return
        # Set mode to either passband-0 or baseband-1
        self.setValueI('PlayMode', bb)
        
        # Start the play
        self.send('StartNetPlay 0 0')
       
        # Open the file for playing
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
            # Read socket of pcm data
            fdata = fpin.read(642*4)

            if(len(fdata) < 642*4):
                print('Done Reading File')
                Done = 1
           
            StartSample = sampleCounter
            while(sampleCounter == StartSample):
                try:
                    self.pcmlogsocket.send(fdata) # Send data over socket
                    sampleCounter += (len(fdata)-8)
                except:
                    print('Waiting For Network')
        
        duration = sampleCounter / (4*SampPerSec);  #  Bytes to Floats->seconds
        print('Duration {}'.format(duration))

        while(time.time() < s_time+duration):
            time.sleep(1)            
        
        # Terminate play
        self.send('Event_playPcmQueueEmpty')
    
        print("Exiting PCM Loop")
        self.pcmlogsocket.close()
        fpin.close()


    def recPcmLoop(self, outFile, duration, bb):
        """
        recPcmLoop records passband/baseband pcm for duration seconds.  
        This function also returns a vector of timestamps in pcmCount and a vector of 
        HiGain_LowGain flags 0=lo,1=hi which indicate which A/D
        channel was selected on a frame basis
        
        Code sets baseband mode as selected on input, but changes back to pass
        band mode on exit.  Base band recording and normal modem function are
        mutually exclusive, as they share the Modem's Digital up converter.

        :param      outFile:   The output filename with path
        :type       outFile:   string
        :param      duration:  The duration of recording in seconds
        :type       duration:  number
        :param      bb:        passband or baseband selection
        :type       bb:        number 0/1 passband/baseband
        """
        
        # Open and configure streaming port 
        self.pcmlogsocket=socket(AF_INET, SOCK_STREAM)
        self.pcmlogsocket.connect((self.ip, self.pcmlogport))
        self.pcmlogsocket.settimeout(1)

        # Set mode to either passband-0 or baseband-1
        self.setValueI('RecordMode', bb)
        if(bb == 1):
            duration = duration * 10240 *2   # Baseband rate 10240 Cplx samples /sec
        else:
            duration = duration *102400

    
        if(self.pcmlogsocket == None):
            print("Unable to open PCM Log Socket")
            self.setValueI('RecordMode', 0)
            return

        # Open the recording file
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
                fromRx=self.pcmlogsocket.recv(642*4); # Read the socket
                if fpout != None:
                    fpout.write(fromRx)     # write the data
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
      
    def streamUpload(self, filename, power):
        """
        streamUpload Upload a file for acoustic transmission
        
        :param      filename:  The filename to be sent with path
        :type       filename:  string
        :param      power:     The desired power in watts
        :type       power:     number
        """

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
            fileChars = f.read(nbytes)
       
            try:
                count=self.datasocket.send(fileChars);
            except:
                print("ERROR SENDING ON  DATA SOCKET")
            
        print("Upload Complete")
        print("Sent out %d",count)
        f.close();

    def getParametersList(self):
        """
        Gets the parameters list from the system controller.
        """
        return self.paramsList

    def getParameter(self, idx):
        """
        Gets a Popoto control element info string by element index.
        
        :param      idx:  The index is the reference number of the element
        :type       idx:  number
        """
        self.send('GetParameters {}'.format(idx))        
 
    def getAllParameters(self):
        """
        Gets all Popoto control element info strings for all elements.
        """
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
# -------------------------------------------------------------------
# Popoto Internal NON Public API commands are listed below this point
# -------------------------------------------------------------------
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
   
    def receive(self):
        data = self.cmdsocket.recv(256)

    def close(self):
        self.cmdsocket.close() 

    def setTimeout(self, timeout):
        self.cmdsocket.settimeout(timeout)

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


    def dispMips(self, mips):
        v = {};
        print('Name                            |       min  |        max |     total  |      count |    average |  peak mips | avg mips')
        for module in mips:
            v = mips[module]
            name = module 
            print('{:<32}|{:12}|{:12}|{:12.1e}|{:12}|{:12.1f}|{:12.1f}|{:12.1f}'.format(name,v['min'],v['max'],v['total'], v['count'], v['total']/v['count'], v['max']*160/1e6, (160/1e6)*v['total']/v['count'] ))



