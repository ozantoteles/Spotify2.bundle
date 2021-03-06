from client import SpotifyClient
from containers import Containers
from plugin.server import Server
from routing import route_path
from search import SpotifySearch
from settings import PREF_SS_RANGES, VERSION
from utils import authenticated, parse_xml, LF
import logging_handler

from cachecontrol import CacheControl
import json
import logging
import os
import requests
import socket


class SpotifyHost(object):
    def __init__(self):
        self.client = None
        self.server = None

        self.messages = []
        self.start()

        self.search = SpotifySearch(self)

        self.session = requests.session()
        self.session_cached = CacheControl(self.session)

        self.containers = Containers(self)

        # Server detail
        self.server_name = None
        self.server_address = None
        self.server_version = None

        self.local_address = None

        # Private
        self.credits_data = None

    @property
    def username(self):
        return Prefs["username"]

    @property
    def password(self):
        return Prefs["password"]

    @property
    def proxy_tracks(self):
        return Prefs['proxy_tracks']

    @property
    def hostname(self):
        if Prefs['proxy_hostname']:
            # Custom hostname defined in preferences
            return Prefs['proxy_hostname']

        if self.local_address:
            # Hostname identified from <socket>.getsockname()
            return self.local_address

        if self.server_address:
            # Hostname identified from Plex API
            return self.server_address

        # Fallback to socket hostname
        return socket.gethostname()

    @property
    def sp(self):
        if not self.client:
            return None

        return self.client.sp

    @property
    def code_path(self):
        return Core.code_path

    @property
    def bundle_path(self):
        return os.path.abspath(os.path.join(self.code_path, '..'))

    @property
    def credits(self):
        if not self.credits_data:
            try:
                # Parse credits file
                self.credits_data = json.loads(Resource.Load('credits.json'))
            except (ValueError, TypeError):
                # Invalid credits file
                self.credits_data = {}

        return self.credits_data

    def preferences_updated(self):
        # Update logging levels
        logging_handler.setup()

        # Trigger a client restart
        self.start()

    def start(self):
        self.messages = []

        if not self.username or not self.password:
            self.messages.append((logging.ERROR, 'Username or Password not entered'))
            Log.Error('Username or Password not entered')
            return

        Log.Debug('bundle_path: "%s"', self.bundle_path)

        if not self.client:
            self.client = SpotifyClient(self)

        # Start server (if 'proxy_tracks' is enabled)
        if not self.server and self.proxy_tracks:
            self.server = Server(self)
            self.server.start()

        # Stop server if 'proxy_tracks' has been disabled
        if self.server and not self.proxy_tracks:
            self.server.stop()
            self.server = None

        # Update server preferences
        if self.server:
            self.server.supports_ranges = PREF_SS_RANGES.get(Prefs['proxy_ranges'], True)

        # Update reference on SpotifyClient
        self.client.server = self.server

        # start/restart the client
        self.client.start()

    def get(self, url, *args, **kwargs):
        try:
            return self.session.get(url, *args, **kwargs)
        except:
            return None

    def get_xml(self, url, *args, **kwargs):
        response = self.session.get(url, *args, **kwargs)
        if not response:
            return None

        return parse_xml(response.content)

    def refresh(self):
        self.refresh_server()
        self.refresh_local()

        Log.Info('Using the host/address "%s" for streaming', self.hostname)

    def refresh_server(self):
        Log.Debug('Refreshing server info...')

        # Determine local server name
        detail = self.get_xml('http://127.0.0.1:32400')

        if not detail:
            Log.Warn('"/" request failed, unable to retrieve info')
            return None

        self.server_name = detail.get('friendlyName')

        # Find server address and version
        servers = self.get_xml('http://127.0.0.1:32400/servers')

        if not servers:
            Log.Warn('"/servers" request failed, unable to retrieve server info')
            return None

        for server in servers.findall('Server'):
            if server.get('name').lower() == self.server_name.lower():
                self.server_address = server.get('address')
                self.server_version = server.get('version')
                break

        Log.Debug(
            'Updated server info - name: %s, address: %s, version: %s',
            self.server_name,
            self.server_address,
            self.server_version
        )

    def refresh_local(self):
        try:
            s_discovery = socket.socket(type=socket.SOCK_DGRAM)
            s_discovery.connect(('spotify.com', 80))

            netloc = s_discovery.getsockname()
            s_discovery.close()

            if len(netloc) != 2:
                self.local_address = None
                Log.Warn('Invalid response from getsockname(): %s', netloc)
                return

            self.local_address, _ = netloc
            Log.Debug('Updated local info - address: %s', self.local_address)
        except Exception, ex:
            self.local_address = None
            Log.Warn('Unable to discover local address - %s', ex)

    @property
    def all_messages(self):
        if not self.client:
            return [(logging.ERROR, 'Client not initialized')] + self.messages

        return self.messages + self.client.messages

    def last_message(self):
        if not self.all_messages:
            return None, ''

        return self.all_messages[-1]

    #
    # Core
    #

    def main_menu(self):
        objects = []

        level, message = self.last_message()

        if level:
            objects.append(DirectoryObject(
                key=route_path('messages'),
                title='%s: %s' % (logging.getLevelName(level), message),
                thumb=R('icon-message-%s.png' % (
                    'error' if level == logging.ERROR
                    else 'warning'
                ))
            ))

        objects.extend([
            InputDirectoryObject(
                key=route_path('search'),
                prompt=L('PROMPT_SEARCH'),
                title=L('SEARCH'),
                thumb=R('icon-search.png')
            ),
            DirectoryObject(
                key=route_path('explore'),
                title=L('EXPLORE'),
                thumb=R('icon-explore.png')
            ),
            #DirectoryObject(
            #    key=route_path('discover'),
            #    title=L("DISCOVER"),
            #    thumb=R("icon-default.png")
            #),
            #DirectoryObject(
            #    key=route_path('radio'),
            #    title=L("RADIO"),
            #    thumb=R("icon-default.png")
            #),
            DirectoryObject(
                key=route_path('your_music'),
                title=L('YOUR_MUSIC'),
                thumb=R('icon-your_music.png')
            ),
            DirectoryObject(
                key=route_path('about'),
                title=L('ABOUT'),
                thumb=R('icon-about.png')
            ),
            PrefsObject(
                title=L('PREFERENCES'),
                thumb=R('icon-preferences.png')
            )
        ])

        return ObjectContainer(
            objects=objects,
            no_cache=True
        )

    def messages(self):
        oc = ObjectContainer(
            title2=L('MESSAGES'),
            no_cache=True
        )

        for level, message in self.all_messages:
            oc.add(DirectoryObject(
                key=route_path('messages'),
                title='[%s] %s' % (logging.getLevelName(level), message)
            ))

        return oc

    def about(self):
        return ObjectContainer(
            objects=[
                DirectoryObject(
                    key='',
                    title=LF('VERSION', VERSION)
                ),
                DirectoryObject(
                    key=route_path('about/credits'),
                    title=L('CREDITS')
                )
            ]
        )

    def about_credits(self):
        objects = []

        for group, names in self.credits.items():
            # Create objects for each name
            for name in names:
                objects.append(DirectoryObject(
                    key='',
                    title='[%s] %s' % (group, name)
                ))

        return ObjectContainer(
            objects=objects
        )

    @authenticated
    def search(self, query, callback, type='all', count=7, plain=False):
        self.search.run(query, callback, type, count, plain)

    @authenticated
    def play(self, uri):
        """ Play a spotify track: redirect the user to the actual stream """
        return Redirect(self.client.stream_url(uri))

    @authenticated
    def image(self, uri):
        if not uri:
            # TODO media specific placeholders
            return Redirect(R('placeholder-artist.png'))

        if uri.startswith('spotify:'):
            # TODO image for URI
            raise NotImplementedError()
        else:
            # pre-selected image provided
            Log.Debug('Using pre-selected image URL: "%s"' % uri)
            image_url = uri

        return self.session_cached.get(image_url).content

    #
    # Metadata
    #

    @authenticated
    def artist(self, uri, callback):
        @self.sp.metadata(uri)
        def on_artist(artist):
            self.containers.artist(artist, callback)

    @authenticated
    def artist_top_tracks(self, uri, callback):
        @self.sp.metadata(uri)
        def on_artist(artist):
            self.containers.artist_top_tracks(artist, callback)

    @authenticated
    def artist_albums(self, uri, callback):
        @self.sp.metadata(uri)
        def on_artist(artist):
            self.containers.artist_albums(artist, callback)

    @authenticated
    def album(self, uri, callback):
        @self.sp.metadata(uri)
        def on_album(album):
            self.containers.album(album, callback)

    @authenticated
    def metadata(self, uri, callback):
        Log.Debug('fetching metadata for uri: "%s"', uri)

        @self.sp.metadata(uri)
        def on_track(track):
            callback(self.containers.metadata(track))

    #
    # Your Music
    #

    @authenticated
    def your_music(self):
        """ Explore your music"""
        return ObjectContainer(
            title2=L('YOUR_MUSIC'),
            objects=[
                DirectoryObject(
                    key=route_path('your_music/playlists'),
                    title=L('PLAYLISTS'),
                    thumb=R('icon-playlists.png')
                ),
                DirectoryObject(
                    key=route_path('your_music/starred'),
                    title=L('STARRED'),
                    thumb=R('icon-starred.png')
                ),
                DirectoryObject(
                    key=route_path('your_music/albums'),
                    title=L('ALBUMS'),
                    thumb=R('icon-albums.png')
                ),
                DirectoryObject(
                    key=route_path('your_music/artists'),
                    title=L('ARTISTS'),
                    thumb=R('icon-artists.png')
                ),
            ],
        )

    @authenticated
    def playlists(self, callback, **kwargs):
        @self.sp.user.playlists()
        def on_playlists(playlists):
            callback(self.containers.playlists(playlists, **kwargs))

    @authenticated
    def playlist(self, uri, callback):
        @self.sp.playlist(uri)
        def on_playlist(playlist):
            Log("Got playlist: %s", playlist.name)
            Log.Debug('playlist truncated: %s', playlist.truncated)

            callback(self.containers.playlist(playlist))

    @authenticated
    def starred(self, callback):
        return SpotifyHost.playlist(self, 'spotify:user:%s:starred' % self.sp.username, callback)

    @authenticated
    def artists(self, callback):
        params = {'includefollowedartists': 'true'}

        @self.sp.user.collection('artistscoverlist', params)
        def on_artists(artists):
            self.containers.artists(artists, callback)

    @authenticated
    def albums(self, callback):
        @self.sp.user.collection('albumscoverlist')
        def on_albums(albums):
            self.containers.albums(albums, callback)

    #
    # Explore
    #

    @authenticated
    def explore(self):
        """ Explore shared music"""
        return ObjectContainer(
            title2=L('EXPLORE'),
            objects=[
                DirectoryObject(
                    key=route_path('explore/featured_playlists'),
                    title=L('FEATURED_PLAYLISTS'),
                    thumb=R("icon-featured_playlists.png")
                ),
                DirectoryObject(
                    key=route_path('explore/top_playlists'),
                    title=L('TOP_PLAYLISTS'),
                    thumb=R("icon-top_playlists.png")
                ),
                DirectoryObject(
                    key=route_path('explore/new_releases'),
                    title=L('NEW_RELEASES'),
                    thumb=R("icon-new_releases.png")
                )
            ],
        )

    def featured_playlists(self, callback):
        @self.sp.explore.featured_playlists()
        def on_playlists(result):
            callback(self.containers.playlists(result.items, title=L('FEATURED_PLAYLISTS')))

    def top_playlists(self, callback):
        @self.sp.explore.top_playlists()
        def on_playlists(result):
            callback(self.containers.playlists(result.items, title=L('TOP_PLAYLISTS')))

    def new_releases(self, callback):
        @self.sp.explore.new_releases()
        def on_albums(result):
            self.containers.albums(result.items, callback, title=L('NEW_RELEASES'))
