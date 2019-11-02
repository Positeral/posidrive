import os
from setuptools import setup, find_packages

scriptdir = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(scriptdir, 'requirements.txt')) as f:
    requirements = f.read().splitlines()

with open(os.path.join(scriptdir, 'README.md')) as f:
    long_description = f.read()

setup(name='posidrive',
      packages=find_packages(),
      version='0.0.2',
      license='BSD License',
      author='Arthur Goncharuk',
      author_email='af3.inet@gmail.com',
      long_description=long_description,
      long_description_content_type='text/markdown',
      classifiers=[
          'Intended Audience :: Developers',
          'License :: OSI Approved :: BSD License',
          'Programming Language :: Python',
          'Programming Language :: Python :: Implementation :: CPython'
          'Topic :: Software Development :: Libraries',
      ],
      install_requires=requirements,
      zip_safe=False
)
