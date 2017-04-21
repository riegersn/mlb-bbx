#
# Backend script for MLB on Boxee Box
# Written by Shawn Rieger
#
# Interacts with MLB's HTTP Live Streaming service and handles playback
# through the Boxee Box's media player.
# 

import mc
import tracker
import urllib
import random
import base64
import datetime as dt
import time
import simplejson as json
import re
import monthdelta as md
from xml.dom.minidom import parse, parseString
import jobmanager
import md5
import threading

'''
Base MLB class
(where the magic happens)
'''
class MLB(object):
    '''
    Default values
    '''
    def __init__(self):
        # Status variables
        self.status_error = -2
        self.status_valid = 1
        self.status_invalid = 0
        self.status_missing = -1
        self.send_to_server = True
        self.send_to_history = True

        # Data tables
        self.pitches = {'PO': ['Pitchout', 'Pitchout'], 'AB': ['Automatic Ball', 'Automatic Ball'], 'AS': ['Automatic Strike', 'Automatic Strike'], 'CH': ['Changeup', 'Changeup'], 'CU': ['Curveball', 'Curveball'], 'FA': ['Fastball', 'Fastball'], 'FT': ['Two-seam FB', 'Fastball (2-seam)'], 'FF': ['Four-seam FB', 'Fastball (4-seam)'], 'FC': ['Cutter', 'Fastball (Cut)'], 'FS': ['Splitter', 'Fastball (Split-finger)'], 'FO': ['Forkball', 'Forkball'], 'GY': ['Gyroball', 'Gyroball'], 'IN': ['Intentional Ball', 'Intentional Ball'], 'KC': ['Knuckle Curve', 'Knuckle Curve'], 'KN': ['Knuckleball', 'Knuckleball'], 'NP': ['No Pitch', 'No Pitch'], 'SC': ['Screwball', 'Screwball'], 'SI': ['Sinker', 'Sinker'], 'SL': ['Slider', 'Slider'], 'UN': ['Unknown', 'Unknown']}
        self.event_filter = ['Hit By Pitch', 'Double', 'Home Run', 'Single', 'Triple', 'Batter Interference', 'Catcher Interference', 'Error', 'Fan interference', 'Field Error', 'Fielder Interference', 'Runner Interference', 'Double Play', 'Grounded Into DP', 'Sac Bunt', 'Sac Fly', 'Sac Fly DP', 'Triple Play', 'Ejection', 'Player Injured', 'Pickoff 1B', 'Pickoff 2B ', 'Pickoff 3B', 'Pickoff Error 1B', 'Pickoff Error 2B', 'Pickoff Error 3B', 'Run', 'Balk', 'Caught Stealing 2B', 'Caught Stealing 3B', 'Caught Stealing Home', 'Caught Stealing DP', 'Passed Ball', 'Picked off stealing 2B', 'Picked off stealing 3B', 'Picked off stealing home', 'Stolen Base 2B', 'Stolen Base 3B', 'Stolen Base Home', 'Wild Pitch', 'Strikeout - DP', 'Strikeout - TP', 'Sacrifice Bunt DP', 'In play, run(s)']

        # URIs
        self.mr_url = "https://mlb-ws.mlb.com/pubajaxws/bamrest/MediaService2_0/op-findUserVerifiedEvent/v-2.3?%s"
        self.boxee_server = "http://dir.boxee.tv/apps"
        #self.boxee_server = "http://drgonzo.boxee.pvt"
        self.url_base = self.boxee_server + "/mlb/mlb.php?func=%s&%s"
        self.data_uri = "http://gdx.mlb.com/components/game/mlb"
        self.realtime_uri = "http://lwsa.mlb.com/tfs/tfs?file=components/game/mlb"
        self.message_uri = "http://dir.boxee.tv/apps/mlb/messages.xml"
        self.time_uri = "http://dir.boxee.tv/apps/mlb/mlbTime.php"

        # Objects
        self.myTracker = tracker.Tracker()

        # Check for Fiona
        try:
            self.device_id = mc.GetDeviceId()
        except:
            self.device_id = None

        self.config = {}


    '''
    Utility methods
    '''
    def request(self, data):
        try:
            self.info('request', 'processing post request to boxee.tv')
            if not data or str(type(data)) != "<type 'dict'>":
                return self.raiseError(log='request',error='data passed is not usable. contact support@boxee.tv')

            try:
                params = urllib.urlencode(data)
            except:
                return self.raiseError(log='request',error='data passed is not usable. contact support@boxee.tv')

            http = mc.Http()
            result = http.Post('http://dir.boxee.tv/apps/mlb/mlb.php', params)
            code = http.GetHttpResponseCode()
            http.Reset()

            if code != 200:
                self.debug('request', 'post returned response code '+str(code))
            if not result:
                self.debug('request', 'post return zero bytes')
            if code == 200 and result:
                self.info('request', 'post was successful')

            response = {'data': result, 'code': code}
            return response
        except Exception, e:
            return self.raiseError(log='request',error=e)

    def callService(self, func, values={}, authenticated=True, content=False):
        try:
            self.info('callservice', 'calling the boxee_mlb service w/%s, authentication/%s' % (func,str(authenticated).lower()))
            params = {}
            http_service = mc.Http()

            if authenticated:
                app = mc.GetApp()
                cf = app.GetLocalConfig()
                params['nsfp'] = cf.GetValue('fprt')
                params['nsid'] = cf.GetValue('ipid')

            if values:
                for i in values: params[i] = values[i]

            url_base = self.underscore(self.url_base % (func, urllib.urlencode(params)))
            query_result = http_service.Get(url_base)

            if content == 'json':
                query_result = re.sub('//.*?\n|/\*.*?\*/', '', query_result, re.S)
                query_result = json.loads(query_result)

            return query_result
        except Exception, e:
            return self.raiseError(log='callservice', error=e)

    def underscore(self, string):
        return string.replace('_', '%5F')

    def ordinal(self, n):
        if 10 < n < 14: return u'%sth' % n
        if n % 10 == 1: return u'%sst' % n
        if n % 10 == 2: return u'%snd' % n
        if n % 10 == 3: return u'%srd' % n
        return '%sth' % n

    def gameIdToEventURI(self, game_id, realtime=False):
        game_id = game_id.replace("-", "_")
        underscored = game_id.replace("/", "_")
        split = game_id.split("/")
        if realtime:
            return self.realtime_uri + "/year_%s/month_%s/day_%s/gid_%s/" % (split[0], split[1], split[2], underscored)
        return self.data_uri + "/year_%s/month_%s/day_%s/gid_%s/" % (split[0], split[1], split[2], underscored)

    def info(self, func, msg):
        mc.LogInfo('@mlb.tv ('+func+') '+str(msg))

    def debug(self, func, msg):
        mc.LogDebug('@mlb.tv ('+func+') '+str(msg))

    def error(self, func, msg):
        mc.LogError('@mlb.tv ('+func+') '+str(msg))

    def raiseError(self, message=False, log=False, error=False):
        mc.HideDialogWait()
        if log and error:
            mc.LogError('@mlb.tv ('+log+') '+str(error))

        if message:
            response = message
        else:
            response = "An error has occurred. Details have been saved in your log. Please notify Boxee support."

        mc.ShowDialogOk("MLB.TV", response)
        return False

    def getJson(self, url=False, data=False):
        try:
            if url: data = mc.Http().Get(url)
            data = re.sub('//.*?\n|/\*.*?\*/', '', data, re.S)
            data = json.loads(data)
            return data
        except Exception, e:
            return self.raiseError(log='getjson',error=e)

    def digitsToTimecode(self, digits):
        return digits[0:2] + ":" + digits[2:4] + ":" + digits[4:6]

    def getCurrentMLBTime(self):
        self.debug('time', "Getting MLB time...")
        xml = mc.Http().Get(self.time_uri)
        if xml:
            dom = parseString(xml)
            if dom.getElementsByTagName('time'):
                value = dom.getElementsByTagName('time')[0].firstChild.data
                return time.strptime(value, "%d %b %Y %H:%M:%S")
        else:
            self.debug('time', "Could not retrieve MLB time.")
            return False


    '''
    Authentication
    '''
    def authenticate(self):
        try:
            content = mc.Http().Get('http://app.boxee.tv/api/get_application_data?id=mlb')
            if not content:
                return self.status_error
            else:
                auth_dom = parseString(content)
                email = auth_dom.getElementsByTagName('email')[0].firstChild.data
                account = auth_dom.getElementsByTagName('rand_account')[0].firstChild.data
                post_data = self.request({'func': '_login', 'email': email, 'pass': account})

                if not post_data or post_data['data'] == '0':
                    Exception('post request return false')


                cf = mc.GetApp().GetLocalConfig()
                response = self.getJson(data=post_data['data'])
                response = response.get('identity')
                code = str(response.get('code'))
                if code != '1':
                    self.info('authenticate.code', code)
                    cf.Reset("fprt")
                    cf.Reset("ipid")
                    cf.Reset("username")
                    cf.Reset("password")
                    self.info('login', 'stored/entered credentials invalid')
                    return self.status_invalid
                else:
                    creds = response.get('credentials')
                    self.info('authenticate.email', str(email))
                    self.info('authenticate.ipid', str(creds.get('id')))
                    self.info('authenticate.fprt', str(creds.get('fingerprint')))
                    cf.SetValue("username", str(email))
                    cf.SetValue("ipid", str(creds.get('id')))
                    cf.SetValue("fprt", str(creds.get('fingerprint')))
                    self.info('login', 'login was successfull')
                    self.updateArchiveSpoiler()

                    try:
                        platform = mc.GetPlatform()
                    except:
                        platform = 'PC'

                    try:
                        service_check = "http://lwsa.mlb.com/partner-config/config?company=Boxee&type=tv&productYear=2011&model=%s&firmware=1.5&app_version=2.43&identityPointId=%s&a=%d"
                        service_check = service_check % (platform, str(creds.get('id')), random.random())
                        self.info('login.service_check', service_check)

                        content = mc.Http().Get(service_check)
                        matches = re.findall('^(.*?)=(.*?)$', content, re.M)

                        for m in matches:
                            self.config[m[0]] = m[1]

                        if 'launch.alert' in self.config and 'launch.alert.duration' in self.config:
                            if int(self.config['launch.alert.duration']) > 0:
                                mc.ShowDialogOk('MLB.tv', self.config['launch.alert'])

                        self.data_uri = self.config['gameday_root']

                    except:
                        self.info('login.service_check', 'error building service check url')

                    return self.status_valid

                mc.HideDialogWait()
        except Exception, e:
            self.updateArchiveSpoiler()
            return self.status_invalid

    def isLoggedIn(self):
        cf = mc.GetApp().GetLocalConfig()
        if cf.GetValue('fprt') and cf.GetValue('ipid'): return True
        else: return False

    def getCredentials(self):
        try:
            cf = mc.GetApp().GetLocalConfig()
            if cf.GetValue('username') and cf.GetValue('password'):
                return {'user': cf.GetValue('username'), 'pass': cf.GetValue('password')}
            else: return False
        except Exception, e:
            return self.raiseError(log='getCredentials', error=e)


    '''
    Feature game
    '''
    def launchWithItem(self, args):
        try:
            item = mc.ListItem(mc.ListItem.MEDIA_VIDEO_OTHER)
            item.SetLabel(args['title'][0])
            item.SetDescription(args['description'][0])
            item.SetThumbnail(args['thumbnail'][0])
            item.SetProperty('alt-label', args['alt-label'][0])
            item.SetProperty('event-id', args['event-id'][0])
            item.SetProperty('content-id', args['content-id'][0])
            item.SetProperty('bx-ourl', args['bx-ourl'][0])
            item.SetProperty('audio-stream', args['audio-stream'][0])
            item.SetProperty('media-state', args['media-state'][0])
            self.playItem(mlbList=0,playFromListItem=item)
        except Exception, e:
            return self.raiseError('Unable to play requested stream. If this continues please contact support@boxee.tv', 'launchWithItem', e)


    '''
    App startup
    '''
    def init(self, args=False):
        try:
            self.info('init', 'mlb launched, checking authentication')
            auth = self.authenticate()
            #mc.ShowDialogOk('er', str(auth))
            if auth == self.status_valid:
                self.authenticated = True
                if args: self.launchWithItem(args)
                else: mc.ActivateWindow(14000)
            elif auth == self.status_missing or auth == self.status_invalid:
                self.authenticated = False
                mc.ShowDialogOk('MLB.TV', 'Got MLB.tv? Go to boxee.tv/services to link your account. [CR]No MLB.tv? Sign up at mlb.com/boxee and get a free game every day!')
            else:
                mc.ShowDialogOk('MLB.TV', 'An error occurred while trying to validate your account, if you continue to receive this message contact support@boxee.tv')
                return False
            return False
        except Exception, e:
            return self.raiseError(False, True)

    def populateTodayScreen(self):
        try:
            w = mc.GetWindow(14000)
            w.GetList(120).SetFocusedItem(0)
            w.GetControl(120).SetFocus()
            w.GetList(120).SetFocusedItem(0)
            dt = self.getMonth(0)
            w.GetLabel(101).SetLabel(dt.strftime("%B %d, %Y"))
            games = self.getGames()
            if games: w.GetList(120).SetItems(games)
        except Exception, e:
            if 'AppException' in str(e):
                self.info('populateTodayScreen', e)
                return False
            else:
                return self.raiseError(log='populateTodayScreen', error=e)

    def setUpCalendar(self):
        try:
            mc.GetWindow(14001).GetList(121).SetFocus()
            self.setMonth(0, False)
        except Exception, e:
            return self.raiseError(log='setUpCalendar', error=e)

    '''
    Standings
    '''
    def standings(self, league):
        try:
            mc.ShowDialogWait()

            if league == 'national': league = 0
            elif league == 'american': league = 1

            data = self.getJson('http://mlb.mlb.com/lookup/json/named.standings_all_league_repeater.bam?sit_code=%27h0%27&league_id=104&league_id=103&season=2010')
            data = data.get('standings_all_league_repeater').get('standings_all')[league]
            stand = data.get('queryResults').get('row')
            east = mc.ListItems()
            west = mc.ListItems()
            central = mc.ListItems()

            for team in stand:
                item = mc.ListItem(mc.ListItem.MEDIA_UNKNOWN)
                item.SetLabel(str(team.get('team_short')))
                item.SetThumbnail('http://mlb.mlb.com/images/logos/200x200/200x200_%s.png' % (str(team.get('team_abbrev'))))
                item.SetProperty('games-back', str(team.get('gb')))
                item.SetProperty('wild-card', str(team.get('wild_card')))
                item.SetProperty('elim-wildcard', str(team.get('elim_wildcard')))
                details = 'Steak (' + team.get('streak') + '), Home (' + team.get('home') + '), Away (' + team.get('away') + '), Vs Division ('+team.get('vs_division')+'), Last Ten ('+team.get('last_ten')+')[CR]Winning Percentage ('+team.get('pct')+'%), Wildcard ('+team.get('wild_card')+'), Elimination Wildcard ('+team.get('elim_wildcard')+')'
                item.SetDescription(str(details))
                division = str(team.get('division'))

                if 'East' in division: east.append(item)
                elif 'West' in division: west.append(item)
                elif 'Central' in division: central.append(item)

            mc.GetActiveWindow().GetList(3002).SetItems(west)
            mc.GetActiveWindow().GetList(3003).SetItems(central)
            mc.GetActiveWindow().GetList(3004).SetItems(east)
            mc.HideDialogWait()
        except Exception, e:
            return self.raiseError(message='There was a problem accessing standings. Please try again later.',log='league',error=e)


    '''
    Calendar
    '''
    def getGames(self, year=False, month=False, day=False):
        try:
            mc.ShowDialogWait()
            if self.isLoggedIn():
                params = {}
                if year and month and day:
                    params['year'] = year
                    params['month'] = month
                    params['day'] = day

                #was having problems where the first request failed immediately after it was called (i have no idea)
                #in this instance if the request fails it will be immediately called once more (which has been working)
                #if it fails yet again the user will be presented with an error message.
                try: games = self.callService('today',params,content='json').get('games')
                except:
                    try: games = self.callService('today',params,content='json').get('games')
                    except: return self.raiseError('Unable to fetch games list. Please try again later.','getgames','unable to fetch game list.')

                list = mc.ListItems()
                for game in games:
                    item = mc.ListItem(mc.ListItem.MEDIA_VIDEO_OTHER)
                    item.SetLabel(str(game.get('title')))
                    item.SetThumbnail(str(game.get('thumbnail')))
                    item.SetDescription(str(game.get('description')))
                    custom = game.get('custom:items')
                    for value in custom: item.SetProperty(str(value), str(custom.get(str(value))))
                    images = game.get('image:items')
                    for key,value in enumerate(images): item.SetImage(key, str(value))
                    media_string = ''
                    audio_string = ''
                    media = game.get('media:items')
                    if bool(media.get('has_video')):
                        video = media.get('video')
                        for stream in video:
                            if media_string: media_string = media_string+"||"
                            media_string = media_string + str(stream.get('title'))+'|'+str(stream.get('contentid'))+'|'+str(stream.get('eventid'))
                    if media_string: item.SetProperty('media-string', media_string)
                    if bool(media.get('has_audio')):
                        audio = media.get('audio')
                        for stream in audio:
                            if audio_string: audio_string = audio_string+"||"
                            audio_string = audio_string + str(stream.get('title'))+'|'+str(stream.get('contentid'))+'|'+str(stream.get('eventid'))
                    if audio_string: item.SetProperty('audio-string', audio_string)
                    list.append(item)
                mc.HideDialogWait()
                return list
            mc.HideDialogWait()
        except Exception, e:
            return self.raiseError('Unable to fetch game list! Please wait and try again. If problem persists contact support@boxee.tv!','getgames',e)

    def getMonth(self, month=0, formatted=False):
        try:
            date = dt.date.today() + md.monthdelta(month)
            if not formatted: return date
            else: return date.strftime("%B %Y")
        except Exception, e:
            self.raiseError(log='getmonth',error=e)
            return dt.date.today()

    def setMonth(self, active, setList=True):
        setList = True
        try:
            window = mc.GetActiveWindow()
            cf = mc.GetApp().GetLocalConfig()
            cf.SetValue('calendar', str(active))
            if setList:
                month = self.getMonth(active,False)
                if not active == 0: url = month.strftime("rss://dir.boxee.tv/apps/mlb/feed/%Y/%m")
                else: url = "rss://dir.boxee.tv/apps/mlb/feed/calendar"
                mc.GetActiveWindow().GetList(121).SetContentURL(url)
            window.GetLabel(102).SetLabel('[UPPERCASE]'+self.getMonth(active,True)+'[/UPPERCASE]')
            window.GetLabel(103).SetLabel('[UPPERCASE]'+self.getMonth(active+1,True)+'[/UPPERCASE]')
            window.GetLabel(101).SetLabel('[UPPERCASE]'+self.getMonth(active-1,True)+'[/UPPERCASE]')
        except Exception, e:
            return self.raiseError(log='nextmonth',error=e)

    def nextMonth(self):
        try:
            cf = mc.GetApp().GetLocalConfig()
            if not cf.GetValue('calendar'): active = 0
            else: active = int(cf.GetValue('calendar'))
            self.setMonth(active+1)
        except Exception, e:
            return self.raiseError(log='nextmonth',error=e)

    def prevMonth(self):
        try:
            cf = mc.GetApp().GetLocalConfig()
            if not cf.GetValue('calendar'): active = 0
            else: active = int(cf.GetValue('calendar'))
            self.setMonth(active-1)
        except Exception, e:
            return self.raiseError(log='prevmonth',error=e)


    '''
    Playback
    '''
    def mediaServiceResponseCodes(self, id=-9999):
        if id == -1000: return 'The requested media is not currently available.'
        elif id == -2000: return 'invalid app account/partner'
        elif id == -2500: return 'system error determining blackouts'
        elif id == -3500: return 'too many active sessions/devices, this account is temporarily locked.'
        elif id == -4000: return 'general system error'
        elif id == -9999: return 'an unknown error'
        elif id != -3000: return 'an unknown error'
        elif id == -3000: return 'authentication key expired. please log in again to refresh.'

    def queryMediaService(self, media_request, isAudio=False):
        try:
            http = mc.Http()
            cf = mc.GetApp().GetLocalConfig()
            # It is required to ping the following url before hitting the mlb media_service
            rand_number = str(random.randint(10000,100000000))
            http.Get("http://mlbglobal08.112.2o7.net/b/ss/mlbglobal08/1/H.19--NS/"+rand_number+"?ch=Media&pageName=BOXEE%20Request&c1=BOXEE")
            http.Reset()
            # Query the mlb media_service to obtain stream information
            media_service = http.Get(media_request)

            # Parse the media service return
            try:
                media_service_dom = parseString(media_service)
            except Exception,e:
                self.raiseError(log='querymediaservice', error=e)
            status_code=''
            if media_service:
                if 'status-code' in media_service:
                    status_code = int(media_service_dom.getElementsByTagName('status-code')[0].firstChild.data)
                if 'notAuthorizedStatus' in media_service:
                    return {'playlist_url':-2,'media_state':''}
                #checking for valid return and grabbing all the parameters we need to make a successfull playback attempt
                if '<url>' in media_service and media_service_dom.getElementsByTagName('url')[0].firstChild:
                    base_encoded_string = media_service_dom.getElementsByTagName('url')[0].firstChild.data
                else:
                    status_reason = False
                    #request failed, user may be blacked out
                    if '<blackedOutStatus>' in media_service and '<blackout>' in media_service and '<blackout-status>' in media_service:
                        blackout_reason = media_service_dom.getElementsByTagName('blackout')[0].firstChild.data
                        self.info('querymediaservice', blackout_reason)
                        mc.ShowDialogOk('MLB.TV', 'You are currently blacked out from watching this broadcast. This stream will be made available to you approximately 90 minutes after the conclusion of the game.')
                        return {'playlist_url':-1,'media_state':''}
                    #user is not blacked out, checking status message from media_service
                    elif status_code == -3000:
                        return {'playlist_url':-3000,'media_state':''}
                    elif status_code != 1:
                        status_reason = self.mediaServiceResponseCodes(status_code)
                        self.raiseError('MLB.TV returned the following error: '+str(status_reason))
                        return {'playlist_url':False,'media_state':''}
                    elif status_code == 1:
                        self.raiseError('MLB returned a valid response however no media was present. If you are trying to play audio, this is only available for live games. Please contact support@boxee.tv')
                        return {'playlist_url':False,'media_state':''}
                    else:
                        #here we have no idea why this request failed. displaying generic error and falling back
                        self.raiseError(log='querymediaservice', error='unknown error calling media_service')
                        return {'playlist_url':False,'media_state':''}
                #grab the state from media_service repsonse
                media_state = ''
                if '<state>' in media_service:
                    media_state = media_service_dom.getElementsByTagName('state')[0].firstChild.data
                #grab the content_id from media_service repsonse
                content_id = ''
                if '<content-id>' in media_service:
                    content_id = media_service_dom.getElementsByTagName('content-id')[0].firstChild.data
                #grab the event_id from media_service repsonse
                event_id = ''
                if '<event-id>' in media_service:
                    event_id = media_service_dom.getElementsByTagName('event-id')[0].firstChild.data
                # grab the game_id from media service response
                if 'domain-attribute' in media_service:
                    domain_attributes = {}
                    for element in media_service_dom.getElementsByTagName("domain-attribute"):
                        domain_attributes[element.attributes["name"].value] = element.firstChild.data
                    game_id = domain_attributes['game_id']

                #grab innings-index url and pass as additional parameter via the returned playlist_url
                startDate = '0'
                innings_index = ''
                if 'innings-index' in media_service and media_service_dom.getElementsByTagName('innings-index')[0].firstChild:
                    innings_index = media_service_dom.getElementsByTagName('innings-index')[0].firstChild.data
                    self.info('innings_index', innings_index)
                    if innings_index.startswith('http'):
                        innings_xml = mc.Http().Get(str(innings_index))
                        if not innings_xml:
                            startDate = '0'
                        else:
                            innings_dom = parseString(innings_xml)
                            if 'start_timecode' in innings_xml:
                                startDate = innings_dom.getElementsByTagName('game')[0].attributes["start_timecode"].value
                    else:
                        startDate = '0'
                #check for updated session-key and replace new value with users active session-key in config
                if '<session-key>' in media_service:
                    old_session = cf.GetValue('sessionid')
                    for element in media_service_dom.getElementsByTagName("session-key"):
                        session_key = element.firstChild.data
                    cf.SetValue('sessionid', str(session_key))
                if not isAudio and not base_encoded_string.startswith('http://') and not base_encoded_string.startswith('rtmp://'):
                    #decode base64 string from mlb media_service request
                    request_params = base64.b64decode(base_encoded_string).split('|')
                    stream_url,stream_fingerprint,stream_params = request_params

                    rand_number = str(random.randint(10000,100000000))
                    bx_ourl = 'http://mlb.mlb.com/media/player/entry.jsp?calendar_event_id=%s&source=boxeeRef' % (event_id)
                    tracking_url = "http://mlbglobal08.112.2o7.net/b/ss/mlbglobal08/1/G.5--NS/"+rand_number+"?ch=Media&pageName=BOXEE%20Media%20Return&c25="+content_id+"%7CHTTP%5FCLOUD%5FWIRED&c27=Media%20Player&c43=BOXEE"
                    params = {
                        'stream-fingerprint':   stream_fingerprint,
                        'tracking-url':         tracking_url,
                        'startDate':            startDate,
                        'stream-params':        stream_params,
                        }
                    playlist_url = "playlist://%s?%s" % (urllib.quote_plus(stream_url), urllib.urlencode(params))
                else:
                    #either audio stream was requested or the url is not base64 encoded. returning url
                    playlist_url = base_encoded_string.replace('&amp;', '&')
                data = {
                    'playlist_url': playlist_url,
                    'media_state':  media_state,
                    'game_id': str(game_id),
                    'innings_index': str(innings_index)
                    }
                return data
            else:
               self.raiseError(log='querymediaservice', error="Could not get game information from MLB.tv.  Please try again later.")
        except Exception, e:
            self.raiseError(log='querymediaservice', error=e)
            self.log.exception('Error from querymedia service:')
            return {'playlist_url':False,'media_state':''}

    def parseAudioStreams(self, item):
        try:
            play_audio = False
            audio_string = item.GetProperty('audio-string')
            audio_items = audio_string.split('||')
            if len(audio_items) == 0:
                return self.raiseError('Unable to located proper audio items. This may be an error, please contact support@boxee.tv. We apologize for the inconvenience.', 'playitem', 'problem locating audio streams, audio-string property is empty or malformed')
            elif len(audio_items) == 1:
                stream_1 = audio_items[0]
                stream_1 = stream_1.split('|')
                play_audio = stream_1
            elif len(audio_items) > 1:
                stream_1 = audio_items[0]
                stream_2 = audio_items[1]
                stream_1 = stream_1.split('|')
                stream_2 = stream_2.split('|')
                confirm = mc.ShowDialogConfirm('MLB.TV', 'Please select the audio stream you wish to listen to...', stream_1[0], stream_2[0])
                if not confirm: play_audio = stream_1
                else: play_audio = stream_2
            if not play_audio:
                self.raiseError()
                return False
            return play_audio
        except Exception, e:
            return self.raiseError(log='parseaudiostreams', error=e)

    def promptQuality(self):
        try:
            cf = mc.GetApp().GetLocalConfig()
            q_ask = bool(cf.GetValue('ask_quality'))
            q_high = bool(cf.GetValue('high_quality'))
            q_default = bool(cf.GetValue('default_quality'))
            q_adaptive = bool(cf.GetValue('adaptive_quality'))
            if not q_ask and not q_high and not q_default and not q_adaptive:
                q_ask = True
                cf.SetValue('ask_quality', '1')
            if q_ask:
                q_message = 'Please select your video quality (manage this and other options in the Settings tab):'
                quality = mc.ShowDialogConfirm('MLB.TV', q_message, 'Normal', 'High')
                quality = int(quality)
            elif q_high: quality = 1
            elif q_adaptive: quality = "A"
            else: quality = 0
            return str(quality)
        except Exception, e:
            return raiseError(log='promptquality', error=e)

    def playItem(self, mlbList, forceAudioCheck=False, playFromListItem=False):
        try:
            mc.ShowDialogWait()
            play_audio = False
            if not playFromListItem:
                window = mc.GetActiveWindow()
                list = window.GetList(mlbList)
                index = list.GetFocusedItem()
                item = list.GetItem(index)
            else:
                item = playFromListItem
            session_id = 'null'
            cf = mc.GetApp().GetLocalConfig()
            if cf.GetValue('sessionid'): session_id = cf.GetValue('sessionid')
            if not self.isLoggedIn(): return self.raiseError('You must first log in before you can watch this game.')

            ###### DEBUG & TESTING ######
            #item.SetProperty('event-id', '14-277364-2010-03-28')
            #item.SetProperty('content-id', 7229575')
            video_request_type = 'HTTP_CLOUD_WIRED'
            audio_request_type = 'AUDIO_SHOUTCAST_32K'
            #audio_request_type = 'AUDIO_FMS_32K'
            #audio_request_type = 'AUDIO_AAC_LATM_16K'
            audio_set_shout_protocol = False
            simulate_blackout = False
            simulate_not_authorized = False
            ###### DEBUG & TESTING ######

            params = {
                'subject':          'LIVE_EVENT_COVERAGE',
                'playbackScenario': video_request_type,
                'eventId':          item.GetProperty('event-id'),
                'contentId':        item.GetProperty('content-id'),
                'sessionKey':       session_id,
                'fingerprint':      cf.GetValue('fprt'),
                'identityPointId':  cf.GetValue('ipid'),
                'platform':         'BOXEE'
                }
            web_url = 'http://mlb.mlb.com/media/player/entry.jsp?calendar_event_id=%s&source=boxeeRef' % (item.GetProperty('event-id'))
            media_request = self.underscore(self.mr_url % (urllib.urlencode(params)))
            if simulate_blackout: playlist_url = -1
            elif simulate_not_authorized: playlist_url = -2
            else:
                media_data = self.queryMediaService(media_request)
                playlist_url = media_data['playlist_url']
                update_media_state = media_data['media_state']
                if bool(update_media_state) and str(update_media_state).lower() != item.GetProperty('media-state').lower():
                    self.info('playitem', 'updating media_state (%s)' % update_media_state.lower())
                    item.SetProperty('media-state', update_media_state.lower())

            if playlist_url == -3000:
                check_auth = self.authenticate()
                if check_auth == self.status_valid:
                    media_data = self.queryMediaService(media_request)
                    playlist_url = media_data['playlist_url']
                    update_media_state = media_data['media_state']
                    if bool(update_media_state) and str(update_media_state).lower() != item.GetProperty('media-state').lower():
                        self.info('playitem', 'updating media_state (%s)' % update_media_state.lower())
                        item.SetProperty('media-state', update_media_state.lower())
                else:
                   self.raiseError('Unable to validate your account. Please make sure your mlb.tv account is linked with Boxee! See boxee.tv/services.', 'playitem', 'lost users login credentials')
                   mc.HideDialogWait()
                   return False
            if playlist_url == -1:
                if not item.GetProperty('audio-string') and item.GetProperty('media-state') != 'media_on':
                    return self.raiseError('No available audio streams found for this game. We apologize for the inconvenience.')
                confirm = mc.ShowDialogConfirm('MLB.TV', 'Video is not currently available for this game. Would you like to listen to the live audio broadcast?', 'No', 'Yes')
                if confirm:
                    play_audio = self.parseAudioStreams(item)
                    if not play_audio:
                        return False
                    params = {
                        'subject':          'LIVE_EVENT_COVERAGE',
                        'playbackScenario': audio_request_type,
                        'eventId':          item.GetProperty('event-id'),
                        'contentId':        play_audio[1],
                        'sessionKey':       session_id,
                        'fingerprint':      cf.GetValue('fprt'),
                        'identityPointId':  cf.GetValue('ipid'),
                        'platform':         'BOXEE'
                        }
                    del params['platform']
                    media_request = self.underscore(self.mr_url % (urllib.urlencode(params)))
                    media_data = self.queryMediaService(media_request)
                    playlist_url = media_data['playlist_url']
                    update_media_state = media_data['media_state']
                    if bool(update_media_state) and str(update_media_state).lower() != item.GetProperty('media-state').lower():
                        self.info('playitem', 'updating media_state (%s)' % update_media_state.lower())
                        item.SetProperty('media-state', update_media_state.lower())
                else:
                    mc.HideDialogWait()
                    return False
            if playlist_url == -2:
                mc.GetActiveWindow().ClearStateStack()
                return self.raiseError('You must own MLB.TV to watch live baseball. Please go to mlb.com/boxee to sign up.')
            elif playlist_url == False:
                mc.HideDialogWait()
                return False
            if play_audio:
                content_type = 'audio/mpeg'
                stream_type = mc.ListItem.MEDIA_AUDIO_OTHER
                playlist_url = playlist_url.replace('http://', 'shout://')
                live=0
            else:
                live=0
                playlist_url = playlist_url + "&quality=%s" % (self.promptQuality())

                # Add seek param for Fiona clients
                if self.device_id:
                    playlist_url = playlist_url + "&seek=1"

                if item.GetProperty('media-state') == 'media_on':
                    confirm = mc.ShowDialogConfirm('MLB.TV', 'Would you like to watch this game from the start or jump into the live broadcast?', 'Start', 'Live')
                    live = int(confirm)
                item.SetProperty('IsLiveStream', str(live))
                playlist_url = playlist_url + "&live=" + str(live)
                content_type = 'application/vnd.apple.mpegurl'
                stream_type = mc.ListItem.MEDIA_VIDEO_OTHER
            alt_label = item.GetProperty('alt-label')
            title = alt_label.replace('#','').replace('@mlbtv', '')
            title = title.replace(' v ', ' @ ')+' on MLB.TV'
            playlist_url = playlist_url+"&bx-ourl="+urllib.quote_plus(web_url)
            ext = mc.ListItem(stream_type)
            ext.SetTitle(alt_label)
            ext.SetLabel(title)
            ext.SetDescription(item.GetDescription(), False)
            ext.SetContentType(content_type)
            ext.SetThumbnail(item.GetThumbnail())
            ext.SetProviderSource("MLB.TV")

            # Build playlist params
            params = {
                'title':        title,
                'alt-label':    alt_label,
                'event-id':     item.GetProperty("event-id"),
                'content-id':   item.GetProperty("content-id"),
                'description':  item.GetDescription(),
                'bx-ourl':      web_url,
                'thumbnail':    item.GetThumbnail(),
                'audio-stream': play_audio,
                'media-state': item.GetProperty("media-state")
                }

            # Set audio stream if audio was selected
            if play_audio:
                params['audio-string'] = item.GetProperty('audio-string')
                rand_number = str(random.randint(10000,100000000))
                tracking_url = "http://mlbglobal08.112.2o7.net/b/ss/mlbglobal08/1/G.5--NS/"+rand_number+"?ch=Media&pageName=BOXEE%20Media%20Return&c25="+str(play_audio[2])+"%7C"+self.underscore(audio_request_type)+"&c27=Media%20Player&c43=BOXEE"
                notify = mc.Http().Get(tracking_url)
                del notify

            ext.SetPath("app://mlb/launch?%s" % (urllib.urlencode(params)))
            new_item = mc.ListItem(stream_type)
            new_item.SetLabel(title)
            new_item.SetTitle(alt_label)
            new_item.SetDescription(item.GetDescription(), False)
            new_item.SetPath(str(playlist_url))
            new_item.SetProviderSource("MLB.TV")
            new_item.SetContentType(content_type)
            if media_data['game_id']:
                new_item.SetProperty("game_id", media_data['game_id'])
            new_item.SetProperty("live", str(live))
            new_item.SetThumbnail(item.GetThumbnail())
            if play_audio:
                new_item.SetAddToHistory(False)
                new_item.SetReportToServer(False)
            else:
                new_item.SetAddToHistory(True)
                new_item.SetReportToServer(True)
            new_item.SetExternalItem(ext)
            mc.GetActiveWindow().ClearStateStack()

            # Set game Job Manager
            myJobManager = MLBJobManager(media_data['game_id'])

            # Track game view
            try:
                track_label = self.generateTrackerGameString(item)
                #self.info('playItem', track_label)
                if track_label:
                    self.myTracker.trackEvent("Video", "Play", track_label)
                else:
                    self.myTracker.trackEvent("Video", "Play", title)
            except:
                self.myTracker.trackEvent("Video", "Play", title)

            # Had to disable any features that asked the player to seek, client issues
            # causing the video to jump to the end when seeked and will not be fixed.

            # Friday, 24 May 2013 // Removed due to client issues with MLB HLS timestamps
            # Innings / At-Bats / Interesting plays chapters - Fiona only
            # if self.device_id:
            #     chapters = self.getGameMarkers(media_data)
            #     if chapters:
            #         new_item.SetProperty("chapters", chapters)

            # Add Events / Innings checker if client is embedded and game is live.
            # if live == 1 and self.device_id:
            #     if mc.App().GetLocalConfig().GetValue('chapters') == "atbats" or mc.App().GetLocalConfig().GetValue('chapters') == "interesting":
            #         myJobManager.addJob(EventChecker(media_data['game_id']))
            #     else:
            #         myJobManager.addJob(InningsChecker(media_data['game_id'], media_data['innings_index']))

            # If game is live and client is Elin, turn on GameEndChecker
            if live == 1 and not self.device_id:
                myJobManager.addJob(GameEndChecker(media_data['game_id']))

            # Friday, 24 May 2013 // Removed, was not working.
            # Turn on pitch checker
            # if self.device_id and mc.App().GetLocalConfig().GetValue('pitches') and mc.App().GetLocalConfig().GetValue('pitches') != "none":
            #     self.info('playItem', 'activating PitchChecker job in JobManager')
            #     myJobManager.addJob(PitchChecker(media_data['game_id']))

            # Add message checker
            myJobManager.addJob(MessageChecker(media_data['game_id']))

            # Start job manager thread
            myJobManager.start()

            mc.HideDialogWait()

            mc.GetPlayer().Play(new_item)
        except Exception, e:
            self.info('playitem', e)
            mc.HideDialogWait()
            return False

    def generateTrackerGameString(self, item):
        try:
            desc = item.GetDescription() #Braves @ Giants (9:30 PM)[CR]AT&T Park
            event = item.GetProperty('event-id') #14-286328-2010-10-07
            desc = desc.split('[CR]')[0]
            event = event.split('-')[-3:]
            title = desc.replace(')', ' '+'-'.join(event)+')')
            self.info('generateTrackerGameString', title)
            return title
        except:
            return False

    def playList(self, mlbList):
        try:
            cf = mc.GetApp().GetLocalConfig()
            list = mc.GetActiveWindow().GetList(mlbList)
            item = list.GetItem(list.GetFocusedItem())
            if not self.isLoggedIn():
                mc.ShowDialogNotification('You must first log in before you can watch this game.','mlb-icon.png')
            elif not item.GetProperty('media-on') and not item.GetProperty('media-archive'):
                mc.ShowDialogNotification('This game is not currently available for playback.','mlb-icon.png')
            elif int(item.GetProperty('media-stream-count')) < 1:
                mc.ShowDialogNotification('This game is not currently available for playback.','mlb-icon.png')
            else:
                mc.GetActiveWindow().PushState()
                media_streams = item.GetProperty('media-string')
                media = media_streams.split('||')
                gameList = mc.ListItems()
                for stream in media:
                   gItem = mc.ListItem(mc.ListItem.MEDIA_VIDEO_CLIP)
                   data = stream.split('|')
                   gItem.SetLabel(data[0])
                   gItem.SetDescription(item.GetDescription())
                   gItem.SetThumbnail(item.GetThumbnail())
                   gItem.SetProperty('alt-label', item.GetProperty('alt-title'))
                   gItem.SetProperty('media-state', item.GetProperty('media-state'))
                   gItem.SetProperty('event-id', item.GetProperty('event-id'))
                   gItem.SetProperty('content-id', data[1])
                   gItem.SetProperty('has-audio', item.GetProperty('has-audio'))
                   gItem.SetProperty('audio-string', item.GetProperty('audio-string'))
                   #gItem.SetPath(data[1])
                   gameList.append(gItem)
                   mc.GetActiveWindow().GetList(501).SetItems(gameList)
                   mc.GetActiveWindow().GetList(501).SetFocusedItem(0)
                   mc.GetActiveWindow().GetControl(501).SetFocus()
                mc.GetActiveWindow().GetControl(500).SetVisible(True)
        except Exception, e:
            self.error('playlist', e)
            mc.ShowDialogNotification('Sorry, we are currently unable to play this game.','mlb-icon.png')
            return False


    '''
    Spoilers
    '''
    def updateArchiveSpoiler(self):
        try:
            mc.ShowDialogWait()
            if self.isLoggedIn():
                response = self.callService('showhide')
                if response == 'T': mc.GetApp().GetLocalConfig().SetValue('hide_scores', 'true')
                else: mc.GetApp().GetLocalConfig().Reset('hide_scores')
            else: mc.GetApp().GetLocalConfig().Reset('hide_scores')
            mc.HideDialogWait()
        except Exception, e:
            mc.GetApp().GetLocalConfig().Reset('hide_scores')
            return self.raiseError(log='updatearchivespoiler', error=e)

    def saveArchiveSpoiler(self, value):
        try:
            mc.ShowDialogWait()
            if self.isLoggedIn():
                response = self.callService('showhidesave', {'value':value})
                if response == '1':
                    mc.ShowDialogNotification('Score spoiler settings saved successfully!','mlb-icon.png')
                else: raise Exception('Server returned '+response)
            else: mc.ShowDialogNotification('You must be logged in to modify settings.','mlb-icon.png')
            mc.HideDialogWait()
        except Exception, e:
            return self.raiseError(log='savearchivespoiler', error=e)


    '''
    Favorites
    '''
    def favoriteTeams(self):
        try:
            mc.ShowDialogWait()
            data = self.getJson('http://mlb.mlb.com/lookup/json/named.team_all.bam?sport_code=%27mlb%27&active_sw=%27Y%27&all_star_sw=%27N%27')
            data = data.get("team_all").get("queryResults").get("row")
            teamList = mc.ListItems()
            for team in data:
                item = mc.ListItem(mc.ListItem.MEDIA_UNKNOWN)
                item.SetLabel(str(team.get('name_display_full')))
                item.SetThumbnail("http://mlb.mlb.com/images/logos/200x200/200x200_%s.png" % (str(team.get('name_abbrev'))))
                item.SetProperty('team-id', str(team.get('team_id')))
                item.SetProperty('team-abbrev', str(team.get('team_abbrev')))
                teamList.append(item)
            favList = []
            for index,team in enumerate(teamList):
                if team.GetProperty('team-id') in favList:
                    teamList.SetSelected(index,True)
            mc.HideDialogWait()
            return teamList
        except Exception, e:
            self.raiseError(log='favoriteteams',error=e)

    def selectFavorite(self, listId):
        try:
            found = False
            list = mc.GetWindow(14010).GetList(listId)
            itemNumber = list.GetFocusedItem()
            item = list.GetItem(itemNumber)
            selectedItems = list.GetSelected()
            for team in selectedItems:
               if team.GetProperty('team-id') == item.GetProperty('team-id'):
                  found = True
                  list.SetSelected(itemNumber, False)
            if not found: list.SetSelected(itemNumber, True)
        except Exception, e:
            return self.raiseError(log='selectfavorite', error=e)

    def saveFavorites(self):
        try:
            mc.ShowDialogWait()
            favs = []
            for div in range(200,206):
                items = mc.GetWindow(14010).GetList(div).GetSelected()
                for team in items:
                    favs.append(team.GetProperty('team-id'))
            favs = ";".join(favs)
            response = self.callService('setfavorites', {'teamids':favs})
            if response == '1': mc.ShowDialogNotification('Your favorite teams have been saved successfully.','mlb-icon.png')
            else: raise Exception('Server returned '+str(response))
            mc.HideDialogWait()
        except Exception, e:
            mc.GetActiveWindow().PopState()
            return self.raiseError(log='savefavorites', error=e)

    def loadFavorites(self):
        try:
            mc.ShowDialogWait()
            if self.isLoggedIn():
                response = self.callService('teams')
                data = json.loads(response)
                data = data.get('teams')
                division = { '200': mc.ListItems(),'201': mc.ListItems(),'202': mc.ListItems(),'203': mc.ListItems(),'204': mc.ListItems(),'205': mc.ListItems() }
                for team in data:
                   item = mc.ListItem(mc.ListItem.MEDIA_UNKNOWN)
                   item.SetLabel(str(team.get('title')))
                   item.SetThumbnail(str(team.get('thumb')))
                   item.SetProperty('team-id', str(team.get('team-id')))
                   item.SetProperty('team-abbrev', str(team.get('team-abbrev')))
                   item.SetProperty('team-leauge', str(team.get('team-leauge')))
                   item.SetProperty('team-division', str(team.get('team-division')))
                   item.SetProperty('team-fav', str(team.get('team-fav')))
                   div = str(team.get('team-division'))
                   division[div].append(item)
                for div in division:
                   mc.GetWindow(14010).GetList(int(div)).SetItems(division[div])
                   list = mc.GetWindow(14010).GetList(int(div))
                   for i,v in enumerate(list.GetItems()):
                      if v.GetProperty('team-fav') == '1':
                         list.SetSelected(i,True)
            else: return self.raiseError('You must be logged in to access your favorite teams!')
            mc.HideDialogWait()
        except Exception, e:
           import xbmc
           xbmc.executebuiltin("Dialog.Close(14010)")
           return self.raiseError('An error occured while accessing your favorite team settings. Are you logged in?', log='loadfavorites', error=e)


    '''
    Game Data
    '''
    def getPlayers(self, game_id):
        '''
        Get players for game
        '''
        players_uri = self.gameIdToEventURI(game_id) + "players.xml"
        xml = mc.Http().Get(players_uri)
        if not xml:
            self.debug('playersdata', "Could not retrieve players xml here - %s" % (players_uri))
            return False
        else:
            try:
                data = self.parsePlayers(xml)
                return data
            except Exception, e:
                self.debug('playersdata', "Encountered error parsing players data.")
                self.raiseError(log='playersdata', error=e)
                return False

    def parsePlayers(self, xml):
        '''
        Parse players from gdx xml
        '''
        players = {}
        dom = parseString(xml)
        for player in dom.getElementsByTagName('player'):
            dict = {}
            dict['teamname'] = player.parentNode.attributes["name"].value
            dict['teamcode'] = player.parentNode.attributes["id"].value
            dict['teamtype'] = player.parentNode.attributes["type"].value
            for i in range(player.attributes.length):
                attribute = player.attributes.item(i)
                dict[attribute.name] = attribute.value
            players[dict['id']] = dict
        return players


    '''
    Game markers
    '''
    def getGameMarkers(self, media_data):
        if mc.App().GetLocalConfig().GetValue('chapters') == "atbats" or mc.App().GetLocalConfig().GetValue('chapters') == "interesting":
            if media_data['game_id']:
                self.players = self.getPlayers(media_data['game_id'])
                if mc.App().GetLocalConfig().GetValue('chapters') == "interesting":
                    events = self.getEvents(media_data['game_id'], self.players, True)
                else:
                    events = self.getEvents(media_data['game_id'], self.players)
                if events:
                    return self.setEvents(events)
            else:
                self.debug('chapters', "Could not get game_id from media service request.")
                return False
        else:
            if media_data['innings_index']:
                innings = self.getInnings(media_data['innings_index'])
                if innings:
                    return self.setInnings(innings)
            else:
                self.debug('chapters', "Could not get innings_index from media service request.")
                return False


    def setInnings(self, innings):
        '''
        Set innings for listitem
        '''
        chapters = []
        for inning in innings:
            chapters.append({
                'name': inning['inning'],
                'startTime': inning['start'],
                'duration': 0
            })
        try:
            chapters = self.formatChapters(chapters)
        except Exception, e:
            self.debug('innings', "Encountered error formatting innings data.")
            self.raiseError(log='innings', error=e)
            return False
        return chapters

    def getInnings(self, innings_index):
        '''
        Retrieve innings for innings_index
        '''
        # Retrieve innings index
        xml = mc.Http().Get(innings_index)
        if not xml:
            self.debug('innings', "Could not retrieve innings_index xml here - %s" % (innings_index))
            return False
        else:
            try:
                data = self.parseInnings(xml)
                if data:
                    return data
                else:
                    return False
            except Exception, e:
                self.debug('innings', "Encountered error parsing innings data.")
                self.raiseError(log='innings', error=e)
                return False


    def parseInnings(self, xml):
        '''
        Parse innings index xml
        '''
        innings = []
        self.debug('innings', "Creating DOM...")
        dom = parseString(xml)
        for inning in dom.firstChild.childNodes:
            self.debug('innings', "Finding inning...")
            dict = {}
            # Get inning title
            self.debug('innings', "Getting inning names...")
            if inning.attributes["top"].value == "true":
                dict['inning'] = "Top " + self.ordinal(int(inning.attributes["inning_number"].value))
            else:
                dict['inning'] = "Bottom " + self.ordinal(int(inning.attributes["inning_number"].value))
            # Get start and end time
            self.debug('innings', "Setting start and end times...")
            time = inning.firstChild
            try:
                dict['start'] = time.attributes["start"].value
                matches = re.findall('^.*?T(\d+:\d+:\d+)\+', dict['start'], re.M)
                if matches:
                    dict['start'] = str(matches[0])
            except:
                dict['start'] = 0
            try:
                dict['stop'] = time.attributes["end"].value
                matches = re.findall('^.*?T(\d+:\d+:\d+)\+', dict['stop'], re.M)
                if matches:
                    dict['stop'] = str(matches[0])
            except:
                dict['stop'] = 0
            self.debug('innings', "Adding to innings...")
            innings.append(dict)
        print innings
        return innings

    def setEvents(self, events):
        '''
        Set Events chapters for listitem
        '''
        chapters = []
        for event in events:
            startTime = self.digitsToTimecode(str(event['start_tfs']))
            if mc.GetApp().GetLocalConfig().GetValue('hide_scores') == "true":
                chapters.append({
                    'name': event['inning'] + " " + event['boxname'] + " / " + event['pitcher_boxname'],
                    'startTime': startTime,
                    'duration': 0
                })
            else:
                chapters.append({
                    'name': event['inning'] + " " + event['boxname'] + " / " + event['event'],
                    'startTime': startTime,
                    'duration': 0
                })
        try:
            chapters = self.formatChapters(chapters)
        except Exception, e:
            self.debug('events', "Encountered error formatting events data.")
            self.raiseError(log='events', error=e)
            return False
        return chapters

    def getEvents(self, game_id, players=None, interesting=False):
        '''
        Retrieve events for game_id
        '''
        event_uri = self.gameIdToEventURI(game_id) + "game_events.xml"
        xml = mc.Http().Get(event_uri)
        if not xml:
            self.debug('events', "Could not retrieve events xml here - %s" % (event_uri))
            return False
        else:
            try:
                data = self.parseEvents(xml)
                # If "interesting" bit is set, return only at-bats that are interesting.
                if interesting:
                    data = self.parseInterestingEvents(data)
                # if Players Data available, map IDs to boxnames
                if players:
                    for event in data:
                        event['boxname'] = players[event['batter']]['boxname']
                        event['pitcher_boxname'] = players[event['pitcher']]['boxname']
                return data
            except Exception, e:
                self.raiseError(log='events', error=e)
                return False

    def parseInterestingEvents(self, events):
        new_data = []
        for event in events:
            if event['event'] in self.event_filter:
                new_data.append(event)
        return new_data

    def parseEvents(self, xml):
        '''
        Parse innings index xml
        '''
        events = []
        dom = parseString(xml)
        for event in dom.getElementsByTagName('atbat'):
            dict = {}
            dict['inning'] = event.parentNode.tagName.capitalize() + " " + self.ordinal(int(event.parentNode.parentNode.attributes["num"].value))
            for i in range(event.attributes.length):
                attribute = event.attributes.item(i)
                dict[attribute.name] = attribute.value
            events.append(dict)
        return events

    def formatChapters(self, chapters):
        '''
        Accept chapters list of dictionaries and output into XML for Boxee client.
        '''
        xml = "<?xml version=\"1.0\" encoding=\"UTF-8\" ?><chapters>"
        for chapter in chapters:
            xml = xml + "<chapter name=\"" + str(chapter['name']) + "\" startTime=\"" + str(chapter['startTime']) + "\" duration=\"" + str(chapter['duration']) + "\" />"
        xml = xml + "</chapters>"
        return xml

    def getPitch(self, game_id):
        '''
        Get latest pitch
        '''
        event_uri = self.gameIdToEventURI(game_id) + "plays.xml"
        xml = mc.Http().Get(event_uri)
        if not xml:
            self.debug('pitch', "Could not retrieve pitch xml here - %s" % (event_uri))
        else:
            try:
                data = parsePitch(self, xml)
                if data:
                    data['string_type'] = self.pitches[data['pitch_type']]
                    return data
                else:
                    return None
            except Exception, e:
                self.error('pitch', "Error parsing pitch.")
                return None

    def parsePitch(self, xml):
        '''
        Parse pitch from plays.xml
        '''
        pitches = []
        dom = parseString(xml)
        if dom.getElementsByTagName('p'):
            for pitch in dom.getElementsByTagName('p'):
                dict = {}
                dict['pitcher'] = dom.getElementsByTagName('pitcher')[0].attributes["boxname"].value

                # Define pitch schema
                if pitch.hasAttribute('nasty'):
                    dict['schema'] = "detailed"
                else:
                    dict['schema'] = "small"

                # Get pitch attributes
                for i in range(pitch.attributes.length):
                    attribute = pitch.attributes.item(i)
                    dict[attribute.name] = attribute.value

                # Remove spoiler data from pitch.
                if pitch.hasAttribute('des'):
                    dict['des'] = dict['des'].split(",")[0]
                pitches.append(dict)
            if pitches:
                return pitches.pop()
        else:
            self.debug("pitches", "No pitches found.")
            return False


    '''
    MLB Messaging
    '''
    def processMessages(self):
        '''
        Process all the messages
        '''
        self.debug('messages', "Processing messages...")
        try:
            self.debug('messages', "Getting messages...")
            messages = self.getMessages()
        except Exception, e:
            self.error('messages', "Error getting messages.")
            return False
        if messages:
            self.debug('messages', "Messages found - processing")
            for message in messages:
                if not self.messageAlreadyDisplayed(message) and self.messageWithinWindow(message):
                    try:
                        self.debug('messages', "Displaying message: %s" % (message['message']))
                        self.displayMessage(message)
                    except Exception, e:
                        self.error('messages', "Error displaying messages.")
                        return False
                else:
                    self.debug('messages', "Already displayed message")
        else:
            self.debug('messages', "No messages found.")

    def getMessages(self):
        '''
        Get message from message_uri
        '''
        xml = mc.Http().Get(self.message_uri)
        if not xml:
            self.debug('messages', "Could not retrieve message xml here - %s" % (event_uri))
        else:
            try:
                messages = self.parseMessages(xml)
            except Exception, e:
                self.error('messages', "Error parsing messages.")
                return False
            if messages:
                # Filter message based on user.
                messageList = []
                for message in messages:
                        playing = mc.GetPlayer().IsPlaying()
                        if message['users'] == "all" and not playing:
                            messageList.append(message)
                        elif message['users'] == "registered" and self.authenticated and not playing:
                            messageList.append(message)
                        elif message['users'] == "unregistered" and self.authenticated and not playing:
                            messageList.append(message)
                        elif message['users'] == "viewing" and playing:
                            messageList.append(message)
                return messageList
            else:
                self.debug("No messages posted.")
                return False

    def displayMessage(self, message):
        hash = md5.md5(str(message)).hexdigest()
        mc.GetApp().GetLocalConfig().SetValue(hash, "true")
        if message['type'] == "ok":
            self.debug('messages', "Displaying OK dialog")
            return mc.ShowDialogOk(str(message['source']), str(message['message']))
        else:
            self.debug('messages', "Displaying notification dialog")
            return mc.ShowDialogNotification(str(message['message']), "mlb-icon.png")

    def messageAlreadyDisplayed(self, message):
        self.debug('messages', "Checking if message has already been displayed.")
        hash = md5.md5(str(message)).hexdigest()
        if mc.GetApp().GetLocalConfig().GetValue(hash):
            self.debug('messages', 'Message has already been displayed.')
            return True
        else:
            self.debug('messages', 'Message has not been displayed.')
            return False

    def messageWithinWindow(self, message):
        self.debug('messages', "Checking if time is in current message window.")
        now = self.getCurrentMLBTime()
        self.debug('messages', 'Current MLB time is: %s.' % (str(now)))
        startTime = time.strptime(message['startDatetime'], "%d %b %Y %H:%M")
        endTime = time.strptime(message['endDatetime'], "%d %b %Y %H:%M")
        if now >= startTime and now <= endTime:
            self.debug('messages', 'Message is in window.')
            return True
        else:
            self.debug('messages', 'Message is not in window.')
            return False

    def parseMessages(self, xml):
        self.debug('messages', "Parsing messages.")
        dom = parseString(xml)
        if dom.getElementsByTagName('message'):
            messageList = []
            for message in dom.getElementsByTagName('message'):
                dict ={}
                for i in range(message.attributes.length):
                    attribute = message.attributes.item(i)
                    dict[attribute.name] = attribute.value
                dict['message'] = message.firstChild.data
                messageList.append(dict)
            return messageList
        else:
            return False


'''
Job Manager - threaded job queue that runs during video playback.
'''
class MLBJobManager(jobmanager.BoxeeJobManager):
    def __init__(self, game_id):
        self.game_id = game_id
        self.mlb = MLB()
        self.videoFail = 0
        jobmanager.BoxeeJobManager.__init__(self, 5)
        self.log("Setting game_id as: %s" % (self.game_id))

    def check(self):
        if self.videoFail >= 3:
            return self.stop()
        if not mc.GetPlayer().IsPlaying():
            self.log("Video not playing - incrementing counter.")
            # If video check fails three times, kill JobManager
            self.videoFail = self.videoFail + 1
            return
        else:
            self.log("Video is playing - checking if game is same.")
            playingItem = mc.GetPlayer().GetPlayingItem()
            game_id = playingItem.GetProperty("game_id")
            self.log("Evaluating game_id: %s" % (game_id))
            if not game_id:
                self.log("Video playing is not an MLB game - incremented fail counter.")
                self.videoFail = self.videoFail + 1
                return
            else:
                self.videoFail = 0
                if game_id != self.game_id:
                    self.log("Same game is not playing - exiting!")
                    return self.stop()

class MLBJob(jobmanager.BoxeeJob):
    def __init__(self, name, game_id, interval=10):
        self.name = name
        self.mlb = MLB()
        self.game_id = game_id
        self.hash = None
        self.log("Setting game ID to: %s" % (self.game_id))
        self.players = self.mlb.getPlayers(self.game_id)
        jobmanager.BoxeeJob.__init__(self, name, interval)

    def xmlChanged(self, xml):
        self.log("Checking if xml has changed.")
        new_hash = md5.md5(str(xml)).hexdigest()
        if new_hash == self.hash:
            self.log("Xml has not changed.")
            return False
        else:
            self.log("Xml has changed.")
            self.hash = new_hash
            return True

    def getInHMS(self, seconds):
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return "%d%02d%02d" % (h, m, s)

class PitchChecker(MLBJob):
    def __init__(self, game_id):
        self.firstRun = True
        self.game_id = game_id
        self.timecodeRetry = 0
        self.setting = mc.GetApp().GetLocalConfig().GetValue('pitches')
        self.timer = threading.Event()
        self.lastPitch = None
        MLBJob.__init__(self, "PitchChecker", self.game_id, 0)

    def process(self):
        self.log("activating process")
        xml = self.getXml()
        if not self.firstRun:
            if xml:
                pitch = self.mlb.parsePitch(xml)
                if pitch and pitch['id'] != self.lastPitch:
                    self.log("Received pitch - building message.")
                    if pitch['schema'] == "detailed":
                        pitch['string_type'] = self.mlb.pitches[pitch['pitch_type']][1]
                        if self.setting == "km/h":
                            kmh = str(int(pitch['start_speed'].split(".")[0].strip()) * 1.609344)
                            pitch_message = str("%s: %s - %s km/h" % (pitch['des'], pitch['string_type'], str(int(kmh.split(".")[0].strip()))))
                        elif self.setting == "nasty":
                            pitch_message = str("%s: %s - %s%%" % (pitch['des'], pitch['string_type'], pitch['nasty']))
                        else:
                            pitch_message = str("%s: %s - %s mph" % (pitch['des'], pitch['string_type'], str(int(pitch['start_speed'].split(".")[0].strip()))))
                    else:
                        pitch_message = str("%s" % (pitch['des']))
                    self.log("Sending pitch to client: %s" % (pitch_message))
                    mc.ShowDialogNotification(pitch_message,'mlb-icon.png')
                    self.lastPitch = pitch['id']
                    self.log("Message sent.")
                else:
                    return self.log("No pitch found.")
            else:
                return self.log("No new xml to process")
        else:
            self.log("Storing pitch info for first iteration.")
            self.firstRun = False

    def getXml(self):
        self.log("activating getXML")
        if mc.GetPlayer().IsPlaying():
            rawtime = mc.GetPlayer().GetTime()
            if rawtime == -1:
                self.log("Did not get timecode from client! ")
                self.timecodeRetry = self.timecodeRetry + 1
                if self.timecodeRetry <= 3:
                    self.timer.wait(1)
                    return self.getXml()
                else:
                    self.log("Gave up getting timecode after %i tries." % (self.timecodeRetry))
                    self.timecodeRetry = 0
                    return False
            else:
                self.timecodeRetry = 0
            timecode = self.getInHMS(rawtime)
            # Padding to tighten up pitch to display
            timecode = str(int(timecode) - 5)
            # Round time code to nearest 5
            timecode = str(int(5 * round(float(int(timecode))/5)))
            self.log("Timecode is %s" % (timecode))
        else:
            return False
        event_uri = self.mlb.gameIdToEventURI(self.game_id, True) + "plays.xml&timecode=" + timecode
        self.log("Fetching URI %s" % (event_uri))
        xml = mc.Http().Get(event_uri)
        if not xml:
            self.log("Could not retrieve innings xml here - %s" % (event_uri))
            return False
        else:
            if self.xmlChanged(xml):
                self.log("New xml to process.")
                # Debug info for new data
                #self.debugXml(xml)
                return xml
            else:
                return False

    def debugXml(self, xml):
        self.log("Debug info for plays data:")
        dom = parseString(xml)
        boxscore = {}
        for i in range(dom.getElementsByTagName('game')[0].attributes.length):
            attribute = dom.getElementsByTagName('game')[0].attributes.item(i)
            try:
                boxscore[attribute.name] = boxscore[attribute.value]
            except:
                raise Exception
        self.log("Box: %s %s. Count: %s balls, %s strikes, %s outs." % (boxscore['inning'], boxscore['top_inning'], boxscore['b'], boxscore['s'], boxscore['o']))
        for player in dom.getElementsByTagName('players')[0].childNodes:
            dict = {}
            if self.players:
                for player in self.players:
                    dict['boxname'] = self.players[player['pid']]['boxname']
            for i in range(player.attributes.length):
                attribute = player.attributes.item(i)
                dict[attribute.name] = attribute.value
            self.log("Data for %s: %s" %(player.tagName, dict))
        return self.log("End debug info for plays data.")


class InningsChecker(MLBJob):
    def __init__(self, game_id, innings_index):
        self.innings_index = innings_index
        MLBJob.__init__(self, "InningsChecker", game_id, 120)

    def process(self):
        xml = self.getXml()
        if xml:
            self.log("Received new xml to process.")
            self.log("Parsing xml...")
            data = self.mlb.parseInnings(xml)
            self.log("Formatting chapters...")
            chapters = self.mlb.setInnings(data)
            self.log("Sending chapters to client...")
            return mc.GetApp().SendMessage("mlb:chapters", chapters)
        else:
            return self.log("No new xml to process.")

    def getXml(self):
        xml = mc.Http().Get(self.innings_index)
        if not xml:
            self.log("Could not retrieve innings xml here - %s" % (self.innings_index))
            return False
        else:
            if self.xmlChanged(xml):
                self.log("New xml to process.")
                return xml
            else:
                return False

class EventChecker(MLBJob):
    def __init__(self, game_id):
        MLBJob.__init__(self, "EventsChecker", game_id, 60)

    def process(self):
        xml = self.getXml()
        if xml:
            self.log("Received new xml to process.")
            self.log("Parsing xml...")
            data = self.mlb.parseEvents(xml)
            # If "interesting" bit is set, return only at-bats that are interesting.
            if mc.App().GetLocalConfig().GetValue('chapters') == "interesting":
                self.log("Getting only big plays")
                data = self.mlb.parseInterestingEvents(data)
            # if Players Data available, map IDs to boxnames
            if self.players:
                self.log("Matching up player box names to player ids...")
                for event in data:
                    event['boxname'] = self.players[event['batter']]['boxname']
            if data:
                self.log("Formatting into chapters...")
                chapters = self.mlb.setEvents(data)
                self.log("Updating client with new events.")
                return mc.GetApp().SendMessage("mlb:chapters", chapters)
            return False
        else:
            self.log("No new xml to process.")

    def getXml(self):
        event_uri = self.mlb.gameIdToEventURI(self.game_id) + "game_events.xml"
        xml = mc.Http().Get(event_uri)
        if not xml:
            self.log("Could not retrieve events xml here - %s" % (event_uri))
            return False
        else:
            if self.xmlChanged(xml):
                self.log("New xml to process.")
                return xml
            else:
                return False

class MessageChecker(MLBJob):
    def __init__(self, game_id):
        MLBJob.__init__(self, "MessageChecker", game_id, 900)

    def process(self):
        self.log("Processing messages...")
        self.mlb.processMessages()
        self.log("Done processing messages.")

class GameEndChecker(MLBJob):
    def __init__(self, game_id):
        MLBJob.__init__(self, "MessageChecker", game_id, 600)

    def process(self):
        self.log("Checking if game has ended...")
        xml = self.getXml()
        if xml:
            self.log("Received XML - parsing...")
            dom = parseString(xml)
            boxscore = dom.getElementsByTagName('boxscore')[0]
            if boxscore.attributes["status_ind"].value == "F":
                mc.GetPlayer().Stop()
                mc.ShowDialogOk("MLB.tv", "Thank you for watching MLB.tv!")

    def getXml(self):
        event_uri = self.mlb.gameIdToEventURI(self.game_id) + "boxscore.xml"
        xml = mc.Http().Get(event_uri)
        if not xml:
            self.log("Could not retrieve events xml here - %s" % (event_uri))
            return False
        else:
            if self.xmlChanged(xml):
                self.log("New xml to process.")
                return xml
            else:
                return False
