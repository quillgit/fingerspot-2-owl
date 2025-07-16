import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import sys
import os
import subprocess
from app import app

class FlaskService(win32serviceutil.ServiceFramework):
    _svc_name_ = "FP2PivotAppService"
    _svc_display_name_ = "FP2 Pivot App Service"
    _svc_description_ = "Flask service for FP2 Pivot App"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)
        self.is_alive = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        self.is_alive = False

    def SvcDoRun(self):
        try:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, '')
            )
            app.run(host='localhost', port=5000)
        except Exception as e:
            servicemanager.LogErrorMsg(str(e))
            self.SvcStop()

def ensure_service_running():
    try:
        # Check if service is installed
        win32serviceutil.QueryServiceStatus('FP2PivotAppService')
    except:
        # Install and start service if not installed
        subprocess.run(['python', 'service.py', 'install'], shell=True)
        subprocess.run(['net', 'start', 'FP2PivotAppService'], shell=True)

if __name__ == '__main__':
    if len(sys.argv) == 1:
        ensure_service_running()
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(FlaskService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(FlaskService)