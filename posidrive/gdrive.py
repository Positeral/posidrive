import os
import json
import httplib2

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
from tabulate import tabulate

from posidrive.util import ObjectiveGroup, click, echo
from posidrive.util import programdir, pathtosave, sizesuffix, strdate


class AuthorizationError(click.ClickException):
    pass


# Maintainer's Google client secrets.
# For installed applications this is NOT confidential.
# See https://developers.google.com/identity/protocols/OAuth2#installed
client_config = {
    'installed': {
        'client_id': '757588180354-emk2okb1kdvh1khc0gg44tub9k21daeo.apps.googleusercontent.com',
        'project_id': 'arthurgdriveutility',
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
        'client_secret': 'smmJ618QmJyjF5WPgcStqUBN',
        'redirect_uris': [
            'urn:ietf:wg:oauth:2.0:oob',
            'http://localhost'
        ]
    }
}

class GoogleDrive:
    def __init__(self, folder, credentials_path=None):
        self.cli.bind_class_instance(self)

        self.service = None
        self.current_folder_id = None
        self.current_folder_name = folder
        
        if credentials_path:
            self.credentials_path = os.path.expanduser(credentials_path)
        else:
            self.credentials_path = programdir('.pgdcredentials')

    def initialize(self, force=False):
        if not force and self.service:
            return

        credentials = self.get_credentials()

        if not credentials:
            raise AuthorizationError('Not authorized (credentials absent)')

        if not credentials.valid:
            if credentials.expired:
                if credentials.refresh_token:
                    credentials.refresh(Request())
                    self.put_credentials(credentials)
                else:
                    raise AuthorizationError('Not authorized (credentials expired)')
            else:
                raise AuthorizationError('Not authorized (credentials invalid)')

        try:
            self.service = build('drive', 'v3', credentials=credentials)
        except httplib2.ServerNotFoundError:
            raise AuthorizationError('Not authorized (offline)')

    def get_credentials(self, path=None):
        '''
        '''
        try:
            path = path or self.credentials_path
            return Credentials.from_authorized_user_file(path)
        except FileNotFoundError:
            return None

    def put_credentials(self, credentials, path=None):
        '''
        '''
        path = path or self.credentials_path

        with open(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600), 'w') as f:
            f.write(credentials.to_json())

        return path

    def get_limits(self):
        fields = 'storageQuota(limit,usage)'
        response = self.service.about().get(fields=fields).execute()

        return {
            'limit': int(response['storageQuota']['limit']),
            'usage': int(response['storageQuota']['usage']),
        }

    def get_account(self):
        fields = 'user(emailAddress)'
        response = self.service.about().get(fields=fields).execute()

        return {
            'email': response['user']['emailAddress']
        }
    
    def set_folder(self, name):
        q = (
            "name='{name}' and "
            "mimeType='application/vnd.google-apps.folder' and "
            "trashed=false"
        ).format(name=name.replace("'", r"\'"))

        fields = 'files(id)'
        response = self.service.files().list(pageSize=1, fields=fields, q=q).execute()
        items = response.get('files', [])

        if items:
            return items[0]['id']
        
        # Folder doesn't not exists, create it
        body = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        response = self.service.files().create(body=body, fields='id').execute()
        return response['id']

    def set_current_folder(self, name=None):
        '''Return current folder ID on Google Drive.
        if folder doesn't exist on Google Drive, it will be created and set.
        '''
        name = name or self.current_folder_name

        if name != self.current_folder_name or not self.current_folder_id:
            self.current_folder_id = self.set_folder(name)
            self.current_folder_name = name

        return self.current_folder_id

    def get_files(self, folder_id=None, count=999):
        if not folder_id:
            folder_id = self.set_current_folder()

        q = (
            "mimeType != 'application/vnd.google-apps.folder' and "
            "'{folder_id}' in parents and trashed=false"
        ).format(folder_id=folder_id)

        fields  = 'files(id,name,size,createdTime)'
        request = self.service.files().list(pageSize=count,
                                            orderBy='createdTime',
                                            fields=fields,
                                            q=q)
        response = request.execute()
        return response.get('files', [])
    
    def upload(self, path, name=None, parents=None, chunksize=1048576, callback=None):
        name = name or os.path.split(path)[1]
        parents = parents or [self.set_current_folder()]
        callback = callback or (lambda *args: None)
        chunksize = ((chunksize + 262144 - 1) // 262144) * 262144 # Align to 256 Kb

        body = {
            'name': name,
            'parents': parents
        }

        media = MediaFileUpload(path,
                                mimetype='application/octet-stream',
                                chunksize=chunksize,
                                resumable=True)
        
        request = self.service.files().create(body=body, media_body=media)
        response = None

        while not response:
            status, response = request.next_chunk(num_retries=1)

            if status:
                callback(self, status)

        return response['id']

    def download(self, file_id, path, chunksize=1048576, callback=None):
        callback = callback or (lambda *args: None)
        chunksize = ((chunksize + 262144 - 1) // 262144) * 262144 # Align to 256 Kb

        with open(path, 'wb') as f:
            request = self.service.files().get_media(fileId=file_id)
            downloader = MediaIoBaseDownload(f, request, chunksize=chunksize)
            done = False

            while not done:
                status, done = downloader.next_chunk(num_retries=1)
                callback(self, downloader, status)

    @click.group(cls=ObjectiveGroup)
    def cli(self):
        pass

    @cli.exception_handler()
    def exception(self, e):
        print('EXCEPTION:', e)
        return True

    @cli.command('auth', replacement=False)
    @click.option('--scope', multiple=True, default=['drive.file'])
    def cmd_auth(self, scope=['drive.file']):
        '''Authorize Google account and save credentials
        '''
        prefix = 'https://www.googleapis.com/auth/'
        scope = list(map(prefix.__add__, scope))
        flow = InstalledAppFlow.from_client_config(client_config, scope)
        credentials = flow.run_console()
        path = self.put_credentials(credentials)
        echo(f'Credentials saved to {path}')

    @cli.command('status', replacement=False)
    def cmd_status(self):
        '''Show common information
        '''

        rows = [
            ('Service:', 'Google Drive'),
            ('Current remote folder:', self.current_folder_name),
            ('Credentials file:', self.credentials_path)
        ]

        try:
            self.initialize()
        except AuthorizationError as e:
            rows.append(('Authorization:', e.message))
        else:
            rows.append(('Authorization:', 'Authorized'))

            limits  = self.get_limits()
            account = self.get_account()
            rows.append(('Account:', account['email']))
            rows.append(('Usage:', sizesuffix(limits['usage'])))
            rows.append(('Limit:', sizesuffix(limits['limit'])))

        echo(tabulate(rows, tablefmt='plain'))
    
    @cli.command('list', replacement=False)
    def cmd_list(self):
        '''Show files in Google Drive active folder
        '''
        self.initialize()
        rows = []

        for f in self.get_files():
            created = strdate(f['createdTime'])
            size = sizesuffix(int(f['size']))
            rows.append((created, f['id'], f['name'], size))

        headers = ['Created', 'ID', 'Name', 'Size']
        echo(tabulate(rows, headers, tablefmt='plain'))

    @cli.command(name='upload', replacement=False)
    @click.argument('path')
    @click.argument('name', required=False)
    def cmd_upload(self, path, name=None):
        '''Upload file to Google Drive current folder
        '''
        self.initialize()

        echo('Uploading', path)

        def callback(self, status):
            echo(f'Upload {int(status.progress() * 100)}%')

        chunksize = os.path.getsize(path) // 10
        self.upload(path, name, chunksize=chunksize, callback=callback)
        echo('Done.')

    @cli.command('download', replacement=False)
    @click.argument('file_id')
    @click.argument('path', required=False)
    def cmd_download(self, file_id, path=None):
        '''Download file from Google Drive by ID
        '''
        self.initialize()

        request = self.service.files().get(fileId=file_id, fields='name,size')
        info = request.execute()

        path = pathtosave(info['name'], path)
        chunksize = int(info['size']) / 10

        if path and info['name'] != path:
            echo(f'Downloading {info["name"]} to {path}')
        else:
            echo(f'Downloading {info["name"]}')

        def callback(self, downloader, status):
            echo(f'Download {int(status.progress() * 100)}%')

        self.download(file_id, path, chunksize, callback)




