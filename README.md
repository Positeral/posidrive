# $ posidrive

This Python library aims to make easier use Google Drive to backup/restore your data.

# Installation
```bash
pip install posidrive
```
Install latest development version:
```
pip install git+https://github.com/Positeral/posidrive
```
# Quickstart
Let's write a simple `gd.py` script:
```python
from posidrive.gdrive import GoogleDrive

gdrive = GoogleDrive(folder='test')
gdrive.cli()
```
Run it from command line:
```bash
python gd.py
```
```
Usage: gd.py [OPTIONS] COMMAND [ARGS]...

Options:
  --debug  Enable debug mode.
  --help   Show this message and exit.

Commands:
  auth      Authorize Google account and save credentials.
  status    Show common information.
  list      Show files in current remote folder.
  upload    Upload file to current remote folder.
  download  Download file by ID.
  delete    Delete file by ID.
  clear     Delete all files in folder.
```
```bash
python gd.py status
```
```
Service:               Google Drive
Current remote folder: test
Credentials file:      /home/arthur/projects/posidrive/.pgdcredentials
Authorization:         Not authorized (credentials absent)
```
Let's authorize the application now:
```bash
python gd.py auth
```
```
Please visit this URL to authorize this application: https://[...]
Enter the authorization code: 
```
Follow the link, authorize the application and paste the resulting code. By default, `posidrive` request you the minimal permissions. Сheck the status:
```bash
python gd.py status
```
```
Service:               Google Drive
Current remote folder: test
Credentials file:      /home/arthur/projects/posidrive/.pgdcredentials
Authorization:         Authorized
Account:               af3.inet@gmail.com
Usage:                 11.2G
Limit:                 15G
```
Good! Now you can use `list`, `upload`, `download`, `delete` or `clear`. Don't forget that every command have `--help` option.

# Custom scripts
The following script make a compressed archive and upload it to Google Drive. Then, it will delete all remote files except the last three:
```python
import os
import click
import tarfile

from posidrive.gdrive import GoogleDrive


class MyGoogleDrive(GoogleDrive):
    @GoogleDrive.cli.command('archive')
    @click.argument('path', required=True)
    def cmd_archive(self, path):
        '''Archive directory/file'''
        self.initialize()

        tarname = os.path.basename(path)+'.tar.lzma'
        tarpath = tarname

        tar = tarfile.open(tarpath, 'w:xz')
        tar.add(path)
        tar.close()

        self.cmd_upload(tarpath, tarname)
        self.cmd_clear(keep_last=3, yes=True)


gdrive = MyGoogleDrive(folder='test')
gdrive.cli()

