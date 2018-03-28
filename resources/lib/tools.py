
import datetime
import time
import json
import platform
import subprocess
import os
import re

import xbmc
import xbmcgui
import xbmcaddon

import smtplib
from email.message import Message
from dateutil import parser


ADDON_NAME = xbmcaddon.Addon().getAddonInfo('name')
PATH = xbmcaddon.Addon().getAddonInfo('path')
PROFILE = xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
LS = xbmcaddon.Addon().getLocalizedString

# Constants

STRING = 0
BOOL = 1
NUM = 2

def writeLog(proc, message, level=xbmc.LOGDEBUG):
    if proc is not None:
        proc ='@%s' % (proc)
    else:
        proc = ''
    xbmc.log('[%s %s%s] %s' % (xbmcaddon.Addon().getAddonInfo('id'),
                             xbmcaddon.Addon().getAddonInfo('version'),
                             proc,
                             message.encode('utf-8')), level)


def notify(header, message, icon=xbmcgui.NOTIFICATION_INFO, dispTime=5000):
    xbmcgui.Dialog().notification(header.encode('utf-8'), message.encode('utf-8'), icon=icon, time=dispTime)


def release():
    item = {}
    coll = {'platform': platform.system(), 'hostname': platform.node()}
    if coll['platform'] == 'Linux':
        with open('/etc/os-release', 'r') as _file:
            for _line in _file:
                if '=' in _line:
                    parameter, value = _line.split('=')
                    item[parameter] = value.replace('"', '').strip()

    coll.update({'osname': item.get('NAME', ''), 'osid': item.get('ID', ''), 'osversion': item.get('VERSION_ID', '')})
    return coll


def getProcessPID(process):
    if not process: return False
    OS = release()
    if OS['platform'] == 'Linux':
        _syscmd = subprocess.Popen(['pidof', process], stdout=subprocess.PIPE)
        PID = _syscmd.stdout.read().strip()
        return PID if PID > 0 else False
    elif OS['platform'] == 'Windows':
        _tlcall = 'TASKLIST', '/FI', 'imagename eq %s' % os.path.basename(process)
        _syscmd = subprocess.Popen(_tlcall, shell=True, stdout=subprocess.PIPE)
        PID = _syscmd.communicate()[0].strip().split('\r\n')
        if len(PID) > 1 and os.path.basename(process) in PID[-1]:
            return PID[-1].split()[1]
        else: return False
    else:
        writeLog(None, 'Running on %s, could not determine PID of %s' % (OS, process))
        return False


def dialogOK(header, message):
    xbmcgui.Dialog().ok(header.encode('utf-8'), message.encode('utf-8'))

def jsonrpc(query):
    querystring = {"jsonrpc": "2.0", "id": 1}
    querystring.update(query)
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(querystring, encoding='utf-8')))
        if 'result' in response: return response['result']
    except TypeError, e:
        writeLog(None, 'Error executing JSON RPC: %s' % (e.message), xbmc.LOGFATAL)
    return None


def getAddonSetting(setting, sType=STRING, multiplicator=1):
    if sType == BOOL:
        return  True if xbmcaddon.Addon().getSetting(setting).upper() == 'TRUE' else False
    elif sType == NUM:
        try:
            return int(re.match('\d+', xbmcaddon.Addon().getSetting(setting)).group()) * multiplicator
        except AttributeError:
            return 0
    else:
        return xbmcaddon.Addon().getSetting(setting)

        # send email to user to inform about a successful completition

def deliverMail(hostname, message):
    if getAddonSetting('smtp_sendmail', sType=BOOL):
        try:
            __port = {'None': 25, 'SSL/TLS': 465, 'STARTTLS': 587}
            __s_msg = Message()
            __s_msg.set_charset(getAddonSetting('charset'))
            __s_msg.set_payload(message, charset=getAddonSetting('charset'))
            __s_msg["Subject"] = LS(30046) % (hostname)
            __s_msg["From"] = getAddonSetting('smtp_from')
            __s_msg["To"] = getAddonSetting('smtp_to')

            if getAddonSetting('smtp_encryption') == 'STARTTLS':
                __s_conn = smtplib.SMTP(getAddonSetting('smtp_server'), __port[getAddonSetting('smtp_encryption')])
                __s_conn.ehlo()
                __s_conn.starttls()
            elif getAddonSetting('smtp_encryption') == 'SSL/TLS':
                __s_conn = smtplib.SMTP_SSL(getAddonSetting('smtp_server'), __port[getAddonSetting('smtp_encryption')])
                __s_conn.ehlo()
            else:
                __s_conn = smtplib.SMTP(getAddonSetting('smtp_server'), __port[getAddonSetting('smtp_encryption')])
            __s_conn.login(getAddonSetting('smtp_user'), getAddonSetting('smtp_passwd'))
            __s_conn.sendmail(getAddonSetting('smtp_from'), getAddonSetting('smtp_to'), __s_msg.as_string())
            __s_conn.close()
            writeLog(None, 'Mail delivered to %s.' % (getAddonSetting('smtp_to')), level=xbmc.LOGNOTICE)
            return True
        except Exception, e:
            writeLog(None, 'Mail could not be delivered. Check your settings.', xbmc.LOGERROR)
            writeLog(None, e.message)
            return False
    return True

def strpTimeBug(datestring, formatstring):
    try:
        return datetime.datetime.strptime(datestring, formatstring)
    except TypeError:
        return datetime.datetime(*(time.strptime(datestring, formatstring)[0:6]))
    except ImportError:
        return parser.parse(datestring)
