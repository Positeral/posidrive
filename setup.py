import os
import re
from setuptools import setup, find_packages

scriptdir = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(scriptdir, 'requirements.txt')) as f:
    requirements = f.read().splitlines()

with open(os.path.join(scriptdir, 'README.md')) as f:
    long_description = f.read()

with open(os.path.join(scriptdir, 'posidrive/__init__.py')) as f:
    version = re.search(r"__version__\s*=\s*'(.*?)'", f.read()).group(1)

setup(name='posidrive',
      packages=find_packages(),
      version=version,
      license='BSD License',
      author='Arthur Goncharuk',
      author_email='af3.inet@gmail.com',
      long_description=long_description,
      long_description_content_type='text/markdown',
      url='https://github.com/Positeral/posidrive',
      install_requires=requirements,
      python_requires='>=3.6',
      zip_safe=False,
      classifiers=[
          'Development Status :: 3 - Alpha',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: BSD License',
          "Operating System :: OS Independent",
          "Programming Language :: Python :: 3",
          'Topic :: Software Development :: Libraries',
          'Topic :: Internet :: WWW/HTTP',
          'Topic :: Utilities'
      ]
)
