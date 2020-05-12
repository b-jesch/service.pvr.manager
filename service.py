# -*- coding: utf-8 -*-

from resources.lib.tools import *

import sys
import stat
import random

TIME_OFFSET = int(round((datetime.datetime.now() - datetime.datetime.utcnow()).seconds, -1))
JSON_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

SHUTDOWN_CMD = xbmc.translatePath(os.path.join(PATH, 'resources', 'lib', 'shutdown.sh'))
SHUTDOWN_METHOD = [LS(30012), LS(30013), LS(30025)]
SHUTDOWN_MODE = [LS(30006), LS(30026)]
EXTGRABBER = xbmc.translatePath(os.path.join(PATH, 'resources', 'lib', 'epggrab_ext.sh'))

ACTION_SELECT = 7

osv = release()
writeLog(None, 'OS ID is %s' % (osv['osid']))

if ('libreelec' or 'openelec') in osv['osid'] and getAddonSetting('sudo', sType=BOOL):
    ADDON.setSetting('sudo', 'false')
    writeLog(None, 'Reset wrong setting \'sudo\' to False')

# set permissions for these files, required after installation or update

_sts = os.stat(SHUTDOWN_CMD).st_mode
_stg = os.stat(EXTGRABBER).st_mode
if not (_sts & stat.S_IXOTH): os.chmod(SHUTDOWN_CMD, _sts | stat.S_IXOTH)
if not (_stg & stat.S_IXOTH): os.chmod(EXTGRABBER, _stg | stat.S_IXOTH)

CYCLE = 30  # polling cycle

# binary Flags

isRES = 0b10000     # TVH PM has started by Resume on record/EPG
isNET = 0b01000     # Network is active
isPRG = 0b00100     # Programs/Processes are active
isREC = 0b00010     # Recording is or becomes active
isEPG = 0b00001     # EPG grabbing is active
isUSR = 0b00000     # User is active


class KeyMonitor(xbmcgui.WindowDialog):

    abort = False
    procNum = None

    def __init__(self, *args):
        self.procNum = args[0]
        writeLog(self.procNum, 'create KeyMonitor object')
        xbmcgui.WindowDialog.__init__(self)
        self.show()

    def onAction(self, action):
        writeLog(self.procNum, 'Keypress detected: %s' % action)
        if action == ACTION_SELECT: self.abort = True


class Manager(object):

    def __init__(self):

        self.wakeREC = None
        self.wakeEPG = None
        self.wakeUTC = None

        self.rndProcNum = random.randint(1, 1024)
        self.hasPVR = None
        self.flags = isUSR

        self.__monitored_ports = self.createwellformedlist('monitored_ports')
        self.__pp_list = self.createwellformedlist('processor_list')

        writeLog(self.rndProcNum, 'Settings loaded')

        # PVR server

        _st = int(time.time())
        _attempts = getAddonSetting('conn_attempts', sType=NUM, multiplicator=5)
        while not self.hasPVR and _attempts > 0:
            query = {'method': 'PVR.GetProperties',
                     'params': {'properties': ['available']}}
            response = jsonrpc(query)
            self.hasPVR = True if (response is not None and response.get('available', False)) else False
            if self.hasPVR: break
            xbmc.sleep(1000)
            _attempts -= 1
        writeLog(self.rndProcNum, 'Wait %s seconds for PVR response' % (int(time.time()) - _st))
        if not self.hasPVR:
            writeLog(self.rndProcNum, 'PVR timed out', xbmc.LOGFATAL)
            notify(ADDON_NAME, LS(30032), icon=xbmcgui.NOTIFICATION_WARNING)


    @classmethod
    def createwellformedlist(cls, setting):
        """
        transform possible ugly userinput (e.g. 'p1, p2,,   p3 p4  ') to a shapely list
        """
        return ' '.join(getAddonSetting(setting).replace(',', ' ').split()).split()


    def local_to_utc_datetime(self, local_datetime):
        """
        converts local datetime to datetime in utc
        :param: local_datetime as datetime object
        :return: utc_datetime as datetime object
        """
        if local_datetime == None: return datetime.datetime.fromtimestamp(0)
        return local_datetime - datetime.timedelta(seconds=TIME_OFFSET)

    def utc_to_local_datetime(self, utc_datetime):
        """
        converts utc_datetime to datetime in local timezone
        :param: utc_datetime as datetime object
        :return: loacl_datetime as datetime object
        """
        if utc_datetime == None: return datetime.datetime.fromtimestamp(0)
        return utc_datetime + datetime.timedelta(seconds=TIME_OFFSET)

    def get_pvr_events(self, flags):
        __curTime = datetime.datetime.utcnow()

        if self.hasPVR:
            # Check for current recordings
            query = {'method': 'PVR.GetProperties',
                     'params': {'properties': ['recording']}}
            response = jsonrpc(query)
            if response is not None and bool(response.get('recording', False)):
                flags |= isREC
            else:
                # Check for timers
                query = {'method': 'PVR.GetTimers',
                         'params': {'properties': ['starttime', 'startmargin', 'istimerrule', 'state']}}
                response = jsonrpc(query)
                if response is not None and response.get('timers', False):
                    for timer in response.get('timers'):
                        if timer['istimerrule'] or timer['state'] == 'disabled' or \
                                (strpTimeBug(timer['starttime'], JSON_TIME_FORMAT)  < __curTime): continue
                        self.wakeREC = strpTimeBug(timer['starttime'], JSON_TIME_FORMAT) - \
                        datetime.timedelta(minutes=timer['startmargin'])
                        if (self.wakeREC - __curTime).seconds < \
                                (getAddonSetting('margin_start', sType=NUM) + getAddonSetting('margin_stop', sType=NUM)):
                            flags |= isREC
                            writeLog(self.rndProcNum, 'Next recording starts in %s secs' % ((self.wakeREC - __curTime).seconds))
                        else:
                            flags |= isRES
                            writeLog(self.rndProcNum, 'No active timers yet, prepare timer@%s' % (self.wakeREC.strftime(JSON_TIME_FORMAT)))
                        break
                else:
                    self.wakeREC = None

        # Calculate next EPG
        if getAddonSetting('epgtimer_interval', sType=NUM) > 0:
            __dayDelta = int(__curTime.strftime('%j')) % getAddonSetting('epgtimer_interval', sType=NUM)
            __epg = __curTime + datetime.timedelta(days=__dayDelta)
            self.wakeEPG = self.local_to_utc_datetime(__epg.replace(hour=getAddonSetting('epgtimer_time', sType=NUM),
                                                                    minute=0, second=0, microsecond=0))
            if self.wakeEPG - datetime.timedelta(seconds=getAddonSetting('margin_start', sType=NUM) + getAddonSetting('margin_stop', sType=NUM)) <= \
                    __curTime <= self.wakeEPG + datetime.timedelta(minutes=getAddonSetting('epgtimer_duration', sType=NUM)):
                flags |= isEPG
            else:
                flags |= isRES
        else:
            self.wakeEPG = None
        return flags

    def getSysState(self):
        _flags = isUSR
        __curTime = datetime.datetime.utcnow()

        # Check for PVR events
        _flags |= self.get_pvr_events(_flags)

        # Check if any watched process is running
        if getAddonSetting('postprocessor_enable', sType=BOOL):
            for _proc in self.__pp_list:
                if getProcessPID(_proc): _flags |= isPRG

        # Check for active network connection(s)
        if getAddonSetting('network', sType=BOOL):
            _port = []
            for port in self.__monitored_ports:
                nwc = subprocess.Popen('netstat -an | grep -iE "(established|verbunden)" | grep -v "127.0.0.1" | grep ":%s "' %
                                       port, stdout=subprocess.PIPE, shell=True).communicate()
                nwc = nwc[0].strip()
                if nwc and len(nwc.split('\n')) > 0:
                    _flags |= isNET
                    _port.append(port)
            if _port: writeLog(self.rndProcNum, 'Network on port %s established and active' % (', '.join(_port)))

        if self.flags ^ _flags:
            writeLog(self.rndProcNum, 'Status changed: {0:05b} (RES/NET/PRG/REC/EPG)'.format(_flags))
        self.flags = _flags
        return _flags

    def calcNextSched(self):
        __curTime = datetime.datetime.utcnow()
        _flags = self.getSysState() & isRES

        if not self.wakeREC:
            writeLog(self.rndProcNum, 'No recordings to schedule')

        if not self.wakeEPG:
            writeLog(self.rndProcNum, 'No EPG to schedule')
        elif self.wakeEPG < __curTime:
            self.wakeEPG = self.wakeEPG + datetime.timedelta(days=getAddonSetting('epgtimer_interval', sType=NUM))

        if _flags:
            id4msg = 30018
            if self.wakeREC and not self.wakeEPG:
                self.wakeUTC = self.wakeREC
            elif self.wakeEPG and not self.wakeREC:
                self.wakeUTC = self.wakeEPG
                id4msg = 30019
            elif self.wakeREC and self.wakeEPG and self.wakeREC <= self.wakeEPG:
                self.wakeUTC = self.wakeREC
            else:
                self.wakeUTC = self.wakeEPG
                id4msg = 30019

            # show notifications
            time4msg = self.utc_to_local_datetime(self.wakeUTC).strftime(JSON_TIME_FORMAT)
            if id4msg == 30018:
                writeLog(self.rndProcNum, 'Wakeup for recording at %s' % (time4msg))
                _flags |= isREC
                if getAddonSetting('next_schedule', sType=BOOL): notify(LS(30017), LS(id4msg) % (time4msg))
            elif id4msg == 30019:
                writeLog(self.rndProcNum, 'Wakeup for EPG update at %s' % (time4msg))
                _flags |= isEPG
                if getAddonSetting('next_schedule', sType=BOOL): notify(LS(30017), LS(id4msg) % (time4msg))
        else:
            if getAddonSetting('next_schedule', sType=BOOL): notify(LS(30010), LS(30014))
        xbmc.sleep(6000)
        return _flags

    def countDown(self, counter=5):

        __bar = 0
        __percent = 0
        __counter = counter
        __idleTime = xbmc.getGlobalIdleTime()

        # deactivate screensaver (send key select)

        if xbmc.getCondVisibility('System.ScreenSaverActive'):
            query = {
                "method": "Input.Select"
            }
            jsonrpc(query)

        if xbmc.getCondVisibility('VideoPlayer.isFullscreen'):
            writeLog(self.rndProcNum, 'Countdown possibly invisible (fullscreen mode)')
            writeLog(self.rndProcNum, 'Showing additional notification')
            notify(LS(30010), LS(30011) % (__counter))

        # show countdown, init KeyMonitor

        keymon = KeyMonitor(self.rndProcNum)
        writeLog(self.rndProcNum, 'Display countdown dialog for %s secs' % __counter)
        pb = xbmcgui.DialogProgressBG()
        pb.create(LS(30010), LS(30011) % __counter)
        pb.update(__percent)

        # actualize progressbar

        while __bar <= __counter:
            __percent = int(__bar * 100 / __counter)
            pb.update(__percent, LS(30010), LS(30011) % (__counter - __bar))

            # if __idleTime > xbmc.getGlobalIdleTime():
            if keymon.abort:
                writeLog(self.rndProcNum, 'Countdown aborted by user', level=xbmc.LOGNOTICE)
                keymon.close()
                pb.close()
                return True

            xbmc.sleep(1000)
            __idleTime += 1
            __bar +=1
        keymon.close()
        pb.close()
        return False

    def setWakeup(self):

        if xbmc.getCondVisibility('Player.Playing'):
            writeLog(self.rndProcNum, 'Stopping Player')
            xbmc.Player().stop()

        _flags = self.calcNextSched()

        # consider wakeup margin
        if self.wakeUTC is not None:
            self.wakeUTC -= datetime.timedelta(seconds=getAddonSetting('margin_start', sType=NUM))
            _utc = int(time.mktime(self.utc_to_local_datetime(self.wakeUTC).timetuple()))
        else:
            _utc = 0

        writeLog(self.rndProcNum, 'Instruct the system to shut down using %s: %s' %
                 (SHUTDOWN_METHOD[getAddonSetting('shutdown_method', sType=NUM)],
                  SHUTDOWN_MODE[getAddonSetting('shutdown_mode', sType=NUM)]), xbmc.LOGNOTICE)
        writeLog(self.rndProcNum, 'Wake-Up Unix timestamp: %s' % (_utc), xbmc.LOGNOTICE)
        writeLog(self.rndProcNum, 'Flags on resume points will be later {0:05b}'.format(_flags))

        if osv['platform'] == 'Linux':
            sudo = 'sudo ' if getAddonSetting('sudo', sType=BOOL) else ''
            os.system('%s%s %s %s %s' % (sudo, SHUTDOWN_CMD, _utc,
                                         getAddonSetting('shutdown_method', sType=NUM),
                                         getAddonSetting('shutdown_mode', sType=NUM)))
        if getAddonSetting('shutdown_method', sType=NUM) == 0 or osv['platform'] == 'Windows': xbmc.shutdown()
        xbmc.sleep(1000)

        # If we suspend instead of poweroff the system, we need the flags to control the main loop of the service.
        # On suspend we have to resume the service on resume points instead of start on poweron/login.
        # additional we set the resume flag in calcNextSched if necessary

        return _flags

    ####################################### START MAIN SERVICE #####################################

    def start(self, mode=None):

        writeLog(self.rndProcNum, 'Starting service with id:%s@mode:%s' % (self.rndProcNum, mode))
        _flags = self.getSysState()

        if mode is None:

            if not (_flags & (isREC | isEPG)):
                writeLog(self.rndProcNum, 'Service finished', level=xbmc.LOGNOTICE)
                return

        elif mode == 'CHECKMAILSETTINGS':
            if deliverMail(osv['hostname'], LS(30065) % (osv['hostname'])):
                dialogOK(LS(30066), LS(30068) % (getAddonSetting('smtp_to')))
            else:
                dialogOK(LS(30067), LS(30069) % (getAddonSetting('smtp_to')))
            return

        elif mode == 'POWEROFF':
            writeLog(self.rndProcNum, 'Poweroff command received', level=xbmc.LOGNOTICE)

            if (_flags & isREC):
                notify(LS(30015), LS(30020), icon=xbmcgui.NOTIFICATION_WARNING)  # Notify 'Recording in progress'
            elif (_flags & isEPG):
                notify(LS(30015), LS(30021), icon=xbmcgui.NOTIFICATION_WARNING)  # Notify 'EPG-Update'
            elif (_flags & isPRG):
                notify(LS(30015), LS(30022), icon=xbmcgui.NOTIFICATION_WARNING)  # Notify 'Postprocessing'
            elif (_flags & isNET):
                notify(LS(30015), LS(30023), icon=xbmcgui.NOTIFICATION_WARNING)  # Notify 'Network active'
            else:
                if self.countDown(): return
                _flags = self.setWakeup()
        else:
            writeLog(self.rndProcNum, 'unknown parameter %s' % (mode), xbmc.LOGFATAL)
            return

        # RESUME POINT #1

        if (_flags & isRES) and mode == 'POWEROFF':
            writeLog(self.rndProcNum, 'Resume point #1 passed', xbmc.LOGNOTICE)
            _flags = self.getSysState() & (isREC | isEPG | isPRG | isNET)
            if not _flags: return
            # mode = None

        if (_flags & isEPG) and getAddonSetting('epg_grab_ext', sType=BOOL) and \
                os.path.isfile(EXTGRABBER) and osv['platform'] == 'Linux':
            writeLog(self.rndProcNum, 'Starting script for grabbing external EPG')
            #
            # ToDo: implement startup of external script (epg grabbing)
            #
            _epgpath = xbmc.translatePath(os.path.join(getAddonSetting('epg_path'), 'epg.xml'))
            if getAddonSetting('store_epg', sType=BOOL) and _epgpath == '': _epgpath = '/dev/null'
            _start = datetime.datetime.now()
            try:
                _comm = subprocess.Popen('%s %s %s' % (EXTGRABBER, _epgpath,
                                                       xbmc.translatePath(getAddonSetting('epg_socket_path'))),
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         shell=True, universal_newlines=True)
                while _comm.poll() is None:
                    writeLog(self.rndProcNum, _comm.stdout.readline().decode('utf-8', 'ignore').strip())

                writeLog(self.rndProcNum, 'external EPG grabber script tooks %s seconds' %
                         ((datetime.datetime.now() - _start).seconds))
            except Exception:
                writeLog(self.rndProcNum, 'Could not start external EPG grabber script', xbmc.LOGERROR)

        tmpTimer = {}
        pvrTimer = []
        idle = xbmc.getGlobalIdleTime()
        mon = xbmc.Monitor()

        ### START MAIN LOOP ###

        while _flags:

            _flags = self.getSysState() & (isREC | isEPG | isPRG | isNET)

            outer_loop = 0
            _abort = False
            while outer_loop < CYCLE:
                if mon.waitForAbort(1):
                    writeLog(self.rndProcNum, 'Abort request received', level=xbmc.LOGNOTICE)
                    _abort = True
                    break
                if idle > xbmc.getGlobalIdleTime():
                    writeLog(self.rndProcNum, 'User activty detected (was %s idle)' %
                             (time.strftime('%H:%M:%S', time.gmtime(idle))))
                    _abort = True
                    break
                outer_loop += 1

            if _abort: break
            idle = xbmc.getGlobalIdleTime()

            # check outdated recordings

            curTimer = []
            query = {'method': 'PVR.GetTimers',
                     'params': {'properties': ['title', 'state']}}
            response = jsonrpc(query)

            if response.get('timers', False):
                for item in response.get('timers', {}):
                    if item['state'] == 'recording':
                        tmpTimer.update({item['timerid']: {'title': item['title']}})
                        curTimer.append(item['timerid'])

            for item in curTimer:
                if not item in pvrTimer:
                    pvrTimer.append(item)
                    writeLog(self.rndProcNum, 'Timer #%s of "%s" is recording' % (item, tmpTimer[item]['title']))

            for item in pvrTimer:
                if not item in curTimer:
                    pvrTimer.remove(item)
                    writeLog(self.rndProcNum, 'Timer #%s has finished recording of "%s"' % (item, tmpTimer[item]['title']))
                    if mode is None:
                        deliverMail(osv['hostname'], LS(30047) % (osv['hostname'], tmpTimer[item]['title']))

            if not _flags:
                if mode == 'POWEROFF':
                    if self.countDown(counter=getAddonSetting('notification_counter', sType=NUM)): break
                    _flags = self.setWakeup()
                else:
                    writeLog(self.rndProcNum, 'Service was running w/o user activity', level=xbmc.LOGNOTICE)
                    _flags = self.setWakeup()

                # RESUME POINT #2

                writeLog(self.rndProcNum, 'Resume point #2 passed', xbmc.LOGNOTICE)
                mode = None
                idle = 0
                _flags = self.getSysState() & (isREC | isEPG | isPRG | isNET)

        ### END MAIN LOOP ###

        ##################################### END OF MAIN SERVICE #####################################

# mode translations

if __name__ == '__main__':
    mode = None
    try:
        mode = sys.argv[1].upper()
    except IndexError:
        # Start without arguments (i.e. login|startup|restart)
        pass

    TVHMan = Manager()
    TVHMan.start(mode)
    writeLog(None, 'Service with id %s on %s kicks off' % (TVHMan.rndProcNum, osv['hostname']), level=xbmc.LOGNOTICE)
    del TVHMan
