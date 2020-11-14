import os
import httplib2

from operator import itemgetter
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

from posidrive.util import ObjectiveGroup, click, echo, table
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
    def __init__(self, *, folder, credentials_path=None):
        self.cli.bind_class_instance(self)

        self.service = None
        self.current_folder_id = None
        self.current_folder_name = folder
        
        if credentials_path:
            self.credentials_path = os.path.expanduser(credentials_path)
        else:
            self.credentials_path = programdir('.pgdcredentials')

    def initialize(self, force=False):
        '''Initialize the Google Drive service.
        '''
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
        except httplib2.ServerNotFoundError as e:
            raise AuthorizationError('Not authorized (offline)') from e

    def get_credentials(self, path=None):
        '''Read JSON-encoded credentials from file.
        '''
        try:
            path = path or self.credentials_path
            return Credentials.from_authorized_user_file(path)
        except FileNotFoundError:
            return None

    def put_credentials(self, credentials, path=None):
        '''Save credentials to file as JSON.
        '''
        path = path or self.credentials_path

        with open(path, 'w') as f:
            os.chmod(path, 0o600)
            f.write(credentials.to_json())

        return path

    def get_limits(self):
        '''Get drive usage and limit.
        '''
        fields = 'storageQuota(limit,usage)'
        response = self.service.about().get(fields=fields).execute()

        return {
            'limit': int(response['storageQuota']['limit']),
            'usage': int(response['storageQuota']['usage']),
        }

    def get_account(self):
        '''Get account info
        '''
        fields = 'user(emailAddress)'
        response = self.service.about().get(fields=fields).execute()

        return {
            'email': response['user']['emailAddress']
        }
    
    def set_folder(self, name):
        '''Create remote folder (or return an existing one) and return its ID
        '''
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
        '''Return current folder. If folder doesn't exist, create it first.
        '''
        name = name or self.current_folder_name

        if name != self.current_folder_name or not self.current_folder_id:
            self.current_folder_id = self.set_folder(name)
            self.current_folder_name = name

        return self.current_folder_id

    def get_files(self, folder_id=None, count=999):
        '''Get files list. If folder_id is omitted, use current folder.
        '''
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
    
    def upload(self, path, name=None, parents=None, chunksize=0, callback=None):
        '''Upload file.
        '''
        name = name or os.path.split(path)[1]
        parents = parents or [self.set_current_folder()]
        callback = callback or (lambda *args: None)
         # Align to 256 Kb
        chunksize = (((chunksize or 1048576) + 262144 - 1) // 262144) * 262144

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

    def download(self, file_id, path, chunksize=0, callback=None):
        '''Download file by ID.

        :param file_id: File ID.
        :param path: Destination path.
        :param chunksize: File will be uploaded in chunks of this many bytes.
                          The value will always be aligned to 256 Kb.
                          If the value is 0, it will be set to 1048576 (256 Kb).
        :param callback: An callback to be called on every transferred chunk.
        '''
        callback = callback or (lambda *args: None)
         # Align to 256 Kb
        chunksize = (((chunksize or 1048576) + 262144 - 1) // 262144) * 262144

        with open(path, 'wb') as f:
            request = self.service.files().get_media(fileId=file_id)
            downloader = MediaIoBaseDownload(f, request, chunksize=chunksize)
            done = False

            while not done:
                status, done = downloader.next_chunk(num_retries=1)
                callback(self, downloader, status)

    def delete(self, file_id):
        '''Delete file by ID.

        :param file_id: The file ID.
        '''
        request = self.service.files().delete(fileId=file_id)
        request.execute()

    def clear(self, folder_id=None, keep_first=0, keep_last=0, before=None):
        '''Delete all files in folder.

        :param folder_id: Remote folder ID. By default current folder will be used.
        :param keep_first: Do not delete N first files.
        :param keep_last: Do not delete N last files.
        :param before: A callback to be called BEFORE delete of the form callback(files).
                       If callback return a non-None value, abort execution.
        :return: The number of deleted files.
        '''
        files = self.get_files(folder_id=folder_id)
        files = sorted(files, key=itemgetter('createdTime'))

        if keep_first:
            del files[:keep_first]

        if keep_last:
            del files[-keep_last:]

        if not files:
            return 0

        if before:
            value = before(files)

            if value is not None:
                return value

        count = 0

        def callback(request_id, response, exception):
            nonlocal count
            if exception:
                if isinstance(exception, HttpError):
                    if exception.resp.get('status') == '404':
                        return

                raise exception
            else:
                count += 1

        batch = self.service.new_batch_http_request(callback=callback)

        for f in files:
            batch.add(self.service.files().delete(fileId=f['id']))

        batch.execute()
        return count

    @click.group(cls=ObjectiveGroup)
    @click.option('--debug', is_flag=True, help='Enable debug mode.')
    def cli(self, debug=False):
        pass

    @cli.exception_handler()
    def cli_exception(self, ctx, e):
        if ctx.params.get('debug'):
            return

        if isinstance(e, HttpError):
            echo(e._get_reason())
        else:
            echo(e)

        ctx.abort()

    @cli.command('auth', replacement=False)
    @click.option('--scope', multiple=True, default=['drive.file'], help='Permissions scope')
    def cmd_auth(self, scope=('drive.file',)):
        '''Authorize Google account and save credentials.
        '''
        prefix = 'https://www.googleapis.com/auth/'
        scope = list(map(prefix.__add__, scope))
        flow = InstalledAppFlow.from_client_config(client_config, scope)
        credentials = flow.run_console()
        path = self.put_credentials(credentials)
        echo(f'Credentials saved to {path}')

    @cli.command('status', replacement=False)
    def cmd_status(self):
        '''Show common information.
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

        echo(table(rows))
    
    @cli.command('list', replacement=False)
    def cmd_list(self):
        '''Show files in current remote folder.
        '''
        self.initialize()
        rows = []

        for f in self.get_files():
            created = strdate(f['createdTime'])
            size = sizesuffix(int(f['size']))
            rows.append((created, f['id'], size, f['name']))

        if rows:
            rows.insert(0, ['Created', 'ID', 'Size', 'Name'])
            echo(table(rows, colstransform={2: str.rjust}))
        else:
            echo('No files')

    @cli.command(name='upload', replacement=False)
    @click.argument('path')
    @click.argument('name', required=False)
    def cmd_upload(self, path, name=None):
        '''Upload file to current remote folder.
        '''
        self.initialize()

        echo(f'Uploading {path}')

        def callback(self, status):
            echo(f'{int(status.progress() * 100)}% ', nl=False)

        chunksize = os.path.getsize(path) // 10
        self.upload(path, name, chunksize=chunksize, callback=callback)
        echo('Done.')

    @cli.command('download', replacement=False)
    @click.argument('file_id')
    @click.argument('path', required=False)
    def cmd_download(self, file_id, path=None):
        '''Download file by ID.
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
            echo(f'{int(status.progress() * 100)}% ', nl=False)

        self.download(file_id, path, chunksize, callback)
        echo('Done.')

    @cli.command('delete', replacement=False)
    @click.argument('file_id')
    def cmd_delete(self, file_id):
        '''Delete file by ID.
        '''
        self.initialize()
        self.delete(file_id)
        echo('Ok.')

    @cli.command('clear', replacement=False)
    @click.argument('folder_id', required=False)
    @click.option('--keep-first', default=0, help='Do not delete N first files.')
    @click.option('--keep-last', default=0, help='Do not delete N last files.')
    @click.option('--yes', is_flag=True, help='Automatic yes to prompts.')
    def cmd_clear(self, folder_id=None, keep_first=0, keep_last=0, yes=False):
        '''Delete all files in folder. By default, the current folder will be used.
        '''
        self.initialize()

        def before(files):
            rows = [(f['name'], sizesuffix(int(f['size']))) for f in files]
            echo(f'The following {len(files)} files will be deleted:')
            echo(table(rows))

            if not yes:
                click.confirm('Do you want to continue?', abort=True)

        deleted = self.clear(folder_id=folder_id,
                             keep_first=keep_first,
                             keep_last=keep_last,
                             before=before)

        if deleted:
            echo('Done')
        else:
            echo('Nothing to delete')
