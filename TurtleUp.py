#!/usr/bin/python

VERSION = '0.9'
applist_url = 'http://tracker/games.ini'

import os
import sys
import wx
import urllib
import getopt
from ConfigParser import SafeConfigParser
import platform
import libtorrent
import time
from threading import Thread


ISWIN = platform.system() == 'Windows'
if ISWIN:
    import _winreg


state_str = ['queued', 'checking', 'downloading metastatus', 'downloading',
             'finished', 'finished/seeding', 'allocating', 'checking fastresume']


EVT_PROGRESS_ID = wx.NewId()


class UpdateProgressEvent(wx.PyEvent):
    
    def __init__(self, data):
        wx.PyEvent.__init__(self)
        self.SetEventType(EVT_PROGRESS_ID)
        self.data = data


class UpdateProgress(Thread):

    def __init__(self, wxo, dl, app):
        Thread.__init__(self)
        self.wxo = wxo
        self.dl = dl
        self.app = app
        self.running = False
        self.start()
    
    def run(self):
        self.running = True
        #while not self.dl.is_seed() and self.running:
        while self.running:
            wx.PostEvent(self.wxo, UpdateProgressEvent((self.app, self.dl.status())))
            time.sleep(1)
        self.running = False

    def stop(self):
        self.running = False


class TurtleUp(wx.Frame):
 
    def __init__(self, parent, title, url):
        super(TurtleUp, self).__init__(parent, title=title, style=wx.DEFAULT_FRAME_STYLE ^ wx.RESIZE_BORDER)
        
        try:
            self.apps = AppDB(url)
        except Exception:
            text = 'Failed to download App informations.'
            dlg = wx.MessageDialog(self, text, 'Damn!', wx.OK|wx.ICON_ERROR)
            dlg.ShowModal()
            dlg.Destroy()
            sys.exit(1)

        self.InitUI()
        self.InitBT()
        self.Centre()
        self.Show()
        
    def InitUI(self):
        panel = wx.Panel(self)
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        appListSizer = wx.BoxSizer(wx.VERTICAL)
        
        boldFont = wx.SystemSettings_GetFont(wx.SYS_SYSTEM_FONT)
        boldFont.SetWeight(wx.BOLD)

        for app in self.apps.getAll():
            appBox = wx.StaticBox(panel, label=app['name'])
            appBox.SetFont(boldFont)
            appSizer = wx.StaticBoxSizer(appBox, wx.VERTICAL)
            tmpSizer = wx.BoxSizer(wx.HORIZONTAL)
            app['stat'] = wx.StaticText(panel, label=' ')
            app['gauge'] = wx.Gauge(panel, size=(250, 25))
            app['button'] = wx.Button(panel, app['id'], label='Start', size=(-1, 25))
            tmpSizer.Add(app['gauge'], -1, wx.RIGHT, 3)
            tmpSizer.Add(app['button'])
            appSizer.Add(tmpSizer)
            appSizer.Add(app['stat'])
            appListSizer.Add(appSizer, -1, wx.ALL ^ wx.BOTTOM, 3)
            self.Bind(wx.EVT_BUTTON, self.OnStartStopButton, id=app['id'])
            
            # diable uninstallable apps
            if not self.IsInstallable(app):
                app['button'].Enable(False)
                app['stat'].SetLabel(app['destreqtext'])
                app['stat'].SetForegroundColour(wx.RED)
            
        mainSizer.Add(appListSizer)
        mainSizer.AddSpacer(3)
        mainSizer.Add(wx.Button(panel, 999, label='Exit'), 0, wx.ALIGN_RIGHT | wx.ALL, 3)
        
        panel.SetSizerAndFit(mainSizer)
        rootSizer = wx.BoxSizer(wx.VERTICAL)
        rootSizer.Add(panel, 1, wx.GROW)
        self.SetSizerAndFit(rootSizer)
        
        self.Bind(wx.EVT_BUTTON, self.OnExit, id=999)
        self.Bind(wx.EVT_CLOSE, self.OnExit)
        self.Connect(-1, -1, EVT_PROGRESS_ID, self.UpdateProgress)
        
    def OnExit(self, event):
        # TODO: stop torrents
        for app in self.apps.getAll():
            self.StopUpdate(app['id'])
        self.Destroy()
        sys.exit(0)
        
    def OnStartStopButton(self, event):
        button = event.GetEventObject()
        if button.GetLabel() == 'Start':
            try:
                if self.StartUpdate(button.GetId()):
                    button.SetLabel('Stop')
            except Exception:
                dlg = wx.MessageDialog(self, 'Something went wrong!', 'Shit!', wx.OK|wx.ICON_ERROR)
                dlg.ShowModal()
        else:
            self.StopUpdate(button.GetId())
            button.SetLabel('Start')
        
    def InitBT(self):
        self.lt = libtorrent.session()
        self.lt.listen_on(6881, 6891)

    def StartUpdate(self, aid):
        # TODO: use exceptions instead of return values
        app = self.apps.getFirst(id=aid)
        if app['dest'] == 'prompt':
            dlg = wx.DirDialog(self, "Choose installation directory")
            if dlg.ShowModal() == wx.ID_OK:
                app['dest'] = dlg.GetPath()
            else:
                return False
            dlg.Destroy()
        if app['striptopfolder']:
            app['dest'] = os.path.dirname(app['dest'])
	    tfp = urllib.urlopen(app['torrent'])
        tbdc = libtorrent.bdecode(tfp.read())
        tinfo = libtorrent.torrent_info(tbdc)
        app['download'] = self.lt.add_torrent(tinfo, app['dest'].encode('ASCII'))
        app['updater'] = UpdateProgress(self, app['download'], aid)
        return True
       
    def StopUpdate(self, aid):
        app = self.apps.getFirst(id=aid)
        if app.has_key('updater') and app['updater']:
            app['updater'].stop()
            app['updater'] = None
            app['stat'].SetLabel('stopped')
        if app.has_key('download'):
            # TODO: real check if torrent is active
            try:
                self.lt.remove_torrent(app['download'])
            except Exception:
                pass
        
    def UpdateProgress(self, event):
        aid, status = event.data
        app = self.apps.getFirst(id=aid)
        app['gauge'].SetValue(status.progress * 100)
        app['stat'].SetLabel('%s %d%% - down: %d kB/s up: %d kB/s peers: %d' %
            (state_str[status.state], status.progress * 100, status.download_rate / 1000, status.upload_rate / 1000, status.num_peers))
    
    def IsInstallable(self, app):
        if app['destreq'] and not os.path.exists(app['dest']):
            return False
        return True


class RATable():
    
    def __init__(self, data=[]):
        self.data = data
        
    def addApp(self, data):
        self.data.append(data)

    def getFirst(self, **kwargs):
        field = kwargs.keys()[0]
        for row in self.data:
            if row[field] == kwargs[field]:
                return row
    
    def getAll(self):
        return self.data
    
    def getAnd(self, **kwargs):
        result = []
        for row in self.data:
            flag = True
            for field in kwargs:
                if row[field] != kwargs[field]:
                    flag = False
                    break
            if flag:
                result.append(row)
        return result
                
    def getOr(self, **kwargs):
        result=[]
        for row in self.data:
            for field in kwargs:
                if row.has_key(field) and row[field] == kwargs[field]:
                    result.append(row)
                    break
        return result


class AppDB(RATable):
    
    def __init__(self, url=None):
        RATable.__init__(self)
        self.nextID = 0
        if url:
            self.readFromINI(url)
        
    def getID(self):
        nid = self.nextID
        self.nextID += 1
        return nid
        
    def readFromINI(self, url):
        cp = SafeConfigParser()
        fp = urllib.urlopen(url)
        cp.readfp(fp)
        for section in cp.sections():
            data = {'id': self.getID(),
                    'name': section,
                    'torrent': cp.get(section, 'torrent'),
                    'dest': self.evalDest(cp.get(section, 'dest')),
                    'destreq': cp.getboolean(section, 'destreq'),
                    'destreqtext': cp.get(section, 'destreqtext'),
                    'striptopfolder': cp.getboolean(section, 'striptopfolder')
                    }
            self.addApp(data)
            
    def evalDest(self, dest):
        if ISWIN:
            if dest[:3].lower() == 'reg':
                try:
                    rp = dest[4:].replace('/', '\\')
                    hkey, rp = rp.split('\\', 1)
                    rp, item = rp.rsplit('\\', 1)
                    r = _winreg.OpenKey(getattr(_winreg, hkey), rp)
                    dest = _winreg.QueryValueEx(r, item)[0]
                except WindowsError:
                    pass
        return dest


if __name__ == '__main__':
    app = wx.App()
    TurtleUp(None, 'TurtleUp %s' % VERSION, applist_url)
    app.MainLoop()
    
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4