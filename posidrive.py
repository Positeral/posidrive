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
from googleapiclient.http import MediaFileUpload
from oauth2client.client import OAuth2WebServerFlow
from googleapiclient.errors import HttpError


CLIENT_ID     = '757588180354-emk2okb1kdvh1khc0gg44tub9k21daeo.apps.googleusercontent.com'
CLIENT_SECRET = 'smmJ618QmJyjF5WPgcStqUBN'
CLIENT_SCOPE  = 'https://www.googleapis.com/auth/drive.file'


def programdir(*p):
    '''
    Returns absolute path to current program directory
    with joining *p.
    '''
    dirpath = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(dirpath, *p)


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
        flow = OAuth2WebServerFlow(CLIENT_ID, CLIENT_SECRET, scope=CLIENT_SCOPE)
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
    def cmd_download(self, file_id):
        '''
        Download file from Google Drive by ID
        '''
        self.initialize()
        print(file_id)

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




