from __future__ import print_function

import os
import sys
import functools
import warnings
import argparse

import click
import httplib2

from datetime import datetime
from tabulate import tabulate
from apiclient import discovery
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from oauth2client.client import OAuth2WebServerFlow
from googleapiclient.errors import HttpError


# Maintainer's Google application.
# For installed application client secret is NOT confidential.
# See https://developers.google.com/identity/protocols/OAuth2#installed
GDRIVE_CLIENT_ID     = '757588180354-emk2okb1kdvh1khc0gg44tub9k21daeo.apps.googleusercontent.com'
GDRIVE_CLIENT_SECRET = 'smmJ618QmJyjF5WPgcStqUBN'
GDRIVE_CLIENT_SCOPE  = 'https://www.googleapis.com/auth/drive.file'


def programdir(*p):
    '''
    Returns absolute path to current program directory
    with joining *p.
    '''
    dirpath = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(dirpath, *p)


def savepath(filename, path=None):
    '''
    Returns path for save file with expand ~.
    If path is directory, join it filename.
    '''
    if path:
        path = os.path.expanduser(path)

        if os.path.isdir(path):
            return os.path.join(path, filename)
        else:
            return path
    else:
        return filename


def rfc3339(t):
    '''
    Transform dense RFC3339 to more readable format
    '''
    d = datetime.strptime(t, '%Y-%m-%dT%H:%M:%S.%fZ')
    return d.strftime('%Y-%m-%d %H:%M:%S')


def methodcaller(method):
    '''
    Just method(), no more.
    Returns function that wraps method, because we cannot set
    custom attributes to bound instance methods.
    '''
    @functools.wraps(method)
    def caller(*args, **kwargs):
        return method(*args, **kwargs)

    return caller


class UnauthorizedError(click.ClickException):
    pass


class Cli(object):
    def __init__(self):
        self.cli = click.group()(self.cli)

        for m in dir(self):
            if hasattr(getattr(self, m), 'cli_command_kwargs'):
                method = methodcaller(getattr(self, m))
                self.cli.command(**method.cli_command_kwargs)(method)
    
    def cli(self):
        pass

    @staticmethod
    def method_command(**kwargs):
        def decorator(method):
            method.cli_command_kwargs = kwargs
            return method

        return decorator

    @staticmethod
    def method_argument(*args, **kwargs):
        def decorator(method):
            return click.argument(*args, **kwargs)(method)

        return decorator


class GoogleDrive(Cli):
    def __init__(self, folder, credentials=None):
        super(GoogleDrive, self).__init__()

        self.service = None
        self.folder = folder

        if credentials:
            self.credentials_path = os.path.expand(credentials)
        else:
            self.credentials_path = programdir('.gposidrive')

    @Cli.method_command(name='status')
    def cmd_status(self):
        '''
        Show common information
        '''
        rows = [
            ('Default remote folder:', self.folder),
            ('Credentials file:', self.credentials_path)
        ]

        try:
            self.initialize()
        except UnauthorizedError as e:
            rows.append(('Authorization:', e.message))
        else:
            rows.append(('Authorization:', 'Authorized'))

        print(tabulate(rows, tablefmt='plain'))

    @Cli.method_command(name='auth')
    def cmd_auth(self):
        '''
        Authorize Google account and save credentials
        '''
        flags = argparse.Namespace()
        flags.logging_level = 'ERROR'
        flags.noauth_local_webserver = True
        
        storage = Storage(self.credentials_path)
        flow = OAuth2WebServerFlow(GDRIVE_CLIENT_ID,
                                   GDRIVE_CLIENT_SECRET,
                                   GDRIVE_CLIENT_SCOPE)
        tools.run_flow(flow, storage, flags)

    @Cli.method_command(name='list')
    def cmd_list(self):
        '''
        Show files in Google Drive active folder
        '''
        self.initialize()
        rows = []
        
        for f in self.fetchfiles():
            created = rfc3339(f['createdTime'])
            rows.append((created, f['id'], f['name'], f['size']))

        headers = ['Created', 'ID', 'Name', 'Size']
        print(tabulate(rows, headers, tablefmt='plain'))
            
    @Cli.method_command(name='download')
    @Cli.method_argument('file_id')
    @Cli.method_argument('path', required=False)
    def cmd_download(self, file_id, path=None):
        '''
        Download file from Google Drive by ID
        '''
        self.initialize()

        request = self.service.files().get(fileId=file_id,
                                           fields='name,size')
        try:
            info = request.execute()
        except HttpError as e:
            if e.resp.get('status', '404') != '404':
                raise

            print('File not found')
            return

        path = savepath(info['name'], path)
        chunksize = int(info['size']) / 10

        if chunksize < 1024*100:
            chunksize = 1024*100

        if path and info['name'] != path:
            print('Downloading %s to %s' % (info['name'], path))
        else:
            print('Downloading %s' % (info['name']))

        def callback(self, downloader, status):
            print('Download %d%%' % int(status.progress() * 100))

        self.download(file_id, path, chunksize, callback)

    @Cli.method_command(name='upload')
    @Cli.method_argument('path')
    @Cli.method_argument('name', required=False)
    def cmd_upload(self, path, name=''):
        '''
        Upload file to Google Drive active folder
        '''
        self.initialize()
        print(path)
    
    @Cli.method_command(name='delete')
    @Cli.method_argument('file_id')
    def cmd_delete(self, file_id):
        '''
        Delete file by ID
        '''
        self.initialize()
        print(file_id)

    def get_credentials(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            storage = Storage(self.credentials_path)
            return storage.get()
    
    def initialize(self):
        credentials = self.get_credentials()

        if not credentials:
            raise UnauthorizedError('Not authorized (credentials absent)')

        if credentials.invalid:
            raise UnauthorizedError('Not authorized (credentials invalid)')
        
        try:
            http = credentials.authorize(httplib2.Http())
            self.service = discovery.build('drive', 'v3', http=http)
        except httplib2.ServerNotFoundError:
            raise UnauthorizedError('Not authorized (offline)')

        return credentials
        
    def fetchfiles(self, folder_id=None, count=999):
        if not folder_id:
            folder_id = self.setfolder(self.folder)
        
        q = "mimeType != 'application/vnd.google-apps.folder' and " \
            "'{folder_id}' in parents and " \
            "trashed=false".format(folder_id=folder_id)

        fields  = 'files(id,name,size,createdTime)'
        request = self.service.files().list(pageSize=count,
                                            orderBy='createdTime',
                                            fields=fields,
                                            q=q)
        try:
            response = request.execute()
            return response.get('files', [])
        except HttpError as e:
            if e.resp.get('status', '404') != '404':
                raise

            return []

    def setfolder(self, name):
        q = "name='%s' and " \
            "mimeType='application/vnd.google-apps.folder' and " \
            "trashed=false" % name.replace("'", r"\'")
        
        results = self.service.files().list(pageSize=1, fields="files(id)", q=q).execute()
        items = results.get('files', [])

        if items:
            return items[0]['id']
        
        # targed folder not exists, create it
        body = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        file = self.service.files().create(body=body, fields='id').execute()
        return file['id']

    def upload(self, path, name, parents=[]):
        body = {
            'name': name,
            'parents': parents
        }

        media = MediaFileUpload(path,
                                mimetype='application/octet-stream',
                                resumable=True)
        
        result = self.service.files().create(body=body,
                                             media_body=media,
                                             fields='id').execute()
        return result

    def download(self, file_id, path, chunksize=1048576, callback=None):
        callback = callback or (lambda *args: None)

        with open(path, 'wb') as f:
            request = self.service.files().get_media(fileId=file_id)
            downloader = MediaIoBaseDownload(f, request, chunksize=chunksize)
            done = False

            while not done:
                status, done = downloader.next_chunk(num_retries=1)
                callback(self, downloader, status)



