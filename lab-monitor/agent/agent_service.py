"""
Lab Monitor Agent — Windows Service Wrapper
==========================================
Installs the agent as a Windows Service so it starts automatically
on boot, runs silently in the background, and restarts on failure.

USAGE (run as Administrator):
  Install:   python agent_service.py install
  Start:     python agent_service.py start
  Stop:      python agent_service.py stop
  Remove:    python agent_service.py remove
  Debug:     python agent_service.py debug   (runs in console for testing)

Or just double-click: install_service.bat  (handles everything)
"""

import sys, os, time, threading
import servicemanager
import win32event
import win32service
import win32serviceutil

# Make sure imports resolve relative to this file's directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


class LabMonitorService(win32serviceutil.ServiceFramework):
    _svc_name_         = "LabMonitorAgent"
    _svc_display_name_ = "Lab Monitor Agent"
    _svc_description_  = "Monitors active applications and reports to the Lab Monitor server."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._running = False

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._running = False
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        self._running = True
        self._run_agent()

    def _run_agent(self):
        """Run the agent loop inside the service."""
        # Import agent internals
        try:
            import json, requests, re

            config_path = os.path.join(BASE_DIR, 'config.json')
            if not os.path.exists(config_path):
                servicemanager.LogErrorMsg("LabMonitorAgent: config.json not found. Service cannot start.")
                return

            with open(config_path) as f:
                cfg = json.load(f)

            server_url = cfg.get('server_url', '').strip()
            token      = cfg.get('machine_token', '').strip()
            headers    = {'Authorization': f'Bearer {token}'}
            interval   = 5

            def get_active_window():
                try:
                    import pygetwindow as gw
                    win = gw.getActiveWindow()
                    if not win or not win.title:
                        return 'Desktop', ''
                    title = win.title.strip()
                    app   = extract_app(title)
                    return app, title
                except Exception:
                    return 'Unknown', ''

            def extract_app(title):
                patterns = [
                    (r' - Google Chrome$',       'Google Chrome'),
                    (r' - Microsoft Edge$',       'Microsoft Edge'),
                    (r' - Mozilla Firefox$',      'Mozilla Firefox'),
                    (r' - Visual Studio Code$',   'Visual Studio Code'),
                    (r'Visual Studio Code$',      'Visual Studio Code'),
                    (r' - Notepad\+\+$',          'Notepad++'),
                    (r'Notepad$',                 'Notepad'),
                    (r'File Explorer$',           'File Explorer'),
                    (r'Discord$',                 'Discord'),
                    (r'Spotify$',                 'Spotify'),
                    (r'Command Prompt$',          'Command Prompt'),
                    (r'PowerShell$',              'PowerShell'),
                    (r'Task Manager$',            'Task Manager'),
                ]
                for pattern, name in patterns:
                    if re.search(pattern, title, re.IGNORECASE):
                        return name
                if ' - ' in title:
                    parts = title.split(' - ')
                    last = parts[-1].strip()
                    if len(last) <= 50:
                        return last
                return title[:40].strip() or 'Unknown'

            # Send offline on stop
            def send_offline():
                try:
                    requests.post(f'{server_url}/api/agent/offline',
                                  headers=headers, timeout=5)
                except Exception:
                    pass

            servicemanager.LogInfoMsg(f"LabMonitorAgent: connected to {server_url}")

            while self._running:
                try:
                    app_name, window_title = get_active_window()
                    requests.post(
                        f'{server_url}/api/agent/heartbeat',
                        json={'app_name': app_name, 'window_title': window_title},
                        headers=headers,
                        timeout=5
                    )
                except Exception:
                    pass  # silently retry next cycle

                # Wait for interval or stop signal
                win32event.WaitForSingleObject(self.stop_event, interval * 1000)

            send_offline()

        except Exception as e:
            servicemanager.LogErrorMsg(f"LabMonitorAgent error: {e}")


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # Called by SCM
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(LabMonitorService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(LabMonitorService)
